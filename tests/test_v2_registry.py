"""v2 레지스트리 저장·로드·예측, 제출 파일 형식, 동결 검증 스크립트, freeze_v2 --dry-run.

- 합성 데이터: V2Model → registry(kind=ensemble_v2) 저장·로드 → 예측 동일, 구성 왕복, 가중치 합 1.
- 실제 데이터(없으면 skip): 축약 v2 모델을 임시 레지스트리(분류기·분위 = v1 파일 사본)에 등록 →
  make_submission 124행·sample 순서·정수·NaN/음수 없음·UTF-8 BOM, 분위·분류기 출력이 v1 경로와 같음,
  as-of 피처에 상류 열 부착(v2)·미부착(v1). freeze_v2 --dry-run 이 models/·submission/ 을 건드리지 않음.
- verify_frozen: FROZEN.md + FROZEN_v2.md 해시·current 확인.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pickle
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from algaecast.config import MODELS_DIR, ROOT, SUBMISSION_PATH
from algaecast.features import upstream as U
from algaecast.models import data as D
from algaecast.models import registry as R
from algaecast.models import v2 as V2
from algaecast.models.train import VariantSpec

V1_REG = "20261021_091108"


def _script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 합성 데이터
def _synthetic(n: int = 600, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = pd.to_datetime("2016-03-01") + pd.to_timedelta(rng.integers(0, 365 * 9 + 250, n), unit="D")
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    logy = np.clip(2.5 + 1.2 * x1 - 0.5 * x2 + rng.normal(scale=0.4, size=n), 0, 6)
    df = pd.DataFrame(
        {
            "station_id": rng.choice(["HP", "CS", "DCHN"], n),
            "base_date": base.date,
            "target_date": (base + pd.Timedelta(days=7)).date,
            "f1": x1,
            "f2": x2,
            "f3": rng.uniform(size=n),
            "basin": rng.choice(["금강", "낙동강"], n),
            "target_cells": 10**logy - 1,
        }
    )
    df["target_log"] = np.log10(df["target_cells"] + 1)
    return df.sort_values(["station_id", "base_date"]).reset_index(drop=True)


def _tiny_specs() -> dict[str, VariantSpec]:
    p = {
        "n_estimators": 20,
        "learning_rate": 0.1,
        "num_leaves": 7,
        "min_child_samples": 5,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "feature_fraction": 0.9,
    }
    return {
        "c1": VariantSpec("log_w", alpha=0.05, params=dict(p)),
        "c3": VariantSpec("hurdle", params=dict(p), cls_params=dict(p)),
        "c2": VariantSpec("tweedie", variance_power=1.4, params=dict(p)),
    }


def _cfg(weights: tuple | None) -> V2.V2Config:
    return V2.V2Config(
        name="t", base_features=("f1", "f2", "f3", "basin"), members=V2.V1_MEMBERS, weights=weights
    )


def test_config_roundtrip() -> None:
    for cfg in (_cfg((("c1", 0.2), ("c3", 0.3), ("c2", 0.5))), V2.config_v2(), V2.config_v1()):
        assert V2.V2Config.from_dict(json.loads(json.dumps(cfg.to_dict()))) == cfg
    c = V2.config_v2()
    assert c.cols[-5:] == U.UPSTREAM_COLS and len(c.cols) == 35 and c.names == ("c1", "c3", "c2", "cg")
    assert V2.config_v1().fixed_weights().keys() == {"c1", "c3", "c2"}


def test_registry_v2_save_load_predict(tmp_path: Path) -> None:
    df = _synthetic()
    cfg = _cfg((("c1", 0.2), ("c3", 0.3), ("c2", 0.5)))
    model = V2.fit_final(df, cfg, specs=_tiny_specs(), seed=42)
    pred = model.predict(df)
    assert pred.shape == (len(df),) and np.isfinite(pred).all() and (pred >= 0).all()
    reg_dir = tmp_path / "models"
    R.register(
        "regression", {"kind": "ensemble", "dummy": 1}, features=["f1"], metrics_holdout={}, reg_dir=reg_dir
    )
    v1_entry = R.current_entry("regression", reg_dir)
    e = R.register(
        "regression",
        model.to_registry(),
        features=model.cols,
        metrics_holdout={"rmse_log": 0.7},
        meta={"kind": V2.KIND, "config": cfg.to_dict()},
        reg_dir=reg_dir,
    )
    obj, entry = R.load_current("regression", reg_dir=reg_dir)
    assert entry["version"] == e["version"] != v1_entry["version"]
    assert obj["kind"] == "ensemble_v2" and R.current_kind("regression", reg_dir) == "ensemble_v2"
    again = V2.V2Model.from_registry(obj)
    assert np.array_equal(again.predict(df), pred)
    assert np.array_equal(V2.V2Model.from_registry(pickle.loads(pickle.dumps(obj))).predict(df), pred)
    # 기존(v1) 항목은 남아 있고 그대로 읽힌다
    assert R.entry_for("regression", v1_entry["version"], reg_dir)["version"] == v1_entry["version"]
    ex = R.explain_member(obj)
    assert ex["cols"] == model.cols and "model" in ex
    with pytest.raises(FileExistsError):
        R.register("regression", {}, features=[], metrics_holdout={}, reg_dir=reg_dir, version=e["version"])


def test_fit_weights_synthetic() -> None:
    df = _synthetic()
    cfg = _cfg(None)
    w = V2.fit_weights(df, 42, cfg, specs=_tiny_specs())
    assert list(w) == ["c1", "c3", "c2"] and sum(w.values()) == pytest.approx(1.0)
    assert all(v >= 0 for v in w.values())


def test_guard_rejects_2026_rows() -> None:
    df = _synthetic()
    bad = df.copy()
    bad.loc[bad.index[-1], "target_date"] = pd.Timestamp("2026-01-05").date()
    with pytest.raises(RuntimeError):
        V2.fit_final(bad, _cfg((("c1", 0.2), ("c3", 0.3), ("c2", 0.5))), specs=_tiny_specs())
    with pytest.raises(RuntimeError):
        V2.cv_members(bad, 42, _cfg(None), specs=_tiny_specs())


# ---------------------------------------------------------------- verify_frozen
def _fake_models(tmp: Path) -> Path:
    md = tmp / "models"
    rows = {}
    for name, ver in (("regression", "20261021_091108"), ("regression", "20261022_120000")):
        (md / name / ver).mkdir(parents=True)
        (md / name / ver / "model.pkl").write_bytes(ver.encode())
        rows[ver] = _sha(md / name / ver / "model.pkl")
    for name, ver in (("classifier", "20261021_091109"), ("quantile", "20261021_091110")):
        (md / name / ver).mkdir(parents=True)
        (md / name / ver / "model.pkl").write_bytes(name.encode())
        rows[ver] = _sha(md / name / ver / "model.pkl")

    def table(reg: str) -> str:
        return "\n".join(
            f"| {n} | {v} | `{rows[v]}` | 1 | x | y |"
            for n, v in (
                ("regression", reg),
                ("classifier", "20261021_091109"),
                ("quantile", "20261021_091110"),
            )
        )

    (md / "FROZEN.md").write_text("# v1\n\n" + table("20261021_091108") + "\n", encoding="utf-8")
    (md / "FROZEN_v2.md").write_text("# v2\n\n" + table("20261022_120000") + "\n", encoding="utf-8")
    cur = {"regression": "20261022_120000", "classifier": "20261021_091109", "quantile": "20261021_091110"}
    (md / "registry.json").write_text(json.dumps({"current": cur, "versions": []}), encoding="utf-8")
    return md


def test_verify_frozen_v1_and_v2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    vf = _script("verify_frozen")
    md = _fake_models(tmp_path)
    assert vf.main(["--models-dir", str(md)]) == 0
    out = capsys.readouterr().out
    assert "[FROZEN.md]" in out and "[FROZEN_v2.md]" in out
    # current 가 v1 회귀를 가리키면 실패(최근 문서 = FROZEN_v2)
    reg = json.loads((md / "registry.json").read_text(encoding="utf-8"))
    reg["current"]["regression"] = "20261021_091108"
    (md / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    assert vf.main(["--models-dir", str(md)]) == 1
    reg["current"]["regression"] = "20261022_120000"
    (md / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    (md / "regression" / "20261021_091108" / "model.pkl").write_bytes(b"tampered")  # v1 파일 변조도 실패
    assert vf.main(["--models-dir", str(md)]) == 1


def test_verify_frozen_repo() -> None:
    if not (MODELS_DIR / "regression" / V1_REG / "model.pkl").exists():
        pytest.skip("동결 모델 pickle 없음")
    assert _script("verify_frozen").main([]) == 0


# ---------------------------------------------------------------- 실제 데이터(축약 v2)
def _need_data() -> None:
    if not (D.PROCESSED / "features_S1.parquet").exists() or not U.ALGAE_PARQUET.exists():
        pytest.skip("features_S1·조류 원자료 없음")
    if not (MODELS_DIR / "regression" / V1_REG / "model.pkl").exists():
        pytest.skip("v1 동결 모델 pickle 없음")


def _small_real_specs() -> dict[str, VariantSpec]:
    out = {}
    for k, s in V2.member_specs().items():
        s2 = copy.deepcopy(s)
        s2.params = {**s2.params, "n_estimators": 30}
        s2.cls_params = {**s2.cls_params, "n_estimators": 30}
        out[k] = s2
    return out


@pytest.fixture(scope="module")
def v2_registry(tmp_path_factory: pytest.TempPathFactory) -> Path:
    _need_data()
    reg_dir = tmp_path_factory.mktemp("v2reg") / "models"
    cur = R.current_versions()
    with R.model_path("regression", V1_REG).open(
        "rb"
    ) as f:  # 동결 후 current 는 v2 → v1 회귀를 버전으로 읽는다
        v1_obj = pickle.load(f)
    for name in ("classifier", "quantile"):
        R.copy_version(name, cur[name], reg_dir)
        R.set_current(name, cur[name], reg_dir)
    frame = V2.load_training_frame()
    w = {"c1": 0.1, "c3": 0.3, "c2": 0.3, "cg": 0.3}
    model = V2.fit_final(frame, weights=w, specs=_small_real_specs())
    model.aux = {"cols": v1_obj["cols"], "cats": v1_obj["cats"], "categories": v1_obj["categories"]}
    R.register(
        "regression",
        model.to_registry(),
        features=model.cols,
        metrics_holdout={},
        meta={"kind": V2.KIND, "config": model.config.to_dict(), "weights": w},
        reg_dir=reg_dir,
    )
    return reg_dir


def test_v1_registry_kept() -> None:
    _need_data()
    e = R.entry_for("regression", V1_REG)
    assert e["meta"]["kind"] == "ensemble"
    assert R.current_kind("regression") in ("ensemble", "ensemble_v2")
    with R.model_path("regression", V1_REG).open("rb") as f:
        assert pickle.load(f)["kind"] == "ensemble"


def test_make_submission_v2_format(v2_registry: Path, tmp_path: Path) -> None:
    from algaecast.models.predict import (
        DEFAULT_SAMPLE,
        make_submission,
        validate_submission,
        write_submission,
    )

    sub = make_submission(reg_dir=v2_registry)
    sample = pd.read_csv(DEFAULT_SAMPLE, encoding="utf-8-sig", dtype={"station_id": str})
    assert len(sub) == len(sample) == 124
    assert list(sub.columns) == list(sample.columns)
    key = ["station_id", "base_date", "target_date"]
    assert (sub[key].to_numpy() == sample[key].to_numpy()).all()
    assert sub["pred_cells"].dtype == "int64" and (sub["pred_cells"] >= 0).all()
    p = write_submission(sub, tmp_path / "submission.csv")
    v = validate_submission(p)
    assert v["rows"] == 124 and v["columns"] and v["order_same_as_sample"] and v["bom"]
    assert v["nan"] == 0 and v["negative"] == 0
    assert p.read_bytes().count(b"\r\n") == 0


def test_predict_registry_v2_keeps_v1_quantile_classifier(v2_registry: Path) -> None:
    from algaecast.db.upload import predict_registry

    te = D.load_test_features("S1").reset_index(drop=True)
    a = predict_registry(te)  # 저장소 레지스트리(v1 또는 동결 후 v2)
    b = predict_registry(te, reg_dir=v2_registry)
    for c in ("q10", "q50", "q90", "q10_cqr", "q90_cqr", "p_alert"):
        assert np.array_equal(a[c].to_numpy(), b[c].to_numpy()), c
    assert np.isfinite(b["pred_cell_count"]).all() and (b["pred_cell_count"] >= 0).all()
    # 상류 피처를 미리 붙여 넘겨도 같은 예측
    te2 = pd.concat([te, U.build_upstream(te)], axis=1)
    c2 = predict_registry(te2, reg_dir=v2_registry)
    assert np.array_equal(b["pred_cell_count"].to_numpy(), c2["pred_cell_count"].to_numpy())


def test_attach_model_features(v2_registry: Path) -> None:
    from algaecast.predict.asof import attach_model_features

    te = D.load_test_features("S1").reset_index(drop=True).head(10)
    te["base_date"] = pd.to_datetime(te["base_date"])
    out = attach_model_features(te, None, reg_dir=v2_registry)
    assert all(c in out.columns for c in U.UPSTREAM_COLS) and len(out) == len(te)
    raw = pd.read_parquet(U.ALGAE_PARQUET)
    out2 = attach_model_features(te, raw, reg_dir=v2_registry)
    assert np.array_equal(
        out[U.UPSTREAM_COLS].to_numpy(dtype=float),
        out2[U.UPSTREAM_COLS].to_numpy(dtype=float),
        equal_nan=True,
    )
    empty = attach_model_features(te, raw.iloc[0:0], reg_dir=v2_registry)
    assert empty[U.UPSTREAM_COLS].isna().all().all()
    if R.current_kind("regression") == "ensemble":  # v1 레지스트리면 그대로
        same = attach_model_features(te, raw)
        assert list(same.columns) == list(te.columns)


def test_freeze_v2_dry_run_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _need_data()
    fv = _script("freeze_v2")
    before = {
        p: _sha(p) for p in (R.registry_path(), SUBMISSION_PATH, MODELS_DIR / "FROZEN.md") if p.exists()
    }
    small = _small_real_specs()
    monkeypatch.setattr(V2, "member_specs", lambda: small)
    monkeypatch.setattr(fv, "DRY_DIR", tmp_path / "v2_dryrun")
    assert fv.run(dry=True, force=False) == 0
    after = {p: _sha(p) for p in before}
    assert before == after  # models/·submission/ 불변
    out = tmp_path / "v2_dryrun"
    for f in ("models/registry.json", "models/FROZEN_v2.md", "submission_v2.csv", "summary.json"):
        assert (out / f).exists(), f
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["submission"]["rows"] == 124 and s["submission"]["bom"] and s["train"]["n_rows"] > 2000
    assert R.current_kind("regression", out / "models") == "ensemble_v2"
    assert _script("verify_frozen").main(["--models-dir", str(out / "models")]) == 0


def test_explain_member_picks_max_weight_single_model() -> None:
    """v2 SHAP 설명 구성원 = 가중치 최대 단일 LightGBM 구성원(가중치 0 인 c1 이 아님), tweedie 는 log10 환산."""
    reg = {
        "kind": "ensemble_v2",
        "weights": {"c1": 0.0, "c3": 0.266, "c2": 0.373, "cg": 0.361},
        "members": {
            "c1": {"kind": "log_w", "model": "m1", "cats": []},
            "c3": {"kind": "hurdle", "clf": "a", "hi": "b", "lo": "c", "cats": []},
            "c2": {"kind": "tweedie", "model": "m2", "cats": []},
            "cg": {"kind": "genus", "layout": "G2", "parts": {}},
        },
        "cols": ["x1", "x2"],
        "cats": [],
    }
    ex = R.explain_member(reg)
    assert ex["member"] == "c2" and ex["model"] == "m2" and ex["cols"] == ["x1", "x2"]
    assert ex["shap_scale"] == pytest.approx(1 / np.log(10))
    reg["weights"] = {"c1": 0.5, "c3": 0.2, "c2": 0.3, "cg": 0.0}
    ex1 = R.explain_member(reg)
    assert ex1["member"] == "c1" and ex1["shap_scale"] == 1.0
