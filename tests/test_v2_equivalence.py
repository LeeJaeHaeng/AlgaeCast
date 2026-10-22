"""운영 v2(models.v2) ↔ 실험 코드(EXP-confirm C) 동등성 — 빠른 축약판(트리 수만 줄인 같은 스펙).

전체 수치(실제 하이퍼파라미터)는 scripts/check_v2_equivalence.py 가 계산한다(reports/v2/BUILD.md).
축약판도 두 경로에 같은 스펙(n_estimators 40)을 넣으므로 결과가 완전히 같아야 한다.
(a) 폴드 모드(학습 ≤2024 → 2025) vs confirm.config_members + harness.ensemble_expanding 의 2025 OOF
(b) fit_weights vs ensemble_expanding 의 2025 가중치
(c) 최종 모드(test 124행) vs confirm_2026.final_fit_predict + combine — 2026 정답은 읽지 않는다(예측끼리 비교)
데이터(features_S1·조류 원자료)가 없으면 skip.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from algaecast.features import upstream as U
from algaecast.models import data as D

NAMES = ("c1", "c3", "c2", "cg")
N_TREES = 40

pytestmark = pytest.mark.skipif(
    not (D.PROCESSED / "features_S1.parquet").exists() or not U.ALGAE_PARQUET.exists(),
    reason="features_S1·조류 원자료 없음",
)


def _logdiff(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    assert (np.isfinite(a) == np.isfinite(b)).all()
    ok = np.isfinite(a)
    return float(np.max(np.abs(np.log10(a[ok] + 1) - np.log10(b[ok] + 1))))


@pytest.fixture(scope="module")
def small_specs() -> dict:
    from algaecast.models import v2 as V2

    out = {}
    for k, s in V2.member_specs().items():
        s2 = copy.deepcopy(s)
        s2.params = {**s2.params, "n_estimators": N_TREES}
        s2.cls_params = {**s2.cls_params, "n_estimators": N_TREES}
        out[k] = s2
    return out


@pytest.fixture(scope="module")
def ctx(small_specs: dict) -> dict:
    """실험 경로(C 시드 42, 축약 스펙)와 운영 경로의 OOF·가중치."""
    from algaecast.exp import confirm as CF
    from algaecast.exp import harness as H
    from algaecast.models import v2 as V2

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(H, "v1_specs", lambda: small_specs)  # run_members·genus_members·final_fit_predict 가 쓴다
        df = H.load_base()
        f2 = CF.f2_frame(df)
        mem = CF.config_members(df, f2, 42, genus=True)
        ens, w = H.ensemble_expanding(df, mem, names=NAMES)
        frame = V2.load_training_frame()
        oof = V2.cv_members(frame, 42, specs=small_specs)
        w_v2 = V2.fit_weights(frame, 42, oof=oof)
    return {"df": df, "f2": f2, "mem": mem, "ens": ens, "w": w, "frame": frame, "oof": oof, "w_v2": w_v2}


def test_same_training_rows(ctx: dict) -> None:
    df, frame = ctx["df"], ctx["frame"]
    assert len(df) == len(frame)
    assert (df["station_id"].astype(str).to_numpy() == frame["station_id"].astype(str).to_numpy()).all()
    assert (pd.to_datetime(df["base_date"]) == pd.to_datetime(frame["base_date"])).all()
    assert (pd.to_datetime(frame["target_date"]) <= pd.Timestamp("2025-12-31")).all()
    assert np.array_equal(
        ctx["f2"].to_numpy(dtype=float), frame[U.UPSTREAM_COLS].to_numpy(dtype=float), equal_nan=True
    )


def test_b_weights(ctx: dict) -> None:
    w_v2, w = ctx["w_v2"], ctx["w"][2025]
    assert list(w_v2) == list(NAMES) == list(w)
    assert max(abs(w_v2[k] - w[k]) for k in NAMES) < 1e-12
    assert sum(w_v2.values()) == pytest.approx(1.0)


def test_members_oof(ctx: dict) -> None:
    from algaecast.models import v2 as V2

    m6 = V2.years_of(ctx["frame"]) >= 2020
    for k in NAMES:
        assert _logdiff(ctx["oof"][k][m6], ctx["mem"][k][m6]) < 1e-9, k


def test_a_fold_mode(ctx: dict, small_specs: dict) -> None:
    from algaecast.models import v2 as V2

    frame = ctx["frame"]
    yrs = V2.years_of(frame)
    model = V2.fit_final(frame[yrs <= 2024].reset_index(drop=True), weights=ctx["w_v2"], specs=small_specs)
    pred = model.predict(frame[yrs == 2025].reset_index(drop=True))
    assert _logdiff(pred, ctx["ens"][yrs == 2025]) < 1e-9


def test_c_final_mode(ctx: dict, small_specs: dict) -> None:
    from algaecast.exp import confirm_2026 as C26
    from algaecast.exp import harness as H
    from algaecast.exp import r2_upstream as R2
    from algaecast.models import v2 as V2
    from algaecast.models.ensemble import combine

    te = D.load_test_features("S1").reset_index(drop=True)
    f2_te = R2.build_variant_features(
        te, str(R2.CHOSEN["lag_mode"]), algae=R2.load_algae(last=pd.Timestamp("2026-12-31"))
    )[U.UPSTREAM_COLS]
    cols = H.base_columns() + U.UPSTREAM_COLS
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(H, "v1_specs", lambda: small_specs)
        mem_te = C26.final_fit_predict(
            pd.concat([ctx["df"], ctx["f2"]], axis=1), pd.concat([te, f2_te], axis=1), cols
        )
    w = ctx["w"][2025]
    expected = combine({k: mem_te[k] for k in NAMES}, w)
    model = V2.fit_final(ctx["frame"], weights=ctx["w_v2"], specs=small_specs)
    got = model.predict(te)  # 상류 피처는 build_upstream 이 행 기준일까지의 원자료로 계산
    assert len(got) == 124
    assert _logdiff(got, expected) < 1e-9
