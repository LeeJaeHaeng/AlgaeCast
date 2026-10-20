"""HY-06 WAMIS 개방 API (환경부 한강홍수통제소, 인증키 불필요) — T1-b/T1-d.

- ``wkd/mn_dtdata?damcd=<코드>&startdt&enddt`` : 댐 **및 보** 일자료 (rwl 저수위/보 수위 EL.m, iqty 유입량,
  tdqty 총방류량, edqty 발전, spdqty 여수로, otltdqty 기타 방류량 ㎥/s, itqty 취수량, rf 강우 mm).
  보 코드는 WAMIS 보 코드(boobscd: 칠곡보 2011801, 강정고령보 2011802, 창녕함안보 2017801,
  낙동강하굿둑 2022510).
  요청당 약 3년까지만 반환되므로 연 단위로 나눠 받는다.
- ``wkw/wl_dtdata?obscd=<관측소>`` : 수위관측소 일수위 (보 상·하류 등),
  ``wkw/wl_dubwlobs?basin=2`` : 관측소 목록.
- 응답 ``{"result":{"code":"success"},"count":N,"list":[...]}``. 수치는 문자열 → float.
- 출력 규약(02 문서 9절): facility_code(또는 obscd), obs_date(date), 변수..., source, fetched_at.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import pandas as pd
import pandera.pandas as pa

from algaecast.collect.base import KST, BaseCollector, CollectError, closed_year_ttl
from algaecast.config import get_env

log = logging.getLogger(__name__)

DEFAULT_BASE = "http://www.wamis.go.kr:8080/wamis/openapi"
DAM_FIELDS = {
    "rwl": "rwl",
    "iqty": "iqty",
    "tdqty": "tdqty",
    "edqty": "edqty",
    "spdqty": "spdqty",
    "otltdqty": "otltdqty",
    "itqty": "itqty",
    "rf": "rf",
}
WEIR_CODES: dict[str, str] = {  # WAMIS 보 코드 → 이름 (연구 조사 2026-10-20, mn_dtdata 응답 확인)
    "2007801": "상주보",
    "2009801": "낙단보",
    "2009802": "구미보",
    "2011801": "칠곡보",
    "2011802": "강정고령보",
    "2014801": "달성보",
    "2014802": "합천창녕보",
    "2017801": "창녕함안보",
    "2022510": "낙동강하굿둑",
}


def wamis_base() -> str:
    return (get_env("API_WAMIS_BASE") or DEFAULT_BASE).rstrip("/")


def _repair_truncated(text: str) -> dict | None:
    """서버가 응답을 중간에 끊은 경우(관측소 목록 등에서 관찰) 마지막 완전한 list 항목까지 잘라 복구한다."""
    head = text.lstrip()
    if not head.startswith("{") or '"list":[' not in head:
        return None
    cut = head.rfind("},{")
    if cut < 0:
        return None
    try:
        return json.loads(head[: cut + 1] + "]}")
    except ValueError:
        return None


def _num(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.strip().str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned.where(cleaned != "", None), errors="coerce").astype("float64")


class WamisBase(BaseCollector):
    key_env = None  # 인증키 불필요

    def is_cacheable(self, text: str) -> bool:
        try:
            return json.loads(text).get("result", {}).get("code") == "success"
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def parse(text: str) -> list[dict]:
        try:
            payload = json.loads(text)
        except ValueError as exc:
            payload = _repair_truncated(text)
            if payload is None:
                raise CollectError(f"WAMIS 응답이 JSON 이 아님: {text.lstrip()[:100]!r}") from exc
            log.warning("WAMIS 응답이 중간에 잘려 마지막 완전한 항목까지만 사용 (%d bytes)", len(text))
        res = payload.get("result", {})
        if res.get("code") != "success":
            raise CollectError(f"WAMIS 오류 {res.get('code')}: {res.get('msg')}")
        return payload.get("list") or []

    def _by_year(
        self, endpoint: str, code_param: str, code: str, start: date, end: date
    ) -> tuple[list[dict], pd.Timestamp | None]:
        rows: list[dict] = []
        fetched: pd.Timestamp | None = None
        for year in range(start.year, end.year + 1):
            y0, y1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            params = {
                code_param: code,
                "startdt": y0.strftime("%Y%m%d"),
                "enddt": y1.strftime("%Y%m%d"),
                "output": "json",
            }
            try:
                res = self.get(f"{wamis_base()}/{endpoint}", params, ttl=closed_year_ttl(year))
                got = self.parse(res.text)
            except CollectError as exc:  # 연도 하나가 실패해도 나머지 연도는 유지 (오류는 collect_errors.log)
                log.warning("WAMIS %s %s %d 실패 — 건너뜀: %s", endpoint, code, year, exc)
                continue
            rows.extend(got)
            ts = pd.Timestamp(res.fetched_at)
            fetched = ts if fetched is None else max(fetched, ts)
        return rows, fetched


DAM_SCHEMA = pa.DataFrameSchema(
    {
        "facility_code": pa.Column(str),
        "obs_date": pa.Column(object, pa.Check(lambda s: s.map(lambda v: type(v) is date).all())),
        **{c: pa.Column(float, nullable=True) for c in DAM_FIELDS.values()},
        "source": pa.Column(str),
        "fetched_at": pa.Column(pd.DatetimeTZDtype(tz="Asia/Seoul")),
    },
    unique=["facility_code", "obs_date"],
    strict=False,
)


class WamisDamDailyCollector(WamisBase):
    """댐·보 일자료 (mn_dtdata). ``fetch(code, start, end)`` 의 code 는 WAMIS 댐코드 또는 보 코드."""

    source = "wamis_dam"
    schema = DAM_SCHEMA

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        rows, fetched = self._by_year("wkd/mn_dtdata", "damcd", site_code, start, end)
        return self.validate(self.tidy(rows, site_code, fetched))

    @staticmethod
    def tidy(rows: list[dict], code: str, fetched: pd.Timestamp | None) -> pd.DataFrame:
        cols = ["facility_code", "obs_date", *DAM_FIELDS.values(), "source", "fetched_at"]
        if not rows:
            return pd.DataFrame(columns=cols)
        raw = pd.DataFrame(rows).fillna("")
        df = pd.DataFrame(
            {"facility_code": code, "obs_date": pd.to_datetime(raw["obsymd"], format="%Y%m%d").dt.date}
        )
        for src, dst in DAM_FIELDS.items():
            df[dst] = _num(raw[src]) if src in raw.columns else float("nan")
        df["source"] = "wamis_mn_dtdata"
        stamp = fetched or pd.Timestamp.now(tz=KST)
        df["fetched_at"] = pd.Series(stamp, index=df.index).astype("datetime64[ns, Asia/Seoul]")
        df = df.sort_values("obs_date").drop_duplicates(["facility_code", "obs_date"], keep="last")
        return df.reset_index(drop=True)[cols]


LEVEL_SCHEMA = pa.DataFrameSchema(
    {
        "obscd": pa.Column(str),
        "obs_date": pa.Column(object, pa.Check(lambda s: s.map(lambda v: type(v) is date).all())),
        "wl": pa.Column(float, nullable=True),
        "source": pa.Column(str),
        "fetched_at": pa.Column(pd.DatetimeTZDtype(tz="Asia/Seoul")),
    },
    unique=["obscd", "obs_date"],
    strict=False,
)


class WamisLevelCollector(WamisBase):
    """수위관측소 일수위 (wl_dtdata). code 는 관측소 코드(obscd), 예: 칠곡보상 2011648."""

    source = "wamis_wl"
    schema = LEVEL_SCHEMA

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        rows, fetched = self._by_year("wkw/wl_dtdata", "obscd", site_code, start, end)
        cols = ["obscd", "obs_date", "wl", "source", "fetched_at"]
        if not rows:
            return pd.DataFrame(columns=cols)
        raw = pd.DataFrame(rows).fillna("")
        df = pd.DataFrame(
            {"obscd": site_code, "obs_date": pd.to_datetime(raw["ymd"], format="%Y%m%d").dt.date}
        )
        df["wl"] = _num(raw["wl"])
        df["source"] = "wamis_wl_dtdata"
        stamp = fetched or pd.Timestamp.now(tz=KST)
        df["fetched_at"] = pd.Series(stamp, index=df.index).astype("datetime64[ns, Asia/Seoul]")
        df = (
            df.sort_values("obs_date")
            .drop_duplicates(["obscd", "obs_date"], keep="last")
            .reset_index(drop=True)
        )
        return self.validate(df[cols])


def station_list(basin: str = "2", collector: WamisBase | None = None) -> pd.DataFrame:
    """수위관측소 목록 (basin 1 한강, 2 낙동강, 3 금강). 컬럼 obscd, obsnm, clsyn, mngorg, sbsncd."""
    col = collector or WamisLevelCollector()
    res = col.get(
        f"{wamis_base()}/wkw/wl_dubwlobs", {"basin": basin, "output": "json"}, ttl=timedelta(days=30)
    )
    return pd.DataFrame(col.parse(res.text))
