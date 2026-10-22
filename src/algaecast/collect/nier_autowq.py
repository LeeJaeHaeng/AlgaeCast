"""WQ-06 수질자동측정망 운영결과 DB 수집기 (국립환경과학원 수질 DB, data.go.kr #15081073) — EXP-009(R6).

엔드포인트 ``{API_NIER_WQDB}/getRealTimeWaterQualityList`` (키 ``NIER_WQDB_KEY``, Decoding).
2026-10-21 인자 탐색 결과(공식 요청변수 표 = data.go.kr 상세기능 31760):
- ``siteId``(측정소 코드, 콤마 다중), ``startDate``·``endDate``(yyyyMMddHHmmss 14자리, **둘 다** 있어야 함),
  ``numOfRows``·``pageNo``·``resultType=JSON``. siteId 를 빼면 전 측정소가 섞여 나온다.
- 기간 경계는 (startDate, endDate] — MSR_DATE 자정 시각 기준으로 시작은 제외·끝은 포함.
  연도 Y 전체는 startDate=(Y−1)1231000000, endDate=Y1231000000.
- 응답 ``{"getRealTimeWaterQualityList": {"header": {"code": "00"}, "item": [...], "totalCount": N}}``,
  item 은 측정소·일(MSR_DATE, YYYY-MM-DD)당 1행의 **일평균**(M01~M100).
  2026-10-21 기준 최신 2026-08-31(월 단위 확정 공개).
- 항목 코드 의미는 포털 출력결과 표(구버전, m69=납 등)와 다르다. 실제 값과 맞는 것은 활용가이드 zip 의
  '물환경 수질자동측정망(실시간) 운영결과 DB_물 환경_코드_코드명.xlsx'(ITEM_CODES).
  수치코드 −999 = 정량한계 미만.
- 측정소마다 센서 묶음(1·2·3)이 달라 같은 항목이 M02/M38/M69(수온) 등으로 나뉜다
  → UNIFIED 로 합친다(3 → 2 → 1 순).

측정소 위치: 물환경정보시스템 GIS(ArcGIS REST, 층 B001 '수질자동측정망', WGS84; 키 불필요),
주소·측정항목: 물환경정보시스템 측정소 목록(``/web/autoMeasure/confirm/toastList``, 키 불필요).

출력(02 문서 9절 규약 확장): site_id, site_name, obs_date(date), M 원값..., 통합 변수(UNIFIED),
source, fetched_at.
저장: ``data/raw/nier_autowq/autowq_daily.parquet``(+csv), ``stations.csv``.

사용: python -m algaecast.collect.nier_autowq [--sites S02012,S02009] [--start-year 2012] [--end-year 2026]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from algaecast.collect.base import KST, BaseCollector, CollectError, closed_year_ttl
from algaecast.config import get_env

log = logging.getLogger(__name__)

URL_DEFAULT = "https://apis.data.go.kr/1480523/WaterQualityService"
OPERATION = "getRealTimeWaterQualityList"
GIS_URL = "http://211.114.21.35:8080/arcgis/rest/services/reach_V3/MapServer/96/query"
STATION_LIST_URL = "https://water.nier.go.kr/web/autoMeasure/confirm/toastList"
PAGE_SIZE = 500
BELOW_LOQ = -999.0

# 활용가이드(2022-10-07) 코드표 — 실제 응답 값 범위와 일치 확인(2026-10-21)
ITEM_CODES: dict[str, str] = {
    "M01": "통신상태", "M02": "수온1", "M03": "수소이온농도1", "M04": "전기전도도1", "M05": "용존산소1",
    "M06": "총유기탄소1", "M12": "염화메틸렌", "M13": "1.1.1-트리클로로에테인", "M14": "벤젠",
    "M15": "사염화탄소", "M16": "트리클로로에틸렌", "M17": "톨루엔", "M18": "테트라클로로에틸렌",
    "M19": "에틸벤젠", "M20": "m,p-자일렌", "M21": "o-자일렌", "M22": "[ECD]염화메틸렌",
    "M23": "[ECD]1.1.1-트리클로로에테인", "M24": "[ECD]사염화탄소", "M25": "[ECD]트리클로로에틸렌",
    "M26": "[ECD]테트라클로로에틸렌", "M27": "총질소", "M28": "총인", "M29": "클로로필-a", "M35": "인산염인",
    "M36": "암모니아성질소", "M37": "질산성질소", "M38": "수온2", "M39": "수소이온농도2",
    "M40": "전기전도도2", "M41": "용존산소2", "M69": "수온3", "M70": "수소이온농도3", "M71": "전기전도도3",
    "M72": "용존산소3", "M73": "탁도3", "M74": "카드뮴", "M75": "납", "M76": "구리", "M77": "아연",
    "M78": "페놀", "M79": "탁도1", "M80": "탁도2", "M81": "총유기탄소", "M100": "페놀2",
}  # fmt: skip
# 통합 변수 ← M 코드(앞이 우선). 센서 묶음 3 → 2 → 1.
UNIFIED: dict[str, tuple[str, ...]] = {
    "wtemp": ("M69", "M38", "M02"),
    "ph": ("M70", "M39", "M03"),
    "ec": ("M71", "M40", "M04"),
    "do": ("M72", "M41", "M05"),
    "toc": ("M06", "M81"),
    "turb": ("M73", "M80", "M79"),
    "tn": ("M27",),
    "tp": ("M28",),
    "chla": ("M29",),
    "po4p": ("M35",),
    "nh3n": ("M36",),
    "no3n": ("M37",),
}
# 정량한계 미만(−999)을 0 으로 볼 농도 항목(나머지는 NaN)
LOQ_ZERO = ("toc", "turb", "tn", "tp", "chla", "po4p", "nh3n", "no3n")
# 물리적으로 가능한 일평균 범위(밖이면 센서 이상으로 보고 NaN)
VALID_RANGE: dict[str, tuple[float, float]] = {
    "wtemp": (-1.0, 40.0),
    "ph": (4.0, 11.0),
    "ec": (5.0, 5000.0),
    "do": (0.1, 25.0),
    "toc": (0.0, 50.0),
    "turb": (0.0, 3000.0),
    "tn": (0.0, 30.0),
    "tp": (0.0, 3.0),
    "chla": (0.0, 1500.0),
    "po4p": (0.0, 3.0),
    "nh3n": (0.0, 20.0),
    "no3n": (0.0, 30.0),
}
# 대상 5지점 ↔ 최근접 본류 자동측정소(EXP-009 보고서 1절 표, GIS 좌표 기준 거리)와 차순위 본류 측정소
PRIMARY: dict[str, str] = {
    "HP": "S02012",
    "GJGR": "S02009",
    "CS": "S02007",
    "MGMR": "S02017",
    "DCHN": "S03003",
}
SECONDARY: dict[str, str] = {
    "HP": "S02021",
    "GJGR": "S02003",
    "CS": "S02006",
    "MGMR": "S02008",
    "DCHN": "S03007",
}
EXTRA: tuple[str, ...] = ("S02030", "S02024", "S02056", "S02004", "S03009")  # 지류·하류(가용성 표용)


def parse_items(text: str) -> tuple[list[dict], int]:
    """응답 JSON → (item 목록, totalCount). JSON 아님·header.code≠00 → CollectError."""
    try:
        d = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CollectError(f"자동측정망 API 응답이 JSON 이 아님: {text.lstrip()[:120]!r}") from exc
    root = d.get(OPERATION)
    if not isinstance(root, dict):
        raise CollectError(f"자동측정망 API 응답 루트 없음: {list(d)[:5]}")
    code = str((root.get("header") or {}).get("code", ""))
    if code not in ("00", "0"):
        raise CollectError(f"자동측정망 API code={code} {(root.get('header') or {}).get('message')}")
    items = root.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return list(items), int(root.get("totalCount") or len(items))


def unify(raw: pd.DataFrame) -> pd.DataFrame:
    """M 원값 → 통합 변수(센서 묶음 우선순위 병합, −999 처리, 범위 밖 NaN). 원 열은 그대로 둔다."""
    out = raw.copy()
    for var, codes in UNIFIED.items():
        v = pd.Series(np.nan, index=out.index, dtype=float)
        for c in codes:
            if c in out.columns:
                v = v.fillna(pd.to_numeric(out[c], errors="coerce").astype(float))
        loq = v == BELOW_LOQ
        v = v.mask(loq, 0.0 if var in LOQ_ZERO else np.nan)
        lo, hi = VALID_RANGE[var]
        v = v.where((v >= lo) & (v <= hi))
        out[var] = v
        out[f"{var}_loq"] = loq
    return out


def items_to_frame(items: list[dict]) -> pd.DataFrame:
    """item 목록 → 측정소·일 1행 DataFrame(M 원값 float + 통합 변수)."""
    if not items:
        cols = ["site_id", "site_name", "obs_date", *ITEM_CODES, *UNIFIED]
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(items)
    df = df.rename(columns={"SITE_ID": "site_id", "SITE_NAME": "site_name", "MSR_DATE": "obs_date"})
    df["obs_date"] = pd.to_datetime(df["obs_date"].astype(str).str[:10]).dt.date
    for c in ITEM_CODES:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float) if c in df.columns else np.nan
    df = df[["site_id", "site_name", "obs_date", *ITEM_CODES]]
    return unify(df)


class NierAutoWQCollector(BaseCollector):
    """수질자동측정망 일평균 수집기(측정소·연도 단위 요청, 마감 연도는 캐시 영구)."""

    source = "nier_autowq"
    key_env = "NIER_WQDB_KEY"

    @property
    def url(self) -> str:
        return (get_env("API_NIER_WQDB") or URL_DEFAULT).rstrip("/") + "/" + OPERATION

    def is_cacheable(self, text: str) -> bool:
        """자료 API 는 header.code=00, 측정소 목록은 'list', GIS 는 'features' 가 있어야 캐시."""
        try:
            d = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(d, dict):
            return False
        if OPERATION in d:
            try:
                parse_items(text)
            except CollectError:
                return False
            return True
        return isinstance(d.get("list"), list) or isinstance(d.get("features"), list)

    def fetch_year(self, site_id: str, year: int) -> list[dict]:
        """한 측정소의 한 해(1/1~12/31) 일평균 item 전부(페이지 반복)."""
        out: list[dict] = []
        page = 1
        while True:
            params = {
                "serviceKey": self.service_key(),
                "pageNo": page,
                "numOfRows": PAGE_SIZE,
                "resultType": "JSON",
                "siteId": site_id,
                "startDate": f"{year - 1}1231000000",
                "endDate": f"{year}1231000000",
            }
            res = self.get(self.url, params, ttl=closed_year_ttl(year))
            items, total = parse_items(res.text)
            out.extend(items)
            if len(out) >= total or not items:
                break
            page += 1
        return out

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        """site_code = 자동측정소 코드(S0xxxx). start~end 연도 전체를 받아 날짜로 자른다."""
        items: list[dict] = []
        for y in range(start.year, end.year + 1):
            items.extend(self.fetch_year(site_code, y))
        df = items_to_frame(items)
        if len(df):
            df = df[(df["obs_date"] >= start) & (df["obs_date"] <= end)]
            df = df.drop_duplicates(["site_id", "obs_date"], keep="last")
        df = df.assign(source=self.source, fetched_at=pd.Timestamp(datetime.now(KST)))
        return df.sort_values(["site_id", "obs_date"]).reset_index(drop=True)

    def fetch_stations(self) -> pd.DataFrame:
        """자동측정소 목록(코드·이름·수계·주소·측정항목·설치연도) + GIS 좌표(WGS84)."""
        hdr = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
        self.session.headers.update(hdr)
        lst = self.get(STATION_LIST_URL, {"ATTR_1": 2, "ATTR_2": "", "ATTR_3": "", "querySn": 65})
        meta = pd.DataFrame(json.loads(lst.text)["list"])
        gis = self.get(
            GIS_URL,
            {
                "where": "JIJUM_CODE LIKE 'S0%'",
                "outFields": "JIJUM_CODE,JIJUM_NM,LAYER_CODE",
                "returnGeometry": "true",
                "f": "json",
            },
        )
        feats = json.loads(gis.text)["features"]
        pts = pd.DataFrame(
            [
                {
                    "site_id": f["attributes"]["JIJUM_CODE"],
                    "lat": f["geometry"]["y"],
                    "lon": f["geometry"]["x"],
                }
                for f in feats
                if f["attributes"].get("LAYER_CODE") == "B001"
            ]
        )
        meta = meta.rename(
            columns={
                "WQAMN_CODE": "site_id",
                "WQAMN_NM": "site_name",
                "WRSSM_NM": "basin",
                "DETAIL_ADRES": "address",
                "DETAIL_ADRES_2": "location_note",
                "MESURE_IEM": "items",
                "CFR_SITTN": "surroundings",
                "INSTL_YEAR": "install_year",
            }
        )
        keep = ["site_id", "site_name", "basin", "install_year", "address", "location_note", "items"]
        meta = meta[[c for c in keep if c in meta.columns]]
        return meta.merge(pts, on="site_id", how="outer").sort_values("site_id").reset_index(drop=True)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    h = (
        math.sin((lat2 - lat1) * p / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sites", default=",".join([*PRIMARY.values(), *SECONDARY.values(), *EXTRA]))
    ap.add_argument("--start-year", type=int, default=2012)
    ap.add_argument("--end-year", type=int, default=datetime.now(KST).year)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    col = NierAutoWQCollector(use_cache=not a.no_cache)
    st = col.fetch_stations()
    col.out_dir.mkdir(parents=True, exist_ok=True)
    st.to_csv(col.out_dir / "stations.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    frames = []
    for s in a.sites.split(","):
        d = col.fetch(s.strip(), date(a.start_year, 1, 1), date(a.end_year, 12, 31))
        log.info("%s: %d일 (%s ~ %s)", s, len(d), d["obs_date"].min(), d["obs_date"].max())
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    pq, _ = col.save(df, "autowq_daily")
    log.info("저장 %s (%d행), 요청 %d·캐시 %d", pq, len(df), col.n_requests, col.n_cache_hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
