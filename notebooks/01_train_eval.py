# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # AlgaeCast-7 — 데이터 로드 → 피처 → 학습(동결 파라미터) → 2025 검증 → submission.csv
#
# 이 노트북은 제출 패키지의 `data/`(대회 번들 + 외부 원천 스냅샷)와 `model/`(동결 모델)만으로
# 위에서 아래로 한 번에 실행된다. 외부 API 호출은 없다. 재현 순서:
#
# 1. 동결 모델 sha256 검증 → 2. 일 달력 정렬(S1) → 3. 피처 생성·분할(test 타깃 격리) + 상류 피처
# → 4. 동결 파라미터로 재학습(train ≤2024: T24 = 로그 앙상블 + 상류 피처 + 속별 구성원, 비교용 v1-fix = v1 구성)
# → 5. 2025 홀드아웃 지표(T24·v1-fix 나란히) → 6. `submission.csv`(패키지 루트, 동결 레지스트리 current = T24) 생성·검증
# → 7. 핵심 그림 저장(`figures/`)
#
# 제출·운영 모델 T24(2026-10-28, 운영사무국 답변 '학습은 24년까지'에 따른 사전등록 전환): v2.1(누수 수정판) 구성 그대로,
# 학습 = 대회 번들 eval_pairs.csv 의 split=train 정의 그대로(2,310행, 기준일 ≤2024-12-30, 이 중 5행은 목표일 2025-01-06).
# 구성: 로그 앙상블(C1 smearing·C3 hurdle·C2 tweedie, v1 하이퍼파라미터)
# + 낙동강 상류 지점 피처 5열(lag 0, 1단계) + 속별 구성원 cg(Microcystis + 나머지 3속, 부분별 log 회귀),
# log 공간 NNLS 가중치(2020~2024 CV OOF, 시드 42). 분류기·분위·CQR·운영점도 수정 피처로 다시 적합했다.
# 데이터로 계산한 상수는 기준일까지(as-of) 또는 학습기간 자료로만 쓴다(reports/experiments/FIX-v2.1/PREREG.md):
# 수위 편차 = 관측소별 직전 365일 평균 대비, 지점별 수온 임계 = 학습기간 측정만(폴드마다, 제출 모델 T24 ≤2024).
# 2025·2026 측정은 예측 시점의 입력(as-of 피처)으로만 쓴다(학습 아님). 2026 정답은 읽지 않는다
# (test 행은 피처만, 상류 피처는 원자료를 행의 기준일까지만 사용).
#
# 소요 시간: 약 20분(대부분 3단계 피처 생성, 8코어 CPU 기준, GPU 미사용). 실행 결과(출력)를 포함해 저장되어 있다.

# %%
import json
import subprocess
import sys
import time
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

warnings.filterwarnings("ignore", message="IProgress not found")  # tqdm 진행 막대 위젯 안내(결과와 무관)
# 정션·심볼릭 링크 경로에서도 algaecast.config 의 ROOT(resolve 된 실제 경로)와 맞도록 resolve
ROOT = (Path.cwd() if (Path.cwd() / "src").exists() else Path.cwd().parent).resolve()
sys.path.insert(0, str(ROOT / "src"))
from algaecast.config import CONFIG_DIR, MODELS_DIR, SUBMISSION_PATH  # noqa: E402

T0 = time.time()
print(
    "Python",
    sys.version.split()[0],
    "| 설정",
    CONFIG_DIR.relative_to(ROOT).as_posix(),
    "| 동결 모델",
    MODELS_DIR.relative_to(ROOT).as_posix(),
)
for f in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
    if any(ft.name == f for ft in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)

# %% [markdown]
# ## 1. 동결 모델 검증 (`model/FROZEN.md`(v1)·`FROZEN_v2.md`(v2)·`FROZEN_v2.1.md`(v2.1)·`FROZEN_T24.md`(T24, 제출) 의 sha256 과 대조)
#
# `verify_frozen.py` 는 동결 문서 표의 파일 해시를 확인하고, 레지스트리 current 가 가장 최근 동결 문서
# (`FROZEN_T24.md`)의 버전과 같은지도 확인한다. 제출·운영 모델 T24(회귀·분류기·분위) 파일은
# 반드시 있고 해시가 맞아야 한다. 제출 패키지에는 재현에 쓰지 않는 이력 모델(v1·v2·v1-fix·v2.1) 파일을
# 넣지 않았으므로, 그 행은 `model/HISTORY.md` 에 적힌 sha256 이 동결 문서와 같은지 확인해
# '패키지 미포함(이력, model/HISTORY.md)'으로 표시한다(저장소 `models/` 에서는 파일을 직접 대조).

