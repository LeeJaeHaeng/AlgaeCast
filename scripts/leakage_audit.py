"""평가 조합 누수 감사 (T3-b) → reports/eval/leakage_audit.md

검사 항목
1. 규칙: 모든 샘플에서 target_date > base_date, horizon 4~10, sample_submission 조합이 test 로 1:1 존재.
2. 재계산 불변성: 각 (site, base_date) 에 대해 일 달력을 base_date 까지 잘라낸 프레임으로 피처를 다시 계산해
   features_<S>.parquet 의 행과 완전히 같은지 비교 (전 샘플 또는 --sample N).
3. 예보: fc_available=1 인 샘플은 모두 base_date ≥ available_from.
4. 컬럼 이름에 target/future 가 없고, 타깃 자체가 피처에 들어가지 않았는지(타깃과 상관 1.0 피처 없음).
5. 원자료부터 재계산(FIX-v2.1): 표본 (site, base_date) 마다 원자료 전부(조류·수문·기상·연속 수위·예보 발표)를
   base_date 까지 잘라 일 달력 정렬·결측 대체·피처를 처음부터 다시 만들고 저장된 피처와 비교한다.
   중간 파일(일 달력)에 전 기간 통계가 들어간 경우(예: 수위 편차의 전 기간 평균)도 잡는다.

사용: python scripts/leakage_audit.py [--strategy S1] [--sample 0(전체)] [--raw-sample 60(0=생략)]
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
from algaecast.features.run import (
    GROUPS,
    LEVEL_FEATURES,
    META_COLS,
    level_cont_mode,
    wamis_hydro_path,
    wamis_mode,
)

INTERIM = DATA_DIR / "interim"
PROCESSED = DATA_DIR / "processed"


def _same(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return str(a) == str(b)


def truncate_sources(src: dict[str, pd.DataFrame], as_of: date) -> dict[str, pd.DataFrame]:
    """원자료를 as_of(포함)까지 자른 사본. 예보는 발표 시각(KST) 날짜 기준."""
    end = pd.Timestamp(as_of)
    out = {}
    for k, d in src.items():
        if k == "forecast":
            day = d["issued_at"].dt.tz_convert("Asia/Seoul").dt.normalize().dt.tz_localize(None)
            out[k] = d[day <= end]
        else:
            out[k] = d[pd.to_datetime(d["obs_date"]) <= end]
    return out


def raw_recompute(
    feats: pd.DataFrame, check_cols: list[str], sites: dict, strategy: str, n: int
) -> tuple[int, list[tuple]]:
    """표본마다 원자료를 base_date 까지 잘라 정렬·피처를 다시 만들고 저장 피처와 비교한다."""
    from algaecast.align.run import apply_strategy, build_site_daily, load_cfg, load_sources

    sites_cfg, feat_cfg = load_cfg()
    full = load_sources()
    rows = feats.sample(min(n, len(feats)), random_state=42)
    mism: list[tuple] = []
    for r in rows.itertuples():
        site = sites[r.station_id]
        src = truncate_sources(full, r.base_date)
        base = build_site_daily(site, src, sites_cfg, feat_cfg, r.base_date)
        d = apply_strategy(base, strategy, feat_cfg)
        d["obs_date"] = pd.to_datetime(d["obs_date"])
        trunc = cut_as_of(d, r.base_date)
        rec: dict = {}
        for fn in GROUPS.values():
            rec.update(fn(trunc, r.base_date, site["site_code"]))
        for c in check_cols:
            v = getattr(r, c)
            v = float(v) if isinstance(v, (np.floating, np.integer)) else v
            if c in rec and not _same(rec[c], v):
                mism.append((r.station_id, str(r.base_date), c, rec[c], v))
    return len(rows), mism


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", default="S1")
    ap.add_argument("--sample", type=int, default=0, help="재계산 검사 샘플 수 (0 = 전체)")
    ap.add_argument("--raw-sample", type=int, default=60, help="원자료부터 재계산 표본 수 (0 = 생략)")
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
    # DataON 원자료가 없으면 수위 2열은 가공 피처 파일 값이라 달력으로 재계산할 수 없다
    # (그 값은 원자료 환경에서 이 검사를 통과한 값이다)
    level_mode = level_cont_mode(args.strategy)
    check_cols = [c for c in feature_cols if level_mode == "raw" or c not in LEVEL_FEATURES]
    w_mode = wamis_mode(args.strategy)
    if w_mode == "derived":
        w_cols = set(pd.read_parquet(wamis_hydro_path(args.strategy)).columns) - {"station_id", "base_date"}
        check_cols = [c for c in check_cols if c not in w_cols]
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
        for c in check_cols:
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
    if w_mode == "derived":
        lines.append("- WAMIS 원자료 없음(derived) → 수문 피처는 재계산 검사에서 제외(가공 피처 파일 값)")
    if level_mode != "raw":
        lines.append(
            f"- DataON 원자료 없음({level_mode}) → {', '.join(LEVEL_FEATURES)} 는 재계산 검사에서 제외"
            " (가공 피처 파일 값, 원자료 환경에서 검사됨)"
        )
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

    # 5. 원자료부터 재계산
    raw_checked, raw_mism = 0, []
    if args.raw_sample > 0:
        raw_checked, raw_mism = raw_recompute(feats, check_cols, sites, args.strategy, args.raw_sample)
        lines += [
            "## 5. 원자료부터 재계산 (원자료를 base_date 까지 잘라 정렬·결측 대체·피처를 처음부터)",
            f"- 검사 표본 {raw_checked:,}, 불일치 {len(raw_mism)}",
        ]
        if raw_mism:
            issues.append("원자료 재계산 불일치")
            lines += ["", "| 지점 | base_date | 피처 | 재계산 | 저장 |", "|---|---|---|---|---|"] + [
                f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in raw_mism[:30]
            ]
        lines.append("")

    lines += ["## 결론", "- **이상 없음**" if not issues else f"- **조치 필요**: {', '.join(issues)}"]
    out = ROOT / "reports" / "eval" / "leakage_audit.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    (ROOT / "reports" / "eval" / "leakage_audit.json").write_text(
        json.dumps(
            {
                "strategy": args.strategy,
                "checked": checked,
                "mismatch": len(mism),
                "raw_checked": raw_checked,
                "raw_mismatch": len(raw_mism),
                "issues": issues,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
