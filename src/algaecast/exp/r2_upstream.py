# ruff: noqa: E501  (한국어 표·보고서 문자열)
"""EXP-005(R2) 상류 지점 특징 — 낙동강 상류 사슬 HP → GJGR → CS → MGMR.

각 대상 지점에 바로 위(1단계)·두 단계 위(2단계) 조류경보 지점의 'base_date − lag 이전' 최근 측정을 붙인다.
회남(DCHN)과 최상류 해평(HP)은 상류 지점이 없으므로 모든 새 피처가 NaN 이다.

새 피처(k = 1, 2 단계)
- up{k}_cell_log   : obs_date ≤ base_date − lag 인 최근 유효 측정의 log10(세포수 + 1)
- up{k}_slope3     : 같은 기준의 최근 3회 log10 세포수 기울기(log10/일, ar.py 의 cell_slope_3 과 같은 정의)
- up{k}_wtemp      : 같은 기준의 최근 유효 수온(℃)
- up{k}_days       : base_date − (그 최근 유효 세포수 측정일) 일수(경과일)
- up{k}_diff       : up{k}_cell_log − cell_log_t0(자기 지점 최근 측정, v1 피처) — 묶음 'all4_diff' 에서만

lag 방식(CV 로 선택)
- 고정 lag 0 / 3 / 7 일(1·2단계 같은 lag)
- travel: 보 방류량 기반 이동시간 대략값 T 로 lag = clip(round(T − horizon_days), 0, 28)
  (목표일 target_date 에 하류에 도달하는 물은 target_date − T 에 상류를 지났다 → 그 시점 이전 측정이 가장 관련.
   T ≤ horizon 이면 그 측정이 아직 미래이므로 가장 최근 측정(lag 0)을 쓴다.)
  T(구간 U→D) = L_UD · Ā / Q̄ / 86400 [일],
     Ā = 구간 양 끝 지점 시설(보) 저수 구간의 평균 단면적 V_f / L_pool,f 의 평균(V_f 는 base_date 까지 7일 중앙값 fac_storage),
     Q̄ = 양 끝 시설 fac_outflow 의 base_date 까지 7일 평균의 평균(m³/s, 하한 5).
  2단계는 T(U2→U1) + T(U1→D).

as_of 규칙: 모든 피처 함수는 진입 직후 features.base.cut_as_of(raw, as_of) 로 base_date 이후 행을 버리고,
그 다음 obs_date ≤ as_of − lag 로 한 번 더 자른다. 2026 행은 읽는 즉시 버린다(harness.LAST_DATE).

공개 함수(종합 단계 재사용)
- build_features(df) -> DataFrame : df = harness.load_base() 형식, 같은 인덱스로 선택한 설정(CHOSEN)의 새 열만 반환.
- build_variant_features(df, lag_mode) -> DataFrame : 한 lag 방식의 전체 새 열(단계·묶음 선택 전).
- columns_for(depth, bundle) -> list[str] : 단계·묶음에 해당하는 열 이름.
- make_upstream_features(algae, hydro, as_of, station_id, horizon_days, lag_mode) -> dict : 순수 함수(행 하나).

실행: python -m algaecast.exp.r2_upstream  (변형 학습 결과는 data/processed/exp/EXP-005/variants/ 에 캐시, 표 초안은 README_draft.md)
보조: python -m algaecast.exp.r2_upstream --supplement  (분위 v1 유지 표·gain 비중·지점별 2025 → supplement.json)
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import date, datetime

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR
from algaecast.exp import harness as H
from algaecast.features.base import cut_as_of, slope, window_days

log = logging.getLogger(__name__)

EXP_ID = "EXP-005"
OUT_DATA = H.EXP_DATA / EXP_ID
OUT_REPORT = H.EXP_REPORTS / EXP_ID
INTERIM = DATA_DIR / "interim"
BUDGET_HOURS = 4.0

# 상류 사슬(낙동강 본류, 상류 → 하류). 값 = (1단계 상류, 2단계 상류). 회남(DCHN)·해평(HP)은 해당 없음.
CHAIN: dict[str, tuple[str | None, str | None]] = {
    "HP": (None, None),
    "GJGR": ("HP", None),
    "CS": ("GJGR", "HP"),
    "MGMR": ("CS", "GJGR"),
    "DCHN": (None, None),
}
NAKDONG = ("HP", "GJGR", "CS", "MGMR")

# 이동시간 대략값의 기하 가정(km). 출처: config/sites.yaml 주석·docs/reference/sites_facts_verified.json.
# 안동댐 기준 하류 거리: 구미보 114, 칠곡보 141(검증), 강정고령보 = 칠곡보 + 25(검증), 달성보 = 강정고령보 + 18(가정, 미검증),
# 합천창녕보 = 달성보 + 38(검증), 창녕함안보 = 합천창녕보 + 43(검증), 하굿둑 = 창녕함안보 + 75(검증).
# 측정지점: HP = 칠곡보 상류 23 km(sites.yaml), GJGR = 강정고령보 상류 7 km(sites.yaml), CS = 창녕함안보 상류 12 km,
# MGMR = 하굿둑 상류 27 km(26~28 km 의 가운데).
RIVER_KM: dict[str, float] = {"HP": 118.0, "GJGR": 159.0, "CS": 253.0, "MGMR": 313.0}
SEG_KM: dict[tuple[str, str], float] = {
    ("HP", "GJGR"): RIVER_KM["GJGR"] - RIVER_KM["HP"],  # 41
    ("GJGR", "CS"): RIVER_KM["CS"] - RIVER_KM["GJGR"],  # 94
    ("CS", "MGMR"): RIVER_KM["MGMR"] - RIVER_KM["CS"],  # 60
}
# 지점 시설(보)의 저수 구간 길이(km, 바로 위 보 → 이 보)와 제원 저수량(백만 m³, sites.yaml; 하굿둑은 제원 없음)
POOL_KM: dict[str, float] = {"HP": 27.0, "GJGR": 25.0, "CS": 43.0, "MGMR": 75.0}
NOMINAL_MCM: dict[str, float | None] = {"HP": 88.8, "GJGR": 92.3, "CS": 100.9, "MGMR": None}
Q_FLOOR = 5.0  # m³/s
LAG_CAP = 28  # 일
HYDRO_WINDOW = 7  # 일

LAG_MODES: tuple[str, ...] = ("0", "3", "7", "travel")
ITEMS = ("cell_log", "slope3", "wtemp", "days", "diff")
BUNDLES: dict[str, tuple[str, ...]] = {
    "cell": ("cell_log",),
    "cell_slope": ("cell_log", "slope3"),
    "all4": ("cell_log", "slope3", "wtemp", "days"),
    "all4_diff": ("cell_log", "slope3", "wtemp", "days", "diff"),
}
DEPTHS = (1, 2)

# 선택 결과(main() 실행 후 CV 규칙으로 정한 값을 고정 — build_features 가 사용)
CHOSEN: dict[str, object] = {"lag_mode": "0", "depth": 1, "bundle": "all4_diff"}  # 2026-10-21 main() 결과


# ---------------------------------------------------------------- 원자료
def load_algae(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """조류경보 원자료(5지점) — 2025-12-31 이후 행은 읽은 즉시 버린다."""
    a = pd.read_parquet(
        H.ALGAE_PARQUET, columns=["station_id", "obs_date", "iem_bgalage_cell_co", "iem_wtrtp"]
    )
    a["obs_date"] = pd.to_datetime(a["obs_date"]).dt.normalize()
    a = a[a["obs_date"] <= last]
    a = a.rename(columns={"iem_bgalage_cell_co": "cells", "iem_wtrtp": "wtemp"})
    a["station_id"] = a["station_id"].astype(str)
    return a.sort_values(["station_id", "obs_date"]).reset_index(drop=True)


def load_hydro(last: pd.Timestamp = H.LAST_DATE) -> dict[str, pd.DataFrame]:
    """낙동강 4지점 시설(보·하굿둑) 일자료(fac_outflow·fac_storage, 읽기 전용 interim) — 2026 행은 버린다."""
    out = {}
    for s in NAKDONG:
        d = pd.read_parquet(
            INTERIM / f"daily_{s}_S1.parquet", columns=["obs_date", "fac_outflow", "fac_storage"]
        )
        d["obs_date"] = pd.to_datetime(d["obs_date"]).dt.normalize()
        out[s] = d[d["obs_date"] <= last].sort_values("obs_date").reset_index(drop=True)
    return out


# ---------------------------------------------------------------- 순수 피처 함수
def upstream_point_features(algae_u: pd.DataFrame, as_of: date, lag_days: int) -> dict[str, float]:
    """한 상류 지점의 측정 원자료(obs_date·cells·wtemp) → obs_date ≤ as_of − lag 기준 4항목.

    진입 직후 cut_as_of(as_of) 로 기준일 이후 행을 버리고, 다시 as_of − lag 로 자른다.
    """
    d = cut_as_of(algae_u, as_of)
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=int(lag_days))
    d = d[pd.to_datetime(d["obs_date"]) <= cutoff]
    dates = pd.to_datetime(d["obs_date"])
    cells = d["cells"].astype(float)
    valid = cells.notna()
    out = {"cell_log": math.nan, "slope3": math.nan, "wtemp": math.nan, "days": math.nan}
    if valid.any():
        logc = np.log10(cells[valid].to_numpy(dtype=float) + 1.0)
        vd = dates[valid]
        out["cell_log"] = float(logc[-1])
        out["days"] = float((pd.Timestamp(as_of) - vd.iloc[-1]).days)
        if len(logc) >= 3:
            x = (vd.iloc[-3:] - pd.Timestamp(as_of)).dt.days.to_numpy(dtype=float)
            out["slope3"] = slope(logc[-3:], x)
    wt = d["wtemp"].astype(float).dropna()
    if len(wt):
        out["wtemp"] = float(wt.iloc[-1])
    return out


def _facility_state(daily: pd.DataFrame, as_of: date, site: str) -> tuple[float, float]:
    """시설 일자료 → (Q̄ 7일 평균 방류량 m³/s, 단면적 A m²). as_of 이후 행은 진입 직후 버린다."""
    d = cut_as_of(daily, as_of)
    q = window_days(d, as_of, HYDRO_WINDOW, "fac_outflow").astype(float).dropna()
    v = window_days(d, as_of, HYDRO_WINDOW, "fac_storage").astype(float).dropna()
    q_mean = float(q.mean()) if len(q) else math.nan
    v_med = float(v.median()) if len(v) else math.nan
    nom = NOMINAL_MCM[site]
    if nom is not None and not (np.isfinite(v_med) and 0.3 * nom <= v_med <= 3.0 * nom):
        v_med = nom  # 결측·이상치는 제원 저수량
    if not (np.isfinite(v_med) and v_med > 0):
        return q_mean, math.nan
    return q_mean, v_med * 1e6 / (POOL_KM[site] * 1e3)


def segment_travel_days(hydro: dict[str, pd.DataFrame], as_of: date, up: str, down: str) -> float:
    """구간 up→down(인접 지점) 이동시간 대략값(일) = L · Ā / Q̄ / 86400."""
    qa, aa = _facility_state(hydro[up], as_of, up)
    qb, ab = _facility_state(hydro[down], as_of, down)
    a_bar = float(np.nanmean([aa, ab])) if np.isfinite([aa, ab]).any() else math.nan
    q_bar = float(np.nanmean([qa, qb])) if np.isfinite([qa, qb]).any() else math.nan
    if not (np.isfinite(a_bar) and np.isfinite(q_bar)):
        return math.nan
    return SEG_KM[(up, down)] * 1e3 * a_bar / max(q_bar, Q_FLOOR) / 86400.0


def travel_days(hydro: dict[str, pd.DataFrame], as_of: date, up: str, down: str) -> float:
    """상류 up → 하류 down 이동시간(인접 구간 합)."""
    i, j = NAKDONG.index(up), NAKDONG.index(down)
    if i >= j:
        raise ValueError(f"{up} 는 {down} 의 상류가 아님")
    return float(sum(segment_travel_days(hydro, as_of, NAKDONG[k], NAKDONG[k + 1]) for k in range(i, j)))


def lag_for(
    lag_mode: str, hydro: dict[str, pd.DataFrame] | None, as_of: date, up: str, down: str, horizon: float
) -> tuple[int, float]:
    """(사용할 lag 일수, 이동시간 T). 고정 lag 이면 T = NaN."""
    if lag_mode != "travel":
        return int(lag_mode), math.nan
    if hydro is None:
        raise ValueError("travel lag 에는 hydro 가 필요")
    t = travel_days(hydro, as_of, up, down)
    if not np.isfinite(t):
        return 0, t
    return int(np.clip(np.round(t - float(horizon)), 0, LAG_CAP)), t


def make_upstream_features(
    algae: pd.DataFrame,
    hydro: dict[str, pd.DataFrame] | None,
    as_of: date,
    station_id: str,
    horizon_days: float,
    lag_mode: str,
    own_cell_log: float = math.nan,
) -> dict[str, float]:
    """(조류 원자료, 시설 일자료, as_of, 지점) → 상류 1·2단계 피처 dict. 상류 없는 지점은 모두 NaN.

    algae: 열 station_id·obs_date·cells·wtemp (load_algae 형식). hydro: load_hydro 형식(travel 에만 필요).
    own_cell_log: 자기 지점 cell_log_t0(v1 피처, as_of 규칙 준수) — diff 계산용.
    """
    algae = cut_as_of(algae, as_of)
    hydro = {k: cut_as_of(v, as_of) for k, v in hydro.items()} if hydro is not None else None
    out: dict[str, float] = {}
    ups = CHAIN.get(str(station_id), (None, None))
    for k, up in enumerate(ups, start=1):
        names = [f"up{k}_{it}" for it in ITEMS] + [f"up{k}_lag"]
        if up is None:
            out.update({n: math.nan for n in names})
            continue
        lag, _ = lag_for(lag_mode, hydro, as_of, up, str(station_id), horizon_days)
        pf = upstream_point_features(algae[algae["station_id"] == up], as_of, lag)
        for it in ("cell_log", "slope3", "wtemp", "days"):
            out[f"up{k}_{it}"] = pf[it]
        out[f"up{k}_diff"] = pf["cell_log"] - own_cell_log if np.isfinite(own_cell_log) else math.nan
        out[f"up{k}_lag"] = float(lag)
    return out


# ---------------------------------------------------------------- 표 단위 생성
def columns_for(depth: int, bundle: str) -> list[str]:
    """단계(1: 1단계만, 2: 2단계까지)·항목 묶음 → 새 피처 열 이름."""
    return [f"up{k}_{it}" for k in range(1, depth + 1) for it in BUNDLES[bundle]]


def build_variant_features(
    df: pd.DataFrame,
    lag_mode: str,
    *,
    algae: pd.DataFrame | None = None,
    hydro: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """df(load_base 형식)의 각 행에 make_upstream_features 를 적용(같은 인덱스). up{k}_lag 열 포함."""
    algae = load_algae() if algae is None else algae
    if lag_mode == "travel" and hydro is None:
        hydro = load_hydro()
    sub_by_target = {
        s: algae[algae["station_id"].isin([u for u in ups if u is not None])] for s, ups in CHAIN.items()
    }
    recs = []
    for sid, bd, h, own in zip(
        df["station_id"].astype(str),
        pd.to_datetime(df["base_date"]).dt.date,
        df["horizon_days"].astype(float),
        df["cell_log_t0"].astype(float),
        strict=True,
    ):
        sub = sub_by_target.get(sid, algae.iloc[0:0])
        recs.append(make_upstream_features(sub, hydro, bd, sid, h, lag_mode, own))
    return pd.DataFrame(recs, index=df.index)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """선택한 설정(CHOSEN)의 새 피처만(같은 인덱스). df = harness.load_base() 형식."""
    full = build_variant_features(df, str(CHOSEN["lag_mode"]))
    return full[columns_for(int(CHOSEN["depth"]), str(CHOSEN["bundle"]))]


# ---------------------------------------------------------------- 실험 실행
def variant_label(lag_mode: str, depth: int, bundle: str) -> str:
    return f"R2 lag={lag_mode} depth={depth} {bundle}"


def _variant_key(lag_mode: str, depth: int, bundle: str) -> str:
    return f"lag{lag_mode}_d{depth}_{bundle}"


def run_variant(
    df: pd.DataFrame, feats: pd.DataFrame, lag_mode: str, depth: int, bundle: str
) -> tuple[dict, dict[str, np.ndarray]]:
    """v1 30개 + 새 피처로 C1·C3·C2·분위 재학습 → 확장 NNLS 앙상블 → 표준 지표(캐시 사용)."""
    key = _variant_key(lag_mode, depth, bundle)
    cache = OUT_DATA / "variants" / f"{key}.parquet"
    new_cols = columns_for(depth, bundle)
    if cache.exists():
        o = pd.read_parquet(cache)
        mem = {k: o[k].to_numpy(dtype=float) for k in o.columns if k not in ("station_id", "base_date")}
    else:
        d2 = pd.concat([df, feats[new_cols]], axis=1)
        H.guard_no_2026(d2)
        mem = H.run_members(d2, H.base_columns() + new_cols)
        ens, _ = H.ensemble_expanding(d2, mem)
        mem["ens"] = ens
        cache.parent.mkdir(parents=True, exist_ok=True)
        o = df[["station_id", "base_date"]].astype(str).copy()
        for k, v in mem.items():
            o[k] = v
        o.to_parquet(cache, index=False)
    row = H.metric_row(df, mem["ens"], mem["q90"], variant_label(lag_mode, depth, bundle))
    row.update({"lag_mode": lag_mode, "depth": depth, "bundle": bundle, "n_new": len(new_cols)})
    return row, mem


def choose(base: dict, rows: list[dict]) -> tuple[dict, dict, bool]:
    """EXP-PLAN 4절: 채택 기준을 만족하는 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대(기준 미달)."""
    ok = [r for r in rows if H.adoption(base, r)["pass"]]
    pool = ok or rows
    best = max(pool, key=lambda r: r["cv_r2_raw"])
    return best, H.adoption(base, best), bool(ok)


def _site_metrics(df: pd.DataFrame, preds: dict[str, np.ndarray]) -> pd.DataFrame:
    """지점별 CV(2020~2024) r2_raw·rmse_log(집계값만)."""
    from algaecast.eval.metrics import compute_all

    cv_mask, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    sid = df["station_id"].astype(str).to_numpy()
    out = []
    for s in ("HP", "GJGR", "CS", "MGMR", "DCHN"):
        m = cv_mask & (sid == s)
        rec: dict = {"지점": s, "n": int(m.sum())}
        for name, p in preds.items():
            mm = compute_all(obs[m], p[m])
            rec[f"{name}_r2_raw"] = float(mm["r2_raw"])
            rec[f"{name}_rmse_log"] = float(mm["rmse_log"])
        out.append(rec)
    return pd.DataFrame(out)


def gain_share(df: pd.DataFrame, feats: pd.DataFrame, new_cols: list[str]) -> pd.DataFrame:
    """진단용: ≤2024 행으로 C1(v1 파라미터) 한 번 적합한 gain 중요도에서 새 피처 각각의 비중(선택에 쓰지 않음)."""
    import lightgbm as lgb

    from algaecast.models import data as D
    from algaecast.models.train import SEED, _lgb_params, _prep

    d2 = pd.concat([df, feats[new_cols]], axis=1)
    H.guard_no_2026(d2)
    tr = d2[H.years_of(d2) <= 2024]
    cols = H.base_columns() + new_cols
    _, cats = D.numeric_and_categorical(cols)
    spec = H.v1_specs()["c1"]
    y = tr["target_log"].to_numpy(dtype=float)
    m = lgb.LGBMRegressor(**_lgb_params(spec.params, SEED, objective="regression"))
    m.fit(_prep(tr[cols], cats), y, sample_weight=1.0 + spec.alpha * y, categorical_feature=cats or "auto")
    g = pd.Series(m.booster_.feature_importance("gain"), index=cols, dtype=float)
    g = g / g.sum()
    rank = g.rank(ascending=False).astype(int)
    return pd.DataFrame({"피처": new_cols, "gain 비중": g[new_cols].to_numpy(), "순위(전체)": rank[new_cols]})


def _bootstrap_delta(
    df: pd.DataFrame, base: np.ndarray, cand: np.ndarray, n: int = 1000, seed: int = 42
) -> dict[str, float]:
    """CV 행 재표본(복원) 1,000회로 Δr2_raw·Δrmse_log 의 2.5·97.5% 구간(보고용 진단, 선택에 쓰지 않음)."""
    cv_mask, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)[cv_mask]
    b, c = base[cv_mask], cand[cv_mask]
    rng = np.random.default_rng(seed)

    def r2(o: np.ndarray, p: np.ndarray) -> float:
        return 1.0 - float(np.sum((o - p) ** 2)) / float(np.sum((o - o.mean()) ** 2))

    def rmse_log(o: np.ndarray, p: np.ndarray) -> float:
        return float(np.sqrt(np.mean((np.log10(o + 1) - np.log10(p + 1)) ** 2)))

    d_r2, d_rm = [], []
    for _ in range(n):
        i = rng.integers(0, len(obs), len(obs))
        d_r2.append(r2(obs[i], c[i]) - r2(obs[i], b[i]))
        d_rm.append(rmse_log(obs[i], c[i]) - rmse_log(obs[i], b[i]))
    return {
        "d_r2_raw_lo": float(np.percentile(d_r2, 2.5)),
        "d_r2_raw_hi": float(np.percentile(d_r2, 97.5)),
        "p_d_r2_raw_le0": float(np.mean(np.array(d_r2) <= 0)),
        "d_rmse_log_lo": float(np.percentile(d_rm, 2.5)),
        "d_rmse_log_hi": float(np.percentile(d_rm, 97.5)),
    }


def _travel_summary(df: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    """travel 방식의 지점·단계별 lag 분포(일) 요약."""
    out = []
    sid = df["station_id"].astype(str)
    months = pd.to_datetime(df["base_date"]).dt.month
    for s in ("GJGR", "CS", "MGMR"):
        for k in (1, 2):
            col = f"up{k}_lag"
            v = feats.loc[(sid == s) & feats[col].notna(), col]
            vs = feats.loc[(sid == s) & feats[col].notna() & months.between(6, 10), col]
            if len(v) == 0:
                continue
            out.append(
                {
                    "지점": s,
                    "단계": k,
                    "n": len(v),
                    "lag 중앙값": float(v.median()),
                    "lag=0 비율": float((v == 0).mean()),
                    "lag=28(상한) 비율": float((v == LAG_CAP).mean()),
                    "6~10월 lag 중앙값": float(vs.median()) if len(vs) else math.nan,
                }
            )
    return pd.DataFrame(out)


def _md_table(t: pd.DataFrame, nd: int = 3) -> str:
    cols = list(t.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float | np.floating):
                cells.append("–" if not np.isfinite(v) else f"{v:.{nd}f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    budget = H.Budget(BUDGET_HOURS, EXP_ID)
    started = datetime.now()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.mkdir(parents=True, exist_ok=True)

    df = H.load_base()
    H.guard_no_2026(df)
    _, bl = H.load_baseline()
    base_row = H.metric_row(df, bl["ens"], bl["q90"], "v1 기준(하네스 재현)")

    algae, hydro = load_algae(), load_hydro()
    feats: dict[str, pd.DataFrame] = {}
    t0 = time.time()
    for lm in LAG_MODES:
        fpath = OUT_DATA / f"features_lag{lm}.parquet"
        if fpath.exists():
            f = pd.read_parquet(fpath)
            f.index = df.index
        else:
            f = build_variant_features(df, lm, algae=algae, hydro=hydro)
            f.to_parquet(fpath)
        feats[lm] = f
    log.info("피처 생성 %.1f초", time.time() - t0)

    rows: list[dict] = []
    mems: dict[str, dict[str, np.ndarray]] = {}
    status = "completed"
    try:
        for lm in LAG_MODES:
            for depth in DEPTHS:
                for bundle in BUNDLES:
                    budget.check()
                    t1 = time.time()
                    row, mem = run_variant(df, feats[lm], lm, depth, bundle)
                    rows.append(row)
                    mems[_variant_key(lm, depth, bundle)] = mem
                    log.info(
                        "%s: CV r2_raw %.3f rmse_log %.3f lead %s/%s (%.0fs)",
                        row["구성"],
                        row["cv_r2_raw"],
                        row["cv_rmse_log"],
                        row.get("lead_q90"),
                        row.get("lead_n"),
                        time.time() - t1,
                    )
    except H.BudgetExceeded as e:
        log.warning("%s", e)
        status = "time_cap"

    best, adop, met = choose(base_row, rows)
    bkey = _variant_key(best["lag_mode"], best["depth"], best["bundle"])
    bmem = mems[bkey]
    H.save_oof(
        df,
        {k: bmem[k] for k in ("c1", "c3", "c2", "q10", "q50", "q90")} | {"pred": bmem["ens"]},
        OUT_DATA / "chosen_oof.parquet",
    )
    chosen_cols = columns_for(best["depth"], best["bundle"])
    fout = df[["station_id", "base_date"]].astype(str).copy()
    for c in chosen_cols:
        fout[c] = feats[best["lag_mode"]][c].to_numpy()
    fout.to_parquet(OUT_DATA / "features.parquet", index=False)

    site_t = _site_metrics(df, {"v1": bl["ens"], "R2": bmem["ens"]})
    boot = _bootstrap_delta(df, bl["ens"], bmem["ens"])
    trav = _travel_summary(df, feats["travel"])
    elapsed = budget.elapsed_h
    meta = {
        "exp_id": EXP_ID,
        "status": status,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "elapsed_hours": elapsed,
        "budget_hours": BUDGET_HOURS,
        "chosen": {"lag_mode": best["lag_mode"], "depth": best["depth"], "bundle": best["bundle"]},
        "chosen_label": best["구성"],
        "criteria_met_by_any": met,
        "adoption": adop,
        "bootstrap_cv_delta": boot,
    }
    (OUT_REPORT / "metrics.json").write_text(
        json.dumps({"meta": meta, "rows": [base_row, *rows]}, ensure_ascii=False, indent=1, default=float)
        + "\n",
        encoding="utf-8",
    )
    (OUT_DATA / "site_metrics.json").write_text(
        site_t.to_json(orient="records", force_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    _write_readme(base_row, rows, best, adop, met, site_t, boot, trav, meta)
    print(H.standard_table([base_row, best]))
    print(json.dumps(meta, ensure_ascii=False, indent=1, default=float))
    return 0


def _write_readme(
    base_row: dict,
    rows: list[dict],
    best: dict,
    adop: dict,
    met: bool,
    site_t: pd.DataFrame,
    boot: dict,
    trav: pd.DataFrame,
    meta: dict,
) -> None:
    """보고서 초안(표·수치) → data/processed/exp/EXP-005/README_draft.md. 최종 README 는 손으로 정리(덮어쓰지 않음)."""
    srt = sorted(rows, key=lambda r: -r["cv_r2_raw"])
    grid = pd.DataFrame(
        [
            {
                "lag": r["lag_mode"],
                "단계": r["depth"],
                "묶음": r["bundle"],
                "CV r2_raw": r["cv_r2_raw"],
                "CV nse_raw": r["cv_nse_raw"],
                "CV rmse_log": r["cv_rmse_log"],
                "CV F1@10k": r["cv_f1_10k"],
                "리드타임": f"{r.get('lead_q90')}/{r.get('lead_n')}",
                "채택 기준": "통과" if H.adoption(base_row, r)["pass"] else "미달",
            }
            for r in srt
        ]
    )
    txt = f"""# {EXP_ID} (R2) 상류 지점 특징

