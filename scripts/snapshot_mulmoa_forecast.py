"""물모아 'AI 녹조 정밀 예측 정보' 스냅샷 수집 (WQ-04 벤치마크, 인증 불필요).

서버는 지점당 최근 3회 발표분만 돌려주므로 매일 실행해 쌓는다
(GitHub Actions: KST 06/09/18시, Windows 작업 스케줄러: 07시).
출력: data/raw/mulmoa/YYYY-MM-DD_HHMM.csv — 한 행 = (발표일, 지점, 예측일 +1~+7). 컬럼:
  collected_at_kst, issued_date, site_code, station_id, water_body, site_name, horizon_day, forecast_date,
  forecast_level(0~4), forecast_level_label, forecast_cells(물모아는 단계만 제공 → 항상 빈칸),
  obs_cells_latest(발표 시점 최근 관측 유해남조류 세포수), alert_latest(현재 경보), source
같은 날 마지막 CSV 와 내용(수집 시각 제외)이 같으면 파일을 만들지 않고 종료한다(--no-dedupe 로 끔).
원문 JSON 은 data/raw/mulmoa/raw/ 에 함께 남긴다(git 미추적).

벤치마크 사용 규칙은 algaecast.collect.nier_forecast 참조: 발표일(issued_date) ≤ base_date 인 발표분만 쓴다.

사용: python scripts/snapshot_mulmoa_forecast.py [--out data/raw/mulmoa] [--no-dedupe]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import urllib3

try:  # 저장소 밖(예: CI 최소 설치)에서도 돌아가게 폴백
    from algaecast.config import RAW_DIR
except ImportError:  # pragma: no cover
    RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

KST = ZoneInfo("Asia/Seoul")
BASE = "https://www.mulmoa.go.kr/web/totalSearch/water"
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
TIMEOUT = 40
# (수계, 지점명; 가운뎃점 제거) → (조사지점코드, 대회 station_id). 대상 5지점 + 대청호 2지점, 그 외 공란.
SITE_CODES: dict[tuple[str, str], tuple[str, str]] = {
    ("낙동강", "해평"): ("2011G26", "HP"),
    ("낙동강", "강정고령"): ("2011G56", "GJGR"),
    ("낙동강", "칠서"): ("2020G33", "CS"),
    ("낙동강", "물금매리"): ("2022G05", "MGMR"),
    ("대청호", "회남"): ("3008G30", "DCHN"),
    ("대청호", "추동"): ("3008G40", ""),
    ("대청호", "문의"): ("3008G50", ""),
}
DISPLAY = {"강정고령": "강정·고령", "물금매리": "물금·매리"}  # 출력용 표기(조류경보제 공식 지점명)
TARGET_CODES = [v[0] for k, v in SITE_CODES.items() if v[1]]
COLUMNS = [
    "collected_at_kst",
    "issued_date",
    "site_code",
    "station_id",
    "water_body",
    "site_name",
    "horizon_day",
    "forecast_date",
    "forecast_level",
    "forecast_level_label",
    "forecast_cells",
    "obs_cells_latest",
    "alert_latest",
    "source",
]
DEDUPE_IGNORE = {"collected_at_kst"}


def _norm_name(s: str | None) -> str:
    return re.sub(r"\s+", "", (s or "")).replace("ㆍ", "·").replace("・", "·")


def _key(spot1: str | None, spot2: str | None) -> tuple[str, str]:
    """(수역, 지점) 정규화 키. B 는 '낙동강(해평)'/'낙동강(해평)' 괄호 표기, A 는 '낙동강'/'해평'."""
    a, b = _norm_name(spot1), _norm_name(spot2)
    m = re.fullmatch(r"(.+?)\((.+)\)", a)
    if m and (b == a or not b):
        a, b = m.group(1), m.group(2)
    return a.replace("·", ""), b.replace("·", "")


def _level(label: str | None) -> str:
    m = re.match(r"\s*(\d)\s*단계", label or "")
    return m.group(1) if m else ""


def _num(s: str | None) -> str:
    t = (s or "").replace(",", "").strip()
    return t if re.fullmatch(r"\d+(\.\d+)?", t) else ""


def _ymd(s: str | None) -> date | None:
    t = (s or "").strip().replace("-", "").replace(".", "")
    try:
        return datetime.strptime(t, "%Y%m%d").date()
    except ValueError:
        return None


def fetch_sites(session: requests.Session) -> dict:
    """A. 대상 지점코드의 최신 발표 7일 단계 (교차검증용)."""
    r = session.post(
        f"{BASE}/algaeMap/beforBlalMapDataCall",
        data={"ATTR_1S": json.dumps(TARGET_CODES)},
        headers=HEADERS,
        timeout=TIMEOUT,
        verify=False,
    )
    r.raise_for_status()
    return r.json()


def fetch_grid(session: requests.Session, today: date) -> dict:
    """B. 전 지점 최근 3회 발표 + 최근 관측치 (주 자료)."""
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


def normalize(grid: dict, sites: dict, collected_at: datetime) -> list[dict[str, str]]:
    """그리드(B) 행을 (발표일 × 지점 × +1~+7) 긴 형식으로 편다. A 와 최신 발표 단계가 다르면 stderr 경고."""
    stamp = collected_at.strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict[str, str]] = []
    seen_issues: set[tuple] = set()
    latest_a = {_key(r.get("SWMN_NM"), r.get("SWMN_DTL_NM")): r for r in (sites.get("list") or [])}
    for r in grid.get("list") or []:
        issued = _ymd(r.get("YMD_1"))
        if issued is None:
            continue
        key = _key(r.get("SPOT_1"), r.get("SPOT_2"))
        code, sid = SITE_CODES.get(key, ("", ""))
        for k in range(1, 8):
            label = (r.get(f"SUMMARY_D{k + 1}") or "").strip()
            rows.append(
                {
                    "collected_at_kst": stamp,
                    "issued_date": issued.isoformat(),
                    "site_code": code,
                    "station_id": sid,
                    "water_body": key[0],
                    "site_name": DISPLAY.get(key[1], key[1]),
                    "horizon_day": str(k),
                    "forecast_date": (issued + timedelta(days=k)).isoformat(),
                    "forecast_level": _level(label),
                    "forecast_level_label": label,
                    "forecast_cells": "",
                    "obs_cells_latest": _num(r.get("OLD_D")),
                    "alert_latest": (r.get("OLD_D_AG_ISSUE") or "").strip(),
                    "source": "mulmoa.go.kr/web algaeBeforInfo/mesureDataCall",
                }
            )
        seen_issues.add((key, issued))
        a = latest_a.get(key)
        if a and _ymd(a.get("PRSNTN_NOW_YMD")) == issued:
            mism = []
            for k in range(2, 9):
                la, lb = (a.get(f"SUMMARY_D{k}") or "").strip(), (r.get(f"SUMMARY_D{k}") or "").strip()
                if _level(lb) == "" and _level(la) != "":  # B 가 비었고 A 에 값이 있으면 A 로 채움
                    row = rows[-8 + (k - 1)]
                    row["forecast_level"], row["forecast_level_label"] = _level(la), la
                    row["source"] = "mulmoa.go.kr/web algaeMap/beforBlalMapDataCall (B 공란 보완)"
                elif la != lb:
                    mism.append(k)
            if mism:
                print(f"[warn] {key} {issued}: A/B 단계 불일치 D{mism} (B 값 유지)", file=sys.stderr)
    # A 에만 있는 발표(대상 지점, B 에 해당 발표일 행이 없을 때)
    for key, a in latest_a.items():
        issued = _ymd(a.get("PRSNTN_NOW_YMD"))
        if issued is None or (key, issued) in seen_issues:
            continue
        code, sid = SITE_CODES.get(key, ("", ""))
        for k in range(1, 8):
            label = (a.get(f"SUMMARY_D{k + 1}") or "").strip()
            rows.append(
                {
                    "collected_at_kst": stamp,
                    "issued_date": issued.isoformat(),
                    "site_code": code,
                    "station_id": sid,
                    "water_body": key[0],
                    "site_name": DISPLAY.get(key[1], key[1]),
                    "horizon_day": str(k),
                    "forecast_date": (issued + timedelta(days=k)).isoformat(),
                    "forecast_level": _level(label),
                    "forecast_level_label": label,
                    "forecast_cells": "",
                    "obs_cells_latest": "",
                    "alert_latest": "",
                    "source": "mulmoa.go.kr/web algaeMap/beforBlalMapDataCall",
                }
            )
    # 정렬: 발표일 → 대상 5지점 먼저 → 수계·지점 → 예측일
    rows.sort(
        key=lambda x: (
            x["issued_date"],
            x["station_id"] == "",
            x["water_body"],
            x["site_name"],
            int(x["horizon_day"]),
        )
    )
    return rows


def _content_key(rows: list[dict[str, str]]) -> list[tuple]:
    return [tuple(v for k, v in sorted(r.items()) if k not in DEDUPE_IGNORE) for r in rows]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=RAW_DIR / "mulmoa")
    ap.add_argument("--no-dedupe", action="store_true", help="같은 날 동일 내용이어도 파일을 쓴다")
    args = ap.parse_args(argv)
    out: Path = args.out
    (out / "raw").mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 사이트 인증서 체인 검증 불가
    with requests.Session() as s:
        s.get("https://www.mulmoa.go.kr/web", headers=HEADERS, timeout=TIMEOUT, verify=False)  # 세션 쿠키
        sites = fetch_sites(s)
        grid = fetch_grid(s, now.date())
    stamp = now.strftime("%Y-%m-%d_%H%M")
    for name, payload in (("sites", sites), ("grid", grid)):
        (out / "raw" / f"{stamp}_{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    rows = normalize(grid, sites, now)
    if not rows:
        print("예측정보 제공기간이 아니거나 응답이 비었음 — 파일 미생성")
        return 0
    if not args.no_dedupe:
        same_day = sorted(out.glob(f"{now.date().isoformat()}_*.csv"))
        if same_day and _content_key(_read_csv(same_day[-1])) == _content_key(rows):
            print(f"동일 내용 ({same_day[-1].name}) — 생략")
            return 0
    path = out / f"{stamp}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    issued = sorted({r["issued_date"] for r in rows})
    n_sites = len({(r["water_body"], r["site_name"]) for r in rows})
    print(f"{path.name}: {len(rows)} rows, 지점 {n_sites}, 발표일 {issued}")
    for r in rows:
        if r["station_id"] and r["issued_date"] == issued[-1] and r["horizon_day"] == "1":
            obs = (
                f"{r['obs_cells_latest']} cells/mL ({r['alert_latest']})"
                if r["obs_cells_latest"]
                else "관측 없음"
            )
            print(f"  {r['station_id']} {r['site_name']}: 최근 {obs}, +1일 {r['forecast_level_label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
