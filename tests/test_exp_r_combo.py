"""EXP-011 종합 — 2026 가드·구성 조합 함수·점예측 축·선택 규칙·부트스트랩 테스트(모델 학습 없음)."""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import harness as H
from algaecast.exp import r1_variance_restore as R1
from algaecast.exp import r_combo as RC

YEARS = range(2019, 2026)
SITES = ("CS", "DCHN", "GJGR", "HP", "MGMR")


def _synthetic(seed: int = 0, per_site_year: int = 10) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """harness.load_base() 형식 축소판 + 구성원 예측(로그정규 잡음)."""
    rng = np.random.default_rng(seed)
    rows = [
        (s, pd.Timestamp(f"{y}-06-01") + pd.Timedelta(days=int(d)))
        for y in YEARS
        for s in SITES
        for d in rng.integers(0, 120, per_site_year)
    ]
    df = pd.DataFrame(rows, columns=["station_id", "base_date"])
    df["base_date"] = df["base_date"].dt.date
    n = len(df)
    z = rng.normal(2.5, 1.0, n)
    df["target_cells"] = np.clip(10 ** (z + rng.normal(0, 0.7, n)) - 1, 0, None)
    c1_log = z + rng.normal(0, 0.3, n)
    width = 0.5 + 0.3 * rng.random(n)
    preds = {
        "c1_log": c1_log,
        "c1": (10**c1_log - 1) * 1.4,
        "c1_none": 10**c1_log - 1,
        "c3": 10 ** (z + rng.normal(0, 0.3, n)) - 1,
        "c2": 10 ** (z + rng.normal(0, 0.4, n)) - 1,
        "cg": 10 ** (z + rng.normal(0, 0.35, n)) - 1,
        "q10": 10 ** (z - width) - 1,
        "q50": 10**z - 1,
        "q90": 10 ** (z + width) - 1,
    }
    preds = {k: (v if k == "c1_log" else np.clip(v, 0, None)) for k, v in preds.items()}
    return df, preds


def _with_2026(df: pd.DataFrame) -> pd.DataFrame:
    bad = df.copy()
    bad.loc[bad.index[-3:], "base_date"] = pd.Timestamp("2026-03-02").date()
    return bad


# ---------------------------------------------------------------- 2026 가드
def test_entry_points_reject_2026_rows() -> None:
    df, preds = _synthetic()
    bad = _with_2026(df)
    with pytest.raises(RuntimeError):
        RC.frame_for(bad, None, RC.Combo(), 42)
    with pytest.raises(RuntimeError):
        RC.combo_members(bad, None, RC.Combo(), 42)  # 학습 전에 멈춘다
    with pytest.raises(RuntimeError):
        RC.combo_members(bad, None, RC.Combo(t5="all_noembed_w5", m3=True), 7)
    with pytest.raises(RuntimeError):
        RC.v2_candidate(bad)
    with pytest.raises(RuntimeError):
        RC.Evaluator(bad)
    with pytest.raises(RuntimeError):
        RC.point_preds(bad, preds, m3=False)
    with pytest.raises(RuntimeError):
        RC.own_quantiles(bad, ["x"], 42)
    with pytest.raises(RuntimeError):
        RC.build_features(bad)


def test_test_split_rows_rejected() -> None:
    df, _ = _synthetic()
    with pytest.raises(RuntimeError):
        RC.frame_for(df.assign(split="test"), None, RC.Combo(), 42)


# ---------------------------------------------------------------- 구성 조합
def _all_combos() -> list[RC.Combo]:
    out = []
    for f2, f4, m3 in itertools.product((False, True), repeat=3):
        for t5 in ("", *RC.T5_VARIANTS):
            for ctrl, mask in ((0, ""), (3, ""), (5, ""), (5, "F2")):
                out.append(RC.Combo(f2=f2, f4=f4, t5=t5, m3=m3, ctrl=ctrl, ctrl_mask=mask))
    return out


def test_combo_key_roundtrip_and_parts() -> None:
    keys = set()
    for c in _all_combos():
        assert RC.parse_key(c.key) == c
        assert c.label
        assert not c.base.m3 and c.base.t5 == c.t5 and c.base.f2 == c.f2
        assert not c.genus.m3 and not c.genus.t5 and c.genus.f4 == c.f4 and c.genus.ctrl == c.ctrl
        keys.add(c.key)
    assert len(keys) == len(_all_combos())  # 키가 구성마다 다르다
    assert RC.Combo().key == "v1" and RC.parse_key("v1") == RC.Combo()
    assert RC.Combo(f2=True, t5="all_noembed_w10", m3=True).key == "F2+T5[all_noembed_w10]+M3"


@pytest.mark.parametrize("bad", ["X1", "M3+F2", "F2+F2x", "T5[]", "C5+F2"])
def test_parse_key_rejects_bad_or_noncanonical(bad: str) -> None:
    with pytest.raises(ValueError):
        RC.parse_key(bad)


