"""WQ-03/04 조류예측정보·AI 녹조 정밀 예측 벤치마크 (T1-e). 현재는 물모아 웹 스냅샷 로더.

수집은 ``scripts/snapshot_mulmoa_forecast.py`` 가 ``data/raw/mulmoa/YYYY-MM-DD_HHMM.csv`` 로 쌓는다
(GitHub Actions 하루 3회 + 작업 스케줄러 07시). 물모아 Open API 키가 승인되면 API 경로를 추가하고,
겹치는 발표일의 값이 웹 스냅샷과 일치하는지 검증한 뒤 전환한다.

**벤치마크 누수 규칙 (CLAUDE.md 절대 규칙의 예보 데이터 적용)**
- 발표분은 관측값이 아니라 '발표 시점에 존재한 정보'이므로, ``issued_date <= base_date`` 인 발표분만 쓴다.
  base_date 이후에 발표된 예측은 그 base_date 의 비교·피처에 절대 쓰지 않는다 (``forecasts_as_of`` 가 강제).
- 비교는 동일 (site_code, base_date, target_date) 조합에서만: 발표일 ≤ base_date 인 가장 최근 발표분의
  ``forecast_date == target_date`` 행을 쓴다. 없으면 그 조합은 벤치마크 표본에서 제외하고 n 을 명시한다.
- 물모아는 세포수가 아니라 단계(0~4)만 주므로 비교 지표는 단계 일치율·관측 단계 대비 혼동행렬이다.

**단계 코드 (물모아 조류예측정보 '단계별 범례', 2026-10-20 페이지 원문 확인)** — 유해남조류 세포수(cells/mL)
= Anabaena + Aphanizomenon + Microcystis + Oscillatoria 속 세포수 합. 우리 5지점은 모두 **상수원(혼합)** 구간.

| 코드 | 상수원(혼합)·관찰지점 | 친수(표층) | 경보 대응(상수원) |
|---|---|---|---|
| 0단계 | 1,000 미만 | 20,000 미만 | 해제/미발령 |
| 1단계 | 1,000 이상 ~ 10,000 미만 | 20,000 이상 ~ 100,000 미만 | 관심 |
| 2단계 | 10,000 이상 ~ 100,000 미만 | 100,000 이상 | 경계 (하) |
| 3단계 | 100,000 이상 ~ 1,000,000 미만 | (없음) | 경계 (상) |
| 4단계 | **1,000,000 이상** | (없음) | 조류대발생 |

범례 배경색: 0 #FFFFFF, 1 #ffff00, 2 #fda155, 3 #d8bee4, 4 #e10000 (Water.js applyCellStyle). '-' 는 미발표.
``LEVEL_BOUNDS`` 가 이 상수원 경계를 그대로 담는다. 친수 구간 지점은 ``level_from_cells`` 를 쓰면 안 된다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from algaecast.config import RAW_DIR

MULMOA_DIR: Path = RAW_DIR / "mulmoa"
SOURCE = "mulmoa_web_snapshot"
LEVEL_BOUNDS = [0, 1_000, 10_000, 100_000, 1_000_000]  # 상수원(혼합) 0~4단계 하한 (물모아 범례)


def level_from_cells(cells: pd.Series) -> pd.Series:
    """세포수 → 물모아 상수원 단계(0: <1,000, 1: <10,000, 2: <100,000, 3: <1,000,000, 4: 이상). NaN 유지."""
    c = pd.to_numeric(cells, errors="coerce")
    lvl = pd.Series(pd.NA, index=c.index, dtype="Int64")
    for i, b in enumerate(LEVEL_BOUNDS):
        lvl = lvl.mask(c >= b, i)
    return lvl


def load_snapshots(directory: Path | None = None) -> pd.DataFrame:
    """스냅샷 CSV 전부를 읽어 (issued_date, site_code/site_name, horizon_day) 유일 표로 만든다.

    같은 발표분이 여러 스냅샷에 반복 수집되므로 가장 이른 ``collected_at_kst`` 행을 남긴다
    (발표 내용이 사후 수정되면 ``n_versions`` > 1 로 표시).
    """
    directory = MULMOA_DIR if directory is None else directory
    files = sorted(directory.glob("*.csv"))
    if not files:
        return pd.DataFrame(
            columns=[
                "issued_date",
                "site_code",
                "station_id",
                "water_body",
                "site_name",
                "horizon_day",
                "forecast_date",
                "forecast_level",
                "obs_cells_latest",
                "alert_latest",
                "collected_at_kst",
                "n_versions",
                "source",
            ]
        )
    df = pd.concat(
        [pd.read_csv(f, encoding="utf-8-sig", dtype=str, keep_default_na=False) for f in files],
        ignore_index=True,
    )
    df["issued_date"] = pd.to_datetime(df["issued_date"]).dt.date
    df["forecast_date"] = pd.to_datetime(df["forecast_date"]).dt.date
    df["horizon_day"] = df["horizon_day"].astype(int)
    df["forecast_level"] = pd.to_numeric(df["forecast_level"], errors="coerce").astype("Int64")
    df["obs_cells_latest"] = pd.to_numeric(df["obs_cells_latest"], errors="coerce")
    df["collected_at_kst"] = pd.to_datetime(df["collected_at_kst"])
    key = ["issued_date", "water_body", "site_name", "horizon_day"]
    df = df.sort_values([*key, "collected_at_kst"])
    content = ["forecast_level", "alert_latest"]
    versions = df.groupby(key, sort=False)[content].nunique().max(axis=1).rename("n_versions")
    out = df.drop_duplicates(key, keep="first").merge(versions, left_on=key, right_index=True, how="left")
    out["source"] = SOURCE
    return out.reset_index(drop=True)


def forecasts_as_of(snapshots: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """``issued_date <= as_of`` 인 발표분만 남긴다. 모든 벤치마크·피처 계산은 이 함수를 거친 표만 쓴다."""
    return snapshots.loc[snapshots["issued_date"] <= as_of].copy()


def benchmark_table(snapshots: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """(site_code, base_date, target_date) 조합마다 base_date 이전 최신 발표의 target_date 단계를 붙인다.

    Args:
        snapshots: ``load_snapshots()`` 결과.
        pairs: ``site_code, base_date, target_date`` 컬럼(date)을 가진 표(eval_pairs 등).

    Returns:
        pairs + ``issued_date, forecast_level`` (발표 없으면 NaN). 지표는 forecast_level 비결측 행에서만.
    """
    rows = []
    snap = snapshots.loc[snapshots["site_code"] != ""]
    for r in pairs.itertuples(index=False):
        cand = forecasts_as_of(snap[snap["site_code"] == r.site_code], r.base_date)
        cand = cand[cand["forecast_date"] == r.target_date]
        if cand.empty:
            rows.append({"issued_date": pd.NaT, "forecast_level": pd.NA})
            continue
        best = cand.sort_values("issued_date").iloc[-1]  # base_date 이전 가장 최근 발표
        rows.append({"issued_date": best["issued_date"], "forecast_level": best["forecast_level"]})
    extra = pd.DataFrame(rows, index=pairs.index)
    out = pd.concat([pairs, extra], axis=1)
    out["forecast_level"] = out["forecast_level"].astype("Int64")
    return out
