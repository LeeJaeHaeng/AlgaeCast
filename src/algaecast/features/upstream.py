"""상류 지점 피처(운영 v2) — 낙동강 상류 사슬 HP → GJGR → CS → MGMR 의 바로 위 지점(1단계) 최근 측정.

EXP-005(R2) 선택 설정(lag 0, 상류 1단계, 묶음 all4_diff)을 운영용으로 옮긴 모듈이다.
실험 코드(algaecast.exp.r2_upstream)와 값이 완전히 같아야 한다(NaN 위치 포함, tests/test_v2_upstream.py).

새 피처 5열(UPSTREAM_COLS)
- up1_cell_log : 상류 지점의 obs_date ≤ base_date 인 최근 유효 측정 log10(세포수 + 1)
- up1_slope3   : 같은 기준 최근 3회 log10 세포수 기울기(log10/일, ar.py 의 cell_slope_3 과 같은 정의)
- up1_wtemp    : 같은 기준 최근 유효 수온(℃)
- up1_days     : base_date − (그 최근 유효 세포수 측정일) 일수
- up1_diff     : up1_cell_log − cell_log_t0(자기 지점 최근 측정, v1 피처)
해평(HP, 최상류)·회남(DCHN, 대청호)은 상류 지점이 없어 5열 모두 NaN 이다.

as_of 규칙(CLAUDE.md): 순수 함수 make_upstream_features 는 진입 직후 cut_as_of(raw, as_of) 로 기준일 이후 행을
버린다. 표본 프레임용 build_upstream 은 행마다 그 행의 base_date 를 as_of 로 넘기므로 학습 행(≤2025)과
2026 test 행·일일 as-of 행을 같은 함수로 계산한다. 원자료는 측정 시계열(조류경보제 5지점)뿐이며
2026 정답 격리 파일(data/processed 의 격리 parquet)은 읽지 않는다.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.config import RAW_DIR
from algaecast.features.base import cut_as_of, slope

ALGAE_PARQUET: Path = RAW_DIR / "nier_algae" / "nier_algae_2012_2026.parquet"

# 상류 사슬(낙동강 본류). 값 = 1단계 상류 지점. 회남(DCHN)·해평(HP)은 해당 없음.
UPSTREAM_OF: dict[str, str | None] = {
    "HP": None,
    "GJGR": "HP",
    "CS": "GJGR",
    "MGMR": "CS",
    "DCHN": None,
}
LAG_DAYS = 0  # EXP-005 선택: 고정 lag 0(기준일까지의 가장 최근 측정)
ITEMS: tuple[str, ...] = ("cell_log", "slope3", "wtemp", "days", "diff")
UPSTREAM_COLS: list[str] = [f"up1_{it}" for it in ITEMS]
RAW_RENAME: dict[str, str] = {"iem_bgalage_cell_co": "cells", "iem_wtrtp": "wtemp"}


# ---------------------------------------------------------------- 원자료
def prepare_algae(raw: pd.DataFrame) -> pd.DataFrame:
    """조류경보제 측정 원자료 → 열 station_id·obs_date·cells·wtemp(지점·측정일 정렬).

    raw 는 parquet(data/raw/nier_algae) 이나 수집기(NierAlgaeCollector) 출력처럼
    iem_bgalage_cell_co·iem_wtrtp 열을 갖거나, 이미 cells·wtemp 로 바뀐 형식이면 된다.
    """
    a = raw.rename(columns=RAW_RENAME)
    missing = [c for c in ("station_id", "obs_date", "cells", "wtemp") if c not in a.columns]
    if missing:
        raise KeyError(f"조류 원자료에 열이 없다: {missing}")
    a = a[["station_id", "obs_date", "cells", "wtemp"]].copy()
    a["obs_date"] = pd.to_datetime(a["obs_date"]).dt.normalize()
    a["station_id"] = a["station_id"].astype(str)
    return a.sort_values(["station_id", "obs_date"]).reset_index(drop=True)


def load_algae(path: Path = ALGAE_PARQUET) -> pd.DataFrame:
    """조류경보제 원자료(5지점 측정 시계열)를 읽는다. 날짜로 자르지 않는다 — 행마다 as_of 로 자른다."""
    raw = pd.read_parquet(path, columns=["station_id", "obs_date", "iem_bgalage_cell_co", "iem_wtrtp"])
    return prepare_algae(raw)


# ---------------------------------------------------------------- 순수 피처 함수
def upstream_point_features(algae_u: pd.DataFrame, as_of: date, lag_days: int = LAG_DAYS) -> dict[str, float]:
    """한 상류 지점의 측정(obs_date·cells·wtemp) → obs_date ≤ as_of − lag 기준 4항목.

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


def make_upstream_features(
    algae: pd.DataFrame, as_of: date, station_id: str, own_cell_log: float = math.nan
) -> dict[str, float]:
    """(조류 원자료, as_of, 지점) → 상류 1단계 피처 5개 dict. 상류 없는 지점은 모두 NaN.

    Args:
        algae: prepare_algae 형식(station_id·obs_date·cells·wtemp). 기준일 이후 행이 있어도 진입 직후 버린다.
        as_of: 예측 기준일(base_date).
        station_id: 대상 지점(HP·GJGR·CS·MGMR·DCHN).
        own_cell_log: 자기 지점 cell_log_t0(v1 피처, as_of 규칙 준수) — up1_diff 계산용.
    """
    algae = cut_as_of(algae, as_of)
    up = UPSTREAM_OF.get(str(station_id))
    if up is None:
        return {c: math.nan for c in UPSTREAM_COLS}
    pf = upstream_point_features(algae[algae["station_id"] == up], as_of, LAG_DAYS)
    out = {f"up1_{it}": pf[it] for it in ("cell_log", "slope3", "wtemp", "days")}
    own = float(own_cell_log) if own_cell_log is not None else math.nan
    out["up1_diff"] = pf["cell_log"] - own if np.isfinite(own) else math.nan
    return out


# ---------------------------------------------------------------- 표본 프레임
def build_upstream(df: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """표본 프레임(station_id·base_date·cell_log_t0) 각 행의 상류 피처 5열(같은 인덱스).

    행마다 그 행의 base_date 를 as_of 로 make_upstream_features 를 부른다(원자료는 기준일까지만 사용).
    algae 가 None 이면 data/raw/nier_algae parquet 을 읽는다.
    일일 as-of 에서는 수집한 5지점 조류 자료를 넘긴다.
    """
    a = load_algae() if algae is None else prepare_algae(algae)
    by_up = {u: a[a["station_id"] == u] for u in {v for v in UPSTREAM_OF.values() if v is not None}}
    empty = a.iloc[0:0]
    own = df["cell_log_t0"] if "cell_log_t0" in df.columns else pd.Series(math.nan, index=df.index)
    recs = []
    for sid, bd, oc in zip(
        df["station_id"].astype(str),
        pd.to_datetime(df["base_date"]).dt.date,
        pd.to_numeric(own, errors="coerce").astype(float),
        strict=True,
    ):
        up = UPSTREAM_OF.get(sid)
        sub = by_up.get(up, empty) if up is not None else empty
        recs.append(make_upstream_features(sub, bd, sid, oc))
    return pd.DataFrame(recs, index=df.index, columns=UPSTREAM_COLS).astype(float)
