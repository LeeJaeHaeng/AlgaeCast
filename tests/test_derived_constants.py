"""데이터 유래 상수는 as-of 또는 학습기간 자료로만 계산한다 (FIX-v2.1 PREREG R1·R3·R4, 재발 방지).

- config/derived_constants.json 의 각 상수에 계산 자료의 마지막 날이 기록돼 있고, 그 날이 사용 시점보다 앞서야 한다.
  CV 폴드(검증 연도 V) → 임계[V−1], 2025 홀드아웃 → [2024], 제출 모델 T24·2026·운영 → [2024](2026-10-28 전환),
  v2.1 이력 → [2025].
- 폴드 프레임은 그 폴드 학습기간 임계를 적용한다(models.cv.fold_frames).
- 수위 편차는 직전 365일 평균 대비라 뒤에 자료가 붙어도 앞 날짜 값이 바뀌지 않는다.
- 폐기한 전 기간 상수(features.yaml site_caution_wtemp, level_cont_stats station_mean_wl_adj)가 남아 있지 않다.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
import yaml

from algaecast.align.run import level_anomaly_asof
from algaecast.config import CONFIG_DIR
from algaecast.features import constants as K
from algaecast.models.cv import FINAL_VALID_YEAR, FOLD_YEARS, Fold, fold_frames

DOC = json.loads(K.DERIVED_PATH.read_text(encoding="utf-8"))
FIRST_TEST_BASE = date(2026, 1, 1)  # 2026 예측·운영의 가장 이른 기준일 하한


def _last(year: int) -> date:
    return date.fromisoformat(DOC["site_caution_wtemp"][str(year)]["data_last_date"])


def test_threshold_metadata_within_year() -> None:
    for y in K.THRESHOLD_YEARS:
        s = DOC["site_caution_wtemp"][str(y)]
        assert s["data_max_year"] == y
        assert _last(y) <= date(y, 12, 31), f"임계[{y}] 에 {y} 이후 자료"
        for d in s["data_last_date_by_site"].values():
            assert d is None or date.fromisoformat(d) <= date(y, 12, 31)


@pytest.mark.parametrize("valid_year", [*FOLD_YEARS, FINAL_VALID_YEAR])
def test_fold_threshold_precedes_validation(valid_year: int) -> None:
    y = K.threshold_year_for_valid(valid_year)
    assert y == valid_year - 1
    assert _last(y) < date(valid_year, 1, 1), f"검증 {valid_year} 폴드 임계에 검증 연도 자료"


def test_final_threshold_precedes_test() -> None:
    assert K.FINAL_THRESHOLD_YEAR == 2024  # T24(학습 = 대회 split=train, 운영사무국 답변 2026-10-28)
    assert K.V21_THRESHOLD_YEAR == 2025  # v2.1 이력 재현 전용
    assert _last(K.FINAL_THRESHOLD_YEAR) < FIRST_TEST_BASE


def test_decisions_use_2024_or_earlier() -> None:
    for name, d in DOC["decisions"].items():
        assert d["data_max_year"] <= 2024, name
        if d.get("data_last_date"):
            assert date.fromisoformat(d["data_last_date"]) <= date(2024, 12, 31), name


def test_sites_yaml_follows_decision() -> None:
    sites = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))["sites"]
    dec = DOC["decisions"]["asos"]["sites"]
    for s in sites:
        assert int(s["asos_primary"]) == dec[s["station_id"]]["asos_primary"], s["station_id"]
        si = s["asos_by_var"].get("si", "primary")
        si = int(s["asos_primary"]) if si == "primary" else int(si)
        assert si == dec[s["station_id"]]["si"], s["station_id"]


def test_retired_full_period_constants_absent() -> None:
    feats = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    assert "site_caution_wtemp" not in feats
    stats = json.loads((CONFIG_DIR / "level_cont_stats.json").read_text(encoding="utf-8"))
    assert "station_mean_wl_adj" not in stats


def test_fold_frames_apply_training_period_thresholds() -> None:
    df = pd.DataFrame(
        {
            "station_id": ["HP", "CS", "HP", "CS"],
            "base_date": pd.to_datetime(["2021-07-01", "2021-07-08", "2022-07-01", "2022-07-08"]).date,
            K.WTEMP_LAST: [27.0, 25.0, 28.0, 26.0],
            "wtemp_minus_site_thresh": [np.nan] * 4,
        }
    )
    fo = Fold("F3", 2022, np.array([0, 1]), np.array([2, 3]))
    tr, va = fold_frames(df, fo)
    th = K.site_thresholds(2021)
    assert tr["wtemp_minus_site_thresh"].tolist() == pytest.approx([27.0 - th["HP"], 25.0 - th["CS"]])
    assert va["wtemp_minus_site_thresh"].tolist() == pytest.approx([28.0 - th["HP"], 26.0 - th["CS"]])


def test_fold_frames_require_wtemp_meta() -> None:
    df = pd.DataFrame(
        {"station_id": ["HP"], "base_date": [date(2021, 7, 1)], "wtemp_minus_site_thresh": [1.0]}
    )
    with pytest.raises(KeyError):
        fold_frames(df, Fold("F1", 2021, np.array([0]), np.array([0])))


def _levels(n_days: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.date_range("2020-01-01", periods=n_days)
    rows = []
    for code, base in (("A", 10.0), ("B", 50.0)):
        rows.append(
            pd.DataFrame(
                {
                    "station_code": code,
                    "obs_date": days,
                    "wl_adj": base + np.cumsum(rng.normal(0, 0.05, n_days)),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def test_level_anomaly_is_asof() -> None:
    full = _levels(900)
    days = pd.date_range("2020-01-01", periods=900)
    a_full, n_full = level_anomaly_asof(full, days)
    cut = full[full["obs_date"] < pd.Timestamp("2021-06-01")]
    days_cut = days[days < pd.Timestamp("2021-06-01")]
    a_cut, _ = level_anomaly_asof(cut, days_cut)
    pd.testing.assert_series_equal(a_cut, a_full.reindex(days_cut), check_names=False)
    # 직전 365일 평균 대비 · 180일 미만이면 결측
    assert a_full.iloc[:180].isna().all() and n_full.iloc[:180].eq(0).all()
    w = full.pivot_table(index="obs_date", columns="station_code", values="wl_adj")
    d = 500
    want = (w.iloc[d] - w.iloc[d - 365 : d].mean()).mean()
    assert a_full.iloc[d] == pytest.approx(want)


@pytest.mark.skipif(not K.NIER_PATH.exists(), reason="NIER 원자료 없음")
def test_thresholds_match_raw_recompute() -> None:
    assert K.check() == []