# %%
from algaecast.models.registry import current_entry  # noqa: E402

FROZEN_DOC = next(
    MODELS_DIR / d
    for d in ("FROZEN_T24.md", "FROZEN_v2.1.md", "FROZEN_v2.md", "FROZEN.md")
    if (MODELS_DIR / d).exists()
)
print("동결 문서:", FROZEN_DOC.relative_to(ROOT).as_posix())
r = subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "verify_frozen.py")], capture_output=True, text=True, cwd=ROOT
)
print(r.stdout)
assert r.returncode == 0, "동결 모델 해시 불일치 — 재현 중단"
REG_ENTRY = current_entry("regression")
REG_KIND = REG_ENTRY["meta"].get("kind")
print("current 회귀:", REG_ENTRY["version"], REG_KIND, REG_ENTRY["meta"].get("model_name", ""))
if FROZEN_DOC.name in ("FROZEN_T24.md", "FROZEN_v2.1.md", "FROZEN_v2.md"):
    assert REG_KIND == "ensemble_v2", f"{FROZEN_DOC.name} 가 있는데 current 회귀가 v2 계열이 아님"

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
#
# v2 학습 프레임 = 학습·검증 행 중 기준일·목표일 ≤ 2025-12-31 + 상류 피처 5열(`features/upstream.py`, 행마다
# 그 행의 기준일까지의 조류 측정만 사용). test 행(2026 기준일)도 같은 함수로 계산한다.

# %%
from algaecast.features import run as FEAT  # noqa: E402

FEAT.main(["--strategy", "S1"])
from algaecast.features.upstream import UPSTREAM_COLS, build_upstream  # noqa: E402
from algaecast.models import data as D  # noqa: E402
from algaecast.models import v2 as V2  # noqa: E402
from algaecast.models.train import feature_sets  # noqa: E402

tv = D.load_train_valid("S1")
test = D.load_test_features("S1")
cols = feature_sets()["perc75"]
cfg_v2 = V2.config_v2()
tv2 = V2.load_training_frame(config=cfg_v2)  # v1 피처 + 상류 5열
test_up = build_upstream(test)
print(
    f"train/valid {len(tv):,} (train {int((tv['split']=='train').sum())}, valid {int((tv['split']=='valid').sum())}), test {len(test)}, 피처 v1 {len(cols)} / v2 {len(cfg_v2.cols)}"
)
print("v2 학습 프레임", len(tv2), "행, 목표일 최대", pd.to_datetime(tv2["target_date"]).max().date())
print("상류 피처 결측 비율(test):", test_up.isna().mean().round(3).to_dict())
assert "target_log" not in test.columns, "test 타깃이 로더에 노출됨"
assert (pd.to_datetime(tv2["target_date"]) <= pd.Timestamp("2025-12-31")).all()

# %% [markdown]
# ## 4. 학습 — 동결 파라미터로 train ≤2024 를 재학습해 2025 검증용 예측을 만든다
#
# - T24(제출 모델): C1·C3·C2 + 속별 cg, 피처 35열, 가중치 = 동결 레지스트리(meta.weights, v2.1 과 같음).
#   train ≤2024(대회 split=train 2,310행) 재학습이 곧 동결 T24 이므로, 레지스트리 모델의 2025 예측과 직접 대조한다.
# - v1-fix(비교용): v1 구성 C1·C3·C2, 피처 30열, 가중치 `model.yaml` ensemble(수정 피처로 다시 적합)
# - 학습 ≤2024 → 2025 검증이므로 지점별 수온 임계도 ≤2024 측정으로 계산한 값을 쓴다(폴드 규칙).
#
# LightGBM 은 시드·데이터·파라미터가 같으면 결정론적이므로 재학습 결과가 동결 모델과 일치해야 한다(라이브러리 버전 동일 가정).

