"""평가 조합 누수 감사 (T3-b) → reports/eval/leakage_audit.md

검사 항목
1. 규칙: 모든 샘플에서 target_date > base_date, horizon 4~10, sample_submission 조합이 test 로 1:1 존재.
2. 재계산 불변성: 각 (site, base_date) 에 대해 일 달력을 base_date 까지 잘라낸 프레임으로 피처를 다시 계산해
   features_<S>.parquet 의 행과 완전히 같은지 비교 (전 샘플 또는 --sample N).
3. 예보: fc_available=1 인 샘플은 모두 base_date ≥ available_from.
4. 컬럼 이름에 target/future 가 없고, 타깃 자체가 피처에 들어가지 않았는지(타깃과 상관 1.0 피처 없음).

사용: python scripts/leakage_audit.py [--strategy S1] [--sample 0(전체)]
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date

import numpy as np
import pandas as pd
import yaml

from algaecast.collect import competition as comp
from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT
from algaecast.features.base import cut_as_of
from algaecast.features.run import GROUPS, META_COLS

INTERIM = DATA_DIR / "interim"
PROCESSED = DATA_DIR / "processed"


def _same(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return str(a) == str(b)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", default="S1")
    ap.add_argument("--sample", type=int, default=0, help="재계산 검사 샘플 수 (0 = 전체)")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    sites = {
        s["station_id"]: s
        for s in yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))["sites"]
    }
    feats = pd.read_parquet(PROCESSED / f"features_{args.strategy}.parquet")
    feats["base_date"] = pd.to_datetime(feats["base_date"]).dt.date
    feats["target_date"] = pd.to_datetime(feats["target_date"]).dt.date
    lines = [f"# 누수 감사 — 전략 {args.strategy} ({date.today()})", ""]
    issues: list[str] = []

    # 1. 규칙
    has_t = feats["target_date"].notna()
    bad_order = feats[has_t & (pd.to_datetime(feats["target_date"]) <= pd.to_datetime(feats["base_date"]))]
    bad_h = feats[has_t & ~feats["horizon_days"].between(4, 10)]
    sub = comp.load_sample_submission()
    key = set(
        zip(
            sub["station_id"],
            pd.to_datetime(sub["base_date"]).dt.date,
            pd.to_datetime(sub["target_date"]).dt.date,
            strict=True,
        )
    )
    test_rows = feats[feats["split"] == "test"]
    test_key = set(
        zip(test_rows["station_id"], test_rows["base_date"], test_rows["target_date"], strict=True)
    )
    lines += [
        "## 1. 규칙 검사",
        f"- target_date ≤ base_date 인 행: {len(bad_order)}",
        f"- horizon 4~10 벗어난 행: {len(bad_h)}",
        f"- sample_submission {len(key)} 조합 중 test 샘플 존재: {len(key & test_key)}, "
        f"누락 {len(key - test_key)}, 초과 {len(test_key - key)}",
        "- test 샘플의 타깃이 피처 파일에 노출: "
        f"{'예' if test_rows['target_log'].notna().any() else '아니오'} "
        "(2026 측정값이 있으면 보관하지만 학습에 쓰지 않음)",
        "",
    ]
    if len(bad_order) or len(bad_h) or (key - test_key):
        issues.append("규칙 위반")

    # 2. 재계산 불변성
    feature_cols = [c for c in feats.columns if c not in META_COLS]
    rows = feats if args.sample == 0 else feats.sample(min(args.sample, len(feats)), random_state=42)
    mism: list[tuple] = []
    checked = 0
    daily_cache: dict[str, pd.DataFrame] = {}
    for r in rows.itertuples():
        if r.station_id not in daily_cache:
            d = pd.read_parquet(INTERIM / f"daily_{r.station_id}_{args.strategy}.parquet")
            d["obs_date"] = pd.to_datetime(d["obs_date"])
            daily_cache[r.station_id] = d
        trunc = cut_as_of(daily_cache[r.station_id], r.base_date)
        rec: dict = {}
        for fn in GROUPS.values():
            rec.update(fn(trunc, r.base_date, sites[r.station_id]["site_code"]))
        for c in feature_cols:
            if c in rec and not _same(
                rec[c],
                (
                    getattr(r, c)
                    if not isinstance(getattr(r, c), (np.floating, np.integer))
                    else float(getattr(r, c))
                ),
            ):
                mism.append((r.station_id, str(r.base_date), c, rec[c], getattr(r, c)))
        checked += 1
    lines += [
        "## 2. 재계산 불변성 (base_date 까지 잘라낸 달력으로 재계산 = 저장된 피처)",
        f"- 검사 샘플 {checked:,}, 불일치 {len(mism)}",
    ]
    if mism:
        issues.append("재계산 불일치")
        lines += ["", "| 지점 | base_date | 피처 | 재계산 | 저장 |", "|---|---|---|---|---|"] + [
            f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in mism[:30]
        ]
    lines.append("")

    # 3. 예보
    av = pd.Timestamp(cfg["forecast"]["available_from"]).date()
    bad_fc = feats[(feats["fc_available"] == 1) & (feats["base_date"] < av)]
    lines += [
        "## 3. 예보 가용 규칙",
        f"- fc_available=1 이면서 base_date < {av} 인 행: {len(bad_fc)}",
        f"- fc_available=1 샘플 수: {int((feats['fc_available'] == 1).sum())}",
        "",
    ]
    if len(bad_fc):
        issues.append("예보 가용 위반")

    # 4. 타깃 노출
    tr = feats[feats["split"] == "train"]
    sus = []
    for c in feature_cols:
        x = pd.to_numeric(tr[c], errors="coerce")
        if x.notna().sum() > 50 and x.nunique() > 1:
            rho = abs(np.corrcoef(x.fillna(x.median()), tr["target_log"])[0, 1])
            if rho > 0.98:
                sus.append((c, round(rho, 4)))
    named = [c for c in feature_cols if "target" in c or "future" in c]
    lines += [
        "## 4. 타깃 노출",
        f"- 이름에 target/future 포함 피처: {named or '없음'}",
        f"- train 에서 타깃과 |r|>0.98 피처: {sus or '없음'}",
        "",
    ]
    if named or sus:
        issues.append("타깃 노출 의심")

    lines += ["## 결론", "- **이상 없음**" if not issues else f"- **조치 필요**: {', '.join(issues)}"]
    out = ROOT / "reports" / "eval" / "leakage_audit.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    (ROOT / "reports" / "eval" / "leakage_audit.json").write_text(
        json.dumps(
            {"strategy": args.strategy, "checked": checked, "mismatch": len(mism), "issues": issues},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
