# ruff: noqa: E501  (한국어 표 머리글)
"""DATAON-contrib: v2.1 동결 파이프라인에서 DataON 유래 피처 2열만 뺀 기여도 비교(1회 계산, 2026 계산 없음).

대상 자료: DataON 국가참조표준 「댐유역 하천 일평균수위」(K-water 생산, DOI 10.20925/KSRD.74670854.v5, CC BY-NC-SA).
이 자료에서 나오는 선별 피처는 연속 수위 편차 ``level_cont_t0`` 와 그 7일 변화 ``level_cont_diff7`` 두 열뿐이다
(features.run.LEVEL_FEATURES, features.hydro). 두 열은 v2.1 회귀(35피처)와 v2.1 분류기·분위(30피처)에 모두 들어 있다.

조건
- full(35): v2.1 구성(models.v2.config_v2) 그대로 — 구성원 c1·c3·c2·cg, 동결 하이퍼파라미터(config/model.yaml),
  시드 42, 폴드별 학습기간 수온 임계(models.cv.fold_frames), 2020~2024 연도 확장 CV + Final(≤2024 학습 → 2025 252행).
- no_dataon(33): 같은 구성에서 기본 피처 30개 중 DataON 두 열만 뺀다(상류 5열 유지).

결합 가중치
- (A) 주 결과: 조건마다 같은 규칙(2020~2024 OOF, log10 공간 NNLS, 합=1, models.v2.fit_weights)으로 다시 적합.
- (B) 참고: 동결 v2.1 가중치(reports/experiments/FIX-v2.1/v21_fit.json)를 두 조건에 그대로 고정.

감시(q90≥1만) 포착
- 분위 모델(C1 파라미터, objective=quantile — v2.1 분위와 같은 30피처) 대 두 열을 뺀 28피처, 같은 폴드의 OOF q90.
- 2020~2025 경계 사건(2회 연속 규칙) 포착 수 = exp.harness.leadtime(2025-12-31 까지의 측정만 읽음).

기준 조건 확인: full 의 지표가 v21_fit.json 과 같은지, 구성원 OOF 가 data/processed/v21_oof.parquet 와 같은지,
분위 OOF 가 data/processed/oof_predictions.parquet 의 q90 과 같은지(그리고 감시 포착 17/20 인지).

2026 규칙: 학습 프레임은 models.v2.load_training_frame(기준일·목표일 ≤ 2025-12-31, guard_train)이고
사건·측정은 2025-12-31 까지만 쓴다. 격리 정답 파일·사후 예측 파일은 읽지 않는다.

보조 진단(재학습 없음, 실행할 때마다 results.json 에 덧붙인다)
- watch_event_detail: 저장된 OOF 캐시의 q90 으로 사건별 감시 첫 경보를 두 조건 나란히.
- frozen_gain_share: 동결 v2.1 회귀(registry current) LightGBM 부품별 gain 비중에서 두 열의 몫·순위(읽기만).
- offset_invariance: 기준면 오프셋을 0 으로 바꿔 수위 편차를 다시 계산한 차(수위 입력만) — 2026 일자는 창 전체가
  WAMIS 연장분이라 오프셋이 상쇄되는지 확인.

출력
- data/processed/exp/DATAON-contrib/oof_{full,no_dataon}.parquet(행 단위 OOF, git 제외)
- reports/experiments/DATAON-contrib/results.json, RESULT.md(1~5절은 이 모듈이 쓰고, 수기 절 표시 뒤는 보존)
사용: python -m algaecast.exp.dataon_contrib [--render-only]  (--render-only = 재학습 없이 results.json·OOF 캐시로 다시 쓴다)
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.collect.base import KST
from algaecast.config import DATA_DIR, ROOT
from algaecast.eval.metrics import compute_all
from algaecast.exp import harness as H
from algaecast.features.run import LEVEL_FEATURES
from algaecast.models import v2 as V2
from algaecast.models.ensemble import combine
from algaecast.models.quantile import cv_quantiles
from algaecast.models.train import SEED

log = logging.getLogger(__name__)

NAME = "DATAON-contrib"
DATAON_FEATURES: tuple[str, ...] = tuple(LEVEL_FEATURES)  # ("level_cont_t0", "level_cont_diff7")
REPORT_DIR = ROOT / "reports" / "experiments" / NAME
DATA_OUT = H.EXP_DATA / NAME
FIT_JSON = ROOT / "reports" / "experiments" / "FIX-v2.1" / "v21_fit.json"
V21_OOF = DATA_DIR / "processed" / "v21_oof.parquet"
OOF_CACHE = DATA_DIR / "processed" / "oof_predictions.parquet"
METRICS: tuple[str, ...] = ("rmse_log", "r2_log", "r2_raw", "f1_10k")
EXTRA_METRICS: tuple[str, ...] = ("mae_log", "r2_pearson_raw", "nse_raw", "f1_1k")
KEYS = ["station_id", "base_date", "target_date"]
N_BOOT = 2000
T10K = 10_000.0
CONDITIONS: tuple[tuple[str, str], ...] = (
    ("full", "전체 35피처(v2.1)"),
    ("no_dataon", "DataON 2열 제외 33피처"),
)


# ---------------------------------------------------------------- 구성
def config_without(drop: tuple[str, ...] = DATAON_FEATURES) -> V2.V2Config:
    """v2.1 구성에서 기본 피처 drop 만 뺀 구성(구성원·피처 묶음·시드 그대로)."""
    base = V2.config_v2()
    missing = [c for c in drop if c not in base.base_features]
    if missing:
        raise ValueError(f"v2.1 기본 피처에 없는 열: {missing}")
    return V2.V2Config(
        name=f"{base.name}_minus_dataon",
        base_features=tuple(c for c in base.base_features if c not in drop),
        feature_groups=base.feature_groups,
        members=base.members,
        weights=None,
        seed=base.seed,
    )


def quantile_columns(drop: tuple[str, ...] = ()) -> list[str]:
    """v2.1 분위 모델 피처(v1 선택 30개)에서 drop 을 뺀 목록."""
    cols = list(V2.v1_features())
    missing = [c for c in drop if c not in cols]
    if missing:
        raise ValueError(f"분위 피처에 없는 열: {missing}")
    return [c for c in cols if c not in drop]


# ---------------------------------------------------------------- 지표
def _pick(m: dict) -> dict[str, float]:
    return {k: float(m[k]) for k in (*METRICS, *EXTRA_METRICS)}


def scores(frame: pd.DataFrame, pred: np.ndarray) -> dict:
    """CV(2020~2024) 폴드 평균·폴드 통합·연도별, 2025(252행), 2025 지점별 지표."""
    obs = frame["target_cells"].to_numpy(dtype=float)
    years = V2.years_of(frame)
    pred = np.asarray(pred, dtype=float)
    by_year = {int(y): _pick(compute_all(obs[years == y], pred[years == y])) for y in V2.CV_YEARS}
    fold_mean = {k: float(np.mean([by_year[y][k] for y in by_year])) for k in (*METRICS, *EXTRA_METRICS)}
    cvm = np.isin(years, V2.CV_YEARS)
    fin = years == V2.FINAL_YEAR
    sites = frame["station_id"].astype(str).to_numpy()
    by_site = {}
    for s in sorted(set(sites[fin])):
        m = fin & (sites == s)
        by_site[s] = {"n": int(m.sum()), **_pick(compute_all(obs[m], pred[m]))}
    return {
        "cv_fold_mean": fold_mean,
        "cv_pooled": _pick(compute_all(obs[cvm], pred[cvm])),
        "cv_by_year": by_year,
        "holdout_2025": _pick(compute_all(obs[fin], pred[fin])),
        "holdout_2025_by_site": by_site,
        "n_cv": int(cvm.sum()),
        "n_2025": int(fin.sum()),
    }


def ensemble_oof(frame: pd.DataFrame, oof: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """2020~2025 행(OOF 가 있는 연도)에 같은 가중치를 적용한 앙상블(그 외 행 NaN)."""
    out = np.full(len(frame), np.nan)
    has = V2.years_of(frame) >= min(V2.CV_YEARS)
    out[has] = combine({k: np.asarray(oof[k])[has] for k in weights}, weights)
    return out


def _rmse_log(o: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.log10(o + 1) - np.log10(p + 1)) ** 2)))


def _r2(o: np.ndarray, p: np.ndarray) -> float:
    den = float(np.sum((o - o.mean()) ** 2))
    return 1.0 - float(np.sum((o - p) ** 2)) / den if den > 0 else float("nan")


def _r2_log(o: np.ndarray, p: np.ndarray) -> float:
    return _r2(np.log10(o + 1), np.log10(p + 1))


def bootstrap_delta(
    frame: pd.DataFrame,
    a: np.ndarray,
    b: np.ndarray,
    mask: np.ndarray,
    seed: int = SEED,
    n_boot: int = N_BOOT,
) -> dict[str, dict[str, float]]:
    """(지점, 기준일 연-월) 블록 부트스트랩으로 Δ = 지표(a) − 지표(b) 의 95% 구간(통합 지표 기준)."""
    obs = frame["target_cells"].to_numpy(dtype=float)
    ym = pd.to_datetime(frame["base_date"]).dt.strftime("%Y-%m").to_numpy()
    sites = frame["station_id"].astype(str).to_numpy()
    idx = np.where(mask)[0]
    blocks: dict[tuple[str, str], list[int]] = {}
    for i in idx:
        blocks.setdefault((sites[i], ym[i]), []).append(int(i))
    keys = sorted(blocks)
    rng = np.random.default_rng(seed)
    fns = {"rmse_log": _rmse_log, "r2_log": _r2_log, "r2_raw": _r2}
    point = {k: f(obs[idx], a[idx]) - f(obs[idx], b[idx]) for k, f in fns.items()}
    draws = {k: np.empty(n_boot) for k in fns}
    for j in range(n_boot):
        pick = rng.integers(0, len(keys), len(keys))
        rows = np.concatenate([blocks[keys[t]] for t in pick])
        o = obs[rows]
        for k, f in fns.items():
            draws[k][j] = f(o, a[rows]) - f(o, b[rows])
    return {
        k: {
            "delta": float(point[k]),
            "ci95_lo": float(np.nanpercentile(draws[k], 2.5)),
            "ci95_hi": float(np.nanpercentile(draws[k], 97.5)),
            "n_blocks": len(keys),
        }
        for k in fns
    }


def max_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    """두 배열의 최대 절대차. 결측 위치가 다르면 inf."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if (np.isfinite(a) != np.isfinite(b)).any():
        return float("inf")
    m = np.isfinite(a)
    return float(np.max(np.abs(a[m] - b[m]))) if m.any() else 0.0