def test_published_candidates_are_valid_configs() -> None:
    v2 = RC.parse_key(RC.V2["combo"])
    assert (
        v2.ctrl == 0 and RC.V2["point"] in RC.SELECTABLE_POINTS
    )  # 대조군·참고 점예측(P3)은 후보가 될 수 없다
    alt = RC.parse_key(RC.ROBUST_ALT["combo"])
    assert alt.ctrl == 0 and RC.ROBUST_ALT["point"] in RC.SELECTABLE_POINTS
    assert RC.parse_key(RC.ROBUST_ALT["q_ref"]) == RC.Combo()


def test_add_and_has() -> None:
    c = RC.Combo()
    for e in RC.ELEMENTS:
        assert not c.has(e)
    c2 = c.add("F2").add("T5", "nakgeum_noembed_w5").add("M3")
    assert c2.elements == ("F2", "T5", "M3")
    assert c2.t5 == "nakgeum_noembed_w5"
    with pytest.raises(ValueError):
        c.add("T5", "all_embed")  # 상위 후보 3개 밖
    with pytest.raises(ValueError):
        c.add("R9")


def test_feature_cols_composition() -> None:
    base = ["a", "b"]
    assert RC.feature_cols(RC.Combo(), base) == base
    assert (
        RC.feature_cols(RC.Combo(t5="all_noembed_w5", m3=True), base) == base
    )  # T5·M3 는 열을 더하지 않는다
    got = RC.feature_cols(RC.Combo(f2=True, f4=True, ctrl=3), base)
    assert got == base + RC.f2_cols() + RC.f4_cols() + ["ctrl_rnd_0", "ctrl_rnd_1", "ctrl_rnd_2"]
    assert RC.f2_cols() == ["up1_cell_log", "up1_slope3", "up1_wtemp", "up1_days", "up1_diff"]
    assert RC.f4_cols() == ["wq_tp_last", "wq_np_last", "wq_days_since"]


def test_step_candidates_and_controls_match_column_counts() -> None:
    cands, ctrls = RC.step_candidates(RC.Combo())
    assert set(cands) == set(RC.ELEMENTS)
    assert [c.t5 for c in cands["T5"]] == list(RC.T5_VARIANTS)
    assert ctrls["F2"] == RC.Combo(ctrl=len(RC.f2_cols()))
    assert ctrls["F4"] == RC.Combo(ctrl=len(RC.f4_cols()))
    cur = RC.Combo(f2=True, t5="all_noembed_w5")
    cands, ctrls = RC.step_candidates(cur)
    assert set(cands) == {"F4", "M3"}
    assert ctrls == {"F4": RC.Combo(f2=True, t5="all_noembed_w5", ctrl=3)}  # 대조군은 현재 구성 위에 난수 열


def test_control_columns_seeded_and_distinct() -> None:
    idx = pd.RangeIndex(4000)
    a = RC.control_columns(idx, 5, 42)
    b = RC.control_columns(idx, 5, 42)
    c = RC.control_columns(idx, 5, 7)
    pd.testing.assert_frame_equal(a, b)
    assert not np.allclose(a.to_numpy(), c.to_numpy())  # 시드마다 다른 난수(3벌)
    assert list(a.columns) == RC.ctrl_cols(5)
    v = a.to_numpy()
    assert abs(v.mean()) < 0.05 and abs(v.std() - 1) < 0.05 and np.isfinite(v).all()
    mask = np.zeros((4000, 2), dtype=bool)
    mask[:100, 0] = True
    mask[:50, 1] = True
    m = RC.control_columns(idx, 3, 42, mask=mask)
    assert m["ctrl_rnd_0"].notna().sum() == 100 and m["ctrl_rnd_1"].notna().sum() == 50
    assert m["ctrl_rnd_2"].notna().sum() == 100  # i % m 열의 결측 위치


def test_frame_for_aligns_new_columns_by_index() -> None:
    df, _ = _synthetic()
    df = df.set_axis(df.index + 100)
    feats = pd.DataFrame(
        {c: np.arange(len(df), dtype=float) + i for i, c in enumerate(RC.f2_cols() + RC.f4_cols())},
        index=df.index,
    ).iloc[
        ::-1
    ]  # 순서를 뒤집어도 인덱스로 맞춘다
    out = RC.frame_for(df, feats, RC.Combo(f2=True, ctrl=2), 42)
    assert list(out.columns) == list(df.columns) + RC.f2_cols() + RC.ctrl_cols(2)
    np.testing.assert_array_equal(out["up1_cell_log"].to_numpy(), np.arange(len(df), dtype=float))
    assert "wq_tp_last" not in out.columns
    same = RC.frame_for(df, None, RC.Combo(t5="all_noembed_w5", m3=True), 42)
    assert list(same.columns) == list(df.columns)
    with pytest.raises(ValueError):
        RC.frame_for(df, None, RC.Combo(f4=True), 42)


def test_jobs_for_splits_base_and_genus(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RC, "CACHE", tmp_path)
    c = RC.Combo(f2=True, t5="all_noembed_w5", m3=True)
    jobs = RC.jobs_for([c, RC.Combo(f2=True, t5="all_noembed_w5")], seeds=(42, 7))
    assert ("base", "F2+T5[all_noembed_w5]", 42) in jobs and ("cg", "F2", 7) in jobs
    assert len(jobs) == 4  # base 2 + cg 2(중복 없음)
    assert RC.cache_path("cg", c, 7) == RC.cache_path("cg", RC.Combo(f2=True, m3=True), 7)


