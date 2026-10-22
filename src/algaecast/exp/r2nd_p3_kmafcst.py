"""EXP-005 2차 P3 — 기상청 단기예보 과거 발표분 피처(기준일 05시 발표분, +1~+3일). 사전등록: PREREG_P3.md.

원자료: API허브 단기예보 격자자료(``nph-dfs_shrt_grd``) 과거 발표분의 5지점 격자값
(``algaecast.collect.kma_fcst_grid_hist`` → data/raw/kma_fcst_grid/calls.jsonl → ``calls_to_long``).
중기예보(+4~+7일)·기상특보는 승인된 API 가 구역 목록 조회뿐이라 자료가 없다(PREREG_P3.md 2절).

피처 정의(사용자 지시 2026-10-22, 자료 형식에 맞춘 세부는 PREREG_P3.md 3절)
- 5지점 격자(nx, ny)의 기준일 당일 05시 발표분, 없으면 직전 발표분(issued_at ≤ base_date 05:00 KST,
  24시간 안). 그보다 오래된 발표분만 있으면 결측.
- 목표일 = 기준일 +1·+2·+3일. 변수:
  최고기온(TMX), 최저기온(TMN), 강수확률(POP, 09·15·21시 최대), 하늘상태(SKY, 09·15·21시 평균),
  강수량(구 동네예보 R06 6시간 4개 합 / 단기예보 PCP 09·15·21시 평균 × 24 = 일 환산 mm).
- 결측 구조(자료 사실): POP·SKY 는 2021-06-30 발표분부터, +3일은 2021-11-29 발표분부터 있다.
- 열: ``p3_fc_<변수>_d<1|2|3>`` 15개 + ``p3_fc_issue_lag_h``·``p3_fc_available``(모형 입력 아님, 점검용).

원자료 형식(long): station_id, issued_at(발표시각 KST, tz 없는 Timestamp),
fcst_at(발효시각 KST; R06 은 6시간 구간 시작 시각), category(TMX·TMN·POP·SKY·PCP·R06),
value(float, -90 이하는 결측).
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.collect.kma_forecast import parse_pcp
from algaecast.config import RAW_DIR as RAW_ROOT
from algaecast.exp import harness as H
from algaecast.features.base import cut_as_of

RAW_DIR = RAW_ROOT / "kma_fcst_grid"
CALLS = RAW_DIR / "calls.jsonl"
LONG_PATH = RAW_DIR / "fcst_long.parquet"
ISSUE_HOUR = 5  # 05시 발표분
LEADS: tuple[int, ...] = (1, 2, 3)
VARS: tuple[str, ...] = ("ta_max", "ta_min", "pop_max", "sky_mean", "rn_day")
SAMPLE_HOURS: tuple[int, ...] = (9, 15, 21)  # POP·SKY·PCP 는 이 시각 값만 쓴다(과거 수집과 실시간을 같게)
FC_COLS: list[str] = [f"p3_fc_{v}_d{d}" for d in LEADS for v in VARS]
META_COLS: list[str] = ["p3_fc_issue_lag_h", "p3_fc_available"]
FEATURE_COLS: list[str] = FC_COLS + META_COLS
BUNDLES: dict[str, list[str]] = {  # 사전등록 묶음(PREREG_P3.md 4절). 메타 열은 모형에 넣지 않는다.
    "T": [f"p3_fc_{v}_d{d}" for d in LEADS for v in ("ta_max", "ta_min")],
    "TS": [f"p3_fc_{v}_d{d}" for d in LEADS for v in ("ta_max", "ta_min", "pop_max", "sky_mean")],
    "TSR": FC_COLS,
}
LONG_COLS = ("station_id", "issued_at", "fcst_at", "category", "value")
MISSING_BELOW = -90.0  # 격자 자료 결측값(-99)
MAX_LAG_H = 24.0  # 05시 발표분이 없을 때 대신 쓸 직전 발표분의 최대 지연(시간)
R06_N = 4  # 하루 6시간 구간 수


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


def day_values(gd: pd.DataFrame) -> dict[str, float]:
    """한 목표일의 발표분 행(v 열 = 숫자) → 변수 5개."""
    hour = pd.to_datetime(gd["fcst_at"]).dt.hour
    sampled = hour.isin(SAMPLE_HOURS).to_numpy()
    by = {c: gd.loc[gd["category"] == c, "v"].dropna() for c in ("TMX", "TMN", "R06")}
    for c in ("POP", "SKY", "PCP"):
        by[c] = gd.loc[(gd["category"] == c).to_numpy() & sampled, "v"].dropna()
    if len(by["R06"]):
        rn = float(by["R06"].sum()) if len(by["R06"]) == R06_N else math.nan
    elif len(by["PCP"]):
        rn = float(by["PCP"].mean() * 24.0) if len(by["PCP"]) == len(SAMPLE_HOURS) else math.nan
    else:
        rn = math.nan
    return {
        "ta_max": float(by["TMX"].max()) if len(by["TMX"]) else math.nan,
        "ta_min": float(by["TMN"].min()) if len(by["TMN"]) else math.nan,
        "pop_max": float(by["POP"].max()) if len(by["POP"]) else math.nan,
        "sky_mean": float(by["SKY"].mean()) if len(by["SKY"]) else math.nan,
        "rn_day": rn,
    }


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
        for v, x in day_values(gd).items():
            out[f"p3_fc_{v}_d{d}"] = x
    if all(math.isnan(out[c]) for c in FC_COLS):
        return _empty()  # +1~+3일 값이 하나도 없으면 발표분이 없는 것과 같다
    out["p3_fc_issue_lag_h"] = float((cutoff - latest) / pd.Timedelta(hours=1))
    out["p3_fc_available"] = 1.0
    return out


# ---------------------------------------------------------------- 수집 기록 → long
def calls_to_long(path: Path = CALLS) -> pd.DataFrame:
    """calls.jsonl(호출 1건 = 발표·발효·변수 하나의 5지점 값) → long.

    채택 규칙(자료 사실에 근거, PREREG_P3.md 3절):
    - TMX·TMN·SKY: 육지 격자 status 가 ok 일 때만(전부 0 = 0채움, 전부 -99 = 결측은 버림).
    - POP·PCP: 같은 (발표, 발효) 의 SKY 가 ok 일 때만(0 은 실제 0일 수 있어 SKY 로 유효성을 판단).
    - R06: ok 또는 전국 0(실제 무강수일 수 있음).
      해당 발표분의 TMX 가 ok 인 것만 쓰이도록 수집 단계에서 고른다.
    - 지점 값 ≤ -90 은 결측. R06 의 fcst_at 은 6시간 구간 시작 시각(끝 시각 - 6시간)으로 둔다.
    """
    recs = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    recs = [r for r in recs if r.get("http") == 200 and r.get("status") in ("ok", "zero_fill", "missing")]
    best: dict[tuple[str, str, str], dict] = {}
    for r in recs:  # 같은 호출이 여러 번 기록됐으면 마지막 것
        best[(r["tmfc"], r["tmef"], r["var"])] = r
    sky_ok = {(k[0], k[1]) for k, r in best.items() if k[2] == "SKY" and r["status"] == "ok"}
    rows = []
    for (tmfc, tmef, var), r in best.items():
        st = r["status"]
        if var in ("TMX", "TMN", "SKY"):
            keep = st == "ok"
        elif var in ("POP", "PCP"):
            keep = st in ("ok", "zero_fill") and (tmfc, tmef) in sky_ok
        elif var == "R06":
            keep = st in ("ok", "zero_fill")
        else:
            keep = False
        if not keep:
            continue
        issued = pd.Timestamp(pd.to_datetime(tmfc, format="%Y%m%d%H"))
        fcst = pd.Timestamp(pd.to_datetime(tmef, format="%Y%m%d%H"))
        if var == "R06":
            fcst = fcst - pd.Timedelta(hours=6)
        for sid, val in r.get("site", {}).items():
            if val is None or val <= MISSING_BELOW:
                continue
            rows.append((sid, issued, fcst, var, float(val)))
    return pd.DataFrame(rows, columns=list(LONG_COLS)).sort_values(
        ["station_id", "issued_at", "fcst_at", "category"]
    )


def load_raw(path: Path = LONG_PATH) -> pd.DataFrame:
    """data/raw/kma_fcst_grid/fcst_long.parquet(long). 없으면 FileNotFoundError."""
    if not Path(path).exists():
        raise FileNotFoundError(f"P3 원자료가 없다({path}). kma_fcst_grid_hist --to-long 으로 만든다.")
    fc = pd.read_parquet(path, columns=list(LONG_COLS))
    fc["issued_at"] = pd.to_datetime(fc["issued_at"])
    fc["fcst_at"] = pd.to_datetime(fc["fcst_at"])
    # 2026 발표분은 읽은 즉시 버린다(기준일 ≤ 2025-12-31 피처에는 쓰일 일이 없고 열람도 하지 않는다)
    return fc[fc["issued_at"] <= H.LAST_DATE + pd.Timedelta(hours=23, minutes=59)].reset_index(drop=True)


def build_features(df: pd.DataFrame, fc_long: pd.DataFrame | None = None) -> pd.DataFrame:
    """df(harness.load_base 형식)의 행마다 forecast_features → 같은 인덱스의 DataFrame(FEATURE_COLS)."""
    H.guard_no_2026(df)
    fc = load_raw() if fc_long is None else fc_long
    by_site = {s: g for s, g in fc.groupby(fc["station_id"].astype(str))}
    rows = []
    for sid, bd in zip(df["station_id"].astype(str), pd.to_datetime(df["base_date"]), strict=True):
        g = by_site.get(sid)
        rows.append(_empty() if g is None else forecast_features(g, bd, sid))
    out = pd.DataFrame(rows, index=df.index, columns=FEATURE_COLS)
    return out.astype(np.float64)
