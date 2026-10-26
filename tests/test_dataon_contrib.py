"""DATAON-contrib(DataON 유래 피처 2열 제거 비교) 모듈의 구성·지표·보고서 보조 함수 테스트(모델 학습 없음)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import yaml

from algaecast.config import CONFIG_DIR
from algaecast.exp import dataon_contrib as M
from algaecast.exp import harness as H
from algaecast.models import v2 as V2


def test_dataon_features_are_the_two_selected_level_columns() -> None:
    assert M.DATAON_FEATURES == ("level_cont_t0", "level_cont_diff7")
    sel = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))["selected"]
    assert all(c in sel for c in M.DATAON_FEATURES)
    # DataON 연속 수위에서 나오는 선별 피처는 이 두 열뿐(level_cont_* 접두어)
    assert sorted(c for c in sel if c.startswith("level_cont")) == sorted(M.DATAON_FEATURES)


def test_config_without_drops_only_dataon_columns() -> None:
    full = V2.config_v2()
    no = M.config_without()
    assert len(full.cols) == 35 and len(no.cols) == 33
    assert set(full.cols) - set(no.cols) == set(M.DATAON_FEATURES)
    assert no.members == full.members and no.feature_groups == full.feature_groups
    assert no.seed == full.seed and no.weights is None
    assert all(c in no.cols for c in full.extra_features)  # 상류 5열 유지


def test_config_without_rejects_unknown_column() -> None:
    with pytest.raises(ValueError):
        M.config_without(("no_such_feature",))
    with pytest.raises(ValueError):
        M.quantile_columns(("no_such_feature",))


def test_quantile_columns() -> None:
    assert len(M.quantile_columns()) == 30
    q = M.quantile_columns(M.DATAON_FEATURES)
    assert len(q) == 28 and not set(q) & set(M.DATAON_FEATURES)


def test_direction_labels() -> None:
    assert M.direction("rmse_log", 0.01) == "DataON 포함이 좋음"  # 빼면 오차가 커짐
    assert M.direction("rmse_log", -0.01) == "DataON 제외가 좋음"
    assert M.direction("r2_raw", 0.02) == "DataON 제외가 좋음"  # 빼면 R² 가 오름
    assert M.direction("f1_10k", -0.02) == "DataON 포함이 좋음"
    assert M.direction("r2_log", 1e-6) == "같음"


def _frame() -> pd.DataFrame:
    dates = pd.date_range("2020-01-06", "2025-12-15", freq="7D")
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"station_id": np.where(np.arange(len(dates)) % 2, "HP", "CS"), "base_date": dates})
    df["target_cells"] = rng.gamma(1.0, 5_000.0, len(df))
    return df


def test_bootstrap_delta_zero_for_identical_predictions() -> None:
    df = _frame()
    p = df["target_cells"].to_numpy() * 1.1
    out = M.bootstrap_delta(df, p, p.copy(), np.ones(len(df), dtype=bool), n_boot=50)
    for k in ("rmse_log", "r2_log", "r2_raw"):
        assert out[k]["delta"] == 0.0 and out[k]["ci95_lo"] == 0.0 and out[k]["ci95_hi"] == 0.0
        assert out[k]["n_blocks"] > 1


def test_bootstrap_delta_sign() -> None:
    df = _frame()
    obs = df["target_cells"].to_numpy()
    good, bad = obs * 1.05, obs * 3.0
    out = M.bootstrap_delta(df, bad, good, np.ones(len(df), dtype=bool), n_boot=50)
    assert out["rmse_log"]["delta"] > 0 and out["rmse_log"]["ci95_lo"] > 0


def test_max_abs_diff() -> None:
    a = np.array([1.0, np.nan, 3.0])
    assert M.max_abs_diff(a, np.array([1.0, np.nan, 3.5])) == 0.5
    assert M.max_abs_diff(a, np.array([1.0, 2.0, 3.0])) == float("inf")  # 결측 위치가 다르면 불일치


def test_keep_manual_preserves_tail() -> None:
    old = f"# 자동\n표\n{M.MANUAL_MARK}\n## 6. 수기\n본문\n"
    tail = M.keep_manual(old)
    assert tail.startswith("\n" + M.MANUAL_MARK) and "본문" in tail
    assert M.keep_manual("# 자동만\n") == ""


def test_event_table_marks_differences() -> None:
    rows = [
        {
            "station_id": "CS",
            "E": "2020-06-29",
            "D": "2020-07-06",
            "full_first_alarm": None,
            "full_lead_E_days": None,
            "no_dataon_first_alarm": "2020-06-08",
            "no_dataon_lead_E_days": 21,
        }
    ]
    t = M.event_table(rows)
    assert "놓침" in t and "2020-06-08(21일)" in t and "다름" in t
    assert "상세 없음" in M.event_table([])


@pytest.mark.skipif(not H.ALGAE_PARQUET.exists(), reason="조류 원자료 없음")
def test_leadtime_detail_matches_harness_count() -> None:
    df = _frame()
    alarm = (np.arange(len(df)) % 3 == 0).astype(float)
    rows = M.leadtime_detail(df, alarm)
    ref = H.leadtime(df, alarm)
    assert sum(r["first_alarm"] is not None for r in rows) == ref["detected"]
    assert len(rows) == ref["n_events"]
    assert all(pd.Timestamp(r["E"]) <= H.LAST_DATE for r in rows)  # 2026 사건 없음


def test_saved_results_have_no_2026_and_match_baseline() -> None:
    path = M.REPORT_DIR / "results.json"
    if not path.exists():
        pytest.skip("results.json 없음")
    res = json.loads(path.read_text(encoding="utf-8"))
    assert res["baseline_check"]["matches_reported"] is True
    for r in res.get("watch_event_detail", []):
        for k in ("E", "D", "full_first_alarm", "no_dataon_first_alarm"):
            if r[k] is not None:
                assert pd.Timestamp(r[k]) <= H.LAST_DATE
    assert res["conditions"]["full"]["A_nnls_refit"]["n_2025"] == 252


def test_offset_cancels_once_window_is_all_wamis(monkeypatch: pytest.MonkeyPatch) -> None:
    """합성 시계열: 2025년부터 상수 오프셋이 붙은 관측소는 2026 편차가 오프셋과 무관해야 한다."""
    import algaecast.features.base as FB

    days = pd.date_range("2023-01-01", "2026-03-31")
    rng = np.random.default_rng(1)
    wl = 100 + np.cumsum(rng.normal(0, 0.05, len(days)))
    off = np.where(days >= "2025-01-01", 0.3, 0.0)
    lc = pd.DataFrame({"station_code": "1234567", "obs_date": days, "wl": wl - off, "wl_adj": wl})
    site = {"station_id": "XX", "dataon_stations": [{"code": "1234567", "use": True}]}
    monkeypatch.setattr(FB, "sites_cfg", lambda: {"sites": [site]})
    out = M.offset_invariance(lc)["XX"]
    assert out["max_abs_diff_2026"] < 1e-9
    assert out["max_abs_diff_2025"] > 0.01  # 창에 2024(오프셋 0) 값이 섞이는 해는 차이가 난다
    assert out["nan_days_2026"] == []


def test_site_level_inputs_drops_unused_and_bad_wamis_rows() -> None:
    lc = pd.DataFrame(
        {
            "station_code": ["1", "1", "2", "3"],
            "obs_date": pd.to_datetime(["2024-12-31", "2025-01-01", "2025-06-01", "2025-06-01"]),
            "wl": 1.0,
            "wl_adj": 1.0,
        }
    )
    site = {
        "dataon_stations": [
            {"code": "1", "use": True, "wamis_ok": False},
            {"code": "2", "use": True},
            {"code": "3", "use": False},
        ]
    }
    got = M.site_level_inputs(lc, site)
    assert sorted(zip(got["station_code"], got["obs_date"].dt.year, strict=True)) == [
        ("1", 2024),
        ("2", 2025),
    ]
