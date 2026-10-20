"""라이브 벤치마크 매칭·누적 로직 테스트 (네트워크 없음)."""

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from algaecast.config import ROOT

spec = importlib.util.spec_from_file_location(
    "update_live_benchmark", ROOT / "scripts" / "update_live_benchmark.py"
)
lb = importlib.util.module_from_spec(spec)
sys.modules["update_live_benchmark"] = lb
spec.loader.exec_module(lb)


def _snap() -> pd.DataFrame:
    rows = []
    for k in range(1, 8):
        rows.append(("2011G26", date(2026, 10, 12), date(2026, 10, 12 + k), 1 if k < 4 else 2))
        rows.append(("3008G30", date(2026, 10, 12), date(2026, 10, 12 + k), 2))
    return pd.DataFrame(rows, columns=["site_code", "issued_date", "forecast_date", "forecast_level"]).astype(
        {"forecast_level": "Int64"}
    )


def test_build_table_matches_only_observed_target_dates():
    obs = pd.DataFrame(
        {
            "site_code": ["2011G26", "2011G26", "3008G30", "2020G33"],
            "obs_date": [date(2026, 10, 13), date(2026, 10, 19), date(2026, 10, 19), date(2026, 10, 19)],
            "obs_cells": [9_460.0, 25_000.0, 12_484.0, 5.0],
        }
    )
    t = lb.build_table(_snap(), obs)
    assert list(t.columns) == lb.COLUMNS
    assert len(t) == 3  # 해평 10-13·10-19, 회남 10-19 (칠서는 발표 없음)
    r = t.set_index(["site_code", "target_date"])
    assert (
        r.loc[("2011G26", date(2026, 10, 13)), "obs_level"] == 1
        and r.loc[("2011G26", date(2026, 10, 13)), "hit"] == 1
    )
    assert (
        r.loc[("2011G26", date(2026, 10, 19)), "mulmoa_level"] == 2
        and r.loc[("2011G26", date(2026, 10, 19)), "hit"] == 1
    )
    assert (
        r.loc[("3008G30", date(2026, 10, 19)), "obs_cells"] == 12_484
        and r.loc[("3008G30", date(2026, 10, 19)), "hit"] == 1
    )


def test_merge_existing_is_idempotent_and_updates(tmp_path: Path):
    obs = pd.DataFrame({"site_code": ["2011G26"], "obs_date": [date(2026, 10, 13)], "obs_cells": [9_460.0]})
    first = lb.build_table(_snap(), obs)
    out = tmp_path / "live.csv"
    first.to_csv(out, index=False)
    again = lb.merge_existing(first, out)
    assert len(again) == 1
    obs2 = pd.DataFrame(
        {
            "site_code": ["2011G26", "2011G26"],
            "obs_date": [date(2026, 10, 13), date(2026, 10, 15)],
            "obs_cells": [12_000.0, 500.0],
        }
    )
    updated = lb.merge_existing(lb.build_table(_snap(), obs2), out)
    assert len(updated) == 2
    row = updated.set_index("target_date").loc[date(2026, 10, 13)]
    assert row["obs_cells"] == 12_000 and row["obs_level"] == 2 and row["hit"] == 0  # 수정된 관측값으로 갱신


def test_months_helper():
    assert lb._months(date(2026, 9, 28), date(2026, 10, 26)) == [(2026, 9), (2026, 10)]
    assert lb._months(date(2025, 12, 1), date(2026, 1, 5)) == [(2025, 12), (2026, 1)]
