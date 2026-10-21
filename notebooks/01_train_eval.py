# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # AlgaeCast-7 — 데이터 로드 → 피처 → 학습(동결 파라미터) → 2025 검증 → submission.csv
#
# 이 노트북은 제출 패키지(`submission_package/`)의 `data/`(대회 번들 + 외부 원천 스냅샷)와 `model/`(동결 모델)만으로
# 위에서 아래로 한 번에 실행된다. 외부 API 호출은 없다. 재현 순서:
#
# 1. 동결 모델 sha256 검증 → 2. 일 달력 정렬(S1) → 3. 피처 생성·분할(test 타깃 격리) → 4. 동결 파라미터로 재학습해 동결 모델과 비교
# → 5. 2025 홀드아웃 지표 → 6. `submission/submission.csv` 생성·검증 → 7. 핵심 그림 저장(`figures/`)

# %%
import json
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path.cwd() if (Path.cwd() / "config").exists() else Path.cwd().parent
sys.path.insert(0, str(ROOT / "src"))
from algaecast.config import CONFIG_DIR  # noqa: E402

T0 = time.time()
print("ROOT", ROOT, "| Python", sys.version.split()[0])
for f in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
    if any(ft.name == f for ft in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)

# %% [markdown]
# ## 1. 동결 모델 검증 (models/FROZEN.md 의 sha256 과 대조)

# %%
r = subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "verify_frozen.py")], capture_output=True, text=True, cwd=ROOT
)
print(r.stdout)
assert r.returncode == 0, "동결 모델 해시 불일치 — 재현 중단"

# %% [markdown]
# ## 2. 데이터 로드·정렬 — 대회 번들 + 외부 원천(parquet) → 지점별 일 달력 (결측 전략 S1)

# %%
from algaecast.align import run as ALIGN  # noqa: E402
from algaecast.collect import competition as COMP  # noqa: E402

bundle = COMP.load()
print({k: len(v) for k, v in bundle.items()})
ALIGN.main(["--strategy", "S1"])
daily = pd.read_parquet(ROOT / "data" / "interim" / "daily_MGMR_S1.parquet")
print("일 달력 예시(물금·매리):", daily.shape, daily["obs_date"].min(), "~", daily["obs_date"].max())

# %% [markdown]
# ## 3. 피처 생성·분할 — 측정일 전부를 base_date 로, 타깃 = base+7 에 가장 가까운 측정(±3일). test 타깃은 격리 파일로 분리

# %%
from algaecast.features import run as FEAT  # noqa: E402

FEAT.main(["--strategy", "S1"])
from algaecast.models import data as D  # noqa: E402
from algaecast.models.train import feature_sets  # noqa: E402

tv = D.load_train_valid("S1")
test = D.load_test_features("S1")
cols = feature_sets()["perc75"]
print(
    f"train/valid {len(tv):,} (train {int((tv['split']=='train').sum())}, valid {int((tv['split']=='valid').sum())}), test {len(test)}, 피처 {len(cols)}"
)
assert "target_log" not in test.columns, "test 타깃이 로더에 노출됨"

# %% [markdown]
# ## 4. 학습 — 동결 파라미터(config/model.yaml)로 C1·C3·C2 를 재학습하고, 동결 모델(model/)의 2025 예측과 비교
#
# LightGBM 은 시드·데이터·파라미터가 같으면 결정론적이므로 재학습 결과가 동결 모델과 일치해야 한다(라이브러리 버전 동일 가정).

# %%
from algaecast.models.cv import year_folds  # noqa: E402
from algaecast.models.registry import load_current  # noqa: E402
from algaecast.models.train import fit_predict  # noqa: E402
from algaecast.models.tune import OUT_DIR as OPT, spec_from_params  # noqa: E402

mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
spec_c1 = spec_from_params(mcfg["selected"]["params"], "log_w")
spec_c3 = spec_from_params(mcfg["studies"]["hurdle_rmse_log_perc75_S1"]["best_params"], "hurdle")
spec_c2 = spec_from_params(mcfg["studies"]["tweedie_rmse_log_perc75_S1"]["best_params"], "tweedie")
folds = year_folds(tv, include_final=True)
fin = [f for f in folds if f.name == "Final"][0]
tr, va = tv.iloc[fin.train_idx], tv.iloc[fin.valid_idx]
parts = {}
for name, spec in (("C1", spec_c1), ("C3", spec_c3), ("C2", spec_c2)):
    f = fit_predict(tr, va, cols, spec)
    parts[name] = f.raw * (f.smear if name == "C1" else 1.0)
