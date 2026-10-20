"""data.go.kr 인증키·엔드포인트 점검 스크립트.

.env 의 DATA_GO_KR_KEY 로 승인된 4개 서비스를 각 1회 호출해 resultCode·건수를 출력한다.
다목적댐 API 는 일일 트래픽이 100 건이므로 반복 실행에 주의.

사용: python scripts/check_api_keys.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

from algaecast.config import get_env

TIMEOUT = 30


def _redact(text: str) -> str:
    """오류 메시지(요청 URL 포함)에 섞인 인증키를 *** 로 가린다."""
    key = get_env("DATA_GO_KR_KEY") or ""
    for secret in {key, urllib.parse.quote(key, safe=""), get_env("DATA_GO_KR_KEY_ENC") or ""}:
        if secret:
            text = text.replace(secret, "***")
    return text


def _year_ago(d: date) -> date:
    """전년 동일 날짜. 2월 29일이면 2월 28일로 내린다."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def _call(url: str, params: dict[str, str]) -> tuple[str, str, int, list[str]]:
    """(resultCode, resultMsg, totalCount, 첫 item 의 필드명 목록)을 반환한다."""
    params = {"serviceKey": get_env("DATA_GO_KR_KEY", required=True), **params}
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text.strip()
    if text.startswith("{"):
        payload = r.json()
        if "data" in payload and "totalCount" in payload:  # odcloud 파일데이터 API
            first = payload["data"][0] if payload["data"] else {}
            return "00", "odcloud", int(payload["totalCount"]), list(first.keys())
        if "result" in payload and "list" in payload:  # WAMIS 개방 API
            res = payload["result"]
            code = "00" if res.get("code") == "success" else str(res.get("code"))
            first = payload["list"][0] if payload["list"] else {}
            return (
                code,
                res.get("msg", ""),
                int(payload.get("count", len(payload["list"]))),
                list(first.keys()),
            )
        body = payload["response"]
        header, items = body["header"], body["body"]
        item = items.get("items") or {}
        raw = item.get("item") if isinstance(item, dict) else None
        records = raw if isinstance(raw, list) else ([raw] if raw else [])  # 단일 레코드는 dict 로 온다
        first = records[0] if records else {}
        return header["resultCode"], header["resultMsg"], int(items.get("totalCount", 0)), list(first.keys())
    root = ET.fromstring(r.content)  # XML 선언의 encoding 을 존중
    if root.tag == "OpenAPI_ServiceResponse":  # 포털 레벨 오류 (키 미등록, 트래픽 초과 등)
        code = root.findtext(".//returnReasonCode") or "?"
        return code, root.findtext(".//returnAuthMsg") or "", 0, []
    first_item = root.find(".//item")
    fields = [c.tag for c in first_item] if first_item is not None else []
    return (
        root.findtext(".//resultCode") or "?",
        root.findtext(".//resultMsg") or "",
        int(root.findtext(".//totalCount") or 0),
        fields,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--all", action="store_true", help="일 100건 제한 서비스(댐코드 조회)까지 호출")
    args = ap.parse_args(argv)
    d: date = args.date
    ymd = d.strftime("%Y%m%d")

    checks = {
        "KMA ASOS 일자료 (대전 133)": (
            get_env("API_KMA_ASOS_DAILY", required=True),
            {
                "pageNo": "1",
                "numOfRows": "3",
                "dataType": "JSON",
                "dataCd": "ASOS",
                "dateCd": "DAY",
                "startDt": ymd,
                "endDt": ymd,
                "stnIds": "133",
            },
        ),
        "KMA ASOS 시간자료 (대전 133)": (
            get_env("API_KMA_ASOS_HOURLY", required=True),
            {
                "pageNo": "1",
                "numOfRows": "3",
                "dataType": "JSON",
                "dataCd": "ASOS",
                "dateCd": "HR",
                "startDt": ymd,
                "startHh": "01",
                "endDt": ymd,
                "endHh": "03",
                "stnIds": "133",
            },
        ),
        "K-water 다목적댐 운영정보 (21개 댐)": (
            get_env("API_KWATER_DAM", required=True),
            {
                "pageNo": "1",
                "numOfRows": "30",
                "_type": "json",
                "vdate": d.isoformat(),
                "tdate": (d - timedelta(days=1)).isoformat(),
                "ldate": _year_ago(d).isoformat(),
                "vtime": "07",
            },
        ),
        "NIER 조류경보제 측정결과 (XML)": (
            get_env("API_NIER_ALGAE", required=True),
            {"pageNo": "1", "numOfRows": "3"},
        ),
        "K-water 수문 운영 정보 delist (강정고령보)": (
            get_env("API_KWATER_SLUICE", required=True) + "/delist",
            {
                "pageNo": "1",
                "numOfRows": "3",
                "_type": "json",
                "damcode": "2011602",
                "stdt": (d - timedelta(days=2)).isoformat(),
                "eddt": d.isoformat(),
            },
        ),
        "KMA 단기예보 getVilageFcst (대구 89,90)": (
            get_env("API_KMA_VILAGE_FCST", required=True) + "/getVilageFcst",
            {
                "pageNo": "1",
                "numOfRows": "3",
                "dataType": "JSON",
                "base_date": ymd,
                "base_time": "0500",
                "nx": "89",
                "ny": "90",
            },
        ),
        "KMA 유역별 강수량 (odcloud, 단일 일자 스냅샷)": (
            get_env("API_KMA_BASIN_RAIN_ODCLOUD", required=True),
            {"page": "1", "perPage": "3"},
        ),
        "WAMIS 댐 일자료 mn_dtdata (대청 3008110, 키 불필요)": (
            get_env("API_WAMIS_BASE", required=True) + "/wkd/mn_dtdata",
            {"damcd": "3008110", "startdt": ymd, "enddt": ymd, "output": "json"},
        ),
    }
    if args.all:  # 일 100건 제한 서비스는 명시적으로만 호출
        checks["K-water 댐코드 조회 (일 100건)"] = (
            get_env("API_KWATER_DAMCODE", required=True),
            {"pageNo": "1", "numOfRows": "100", "_type": "json"},
        )
    ok = True
    print(f"기준일 {d.isoformat()}")
    for name, (url, params) in checks.items():
        try:
            code, msg, total, fields = _call(url, params)
        except Exception as exc:  # noqa: BLE001 - 점검 스크립트는 모든 예외를 보고만 한다
            code, msg, total, fields = "EXC", _redact(f"{type(exc).__name__}: {exc}"), 0, []
        status = "OK " if code == "00" else "FAIL"
        ok &= code == "00"
        print(f"[{status}] {name:<32} code={code} msg={msg} totalCount={total} fields={len(fields)}")
        if fields:
            tail = " ..." if len(fields) > 12 else ""
            print("        " + ", ".join(fields[:12]) + tail)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
