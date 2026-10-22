"""MT-05b 기상청 API허브 단기예보 과거 발표분 — 접근 점검(프로브)과 5지점 격자 (EXP-005 2차 P3).

목적: 단기예보 과거 발표분(2010-06~)을 5지점 격자(nx, ny)로 받아 '기준일 05시 발표분 +1~+3일' 피처를 만든다.

상태(2026-10-22 점검): ``KMA_APIHUB_KEY`` 는 인증을 통과한다(예보구역 조회 API 200, 잘못된 키는 401).
그러나 단기예보 자료 API(격자 ``nph-dfs_shrt_grd`` 등, API허브판 단기예보 조회서비스, 단기 육상예보)는 모두
HTTP 403 "활용신청이 필요한 API 입니다"를 돌려준다. 공공데이터포털 단기예보 2.0 은 "최근 3일 간의 자료만"
제공한다(resultCode 10). 따라서 자료 수집은 하지 않았고, 이 모듈은 접근 점검과 격자 정보만 담는다.
API허브에서 해당 API 활용신청이 승인되면 ``python -m algaecast.collect.kma_apihub_fcst`` 로 다시 점검한다.

키 취급: ``authKey`` 는 요청 인자로만 쓰고, 응답·예외 문자열에서 키 값을 지운 뒤 기록한다(``scrub``).
점검 결과는 캐시하지 않는다(현재 상태 확인용). 키 값·키 일부는 어떤 출력에도 남기지 않는다.

사용: python -m algaecast.collect.kma_apihub_fcst [--out reports/experiments/EXP-005/P3/probe.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from algaecast.collect.base import KST
from algaecast.collect.kma_forecast import latlon_to_grid
from algaecast.config import ROOT, get_env
from algaecast.features.base import sites_cfg

log = logging.getLogger(__name__)

APIHUB = "https://apihub.kma.go.kr/api/"
KEY_ENV = "KMA_APIHUB_KEY"
PORTAL_KEY_ENV = "DATA_GO_KR_KEY"
OUT_RAW = ROOT / "data" / "raw" / "kma_fcst_hist"  # 승인 후 원자료 저장 위치(현재 비어 있음)
DEFAULT_OUT = ROOT / "reports" / "experiments" / "EXP-005" / "P3" / "probe.json"
INVALID_KEY = "INVALIDKEY0000000000000"  # 대조용 가짜 키(인증 실패 응답 확인)


@dataclass(frozen=True)
class Endpoint:
    """점검 대상 API. path 는 APIHUB 뒤 경로(또는 portal=True 면 공공데이터포털 전체 URL 환경변수 이름)."""

    name: str
    path: str
    params: dict[str, str] = field(default_factory=dict)
    role: str = ""
    portal: bool = False
    fake_key: bool = False


# 과거 발표분을 받을 수 있는 경로(핵심 → 대안) + 키 유효성 대조
ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint(
        "단기예보 격자자료",
        "typ01/cgi-bin/url/nph-dfs_shrt_grd",
        {"tmfc": "2024060105", "tmef": "2024060206", "vars": "TMP"},
        "핵심 경로: 발표시각(tmfc)·발효시각(tmef)·변수별 전국 격자",
    ),
    Endpoint(
        "초단기예보 격자자료",
        "typ01/cgi-bin/url/nph-dfs_vsrt_grd",
        {"tmfc": "2024060105", "tmef": "2024060106", "vars": "T1H"},
        "같은 묶음(동네예보 격자) 접근 확인",
    ),
    Endpoint(
        "초단기실황 격자자료",
        "typ01/cgi-bin/url/nph-dfs_odam_grd",
        {"tmfc": "2024060105", "vars": "T1H"},
        "같은 묶음 접근 확인",
    ),
    Endpoint(
        "격자-위경도 변환",
        "typ01/cgi-bin/url/nph-dfs_xy_lonlat",
        {"lon": "128.3873", "lat": "36.1695", "help": "0"},
        "같은 묶음 접근 확인",
    ),
    Endpoint(
        "단기예보 조회서비스(API허브판)",
        "typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst",
        {
            "pageNo": "1",
            "numOfRows": "10",
            "dataType": "JSON",
            "base_date": "20241001",
            "base_time": "0500",
            "nx": "85",
            "ny": "97",
        },
        "대안: 지점 격자 단위 조회(과거 제공 범위는 승인 후 확인 필요)",
    ),
    Endpoint(
        "단기 육상예보",
        "typ01/url/fct_afs_dl.php",
        {"reg": "11H10602", "tmfc1": "2024060105", "tmfc2": "2024060105", "disp": "0"},
        "대안: 예보구역 단위(격자 아님) 기온·강수확률·하늘상태",
    ),
    Endpoint(
        "단기 육상예보 v2",
        "typ01/url/fct_afs_dl2.php",
        {"reg": "11H10602", "tmfc1": "2024060105", "tmfc2": "2024060105", "disp": "0"},
        "대안: 예보구역 단위",
    ),
    Endpoint("단기 개황", "typ01/url/fct_afs_ds.php", {"help": "1"}, "같은 묶음 접근 확인"),
    Endpoint(
        "단기예보구역 조회", "typ01/url/fct_shrt_reg.php", {"tmfc": "0", "disp": "0"}, "키 유효성 확인(대조)"
    ),
    Endpoint("중기예보구역 조회", "typ01/url/fct_medm_reg.php", {"help": "1"}, "키 유효성 확인(대조)"),
    Endpoint(
        "단기예보 격자자료(잘못된 키)",
        "typ01/cgi-bin/url/nph-dfs_shrt_grd",
        {"tmfc": "2024060105", "tmef": "2024060206", "vars": "TMP"},
        "대조: 인증 실패일 때의 응답",
        fake_key=True,
    ),
    Endpoint(
        "공공데이터포털 단기예보 2.0(과거 발표일)",
        "API_KMA_VILAGE_FCST",
        {
            "pageNo": "1",
            "numOfRows": "5",
            "dataType": "JSON",
            "base_date": "20241001",
            "base_time": "0500",
            "nx": "85",
            "ny": "97",
        },
        "대안: data.go.kr(과거 제공 범위 확인)",
        portal=True,
    ),
)


# ---------------------------------------------------------------- 격자
def site_grids() -> list[dict[str, Any]]:
    """config/sites.yaml 5지점의 (lat, lon) → 단기예보 격자(nx, ny). 좌표는 sites.yaml 의 근사값이다."""
    out = []
    for s in sites_cfg()["sites"]:
        nx, ny = latlon_to_grid(float(s["lat"]), float(s["lon"]))
        out.append(
            {
                "station_id": s["station_id"],
                "site_code": s["site_code"],
                "lat": float(s["lat"]),
                "lon": float(s["lon"]),
                "nx": nx,
                "ny": ny,
            }
        )
    return out


# ---------------------------------------------------------------- 점검
def scrub(text: str, secrets: list[str]) -> str:
    """문자열에서 비밀값(키)을 모두 지운다."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _decode(body: bytes, enc: str | None) -> str:
    for e in ("utf-8", "euc-kr", enc or "utf-8"):
        try:
            return body.decode(e)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def _message(text: str) -> str:
    """API허브 JSON 오류({"result": {"status", "message"}}) 또는 포털 헤더의 메시지, 아니면 앞부분."""
    try:
        j = json.loads(text)
    except ValueError:
        head = text.strip().splitlines()
        return " / ".join(h.strip() for h in head[:4])[:200]
    if isinstance(j, dict) and "result" in j:
        return str(j["result"].get("message", ""))
    if isinstance(j, dict) and "response" in j:
        h = j["response"].get("header", {})
        return f"resultCode={h.get('resultCode')} {h.get('resultMsg')}"
    return str(j)[:200]