(자동 생성 초안 — 해석은 아래 절에 보강)

## 표준 표(v1 기준 + 선택 변형 + CV 상위 변형)

{H.standard_table([base_row, best] + [r for r in srt[:5] if r is not best])}
## 보조 표

{H.detail_table([base_row, best] + [r for r in srt[:5] if r is not best])}
## 전체 변형(CV 기준, r2_raw 내림차순)

{_md_table(grid)}
## 지점별 CV

{_md_table(site_t)}
## 부트스트랩(CV 행 재표본 1,000회, 진단용)

{json.dumps(boot, ensure_ascii=False)}

## travel lag 분포

{_md_table(trav, 2)}
## 판정

선택: {best['구성']} / 채택 판정: {json.dumps(adop, ensure_ascii=False, default=float)} / 기준 만족 변형 존재: {met}

## 메타

{json.dumps(meta, ensure_ascii=False, default=float)}
"""
    (OUT_DATA / "README_draft.md").write_text(txt, encoding="utf-8")


def _site_metrics_2025(df: pd.DataFrame, preds: dict[str, np.ndarray]) -> pd.DataFrame:
    """지점별 2025(확인용) r2_raw·rmse_log(집계값만, 선택에 쓰지 않음)."""
    from algaecast.eval.metrics import compute_all

    _, fin = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    sid = df["station_id"].astype(str).to_numpy()
    out = []
    for s in ("HP", "GJGR", "CS", "MGMR", "DCHN"):
        m = fin & (sid == s)
        rec: dict = {"지점": s, "n": int(m.sum())}
        for name, p in preds.items():
            mm = compute_all(obs[m], p[m])
            rec[f"{name}_r2_raw"] = float(mm["r2_raw"])
            rec[f"{name}_rmse_log"] = float(mm["rmse_log"])
        out.append(rec)
    return pd.DataFrame(out)


def supplement() -> int:
    """보조 분석(main() 이후, 캐시 사용): ① 분위 v1 유지 시 지표 ② 새 피처 gain 비중 ③ 지점별 2025.

    ① 은 회귀 3종만 새 피처로 바꾸고 q90 경보는 v1 그대로 둔 경우의 표 — 선택에는 쓰지 않고 종합 단계 참고용.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    df = H.load_base()
    _, bl = H.load_baseline()
    base_row = H.metric_row(df, bl["ens"], bl["q90"], "v1 기준(하네스 재현)")
    feats = {
        lm: pd.read_parquet(OUT_DATA / f"features_lag{lm}.parquet").set_axis(df.index) for lm in LAG_MODES
    }
    rows_v1q = []
    for lm in LAG_MODES:
        for depth in DEPTHS:
            for bundle in BUNDLES:
                o = pd.read_parquet(OUT_DATA / "variants" / f"{_variant_key(lm, depth, bundle)}.parquet")
                r = H.metric_row(
                    df,
                    o["ens"].to_numpy(dtype=float),
                    bl["q90"],
                    variant_label(lm, depth, bundle) + " +q90 v1",
                )
                r.update({"lag_mode": lm, "depth": depth, "bundle": bundle})
                r["adoption"] = H.adoption(base_row, r)
                rows_v1q.append(r)
    ch = (str(CHOSEN["lag_mode"]), int(CHOSEN["depth"]), str(CHOSEN["bundle"]))
    gains = {
        _variant_key(*k): gain_share(df, feats[k[0]], columns_for(k[1], k[2])).to_dict(orient="records")
        for k in (ch, ("0", 2, "all4_diff"), ("3", 1, "all4"))
    }
    och = pd.read_parquet(OUT_DATA / "chosen_oof.parquet")
    s25 = _site_metrics_2025(df, {"v1": bl["ens"], "R2": och["pred"].to_numpy(dtype=float)})
    sup = {
        "base_row": base_row,
        "rows_q90_v1": rows_v1q,
        "gain_share": gains,
        "site_2025": s25.to_dict("records"),
    }
    (OUT_REPORT / "supplement.json").write_text(
        json.dumps(sup, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8"
    )
    top = sorted(rows_v1q, key=lambda r: -r["cv_r2_raw"])[:6]
    print(H.standard_table([base_row, *top]))
    for k, g in gains.items():
        print(k)
        print(_md_table(pd.DataFrame(g)))
    print(_md_table(s25))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(supplement() if "--supplement" in sys.argv[1:] else main())