def _key(df: pd.DataFrame) -> np.ndarray:
    return (
        df["station_id"].astype(str)
        + "|"
        + pd.to_datetime(df["base_date"]).dt.strftime("%Y-%m-%d")
        + "|"
        + pd.to_datetime(df["target_date"]).dt.strftime("%Y-%m-%d")
    ).to_numpy()


def leadtime_detail(df: pd.DataFrame, alarm: np.ndarray, *, lookback_days: int = 28) -> list[dict]:
    """exp.harness.leadtime 과 같은 규칙으로 사건별 첫 경보 기준일을 돌려준다(2025-12-31 까지 측정만).

    포착 수는 [r for r in 반환 if r["first_alarm"]] 의 길이와 harness.leadtime 의 detected 가 같다.
    """
    H.guard_no_2026(df)
    ev = H.official_events_until(level=T10K)
    meas = H._measurements_until()
    o = pd.DataFrame(
        {
            "station_id": df["station_id"].astype(str).to_numpy(),
            "base_date": pd.to_datetime(df["base_date"]).to_numpy(),
            "year": V2.years_of(df),
            "al": np.nan_to_num(np.asarray(alarm, dtype=float), nan=0.0),
        }
    )
    o = o[o["year"] >= min(V2.CV_YEARS)]
    rows: list[dict] = []
    for e in ev.itertuples():
        prev = meas[
            (meas["station_id"] == e.station_id) & (meas["obs_date"] < e.E) & (meas["cells"] >= T10K)
        ]["obs_date"]
        start = e.E - pd.Timedelta(days=lookback_days)
        if len(prev):
            start = max(start, prev.max() + pd.Timedelta(days=1))
        cand = o[(o["station_id"] == e.station_id) & (o["base_date"] < e.E) & (o["base_date"] >= start)]
        if cand.empty:
            continue
        fired = cand[cand["al"] >= 1]
        first = fired["base_date"].min() if len(fired) else None
        rows.append(
            {
                "station_id": e.station_id,
                "E": str(e.E.date()),
                "D": str(e.D.date()),
                "first_alarm": None if first is None else str(pd.Timestamp(first).date()),
                "lead_E_days": None if first is None else int((e.E - first).days),
            }
        )
    return rows


