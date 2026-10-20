"""T3-c/T4-a: 공통 로더가 test 타깃을 반환하지 않음(고정), 폴드 생성기, 베이스라인 함수."""

import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from algaecast.models import baselines as B
from algaecast.models import cv as CV
from algaecast.models import data as D


def _fake_processed(tmp_path: Path, monkeypatch) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    for yr in range(2018, 2027):
        for sid in ("HP", "MGMR") if yr >= 2020 else ("HP",):
            for k in range(6):
                b = date(yr, 5 + k, 1)
                rows.append(
                    {
                        "station_id": sid,
                        "site_code": "x",
                        "base_date": b,
                        "target_date": date(yr, 5 + k, 8),
                        "horizon_days": 7.0,
                        "cell_log_t0": rng.uniform(0, 4),
                        "cell_slope_3": rng.normal(0, 0.05),
                        "wtemp_ma14": rng.uniform(5, 30),
                        "dominant_genus": "Microcystis",
                        "target_cells": float(10 ** rng.uniform(0, 4)),
                        "split": "test" if yr == 2026 else ("valid" if yr == 2025 else "train"),
                    }
                )
    df = pd.DataFrame(rows)
    df["target_log"] = np.log10(df["target_cells"] + 1)
    monkeypatch.setattr(D, "PROCESSED", tmp_path)
    from algaecast.features import run as FR

    monkeypatch.setattr(FR, "PROCESSED", tmp_path)
    monkeypatch.setattr(FR, "TEST_TARGETS_PATH", tmp_path / "test_targets_DO_NOT_USE.parquet")
    q = FR.quarantine_test_targets(df, tmp_path / "test_targets_DO_NOT_USE.parquet")
    q.to_parquet(tmp_path / "features_S1.parquet", index=False)
    splits = {
        "S1": {
            sp: [
                [r.station_id, str(r.base_date), str(r.target_date)] for r in q[q["split"] == sp].itertuples()
            ]
            for sp in ("train", "valid", "test")
        }
    }
    (tmp_path / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    return df


def test_loader_never_returns_test_targets(tmp_path, monkeypatch) -> None:
    raw = _fake_processed(tmp_path, monkeypatch)
    tv = D.load_train_valid("S1")
    assert set(tv["split"]) == {"train", "valid"} and not (tv["split"] == "test").any()
    assert tv["target_log"].notna().all()
    te = D.load_test_features("S1")
    assert (
        len(te) == int((raw["split"] == "test").sum()) and "target_log" not in te and "target_cells" not in te
    )
    stored = pd.read_parquet(tmp_path / "features_S1.parquet")
    assert stored.loc[stored["split"] == "test", "target_log"].isna().all()
    quarantine = pd.read_parquet(tmp_path / "test_targets_DO_NOT_USE.parquet")
    assert len(quarantine) == len(te) and quarantine["target_log"].notna().all()


def test_models_package_never_imports_test_targets() -> None:
    """학습·튜닝·앙상블 코드(models/, features/select)는 test 타깃 경로·함수를 참조하지 않는다."""
    root = Path(D.__file__).resolve().parents[1]
    offenders = []
    for p in list((root / "models").glob("*.py")) + [root / "features" / "select.py"]:
        text = p.read_text(encoding="utf-8")
        if p.name == "data.py":
            text = re.sub(r'""".*?"""', "", text, count=1, flags=re.S)  # docstring 의 안내 문구 제외
        if "test_targets" in text or "load_test_targets" in text or "eval.live" in text:
            offenders.append(p.name)
    assert not offenders, offenders


def test_live_loader_requires_explicit_flag() -> None:
    from algaecast.eval import live

    with pytest.raises(PermissionError):
        live.load_test_targets()


def test_year_folds_expanding_and_grouped(tmp_path, monkeypatch) -> None:
    _fake_processed(tmp_path, monkeypatch)
    df = D.load_train_valid("S1")
    folds = CV.year_folds(df, include_final=True)
    names = [f.name for f in folds]
    assert names == ["F1", "F2", "F3", "F4", "F5", "Final"]
    y = CV.year_of(df).to_numpy()
    for f in folds:
        assert (y[f.train_idx] < f.valid_year).all() and (y[f.valid_idx] == f.valid_year).all()
        assert not set(f.train_idx) & set(f.valid_idx)
    # 같은 base_date 의 지점은 같은 폴드
    f1 = folds[0]
    assert set(df.iloc[f1.valid_idx]["base_date"]).isdisjoint(df.iloc[f1.train_idx]["base_date"])
    assert "MGMR" not in set(df.iloc[f1.train_idx]["station_id"])  # F1 에서 물금 train 0


def test_baselines_run_and_cv_table(tmp_path, monkeypatch) -> None:
    _fake_processed(tmp_path, monkeypatch)
    df = D.load_train_valid("S1")
    for name, fn in B.BASELINES.items():
        if name.startswith("B4"):
            continue  # ElasticNet 은 실제 피처 파일 필요
        res = CV.cv_evaluate(df, fn, include_final=True)
        assert len(res["folds"]) == 6 and res["folds"]["rmse_log"].notna().all(), name
        assert res["oof"].notna().sum() == sum(
            len(f.valid_idx) for f in CV.year_folds(df, include_final=True)
        )
    b0 = B.b0_persistence(df, df)
    assert np.allclose(b0, 10 ** df["cell_log_t0"] - 1)
    s = CV.summarize(CV.cv_evaluate(df, B.b1_site_month_median)["folds"])
    assert "cv_rmse_log" in s and "final_rmse_log" in s