def probe_one(
    ep: Endpoint,
    *,
    session: requests.Session | None = None,
    timeout: int = 60,
    retries: int = 2,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """API 하나를 한 번 호출해 HTTP 상태·메시지(키 제거)를 돌려준다. 5xx·네트워크 오류만 재시도."""
    sess = session or requests.Session()
    hub_key = get_env(KEY_ENV) or ""
    portal_key = (get_env(PORTAL_KEY_ENV) or "") if ep.portal else ""
    secrets = [hub_key, portal_key]
    if ep.portal:
        url = (get_env(ep.path) or "") + "/getVilageFcst"
        params = {"serviceKey": portal_key, **ep.params}
    else:
        url = APIHUB + ep.path
        params = {**ep.params, "authKey": INVALID_KEY if ep.fake_key else hub_key}
    rec: dict[str, Any] = {
        "name": ep.name,
        "url": "apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst" if ep.portal else url,
        "params": dict(ep.params),
        "role": ep.role,
        "key": "invalid(대조)" if ep.fake_key else ("DATA_GO_KR_KEY" if ep.portal else KEY_ENV),
        "checked_at": datetime.now(KST).isoformat(timespec="seconds"),
    }
    if not (portal_key if ep.portal else (hub_key or ep.fake_key)):
        rec.update({"http": None, "message": "키 환경변수가 없다", "ok": False})
        return rec
    last = ""
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = scrub(str(exc), secrets)
            sleep(2**attempt)
            continue
        text = _decode(r.content or b"", r.encoding)
        if r.status_code >= 500 and attempt < retries:
            last = f"HTTP {r.status_code}"
            sleep(2**attempt)
            continue
        msg = scrub(_message(text), secrets)
        ok = r.status_code == 200 and (not msg.startswith("resultCode=") or msg.startswith("resultCode=00"))
        rec.update(
            {
                "http": r.status_code,
                "content_type": r.headers.get("content-type"),
                "bytes": len(r.content or b""),
                "message": msg,
                "ok": bool(ok),
            }
        )
        return rec
    rec.update({"http": None, "message": f"호출 실패: {last}", "ok": False})
    return rec


def diagnose(results: list[dict[str, Any]]) -> dict[str, Any]:
    """점검 결과 → 판정: key_valid(구역 조회 200), data_access(핵심 경로 200), 사유."""
    by = {r["name"]: r for r in results}
    key_valid = any(by.get(n, {}).get("http") == 200 for n in ("단기예보구역 조회", "중기예보구역 조회"))
    core = by.get("단기예보 격자자료", {})
    data_ok = core.get("http") == 200
    alt_ok = [
        r["name"]
        for r in results
        if r.get("ok")
        and r["name"] not in ("단기예보구역 조회", "중기예보구역 조회")
        and "잘못된 키" not in r["name"]
    ]
    if data_ok:
        reason = "핵심 경로 접근 가능"
    elif key_valid and core.get("http") == 403:
        reason = "키 인증은 통과, 단기예보 자료 API 활용신청 미승인(HTTP 403)"
    elif core.get("http") == 401:
        reason = "키 인증 실패(HTTP 401)"
    else:
        reason = f"핵심 경로 호출 실패(HTTP {core.get('http')}: {core.get('message')})"
    return {"key_valid": key_valid, "data_access": data_ok, "alt_access": alt_ok, "reason": reason}


def probe_all(endpoints: tuple[Endpoint, ...] = ENDPOINTS, **kw: Any) -> dict[str, Any]:
    results = [probe_one(ep, **kw) for ep in endpoints]
    return {
        "checked_at": datetime.now(KST).isoformat(timespec="seconds"),
        "results": results,
        "diagnosis": diagnose(results),
        "site_grids": site_grids(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="점검 결과 JSON 경로")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = probe_all()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    for r in res["results"]:
        print(f"{r['name']}: HTTP {r['http']} — {r['message']}")
    print("판정:", json.dumps(res["diagnosis"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
