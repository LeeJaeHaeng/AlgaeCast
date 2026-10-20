"""물모아 'AI 녹조 정밀 예측 정보' 스냅샷 수집 (WQ-04 벤치마크, 인증 불필요).

서버는 지점당 최근 3회 발표분만 돌려주므로 월·목(발표일) 이후 매일 실행해 원문 JSON 을 쌓는다.
저장: data/raw/nier_forecast/mulmoa/<YYYY-MM-DD>_{sites,grid}.json (같은 날 재실행은 덮어씀).
T1-e 에서 이 원문을 발표일·지점·D+1~7 단계 테이블로 정규화한다.

사용: python scripts/snapshot_mulmoa_forecast.py [--out data/raw/nier_forecast/mulmoa]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import requests

from algaecast.config import RAW_DIR

BASE = "https://www.mulmoa.go.kr/web/totalSearch/water"
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
SITES = ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"]
TIMEOUT = 40


def fetch_sites(session: requests.Session) -> dict:
    """A. 지점코드 지정 최신 발표 7일 단계."""
    r = session.post(
        f"{BASE}/algaeMap/beforBlalMapDataCall",
        data={"ATTR_1S": json.dumps(SITES)},
        headers=HEADERS,
        timeout=TIMEOUT,
        verify=False,
    )
    r.raise_for_status()
    return r.json()


def fetch_grid(session: requests.Session, today: date) -> dict:
    """B. 전 지점 최근 3회 발표 + 최근 관측치."""
    r = session.post(
        f"{BASE}/algaeBeforInfo/mesureDataCall",
        data={
            "data_code": "16",
            "tbmn_sn": "19",
            "pDataGubun": "58",
            "pLgubun": "02",
            "ATTR_1S": json.dumps(["1", "2", "3", "4"]),
            "pSDate": today.strftime("%Y%m%d"),
            "excel": "N",
        },
        headers=HEADERS,
        timeout=TIMEOUT,
        verify=False,
    )
    r.raise_for_status()
    return r.json()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=RAW_DIR / "nier_forecast" / "mulmoa")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    today = date.today()
    requests.packages.urllib3.disable_warnings()  # 사이트 인증서 체인 검증 불가 (조사 시 확인)
    with requests.Session() as s:
        s.get("https://www.mulmoa.go.kr/web", headers=HEADERS, timeout=TIMEOUT, verify=False)  # 세션 쿠키
        sites = fetch_sites(s)
        grid = fetch_grid(s, today)
    for name, payload in (("sites", sites), ("grid", grid)):
        path = args.out / f"{today.isoformat()}_{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        rows = payload.get("list") or []
        print(f"{path.name}: {len(rows)} rows")
    rows_a = sites.get("list") or []
    issued = sorted({r["PRSNTN_NOW_YMD"] for r in rows_a if r.get("PRSNTN_NOW_YMD")})
    print("발표일:", issued or "(예측정보 제공기간 아님)")
    for row in sites.get("list") or []:
        days = " ".join(str(row.get(f"SUMMARY_D{k}", "")) for k in range(2, 9))
        print(f"  {row.get('SWMN_NM')}/{row.get('SWMN_DTL_NM')}: {days}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
