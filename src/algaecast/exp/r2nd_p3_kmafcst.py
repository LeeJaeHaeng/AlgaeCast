"""EXP-005 2차 P3 — 기상청 단기예보 과거 발표분 피처(기준일 05시 발표분, +1~+3일). 수집 불가로 평가하지 못함.

상태(2026-10-22): API허브 단기예보 자료 API 가 HTTP 403("활용신청이 필요한 API 입니다")이라
원자료를 받지 못했다(``algaecast.collect.kma_apihub_fcst`` 점검 결과,
reports/experiments/EXP-005/P3/probe.json).
이 모듈은 자료가 들어오면 바로 쓸 수 있도록 as_of 규칙 피처 함수와 누수 테스트
(tests/test_exp_r2nd_p3_kmafcst.py)만 둔다.
C + 예보 피처 평가는 하지 않았다.

피처 정의(사용자 지시)
- 5지점 격자(nx, ny)의 기준일 당일 05시 발표분, 없으면 직전 발표분(issued_at ≤ base_date 05:00 KST).
  직전 발표분은 MAX_LAG_H(24시간) 안의 것만 쓴다. 그보다 오래된 발표분만 있으면 결측으로 둔다.
- 목표일 = 기준일 +1·+2·+3일. 변수: 최고기온(TMX, 없으면 TMP 최대), 평균기온(TMP 평균), 강수량(PCP 합),
  강수확률(POP 최대), 하늘상태(SKY 평균, 1 맑음·3 구름많음·4 흐림), 풍속(WSD 평균).
- 열: ``p3_fc_<변수>_d<1|2|3>`` 18개 + ``p3_fc_issue_lag_h``(05시 기준 발표 지연 시간) + ``p3_fc_available``.

원자료 형식(long, 시간 단위): station_id, issued_at(발표시각 KST, tz 없는 Timestamp), fcst_at(발효시각 KST),
category(TMP·TMX·TMN·POP·PCP·SKY·WSD), value(float, -90 이하는 결측).
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.collect.kma_forecast import parse_pcp
from algaecast.config import RAW_DIR as RAW_ROOT
from algaecast.exp import harness as H
from algaecast.features.base import cut_as_of

RAW_DIR = RAW_ROOT / "kma_fcst_hist"
ISSUE_HOUR = 5  # 05시 발표분
LEADS: tuple[int, ...] = (1, 2, 3)
VARS: tuple[str, ...] = ("ta_max", "ta_mean", "rn_sum", "pop_max", "sky_mean", "ws_mean")
FEATURE_COLS: list[str] = [f"p3_fc_{v}_d{d}" for d in LEADS for v in VARS] + [
    "p3_fc_issue_lag_h",
    "p3_fc_available",
]
LONG_COLS = ("station_id", "issued_at", "fcst_at", "category", "value")
MISSING_BELOW = -90.0  # 격자 자료 결측값(-99 등)
MAX_LAG_H = 24.0  # 05시 발표분이 없을 때 대신 쓸 직전 발표분의 최대 지연(시간)


def issue_cutoff(as_of: date | pd.Timestamp) -> pd.Timestamp:
    """기준일 05:00 KST(tz 없는 Timestamp). 이 시각 이전·같은 발표분만 쓴다."""
    return pd.Timestamp(as_of).normalize() + pd.Timedelta(hours=ISSUE_HOUR)


def _values(g: pd.DataFrame) -> pd.Series:
    """value 를 숫자로(PCP 문자열 '강수없음'·'1mm 미만' 등도 처리), 결측 코드는 NaN."""
    v = g["value"]
    if v.dtype == object:
        num = pd.to_numeric(v, errors="coerce")
        pcp = g["category"].eq("PCP") & num.isna()
        if pcp.any():
            num.loc[pcp] = [parse_pcp(x) for x in v[pcp]]
        v = num.astype(float)
    v = v.astype(float)
    return v.where(v > MISSING_BELOW)


def _empty() -> dict[str, float]:
    out = {c: math.nan for c in FEATURE_COLS}
    out["p3_fc_available"] = 0.0
    return out


def forecast_features(fc_long: pd.DataFrame, as_of: date | pd.Timestamp, site: str) -> dict[str, float]:
    """(원자료, as_of, site) → 피처 dict. issued_at ≤ as_of 05:00 인 발표분 중 가장 늦은 것 하나만 쓴다.

    진입 직후 cut_as_of(발표일 기준)로 as_of 다음 날 이후 발표분을 버리고, 같은 날 05시 이후 발표분도 버린다.
    """
    fc = cut_as_of(fc_long, as_of, date_col="issued_at")
    cutoff = issue_cutoff(as_of)
    issued = pd.to_datetime(fc["issued_at"])
    oldest = cutoff - pd.Timedelta(hours=MAX_LAG_H)
    fc = fc[(fc["station_id"].astype(str) == str(site)) & (issued <= cutoff) & (issued >= oldest)]
    if fc.empty:
        return _empty()
    issued = pd.to_datetime(fc["issued_at"])
    latest = issued.max()
    g = fc[issued == latest].copy()
    g["v"] = _values(g).to_numpy()
    lead = (pd.to_datetime(g["fcst_at"]).dt.normalize() - pd.Timestamp(as_of).normalize()).dt.days
    out = _empty()
    for d in LEADS:
        gd = g[lead.to_numpy() == d]
        if gd.empty:
            continue
        by = {
            c: gd.loc[gd["category"] == c, "v"].dropna() for c in ("TMP", "TMX", "POP", "PCP", "SKY", "WSD")
        }
        tmx = by["TMX"]
        out[f"p3_fc_ta_max_d{d}"] = (
            float(tmx.max()) if len(tmx) else (float(by["TMP"].max()) if len(by["TMP"]) else math.nan)
        )
        out[f"p3_fc_ta_mean_d{d}"] = float(by["TMP"].mean()) if len(by["TMP"]) else math.nan
        out[f"p3_fc_rn_sum_d{d}"] = float(by["PCP"].sum()) if len(by["PCP"]) else math.nan
        out[f"p3_fc_pop_max_d{d}"] = float(by["POP"].max()) if len(by["POP"]) else math.nan
        out[f"p3_fc_sky_mean_d{d}"] = float(by["SKY"].mean()) if len(by["SKY"]) else math.nan
        out[f"p3_fc_ws_mean_d{d}"] = float(by["WSD"].mean()) if len(by["WSD"]) else math.nan
    if all(math.isnan(out[c]) for c in FEATURE_COLS[: len(LEADS) * len(VARS)]):
        return _empty()  # +1~+3일 값이 하나도 없으면 발표분이 없는 것과 같다
    out["p3_fc_issue_lag_h"] = float((cutoff - latest) / pd.Timedelta(hours=1))
    out["p3_fc_available"] = 1.0
    return out


def load_raw(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """data/raw/kma_fcst_hist/*.parquet(long). 없으면 FileNotFoundError — 2026-10-22 현재 수집 불가(403)."""
    files = sorted(Path(raw_dir).glob("*.parquet")) if Path(raw_dir).exists() else []
    if not files:
        raise FileNotFoundError(
            f"P3 원자료가 없다({raw_dir}). API허브 단기예보 격자자료 활용신청 승인 후 수집해야 한다."
        )
    fc = pd.concat([pd.read_parquet(f, columns=list(LONG_COLS)) for f in files], ignore_index=True)
    fc["issued_at"] = pd.to_datetime(fc["issued_at"])
    fc["fcst_at"] = pd.to_datetime(fc["fcst_at"])
    # 2026 발표분은 읽은 즉시 버린다(기준일 ≤ 2025-12-31 피처에는 쓰일 일이 없고 열람도 하지 않는다)
    return fc[fc["issued_at"] <= H.LAST_DATE + pd.Timedelta(hours=23, minutes=59)].reset_index(drop=True)


def build_features(df: pd.DataFrame, fc_long: pd.DataFrame | None = None) -> pd.DataFrame:
    """df(harness.load_base 형식)의 행마다 forecast_features → 같은 인덱스의 DataFrame(FEATURE_COLS).

    fc_long 을 주지 않으면 load_raw() 를 읽는다(현재는 원자료가 없어 FileNotFoundError).
    """
    H.guard_no_2026(df)
    fc = load_raw() if fc_long is None else fc_long
    by_site = {s: g for s, g in fc.groupby(fc["station_id"].astype(str))}
    rows = []
    for sid, bd in zip(df["station_id"].astype(str), pd.to_datetime(df["base_date"]), strict=True):
        g = by_site.get(sid)
        rows.append(_empty() if g is None else forecast_features(g, bd, sid))
    out = pd.DataFrame(rows, index=df.index, columns=FEATURE_COLS)
    return out.astype(np.float64)