# ---------------------------------------------------------------- 점예측 축
def test_convex_expanding_matches_r1_recombine() -> None:
    df, p = _synthetic(1)
    mem = {k: p[k] for k in ("c1", "c3", "c2")}
    fb = H.ensemble_expanding(df, p)[0]
    mine, rec = RC.convex_expanding(df, mem, fb)
    ref, _ = R1.recombine_raw(df, mem, fb, ref=fb)
    np.testing.assert_allclose(mine, ref, rtol=0, atol=1e-9, equal_nan=True)
    assert rec[2020] is None and abs(sum(rec[2025].values()) - 1) < 1e-9


def test_convex_weights_four_members_on_simplex() -> None:
    rng = np.random.default_rng(3)
    M = rng.gamma(2.0, 100.0, size=(300, 4))
    obs = M @ np.array([0.1, 0.0, 0.6, 0.3]) + rng.normal(0, 1, 300)
    w = RC.convex_weights(M, obs)
    assert w.shape == (4,) and abs(w.sum() - 1) < 1e-9 and (w >= 0).all()
    np.testing.assert_allclose(w, [0.1, 0.0, 0.6, 0.3], atol=0.02)


def test_convex_expanding_uses_only_prior_years() -> None:
    df, p = _synthetic(2)
    years = H.years_of(df)
    mem = {k: p[k] for k in ("c1", "c3", "c2", "cg")}
    fb = H.ensemble_expanding(df, p, names=("c1", "c3", "c2", "cg"))[0]
    base, _ = RC.convex_expanding(df, mem, fb)
    for cut in (2021, 2023):
        rng = np.random.default_rng(cut)
        df2 = df.copy()
        fut = years >= cut
        df2.loc[fut, "target_cells"] = rng.gamma(1.0, 5e4, fut.sum())
        mem2 = {k: np.where(years > cut, rng.gamma(1.0, 5e4, len(df)), v) for k, v in mem.items()}
        out, _ = RC.convex_expanding(df2, mem2, fb)
        keep = years <= cut
        np.testing.assert_array_equal(out[keep], base[keep])


def test_point_preds_axes() -> None:
    df, p = _synthetic(4)
    preds, info = RC.point_preds(df, p, m3=True)
    assert set(preds) == set(RC.POINTS)
    ens4 = H.ensemble_expanding(df, p, names=("c1", "c3", "c2", "cg"))[0]
    np.testing.assert_array_equal(preds["P0"], ens4)
    np.testing.assert_array_equal(preds["P2"], p["c1"])
    assert set(info["P0"][2025]) == {"c1", "c3", "c2", "cg"}
    only, _ = RC.point_preds(df, p, m3=False, points=("P0", "P1"))
    assert set(only) == {"P0", "P1"}


# ---------------------------------------------------------------- 선택 규칙
def _rec(key: str, gain: float, eligible: bool = True, element: str = "F2") -> dict:
    return {"key": key, "gain": gain, "eligible": eligible, "element": element}


def test_decide_step_rules() -> None:
    best, why = RC.decide_step([_rec("a", 0.05), _rec("b", 0.08, eligible=False), _rec("c", 0.03)])
    assert best is not None and best["key"] == "a"
    best, why = RC.decide_step([_rec("a", 0.009), _rec("b", 0.2, eligible=False)])
    assert best is None and "멈춤" in why
    best, why = RC.decide_step([_rec("a", 0.3, eligible=False)])
    assert best is None and "적격 후보 없음" in why


def test_pick_t5_prefers_eligible_variant() -> None:
    recs = [_rec("w5", 0.09, eligible=False), _rec("w10", 0.07), _rec("nk", 0.05)]
    assert RC.pick_t5(recs)["key"] == "w10"
    assert RC.pick_t5([_rec("w5", 0.09, False), _rec("w10", 0.07, False)])["key"] == "w5"


# ---------------------------------------------------------------- 부트스트랩
def test_block_bootstrap_identity_and_sign() -> None:
    df, p = _synthetic(5)
    same = RC.block_bootstrap(df, [p["c1"]] * 3, [p["c1"]] * 3, n_boot=200)
    assert same["delta"] == 0 and same["ci95"] == [0.0, 0.0] and same["n_blocks"] == 25
    obs = df["target_cells"].to_numpy(dtype=float)
    better = RC.block_bootstrap(df, [obs * 0.9 + p["c3"] * 0.1] * 3, [p["c3"]] * 3, n_boot=200, blocks="year")
    assert better["n_blocks"] == 5 and better["delta"] > 0 and better["p_gt0"] > 0.9
    cv, _ = H.masks(df)
    full = RC.r2_fast(obs[cv], (obs * 0.9 + p["c3"] * 0.1)[cv]) - RC.r2_fast(obs[cv], p["c3"][cv])
    assert better["delta"] == pytest.approx(full, abs=1e-12)
