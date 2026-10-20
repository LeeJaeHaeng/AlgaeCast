"""WQ-01 조류경보제 조회서비스 수집기 (data.go.kr #15126738, XML 전용) — T1-a.

- 엔드포인트 ``/1480523/nieragainstalgae/algaePreMeasure``. 파라미터 ``ptNoList``(조사지점코드, 콤마 다중),
  ``wmyrList``(연도, 콤마), ``wmodList``(월, 콤마), ``numOfRows``(10,000 까지 확인), ``pageNo``,
  ``resultType=xml``.
- 전 항목이 String → 수치 변환. '정량한계미만' → NaN + ``*_below_loq``, '분석중' → NaN + ``*_pending``.
- 파생: ``cells_sum4``(4속 합) 와 API 총합 대조(``cells_consistent``), ``dominant_genus``(4속 중
  최대, 전부 0 이면 결측), ``alert_level_single``(단일 측정 임계: 0 해제/1 관심/2 경계/3 대발생),
  ``alert_level_2consec``(2회 연속 규칙 대리 산출).
- 출력 규약(02 문서 9절): site_code, station_id, obs_date(date), 변수..., source, fetched_at. 세포수 cells/mL.

사용: python -m algaecast.collect.nier_algae [--start 2012-01-01] [--end 오늘] [--no-cache]
"""

from __future__ import annotations

import argparse
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pandera.pandas as pa

from algaecast.collect.base import KST, BaseCollector, CollectError

log = logging.getLogger(__name__)

URL = "https://apis.data.go.kr/1480523/nieragainstalgae/algaePreMeasure"
PAGE_SIZE = 10_000
SITES: dict[str, str] = {
    "2011G26": "HP",
    "2011G56": "GJGR",
    "2020G33": "CS",
    "2022G05": "MGMR",
    "3008G30": "DCHN",
}
FIELDS: dict[str, str] = {  # API 태그 → 컬럼 (대회 번들 algae_measure.csv 와 동일 이름)
    "swmnCode": "site_code",
    "riverLkmhSe": "river_lkmh_se",
    "swmnNm": "swmn_nm",
    "swmnDetailNm": "swmn_detail_nm",
    "detailAdres": "detail_adres",
    "chckDe": "obs_date",
    "iemWtrtp": "iem_wtrtp",
    "iemPh": "iem_ph",
    "iemDoc": "iem_doc",
    "iemTrp": "iem_trp",
    "iemTur": "iem_tur",
    "iemChla": "iem_chla",
    "iemBgalageCellCo": "iem_bgalage_cell_co",
    "iemBgalageMicrosts": "iem_bgalage_microsts",
    "iemBgalageAnba": "iem_bgalage_anba",
    "iemBgalageOsrtria": "iem_bgalage_osrtria",
    "iemBgalageApzo": "iem_bgalage_apzo",
    "iemGeosm": "iem_geosm",
    "iemMib2": "iem_mib2",
    "iemMicrostlr": "iem_microstlr",
}
NUMERIC = [
    "iem_wtrtp",
    "iem_ph",
    "iem_doc",
    "iem_trp",
    "iem_tur",
    "iem_chla",
    "iem_bgalage_cell_co",
    "iem_bgalage_microsts",
    "iem_bgalage_anba",
    "iem_bgalage_osrtria",
    "iem_bgalage_apzo",
    "iem_geosm",
    "iem_mib2",
    "iem_microstlr",
]
GENUS = {
    "iem_bgalage_microsts": "Microcystis",
    "iem_bgalage_anba": "Anabaena",
    "iem_bgalage_osrtria": "Oscillatoria",
    "iem_bgalage_apzo": "Aphanizomenon",
}
TOKENS = {"정량한계미만": "below_loq", "분석중": "pending"}
LOQ_COLS = ["iem_geosm", "iem_mib2", "iem_microstlr"]  # '정량한계미만' 이 나타나는 컬럼 (대회 번들과 동일)
PENDING_COLS = ["iem_chla", *LOQ_COLS]  # '분석중' 이 나타나는 컬럼
THRESHOLDS = (1_000, 10_000, 1_000_000)  # 관심·경계·대발생 (상수원 구간, 2회 연속 기준)
ALERT_NAMES = {0: "해제", 1: "관심", 2: "경계", 3: "대발생"}