def watch_event_detail() -> list[dict]:
    """저장된 OOF 캐시(oof_full·oof_no_dataon)의 q90 으로 사건별 감시 첫 경보를 나란히(재학습 없음)."""
    caches = {n: pd.read_parquet(DATA_OUT / f"oof_{n}.parquet") for n, _ in CONDITIONS}
    det = {
        n: leadtime_detail(c, (np.nan_to_num(c["q90"].to_numpy(dtype=float), nan=0.0) >= T10K).astype(float))
        for n, c in caches.items()
    }
    out = []
    for a, b in zip(det["full"], det["no_dataon"], strict=True):
        if (a["station_id"], a["E"]) != (b["station_id"], b["E"]):
            raise RuntimeError("두 조건의 사건 목록이 다르다")
        out.append(
            {
                "station_id": a["station_id"],
                "E": a["E"],
                "D": a["D"],
                "full_first_alarm": a["first_alarm"],
                "full_lead_E_days": a["lead_E_days"],
                "no_dataon_first_alarm": b["first_alarm"],
                "no_dataon_lead_E_days": b["lead_E_days"],
            }
        )
    return out


def site_level_inputs(lc: pd.DataFrame, site: dict) -> pd.DataFrame:
    """정렬 단계(align.run.build_site_daily)와 같은 규칙으로 지점의 연속 수위 관측소 행만 고른다
    (use:false 제외, wamis_ok:false 관측소의 2025년~ 행 제외)."""
    from algaecast.align.run import LEVEL_WAMIS_CUTOVER

    ents = [e for e in site.get("dataon_stations", []) if isinstance(e, dict) and e.get("use", True)]
    codes = {str(e["code"]) for e in ents}
    bad = {str(e["code"]) for e in ents if e.get("wamis_ok") is False}
    c = lc[lc["station_code"].astype(str).isin(codes)]
    late = pd.to_datetime(c["obs_date"]) >= LEVEL_WAMIS_CUTOVER
    return c[~(c["station_code"].astype(str).isin(bad) & late)]


