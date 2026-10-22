"""EXP-008(R5) 조류경보제 전 지점 수집기 — ``ptNoList`` 없이 연도별 조회(data.go.kr #15126738).

- 엔드포인트·항목·파생 규칙은 ``collect/nier_algae.py`` 와 같다(같은 함수 재사용). 차이:
  ``ptNoList`` 를 보내지 않아 그 해 운영된 **전 지점**(상수원·친수, 하천·호소)이 응답에 들어온다.
- 지점 식별: ``station_id`` = 우리 5지점은 v1 이름(HP·GJGR·CS·MGMR·DCHN), 그 밖은 조사지점코드 그대로.
- 비수치 문자열: v1 수집기는 알 수 없는 토큰이면 중단하지만 전 지점 자료는 표기가 다양하므로 NaN 으로 두고
  ``token_report`` 에 (열, 값, 건수)를 남긴다.
- 출력: ``data/raw/nier_algae_all/nier_algae_all_<시작>_<끝>.parquet``(+csv), 지점 목록 ``sites_all.csv``.
  2026 측정도 원자료에는 들어오지만, 실험(EXP-008)은 obs_date ≤ 2025-12-31 만 읽는다.

사용: python -m algaecast.collect.nier_algae_all [--start-year 2012] [--end-year 2026]
"""

from __future__ import annotations

import argparse
import logging
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd

from algaecast.collect.base import KST, BaseCollector, closed_year_ttl
from algaecast.collect.nier_algae import (
    ALERT_NAMES,
    FIELDS,
    GENUS,
    LOQ_COLS,
    NUMERIC,
    PAGE_SIZE,
    PENDING_COLS,
    SITES,
    TOKENS,
    URL,
    dominant_genus,
    parse_items,
    single_level,
    two_consecutive_levels,
)

log = logging.getLogger(__name__)
SOURCE = "nier_algae_all"


def lenient_num(s: pd.Series) -> tuple[pd.Series, dict[str, int]]:
    """문자열 → float. 빈칸·토큰·알 수 없는 문자열은 NaN, 알 수 없는 문자열은 건수로 돌려준다."""
    cleaned = s.astype(str).str.strip().str.replace(",", "", regex=False)
    out = pd.to_numeric(cleaned.where(cleaned != "", None), errors="coerce").astype("float64")
    bad = cleaned[(cleaned != "") & out.isna() & ~cleaned.isin(TOKENS)]
    return out, {str(k): int(v) for k, v in bad.value_counts().items()}


def tidy_all(items: list[dict[str, str]], fetched_at: pd.Timestamp) -> tuple[pd.DataFrame, list[dict]]:
    """API item 목록(전 지점) → 표준 열·파생 열. (데이터, 알 수 없는 토큰 보고)"""
    raw = pd.DataFrame(items).fillna("")
    if raw.empty:
        return raw, []
    df = pd.DataFrame({dst: raw.get(src, pd.Series("", index=raw.index)) for src, dst in FIELDS.items()})
    df = df[df["site_code"].astype(str).str.len() > 0].copy()
    df["station_id"] = df["site_code"].map(SITES).fillna(df["site_code"])
    dates = df["obs_date"].str.replace(".", "-", regex=False)
    df["obs_date"] = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce").dt.date
    df = df[df["obs_date"].notna()].copy()
    texts = {c: df[c].astype(str).str.strip() for c in NUMERIC}
    report: list[dict] = []
    for c in NUMERIC:
        df[c], bad = lenient_num(df[c])
        report += [{"column": c, "value": k, "count": v} for k, v in bad.items()]
    for c in LOQ_COLS:
        df[f"{c}_below_loq"] = texts[c].eq("정량한계미만")
    for c in PENDING_COLS:
        df[f"{c}_pending"] = texts[c].eq("분석중")
    # 음수(오기) 세포수는 결측으로 둔다
    for c in ["iem_bgalage_cell_co", *GENUS]:
        df.loc[df[c] < 0, c] = float("nan")
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
    df["source"] = "nier_algae_api_all"
    df["fetched_at"] = pd.Series(fetched_at, index=df.index).astype("datetime64[ns, Asia/Seoul]")
    return df.reset_index(drop=True), report


