"""T0-c: eval/metrics.py — 알려진 값·경계·오류 경로·부트스트랩 검증."""

import math

import numpy as np
import pandas as pd
import pytest

from algaecast.eval import metrics as m

OBS = np.array([0.0, 9.0, 99.0, 999.0, 20_000.0, 150_000.0])


def test_perfect_prediction_scores():
    r = m.compute_all(OBS, OBS, q10=OBS, q90=OBS, p10k=(OBS >= 10_000).astype(float))
    assert r["rmse_log"] == 0
    assert r["mae_log"] == 0
    assert r["r2_raw"] == pytest.approx(1)
    assert r["nse_raw"] == pytest.approx(1)
    assert r["r2_log"] == pytest.approx(1)
    assert r["kge_log"] == pytest.approx(1)
    assert r["f1_10k"] == 1 and r["precision_10k"] == 1 and r["recall_10k"] == 1
    assert r["n_pos_obs_10k"] == 2
    assert r["f1_1k"] == 1 and r["n_pos_obs_1k"] == 2  # 20,000·150,000 만 ≥1,000 (999 는 미만)
    assert r["picp80"] == 1 and r["mpiw80_log"] == 0 and r["mpiw80_raw"] == 0 and r["n_crossed_q"] == 0
    assert r["brier_10k"] == 0
    assert r["n"] == 6


def test_log_errors_known_values():
    obs, pred = [0, 9, 99], [9, 0, 999]  # log10(x+1): [0,1,2] vs [1,0,3] → 오차 [1,-1,1]
    assert m.rmse_log(obs, pred) == pytest.approx(1.0)
    assert m.mae_log(obs, pred) == pytest.approx(1.0)
    obs2, pred2 = [0, 0, 99], [0, 0, 9999]  # 오차 [0,0,2] → rmse ≠ mae (sqrt 누락·swap 검출)
    assert m.rmse_log(obs2, pred2) == pytest.approx(2 / math.sqrt(3))
    assert m.mae_log(obs2, pred2) == pytest.approx(2 / 3)
    assert m.rmse_log(obs2, pred2) > m.mae_log(obs2, pred2)


def test_nse_and_r2_raw_coincide_and_known_cases():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    assert m.nse_raw(obs, np.full(4, obs.mean())) == pytest.approx(0.0)  # 평균 예측 → 0
    assert m.nse_raw(obs, np.full(4, 10.0)) < 0  # 평균보다 나쁘면 음수
    pred = np.array([1.5, 1.5, 3.5, 3.5])
    assert m.nse_raw(obs, pred) == pytest.approx(m.r2_raw(obs, pred))
    assert m.nse_raw(obs, pred) == pytest.approx(1 - 1.0 / 5.0)  # SS_res 4×0.25=1, SS_tot=5
    assert math.isnan(m.nse_raw([5, 5, 5], [5, 5, 5]))  # 관측 분산 0 → NaN
    assert math.isnan(m.r2_raw([5, 5, 5], [5, 5, 5]))
    # 거의 상수인 큰 값: 두 함수가 같은 판정(상수 아님)을 해야 한다
    o = np.array([489_500.0, 489_501.0, 489_500.0])
    p = np.array([489_500.0, 489_500.0, 489_501.0])
    assert m.r2_raw(o, p) == pytest.approx(-2.0)
    assert m.nse_raw(o, p) == pytest.approx(-2.0)
    assert math.isnan(m.nse_raw([2000.7] * 7, range(1, 8)))  # 비정수 상수도 NaN (ulp 오차 무시)


def test_kge_known_values():
    obs = np.array([10.0, 100.0, 1000.0, 10_000.0])
    assert m.kge(obs, obs) == pytest.approx(1.0)
    assert m.kge(obs, 2 * obs, log=False) == pytest.approx(1 - math.sqrt(2))  # r=1, α=2, β=2
    # log 공간 알려진 값: log(obs)=[1,2,3], log(pred)=[2,3,4] → r=1, α=1, β=3/2 → 0.5
    assert m.kge([9, 99, 999], [99, 999, 9999]) == pytest.approx(0.5)
    assert math.isnan(m.kge([1, 1, 1], [1, 2, 3]))


def test_kge_constant_arrays_return_nan_regardless_of_rounding():
    obs5 = np.array([0, 50, 2000, 30_000, 120_000.0])
    for c in (2000.0, 500.0, 6.0, 20_000.0):  # log10(c+1) 의 평균이 1 ulp 어긋나도 NaN 이어야 한다
        assert math.isnan(m.kge(obs5, np.full(5, c)))
    assert math.isnan(m.kge(np.full(5, 2000.0), obs5 + 1))