def offset_invariance(lc: pd.DataFrame | None = None) -> dict | None:
    """기준면 오프셋을 0 으로 바꿔도 수위 편차(level_cont_anom)가 같은 구간을 지점별로 잰다(수위 입력만, 정답 미사용).

    기준일 d 의 편차 = wl_adj(d) − 평균(wl_adj[d−365..d−1]) 이므로 창 전체가 WAMIS 연장분(오프셋 상수)이면 상쇄된다.
    DataON 원자료 스냅샷(level_continuous_long.parquet)이 없으면 None.
    """
    from algaecast.align.run import level_anomaly_asof
    from algaecast.collect.dataon_level import CONT_PATH
    from algaecast.features.base import sites_cfg

    if lc is None:
        if not CONT_PATH.exists():
            return None
        lc = pd.read_parquet(CONT_PATH)
    lc = lc.assign(obs_date=pd.to_datetime(lc["obs_date"]))
    days = pd.date_range("2012-01-01", lc["obs_date"].max())
    out: dict = {}
    for site in sites_cfg()["sites"]:
        c = site_level_inputs(lc, site)
        a, _ = level_anomaly_asof(c, days)
        b, _ = level_anomaly_asof(c.assign(wl_adj=c["wl"]), days)
        d = (a - b).abs()
        yr = d.index.year
        out[site["station_id"]] = {
            "max_abs_diff_2025": float(d[yr == 2025].max()),
            "max_abs_diff_2026": float(d[yr == 2026].max()),
            "nan_days_2026": [str(x.date()) for x in a[(yr == 2026) & a.isna()].index],
        }
    return out


def _boosters(x: object, path: str = "") -> list[tuple[str, object]]:
    """구성원 dict 안의 LightGBM 모델을 (경로, 모델)로 모은다."""
    import lightgbm as lgb

    if isinstance(x, lgb.LGBMModel):
        return [(path.lstrip("/"), x)]
    if isinstance(x, dict):
        return [p for k, v in x.items() for p in _boosters(v, f"{path}/{k}")]
    return []


def frozen_gain_share() -> dict:
    """동결 v2.1 회귀(registry current)의 LightGBM 부품별 gain 비중에서 DataON 두 열의 몫·순위(읽기 전용 진단)."""
    from algaecast.models import registry as R

    obj, entry = R.load_current("regression")
    out: dict = {"version": entry["version"], "parts": {}}
    for path, m in _boosters(obj["members"]):
        names = list(m.booster_.feature_name())
        gain = np.asarray(m.booster_.feature_importance("gain"), dtype=float)
        share = gain / gain.sum() if gain.sum() > 0 else gain
        rank = {names[i]: r + 1 for r, i in enumerate(np.argsort(-share, kind="stable"))}
        out["parts"][path] = {
            "n_features": len(names),
            **{f: {"share": float(share[names.index(f)]), "rank": int(rank[f])} for f in DATAON_FEATURES},
        }
    return out


def offset_table(o: dict | None) -> str:
    """offset_invariance 결과 표."""
    if not o:
        return ""
    rows = [
        "참고 — 기준면 오프셋을 0 으로 바꿔 수위 편차(`level_cont_anom`)를 다시 계산한 차(m, 수위 입력만):",
        "",
        "| 지점 | 2025 일자 최대 차 | 2026 일자 최대 차 | 2026 편차 결측일 |",
        "|---|---|---|---|",
    ]
    for s, v in o.items():
        nan = ", ".join(v["nan_days_2026"]) or "없음"
        rows.append(f"| {s} | {v['max_abs_diff_2025']:.4f} | {v['max_abs_diff_2026']:.4f} | {nan} |")
    return "\n".join(rows)


def gain_table(g: dict | None) -> str:
    """frozen_gain_share 결과 표."""
    if not g:
        return ""
    head = " | ".join(f"{f} 비중(순위)" for f in DATAON_FEATURES)
    rows = [
        f"참고 — 동결 v2.1 회귀(`regression/{g['version']}`)의 LightGBM 부품별 gain 비중(학습 ≤2025, 읽기 전용 진단):",
        "",
        f"| 부품 | 피처 수 | {head} | 두 열 합 |",
        "|---|---|" + "---|" * len(DATAON_FEATURES) + "---|",
    ]
    for p, v in g["parts"].items():
        cells = " | ".join(f"{v[f]['share']:.3f}({v[f]['rank']}위)" for f in DATAON_FEATURES)
        total = sum(v[f]["share"] for f in DATAON_FEATURES)
        rows.append(f"| {p} | {v['n_features']} | {cells} | {total:.3f} |")
    return "\n".join(rows)


