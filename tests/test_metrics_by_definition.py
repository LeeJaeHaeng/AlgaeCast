"""회귀 지표 정의별 표(eval.posthoc_metrics_by_definition) — 지표 정의·집계 방식 단위 테스트.

- 통합 = 전 행 한 번 계산, 지점 평균 = 지점별 값의 단순 평균(가중 없음)
- 원단위 결정계수 = 1 − SSE/SST(= sklearn r2), 상관계수 제곱 = Pearson r², 로그 RMSE·MAE = log10(x+1)
- B0 지속성 = 최근 측정 log10(x+1) → 원단위, 결측 0
- 2025 실자료가 있으면 통합 값이 기존 보고(tbl_holdout_2025_v21.json)와 같은지(2026 은 읽지 않음)
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from algaecast.eval import posthoc_metrics_by_definition as M


def _frame() -> pd.DataFrame:
    """2지점(행 수 다름) 합성 자료."""
    return pd.DataFrame(
        {
            "station_id": ["HP", "HP", "HP", "CS", "CS", "CS", "CS", "CS"],
            "obs": [10.0, 200.0, 3000.0, 50.0, 0.0, 12000.0, 800.0, 40.0],
            "pred": [30.0, 150.0, 1000.0, 80.0, 5.0, 6000.0, 1500.0, 10.0],
        }
    )


def _nse(o: np.ndarray, p: np.ndarray) -> float:
    return float(1 - np.sum((o - p) ** 2) / np.sum((o - o.mean()) ** 2))


def test_b0_from_log() -> None:
    got = M.b0_from_log(np.array([np.nan, 0.0, 1.0, 3.0]))
    assert np.allclose(got, [0.0, 0.0, 9.0, 999.0])


def test_pooled_matches_hand_formulas() -> None:
    df = _frame()
    res = M.by_definition(df, {"m": "pred"}, sites=("HP", "CS"))["m"]["pooled"]
    o, p = df["obs"].to_numpy(), df["pred"].to_numpy()
    lo, lp = np.log10(o + 1), np.log10(p + 1)
    assert res["n"] == 8
    assert res["nse_raw"] == pytest.approx(_nse(o, p), abs=1e-12)
    assert res["r2_pearson_raw"] == pytest.approx(np.corrcoef(o, p)[0, 1] ** 2, abs=1e-12)
    assert res["rmse_log"] == pytest.approx(np.sqrt(np.mean((lo - lp) ** 2)), abs=1e-12)
    assert res["mae_log"] == pytest.approx(np.mean(np.abs(lo - lp)), abs=1e-12)
    assert res["r2_log"] == pytest.approx(_nse(lo, lp), abs=1e-12)


def test_site_mean_is_unweighted_mean_of_site_values() -> None:
    df = _frame()
    out = M.by_definition(df, {"m": "pred"}, sites=("HP", "CS"))["m"]
    assert out["n_sites"] == 2
    assert out["sites"]["HP"]["n"] == 3 and out["sites"]["CS"]["n"] == 5
    for k in M.METRIC_KEYS:
        assert out["site_mean"][k] == pytest.approx((out["sites"]["HP"][k] + out["sites"]["CS"][k]) / 2)
    g = df[df["station_id"] == "CS"]
    assert out["sites"]["CS"]["nse_raw"] == pytest.approx(_nse(g["obs"].to_numpy(), g["pred"].to_numpy()))


def test_pooled_and_site_nse_differ_by_between_site_level() -> None:
    """지점 평균만 맞히는 예측: 통합 NSE 는 지점 간 수준 차이로 높고, 지점별 NSE 는 0 → 지점 평균 0."""
    df = pd.DataFrame(
        {
            "station_id": ["HP"] * 4 + ["CS"] * 4,
            "obs": [10.0, 20.0, 30.0, 40.0, 10010.0, 10020.0, 10030.0, 10040.0],
        }
    )
    df["pred"] = df.groupby("station_id")["obs"].transform("mean")
    out = M.by_definition(df, {"m": "pred"}, sites=("HP", "CS"))["m"]
    assert out["pooled"]["nse_raw"] > 0.99
    assert out["site_mean"]["nse_raw"] == pytest.approx(0.0, abs=1e-12)


def test_perfect_prediction_and_nse_equals_r2_raw() -> None:
    df = _frame().assign(perfect=lambda d: d["obs"])
    out = M.by_definition(df, {"p": "perfect", "m": "pred"}, sites=("HP", "CS"))
    pp = out["p"]["pooled"]
    assert pp["nse_raw"] == pytest.approx(1.0) and pp["r2_pearson_raw"] == pytest.approx(1.0)
    assert pp["rmse_log"] == pytest.approx(0.0) and pp["mae_log"] == pytest.approx(0.0)
    from algaecast.eval.metrics import compute_all

    m = compute_all(df["obs"], df["pred"])
    assert out["m"]["pooled"]["nse_raw"] == pytest.approx(m["r2_raw"], abs=1e-12)


def test_missing_obs_raises() -> None:
    df = _frame()
    df.loc[0, "obs"] = np.nan
    with pytest.raises(ValueError):
        M.by_definition(df, {"m": "pred"}, sites=("HP", "CS"))


def test_main_table_layout_and_interpretation() -> None:
    df = _frame().assign(b0=lambda d: d["obs"].shift(1).fillna(0.0), v21=lambda d: d["pred"])
    one = M.by_definition(df, {"v21": "v21", "b0": "b0"}, sites=("HP", "CS"))
    res = {"2025": one, "2026": one}
    tab = M.main_table(res)
    assert len(tab) == 2 * len(M.DEFS)
    assert list(tab.columns) == ["지표", "집계", "2025 v2.1", "2025 B0 지속성", "2026 v2.1", "2026 B0 지속성"]
    assert set(tab["집계"]) == {"5지점 통합", "지점별 값의 평균"}
    line = M.interpretation(res)
    assert "\n" not in line and "로그 RMSE" in line


@pytest.mark.skipif(not (M.OOF_V21.exists() and M.OOF.exists()), reason="2025 OOF 없음")
def test_2025_pooled_matches_reported_holdout() -> None:
    """2025 같은 252행 통합 값 = tbl_holdout_2025_v21.json(전체 정밀도). 2026 은 읽지 않는다."""
    d = M.load_2025()
    assert len(d) == M.N_2025
    res = M.by_definition(d, {"v21": "v21", "b0": "b0"})
    ref = json.loads(M.REF_2025.read_text(encoding="utf-8"))["h2025"]
    for key in ("v21", "b0"):
        assert res[key]["n_sites"] == 5
        for mk in M.METRIC_KEYS:
            assert res[key]["pooled"][mk] == pytest.approx(ref[key][mk]["value"], abs=1e-9)


def test_output_json_has_only_aggregates() -> None:
    """출력 JSON 에 행 단위 정답(목표일·세포수 열)이 없다."""
    if not M.OUT_JSON.exists():
        pytest.skip("출력 없음")
    text = M.OUT_JSON.read_text(encoding="utf-8")
    for col in ("target_date", "base_date", "target_cells", "y_true"):
        assert col not in text
