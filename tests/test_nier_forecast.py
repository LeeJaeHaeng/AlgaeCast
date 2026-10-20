"""물모아 스냅샷 로더·벤치마크 누수 규칙 테스트 (합성 CSV)."""

from datetime import date, timedelta

import pandas as pd

from algaecast.collect import nier_forecast as nf

COLS = [
    "collected_at_kst",
    "issued_date",
    "site_code",
    "station_id",
    "water_body",
    "site_name",
    "horizon_day",
    "forecast_date",
    "forecast_level",
    "forecast_level_label",
    "forecast_cells",
    "obs_cells_latest",
    "alert_latest",
    "source",
]


def _rows(collected: str, issued: str, level: str, alert: str = "경계") -> list[list[str]]:
    d = date.fromisoformat(issued)
    return [
        [
            collected,
            issued,
            "2011G26",
            "HP",
            "낙동강",
            "해평",
            str(k),
            (d + timedelta(days=k)).isoformat(),
            level,
            f"{level}단계",
            "",
            "12345",
            alert,
            "x",
        ]
        for k in range(1, 8)
    ]


def _write(tmp_path, name: str, rows: list[list[str]]) -> None:
    pd.DataFrame(rows, columns=COLS).to_csv(tmp_path / name, index=False, encoding="utf-8-sig")


def test_load_dedupes_versions_and_counts_changes(tmp_path):
    _write(tmp_path, "2026-10-20_0600.csv", _rows("2026-10-20 06:00:00", "2026-10-19", "2"))
    _write(tmp_path, "2026-10-20_1800.csv", _rows("2026-10-20 18:00:00", "2026-10-19", "2"))  # 동일 재수집
    _write(
        tmp_path,
        "2026-10-23_0600.csv",
        _rows("2026-10-23 06:00:00", "2026-10-22", "1") + _rows("2026-10-23 06:00:00", "2026-10-19", "3"),
    )  # 10-19 발표가 사후 수정됨
    snap = nf.load_snapshots(tmp_path)
    assert len(snap) == 14  # 발표 2건 × 7일
    first = snap[(snap.issued_date == date(2026, 10, 19)) & (snap.horizon_day == 1)].iloc[0]
    assert first["forecast_level"] == 2 and first["n_versions"] == 2  # 최초 수집값 유지, 변경 감지
    assert isinstance(first["forecast_date"], date) and first["forecast_date"] == date(2026, 10, 20)
    assert nf.load_snapshots(tmp_path / "empty").empty


def test_forecasts_as_of_enforces_issue_date_rule(tmp_path):
    _write(
        tmp_path,
        "a.csv",
        _rows("2026-10-20 06:00:00", "2026-10-19", "2") + _rows("2026-10-23 06:00:00", "2026-10-22", "1"),
    )
    snap = nf.load_snapshots(tmp_path)
    assert set(nf.forecasts_as_of(snap, date(2026, 10, 21))["issued_date"]) == {date(2026, 10, 19)}
    assert nf.forecasts_as_of(snap, date(2026, 10, 18)).empty
    assert set(nf.forecasts_as_of(snap, date(2026, 10, 22))["issued_date"]) == {
        date(2026, 10, 19),
        date(2026, 10, 22),
    }


def test_benchmark_table_uses_latest_issue_before_base_date(tmp_path):
    _write(
        tmp_path,
        "a.csv",
        _rows("2026-10-20 06:00:00", "2026-10-19", "2") + _rows("2026-10-23 06:00:00", "2026-10-22", "1"),
    )
    snap = nf.load_snapshots(tmp_path)
    pairs = pd.DataFrame(
        {
            "site_code": ["2011G26"] * 4,
            "base_date": [date(2026, 10, 20), date(2026, 10, 22), date(2026, 10, 24), date(2026, 10, 18)],
            "target_date": [date(2026, 10, 24), date(2026, 10, 27), date(2026, 10, 29), date(2026, 10, 25)],
        }
    )
    out = nf.benchmark_table(snap, pairs)
    # base 10-20: 10-19 발표(≤base) 의 +5일 → 2단계; 10-22 발표는 base 이후라 금지
    assert out.loc[0, "issued_date"] == date(2026, 10, 19) and out.loc[0, "forecast_level"] == 2
    # base 10-22: 10-22 발표(같은 날, ≤) 의 +5일 → 1단계
    assert out.loc[1, "issued_date"] == date(2026, 10, 22) and out.loc[1, "forecast_level"] == 1
    # base 10-24: 최신 발표 10-22 의 +7일 → 1단계
    assert out.loc[2, "forecast_level"] == 1
    # base 10-18: 발표 없음 → 결측
    assert pd.isna(out.loc[3, "forecast_level"])


def test_level_from_cells_boundaries():
    s = pd.Series([0, 999, 1000, 9999, 10000, 99999, 100000, 999999, 1000000, None])
    assert nf.level_from_cells(s).tolist()[:9] == [0, 0, 1, 1, 2, 2, 3, 3, 4]
    assert pd.isna(nf.level_from_cells(s).iloc[-1])