# ---------------------------------------------------------------- 계산
def run(seed: int = SEED) -> dict:
    """두 조건의 OOF·지표·감시 포착·기준 조건 확인·부트스트랩을 계산하고 results.json 을 쓴다."""
    t0 = time.time()
    cfg_full = V2.config_v2()
    cfg_no = config_without(DATAON_FEATURES)
    frame = V2.load_training_frame(config=cfg_full)
    H.guard_no_2026(frame)
    H.guard_no_2026(frame, "target_date")
    specs = V2.member_specs()
    frozen = json.loads(FIT_JSON.read_text(encoding="utf-8"))
    frozen_w = {k: float(v) for k, v in frozen["weights"].items()}
    obs = frame["target_cells"].to_numpy(dtype=float)
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    out: dict = {
        "experiment": NAME,
        "computed_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "seed": seed,
        "dataon_features": list(DATAON_FEATURES),
        "n_rows": len(frame),
        "frame_rule": "기준일·목표일 ≤ 2025-12-31 인 학습·검증 행(models.v2.load_training_frame, v2.1 동결과 같은 2,562행)",
        "conditions": {},
    }
    preds: dict[str, dict[str, np.ndarray]] = {}
    for name, label in CONDITIONS:
        cfg = cfg_full if name == "full" else cfg_no
        tc = time.time()
        oof = V2.cv_members(frame, seed, cfg, specs=specs)
        w_nnls = V2.fit_weights(frame, seed, cfg, oof=oof, specs=specs)
        ens_a = ensemble_oof(frame, oof, w_nnls)
        ens_b = ensemble_oof(frame, oof, frozen_w)
        qcols = quantile_columns(() if name == "full" else DATAON_FEATURES)
        quant = cv_quantiles(frame, qcols, specs["c1"])
        q90 = np.asarray(quant["q90"], dtype=float)
        lead_q90 = H.leadtime(frame, (np.nan_to_num(q90, nan=0.0) >= T10K).astype(float))
        lead_pt = H.leadtime(frame, (np.nan_to_num(ens_a, nan=0.0) >= T10K).astype(float))
        preds[name] = {
            "ens_a": ens_a,
            "ens_b": ens_b,
            "q90": q90,
            **{k: np.asarray(v, dtype=float) for k, v in oof.items()},
        }
        cache = frame[KEYS].copy()
        for k, v in preds[name].items():
            cache[k] = v
        cache["target_cells"] = obs
        cache.to_parquet(DATA_OUT / f"oof_{name}.parquet", index=False)
        out["conditions"][name] = {
            "label": label,
            "n_regression_features": len(cfg.cols),
            "regression_features": list(cfg.cols),
            "n_quantile_features": len(qcols),
            "weights_nnls": w_nnls,
            "A_nnls_refit": scores(frame, ens_a),
            "B_frozen_weights": scores(frame, ens_b),
            "watch_q90_2020_2025": lead_q90,
            "point_ens_2020_2025": lead_pt,
            "seconds": round(time.time() - tc, 1),
        }
        log.info("%s 완료 (%.0f초)", name, time.time() - tc)
    out["baseline_check"] = baseline_check(frame, out, preds, frozen, cfg_full.names)
    years = V2.years_of(frame)
    a, b = preds["no_dataon"]["ens_a"], preds["full"]["ens_a"]
    out["bootstrap_delta_no_minus_full"] = {
        "method": f"(지점, 기준일 연-월) 블록 부트스트랩 {N_BOOT}회, 시드 {seed}, Δ = 33피처 − 35피처, 통합(pooled) 지표",
        "cv_2020_2024": bootstrap_delta(frame, a, b, np.isin(years, V2.CV_YEARS), seed),
        "holdout_2025": bootstrap_delta(frame, a, b, years == V2.FINAL_YEAR, seed),
    }
    out["elapsed_min"] = round((time.time() - t0) / 60, 1)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    return out


