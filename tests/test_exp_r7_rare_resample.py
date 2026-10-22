"""R7(EXP-010) 희소 사건 재표본·가중 테스트.

- 재표본·가중은 폴드 학습 구간 안에서만: 검증 연도 이상 행의 타깃·피처를 난수로 바꿔도 그 연도 OOF 가 같아야 한다
  (as_of 누수 테스트와 같은 방식, 연도 확장 폴드 기준).
- SMOGN 합성 행 성질, 가중치 함수 성질, 처리 없음(v1) = 하네스 기준 OOF 재현.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import harness as H
from algaecast.exp import r7_rare_resample as R
from algaecast.models.train import VariantSpec

COLS = ["x1", "x2", "horizon_days", "basin", "dominant_genus"]
SMALL = {
    "n_estimators": 25,
    "learning_rate": 0.1,
    "num_leaves": 7,
    "min_child_samples": 5,
    "feature_fraction": 1.0,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
}


def _specs() -> dict[str, VariantSpec]:
    return {
        "c1": VariantSpec("log_w", alpha=0.1, params=dict(SMALL)),
        "c3": VariantSpec("hurdle", params=dict(SMALL), cls_params=dict(SMALL)),
        "c2": VariantSpec("tweedie", variance_power=1.4, params=dict(SMALL)),
    }


def _frame(seed: int = 0, per_year: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    years = np.repeat(np.arange(2016, 2026), per_year)
    n = len(years)
    day = rng.integers(120, 300, size=n)
    base = pd.to_datetime([f"{y}-01-01" for y in years]) + pd.to_timedelta(day, unit="D")
    x1 = rng.normal(size=n)
    x2 = rng.uniform(0, 10, size=n)
    x2[rng.uniform(size=n) < 0.05] = np.nan
    ylog = np.clip(2.5 + 1.2 * x1 + 0.1 * np.nan_to_num(x2) + rng.normal(scale=0.4, size=n), 0, 6.5)
    return pd.DataFrame(
        {
            "station_id": rng.choice(["HP", "CS"], size=n),
            "base_date": base.date,
            "x1": x1,
            "x2": x2,
            "horizon_days": rng.choice([6.0, 7.0, 8.0], size=n),
            "basin": rng.choice(["낙동강", "금강"], size=n),
            "dominant_genus": rng.choice(["Microcystis", "Aphanizomenon", "none"], size=n),
            "target_log": ylog,
            "target_cells": 10**ylog - 1,
        }
    )


TREATS = [
    R.Treatment(resample="smogn", r_param=2),
    R.Treatment(resample="dup", r_param=3),
    R.Treatment(weight="rel", w_param=3.0),
    R.Treatment(weight="dens", w_param=0.8, resample="smogn", r_param=1, under=0.8),
]


@pytest.mark.parametrize("treat", TREATS, ids=lambda t: t.label())
@pytest.mark.parametrize("member", ["c1", "c3"])
def test_future_rows_do_not_change_oof(treat: R.Treatment, member: str) -> None:
    """연도 Y OOF 는 Y 이상 행의 타깃(·Y 초과 행의 피처)을 난수로 바꿔도 같다 — 재표본이 학습 구간 밖을 안 봄."""
    df = _frame()
    ref, _ = R.cv_member(df, COLS, member, treat, specs=_specs())
    years = H.years_of(df)
    rng = np.random.default_rng(99)
    for yv in (2020, 2022, 2024, 2025):
        d2 = df.copy()
        fut = years >= yv
        d2.loc[fut, "target_log"] = rng.uniform(0, 6.5, size=fut.sum())
        d2.loc[fut, "target_cells"] = 10 ** d2.loc[fut, "target_log"] - 1
        later = years > yv
        d2.loc[later, "x1"] = rng.normal(size=later.sum()) * 5
        d2.loc[later, "basin"] = rng.choice(["낙동강", "금강"], size=later.sum())
        out, _ = R.cv_member(d2, COLS, member, treat, specs=_specs())
        m = years == yv
        np.testing.assert_allclose(out["pred"][m], ref["pred"][m], rtol=0, atol=0)


def test_resample_receives_only_training_years(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, int, int]] = []
    orig = R.resample_train

    def spy(tr: pd.DataFrame, cols: list[str], treat: R.Treatment, rng: np.random.Generator) -> tuple:
        seen.append((int(H.years_of(tr).max()), len(tr), 0))
        return orig(tr, cols, treat, rng)

    monkeypatch.setattr(R, "resample_train", spy)
    df = _frame()
    R.cv_member(df, COLS, "c1", R.Treatment(resample="smogn", r_param=1), specs=_specs())
    # 폴드 2020~2024·Final(2025) 의 학습 구간 최대 연도 = 검증 연도 − 1
    assert [s[0] for s in seen] == list(range(2019, 2025))


def test_smogn_synth_properties() -> None:
    df = _frame(seed=3)
    rare = df["target_log"] > R.RARE_LOG
    nr = int(rare.sum())
    syn, info = R.smogn_synth(df, COLS, 2.0, np.random.default_rng(5), mode="smoter")
    assert len(syn) == info["n_synth"] == round(2.0 * nr)
    lo, hi = df.loc[rare, "target_log"].min(), df.loc[rare, "target_log"].max()
    assert syn["target_log"].between(lo - 1e-12, hi + 1e-12).all()  # 보간은 희소 범위 안
    np.testing.assert_allclose(syn["target_cells"], 10 ** syn["target_log"] - 1)
    assert set(syn["basin"]) <= set(df.loc[rare, "basin"].astype(str))
    assert set(syn["horizon_days"].dropna()) <= {6.0, 7.0, 8.0}  # 정수형 열은 반올림(이웃 값 사이)
    again, _ = R.smogn_synth(df, COLS, 2.0, np.random.default_rng(5), mode="smoter")
    pd.testing.assert_frame_equal(syn, again)  # 같은 난수 시드 → 같은 합성
    gn, ginfo = R.smogn_synth(df, COLS, 1.0, np.random.default_rng(5), mode="gn")
    assert ginfo["smoter_frac"] == 0.0 and len(gn) == nr
    sm, sinfo = R.smogn_synth(df, COLS, 1.0, np.random.default_rng(5), mode="smogn")
    assert 0.0 <= sinfo["smoter_frac"] <= 1.0


def test_resample_train_counts() -> None:
    df = _frame(seed=4)
    rare = int((df["target_log"] > R.RARE_LOG).sum())
    rng = np.random.default_rng(0)
    aug, is_orig, info = R.resample_train(df, COLS, R.Treatment(resample="dup", r_param=3), rng)
    assert len(aug) == len(df) + 2 * rare and is_orig.sum() == len(df) and info["n_synth"] == 2 * rare
    aug, is_orig, info = R.resample_train(df, COLS, R.Treatment(resample="smogn", r_param=1, under=0.8), rng)
    normal = len(df) - rare
    assert is_orig.sum() == len(df) - round(normal * 0.2)
    assert (aug.loc[is_orig, "target_log"] > R.RARE_LOG).sum() == rare  # 희소 원본 행은 모두 유지
    assert is_orig[: is_orig.sum()].all()  # 원본 행이 앞
    aug, is_orig, _ = R.resample_train(df, COLS, R.Treatment(), rng)
    assert len(aug) == len(df) and is_orig.all()


def test_weight_functions() -> None:
    y = np.linspace(0, 6, 61)
    spec = VariantSpec("log_w", alpha=0.06)
    np.testing.assert_allclose(R.sample_weights(y, R.Treatment(), spec, "c1"), 1 + 0.06 * y)
    assert R.sample_weights(y, R.Treatment(), VariantSpec("tweedie"), "c2") is None
    for t in (R.Treatment(weight="log", w_param=1.0), R.Treatment(weight="rel", w_param=3.0)):
        w = R.sample_weights(y, t, spec, "c1")
        assert (w >= 1).all() and (np.diff(w) >= 0).all()
    phi = R.relevance(np.array([R.RARE_LOG]))
    assert abs(float(phi[0]) - 0.5) < 1e-12
    rng = np.random.default_rng(0)
    yy = np.r_[rng.normal(2.5, 0.6, 500), rng.normal(4.6, 0.3, 30)]
    w = R.sample_weights(yy, R.Treatment(weight="dens", w_param=0.8), spec, "c1")
    assert (w > 0).all() and abs(w.mean() - 1) < 1e-9
    assert w[yy > 4.3].mean() > w[(yy > 2.2) & (yy < 2.8)].mean()  # 희소 구간이 더 무겁다


def test_config_helpers() -> None:
    t = R.Treatment(resample="smogn", r_param=2)
    assert R.member_names({"c1": t}) == ("c1", "c3", "c2")
    assert R.member_names({"c1r": t}) == ("c1", "c3", "c2", "c1r")
    assert R.config_label({"c1": t, "c3": t}).startswith("C1·C3 ")
    assert R.Treatment().is_v1 and not t.is_v1 and t.is_random


@pytest.mark.skipif(
    not (H.EXP_DATA / "baseline" / "oof.parquet").exists(),
    reason="하네스 기준 OOF 없음(python -m algaecast.exp.harness)",
)
def test_v1_treatment_reproduces_baseline_c1() -> None:
    df, base = H.load_baseline()
    res, _ = R.cv_member(df, H.base_columns(), "c1", R.Treatment())
    a, b = np.log10(res["pred"] + 1), np.log10(base["c1"] + 1)
    ok = np.isfinite(a) & np.isfinite(b)
    # 2020~2025 행 1,530(목표일 2026 인 2025-12 기준일 4행은 격리 — 2026-10-22)
    assert ok.sum() == 1530 and float(np.max(np.abs(a[ok] - b[ok]))) == 0.0
