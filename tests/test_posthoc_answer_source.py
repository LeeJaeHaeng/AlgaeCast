"""eval.posthoc_answer_source — 2026 사후 분석 정답 출처 점검 함수의 단위 테스트.

합성 자료로 사건(2회 연속 규칙)·원천 차이·as-of 입력 동일성·목표일 매칭·리드타임을 검사하고,
자료가 있으면 API 로 만든 사건이 transitions.official_events 와 같은지, 번들 2020~2025 사건이 API 와 같은지 본다.
2026 정답(격리 파일)은 읽지 않는다.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from algaecast.eval import posthoc_answer_source as PAS
from algaecast.eval.transitions import T1K, T10K

CELLS = PAS.CELLS


def _algae(sid: str, dates: list[str], cells: list[float], **extra: list) -> pd.DataFrame:
    d = pd.DataFrame({"station_id": sid, "obs_date": pd.to_datetime(dates), CELLS: cells})
    for k, v in extra.items():
        d[k] = v
    return d


def test_events_from_two_consecutive_and_cut_at_bundle_end() -> None:
    dates = ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"]
    a = _algae("CS", dates, [100.0, 20_000.0, 30_000.0, 500.0, 15_000.0])
    ev = PAS.events_from(a, T10K, 2026)
    assert list(ev.columns) == ["station_id", "발령 측정일 D", "첫 초과 측정일 E"]
    assert len(ev) == 1
    r = ev.iloc[0]
    assert str(r["발령 측정일 D"]) == "2026-06-15" and str(r["첫 초과 측정일 E"]) == "2026-06-08"
    # 번들이 첫 초과 측정에서 끝나면(두 번째 측정 없음) 사건이 생기지 않는다 — 해평 관심 2026-09-07 과 같은 경우
    assert PAS.events_from(a.iloc[:2], T10K, 2026).empty
    # 관심(1k): 100 → 20,000 은 1k 도 넘음
    assert len(PAS.events_from(a, T1K, 2026)) == 1


def test_diff_rows_and_asof_inputs() -> None:
    api = pd.concat(
        [
            _algae(
                "HP", ["2026-09-03", "2026-09-07", "2026-09-14"], [1.0, 2.0, 3.0], iem_chla=[1.0, 9.0, 1.0]
            ),
            _algae("GJGR", ["2026-09-03", "2026-09-07"], [5.0, 6.0], iem_chla=[1.0, 1.0]),
        ],
        ignore_index=True,
    )
    bundle = pd.concat(
        [
            _algae("HP", ["2026-09-03", "2026-09-07"], [1.0, 2.0], iem_chla=[1.0, np.nan]),
            _algae("GJGR", ["2026-09-03", "2026-09-07"], [5.0, 6.0], iem_chla=[1.0, 1.0]),
        ],
        ignore_index=True,
    )
    d = PAS.diff_rows(api, bundle, (CELLS, "iem_chla"))
    kinds = {(r.station_id, str(r.obs_date.date())): r.구분 for r in d.itertuples(index=False)}
    assert kinds == {("HP", "2026-09-07"): "값 차이", ("HP", "2026-09-14"): "API에만"}
    assert d.loc[d["구분"] == "값 차이", "열"].item() == "iem_chla"
    # 자기 지점: 차이 행(09-07) 전 기준일은 같고, 그 날부터는 다르다
    assert PAS.asof_inputs_same("HP", pd.Timestamp("2026-09-03"), d)
    assert not PAS.asof_inputs_same("HP", pd.Timestamp("2026-09-07"), d)
    # 상류 지점(GJGR ← HP): 상류 비교 열을 세포수로 한정하면 HP 의 클로로필a 차이는 GJGR 입력에 들어가지 않는다
    assert not PAS.asof_inputs_same("GJGR", pd.Timestamp("2026-09-07"), d)
    d_up = PAS.diff_rows(api, bundle, (CELLS,))
    assert PAS.asof_inputs_same("GJGR", pd.Timestamp("2026-09-07"), d, d_up)
    assert not PAS.asof_inputs_same("GJGR", pd.Timestamp("2026-09-14"), d, d_up)  # API 에만 있는 HP 09-14
    assert PAS.column_diff_counts(api, bundle, (CELLS, "iem_chla")) == {CELLS: 0, "iem_chla": 1}


def test_match_target_date_tie_and_tolerance() -> None:
    b = pd.Timestamp("2026-09-03")
    obs = pd.DatetimeIndex(["2026-09-07", "2026-09-13"])  # +4(차 −3), +10(차 +3) → 동률은 이른 날
    assert PAS.match_target_date(b, obs, 7, 3) == pd.Timestamp("2026-09-07")
    assert PAS.match_target_date(b, pd.DatetimeIndex(["2026-09-15"]), 7, 3) is None
    assert (
        PAS.match_target_date(b, pd.DatetimeIndex(["2026-09-03"]), 7, 10) is None
    )  # 기준일 당일은 후보 아님


def test_leadtime_from_window_starts_after_previous_exceedance() -> None:
    ev = pd.DataFrame(
        {
            "station_id": ["CS"],
            "발령 측정일 D": [pd.Timestamp("2026-07-20").date()],
            "첫 초과 측정일 E": [pd.Timestamp("2026-07-13").date()],
        }
    )
    meas = PAS.meas_for_window(
        _algae("CS", ["2026-06-29", "2026-07-06", "2026-07-13"], [12_000.0, 500.0, 11_000.0])
    )
    pred = pd.DataFrame(
        {
            "station_id": ["CS", "CS", "CS"],
            "base_date": pd.to_datetime(["2026-06-22", "2026-07-06", "2026-07-13"]),
        }
    )
    rules = {
        "항상": pd.Series([True, True, True], index=pred.index),
        "없음": pd.Series([False] * 3, index=pred.index),
    }
    s, det = PAS.leadtime_from(pred, ev, meas, rules, T10K)
    s = s.set_index("방식")
    # 창 시작 = max(E−28일, 직전 초과 06-29 다음 날) = 06-30 → 06-22 기준일은 창 밖, 07-06 이 첫 경보
    assert s.loc["항상", "사건 수"] == 1 and s.loc["항상", "선행 탐지 수"] == 1
    assert s.loc["항상", "중앙 리드(E, 일)"] == 7 and s.loc["항상", "중앙 리드(D, 일)"] == 14
    assert s.loc["항상", "경보 총수"] == 3
    assert s.loc["없음", "선행 탐지 수"] == 0 and np.isnan(s.loc["없음", "중앙 리드(E, 일)"])
    assert det["첫 경보 base_date"].astype(str).tolist() == ["2026-07-06"]


def test_clean_json_values() -> None:
    out = PAS.clean({"a": np.int64(3), "b": float("nan"), "c": [pd.Timestamp("2026-09-10"), np.float64(1.5)]})
    assert out == {"a": 3, "b": None, "c": ["2026-09-10", 1.5]}
    json.dumps(out)


def test_report_json_has_no_answer_values() -> None:
    """결과 JSON 에 정답 값 열(target_cells·target_log·target·y_true)이 없어야 한다."""
    if not PAS.OUT_JSON.exists():
        pytest.skip("보고서 JSON 없음")
    bad: list[str] = []

    def walk(o: object, path: str = "") -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("target_cells", "target_log", "target", "y_true"):
                    bad.append(f"{path}/{k}")
                walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(json.loads(PAS.OUT_JSON.read_text(encoding="utf-8")))
    assert bad == []


# ---------------------------------------------------------------- 자료가 있을 때만
def _sources() -> tuple[pd.DataFrame, pd.DataFrame]:
    from algaecast.collect.algae_source import API_PARQUET, SOURCE_PATHS
    from algaecast.config import ROOT

    if not API_PARQUET.exists() or not (ROOT / SOURCE_PATHS["bundle"]).exists():
        pytest.skip("API parquet 또는 대회 번들 없음")
    return PAS.load_measurements()


def test_events_from_reproduces_official_events_and_bundle_2020_2025() -> None:
    from algaecast.eval.transitions import official_events

    bundle, api = _sources()
    for lv in (T10K, T1K):
        ea = PAS.events_from(api, lv, 2020)
        assert PAS._events_key(ea) == PAS._events_key(official_events(lv, start_year=2020))
        eb = PAS.events_from(bundle, lv, 2020)
        y = PAS._y(ea, 2020, 2025)
        assert PAS._events_key(ea[y]) == PAS._events_key(eb[PAS._y(eb, 2020, 2025)])