def test_f1_at_threshold_and_inclusive_boundary():
    obs = [0, 20_000, 500, 15_000]
    pred = [12_000, 11_000, 0, 0]  # TP=1(20,000) FP=1(0→12,000) FN=1(15,000)
    r = m.f1_at(obs, pred, 10_000)
    assert r["precision"] == pytest.approx(0.5)
    assert r["recall"] == pytest.approx(0.5)
    assert r["f1"] == pytest.approx(0.5)
    assert r["n_pos_obs"] == 2 and r["n_pos_pred"] == 2
    none = m.f1_at([0, 10], [0, 10], 10_000)  # 양성 없음 → 0 (예외 없음)
    assert none["f1"] == 0 and none["n_pos_obs"] == 0
    assert m.f1_at([0, 20_000], [30_000, 30_000])["recall"] == 1.0
    exact = m.f1_at([10_000, 9_999], [10_000, 9_999], 10_000)  # 경계값은 '이상' → 양성
    assert exact["n_pos_obs"] == 1 and exact["n_pos_pred"] == 1 and exact["f1"] == 1


def test_interval_metrics_and_crossing():
    obs = [50.0, 500.0]
    lo, hi = [9.0, 600.0], [99.0, 900.0]  # 첫 행만 포함
    assert m.picp(obs, lo, hi) == pytest.approx(0.5)
    assert m.picp([9.0, 99.0], lo[:1] * 2, hi[:1] * 2) == 1.0  # 경계값 포함
    assert m.mpiw([9.0], [99.0]) == pytest.approx(1.0)  # log10(100) − log10(10)
    assert m.mpiw([9.0], [99.0], log=False) == pytest.approx(90.0)
    # 교차 구간은 정렬해 계산 (독립 분위 모델에서 q90<q10 발생)
    assert m.picp(obs, hi, lo) == m.picp(obs, lo, hi)
    assert m.mpiw(hi, lo) == m.mpiw(lo, hi)
    r = m.compute_all(obs, obs, q10=hi, q90=lo)
    assert r["n_crossed_q"] == 2 and r["picp80"] == pytest.approx(0.5)


def test_brier():
    obs = [20_000, 0, 50_000, 100]
    assert m.brier(obs, [1, 0, 1, 0]) == 0
    assert m.brier(obs, [0.5, 0.5, 0.5, 0.5]) == pytest.approx(0.25)
    assert m.brier(obs, [0, 1, 0, 1]) == 1
    with pytest.raises(ValueError):
        m.brier(obs, [1.5, 0, 0, 0])


def test_compute_all_matches_individual_functions_on_imperfect_data():
    pred = OBS * np.array([1.0, 2.0, 0.5, 3.0, 0.4, 1.5])
    r = m.compute_all(OBS, pred)
    assert r["rmse_log"] == pytest.approx(m.rmse_log(OBS, pred))
    assert r["mae_log"] == pytest.approx(m.mae_log(OBS, pred))
    assert r["nse_raw"] == pytest.approx(m.nse_raw(OBS, pred))
    assert r["kge_log"] == pytest.approx(m.kge(OBS, pred))
    assert r["f1_10k"] == pytest.approx(m.f1_at(OBS, pred, 10_000)["f1"])
    assert "picp80" not in r and "brier_10k" not in r


def test_validation_errors():
    with pytest.raises(ValueError):
        m.compute_all(OBS, OBS, q10=OBS)  # q90 누락
    with pytest.raises(ValueError):
        m.rmse_log([1, 2], [1])  # 길이 불일치
    with pytest.raises(ValueError):
        m.rmse_log([1, float("nan")], [1, 2])  # NaN
    with pytest.raises(ValueError):
        m.rmse_log([1, float("inf")], [1, 2])  # inf
    with pytest.raises(ValueError):
        m.rmse_log([1, -2], [1, 2])  # 음수
    with pytest.raises(ValueError):
        m.rmse_log([], [])  # 빈 배열
    with pytest.raises(ValueError):
        m.rmse_log(pd.Series([1, pd.NA], dtype="Int64"), [1, 2])  # pd.NA 도 결측으로 거부
    with pytest.raises(ValueError):
        m.brier([1, 2], [-0.1, 0.5])  # 확률 음수


def test_bootstrap_ci_is_seeded_and_brackets_point():
    rng = np.random.default_rng(0)
    obs = 10 ** rng.uniform(0, 5, size=300) - 1
    pred = obs * 10 ** rng.normal(0, 0.3, size=300)
    a = m.bootstrap_ci(obs, pred, m.rmse_log, n=300, seed=7)
    b = m.bootstrap_ci(obs, pred, m.rmse_log, n=300, seed=7)
    assert a == b  # 시드 재현
    assert a["n_boot"] == 300 and a["n_failed"] == 0 and a["method"] == "percentile"
    assert a["lo"] <= a["point"] <= a["hi"]
    assert a["lo"] < a["hi"]
    default_seed = m.bootstrap_ci(obs, pred, m.rmse_log, n=50)
    assert default_seed == m.bootstrap_ci(obs, pred, m.rmse_log, n=50, seed=42)  # config/seed.yaml = 42