def baseline_check(
    frame: pd.DataFrame,
    out: dict,
    preds: dict[str, dict[str, np.ndarray]],
    frozen: dict,
    member_names: tuple[str, ...],
) -> dict:
    """full 조건이 보고값(v21_fit.json)·저장 OOF(v21_oof·oof_predictions)와 같은지."""
    full = out["conditions"]["full"]
    frozen_w = {k: float(v) for k, v in frozen["weights"].items()}
    rep_cv, rep_25 = frozen["cv_mean_2020_2024"], frozen["holdout_2025"]
    chk: dict = {
        "weights_max_abs_diff": max(abs(full["weights_nnls"][k] - frozen_w[k]) for k in frozen_w),
        "holdout_2025_max_abs_diff": max(
            abs(full["A_nnls_refit"]["holdout_2025"][k] - rep_25[k]) for k in METRICS
        ),
        "cv_fold_mean_max_abs_diff": max(
            abs(full["A_nnls_refit"]["cv_fold_mean"][k] - rep_cv[k]) for k in METRICS
        ),
        "reported_2025": {k: rep_25[k] for k in METRICS},
        "reported_cv_fold_mean": {k: rep_cv[k] for k in METRICS},
    }
    if V21_OOF.exists():
        v = pd.read_parquet(V21_OOF)
        v = v.set_index(_key(v)).reindex(_key(frame))
        chk["members_vs_v21_oof_max_abs_diff"] = {
            k: max_abs_diff(preds["full"][k], v[k].to_numpy(dtype=float)) for k in member_names
        }
        chk["ens_vs_v21_oof_max_abs_diff"] = max_abs_diff(
            preds["full"]["ens_a"], v["ens"].to_numpy(dtype=float)
        )
    if OOF_CACHE.exists():
        o = pd.read_parquet(OOF_CACHE)
        o = o.set_index(_key(o)).reindex(_key(frame))
        q_saved = o["q90"].to_numpy(dtype=float)
        q_new = preds["full"]["q90"]
        both = np.isfinite(q_new)
        chk["q90_vs_oof_cache_max_abs_diff"] = max_abs_diff(q_new[both], q_saved[both])
    chk["watch_q90_full"] = full["watch_q90_2020_2025"]
    chk["matches_reported"] = bool(
        chk["holdout_2025_max_abs_diff"] < 1e-9 and chk["cv_fold_mean_max_abs_diff"] < 1e-9
    )
    return chk


# ---------------------------------------------------------------- 보고서
def _f(v: float | None, nd: int = 4) -> str:
    return "–" if v is None or not np.isfinite(v) else f"{v:.{nd}f}"


def _d(v: float | None, nd: int = 4) -> str:
    return "–" if v is None or not np.isfinite(v) else f"{v:+.{nd}f}"


LABEL = {"rmse_log": "rmse_log", "r2_log": "r2_log", "r2_raw": "r2_raw(=NSE)", "f1_10k": "F1@10k"}
BETTER_HIGH = {"rmse_log": False, "r2_log": True, "r2_raw": True, "f1_10k": True}


def direction(metric: str, delta: float) -> str:
    """Δ = 33피처 − 35피처. 빼면 나빠지면 'DataON 포함이 좋음', 좋아지면 'DataON 제외가 좋음'."""
    if not np.isfinite(delta) or abs(delta) < 5e-5:
        return "같음"
    worse_without = delta < 0 if BETTER_HIGH[metric] else delta > 0
    return "DataON 포함이 좋음" if worse_without else "DataON 제외가 좋음"


def metric_table(res: dict, block: str) -> str:
    """CV 폴드 평균·2025 × 4개 지표의 두 조건 비교 표(마크다운)."""
    full, no = res["conditions"]["full"][block], res["conditions"]["no_dataon"][block]
    rows = [
        "| 구간 | 지표 | 35피처(v2.1) | 33피처(DataON 제외) | Δ(33−35) | 해석 |",
        "|---|---|---|---|---|---|",
    ]
    for scope, title in (
        ("cv_fold_mean", "CV 2020~2024 폴드 평균"),
        ("holdout_2025", "2025 홀드아웃(252행)"),
    ):
        for k in METRICS:
            a, b = full[scope][k], no[scope][k]
            rows.append(f"| {title} | {LABEL[k]} | {_f(a)} | {_f(b)} | {_d(b - a)} | {direction(k, b - a)} |")
    return "\n".join(rows)