SCHEMA = pa.DataFrameSchema(
    {
        "site_code": pa.Column(str, pa.Check.isin(list(SITES))),
        "station_id": pa.Column(str, pa.Check.isin(list(SITES.values()))),
        "obs_date": pa.Column(
            object, pa.Check(lambda s: s.map(lambda v: type(v) is date).all(), error="obs_date 는 date")
        ),
        **{c: pa.Column(float, pa.Check.ge(0), nullable=True) for c in NUMERIC},
        **{f"{c}_below_loq": pa.Column(bool) for c in LOQ_COLS},
        **{f"{c}_pending": pa.Column(bool) for c in PENDING_COLS},
        "cells_sum4": pa.Column(float, pa.Check.ge(0), nullable=True),
        "cells_consistent": pa.Column("boolean", nullable=True),
        "dominant_genus": pa.Column(object, nullable=True),
        "alert_level_single": pa.Column("Int64", pa.Check.isin([0, 1, 2, 3]), nullable=True),
        "alert_level_2consec": pa.Column("Int64", pa.Check.isin([0, 1, 2, 3]), nullable=False),
        "source": pa.Column(str),
        "fetched_at": pa.Column(pd.DatetimeTZDtype(tz="Asia/Seoul")),
    },
    unique=["site_code", "obs_date"],
    coerce=False,
    strict=False,
)