def site_table(df: pd.DataFrame) -> pd.DataFrame:
    """지점 목록: 코드·이름·구분·주소·기간·측정 수(최신 이름 기준)."""
    d = df.sort_values("obs_date")
    g = d.groupby("site_code")
    out = pd.DataFrame(
        {
            "station_id": g["station_id"].last(),
            "swmn_nm": g["swmn_nm"].last(),
            "swmn_detail_nm": g["swmn_detail_nm"].last(),
            "detail_adres": g["detail_adres"].last(),
            "river_lkmh_se": g["river_lkmh_se"].last(),
            "first_obs": g["obs_date"].min(),
            "last_obs": g["obs_date"].max(),
            "n_obs": g.size(),
            "n_cells": g["iem_bgalage_cell_co"].count(),
            "n_over_10k": g["iem_bgalage_cell_co"].apply(lambda s: int((s >= 10_000).sum())),
        }
    )
    return out.reset_index()


class NierAlgaeAllCollector(BaseCollector):
    """``ptNoList`` 없이 연도 단위로 전 지점을 받는다(페이지 10,000행)."""

    source = SOURCE
    schema = None

    def is_cacheable(self, text: str) -> bool:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return False
        return root.findtext(".//resultCode") in ("00", "0")

    def year_items(self, year: int) -> tuple[list[dict[str, str]], pd.Timestamp | None, int]:
        items: list[dict[str, str]] = []
        page, fetched, total = 1, None, 0
        while True:
            res = self.get(
                URL,
                {
                    "serviceKey": self.service_key(),
                    "pageNo": str(page),
                    "numOfRows": str(PAGE_SIZE),
                    "resultType": "xml",
                    "wmyrList": str(year),
                    "wmodList": ",".join(f"{m:02d}" for m in range(1, 13)),
                },
                ttl=closed_year_ttl(year),
            )
            ts = pd.Timestamp(res.fetched_at)
            fetched = ts if fetched is None else max(fetched, ts)
            got, total = parse_items(res.text)
            items.extend(got)
            if len(items) >= total or not got:
                break
            page += 1
        return items, fetched, total

    def fetch_years(self, start_year: int, end_year: int) -> tuple[pd.DataFrame, list[dict], dict[int, int]]:
        all_items: list[dict[str, str]] = []
        fetched_at: pd.Timestamp | None = None
        totals: dict[int, int] = {}
        for year in range(start_year, end_year + 1):
            items, fetched, total = self.year_items(year)
            totals[year] = total
            if fetched is not None:
                fetched_at = fetched if fetched_at is None else max(fetched_at, fetched)
            all_items.extend(items)
            log.info("nier_algae_all %d: %d rows (totalCount %d)", year, len(items), total)
        df, report = tidy_all(all_items, fetched_at or pd.Timestamp.now(tz=KST))
        return df, report, totals

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        df, _, _ = self.fetch_years(start.year, end.year)
        if df.empty:
            return df
        return df[(df["site_code"] == site_code) & (df["obs_date"] >= start) & (df["obs_date"] <= end)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-year", type=int, default=2012)
    ap.add_argument("--end-year", type=int, default=date.today().year)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    col = NierAlgaeAllCollector()
    df, report, totals = col.fetch_years(args.start_year, args.end_year)
    name = f"{SOURCE}_{args.start_year}_{args.end_year}"
    pq, csv = col.save(df, name)
    sites = site_table(df)
    sites.to_csv(col.out_dir / "sites_all.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.DataFrame(report).to_csv(
        col.out_dir / "token_report.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )
    print(
        f"수집 {len(df):,}행, 지점 {df['site_code'].nunique()}개 "
        f"({df['obs_date'].min()}~{df['obs_date'].max()}), "
        f"요청 {col.n_requests}회, 캐시 {col.n_cache_hits}회 → {pq.name}"
    )
    print("연도별 totalCount:", totals)
    print("알 수 없는 토큰:", report[:10])
    print(
        col.manifest_row(
            id_="WQ-01b",
            name=f"조류경보제 조회서비스 전 지점({name})",
            org="기후에너지환경부 국립환경과학원",
            endpoint="apis.data.go.kr/1480523/nieragainstalgae/algaePreMeasure (ptNoList 없음, 연도별)",
            period=f"{df['obs_date'].min()}~{df['obs_date'].max()}",
            rows=len(df),
            license_="공공누리 1유형(출처표시)",
            path=csv,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
