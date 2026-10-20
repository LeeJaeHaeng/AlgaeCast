"""사후 검증 라이브 테이블: 물모아 AI 녹조 예측(단계) vs 조류경보제 실측을 매일 매칭해 누적한다.

출력 reports/eval/live_benchmark.csv
  컬럼: site_code, issued_date, target_date, mulmoa_level, obs_cells, obs_level, hit
- 한 행 = (지점, 발표일, 예측 대상일) 조합 중 **발표 단계가 있고 대상일에 실측이 있는 것**
  (대상일 − 발표일 = 1~7일). 그리드에서 '-' 로 비워진 과거 발표는 비교 불가라 제외.
- mulmoa_level: 발표 단계(0~4). obs_level: 실측 세포수를 같은 범례(1천/1만/10만/100만)로 변환.
- hit: mulmoa_level == obs_level (단계 정확도). ≥2단계 이진 지표·혼동행렬은 T5 eval/report 가 계산.
- 실측 출처: data.go.kr 조류경보제 API(WQ-01, DATA_GO_KR_KEY). 키가 없거나 실패하면 물모아 웹 JSON 으로 폴백.
- 멱등: 기존 CSV 와 (site_code, issued_date, target_date) 키로 합치고, 새 관측·수정된 발표는 갱신한다.
- T5 이후 우리 모델의 pred_level·p_over_10k 컬럼을 같은 키로 붙인다 (이 스크립트는 건드리지 않음).

사용: python scripts/update_live_benchmark.py [--out reports/eval/live_benchmark.csv] [--snapshots DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import urllib3

from algaecast.collect import nier_forecast as nf
from algaecast.config import ROOT, get_env

OUT_DEFAULT = ROOT / "reports" / "eval" / "live_benchmark.csv"
COLUMNS = ["site_code", "issued_date", "target_date", "mulmoa_level", "obs_cells", "obs_level", "hit"]
SITES = ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"]
NIER_URL = "https://apis.data.go.kr/1480523/nieragainstalgae/algaePreMeasure"
MULMOA_URL = "https://www.mulmoa.go.kr/web/totalSearch/water/algaePreMeasure/mesureDataCall"
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
TIMEOUT = 60


def _months(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch_obs_datagokr(start: date, end: date, key: str) -> pd.DataFrame:
    """조류경보제 API(WQ-01): 연·월 다중 조회. 반환 site_code, obs_date, obs_cells."""
    rows = []
    for year in sorted({y for y, _ in _months(start, end)}):
        months = ",".join(f"{m:02d}" for y, m in _months(start, end) if y == year)
        page = 1
        while True:
            r = requests.get(
                NIER_URL,
                params={
                    "serviceKey": key,
                    "pageNo": str(page),
                    "numOfRows": "1000",
                    "resultType": "xml",
                    "ptNoList": "",
                    "wmyrList": str(year),
                    "wmodList": months,
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            root = ET.fromstring(r.content)
            code = root.findtext(".//resultCode")
            if code not in (None, "00", "0"):
                raise RuntimeError(f"조류경보제 API 오류 {code}: {root.findtext('.//resultMsg')}")
            items = root.findall(".//item")
            for it in items:
                if (it.findtext("swmnCode") or "") in SITES:
                    rows.append(
                        {
                            "site_code": it.findtext("swmnCode"),
                            "obs_date": (it.findtext("chckDe") or "").replace(".", "-"),
                            "obs_cells": it.findtext("iemBgalageCellCo"),
                        }
                    )
            if len(items) < 1000:
                break
            page += 1
    return _tidy_obs(pd.DataFrame(rows, columns=["site_code", "obs_date", "obs_cells"]))


def fetch_obs_mulmoa(start: date, end: date) -> pd.DataFrame:
    """폴백: 물모아 웹 JSON(조류측정자료 data_code 57, 상수원 169, 월 범위). IEM_1166 = 유해남조류 세포수."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    with requests.Session() as s:
        s.get("https://www.mulmoa.go.kr/web", headers=HEADERS, timeout=TIMEOUT, verify=False)
        r = s.post(
            MULMOA_URL,
            data={
                "data_code": "57",
                "tbmn_sn": "17",
                "pDataGubun": "169",
                "pLgubun": "02",
                "pDateGun": "1",
                "pSDay": start.strftime("%Y%m"),
                "pEDay": end.strftime("%Y%m"),
                "excel": "N",
                "ATTR_1S": json.dumps(["2", "3"]),
                "STATION_CODES": json.dumps(SITES),
            },
            headers=HEADERS,
            timeout=TIMEOUT,
            verify=False,
        )
    r.raise_for_status()
    rows = [
        {"site_code": x.get("SWMN_CD"), "obs_date": x.get("INSP_YMD"), "obs_cells": x.get("IEM_1166")}
        for x in r.json().get("list") or []
        if x.get("SWMN_CD") in SITES
    ]
    return _tidy_obs(pd.DataFrame(rows, columns=["site_code", "obs_date", "obs_cells"]))


