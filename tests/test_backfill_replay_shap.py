"""다시 보기 SHAP 백필(scripts/backfill_replay_shap.py) 순수 함수: 피처 원천 선택·빠진 키·순위 규칙·근거 상위 3 문장."""

from __future__ import annotations

import importlib.util
from types import ModuleType

import pandas as pd

from algaecast.config import ROOT


def _mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "backfill_replay_shap", ROOT / "scripts" / "backfill_replay_shap.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_pred_matches_tolerance() -> None:
    m = _mod()
    assert m.pred_matches(10661.607975, 10661.607975 * (1 + 1e-12))
    assert m.pred_matches(0.0, 0.0)
    assert not m.pred_matches(10661.6, 10700.0)  # 상대차 0.36%
    assert not m.pred_matches(100.0, float("nan"))
    assert not m.pred_matches(100.0, None)


def test_choose_source_prefers_bundle_then_asof_then_none() -> None:
    m = _mod()
    assert m.choose_source(100.0, {"features": 100.0, "asof": 100.0}) == "features"
    assert m.choose_source(100.0, {"features": 103.0, "asof": 100.0}) == "asof"
    assert m.choose_source(100.0, {"features": None, "asof": 100.0}) == "asof"
    assert m.choose_source(100.0, {"features": 103.0, "asof": None}) is None
    assert m.choose_source(100.0, {"features": 103.0, "asof": 97.0}) is None


def test_missing_keys_skips_existing_and_out_of_range() -> None:
    m = _mod()
    preds = [
        {"site_id": "2011G56", "base_date": "2025-08-04"},  # 2025: 다시 보기 범위 밖
        {"site_id": "2011G56", "base_date": "2026-07-27"},
        {"site_id": "2011G56", "base_date": "2026-08-03"},
        {"site_id": "2011G56", "base_date": "2026-10-19"},  # 이미 있음
        {"site_id": "3008G30", "base_date": "2026-07-06"},
        {"site_id": "3008G30", "base_date": "2026-07-06"},  # 중복 키는 한 번만
    ]
    shap = [{"site_id": "2011G56", "base_date": "2026-10-19", "feature_name": "x", "rank": 1}]
    assert m.missing_keys(preds, shap) == [
        ("2011G56", "2026-07-27"),
        ("2011G56", "2026-08-03"),
        ("3008G30", "2026-07-06"),
    ]
    assert m.missing_keys(preds, shap, until="2026-07-27") == [
        ("2011G56", "2026-07-27"),
        ("3008G30", "2026-07-06"),
    ]


def test_rank_rule_top8_by_abs_desc() -> None:
    m = _mod()
    sv = pd.Series(
        {f"f{i}": v for i, v in enumerate([0.1, -0.9, 0.3, -0.05, 0.7, 0.2, -0.4, 0.02, 0.6, -0.8])}
    )
    top = m.rank_top(sv)
    assert top == ["f1", "f9", "f4", "f8", "f6", "f2", "f5", "f0"]
    rows = [
        {"site_id": "s", "base_date": "d", "feature_name": f, "shap_value": float(sv[f]), "rank": i}
        for i, f in enumerate(top, 1)
    ]
    assert m.ranks_ok(rows)
    bad = [dict(r) for r in rows]
    bad[0]["rank"], bad[1]["rank"] = 2, 1  # 순위가 |shap| 순서와 어긋남
    assert not m.ranks_ok(bad)
    assert not m.ranks_ok(rows[:7])  # 8개 미만


def test_reasons_top3_group_sum_sign_and_water_rule() -> None:
    m = _mod()
    texts = {
        "reason": {g: {"up": f"{g}+", "down": f"{g}-"} for g in m.UI_GROUPS},
        "label": {g: g.upper() for g in m.UI_GROUPS},
        "water_days": "(25℃ 이상 ${n}일)",
        "water_up_mild": "mild",
    }
    rows = [
        {"feature_name": "cell_log_t0", "feature_group": "ar", "shap_value": 0.5},
        {"feature_name": "cell_max_4w", "feature_group": "ar", "shap_value": 0.3},  # ar 합 0.8
        {"feature_name": "wtemp_ma14", "feature_group": "water", "shap_value": 0.4},
        {"feature_name": "up1_cell_log", "feature_group": "etc", "shap_value": -0.45},  # up1_* → upstream
        {"feature_name": "season_day", "feature_group": "time_site", "shap_value": 0.1},
        {"feature_name": "rn_sum30", "feature_group": "weather", "shap_value": -0.2},
        {"feature_name": "horizon_days", "feature_group": "zzz", "shap_value": 0.05},  # 미분류 → time_site
    ]
    out = m.reasons_top3(rows, hot_days=3, texts=texts)
    assert [(r["group"], r["direction"]) for r in out] == [
        ("ar", "올림"),
        ("upstream", "내림"),
        ("water", "올림"),
    ]
    assert out[0]["text"] == "ar+" and out[1]["text"] == "upstream-"
    assert out[2]["text"] == "water+ (25℃ 이상 3일)"
    assert m.reasons_top3(rows, hot_days=0, texts=texts)[2]["text"] == "mild"
    assert sum(r["share_pct"] for r in out) <= 100
    # 문구 없이도 그룹·부호는 나온다
    assert m.reasons_top3(rows, hot_days=0)[0]["text"] is None


def test_load_copy_texts_from_real_copy_ts() -> None:
    m = _mod()
    src = m.COPY_TS.read_text(encoding="utf-8")
    t = m.load_copy_texts(src)
    assert set(t["reason"]) == set(m.UI_GROUPS) and set(t["label"]) == set(m.UI_GROUPS)
    assert "${n}" in t["water_days"] and t["water_up_mild"]
    assert t["reason"]["ar"]["up"] and t["reason"]["ar"]["down"]


def test_content_hash_is_order_invariant_and_value_sensitive() -> None:
    m = _mod()
    a = [
        {
            "id": 1,
            "site_id": "s",
            "base_date": "2026-07-27",
            "target_date": "2026-08-03",
            "pred_cell_count": 1.0,
        }
    ]
    b = [
        {
            "id": 2,
            "site_id": "s",
            "base_date": "2026-07-20",
            "target_date": "2026-07-27",
            "pred_cell_count": 2.0,
        }
    ]
    assert m.content_hash(a + b) == m.content_hash(b + a)
    c = [dict(a[0], pred_cell_count=1.5)]
    assert m.content_hash(a + b) != m.content_hash(c + b)
