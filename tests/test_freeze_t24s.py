"""비상안 T24S(엄격판) 동결 기록의 일관성 — 동결 문서 해시 = 학습 기록 해시, submission 사본 해시, 2026 미채점."""

from __future__ import annotations

import hashlib
import json

import yaml

from algaecast.config import CONFIG_DIR, ROOT

D = ROOT / "reports" / "experiments" / "contingency_T24S"


def _fit() -> dict:
    return json.loads((D / "t24s_fit.json").read_text(encoding="utf-8"))


def test_frozen_doc_lists_fit_hashes() -> None:
    doc = (D / "FROZEN_T24S.md").read_text(encoding="utf-8")
    for f in _fit()["files"]:
        assert f["sha256_model_pkl"] in doc and f["sha256_meta_json"] in doc, f["name"]


def test_submission_copy_and_not_scored() -> None:
    fit = _fit()
    sub = fit["submission_T24S"]
    assert hashlib.sha256((D / "submission_T24S.csv").read_bytes()).hexdigest() == sub["sha256_full"]
    assert sub["rows"] == 124 and sub["scored_on_2026"] is False
    assert not any("2026" in k for k in fit.get("eval_2025", {}))


def test_strict_rows_and_unchanged_decisions() -> None:
    fit = _fit()
    assert fit["train_regression"]["n_rows"] == 2305
    assert fit["train_regression"]["target_date_max"] <= "2024-12-31"
    assert len(fit["excluded_rows"]) == 5
    assert {r["target_date"] for r in fit["excluded_rows"]} == {"2025-01-06"}
    mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    dec = fit["decisions"]
    assert abs(dec["thr_clf_a"] - float(mcfg["thresholds"]["clf_a"])) < 1e-9
    assert abs(dec["thr_clf_b"] - float(mcfg["thresholds"]["clf_b"])) < 1e-9
    assert abs(dec["operating_point_r3"] - float(mcfg["operating_point"]["threshold"])) < 1e-9
    assert dec["cqr_n_calib"] == 526 and abs(sum(dec["weights"].values()) - 1) < 1e-9