def _num(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.strip().str.replace(",", "", regex=False)
    out = pd.to_numeric(cleaned.where(cleaned != "", None), errors="coerce").astype("float64")
    bad = cleaned[(cleaned != "") & out.isna() & ~cleaned.isin(TOKENS)]
    if len(bad):
        raise CollectError(f"{s.name}: 알 수 없는 비수치 값 {bad.value_counts().head(5).to_dict()}")
    return out


def parse_items(xml_text: str) -> tuple[list[dict[str, str]], int]:
    """응답 XML → (item dict 목록, totalCount). XML 아님·resultCode 없음·00 아님 → CollectError."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise CollectError(f"조류경보제 API 응답이 XML 이 아님: {xml_text.lstrip()[:120]!r}") from exc
    code = root.findtext(".//resultCode")
    if code is None:
        raise CollectError(f"조류경보제 API 응답에 resultCode 없음: {xml_text.lstrip()[:120]!r}")
    if code not in ("00", "0"):
        raise CollectError(f"조류경보제 API resultCode={code} {root.findtext('.//resultMsg')}")
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    return items, int(root.findtext(".//totalCount") or len(items))


def single_level(cells: pd.Series) -> pd.Series:
    """단일 측정 임계 단계: 0 해제(<1,000) / 1 관심 / 2 경계(≥10,000) / 3 대발생(≥1,000,000). NaN 유지."""
    c = pd.to_numeric(cells, errors="coerce")
    lvl = pd.Series(pd.NA, index=c.index, dtype="Int64")
    lvl = lvl.mask(c.notna(), 0)
    for i, t in enumerate(THRESHOLDS, start=1):
        lvl = lvl.mask(c >= t, i)
    return lvl


def two_consecutive_levels(single: pd.Series) -> pd.Series:
    """2회 연속 규칙 대리 산출 (조류경보제 운영 매뉴얼: 발령·하향·해제 모두 2회 연속 측정 기준).

    상태 s 에서 측정 단계 l 이 들어오면
    - 상향: 직전 측정 단계 p 와 l 이 모두 s 보다 높으면 s = min(l, p) (여러 단계 상향 가능)
    - 하향: p 와 l 이 모두 s 미만이면 s = max(l, p) — 두 측정이 모두 충족하는 단계로 바로 하향(해제 포함).
      매뉴얼 1.4.1.4 "2번 이상 연속하여 하위단계 기준에 해당되면 그 기준에 맞는 경보를 발령" 과
      표1 발령 이력(물금 '21, 강정 '24, 칠서 '18~'20 경계→해제 직행)에 맞춘 규칙.
    - 결측 측정은 상태를 바꾸지 않고 직전 값도 갱신하지 않는다.
    기상 고려 보류·조류독소 기준 등 실제 발령 재량은 반영하지 않으므로 '산출 단계' 로 표기한다.
    """
    out, s, prev = [], 0, None
    for v in single.tolist():
        if pd.isna(v):
            out.append(s)
            continue
        lvl = int(v)
        if prev is not None:
            if lvl > s and prev > s:
                s = min(lvl, prev)
            elif lvl < s and prev < s:
                s = max(lvl, prev)
        prev = lvl
        out.append(s)
    return pd.Series(out, index=single.index, dtype="Int64")


def dominant_genus(df: pd.DataFrame) -> pd.Series:
    g = df[list(GENUS)]
    has = g.notna().any(axis=1) & (g.fillna(0).max(axis=1) > 0)
    name = g.fillna(-1).idxmax(axis=1).map(GENUS)  # 동률이면 열 순서상 첫 속 (주최 측 스크립트와 동일)
    return name.where(has, None)


def tidy(items: list[dict[str, str]], fetched_at: pd.Timestamp) -> pd.DataFrame:
    """API item 목록을 표준 컬럼·수치형·파생 컬럼으로 정리한다 (지점·날짜 중복은 마지막 값 유지)."""
    raw = pd.DataFrame(items).fillna("")  # 일부 item 에 태그가 없으면 NaN → 빈 문자열
    if raw.empty:
        return raw
    df = pd.DataFrame({dst: raw.get(src, pd.Series("", index=raw.index)) for src, dst in FIELDS.items()})
    df = df[df["site_code"].isin(SITES)].copy()
    df["station_id"] = df["site_code"].map(SITES)
    dates = df["obs_date"].str.replace(".", "-", regex=False)
    df["obs_date"] = pd.to_datetime(dates, format="%Y-%m-%d").dt.date
    texts = {c: df[c].astype(str).str.strip() for c in NUMERIC}
    for c in NUMERIC:
        df[c] = _num(df[c])
    for c in LOQ_COLS:  # 플래그 컬럼은 토큰 출현 여부와 무관하게 항상 만든다 (스키마 고정)
        df[f"{c}_below_loq"] = texts[c].eq("정량한계미만")
    for c in PENDING_COLS:
        df[f"{c}_pending"] = texts[c].eq("분석중")
    df = df.sort_values(["site_code", "obs_date"]).drop_duplicates(["site_code", "obs_date"], keep="last")
    df["cells_sum4"] = df[list(GENUS)].sum(axis=1, min_count=1)
    both = df["iem_bgalage_cell_co"].notna() & df["cells_sum4"].notna()
    df["cells_consistent"] = pd.Series(pd.NA, index=df.index, dtype="boolean")
    diff = (df.loc[both, "iem_bgalage_cell_co"] - df.loc[both, "cells_sum4"]).abs()
    df.loc[both, "cells_consistent"] = diff <= 0.5
    df["dominant_genus"] = dominant_genus(df)
    df["alert_level_single"] = single_level(df["iem_bgalage_cell_co"])
    df["alert_level_2consec"] = (
        df.groupby("site_code", group_keys=False)["alert_level_single"]
        .apply(two_consecutive_levels)
        .astype("Int64")
    )
    df["alert_name_2consec"] = df["alert_level_2consec"].map(ALERT_NAMES)
    df["source"] = "nier_algae_api"
    df["fetched_at"] = pd.Series(fetched_at, index=df.index).astype("datetime64[ns, Asia/Seoul]")
    return df.reset_index(drop=True)


class NierAlgaeCollector(BaseCollector):
    source = "nier_algae"
    schema = SCHEMA

    def _year(
        self, sites: list[str], year: int, months: list[int], ttl: timedelta | None
    ) -> tuple[list[dict[str, str]], pd.Timestamp | None]:
        items: list[dict[str, str]] = []
        page, fetched = 1, None
        while True:
            res = self.get(
                URL,
                {
                    "serviceKey": self.service_key(),
                    "pageNo": str(page),
                    "numOfRows": str(PAGE_SIZE),
                    "resultType": "xml",
                    "ptNoList": ",".join(sites),
                    "wmyrList": str(year),
                    "wmodList": ",".join(f"{m:02d}" for m in months),
                },
                ttl=ttl,
            )
            fetched = fetched or pd.Timestamp(res.fetched_at)
            got, total = parse_items(res.text)
            items.extend(got)
            if len(items) >= total or not got:
                break
            page += 1
        return items, fetched

    def is_cacheable(self, text: str) -> bool:
        """resultCode 00 인 정상 XML 만 캐시한다 (점검 페이지·오류 본문이 영구 캐시되는 것을 막는다)."""
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return False
        return root.findtext(".//resultCode") in ("00", "0")

    @staticmethod
    def cache_ttl(year: int, now: datetime | None = None) -> timedelta:
        """연도별 캐시 허용 기간. 그 해가 '마감'(다음 해 2월 1일, 공표 지연 고려)된 뒤 받은 캐시만 영구 사용.

        get() 은 ``now - fetched <= ttl`` 이면 캐시를 쓰므로, ttl = now - closed_at 로 두면
        closed_at 이후에 받은 응답만 통과한다. 진행 중인 해(마감 전)는 12시간.
        """
        now = now or datetime.now(KST)
        closed_at = datetime(year + 1, 2, 1, tzinfo=KST)
        if now <= closed_at:
            return timedelta(hours=12)
        return max(now - closed_at, timedelta(hours=12))

    def fetch_many(self, sites: list[str], start: date, end: date) -> pd.DataFrame:
        """여러 지점을 연 단위로 수집. 마감된 해는 영구 캐시, 진행 중인 해는 12시간 캐시 (cache_ttl 참조).

        연도 요청은 항상 1~12월 전체로 보내 캐시 키를 안정시키고, 기간 필터는 결과에서 적용한다.
        ``fetched_at`` 은 실제 응답 시각(캐시면 캐시 저장 시각) 중 가장 늦은 값이다.
        """
        all_items: list[dict[str, str]] = []
        fetched_at: pd.Timestamp | None = None
        for year in range(start.year, end.year + 1):
            items, fetched = self._year(sites, year, list(range(1, 13)), self.cache_ttl(year))
            if fetched is not None:
                fetched_at = fetched if fetched_at is None else max(fetched_at, fetched)
            all_items.extend(items)
            log.info("nier_algae %d: %d rows", year, len(items))
        df = tidy(all_items, fetched_at or pd.Timestamp.now(tz=KST))
        if df.empty:
            return df
        df = df[(df["obs_date"] >= start) & (df["obs_date"] <= end)].reset_index(drop=True)
        return self.validate(df)

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        return self.fetch_many([site_code], start, end)


def compare_with_competition(api: pd.DataFrame, comp: pd.DataFrame) -> pd.DataFrame:
    """대회 번들(algae_measure)과 겹치는 (지점, 측정일) 의 세포수 일치율을 지점별로 집계한다."""
    key = ["site_code", "obs_date"]
    a = api[key + ["iem_bgalage_cell_co"]].rename(columns={"iem_bgalage_cell_co": "api"})
    c = comp[key + ["iem_bgalage_cell_co"]].rename(columns={"iem_bgalage_cell_co": "comp"})
    m = a.merge(c, on=key, how="outer", indicator=True)
    rows = []
    for site, g in m.groupby("site_code"):
        both = g[g["_merge"] == "both"]
        valid = both.dropna(subset=["api", "comp"])
        eq = (valid["api"] - valid["comp"]).abs() <= 0.5
        both_na = int((both["api"].isna() & both["comp"].isna()).sum())
        rows.append(
            {
                "site_code": site,
                "station_id": SITES.get(site, ""),
                "대회 행": int((g["_merge"] != "left_only").sum()),
                "API 행": int((g["_merge"] != "right_only").sum()),
                "공통 측정일": len(both),
                "둘 다 값 있음": len(valid),
                "세포수 일치": int(eq.sum()),
                "일치율 %": round(100 * eq.mean(), 2) if len(valid) else np.nan,
                "대회에만": int((g["_merge"] == "right_only").sum()),
                "API에만": int((g["_merge"] == "left_only").sum()),
                "결측 불일치": int(len(both) - len(valid) - both_na),
            }
        )
    return pd.DataFrame(rows).sort_values("station_id").reset_index(drop=True)


def _md(t: pd.DataFrame) -> str:
    hdr = "| " + " | ".join(t.columns) + " |\n|" + "---|" * len(t.columns)
    body = "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in t.itertuples(index=False))
    return hdr + "\n" + body


def main(argv: list[str] | None = None) -> int:
    """5지점 수집 → data/raw/nier_algae/ 저장 → 대회 대조표(reports/eda/nier_algae_match.md) → MANIFEST 행."""
    from algaecast.collect import competition as comp
    from algaecast.config import ROOT

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=date.fromisoformat, default=date(2012, 1, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    col = NierAlgaeCollector(use_cache=not args.no_cache)
    df = col.fetch_many(list(SITES), args.start, args.end)
    name = f"nier_algae_{args.start.year}_{args.end.year}"
    pq, csv = col.save(df, name)
    print(
        f"수집 {len(df):,}행 ({df['obs_date'].min()} ~ {df['obs_date'].max()}), "
        f"요청 {col.n_requests}회, 캐시 {col.n_cache_hits}회 → {pq.name}"
    )
    print("지점별 행:", df.groupby("station_id").size().to_dict())
    n_incons = int(df["cells_consistent"].eq(False).sum())
    print("4속 합 ≠ 총합:", n_incons, "/", int(df["cells_consistent"].notna().sum()))

    lines = [
        "# 조류경보제 API vs 대회 번들 세포수 대조 (T1-a)",
        "",
        f"- API 수집: {args.start} ~ {args.end}, {len(df):,}행, "
        f"수집 {pd.Timestamp.now(tz=KST):%Y-%m-%d %H:%M KST}",
        "- 기준: 같은 (지점, 측정일) 에서 `iem_bgalage_cell_co` 차이 ≤ 0.5 이면 일치. "
        "번들 생성일(2026-09-12) 이후 측정은 'API에만' 으로 집계된다.",
        f"- 4속 합 ≠ API 총합: {n_incons}건",
        "",
    ]
    if comp.available():
        cmp_df = comp.load_algae()
        overlap = df[df["obs_date"] <= cmp_df["obs_date"].max()]
        table_all = compare_with_competition(df, cmp_df)
        table_in = compare_with_competition(overlap, cmp_df)
        lines += ["## 전체 기간", _md(table_all), ""]
        lines += [
            f"## 대회 번들 기간 내 ({cmp_df['obs_date'].min()} ~ {cmp_df['obs_date'].max()})",
            _md(table_in),
            "",
        ]
        cols = ["site_code", "obs_date", "iem_bgalage_cell_co"]
        mism = df.merge(cmp_df[cols], on=["site_code", "obs_date"], suffixes=("_api", "_comp"))
        mism = mism[(mism["iem_bgalage_cell_co_api"] - mism["iem_bgalage_cell_co_comp"]).abs() > 0.5]
        if len(mism):
            lines += ["## 불일치 예시 (최대 20건)", "| site | obs_date | API | 대회 |", "|---|---|---|---|"]
            for r in mism.head(20).itertuples():
                lines.append(
                    f"| {r.site_code} | {r.obs_date} | "
                    f"{r.iem_bgalage_cell_co_api} | {r.iem_bgalage_cell_co_comp} |"
                )
        print(table_in.to_string(index=False))
    else:
        lines.append("(대회 번들 없음 — 대조 생략)")
    out = ROOT / "reports" / "eda" / "nier_algae_match.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("MANIFEST 행:")
    print(
        col.manifest_row(
            id_="WQ-01",
            name=f"조류경보제 조회서비스 (5지점, {name})",
            org="기후에너지환경부 국립환경과학원",
            endpoint="apis.data.go.kr/1480523/nieragainstalgae/algaePreMeasure (ptNoList 5지점)",
            period=f"{df['obs_date'].min()}~{df['obs_date'].max()}",
            rows=len(df),
            license_="공공누리 1유형(출처표시)",
            path=csv,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
