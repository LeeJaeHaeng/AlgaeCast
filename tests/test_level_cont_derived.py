"""DataON 원자료 없이 가공 수위 피처 파일로 채운 두 열이 원자료로 계산한 값과 같은지(features/run.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from algaecast.features import run as FEAT


def _toy() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_id": ["HP", "HP", "CS"],
            "base_date": pd.to_datetime(["2020-06-01", "2020-06-08", "2020-06-01"]).date,
            "level_cont_t0": [np.nan] * 3,
            "level_cont_diff7": [np.nan] * 3,
            "x": [1.0, 2.0, 3.0],
        }
    )


def test_apply_derived_fills_by_key(tmp_path, monkeypatch) -> None:
    d = pd.DataFrame(
        {
            "station_id": ["CS", "HP", "HP"],
            "base_date": ["2020-06-01", "2020-06-08", "2020-06-01"],
            "level_cont_t0": [0.3, 0.2, 0.1],
            "level_cont_diff7": [-0.3, -0.2, -0.1],
        }
    )
    monkeypatch.setattr(FEAT, "PROCESSED", tmp_path)
    d.to_parquet(FEAT.level_cont_path("S1"), index=False)
    out = FEAT.apply_level_cont_derived(_toy(), "S1")
    assert list(out.columns) == list(_toy().columns)
    assert out["level_cont_t0"].tolist() == [0.1, 0.2, 0.3]
    assert out["level_cont_diff7"].tolist() == [-0.1, -0.2, -0.3]
    assert out["x"].tolist() == [1.0, 2.0, 3.0]


def test_mode_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(FEAT, "PROCESSED", tmp_path)
    monkeypatch.setattr(FEAT, "DATAON_RAW", tmp_path / "none.parquet")
    assert FEAT.level_cont_mode("S1") == "missing"
    pd.DataFrame({"station_id": [], "base_date": []}).to_parquet(FEAT.level_cont_path("S1"))
    assert FEAT.level_cont_mode("S1") == "derived"
    raw = tmp_path / "raw.parquet"
    raw.write_bytes(b"x")
    monkeypatch.setattr(FEAT, "DATAON_RAW", raw)
    assert FEAT.level_cont_mode("S1") == "raw"


@pytest.mark.skipif(
    not (FEAT.level_cont_path("S1").exists() and (FEAT.PROCESSED / "features_S1.parquet").exists()),
    reason="가공 수위 피처 파일 또는 features_S1 없음",
)
def test_derived_file_matches_features() -> None:
    """저장소의 가공 파일 = features_S1 의 두 열(원자료 기준). 지운 뒤 채우면 원래 프레임과 같다."""
    f = pd.read_parquet(FEAT.PROCESSED / "features_S1.parquet")
    blank = f.copy()
    blank[list(FEAT.LEVEL_FEATURES)] = np.nan
    pd.testing.assert_frame_equal(FEAT.apply_level_cont_derived(blank, "S1"), f, check_exact=True)
