"""T4-c: 분류 타깃·임계·NNLS·레지스트리 기본 계약 (합성 데이터)."""

import numpy as np
import pandas as pd
import pytest

from algaecast.models import classifier as C
from algaecast.models import registry as R
from algaecast.models.ensemble import combine, nnls_weights


def test_best_threshold_and_metrics() -> None:
    y = np.array([0, 0, 0, 1, 1, 1, 0, 1])
    p = np.array([0.1, 0.2, 0.4, 0.6, 0.7, 0.9, 0.55, 0.3])
    thr = C.best_threshold(y, p)
    m = C.cls_metrics(y, p, thr)
    assert 0.05 <= thr <= 0.95 and m["f1"] >= C.cls_metrics(y, p, 0.5)["f1"] - 1e-9
    assert m["n_pos"] == 4 and 0 <= m["brier"] <= 1 and 0 <= m["pr_auc"] <= 1


def test_add_targets_window_uses_measurements_in_4_to_10_days(tmp_path, monkeypatch) -> None:
    daily = pd.DataFrame(
        {
            "obs_date": pd.date_range("2025-06-01", periods=20),
            "is_obs": [d in (0, 7, 9, 14) for d in range(20)],
            "cells_obs": [np.nan] * 20,
        }
    )
    daily.loc[7, "cells_obs"] = 500.0
    daily.loc[9, "cells_obs"] = 20_000.0  # base 6/1 + 8일 → 창 안
    daily.loc[14, "cells_obs"] = 50_000.0  # +13일 → 창 밖
    daily.loc[0, "cells_obs"] = 100.0
    daily.to_parquet(tmp_path / "daily_HP_S1.parquet", index=False)
    monkeypatch.setattr(C, "INTERIM", tmp_path)
    df = pd.DataFrame(
        {
            "station_id": ["HP", "HP"],
            "base_date": [pd.Timestamp("2025-06-01").date(), pd.Timestamp("2025-06-08").date()],
            "target_cells": [500.0, 50_000.0],
        }
    )
    out = C.add_targets(df)
    assert out["over_target"].tolist() == [0, 1]
    assert out["over_window"].tolist() == [1, 1]  # 6/1: 6/10 의 20,000 / 6/8: 6/15 의 50,000(+7일)


def test_nnls_weights_sum_to_one_and_prefer_better_model() -> None:
    rng = np.random.default_rng(42)
    obs = 10 ** rng.uniform(1, 5, 300) - 1
    good = obs * 10 ** rng.normal(0, 0.1, 300)
    bad = obs * 10 ** rng.normal(0.5, 0.8, 300)
    w = nnls_weights({"good": good, "bad": bad}, obs)
    assert w["good"] + w["bad"] == pytest.approx(1.0, abs=1e-6) and w["good"] > 0.8
    ens = combine({"good": good, "bad": bad}, w)
    assert (ens >= 0).all() and len(ens) == 300


def test_registry_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(R, "REG_DIR", tmp_path / "models")
    monkeypatch.setattr(R, "REG_FILE", tmp_path / "models" / "registry.json")
    monkeypatch.setattr(R, "ROOT", tmp_path)
    e = R.register("regression", {"k": 1}, features=["a", "b"], metrics_holdout={"rmse_log": 0.7})
    obj, entry = R.load_current("regression")
    assert (
        obj == {"k": 1}
        and entry["version"] == e["version"]
        and entry["features_hash"] == R.features_hash(["a", "b"])
    )
    assert R.current_versions() == {"regression": e["version"]}
    with pytest.raises(KeyError):
        R.load_current("classifier")
