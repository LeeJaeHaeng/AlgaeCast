"""EXP-005(2차) P5 국면·아날로그 kNN·전년도/평년 피처의 누수 테스트(모델 학습 없음).

- 순수 피처 함수(state_features·history_features): as_of 이후 행을 난수로 바꾸고 절반을 지워도 결과가 같아야 한다
  (tests/test_no_leakage.py 와 같은 방식). 평년은 as_of 연도 이전 연도만 쓴다.
- kNN 구성원: 연도 Y 행의 예측은 기준일 연도 < Y 행(그 폴드의 학습 행)의 목표값만 쓴다 → Y 이후 목표·Y 이후 피처를 바꿔도 불변.
- 국면 게이트 NNLS·국면 전문가: 연도 Y 예측은 Y 이전 자료로만 적합한다.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import r2nd_p5_regime_analog as P
from algaecast.features.base import cut_as_of

AS_OFS = [date(2017, 3, 6), date(2018, 7, 16), date(2018, 9, 3), date(2019, 1, 7)]


def _algae(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = pd.date_range("2016-01-04", "2019-12-30", freq="7D")
    a = pd.DataFrame({"obs_date": d, "cells": 10 ** rng.uniform(0, 5, len(d))})
    a.loc[a.index[::9], "cells"] = np.nan
    return a


def _tamper(a: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = a.copy()
    after = pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of)
    t.loc[after, "cells"] = rng.uniform(-1e6, 1e7, after.sum())
    return t.drop(index=t.index[after][::2]).reset_index(drop=True)


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    if a.keys() != b.keys():
        return False
    return all(
        (math.isnan(x) and math.isnan(y)) or x == y for x, y in zip(a.values(), b.values(), strict=True)
    )


# ---------------------------------------------------------------- 순수 피처 함수
@pytest.mark.parametrize("fn", [P.state_features, P.history_features])
@pytest.mark.parametrize("as_of", AS_OFS)
def test_features_ignore_future(fn, as_of: date) -> None:
    a = _algae()
    base = fn(a, as_of)
    assert any(np.isfinite(v) for v in base.values())
    for seed in (1, 2, 3):
        assert _same(base, fn(_tamper(a, as_of, seed), as_of)), f"{fn.__name__} {as_of} seed={seed}"
    assert _same(base, fn(cut_as_of(a, as_of), as_of))


def test_regime_rules() -> None:
    assert P.regime_code(1.0, 1.0) == 0  # 낮고 정체 → 평온
    assert P.regime_code(2.5, 2.0) == 1  # 100 이상에서 2배 넘게 증가
    assert P.regime_code(1.5, 0.5) == 0  # 100 미만 증가는 평온
    assert P.regime_code(3.5, 3.4) == 2  # 고수준 정체 → 정점
    assert P.regime_code(3.2, 4.0) == 3  # 고수준에서 감소
    assert P.regime_code(2.0, 2.5) == 0  # 1,000 미만에서 감소 → 평온
    assert P.regime_code(4.0, math.nan) == 2
    assert P.regime_code(math.nan, 3.0) == 0


def test_state_features_values() -> None:
    a = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(["2020-06-01", "2020-06-08", "2020-06-15"]),
            "cells": [99.0, 999.0, 9999.0],
        }
    )
    s = P.state_features(a, date(2020, 6, 15))
    assert (s["st_L0"], s["st_L1"], s["st_L2"]) == (4.0, 3.0, 2.0)
    assert s["st_regime"] == 1.0 and s["st_max4w"] == 4.0


def test_history_normal_uses_prior_years_only() -> None:
    d = pd.date_range("2016-01-04", "2018-12-31", freq="7D")
    cells = np.select([d.year == 2016, d.year == 2017], [9.0, 99.0], 999.0)  # log10 1, 2, 3
    a = pd.DataFrame({"obs_date": d, "cells": cells})
    h = P.history_features(a, date(2018, 6, 4))
    assert h["hy_prev_max"] == pytest.approx(2.0)
    assert h["hy_ytd_mean"] == pytest.approx(3.0)  # 2018-01-01 이 측정일
    assert h["hy_ytd_mean_anom"] == pytest.approx(1.5, abs=0.02)  # 평년 ≈ (1 + 2) / 2
    # 과거 연도 값을 바꾸면 평년이 바뀌고(사용 확인), as_of 이후를 바꾸면 그대로
    b = a.copy()
    b.loc[pd.to_datetime(b["obs_date"]).dt.year == 2016, "cells"] = 999.0
    assert P.history_features(b, date(2018, 6, 4))["hy_ytd_mean_anom"] != h["hy_ytd_mean_anom"]
    assert _same(h, P.history_features(_tamper(a, date(2018, 6, 4), 5), date(2018, 6, 4)))
    # 측정 시작 연도만 있으면 평년(2년 이상) 없음
    assert math.isnan(P.history_features(a, date(2017, 6, 5))["hy_ytd_mean_anom"])


# ---------------------------------------------------------------- kNN·게이트·전문가(폴드 격리)
def _frame(seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    recs = []
    for s in ("HP", "CS", "DCHN"):
        for b in pd.date_range("2017-01-02", "2021-12-27", freq="14D"):
            recs.append(
                {"station_id": s, "base_date": b.date(), "target_date": (b + pd.Timedelta(days=7)).date()}
            )
    df = pd.DataFrame(recs)
    n = len(df)
    df["target_cells"] = 10 ** rng.uniform(0, 5, n)
    df["wtemp_t0"] = rng.uniform(2, 30, n)
    df.loc[df.index[::13], "wtemp_t0"] = np.nan
    df["weir_residence_proxy"] = rng.uniform(1, 300, n)
    st = pd.DataFrame({c: rng.uniform(0, 5, n) for c in ("st_L0", "st_L1", "st_L2")})
    st["st_regime"] = rng.integers(0, 4, n).astype(float)
    return df, st


def _years(df: pd.DataFrame) -> np.ndarray:
    return pd.to_datetime(df["base_date"]).dt.year.to_numpy()


def _tamper_frame(
    df: pd.DataFrame, st: pd.DataFrame, yv: int, seed: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """연도 ≥ yv 행의 목표값, 연도 > yv 행의 피처를 난수로 바꾼다(연도 yv 행의 자기 피처는 as_of 정보라 둔다)."""
    rng = np.random.default_rng(seed)
    y = _years(df)
    d2, s2 = df.copy(), st.copy()
    tgt, fut = y >= yv, y > yv
    d2.loc[tgt, "target_cells"] = rng.uniform(0, 1e7, tgt.sum())
    d2.loc[fut, "wtemp_t0"] = rng.uniform(-50, 50, fut.sum())
    d2.loc[fut, "weir_residence_proxy"] = rng.uniform(0, 1e4, fut.sum())
    for c in ("st_L0", "st_L1", "st_L2"):
        s2.loc[fut, c] = rng.uniform(-9, 9, fut.sum())
    return d2, s2


@pytest.mark.parametrize(
    "cfg", [P.KnnCfg(5, "site", "log"), P.KnnCfg(10, "all", "raw"), P.KnnCfg(3, "site", "delta")]
)
@pytest.mark.parametrize("random_seed", [None, 11])
def test_knn_uses_only_past_years(cfg: P.KnnCfg, random_seed: int | None) -> None:
    df, st = _frame()
    base = P.knn_member(df, st, cfg, random_seed=random_seed)
    y = _years(df)
    assert np.isfinite(base[y >= 2020]).all() and np.isnan(base[y < 2020]).all()
    for yv in (2020, 2021):
        for seed in (1, 2):
            d2, s2 = _tamper_frame(df, st, yv, seed)
            out = P.knn_member(d2, s2, cfg, random_seed=random_seed)
            np.testing.assert_array_equal(out[y == yv], base[y == yv])


def test_knn_random_control_differs_and_is_seeded() -> None:
    df, st = _frame()
    cfg = P.KnnCfg(5, "site", "log")
    a, b = P.knn_member(df, st, cfg, random_seed=11), P.knn_member(df, st, cfg, random_seed=11)
    c, d = P.knn_member(df, st, cfg, random_seed=22), P.knn_member(df, st, cfg)
    np.testing.assert_array_equal(a, b)
    m = np.isfinite(a)
    assert not np.allclose(a[m], c[m]) and not np.allclose(a[m], d[m])


def test_knn_site_pool_prefers_same_site() -> None:
    """pool=site: 같은 지점 후보가 k 이상이면 이웃은 모두 같은 지점 → 다른 지점 목표를 바꿔도 불변."""
    df, st = _frame()
    cfg = P.KnnCfg(5, "site", "log")
    base = P.knn_member(df, st, cfg)
    d2 = df.copy()
    other = d2["station_id"] != "HP"
    d2.loc[other, "target_cells"] = 1e7
    out = P.knn_member(d2, st, cfg)
    hp = (df["station_id"] == "HP").to_numpy()
    np.testing.assert_array_equal(out[hp], base[hp])


def test_gated_ensemble_uses_only_past_years() -> None:
    df, st = _frame()
    rng = np.random.default_rng(3)
    obs = df["target_cells"].to_numpy()
    mem = {k: np.clip(obs * 10 ** rng.normal(0, 0.5, len(df)), 0, None) for k in ("c1", "c3", "c2", "cg")}
    groups = st["st_regime"].to_numpy(dtype=int)
    base, _ = P.gated_ensemble(df, mem, groups, min_rows=10)
    y = _years(df)
    for yv in (2020, 2021):
        d2, _ = _tamper_frame(df, st, yv, 7)
        out, _ = P.gated_ensemble(d2, mem, groups, min_rows=10)
        np.testing.assert_array_equal(out[y == yv], base[y == yv])


def test_expert_member_fold_isolation() -> None:
    df, st = _frame()
    groups = P.random_groups(st["st_regime"].to_numpy(dtype=int), 11, P.SALT_EXPERT)
    assert sorted(groups) == sorted(st["st_regime"].to_numpy(dtype=int))  # 같은 비율
    calls: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []

    def stub(tr: pd.DataFrame, va: pd.DataFrame, cols: list[str], seed: int) -> np.ndarray:
        calls.append((_years(tr), _years(va), groups[tr.index], groups[va.index]))
        return np.full(len(va), float(tr["target_cells"].mean()))

    fb = np.full(len(df), -1.0)
    base = P.expert_member(df, [], groups, 11, fb, fit=stub, min_train=5)
    assert calls
    for ty, vy, tg, vg in calls:
        assert ty.max() < vy.min() and len(set(vy)) == 1
        assert len(set(tg)) == 1 and set(tg) == set(vg)
    y = _years(df)
    for yv in (2020, 2021):
        d2, _ = _tamper_frame(df, st, yv, 9)
        out = P.expert_member(d2, [], groups, 11, fb, fit=stub, min_train=5)
        np.testing.assert_array_equal(out[y == yv], base[y == yv])
    # 학습 행이 모자란 국면은 fallback
    out = P.expert_member(df, [], groups, 11, fb, fit=stub, min_train=10_000)
    assert (out[y >= 2020] == -1.0).all()


def test_config_names_and_control() -> None:
    cfg = P.P5Config(feats=("H1",), knn=P.KnnCfg(10, "all", "raw"), experts="E4", gate=True)
    assert cfg.names == ("c1", "c3", "c2", "cg", "knn", "moe")
    assert cfg.control().ctrl and cfg.control().name == cfg.name + "_ctrl"
    m = P.merge(P.P5Config(feats=("H1",)), P.P5Config(feats=("H1", "A1"), gate=True))
    assert m.feats == ("H1", "A1") and m.gate and m.name.startswith("P5_H1+A1")
