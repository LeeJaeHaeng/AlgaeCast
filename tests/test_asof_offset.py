"""as_of 오프셋(비상용 S 모델) — 저장소 기본값은 0 이고, 0 이면 v2.1 경로·as_of 와 같다."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from algaecast.features import offset as OFF
from algaecast.models import data as D


def test_repo_default_offset_is_zero() -> None:
    OFF.as_of_offset_days.cache_clear()
    assert OFF.as_of_offset_days() == 0
    assert OFF.file_suffix() == ""
    assert OFF.data_as_of(date(2026, 7, 6)) == date(2026, 7, 6)
    assert D._features_path("S1").name == "features_S1.parquet"
    assert D._split_key("S1") == "S1"


def test_offset_one_moves_as_of_and_file(monkeypatch) -> None:
    monkeypatch.setattr(OFF, "as_of_offset_days", lambda: 1)
    assert OFF.data_as_of(date(2026, 7, 6)) == date(2026, 7, 5)
    assert OFF.file_suffix() == "_asofm1"
    assert OFF.features_file("S1", Path("p")).name == "features_S1_asofm1.parquet"
    assert D._split_key("S1") == "S1_asofm1"
