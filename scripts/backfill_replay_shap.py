"""다시 보기용 SHAP 근거 백필(1회): 고정 run 의 2026 기준일 예측에 '왜 이렇게 예상했나' 근거를 채운다.

- 대상: run(기본 web/src/lib/replay.ts 의 REPLAY_RUN_ID = v2.1 고정 run)의 predictions 중
  기준일 ≥ 2026-01-01 인 (지점, 기준일) 가운데 shap_contributions 에 아직 없는 키.
  이미 있는 키(예: 10-19·10-22 일일 운영분)는 건드리지 않는다.
- 계산은 일일 운영과 같게: algaecast.db.upload.shap_and_reco_rows 를 기준일 묶음(지점당 1행)마다 그대로 호출
  → 설명 구성원(레지스트리 current 회귀의 가중치 최대 단일 구성원 c2 tweedie, shap_scale=1/ln10)·같은 열·
  지점·기준일별 상위 8. 권고(recommendations)는 쓰지 않는다(다시 보기 화면은 shap_contributions 만 읽음).
- 피처 원천은 기존 as-of 파이프라인 그대로: (a) data/processed/features_S1.parquet 의 같은 (지점, 기준일) 행,
  (b) --asof-fallback 이면 algaecast.predict.asof(일일 러너 방식, 공공 API 증분 수집). 원천마다 레지스트리
  current 점예측을 계산해 저장된 predictions.pred_cell_count 와 대조(저장하지 않음)하고 맞는 원천만 쓴다.
  둘 다 안 맞으면 넣지 않고 보고.
- predictions 테이블은 읽기만 한다. 저장 전·후 run 전체 행 수와 내용 해시(정렬 후 sha256)를 찍어 같음을
  보인다.
- shap_contributions 에는 유일 제약이 없다(supabase/migrations/0001_init.sql: bigserial id + index).
  그래서 upsert 가 아니라 (run_id, site_id, base_date) 키가 아직 없을 때만 insert 한다
  (실행 직전 한 번 더 확인).
- 키 값(.env)은 어디에도 출력하지 않는다.
사용:
  python scripts/backfill_replay_shap.py --dry-run [--out DIR]      # 행 수·표본·대조표만
  python scripts/backfill_replay_shap.py [--out DIR] [--asof-fallback] [--scene 2011G56:2026-07-27 ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, ROOT
from algaecast.models import data as D
from algaecast.models import registry as R

log = logging.getLogger("backfill_replay_shap")

REPLAY_RUN_ID = "9269d95d-9b8f-4d12-babe-02f9f60b41c5"  # web/src/lib/replay.ts REPLAY_RUN_ID 와 같은 값
REPLAY_MIN = "2026-01-01"  # web/src/lib/replay.ts REPLAY_MIN
TOP_K = 8  # shap_and_reco_rows 와 같은 상위 개수
SOURCES = ("features", "asof")  # 대조 순서: 번들 피처 → as-of 수집
# 대시보드 장면 3개(web/src/lib/replay.ts SCENES): ① 강정·고령 07-27 ② 강정·고령 08-03 ③ 회남 07-06
DEFAULT_SCENES = ("2011G56:2026-07-27", "2011G56:2026-08-03", "3008G30:2026-07-06")
COPY_TS = ROOT / "web" / "src" / "lib" / "copy.ts"
UI_GROUPS = ("ar", "water", "hydro", "weather", "forecast", "time_site", "upstream")  # copy.ts GROUPS
UPSTREAM_PREFIX = "up1_"  # copy.ts UPSTREAM_PREFIX
HOT_DAYS_WINDOW = 30  # 지점 상세: 최근 30일 수온 25℃ 이상 측정 횟수
HOT_TEMP = 25.0


# ---------------------------------------------------------------- 순수 함수(테스트 대상)
def pred_matches(stored: float, computed: float, *, tol_log: float = 1e-6, tol_rel: float = 1e-6) -> bool:
    """저장된 점예측과 다시 계산한 점예측이 같은가: |Δlog10(x+1)| ≤ tol_log 또는 상대차 ≤ tol_rel."""
    if stored is None or computed is None or not (np.isfinite(stored) and np.isfinite(computed)):
        return False
    dlog = abs(np.log10(max(computed, 0.0) + 1.0) - np.log10(max(stored, 0.0) + 1.0))
    rel = abs(computed - stored) / (abs(stored) + 1e-9)
    return bool(dlog <= tol_log or rel <= tol_rel)


def choose_source(stored: float, candidates: dict[str, float | None], **tol: float) -> str | None:
    """후보 원천(features → asof 순)마다 점예측을 대조해 처음 맞는 원천 이름을, 없으면 None 을 돌려준다."""
    for name in SOURCES:
        v = candidates.get(name)
        if v is not None and pred_matches(stored, float(v), **tol):
            return name
    return None


def missing_keys(
    pred_rows: list[dict], shap_rows: list[dict], *, since: str = REPLAY_MIN, until: str | None = None
) -> list[tuple[str, str]]:
    """predictions 의 (site_id, base_date) 중 since ≤ 기준일 (≤ until) 이고 shap 에 없는 키(정렬)."""
    have = {(str(r["site_id"]), str(r["base_date"])[:10]) for r in shap_rows}
    keys = set()
    for r in pred_rows:
        b = str(r["base_date"])[:10]
        if b < since or (until and b > until):
            continue
        keys.add((str(r["site_id"]), b))
    return sorted(k for k in keys if k not in have)


def rank_top(sv: pd.Series, k: int = TOP_K) -> list[str]:
    """일일 운영의 순위 규칙(shap_and_reco_rows): |기여| 내림차순 상위 k 피처 이름(순위 1..k)."""
    return list(sv.abs().sort_values(ascending=False, kind="stable").head(k).index)


def ranks_ok(rows: list[dict], k: int = TOP_K) -> bool:
    """키마다 rank 가 1..k 이고 |shap_value| 가 순위대로 내림차순인지."""
    df = pd.DataFrame(rows)
    if df.empty:
        return False
    for _, g in df.groupby(["site_id", "base_date"]):
        g = g.sort_values("rank")
        if list(g["rank"]) != list(range(1, k + 1)):
            return False
        a = g["shap_value"].abs().to_numpy()
        if np.any(a[1:] > a[:-1] + 1e-12):
            return False
    return True


def ui_group(feature_name: str, feature_group: str | None) -> str:
    """지점 상세 화면의 그룹 매핑: up1_* → upstream, UI 그룹 밖(etc 등) → time_site."""
    if str(feature_name).startswith(UPSTREAM_PREFIX):
        return "upstream"
    return feature_group if feature_group in UI_GROUPS else "time_site"


def reasons_top3(shap_rows: list[dict], hot_days: int, texts: dict | None = None) -> list[dict]:
    """대시보드 규칙(web/src/app/sites/[id]/page.tsx): 상위 8 → 그룹 합산 → |합| 큰 3개 → 부호별 고정 문장.

    물 온도 그룹이 올림이면 최근 30일 25℃ 이상 측정이 있을 때 보조 문구, 없으면 REASON_WATER_UP_MILD.
    texts 는 load_copy_texts() 결과(None 이면 문장 없이 그룹·부호·비중만).
    """
    by: dict[str, float] = {}
    for r in shap_rows:
        g = ui_group(r["feature_name"], r.get("feature_group"))
        by[g] = by.get(g, 0.0) + float(r.get("shap_value") or 0.0)
    total = sum(abs(v) for v in by.values()) or 1.0
    out = []
    for g, v in sorted(by.items(), key=lambda kv: -abs(kv[1]))[:3]:
        text = None
        if texts:
            if g == "water" and v >= 0:
                text = (
                    f"{texts['reason'][g]['up']} {texts['water_days'].replace('${n}', str(hot_days))}"
                    if hot_days > 0
                    else texts["water_up_mild"]
                )
            else:
                text = texts["reason"][g]["up" if v >= 0 else "down"]
        out.append(
            {
                "group": g,
                "label": (texts or {}).get("label", {}).get(g, g),
                "direction": "올림" if v >= 0 else "내림",
                "share_pct": int(round(100 * abs(v) / total)),
                "sum_shap": float(v),
                "text": text,
            }
        )
    return out


def load_copy_texts(src: str) -> dict:
    """copy.ts(문구 단일 원천)에서 REASON·GROUP_LABEL·reasonWaterDays·REASON_WATER_UP_MILD 를 읽는다."""
    block = re.search(r"export const REASON: [^=]*= \{(.*?)\n\};", src, re.S)
    label = re.search(r"export const GROUP_LABEL: [^=]*= \{(.*?)\n\};", src, re.S)
    days = re.search(r"reasonWaterDays = \(n: number\) => `([^`]*)`", src)
    mild = re.search(r'REASON_WATER_UP_MILD = "([^"]*)"', src)
    if not (block and label and days and mild):
        raise ValueError("copy.ts 에서 근거 문구를 찾지 못함")
    reason = {
        m.group(1): {"up": m.group(2), "down": m.group(3)}
        for m in re.finditer(r'(\w+): \{ up: "([^"]*)", down: "([^"]*)" \}', block.group(1))
    }
    labels = dict(re.findall(r'(\w+): "([^"]*)"', label.group(1)))
    return {"reason": reason, "label": labels, "water_days": days.group(1), "water_up_mild": mild.group(1)}


def content_hash(rows: list[dict]) -> str:
    """행 목록의 내용 해시: (site_id, base_date, target_date, id) 정렬 → 키 정렬 JSON → sha256."""
    srt = sorted(
        rows,
        key=lambda r: (
            str(r.get("site_id")),
            str(r.get("base_date")),
            str(r.get("target_date")),
            r.get("id"),
        ),
    )
    blob = json.dumps(srt, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------- DB(읽기) · 피처 원천
def fetch_all(sb: Any, table: str, run_id: str, select: str = "*") -> list[dict]:
    rows, start = [], 0
    while True:
        chunk = sb.table(table).select(select).eq("run_id", run_id).range(start, start + 999).execute().data
        rows += chunk
        if len(chunk) < 1000:
            break
        start += 1000
    return rows


def features_from_bundle(keys: list[tuple[str, str]], code2sid: dict[str, str]) -> pd.DataFrame:
    """features_S1 에서 (지점, 기준일) 같은 행(as-of 피처, target·horizon 포함 그대로)."""
    feat = pd.read_parquet(D._features_path("S1"))
    feat["base_date"] = pd.to_datetime(feat["base_date"])
    want = pd.DataFrame(
        {"station_id": [code2sid[s] for s, _ in keys], "base_date": pd.to_datetime([b for _, b in keys])}
    )
    out = feat.merge(want, on=["station_id", "base_date"])
    dup = out.duplicated(["station_id", "base_date"]).sum()
    if dup:
        raise SystemExit(f"중단: features_S1 에 같은 (지점, 기준일) 행이 {dup}개 겹침")
    return out.reset_index(drop=True)


def features_from_asof(
    keys: list[tuple[str, str]], code2sid: dict[str, str], days: int = 400
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """일일 러너 방식(as-of 공공 API 증분 수집 → 일 달력 → feature_rows → v2 상류 열 부착). 네트워크 필요."""
    from algaecast.predict.asof import (
        attach_model_features,
        build_daily,
        collect_recent,
        feature_rows,
        load_cfgs,
        window_start,
    )

    sites_cfg, feat_cfg = load_cfgs()
    end = max(date.fromisoformat(b) for _, b in keys)
    start = window_start(end, days)
    src = collect_recent(sites_cfg, start, end)
    daily = build_daily(sites_cfg, feat_cfg, src, start, end)
    frames = []
    for b in sorted({b for _, b in keys}):
        bases = {code2sid[s]: date.fromisoformat(b) for s, bb in keys if bb == b}
        frames.append(feature_rows(daily, sites_cfg, bases))
    feat = pd.concat(frames, ignore_index=True)
    return attach_model_features(feat, src.get("algae")), src.get("algae")


def point_preds(feat: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.Series:
    """대조용 점예측(레지스트리 current). 저장하지 않는다."""
    from algaecast.db.upload import predict_registry

    if feat.empty:
        return pd.Series(dtype=float)
    return pd.Series(predict_registry(feat, algae=algae)["pred_cell_count"].to_numpy(), index=feat.index)


def shap_rows_like_daily(
    run_id: str, cfg: dict, feat: pd.DataFrame, algae: pd.DataFrame | None = None
) -> list[dict]:
    """일일 운영과 같은 함수(shap_and_reco_rows)를 기준일 묶음(지점당 1행)마다 호출 — 권고는 버린다."""
    from algaecast.db.upload import shap_and_reco_rows

    out: list[dict] = []
    for _, grp in feat.groupby(feat["base_date"].astype(str), sort=True):
        if grp["station_id"].duplicated().any():
            raise SystemExit("중단: 같은 기준일 묶음에 같은 지점이 둘")
        rows, _reco = shap_and_reco_rows(run_id, cfg, grp.copy(), algae=algae)
        out += rows
    return out


def hot_days(sb: Any, site_id: str, asof: str) -> int:
    """지점 상세의 보조 문구용: asof-30 ≤ 관측일 ≤ asof 에서 수온 ≥ 25℃ 인 측정 수(관측 테이블 읽기)."""
    lo = (date.fromisoformat(asof) - timedelta(days=HOT_DAYS_WINDOW)).isoformat()
    data = (
        sb.table("observations")
        .select("obs_date,water_temp")
        .eq("site_id", site_id)
        .gte("obs_date", lo)
        .lte("obs_date", asof)
        .execute()
        .data
    )
    return sum(1 for r in data if (r.get("water_temp") or 0) >= HOT_TEMP)


# ---------------------------------------------------------------- 보고
def md_table(df: pd.DataFrame, floatfmt: str = "{:.4g}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def scene_report(sb: Any, run_id: str, site_id: str, base_date: str, texts: dict | None) -> dict:
    rows = (
        sb.table("shap_contributions")
        .select("feature_name,feature_group,shap_value,feature_value,rank")
        .eq("run_id", run_id)
        .eq("site_id", site_id)
        .eq("base_date", base_date)
        .order("rank")
        .execute()
        .data
    )
    hd = hot_days(sb, site_id, base_date)
    return {
        "site_id": site_id,
        "base_date": base_date,
        "hot_days_25c_30d": hd,
        "top8": rows,
        "reasons_top3": reasons_top3(rows, hd, texts),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default=REPLAY_RUN_ID)
    ap.add_argument("--since", default=REPLAY_MIN, help="이 기준일부터(기본 2026-01-01)")
    ap.add_argument("--until", default=None, help="이 기준일까지(기본 제한 없음)")
    ap.add_argument("--dry-run", action="store_true", help="DB 에 쓰지 않고 행 수·표본·대조표만")
    ap.add_argument(
        "--asof-fallback",
        action="store_true",
        help="번들 피처가 안 맞는 키를 as-of 수집(네트워크)으로 재시도",
    )
    ap.add_argument("--out", type=Path, default=None, help="증거 파일(JSON·CSV)을 둘 폴더")
    ap.add_argument(
        "--scene", action="append", default=None, help="보고할 장면 site_id:YYYY-MM-DD (반복 가능)"
    )
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # Windows 콘솔(cp949)에서 '—'·한글 출력
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 URL 로그 끔

    from algaecast.db.upload import client, upsert

    cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    code2sid = {s["site_code"]: s["station_id"] for s in cfg["sites"]}
    sb = client()
    # 0) 레지스트리 current == run 의 model_version
    run = (
        sb.table("model_runs")
        .select("run_id,model_version,status,run_at")
        .eq("run_id", args.run_id)
        .execute()
        .data
    )
    if not run:
        raise SystemExit(f"중단: model_runs 에 run {args.run_id} 없음")
    cur = R.current_versions().get("regression")
    if cur != run[0]["model_version"]:
        raise SystemExit(f"중단: 레지스트리 current 회귀 {cur} ≠ run model_version {run[0]['model_version']}")
    log.info(
        "run %s model_version %s == registry current (%s)", args.run_id, cur, R.current_kind("regression")
    )
    # 1) 저장 전 증거
    pred_before = fetch_all(sb, "predictions", args.run_id)
    shap_before = fetch_all(sb, "shap_contributions", args.run_id, "site_id,base_date,feature_name,rank")
    h_before = content_hash(pred_before)
    keys = missing_keys(pred_before, shap_before, since=args.since, until=args.until)
    stored = {(str(r["site_id"]), str(r["base_date"])[:10]): float(r["pred_cell_count"]) for r in pred_before}
    log.info(
        "predictions %d행 (hash %s…), shap %d행, 채울 키 %d",
        len(pred_before),
        h_before[:12],
        len(shap_before),
        len(keys),
    )
    if not keys:
        print(json.dumps({"status": "nothing_to_do", "predictions": len(pred_before)}, ensure_ascii=False))
        return 0
    # 2) 피처 원천 대조
    cmp_rows: list[dict] = []
    chosen: dict[tuple[str, str], str] = {}
    fb = features_from_bundle(keys, code2sid)
    pb = point_preds(fb)
    cand: dict[tuple[str, str], dict[str, float | None]] = {k: {"features": None, "asof": None} for k in keys}
    sid2code = {v: k for k, v in code2sid.items()}
    for i, r in fb.iterrows():
        cand[(sid2code[r["station_id"]], str(r["base_date"])[:10])]["features"] = float(pb[i])
    fa, algae_asof = pd.DataFrame(), None
    if args.asof_fallback:
        todo = [k for k in keys if choose_source(stored[k], cand[k]) is None]
        if todo:
            fa, algae_asof = features_from_asof(todo, code2sid)
            pa = point_preds(fa, algae_asof)
            for i, r in fa.iterrows():
                cand[(sid2code[r["station_id"]], str(r["base_date"])[:10])]["asof"] = float(pa[i])
    for k in keys:
        src = choose_source(stored[k], cand[k])
        if src:
            chosen[k] = src
        f_, a_ = cand[k]["features"], cand[k]["asof"]
        cmp_rows.append(
            {
                "site_id": k[0],
                "base_date": k[1],
                "stored_pred": stored[k],
                "features_pred": f_,
                "asof_pred": a_,
                "rel_diff_features": None if f_ is None else abs(f_ - stored[k]) / (abs(stored[k]) + 1e-9),
                "source": src or "none",
            }
        )
    cmp = pd.DataFrame(cmp_rows)
    summary_src = cmp.groupby("source").size().to_dict()
    log.info("원천 선택: %s", summary_src)
    # 3) SHAP(일일 운영과 같은 함수) — 맞는 원천의 피처 행만
    use_b = fb[
        [chosen.get((sid2code[r.station_id], str(r.base_date)[:10])) == "features" for r in fb.itertuples()]
    ]
    rows = shap_rows_like_daily(args.run_id, cfg, use_b) if len(use_b) else []
    if len(fa):
        use_a = fa[
            [chosen.get((sid2code[r.station_id], str(r.base_date)[:10])) == "asof" for r in fa.itertuples()]
        ]
        if len(use_a):
            rows += shap_rows_like_daily(args.run_id, cfg, use_a, algae_asof)
    new_keys = {(r["site_id"], r["base_date"]) for r in rows}
    if rows and not ranks_ok(rows):
        raise SystemExit("중단: 순위 규칙 위반(1..8, |shap| 내림차순)")
    if new_keys - set(chosen):
        raise SystemExit("중단: 선택되지 않은 키의 SHAP 행이 생김")
    have = {(str(r["site_id"]), str(r["base_date"])[:10]) for r in shap_before}
    if new_keys & have:
        raise SystemExit("중단: 이미 있는 키를 넣으려 함")
    sample = pd.DataFrame(rows).head(16) if rows else pd.DataFrame()
    print(f"\n## 피처 원천 대조 ({len(keys)}키) — 일치 기준 |Δlog10(x+1)| ≤ 1e-6 또는 상대차 ≤ 1e-6")
    print(md_table(pd.DataFrame([{"원천": k, "키 수": v} for k, v in summary_src.items()])))
    print(f"최대 상대차(features): {cmp['rel_diff_features'].max():.3g}")
    unmatched = cmp[cmp["source"] == "none"]
    if len(unmatched):
        print("\n### 넣지 않은 키(둘 다 불일치)\n" + md_table(unmatched))
    print(f"\n## 넣을 SHAP 행 {len(rows)} (키 {len(new_keys)} × {TOP_K}) — 표본\n" + md_table(sample))
    result: dict[str, Any] = {
        "run_id": args.run_id,
        "model_version": cur,
        "dry_run": args.dry_run,
        "predictions_before": {"n": len(pred_before), "sha256": h_before},
        "shap_before": {"n": len(shap_before), "keys": len(have)},
        "keys_missing": len(keys),
        "source_counts": summary_src,
        "rows_to_insert": len(rows),
        "keys_to_insert": len(new_keys),
        "unmatched_keys": unmatched[["site_id", "base_date"]].to_dict("records"),
    }
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        cmp.to_csv(
            args.out / "feature_source_compare.csv", index=False, encoding="utf-8", lineterminator="\n"
        )
        pd.DataFrame(rows).to_csv(
            args.out / "shap_rows.csv", index=False, encoding="utf-8", lineterminator="\n"
        )
    # 4) 저장(insert only) → 저장 후 증거
    if not args.dry_run and rows:
        fresh = fetch_all(sb, "shap_contributions", args.run_id, "site_id,base_date")
        fresh_keys = {(str(r["site_id"]), str(r["base_date"])[:10]) for r in fresh}
        rows = [r for r in rows if (r["site_id"], r["base_date"]) not in fresh_keys]
        n_ins = upsert(sb, "shap_contributions", rows, None, False)  # on_conflict=None → insert
        pred_after = fetch_all(sb, "predictions", args.run_id)
        shap_after = fetch_all(sb, "shap_contributions", args.run_id, "site_id,base_date,feature_name,rank")
        h_after = content_hash(pred_after)
        after_keys = {(str(r["site_id"]), str(r["base_date"])[:10]) for r in shap_after}
        result.update(
            {
                "inserted": n_ins,
                "predictions_after": {"n": len(pred_after), "sha256": h_after},
                "predictions_unchanged": (len(pred_after) == len(pred_before)) and (h_after == h_before),
                "shap_after": {
                    "n": len(shap_after),
                    "keys": len(after_keys),
                    "keys_added": len(after_keys - have),
                },
            }
        )
        if not result["predictions_unchanged"]:
            log.error("predictions 내용이 저장 전후로 다르다 — 즉시 확인 필요")
    # 5) 장면 보고(DB 에서 다시 읽음; dry-run 이면 계산한 행으로)
    texts = None
    try:
        texts = load_copy_texts(COPY_TS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("copy.ts 문구를 읽지 못해 문장 없이 보고: %s", exc)
    scenes = []
    for sc in args.scene or list(DEFAULT_SCENES):
        site_id, b = sc.split(":")
        if args.dry_run:
            top = sorted(
                [r for r in rows if r["site_id"] == site_id and r["base_date"] == b], key=lambda r: r["rank"]
            )
            hd = hot_days(sb, site_id, b)
            scenes.append(
                {
                    "site_id": site_id,
                    "base_date": b,
                    "hot_days_25c_30d": hd,
                    "top8": top,
                    "reasons_top3": reasons_top3(top, hd, texts),
                }
            )
        else:
            scenes.append(scene_report(sb, args.run_id, site_id, b, texts))
    result["scenes"] = scenes
    for s in scenes:
        print(
            f"\n## 장면 {s['site_id']} {s['base_date']} (최근 30일 25℃ 이상 측정 {s['hot_days_25c_30d']}회)"
        )
        if s["top8"]:
            print(
                md_table(
                    pd.DataFrame(s["top8"])[
                        ["rank", "feature_name", "feature_group", "shap_value", "feature_value"]
                    ]
                )
            )
        for i, r in enumerate(s["reasons_top3"], 1):
            print(f"{i}. [{r['label']} · {r['direction']} {r['share_pct']}%] {r['text']}")
    if args.out:
        (args.out / "backfill_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    print(
        "\n" + json.dumps({k: v for k, v in result.items() if k != "scenes"}, ensure_ascii=False, default=str)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