def test_bootstrap_ci_coverage_sanity():
    """정규 데이터 평균의 95% 백분위 CI 가 참값을 대부분 덮어야 한다 (coverage ≈ 0.95, 느슨한 하한)."""
    rng = np.random.default_rng(123)
    hits = 0
    for i in range(60):
        obs = rng.normal(100.0, 10.0, size=80).clip(min=0)
        ci = m.bootstrap_ci(obs, obs, lambda o, p: float(o.mean()), n=200, seed=i)
        hits += ci["lo"] <= 100.0 <= ci["hi"]
    assert hits / 60 >= 0.85


def test_bootstrap_ci_cluster_keys():
    obs = np.array([0.0, 10.0, 100.0, 1000.0, 20_000.0, 50_000.0])
    pred = obs * 1.2
    sites = ["HP", "HP", "CS", "CS", "DCHN", "DCHN"]
    dates = pd.to_datetime(["2025-06-02", "2025-06-09"] * 3)
    r1d = m.bootstrap_ci(obs, pred, m.rmse_log, n=100, seed=1, groups=["a", "a", "b", "b", "c", "c"])
    assert r1d["n_boot"] == 100 and r1d["lo"] <= r1d["point"] <= r1d["hi"]
    # (site, base_date) 키: 튜플 목록 / 2열 ndarray / DataFrame / MultiIndex 모두 같은 결과
    composite = [f"{s}|{d.date()}" for s, d in zip(sites, dates, strict=True)]
    ref = m.bootstrap_ci(obs, pred, m.rmse_log, n=100, seed=1, groups=composite)
    as_tuples = m.bootstrap_ci(
        obs, pred, m.rmse_log, n=100, seed=1, groups=list(zip(sites, dates, strict=True))
    )
    as_frame = m.bootstrap_ci(
        obs, pred, m.rmse_log, n=100, seed=1, groups=pd.DataFrame({"site": sites, "base_date": dates})
    )
    as_multi = m.bootstrap_ci(
        obs, pred, m.rmse_log, n=100, seed=1, groups=pd.MultiIndex.from_arrays([sites, dates])
    )
    assert ref == as_tuples == as_frame == as_multi
    with pytest.raises(ValueError):
        m.bootstrap_ci(obs, pred, m.rmse_log, n=10, groups=["a"])
    with pytest.raises(TypeError):
        m.bootstrap_ci(obs, pred, m.f1_at, n=10)  # dict 반환 지표는 거부
    # 재표본에서 NaN 이 나오는 지표(상수 관측)는 n_failed 로 집계된다
    const = m.bootstrap_ci([5.0, 5.0, 5.0], [5.0, 6.0, 7.0], m.nse_raw, n=20, seed=3)
    assert const["n_failed"] == 20 and math.isnan(const["lo"])


def test_r2_official_is_pearson_squared_with_zero_rules():
    """공식 R²(운영사무국 공식 Q&A 2026-10-30 ②) = 원단위 피어슨 r², 예측 상수·상관 음수면 0. r2_raw(= NSE)와 다르다."""
    o = np.array([0.0, 10.0, 100.0, 1_000.0, 20_000.0])
    p = np.array([5.0, 50.0, 80.0, 3_000.0, 9_000.0])
    r = np.corrcoef(o, p)[0, 1]
    assert r > 0
    assert m.r2_official(o, p) == pytest.approx(r**2, abs=1e-12)
    assert m.r2_official(o, p) == pytest.approx(m.r2_pearson_raw(o, p), abs=1e-12)
    assert m.r2_official(o, p) != pytest.approx(m.r2_raw(o, p), abs=1e-3)  # 1 − SSE/SST 와 구분
    assert m.r2_official(o, 2.0 * p + 7.0) == pytest.approx(r**2, abs=1e-12)  # 척도·편향 불변
    assert m.r2_official(o, o[::-1]) == 0.0  # 상관 음수 → 0
    assert m.r2_pearson_raw(o, o[::-1]) > 0  # (0 규칙 없는 r² 는 양수)
    assert m.r2_official(o, np.full(5, 123.0)) == 0.0  # 예측 상수 → 0


def test_f1_official_uses_strict_threshold():
    """공식 참고지표 F1 은 10,000 '초과', f1_at 은 '이상'(조류경보제). 경계값이 없으면 같다."""
    o = np.array([10_000.0, 20_000.0, 500.0, 15_000.0])
    p = np.array([10_000.0, 30_000.0, 100.0, 9_000.0])
    assert m.f1_at(o, p)["f1"] == pytest.approx(0.8)  # ≥: TP 2(10k·20k)·FN 1(15k) → 4/5
    assert m.f1_official(o, p) == pytest.approx(2 / 3)  # >: TP 1(20k)·FN 1(15k) → 2·1/(2·1+0+1)
    o2, p2 = np.array([12_000.0, 500.0, 30_000.0]), np.array([11_000.0, 20_000.0, 5.0])
    assert m.f1_official(o2, p2) == pytest.approx(m.f1_at(o2, p2)["f1"])