# %%
from algaecast.features.constants import apply_site_thresholds  # noqa: E402
from algaecast.models.cv import fold_frames, year_folds  # noqa: E402
from algaecast.models.train import fit_predict  # noqa: E402
from algaecast.models.tune import spec_from_params  # noqa: E402

mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
spec_c1 = spec_from_params(mcfg["selected"]["params"], "log_w")
spec_c3 = spec_from_params(mcfg["studies"]["hurdle_rmse_log_perc75_S1"]["best_params"], "hurdle")
spec_c2 = spec_from_params(mcfg["studies"]["tweedie_rmse_log_perc75_S1"]["best_params"], "tweedie")
folds = year_folds(tv, include_final=True)
fin = [f for f in folds if f.name == "Final"][0]
tr, va = fold_frames(tv, fin)  # 학습 ≤2024 → 2025, 수온 임계 ≤2024
parts = {}
for name, spec in (("C1", spec_c1), ("C3", spec_c3), ("C2", spec_c2)):
    f = fit_predict(tr, va, cols, spec)
    parts[name] = f.raw * (f.smear if name == "C1" else 1.0)
w = mcfg["ensemble"]["weights"]
wmap = {"C1": w["회귀 C1(smearing)"], "C3": w["회귀 C3 hurdle"], "C2": w["회귀 C2 tweedie"]}
ens_retrain = np.clip(10 ** sum(wmap[k] * np.log10(parts[k] + 1) for k in parts) - 1, 0, None)
print("v1-fix 재학습 앙상블 가중치", wmap)

# T24: 동결 가중치(레지스트리) → train ≤2024(split=train) 로 구성원 재학습 → 2025 예측
if REG_KIND == "ensemble_v2":
    w_v2 = {k: float(v) for k, v in REG_ENTRY["meta"]["weights"].items()}
    w_src = f"동결 레지스트리 regression/{REG_ENTRY['version']}({REG_ENTRY['meta'].get('model_name', '')})"
else:
    w_v2 = V2.fit_weights(tv2, V2.SEED, cfg_v2)
    w_src = "동결 전 — 2020~2024 CV OOF NNLS 재계산"
tv2_24 = apply_site_thresholds(tv2, 2024)  # 학습 ≤2024 → 2025: 수온 임계 ≤2024
yrs = V2.years_of(tv2_24)
tr2, va2 = tv2_24[yrs <= 2024].reset_index(drop=True), tv2_24[yrs == 2025].reset_index(drop=True)
model_v2 = V2.fit_final(tr2, cfg_v2, weights=w_v2)
mem_v2 = model_v2.predict_members(va2)
ens_v2 = model_v2.predict(va2)
print("T24 가중치", {k: round(v, 4) for k, v in w_v2.items()}, "|", w_src)
# T24 학습 행 = 대회 번들 eval_pairs.csv split=train 그대로(5행은 목표일 2025-01-06)
_ep = bundle["eval_pairs"]
_k = lambda d: set(
    zip(
        d["station_id"].astype(str),
        pd.to_datetime(d["base_date"]).dt.date,
        pd.to_datetime(d["target_date"]).dt.date,
    )
)  # noqa: E731
assert len(tr2) == 2310 and _k(tr2) == _k(
    _ep[_ep["split"] == "train"]
), "T24 학습 행이 대회 split=train 과 다름"
print(
    "T24 학습 행",
    len(tr2),
    "= 대회 split=train, 목표일 2025 인 행:",
    int((pd.to_datetime(tr2["target_date"]).dt.year >= 2025).sum()),
)
assert (
    len(va2) == len(va)
    and (va2["station_id"].astype(str).to_numpy() == va["station_id"].astype(str).to_numpy()).all()
)

# 동결 T24(레지스트리)의 2025 예측과 재학습 결과를 직접 대조한다(같은 행·가중치·임계 → 최대차 0).
from algaecast.db.upload import predict_registry  # noqa: E402

