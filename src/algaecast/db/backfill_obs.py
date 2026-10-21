"""실측 도착 시 predictions.obs_cell_count 갱신 (T6, docs/05 §5). 사후 검증 차트용.

observations(site_id, obs_date=target_date) 의 cell_count 를 obs_cell_count 가 비어 있는
predictions 행에 채운다.
사용: python -m algaecast.db.backfill_obs [--dry-run]
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from algaecast.db.upload import client

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sb = client()
    preds = (
        sb.table("predictions")
        .select("id,site_id,target_date")
        .is_("obs_cell_count", "null")
        .limit(10000)
        .execute()
        .data
    )
    if not preds:
        print("갱신 대상 없음")
        return 0
    pdf = pd.DataFrame(preds)
    obs = (
        sb.table("observations")
        .select("site_id,obs_date,cell_count")
        .in_("site_id", sorted(pdf["site_id"].unique()))
        .execute()
        .data
    )
    odf = pd.DataFrame(obs).dropna(subset=["cell_count"])
    m = pdf.merge(odf, left_on=["site_id", "target_date"], right_on=["site_id", "obs_date"], how="inner")
    n = 0
    for r in m.itertuples():
        if not args.dry_run:
            sb.table("predictions").update({"obs_cell_count": float(r.cell_count)}).eq(
                "id", int(r.id)
            ).execute()
        n += 1
    print(f"obs_cell_count 갱신 {n}행 (대상 {len(pdf)}, 실측 매칭 {len(m)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