def event_table(rows: list[dict]) -> str:
    """사건별 감시 첫 경보 비교 표. 결과가 다른 사건에 표시를 붙인다."""
    if not rows:
        return "(사건별 상세 없음 — `--render-only` 로 OOF 캐시에서 만든다)"

    def cell(first: str | None, lead: int | None) -> str:
        return "놓침" if first is None else f"{first}({lead}일)"

    out = [
        "사건별 감시 첫 경보(기준일, E 기준 리드):",
        "",
        "| 지점 | 첫 초과 E | 발령 D | DataON 포함 | DataON 제외 | 차이 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        a = cell(r["full_first_alarm"], r["full_lead_E_days"])
        b = cell(r["no_dataon_first_alarm"], r["no_dataon_lead_E_days"])
        out.append(f"| {r['station_id']} | {r['E']} | {r['D']} | {a} | {b} | {'다름' if a != b else ''} |")
    return "\n".join(out)


def render(res: dict) -> str:
    """results.json → RESULT.md 1~5절."""
    c = res["conditions"]
    full, no = c["full"], c["no_dataon"]
    chk = res["baseline_check"]
    bs = res["bootstrap_delta_no_minus_full"]
    wq_f, wq_n = full["watch_q90_2020_2025"], no["watch_q90_2020_2025"]
    pt_f, pt_n = full["point_ens_2020_2025"], no["point_ens_2020_2025"]
    a25, n25 = full["A_nnls_refit"]["holdout_2025"], no["A_nnls_refit"]["holdout_2025"]
    acv, ncv = full["A_nnls_refit"]["cv_fold_mean"], no["A_nnls_refit"]["cv_fold_mean"]
    w_rows = "\n".join(
        f"| {lab} | " + " | ".join(_f(c[n]["weights_nnls"][k]) for k in ("c1", "c3", "c2", "cg")) + " |"
        for n, lab in (("full", "35피처"), ("no_dataon", "33피처"))
    )
    fs, ns = full["A_nnls_refit"]["holdout_2025_by_site"], no["A_nnls_refit"]["holdout_2025_by_site"]
    site_rows = "\n".join(
        f"| {s} | {fs[s]['n']} | {_f(fs[s]['rmse_log'])} | {_f(ns[s]['rmse_log'])} | "
        f"{_d(ns[s]['rmse_log'] - fs[s]['rmse_log'])} |"
        for s in fs
    )
    bs_rows = "\n".join(
        f"| {title} | {k} | {_d(bs[scope][k]['delta'])} | "
        f"[{_d(bs[scope][k]['ci95_lo'])}, {_d(bs[scope][k]['ci95_hi'])}] | {bs[scope][k]['n_blocks']} |"
        for scope, title in (("cv_2020_2024", "CV 2020~2024(통합)"), ("holdout_2025", "2025"))
        for k in ("rmse_log", "r2_log", "r2_raw")
    )
    members = chk.get("members_vs_v21_oof_max_abs_diff", {})
    mem_txt = ", ".join(f"{k} {v:.3g}" for k, v in members.items()) if members else "비교 파일 없음"
    feats = "`·`".join(res["dataon_features"])
    verdict = (
        "보고값과 같음 — 비교 기준으로 쓴다"
        if chk["matches_reported"]
        else "보고값과 다름 — 차이를 먼저 확인해야 한다"
    )
    events = event_table(res.get("watch_event_detail", []))
    return f"""# DATAON-contrib — DataON 유래 피처 2열의 기여도(v2.1 동결 파이프라인, 1회 계산)

- 계산: {res["computed_at"]} KST, 시드 {res["seed"]}, 소요 {res["elapsed_min"]}분. 코드 `src/algaecast/exp/dataon_contrib.py`, 수치 `results.json`.
- 대상 피처: `{feats}` — DataON 국가참조표준 「댐유역 하천 일평균수위」(DOI 10.20925/KSRD.74670854.v5)에서 나오는 선별 피처 전부.
- **2026 은 계산하지 않았다.** 학습·평가 프레임 = {res["frame_rule"]}. 경계 사건은 2025-12-31 까지 측정으로만 만든다.
- 기존 피처 그룹 제거 실험(`reports/eval/tbl_ablation.md`, 방법설명서 6.7절)은 수문 그룹 10열을 한꺼번에 뺀 C1 단일 회귀(30피처) 결과라 'DataON 2열만' 뺀 값이 없다. 그래서 이 비교를 새로 계산했다.
- 제출 모델·예측값·submission.csv·설정 파일은 바꾸지 않았다(OOF 재학습만 하고 레지스트리에 등록하지 않는다).

## 1. 설계

| 항목 | 내용 |
|---|---|
| 비교 | full = v2.1 구성 그대로(회귀 {full["n_regression_features"]}피처) / no_dataon = 같은 구성에서 두 열만 제외(회귀 {no["n_regression_features"]}피처, 상류 5열 유지) |
| 구성원·하이퍼파라미터 | c1(C1 smearing)·c3(C3 hurdle)·c2(C2 tweedie)·cg(속별 G2), `config/model.yaml` 동결값, 시드 42 |
| 검증 | 2020~2024 연도 확장 CV(폴드 V 학습 ≤V−1, 폴드별 학습기간 수온 임계) + Final(≤2024 학습 → 2025 252행) |
| 결합 가중치 | **(A) 주 결과: 조건마다 같은 NNLS 규칙으로 다시 적합**(2020~2024 OOF, log10 공간, 합=1). (B) 참고: 동결 v2.1 가중치를 두 조건에 고정 |
| 감시(q90≥1만) | 분위 모델(C1 파라미터, objective=quantile): full {full["n_quantile_features"]}피처(v2.1 분위와 같은 목록) / no_dataon {no["n_quantile_features"]}피처. 같은 폴드 OOF q90 으로 2020~2025 경계 사건(2회 연속 규칙) 포착 |

## 2. 기준 조건 확인(full = 보고값 재현)

| 확인 | 결과 |
|---|---|
| 2025 rmse_log·r2_log·r2_raw·F1@10k vs `FIX-v2.1/v21_fit.json` | 최대 차 {chk["holdout_2025_max_abs_diff"]:.3g} (보고 rmse_log {chk["reported_2025"]["rmse_log"]:.4f} → 재계산 {a25["rmse_log"]:.4f}) |
| CV 폴드 평균 4개 지표 vs `v21_fit.json` | 최대 차 {chk["cv_fold_mean_max_abs_diff"]:.3g} (보고 rmse_log {chk["reported_cv_fold_mean"]["rmse_log"]:.4f} → 재계산 {acv["rmse_log"]:.4f}) |
| NNLS 가중치 vs 동결 가중치 | 최대 차 {chk["weights_max_abs_diff"]:.3g} |
| 구성원 OOF vs `data/processed/v21_oof.parquet` | 최대 절대차 {mem_txt}; 앙상블 {chk.get("ens_vs_v21_oof_max_abs_diff", float("nan")):.3g} |
| 분위 OOF q90 vs `data/processed/oof_predictions.parquet` | 최대 절대차 {chk.get("q90_vs_oof_cache_max_abs_diff", float("nan")):.3g} |
| 감시 포착(2020~2025) | {wq_f["detected"]}/{wq_f["n_events"]}건, 중앙 {_f(wq_f["median_lead_E"], 0)}일 (보고 17/20, 중앙 14일) |
| 판정 | {verdict} |

## 3. 회귀 앙상블 지표 — (A) 조건별 NNLS 재적합(주 결과)

{metric_table(res, "A_nnls_refit")}

결합 가중치(2020~2024 OOF NNLS):

| 조건 | c1 | c3 | c2 | cg |
|---|---|---|---|---|
{w_rows}

### 참고 — (B) 동결 v2.1 가중치 고정

{metric_table(res, "B_frozen_weights")}

## 4. 감시 포착(2020~2025 경계 사건)

| 방식 | DataON 포함(분위 30·회귀 35피처) | DataON 제외(분위 28·회귀 33피처) |
|---|---|---|
| 감시: 분위 OOF q90 ≥ 1만 | {wq_f["detected"]}/{wq_f["n_events"]}건, 중앙 {_f(wq_f["median_lead_E"], 0)}일 | {wq_n["detected"]}/{wq_n["n_events"]}건, 중앙 {_f(wq_n["median_lead_E"], 0)}일 |
| 참고: 점예측(앙상블 A) ≥ 1만 | {pt_f["detected"]}/{pt_f["n_events"]}건 | {pt_n["detected"]}/{pt_n["n_events"]}건 |

경보(분류기 b, 운영점 0.46)는 다시 계산하지 않았다.

{events}

## 5. 차이의 불확실성과 지점별 분해

Δ(33−35) 95% 구간 — {bs["method"]}:

| 구간 | 지표 | Δ | 95% 구간 | 블록 수 |
|---|---|---|---|---|
{bs_rows}

2025 지점별 rmse_log(A):

| 지점 | n | 35피처 | 33피처 | Δ(33−35) |
|---|---|---|---|---|
{site_rows}

{gain_table(res.get("frozen_gain_share"))}

{offset_table(res.get("offset_invariance"))}

요약(자동): DataON 2열을 빼면 2025 rmse_log {a25["rmse_log"]:.4f}→{n25["rmse_log"]:.4f}({_d(n25["rmse_log"] - a25["rmse_log"])}), r2_raw {a25["r2_raw"]:.4f}→{n25["r2_raw"]:.4f}({_d(n25["r2_raw"] - a25["r2_raw"])}), F1@10k {a25["f1_10k"]:.4f}→{n25["f1_10k"]:.4f}; CV 폴드 평균 rmse_log {acv["rmse_log"]:.4f}→{ncv["rmse_log"]:.4f}({_d(ncv["rmse_log"] - acv["rmse_log"])}), r2_raw {acv["r2_raw"]:.4f}→{ncv["r2_raw"]:.4f}; 감시 포착 {wq_f["detected"]}/{wq_f["n_events"]} → {wq_n["detected"]}/{wq_n["n_events"]}.
"""


MANUAL_MARK = "<!-- 수기 절: 아래는 모듈이 덮어쓰지 않는다 -->"


def keep_manual(old: str) -> str:
    """기존 RESULT.md 에서 수기 절 표시 뒤(표시 포함)를 돌려준다. 없으면 빈 문자열."""
    i = old.find(MANUAL_MARK)
    return "\n" + old[i:] if i >= 0 else ""


def write_report(res: dict) -> Path:
    """RESULT.md 1~5절을 다시 쓴다. 기존 파일의 수기 절(MANUAL_MARK 뒤)은 그대로 둔다."""
    path = REPORT_DIR / "RESULT.md"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    tail = keep_manual(path.read_text(encoding="utf-8")) if path.exists() else ""
    path.write_text(render(res) + tail, encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render-only", action="store_true", help="results.json 으로 RESULT.md 표만 다시 쓴다")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = REPORT_DIR / "results.json"
    res = json.loads(path.read_text(encoding="utf-8")) if args.render_only else run()
    if (DATA_OUT / "oof_full.parquet").exists() and (DATA_OUT / "oof_no_dataon.parquet").exists():
        res["watch_event_detail"] = watch_event_detail()  # 저장된 OOF 로만 계산(재학습 없음)
        res["frozen_gain_share"] = frozen_gain_share()  # 동결 모델 읽기만
        res["offset_invariance"] = offset_invariance()  # 수위 입력만(정답 미사용)
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(write_report(res))
    print(json.dumps(res["baseline_check"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
