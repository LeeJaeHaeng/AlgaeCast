"""WQ-02 보강 — 국립환경과학원 수질 DB '물환경 수질측정망 운영결과 DB' API 수집기 (R4 / EXP-007).

- 엔드포인트 ``{API_NIER_WQDB}/getWaterMeasuringList`` (data.go.kr ``/1480523/WaterQualityService``,
  JSON). 인자 ``ptNoList``(측정소 코드, 콤마 다중)·``wmyrList``(연)·``wmodList``(월, 생략 시 전체)·
  ``pageNo``·``numOfRows``·``resultType=json``. 키는 ``.env`` 의 ``NIER_WQDB_KEY``(Decoding).
- 응답 항목은 앞뒤 공백이 붙은 문자열 → 수치 변환. '정량한계미만' 은 NaN + ``<항목>_below_loq``.
- 측정소 경위도는 도·분·초(LAT_DGR/MIN/SEC, LON_*) → 십진 도(``lat``·``lon``).
- 호소 측정소(대청호 등)는 같은 날 여러 수심(``WMDEP``)을 측정한다. 원자료는 모두 저장하고
  ``surface_layer()`` 가 (측정소, 측정일)마다 가장 얕은 수심(수심 없음=표층) 1행만 남긴다.
- 출력 규약(02 문서 9절): pt_no, obs_date(date), 변수..., source, fetched_at.

사용: python -m algaecast.collect.nier_wq_measuring [--start-year 2012] [--end-year 올해] [--no-cache]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date, datetime, timedelta

import pandas as pd

from algaecast.collect.base import KST, BaseCollector, CollectError, closed_year_ttl
from algaecast.config import RAW_DIR, get_env

log = logging.getLogger(__name__)

URL_DEFAULT = "https://apis.data.go.kr/1480523/WaterQualityService"
OPERATION = "getWaterMeasuringList"
PAGE_SIZE = 5_000
OUT_NAME = "wq_measuring_2012_2026"
OUT_DIR = RAW_DIR / "nier_wqdb"

# 5지점별 후보 측정소(본류만, 상·하류 관계 표시). primary 가 피처에 쓰는 측정소(EXP-007 sites_snippet.yaml).
CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "HP": [("2011A10", "primary"), ("2009A30", "upstream"), ("2011A20", "downstream")],
    "GJGR": [("2011A55", "primary"), ("2011A60", "same_reach"), ("2011A40", "upstream")],
    "CS": [("2020A10", "primary"), ("2020A32", "downstream")],
    "MGMR": [("2022A10", "primary"), ("2020A60", "upstream")],
    "DCHN": [("3008B30", "primary"), ("3008B20", "downstream"), ("3008B10", "upstream")],
}
STATIONS: list[str] = [pt for cands in CANDIDATES.values() for pt, _ in cands]

ITEMS: dict[str, str] = {  # API 태그 → 컬럼 (단위: mg/L, Chl-a mg/m³, EC μS/cm, 수온 ℃, 유량 m³/s)
    "ITEM_TN": "tn",
    "ITEM_TP": "tp",
    "ITEM_NO3N": "no3n",
    "ITEM_NH3N": "nh3n",
    "ITEM_POP": "po4p",
    "ITEM_DTN": "tdn",
    "ITEM_DTP": "tdp",
    "ITEM_CLOA": "chla",
    "ITEM_DOC": "do",  # 용존산소(DO). DOC(용존유기탄소) 아님 — 값이 포화 DO 수준이고 TOC 보다 큼
    "ITEM_EC": "ec",
    "ITEM_SS": "ss",
    "ITEM_TEMP": "wtemp",
    "ITEM_PH": "ph",
    "ITEM_BOD": "bod",
    "ITEM_COD": "cod",
    "ITEM_TOC": "toc",
    "ITEM_AMNT": "flow",
}
META: dict[str, str] = {
    "PT_NO": "pt_no",
    "PT_NM": "pt_nm",
    "ADDR": "addr",
    "ORG_NM": "org_nm",
    "WMYR": "wmyr",
    "WMOD": "wmod",
    "WMWK": "wmwk",
    "WMCYMD": "obs_date",
    "WMDEP": "depth_m",
}
LOQ_TOKEN = "정량한계미만"


def dms_to_deg(d: object, m: object, s: object) -> float:
    """도·분·초 → 십진 도. 하나라도 비면 NaN."""
    try:
        return float(d) + float(m) / 60.0 + float(s) / 3600.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan


def parse_json(text: str) -> tuple[list[dict], int]:
    """응답 JSON → (item 목록, totalCount). JSON 아님·code≠00 → CollectError."""
    try:
        root = json.loads(text)[OPERATION]
    except (ValueError, KeyError, TypeError) as exc:
        raise CollectError(f"수질 DB 응답이 예상 JSON 이 아님: {text.lstrip()[:120]!r}") from exc
    head = root.get("header") or {}
    code = str(head.get("code", ""))
    if code not in ("00", "0"):
        raise CollectError(f"수질 DB resultCode={code} {head.get('message')}")
    items = root.get("item") or []
    if isinstance(items, dict):  # 1건이면 dict 로 오는 경우 대비
        items = [items]
    return list(items), int(root.get("totalCount") or len(items))


def to_number(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """문자열 수치 → (float, below_loq 플래그). 알 수 없는 비수치 토큰은 NaN 으로 두고 경고."""
    txt = s.astype("string").str.strip().fillna("")
    below = txt.eq(LOQ_TOKEN)
    val = pd.to_numeric(txt.str.replace(",", "", regex=False).where(txt != "", None), errors="coerce")
    bad = txt[(txt != "") & val.isna() & ~below]
    if len(bad):
        log.warning("%s: 비수치 값 %s → NaN", s.name, bad.value_counts().head(5).to_dict())
    return val.astype("float64"), below.astype(bool)


def tidy(items: list[dict], fetched_at: pd.Timestamp) -> pd.DataFrame:
    """API item 목록 → 표준 컬럼(수치형·경위도·플래그). 같은 (측정소, 측정일, 수심) 중복은 마지막 값."""
    raw = pd.DataFrame(items)
    if raw.empty:
        return raw
    df = pd.DataFrame({dst: raw.get(src, pd.Series(None, index=raw.index)) for src, dst in META.items()})
    df["pt_no"] = df["pt_no"].astype(str).str.strip()
    dt = pd.to_datetime(df["obs_date"].astype(str).str.strip(), format="%Y.%m.%d", errors="coerce")
    if dt.isna().any():  # 측정일(WMCYMD) 없는 행은 시점을 알 수 없어 버린다(as_of 규칙 적용 불가)
        log.warning(
            "측정일 없는 행 %d개 제외: %s", int(dt.isna().sum()), df.loc[dt.isna(), "pt_no"].tolist()[:5]
        )
    df, raw = df[dt.notna()].copy(), raw[dt.notna()]
    df["obs_date"] = dt[dt.notna()].dt.date
    df["depth_m"] = pd.to_numeric(df["depth_m"], errors="coerce").astype("float64")
    for axis in ("LAT", "LON"):
        dms = [raw.get(f"{axis}_{u}", pd.Series(None, index=raw.index)) for u in ("DGR", "MIN", "SEC")]
        df[axis.lower()] = [dms_to_deg(a, b, c) for a, b, c in zip(*dms, strict=True)]
    for src, dst in ITEMS.items():
        col = raw.get(src, pd.Series(None, index=raw.index, dtype="object")).rename(dst)
        df[dst], df[f"{dst}_below_loq"] = to_number(col)
    df = df.sort_values(["pt_no", "obs_date", "depth_m"], na_position="first")
    df = df.drop_duplicates(["pt_no", "obs_date", "depth_m"], keep="last")
    df["source"] = "nier_wqdb_api"
    df["fetched_at"] = pd.Series(fetched_at, index=df.index).astype("datetime64[ns, Asia/Seoul]")
    return df.reset_index(drop=True)


def surface_layer(df: pd.DataFrame) -> pd.DataFrame:
    """(측정소, 측정일)마다 가장 얕은 수심 1행(수심 없음 = 표층 0 m로 간주)."""
    d = df.assign(_dep=df["depth_m"].fillna(0.0))
    d = d.sort_values(["pt_no", "obs_date", "_dep"]).drop_duplicates(["pt_no", "obs_date"], keep="first")
    return d.drop(columns="_dep").reset_index(drop=True)


def station_table(df: pd.DataFrame) -> pd.DataFrame:
    """측정소별 이름·주소·경위도(최근 응답 기준)·측정 기간·건수."""
    d = df.sort_values("obs_date")
    g = d.groupby("pt_no")
    out = g.agg(
        pt_nm=("pt_nm", "last"),
        addr=("addr", "last"),
        org_nm=("org_nm", "last"),
        lat=("lat", "last"),
        lon=("lon", "last"),
        first_obs=("obs_date", "min"),
        last_obs=("obs_date", "max"),
        n_rows=("obs_date", "size"),
        n_dates=("obs_date", "nunique"),
    )
    return out.reset_index()


class NierWqMeasuringCollector(BaseCollector):
    """수질측정망 운영결과(getWaterMeasuringList) — 연 단위·측정소 묶음 조회."""

    source = "nier_wqdb"
    key_env = "NIER_WQDB_KEY"
    timeout = 120

    @property
    def url(self) -> str:
        base = get_env("API_NIER_WQDB", URL_DEFAULT) or URL_DEFAULT
        return base.rstrip("/") + "/" + OPERATION

    def is_cacheable(self, text: str) -> bool:
        """code 00 인 정상 JSON 만 캐시(오류 본문이 영구 캐시되는 것을 막는다)."""
        try:
            parse_json(text)
        except CollectError:
            return False
        return True

    def year(self, stations: list[str], year: int, ttl: timedelta | None) -> tuple[list[dict], pd.Timestamp]:
        items: list[dict] = []
        page, fetched = 1, None
        while True:
            res = self.get(
                self.url,
                {
                    "serviceKey": self.service_key(),
                    "pageNo": str(page),
                    "numOfRows": str(PAGE_SIZE),
                    "resultType": "json",
                    "ptNoList": ",".join(stations),
                    "wmyrList": str(year),
                },
                ttl=ttl,
            )
            fetched = fetched or pd.Timestamp(res.fetched_at)
            got, total = parse_json(res.text)
            items.extend(got)
            if len(items) >= total or not got:
                break
            page += 1
        return items, fetched or pd.Timestamp(datetime.now(KST))

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        """``site_code`` = 측정소 코드(콤마 다중 허용). start~end 연도 전체를 받아 날짜로 자른다."""
        stations = [s.strip() for s in site_code.split(",") if s.strip()]
        frames = []
        for y in range(start.year, end.year + 1):
            items, fetched = self.year(stations, y, closed_year_ttl(y))
            if items:
                frames.append(tidy(items, fetched))
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        keep = (df["obs_date"] >= start) & (df["obs_date"] <= end)
        return df[keep].reset_index(drop=True)


def collect(start_year: int = 2012, end_year: int | None = None, *, use_cache: bool = True) -> dict:
    """후보 측정소 전체를 수집해 ``data/raw/nier_wqdb/`` 에 저장. 요약(dict) 반환."""
    end_year = end_year or datetime.now(KST).year
    c = NierWqMeasuringCollector(use_cache=use_cache, out_dir=OUT_DIR)
    end = min(date(end_year, 12, 31), datetime.now(KST).date())
    df = c.fetch(",".join(STATIONS), date(start_year, 1, 1), end)
    if df.empty:
        raise CollectError("수질측정망 API 수집 결과 0행")
    pq, _ = c.save(df, OUT_NAME)
    st = station_table(df)
    st.to_csv(OUT_DIR / "wq_measuring_stations.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    period = f"{df['obs_date'].min()}~{df['obs_date'].max()}"
    row = c.manifest_row(
        id_="WQ-02b",
        name=(
            "물환경 수질측정망 운영결과 DB — 5지점 후보 측정소 13개(본류), TN·TP·NO3-N·NH3-N·PO4-P·DTN·DTP·"
            f"Chl-a·DO·EC·SS 등 17항목 (`data/raw/nier_wqdb/{OUT_NAME}.parquet/.csv`)"
        ),
        org="기후에너지환경부 국립환경과학원",
        endpoint=(
            "apis.data.go.kr/1480523/WaterQualityService/getWaterMeasuringList "
            f"(ptNoList=13개소, wmyrList 연 단위, numOfRows={PAGE_SIZE}, resultType=json, "
            f"{end_year - start_year + 1}요청)"
        ),
        period=period,
        rows=len(df),
        license_="이용허락범위 제한 없음(data.go.kr 활용신청 표기)",
        path=pq,
    )
    return {
        "path": str(pq),
        "rows": len(df),
        "period": period,
        "requests": c.n_requests,
        "cache_hits": c.n_cache_hits,
        "manifest_row": row,
        "sha256": c.sha256_prefix(pq, 64),
        "below_loq": {
            k: int(df[f"{k}_below_loq"].sum()) for k in ITEMS.values() if df[f"{k}_below_loq"].any()
        },
        "stations": st,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start-year", type=int, default=2012)
    ap.add_argument("--end-year", type=int, default=None)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = collect(a.start_year, a.end_year, use_cache=not a.no_cache)
    print(f"{res['rows']:,}행 {res['period']} 요청 {res['requests']} 캐시 {res['cache_hits']}")
    print(res["stations"].to_string(index=False))
    print("정량한계미만:", res["below_loq"])
    print(res["manifest_row"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
