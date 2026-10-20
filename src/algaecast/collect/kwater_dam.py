"""HY-01/02/03 댐·보 수문 자료 수집·통합 — T1-b.

소스 우선순위 (사용자 지시 2026-10-20):
1. **번들 ``dam_daily.csv``(WAMIS 기반, 15개 댐, 2012-01-01~2026-09-11)** 가 과거 이력의 1차 소스.
2. data.go.kr '다목적댐 관리현황'(#15083337) CSV 를 ``data/raw/kwater/`` 에 두면
   ``load_kwater_csv()`` 로 보강.
3. 다목적댐 운영 정보 API(#15099049, 일 100건)는 **최근 N일 증분 전용** (``KwaterDamApiCollector``).
4. 보(칠곡·강정고령·창녕함안·낙동강하굿둑)·댐 일자료 검증/보강: K-water 수문 운영 정보 API ``/delist``
   (``KwaterSluiceCollector``, 일 10,000건, 댐·보 코드 지원, 2012~) 와 WAMIS ``mn_dtdata``(collect/wamis.py).
   두 소스는 같은 값을 주는 것으로 확인(칠곡보 2025-08-01 25.67 / 80.884 / 79.698 동일) → 교차검증 표로 보고.

출력: ``data/raw/hydro/hydro_daily_long.parquet`` (+csv) — 한 행 = (시설, 일자, 변수, 소스).
  컬럼: facility_type(dam|weir), facility_code(WAMIS 댐코드 또는 보 코드), kwater_code, facility_name, basin,
        obs_date, variable(rwl, iqty, tdqty, edqty, spdqty, otltdqty, itqty, rf, rsvwtqy, rsvwtrt,
        wl_up, wl_down),
        value, unit, source, fetched_at.
  sites.yaml 의 upstream_dams / facility_kwater_code / weirs.wl_up·wl_down 으로 지점에 결합한다.

사용: python -m algaecast.collect.kwater_dam [--start 2012-01-01] [--end 오늘] [--damapi-days 60]
      [--skip-damapi] [--skip-levels]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import yaml

from algaecast.collect import competition as comp
from algaecast.collect import wamis
from algaecast.collect.base import KST, BaseCollector, CollectError, closed_year_ttl
from algaecast.config import CONFIG_DIR, RAW_DIR, ROOT, get_env

log = logging.getLogger(__name__)

DAM_CODES_JSON = CONFIG_DIR / "dam_codes.json"
KWATER_CSV_DIR = RAW_DIR / "kwater"
HYDRO_DIR = RAW_DIR / "hydro"
UNITS = {
    "rwl": "EL.m",
    "iqty": "m3/s",
    "tdqty": "m3/s",
    "edqty": "m3/s",
    "spdqty": "m3/s",
    "otltdqty": "m3/s",
    "itqty": "m3/s",
    "rf": "mm",
    "rsvwtqy": "Mm3",
    "rsvwtrt": "%",
    "wl_up": "EL.m",
    "wl_down": "EL.m",
}
SLUICE_FIELDS = {  # K-water delist 응답 → 표준 변수명
    "lowlevel": "rwl",
    "inflowqy": "iqty",
    "totdcwtrqy": "tdqty",
    "prcptqy": "rf",
    "rsvwtqy": "rsvwtqy",
    "rsvwtrt": "rsvwtrt",
}
DAMAPI_FIELDS = {  # 다목적댐 운영 정보 응답 → 표준 변수명 (전일 값)
    "prcptqy": "rf",
    "inflowqy": "iqty",
    "totdcwtrqy": "tdqty",
    "nowlowlevel": "rwl",
    "nowrsvwtqy": "rsvwtqy",
    "rsvwtrt": "rsvwtrt",
}
CSV_ALIASES = {  # data.go.kr 다목적댐 관리현황 CSV 헤더 후보 → 표준 변수명 (파일 수령 후 보정)
    "댐명": "facility_name",
    "댐이름": "facility_name",
    "시설명": "facility_name",
    "댐코드": "kwater_code",
    "일자": "obs_date",
    "날짜": "obs_date",
    "관측일": "obs_date",
    "기준일": "obs_date",
    "강우량": "rf",
    "강우량(mm)": "rf",
    "유입량": "iqty",
    "유입량(cms)": "iqty",
    "유입량(㎥/s)": "iqty",
    "방류량": "tdqty",
    "총방류량": "tdqty",
    "방류량(cms)": "tdqty",
    "총방류량(㎥/s)": "tdqty",
    "저수위": "rwl",
    "저수위(el.m)": "rwl",
    "저수량": "rsvwtqy",
    "저수량(백만㎥)": "rsvwtqy",
    "저수율": "rsvwtrt",
    "저수율(%)": "rsvwtrt",
}
LONG_COLS = [
    "facility_type",
    "facility_code",
    "kwater_code",
    "facility_name",
    "basin",
    "obs_date",
    "variable",
    "value",
    "unit",
    "source",
    "fetched_at",
]


def _num(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.strip().str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned.where(cleaned != "", None), errors="coerce").astype("float64")


def load_sites() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))


def facility_catalog(sites: dict | None = None) -> pd.DataFrame:
    """sites.yaml 의 dams/weirs → 시설 목록 (type, facility_code=WAMIS, kwater_code, name, basin, role)."""
    sites = sites or load_sites()
    rows = []
    for code, d in sites["dams"].items():
        rows.append(
            {
                "facility_type": "dam",
                "facility_code": str(code),
                "kwater_code": str(d.get("kwater_code", code)),
                "facility_name": d["name"],
                "basin": d["basin"],
                "role": d.get("role", "main"),
            }
        )
    for kcode, w in sites.get("weirs", {}).items():
        rows.append(
            {
                "facility_type": "weir",
                "facility_code": str(w.get("wamis_bo_code", kcode)),
                "kwater_code": str(kcode),
                "facility_name": w["name"],
                "basin": w["basin"],
                "role": "weir",
            }
        )
    return pd.DataFrame(rows)


def dam_codes() -> dict[str, str]:
    """config/dam_codes.json (댐코드 조회 API 1회 호출 캐시) → {kwater_code: name}."""
    if not DAM_CODES_JSON.exists():
        raise CollectError(
            f"{DAM_CODES_JSON} 없음 — scripts/check_api_keys.py --all 또는 댐코드 조회 API 로 생성"
        )
    return json.loads(DAM_CODES_JSON.read_text(encoding="utf-8"))["codes"]


# ---------------------------------------------------------------- K-water 수문 운영 정보 (delist)
class KwaterSluiceCollector(BaseCollector):
    """``/sluicePresentCondition/delist`` 일자료. code 는 K-water 댐·보 코드 (config/dam_codes.json)."""

    source = "kwater_sluice"
    schema = pa.DataFrameSchema(
        {
            "kwater_code": pa.Column(str),
            "obs_date": pa.Column(object, pa.Check(lambda s: s.map(lambda v: type(v) is date).all())),
            **{v: pa.Column(float, nullable=True) for v in SLUICE_FIELDS.values()},
            "source": pa.Column(str),
            "fetched_at": pa.Column(pd.DatetimeTZDtype(tz="Asia/Seoul")),
        },
        unique=["kwater_code", "obs_date"],
        strict=False,
    )

    def is_cacheable(self, text: str) -> bool:
        try:
            return json.loads(text)["response"]["header"]["resultCode"] == "00"
        except (ValueError, KeyError, TypeError):
            return False

    @staticmethod
    def parse(text: str) -> tuple[list[dict], int]:
        try:
            body = json.loads(text)["response"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CollectError(f"수문 운영 정보 응답 형식 오류: {text.lstrip()[:100]!r}") from exc
        if body["header"].get("resultCode") != "00":
            raise CollectError(f"수문 운영 정보 resultCode={body['header']}")
        items = body["body"].get("items") or {}
        raw = items.get("item") if isinstance(items, dict) else None
        rows = raw if isinstance(raw, list) else ([raw] if raw else [])
        return rows, int(body["body"].get("totalCount") or len(rows))

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        base = get_env("API_KWATER_SLUICE", required=True).rstrip("/") + "/delist"
        rows: list[dict] = []
        fetched: pd.Timestamp | None = None
        for year in range(start.year, end.year + 1):
            y0, y1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            page = 1
            while True:
                res = self.get(
                    base,
                    {
                        "serviceKey": self.service_key(),
                        "pageNo": str(page),
                        "numOfRows": "400",
                        "_type": "json",
                        "damcode": site_code,
                        "stdt": y0.isoformat(),
                        "eddt": y1.isoformat(),
                    },
                    ttl=closed_year_ttl(year),
                )
                got, total = self.parse(res.text)
                rows.extend(got)
                ts = pd.Timestamp(res.fetched_at)
                fetched = ts if fetched is None else max(fetched, ts)
                if len(rows) >= total or not got or len(got) < 400:
                    break
                page += 1
        return self.validate(self.tidy(rows, site_code, fetched))

    @staticmethod
    def tidy(rows: list[dict], code: str, fetched: pd.Timestamp | None) -> pd.DataFrame:
        cols = ["kwater_code", "obs_date", *SLUICE_FIELDS.values(), "source", "fetched_at"]
        if not rows:
            return pd.DataFrame(columns=cols)
        raw = pd.DataFrame(rows).fillna("")
        df = pd.DataFrame({"kwater_code": code, "obs_date": pd.to_datetime(raw["obsryymtde"]).dt.date})
        for src, dst in SLUICE_FIELDS.items():
            df[dst] = _num(raw[src]) if src in raw.columns else float("nan")
        df["source"] = "kwater_sluice_delist"
        stamp = fetched or pd.Timestamp.now(tz=KST)
        df["fetched_at"] = pd.Series(stamp, index=df.index).astype("datetime64[ns, Asia/Seoul]")
        df = df.sort_values("obs_date").drop_duplicates(["kwater_code", "obs_date"], keep="last")
        return df.reset_index(drop=True)[cols]


# ---------------------------------------------------------------- 다목적댐 운영 정보 (최근 증분 전용)
class KwaterDamApiCollector(BaseCollector):
    """``multipurPoseDamlist`` — 날짜별 21개 댐 스냅샷 (일 100건 제한 → 최근 N일만, 날짜별 영구 캐시)."""

    source = "kwater_damapi"

    def is_cacheable(self, text: str) -> bool:
        try:
            p = json.loads(text)["response"]
            return p["header"]["resultCode"] == "00" and bool(p["body"].get("items"))
        except (ValueError, KeyError, TypeError):
            return False

    def fetch_day(self, d: date) -> list[dict]:
        url = get_env("API_KWATER_DAM", required=True)
        res = self.get(
            url,
            {
                "serviceKey": self.service_key(),
                "pageNo": "1",
                "numOfRows": "50",
                "_type": "json",
                "vdate": d.isoformat(),
                "tdate": (d - timedelta(days=1)).isoformat(),
                "ldate": _year_ago(d).isoformat(),
                "vtime": "07",
            },
            ttl=None,
        )
        rows, _ = KwaterSluiceCollector.parse(res.text)
        for r in rows:
            r["_vdate"] = d.isoformat()
            r["_fetched_at"] = pd.Timestamp(res.fetched_at).isoformat()
        return rows

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        """site_code 는 무시(전 댐 반환). start~end 의 각 날짜를 조회(캐시된 날짜는 호출 없음)."""
        rows: list[dict] = []
        d = start
        while d <= end:
            rows.extend(self.fetch_day(d))
            d += timedelta(days=1)
        return self.tidy(rows)

    @staticmethod
    def tidy(rows: list[dict]) -> pd.DataFrame:
        cols = ["dam_name", "basin", "obs_date", *DAMAPI_FIELDS.values(), "source", "fetched_at"]
        if not rows:
            return pd.DataFrame(columns=cols)
        raw = pd.DataFrame(rows).fillna("")
        # 응답의 유입·방류·강우는 '전일' 값 → obs_date = vdate − 1일; 수위·저수량은 조회일 07시 현재 값
        vdate = pd.to_datetime(raw["_vdate"])
        df = pd.DataFrame(
            {
                "dam_name": raw["damnm"],
                "basin": raw["suge"],
                "obs_date": (vdate - pd.Timedelta(days=1)).dt.date,
            }
        )
        for src, dst in DAMAPI_FIELDS.items():
            df[dst] = _num(raw[src]) if src in raw.columns else float("nan")
        df["source"] = "kwater_damapi"
        df["fetched_at"] = (
            pd.to_datetime(raw["_fetched_at"])
            .dt.tz_convert("Asia/Seoul")
            .astype("datetime64[ns, Asia/Seoul]")
        )
        return (
            df.sort_values(["dam_name", "obs_date"])
            .drop_duplicates(["dam_name", "obs_date"], keep="last")
            .reset_index(drop=True)[cols]
        )


def _year_ago(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


# ---------------------------------------------------------------- data.go.kr CSV (수동 다운로드 보강)
def load_kwater_csv(directory: Path | None = None) -> pd.DataFrame | None:
    """``data/raw/kwater/*.csv`` (다목적댐 관리현황 #15083337 등) → 표준 변수 wide 표. 파일이 없으면 None.

    헤더는 CSV_ALIASES 로 매핑하며, 매핑되지 않은 필수 컬럼(댐명·일자)이 없으면 CollectError 로 알린다.
    """
    directory = KWATER_CSV_DIR if directory is None else directory
    files = sorted(directory.glob("*.csv")) if directory.exists() else []
    if not files:
        log.info("data/raw/kwater/*.csv 없음 — 수동 CSV 보강 생략")
        return None
    frames = []
    for f in files:
        for enc in ("utf-8-sig", "cp949"):
            try:
                raw = pd.read_csv(f, encoding=enc, dtype=str, keep_default_na=False)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise CollectError(f"{f.name}: 인코딩 판별 실패")
        ren = {c: CSV_ALIASES.get(str(c).strip().lower().replace(" ", ""), None) for c in raw.columns}
        ren = {k: v for k, v in ren.items() if v}
        df = raw.rename(columns=ren)
        missing = {"facility_name", "obs_date"} - set(df.columns)
        if missing:
            raise CollectError(f"{f.name}: 필수 컬럼 매핑 실패 {missing}; 헤더={list(raw.columns)[:12]}")
        df["obs_date"] = pd.to_datetime(
            df["obs_date"].str.replace(".", "-", regex=False), errors="coerce"
        ).dt.date
        for v in ("rf", "iqty", "tdqty", "rwl", "rsvwtqy", "rsvwtrt"):
            if v in df.columns:
                df[v] = _num(df[v])
        df["source"] = f"kwater_csv:{f.name}"
        frames.append(df)
    out = pd.concat(frames, ignore_index=True).dropna(subset=["obs_date"])
    return out


# ---------------------------------------------------------------- long 포맷·검증
def to_long(wide: pd.DataFrame, meta: pd.Series, variables: list[str]) -> pd.DataFrame:
    """wide(obs_date + 변수 컬럼) → long 행. meta: 시설 메타 행(facility_type, facility_code 등)."""
    keep = [v for v in variables if v in wide.columns]
    m = wide.melt(
        id_vars=["obs_date", "source", "fetched_at"], value_vars=keep, var_name="variable", value_name="value"
    )
    m = m.dropna(subset=["value"])
    for k in ("facility_type", "facility_code", "kwater_code", "facility_name", "basin"):
        m[k] = meta[k]
    m["unit"] = m["variable"].map(UNITS)
    return m[LONG_COLS]


def compare_series(a: pd.DataFrame, b: pd.DataFrame, var: str, *, abs_tol: float, rel_tol: float) -> dict:
    """같은 obs_date 의 변수 var 를 비교. 일치 = |a−b| ≤ abs_tol 또는 상대오차 ≤ rel_tol."""
    m = a[["obs_date", var]].merge(b[["obs_date", var]], on="obs_date", suffixes=("_a", "_b"))
    both = m.dropna()
    if both.empty:
        return {"n_common": len(m), "n_both": 0, "match_pct": float("nan"), "median_abs_diff": float("nan")}
    diff = (both[f"{var}_a"] - both[f"{var}_b"]).abs()
    rel = diff / both[f"{var}_b"].abs().replace(0, float("nan"))
    ok = (diff <= abs_tol) | (rel <= rel_tol)
    return {
        "n_common": int(len(m)),
        "n_both": int(len(both)),
        "match_pct": round(100 * ok.mean(), 2),
        "median_abs_diff": round(float(diff.median()), 4),
        "max_abs_diff": round(float(diff.max()), 3),
    }


TOL = {"rwl": (0.01, 0.0), "iqty": (0.01, 0.01), "tdqty": (0.01, 0.01)}
VAR_KO = {"rwl": "수위", "iqty": "유입량", "tdqty": "방류량"}


def match_table(
    bundle: pd.DataFrame, external: pd.DataFrame, catalog: pd.DataFrame, source_name: str
) -> pd.DataFrame:
    """댐(시설)별 × 변수별 일치율 표. bundle/external 은 wide(obs_date, rwl, iqty, tdqty) + facility_code."""
    rows = []
    for code, grp in bundle.groupby("facility_code"):
        ext = external[external["facility_code"] == code]
        name = catalog.set_index("facility_code")["facility_name"].get(code, code)
        if ext.empty:
            rows.append(
                {
                    "시설": f"{name}({code})",
                    "비교 소스": source_name,
                    "변수": "-",
                    "공통일": 0,
                    "일치율 %": float("nan"),
                    "중앙 |차|": float("nan"),
                    "최대 |차|": float("nan"),
                }
            )
            continue
        for var, (at, rt) in TOL.items():
            st = compare_series(grp, ext, var, abs_tol=at, rel_tol=rt)
            rows.append(
                {
                    "시설": f"{name}({code})",
                    "비교 소스": source_name,
                    "변수": VAR_KO[var],
                    "공통일": st["n_both"],
                    "일치율 %": st["match_pct"],
                    "중앙 |차|": st["median_abs_diff"],
                    "최대 |차|": st.get("max_abs_diff", float("nan")),
                }
            )
    return pd.DataFrame(rows)


def missing_table(
    wide: pd.DataFrame, catalog: pd.DataFrame, variables: tuple[str, ...] = ("rwl", "iqty", "tdqty", "rf")
) -> pd.DataFrame:
    """시설 × 연도 결측률(%) — 기대 일수(해당 연도 수록 구간의 달력 일수) 대비 값이 있는 날 비율."""
    out = []
    names = catalog.set_index("facility_code")["facility_name"]
    for code, grp in wide.groupby("facility_code"):
        d = pd.to_datetime(grp["obs_date"])
        for year, g in grp.groupby(d.dt.year):
            dd = pd.to_datetime(g["obs_date"])
            expected = (dd.max() - dd.min()).days + 1
            row = {"시설": f"{names.get(code, code)}({code})", "연도": int(year), "기대일": int(expected)}
            for v in variables:
                if v in g.columns:
                    row[f"{v} 결측%"] = round(100 * (1 - g[v].notna().sum() / expected), 1)
            out.append(row)
    return pd.DataFrame(out)


def _md(t: pd.DataFrame) -> str:
    if t.empty:
        return "(없음)"
    hdr = "| " + " | ".join(map(str, t.columns)) + " |\n|" + "---|" * len(t.columns)
    body = "\n".join(
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in t.itertuples(index=False)
    )
    return hdr + "\n" + body


# ---------------------------------------------------------------- 실행
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=date.fromisoformat, default=date(2012, 1, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--damapi-days", type=int, default=60)
    ap.add_argument("--skip-damapi", action="store_true")
    ap.add_argument("--skip-levels", action="store_true", help="WAMIS 보 상·하류 수위 생략")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sites = load_sites()
    cat = facility_catalog(sites)
    dams = cat[cat["facility_type"] == "dam"]
    weirs = cat[cat["facility_type"] == "weir"]
    HYDRO_DIR.mkdir(parents=True, exist_ok=True)
    long_parts: list[pd.DataFrame] = []
    report: list[str] = ["# 댐·보 수문 자료 수집 검증 (T1-b)", ""]

    # 1) 번들 dam_daily (1차 소스)
    bundle = comp.load_dam_daily().rename(columns={"dam_code": "facility_code"})
    bundle["source"] = "bundle_wamis"
    for code, grp in bundle.groupby("facility_code"):
        meta = cat[cat["facility_code"] == code].iloc[0]
        long_parts.append(to_long(grp, meta, list(wamis.DAM_FIELDS.values())))
    report += [
        f"- 번들 dam_daily: {len(bundle):,}행, {bundle['facility_code'].nunique()}개 댐, "
        f"{bundle['obs_date'].min()}~{bundle['obs_date'].max()}"
    ]

    # 2) K-water CSV 보강 (있을 때만)
    csv_df = load_kwater_csv()
    if csv_df is not None:
        report.append(
            f"- data.go.kr 다목적댐 관리현황 CSV: {len(csv_df):,}행 ({csv_df['source'].nunique()} 파일)"
        )
    else:
        report.append("- data.go.kr 다목적댐 관리현황 CSV: 없음 (data/raw/kwater/*.csv 에 두면 자동 반영)")

    # 3) K-water delist — 댐(본댐) + 보, 전 기간
    sl = KwaterSluiceCollector()
    ext_frames = []
    for _, m in pd.concat([dams[dams["role"] == "main"], weirs]).iterrows():
        try:
            df = sl.fetch(m["kwater_code"], args.start, args.end)
        except CollectError as exc:
            log.warning("delist %s(%s) 실패: %s", m["facility_name"], m["kwater_code"], exc)
            continue
        df["facility_code"] = m["facility_code"]
        ext_frames.append(df)
        long_parts.append(to_long(df, m, list(SLUICE_FIELDS.values())))
    sluice = pd.concat(ext_frames, ignore_index=True) if ext_frames else pd.DataFrame()
    sl.save(sluice, "kwater_sluice_daily") if len(sluice) else None
    report.append(
        f"- K-water 수문 운영 정보(delist): {len(sluice):,}행, "
        f"요청 {sl.n_requests}회, 캐시 {sl.n_cache_hits}회"
    )

    # 4) WAMIS mn_dtdata — 보 전 기간 + 댐 2026년(번들 이후 보강)
    wd = wamis.WamisDamDailyCollector()
    wamis_frames = []
    for _, m in weirs.iterrows():
        try:
            df = wd.fetch(m["facility_code"], args.start, args.end)
        except CollectError as exc:
            log.warning("WAMIS 보 %s(%s) 실패: %s", m["facility_name"], m["facility_code"], exc)
            continue
        wamis_frames.append(df)
        long_parts.append(to_long(df, m, list(wamis.DAM_FIELDS.values())))
    tail_start = max(args.start, bundle["obs_date"].max() + timedelta(days=1))
    for _, m in dams.iterrows():
        try:
            df = wd.fetch(m["facility_code"], tail_start, args.end)
        except CollectError as exc:
            log.warning("WAMIS 댐 %s(%s) 실패: %s", m["facility_name"], m["facility_code"], exc)
            continue
        wamis_frames.append(df)
        long_parts.append(to_long(df, m, list(wamis.DAM_FIELDS.values())))
    wamis_df = pd.concat(wamis_frames, ignore_index=True) if wamis_frames else pd.DataFrame()
    wd.save(wamis_df, "wamis_dam_daily") if len(wamis_df) else None
    report.append(
        f"- WAMIS mn_dtdata: {len(wamis_df):,}행 (보 전기간 + 댐 {tail_start}~), "
        f"요청 {wd.n_requests}회, 캐시 {wd.n_cache_hits}회"
    )

    # 5) WAMIS 보 상·하류 수위
    if not args.skip_levels:
        wl = wamis.WamisLevelCollector()
        for kcode, w in sites.get("weirs", {}).items():
            meta = weirs[weirs["kwater_code"] == str(kcode)].iloc[0]
            for pos, var in (("wl_up", "wl_up"), ("wl_down", "wl_down")):
                obscd = w.get(pos)
                if not obscd:
                    continue
                try:
                    df = wl.fetch(str(obscd), args.start, args.end)
                except CollectError as exc:
                    log.warning("WAMIS 수위 %s %s 실패: %s", w["name"], obscd, exc)
                    continue
                df = df.rename(columns={"wl": var})
                long_parts.append(to_long(df, meta, [var]))
        report.append(f"- WAMIS 보 상·하류 수위: 요청 {wl.n_requests}회, 캐시 {wl.n_cache_hits}회")

    # 6) 다목적댐 운영 정보 API 최근 증분
    if not args.skip_damapi:
        da = KwaterDamApiCollector()
        try:
            recent = da.fetch("", args.end - timedelta(days=args.damapi_days - 1), args.end)
            name_to_code = {d["name"]: c for c, d in sites["dams"].items()}
            recent["facility_code"] = recent["dam_name"].map(name_to_code)
            da.save(recent, "kwater_damapi_recent")
            for code, grp in recent.dropna(subset=["facility_code"]).groupby("facility_code"):
                meta = cat[cat["facility_code"] == code].iloc[0]
                long_parts.append(to_long(grp, meta, list(DAMAPI_FIELDS.values())))
            report.append(
                f"- 다목적댐 운영 정보 API(최근 {args.damapi_days}일): {len(recent):,}행, "
                f"요청 {da.n_requests}회, 캐시 {da.n_cache_hits}회"
            )
        except CollectError as exc:
            report.append(f"- 다목적댐 운영 정보 API: 실패 — {exc}")

    # 7) 저장 + 검증 표
    long_df = pd.concat(long_parts, ignore_index=True)
    long_df["value"] = long_df["value"].astype("float64")
    pq = HYDRO_DIR / "hydro_daily_long.parquet"
    long_df.to_parquet(pq, index=False)
    long_df.to_csv(HYDRO_DIR / "hydro_daily_long.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    report.append(f"- 통합 long: {len(long_df):,}행 → {pq.relative_to(ROOT)}")
    report.append("")

    if len(sluice):
        report += [
            "## 번들 dam_daily(WAMIS) vs K-water 수문 운영 정보(delist) — 댐별 일치율",
            "허용오차: 수위 ±0.01 EL.m, 유입·방류 ±0.01 ㎥/s 또는 상대 1%",
            _md(match_table(bundle, sluice, cat, "K-water delist")),
            "",
        ]
        weir_w = (
            wamis_df[wamis_df["facility_code"].isin(weirs["facility_code"])]
            if len(wamis_df)
            else pd.DataFrame()
        )
        if len(weir_w):
            sl_w = sluice.merge(weirs[["facility_code"]], on="facility_code")
            report += [
                "## 보: WAMIS mn_dtdata vs K-water delist 교차검증",
                _md(match_table(weir_w, sl_w, cat, "K-water delist")),
                "",
            ]
    report += ["## 번들 dam_daily 결측률 (댐 × 연도, %)", _md(missing_table(bundle, cat)), ""]
    if len(sluice):
        sl_weirs = sluice[sluice["facility_code"].isin(weirs["facility_code"])]
        report += ["## 보 K-water delist 결측률 (보 × 연도, %)", _md(missing_table(sl_weirs, cat)), ""]
    out = ROOT / "reports" / "eda" / "hydro_match.md"
    out.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(report[:12]))
    print(f"... 전체 보고서: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