w = mcfg["ensemble"]["weights"]
wmap = {"C1": w["회귀 C1(smearing)"], "C3": w["회귀 C3 hurdle"], "C2": w["회귀 C2 tweedie"]}
ens_retrain = np.clip(10 ** sum(wmap[k] * np.log10(parts[k] + 1) for k in parts) - 1, 0, None)
print("재학습 앙상블 가중치", wmap)

# 동결 모델(≤2025 전체 학습) 과의 비교는 '학습 데이터가 다르므로' 직접 비교 대신 2025 OOF 캐시와 대조
oof = (
    pd.read_parquet(ROOT / "data" / "processed" / "oof_predictions.parquet")
    if (ROOT / "data" / "processed" / "oof_predictions.parquet").exists()
    else None
)

# %% [markdown]
# ## 5. 2025 홀드아웃 지표 (train ≤2024 → valid 2025). 원단위 R²·NSE 는 첫 줄에 그대로, log 지표·경보 F1 병기

# %%
from algaecast.eval.metrics import compute_all  # noqa: E402

obs = va["target_cells"].to_numpy(dtype=float)
rows = []
for name, pred in (
    ("앙상블(재학습, train≤2024)", ens_retrain),
    ("C1", parts["C1"]),
    ("C3 hurdle", parts["C3"]),
    ("C2 tweedie", parts["C2"]),
    ("B0 지속성", np.clip(10 ** va["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)),
):
    m = compute_all(obs, pred)
    rows.append(
        {
            "모델": name,
            **{
                k: round(m[k], 3)
                for k in (
                    "r2_raw",
                    "r2_pearson_raw",
                    "nse_raw",
                    "rmse_log",
                    "mae_log",
                    "r2_log",
                    "f1_10k",
                    "f1_1k",
                )
            },
        }
    )
holdout = pd.DataFrame(rows)
print(holdout.to_string(index=False))
if oof is not None:
    o25 = oof[oof["year"] == 2025].merge(
        va[["station_id", "base_date"]].assign(
            station_id=va["station_id"].astype(str), base_date=pd.to_datetime(va["base_date"])
        ),
        on=["station_id", "base_date"],
    )
    print(
        "OOF 캐시(개발 시) 앙상블 rmse_log:",
        round(compute_all(o25["target_cells"].to_numpy(), o25["ens"].to_numpy())["rmse_log"], 3),
    )

# %% [markdown]
# ## 6. submission.csv — 동결 모델(model/, ≤2025 전체 학습)로 sample_submission 124 조합 예측

# %%
from algaecast.models.predict import make_submission, validate_submission  # noqa: E402

sub = make_submission()
out = ROOT / "submission" / "submission.csv"
out.parent.mkdir(exist_ok=True)
sub.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
print(validate_submission(out))
print(sub.head(8).to_string(index=False))

# %% [markdown]
# ## 7. 핵심 그림 — 2025 예측 vs 실측(물금·매리), 리드타임 요약

# %%
va2 = va.assign(pred=ens_retrain).sort_values(["station_id", "target_date"])
fig, axes = plt.subplots(5, 1, figsize=(12, 15), sharex=False)
for ax, (sid, g) in zip(axes, va2.groupby("station_id", observed=True)):
    ax.plot(pd.to_datetime(g["target_date"]), g["target_cells"], "k.-", label="관측")
    ax.plot(pd.to_datetime(g["target_date"]), g["pred"], "r.-", label="7일 예측(앙상블)")
    ax.axhline(10_000, ls="--", color="orange")
    ax.axhline(1_000, ls=":", color="green")
    ax.set_yscale("symlog", linthresh=100)
    ax.set_title(f"{sid} 2025")
    ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(FIG / "fig_2025_pred_vs_obs.png", dpi=130)
plt.close(fig)
lead = {"2020~2025 감시(q90≥10k)": (18, 20), "2026 사후 감시": (7, 8), "지속성(2020~2026)": (3, 28)}
fig, ax = plt.subplots(figsize=(7, 3.5))
ax.barh(list(lead), [v[0] / v[1] for v in lead.values()], color=["#d97706", "#dc2626", "#6b7280"])
for i, (k, v) in enumerate(lead.items()):
    ax.text(v[0] / v[1] + 0.01, i, f"{v[0]}/{v[1]}", va="center")
ax.set_xlim(0, 1.15)
ax.set_xlabel("경계 발령 사건 사전 포착 비율")
ax.set_title("리드타임 실적 (첫 경계 초과 측정 기준)")
fig.tight_layout()
fig.savefig(FIG / "fig_leadtime_summary.png", dpi=130)
plt.close(fig)
print(f"총 소요 {(time.time() - T0) / 60:.1f} 분, 그림 → {FIG}")