def _tidy_obs(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df["obs_date"] = pd.to_datetime(df["obs_date"], errors="coerce").dt.date
    df["obs_cells"] = pd.to_numeric(df["obs_cells"].astype(str).str.replace(",", ""), errors="coerce")
    df = df.dropna(subset=["obs_date", "obs_cells"]).drop_duplicates(["site_code", "obs_date"], keep="last")
    return df.reset_index(drop=True)


def build_table(snapshots: pd.DataFrame, obs: pd.DataFrame) -> pd.DataFrame:
    """대상 5지점 발표 행과 실측을 (site_code, target_date == obs_date) 로 정확 매칭한다."""
    cols = ["site_code", "issued_date", "forecast_date", "forecast_level"]
    fc = snapshots.loc[snapshots["site_code"].isin(SITES), cols]
    fc = fc.rename(columns={"forecast_date": "target_date", "forecast_level": "mulmoa_level"})
    fc = fc.dropna(subset=["mulmoa_level"])  # 그리드에서 '-' 로 비워진 과거 발표는 비교 불가
    merged = fc.merge(
        obs, left_on=["site_code", "target_date"], right_on=["site_code", "obs_date"], how="inner"
    )
    merged["obs_level"] = nf.level_from_cells(merged["obs_cells"])
    merged["hit"] = (merged["mulmoa_level"] == merged["obs_level"]).astype("Int64")
    merged.loc[merged["mulmoa_level"].isna() | merged["obs_level"].isna(), "hit"] = pd.NA
    merged["obs_cells"] = merged["obs_cells"].round().astype("Int64")
    return merged[COLUMNS].sort_values(["site_code", "issued_date", "target_date"]).reset_index(drop=True)


def merge_existing(new: pd.DataFrame, path: Path) -> pd.DataFrame:
    if not path.exists():
        return new
    old = pd.read_csv(path, dtype={"site_code": str})
    for c in ("issued_date", "target_date"):
        old[c] = pd.to_datetime(old[c]).dt.date
    for c in ("mulmoa_level", "obs_cells", "obs_level", "hit"):
        old[c] = pd.to_numeric(old[c], errors="coerce").astype("Int64")
    key = ["site_code", "issued_date", "target_date"]
    combined = pd.concat([old[COLUMNS], new[COLUMNS]], ignore_index=True)
    return combined.drop_duplicates(key, keep="last").sort_values(key).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--snapshots", type=Path, default=nf.MULMOA_DIR)
    args = ap.parse_args(argv)
    snaps = nf.load_snapshots(args.snapshots)
    snaps = snaps.loc[snaps["site_code"].isin(SITES) & snaps["forecast_level"].notna()]
    if snaps.empty:
        print("물모아 스냅샷에 단계가 있는 대상 지점 발표가 없음 — 종료")
        return 0
    start, end = min(snaps["issued_date"]), max(snaps["forecast_date"])
    key = os.environ.get("DATA_GO_KR_KEY") or get_env("DATA_GO_KR_KEY")
    try:
        if not key:
            raise RuntimeError("DATA_GO_KR_KEY 없음")
        obs = fetch_obs_datagokr(start, end, key)
        src = "data.go.kr 조류경보제 API"
    except Exception as exc:  # noqa: BLE001 - 폴백 후 계속
        print(f"[warn] 조류경보제 API 실패({type(exc).__name__}) → 물모아 웹 폴백", file=sys.stderr)
        obs = fetch_obs_mulmoa(start, end)
        src = "물모아 웹 JSON"
    new = build_table(snaps, obs)
    table = merge_existing(new, args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False, encoding="utf-8", lineterminator="\n")
    scored = table.dropna(subset=["hit"])
    acc = f"{scored['hit'].mean():.3f}" if len(scored) else "n/a"
    print(
        f"{args.out.relative_to(ROOT)}: {len(table)} rows (+{len(new)} matched now, "
        f"실측 {len(obs)}건 from {src}), 단계 정확도 {acc} (n={len(scored)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
