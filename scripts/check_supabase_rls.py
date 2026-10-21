"""Supabase RLS 점검 (T6 DoD): anon 키로 SELECT 가능 · INSERT 불가, service_role 로 뷰 조회. 키
값은 출력하지 않는다.

사용: python scripts/check_supabase_rls.py
"""

from __future__ import annotations

import sys

from supabase import create_client

from algaecast.config import get_env


def mask(v: str | None) -> str:
    return "(없음)" if not v else f"{v[:6]}…(len {len(v)})"


def main() -> int:
    url = get_env("SUPABASE_URL", required=True)
    anon = get_env("SUPABASE_ANON_KEY", required=True)
    svc = get_env("SUPABASE_SERVICE_ROLE_KEY")
    print(f"URL {url} / anon {mask(anon)} / service_role {mask(svc)}")
    sb = create_client(url, anon)
    ok = True
    for t in ("sites", "observations", "predictions", "bloom_events", "transition_metrics", "v_site_status"):
        try:
            n = len(sb.table(t).select("*").limit(3).execute().data)
            print(f"anon SELECT {t}: OK ({n} rows sampled)")
        except Exception as exc:  # noqa: BLE001
            print(f"anon SELECT {t}: FAIL {type(exc).__name__}")
            ok = False
    try:
        sb.table("sites").insert(
            {"site_id": "ZZZZ", "name": "x", "basin": "x", "facility_type": "weir", "lat": 0, "lon": 0}
        ).execute()
        print("anon INSERT sites: ALLOWED (문제!)")
        ok = False
        if svc:
            create_client(url, svc).table("sites").delete().eq("site_id", "ZZZZ").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"anon INSERT sites: 거부됨 ({type(exc).__name__}) — 기대 동작")
    try:
        sb.table("predictions").update({"pred_cell_count": 0}).eq("site_id", "2011G26").execute()
        res = sb.table("predictions").select("id").eq("site_id", "2011G26").limit(1).execute()
        print("anon UPDATE predictions: 오류 없음 (RLS 로 0행 영향이면 정상)" if res.data is not None else "")
    except Exception as exc:  # noqa: BLE001
        print(f"anon UPDATE predictions: 거부됨 ({type(exc).__name__})")
    if svc:
        rows = (
            create_client(url, svc)
            .table("v_site_status")
            .select("site_id,name,tier,q50,p_alert,latest_cell_count,priority_rank")
            .execute()
            .data
        )
        print("v_site_status:", rows)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
