"""캐시·처리 산출물에서 목표일 ≥ 2026-01-01 인 행(정답이 2026 측정)을 지운다.

대상: data/processed/exp/ 아래 parquet·csv(실험 캐시), data/processed/oof_predictions.parquet.
- 목표일 열(target_date)이 있는 표에서 해당 행을 지우고 다시 쓴다. 남는 행이 없으면 파일을 지운다.
- 격리·사후 검증 파일(live)은 건드리지 않는다:
  test_targets_DO_NOT_USE.parquet, posthoc_2026*.parquet(data/processed 바로 아래).
결과: 지운 파일·행 수를 출력하고 data/processed/exp/purge_2026_log.json 에 남긴다
(정답값은 기록하지 않음).
사용: python scripts/purge_2026_targets.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = pd.Timestamp("2026-01-01")
LIVE = {"test_targets_DO_NOT_USE.parquet", "posthoc_2026.parquet", "posthoc_2026_v2.parquet"}


def targets() -> list[Path]:
    exp = ROOT / "data" / "processed" / "exp"
    files = (
        [p for p in exp.rglob("*") if p.is_file() and p.suffix.lower() in (".parquet", ".csv")]
        if exp.exists()
        else []
    )
    oof = ROOT / "data" / "processed" / "oof_predictions.parquet"
    return sorted(files + ([oof] if oof.exists() else []))


def purge(p: Path, dry: bool) -> tuple[str, int, int]:
    """(조치, 지운 행, 전체 행)."""
    if p.name in LIVE and p.parent == ROOT / "data" / "processed":
        return ("허용(live)", 0, 0)
    if p.suffix.lower() == ".parquet":
        names = pq.read_schema(p).names
        if "target_date" not in names and "base_date" not in names:
            return ("해당 없음", 0, 0)
        df = pd.read_parquet(p)
    else:
        head = p.read_text(encoding="utf-8-sig", errors="ignore").splitlines()[:1]
        if not head or ("target_date" not in head[0] and "base_date" not in head[0]):
            return ("해당 없음", 0, 0)
        df = pd.read_csv(p, encoding="utf-8-sig", low_memory=False)
    vcols = [c for c in ("target_cells", "target_log", "target", "y_true") if c in df.columns]
    dcol = "target_date" if "target_date" in df.columns else "base_date"
    if dcol == "base_date" and not vcols:
        return ("해당 없음", 0, len(df))  # 목표일 열 없이 정답값도 없는 표(예측·피처 캐시)는 그대로
    td = pd.to_datetime(df[dcol], errors="coerce")  # 목표일 열이 없으면 기준일(≥2026 → 목표일도 2026)
    bad = (td >= CUTOFF).to_numpy()
    n = int(bad.sum())
    if n == 0:
        return ("해당 없음", 0, len(df))
    if dry:
        return ("삭제 예정", n, len(df))
    keep = df.loc[~bad]
    if keep.empty:
        p.unlink()
        return ("파일 삭제", n, len(df))
    if p.suffix.lower() == ".parquet":
        keep.to_parquet(p, index=False)
    else:
        keep.to_csv(p, index=False, encoding="utf-8-sig")
    return ("행 삭제", n, len(df))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    log = []
    for p in targets():
        action, n, total = purge(p, args.dry_run)
        if n:
            log.append(
                {
                    "file": p.relative_to(ROOT).as_posix(),
                    "action": action,
                    "rows_removed": n,
                    "rows_before": total,
                }
            )
    files_deleted = sum(1 for r in log if r["action"] == "파일 삭제")
    rows = sum(r["rows_removed"] for r in log)
    tag = " (dry-run)" if args.dry_run else ""
    print(f"대상 파일 {len(log)}개(파일째 삭제 {files_deleted}개), 지운 행 {rows}개{tag}")
    if not args.dry_run:
        out = ROOT / "data" / "processed" / "exp" / "purge_2026_log.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"run_at": datetime.now().isoformat(timespec="seconds"), "files": log},
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