_reg25 = predict_registry(va2.copy())["pred_cell_count"].to_numpy()
print("동결 T24 vs 재학습 2025 예측 최대 절대차:", float(np.nanmax(np.abs(_reg25 - ens_v2))))
assert float(np.nanmax(np.abs(_reg25 - ens_v2))) == 0.0, "재학습 결과가 동결 T24 와 다름"
# 개발 시 OOF 캐시(v2.1 구성 Final 폴드 = T24 와 같은 학습)와도 대조
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
    ("T24 앙상블(재학습 = 동결 T24, train≤2024)", ens_v2),
    ("v1-fix 앙상블(재학습, train≤2024)", ens_retrain),
    ("C1", parts["C1"]),
    ("C3 hurdle", parts["C3"]),
    ("C2 tweedie", parts["C2"]),
    ("T24 속별 cg", mem_v2["cg"]),
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
    oof["base_date"] = pd.to_datetime(oof["base_date"])
    o25 = oof[oof["year"] == 2025].merge(
        va[["station_id", "base_date"]].assign(
            station_id=va["station_id"].astype(str), base_date=pd.to_datetime(va["base_date"])
        ),
        on=["station_id", "base_date"],
    )
    print(
        "OOF 캐시(개발 시, Final 폴드 = T24 학습) 앙상블 rmse_log:",
        round(compute_all(o25["target_cells"].to_numpy(), o25["ens"].to_numpy())["rmse_log"], 3),
    )

# %% [markdown]
# ## 6. submission.csv — 동결 레지스트리 current(model/, T24 = 대회 split=train 학습)로 sample_submission 124 조합 예측
#
# current 회귀가 `ensemble_v2`(T24)이면 test 행 피처에 상류 피처를 붙여 예측한다. test 행의 수온 임계는 ≤2024 측정 값이다
# (`FINAL_THRESHOLD_YEAR = 2024`, 학습과 같은 임계).

# %%
from algaecast.models.predict import make_submission, validate_submission, write_submission  # noqa: E402

sub = make_submission()
out = SUBMISSION_PATH
print("회귀 모델:", REG_ENTRY["version"], REG_KIND, "| 저장:", out.relative_to(ROOT).as_posix())
write_submission(sub, out)
print(validate_submission(out))
print(sub.head(8).to_string(index=False))

# %% [markdown]
# ## 7. 핵심 그림 — 2025 예측 vs 실측(5지점, T24·v1-fix), 리드타임 요약

# %%
from IPython.display import Image, display  # noqa: E402

va_plot = va2.assign(pred_v2=ens_v2, pred_v1=ens_retrain).sort_values(["station_id", "target_date"])
fig, axes = plt.subplots(5, 1, figsize=(12, 15), sharex=False)
for ax, (sid, g) in zip(axes, va_plot.groupby("station_id", observed=True)):
    ax.plot(pd.to_datetime(g["target_date"]), g["target_cells"], "k.-", label="관측")
    ax.plot(pd.to_datetime(g["target_date"]), g["pred_v2"], "r.-", label="7일 예측(T24 앙상블)")
    ax.plot(
        pd.to_datetime(g["target_date"]),
        g["pred_v1"],
        color="#2563eb",
        ls=":",
        lw=1,
        label="7일 예측(v1-fix)",
    )
    ax.axhline(10_000, ls="--", color="orange")
    ax.axhline(1_000, ls=":", color="green")
    ax.set_yscale("symlog", linthresh=100)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_title(f"{sid} 2025")
    ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(FIG / "fig_2025_pred_vs_obs.png", dpi=130)
plt.close(fig)
display(Image(filename=str(FIG / "fig_2025_pred_vs_obs.png"), width=900))  # 실행본에 그림 포함
# 리드타임 집계(예측값 아님): figures/reports/eval/tbl_leadtime.md(2020~2025 17/20, 지속성 1/20)·
# reports/experiments/contingency_T24/tbl_holdout_2026_posthoc_T24.md(2026 T24 7/8, 지속성 2/8) — T24 분위·분류기 기준
lead = {"2020~2025 감시(q90≥10k)": (17, 20), "2026 사후 감시": (7, 8), "지속성(2020~2026)": (3, 28)}
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
display(Image(filename=str(FIG / "fig_leadtime_summary.png"), width=600))
print(f"총 소요 {(time.time() - T0) / 60:.1f} 분, 그림 → {FIG.relative_to(ROOT).as_posix()}/")
