"""MT-01 기상청 ASOS 일자료 수집기 (data.go.kr #15059093) — T1-c.

- 엔드포인트 ``API_KMA_ASOS_DAILY`` (``/AsosDalyInfoService/getWthrDataList``), dataCd=ASOS, dateCd=DAY,
  startDt/endDt(YYYYMMDD), stnIds, numOfRows 999(연 단위 1페이지).
  지점당 후보 관측소 2~3개(sites.yaml asos_candidates). API 는 전날 자료까지만 제공한다.
- 항목: avgTa/maxTa/minTa 기온, sumRn 일강수량(무강수 빈칸 → 관측일에만 0), avgWs/maxWs 풍속, avgRhm 습도,
  sumSsHr 일조시간, sumGsr 일사량(미관측 지점 결측 — 일조시간으로 대체 가능하게 둘 다 보존),
  avgPs 기압, avgTca 전운량.
- 출력 규약: stn_id, obs_date(date), 변수(snake_case), rn_blank, day_observed, source, fetched_at.
- 관측소 선정: ``station_choice()`` 가 후보 관측소 기온과 대회 수질자료 수온의 Spearman 상관을 계산한다.

사용: python -m algaecast.collect.kma_asos [--start 2012-01-01] [--end 오늘]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta

import pandas as pd
import pandera.pandas as pa
import yaml
from scipy.stats import spearmanr

from algaecast.collect import competition as comp
from algaecast.collect.base import KST, BaseCollector, CollectError, closed_year_ttl
from algaecast.config import CONFIG_DIR, ROOT, get_env

log = logging.getLogger(__name__)

FIELDS: dict[str, str] = {
    "avgTa": "avg_ta",
    "maxTa": "max_ta",
    "minTa": "min_ta",
    "sumRn": "sum_rn",
    "hr1MaxRn": "hr1_max_rn",
    "avgWs": "avg_ws",
    "maxWs": "max_ws",
    "maxInsWs": "max_ins_ws",
    "avgRhm": "avg_rhm",
    "sumSsHr": "sum_ss_hr",
    "sumGsr": "sum_gsr",
    "avgPs": "avg_ps",
    "avgTca": "avg_tca",
    "avgTs": "avg_ts",
    "avgTd": "avg_td",
}
SCHEMA = pa.DataFrameSchema(
    {
        "stn_id": pa.Column(int),
        "stn_nm": pa.Column(str),
        "obs_date": pa.Column(object, pa.Check(lambda s: s.map(lambda v: type(v) is date).all())),
        **{v: pa.Column(float, nullable=True) for v in FIELDS.values()},
        "rn_blank": pa.Column(bool),
        "day_observed": pa.Column(bool),
        "source": pa.Column(str),
        "fetched_at": pa.Column(pd.DatetimeTZDtype(tz="Asia/Seoul")),
    },
    unique=["stn_id", "obs_date"],
    strict=False,
)


def _num(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.strip().str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned.where(cleaned != "", None), errors="coerce").astype("float64")


class KmaAsosCollector(BaseCollector):
    source = "kma_asos"
    schema = SCHEMA

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
            raise CollectError(f"ASOS 응답 형식 오류: {text.lstrip()[:100]!r}") from exc
        h = body["header"]
        if h.get("resultCode") != "00":
            raise CollectError(f"ASOS resultCode={h.get('resultCode')} {h.get('resultMsg')}")
        items = body["body"].get("items") or {}
        raw = items.get("item") if isinstance(items, dict) else None
        rows = raw if isinstance(raw, list) else ([raw] if raw else [])
        return rows, int(body["body"].get("totalCount") or len(rows))

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        """site_code = ASOS 지점번호(문자열). 연 단위로 요청(365행 < 999 → 1페이지)."""
        url = get_env("API_KMA_ASOS_DAILY", required=True)
        rows: list[dict] = []
        fetched: pd.Timestamp | None = None
        last = date.today() - timedelta(days=1)  # API 는 전날 자료까지만 제공(resultCode 99)
        for year in range(start.year, end.year + 1):
            y0 = max(start, date(year, 1, 1))
            y1 = min(end, date(year, 12, 31), last)
            if y0 > y1:
                continue
            page = 1
            while True:
                res = self.get(
                    url,
                    {
                        "serviceKey": self.service_key(),
                        "pageNo": str(page),
                        "numOfRows": "999",
                        "dataType": "JSON",
                        "dataCd": "ASOS",
                        "dateCd": "DAY",
                        "startDt": y0.strftime("%Y%m%d"),
                        "endDt": y1.strftime("%Y%m%d"),
                        "stnIds": site_code,
                    },
                    ttl=closed_year_ttl(year),
                )
                got, total = self.parse(res.text)
                rows.extend(got)
                ts = pd.Timestamp(res.fetched_at)
                fetched = ts if fetched is None else max(fetched, ts)
                if len(rows) >= total or not got or len(got) < 999:
                    break
                page += 1
        return self.validate(self.tidy(rows, fetched))

    @staticmethod
    def tidy(rows: list[dict], fetched: pd.Timestamp | None) -> pd.DataFrame:
        cols = [
            "stn_id",
            "stn_nm",
            "obs_date",
            *FIELDS.values(),
            "rn_blank",
            "day_observed",
            "source",
            "fetched_at",
        ]
        if not rows:
            return pd.DataFrame(columns=cols)
        raw = pd.DataFrame(rows).fillna("")
        df = pd.DataFrame(
            {
                "stn_id": raw["stnId"].astype(int),
                "stn_nm": raw["stnNm"],
                "obs_date": pd.to_datetime(raw["tm"]).dt.date,
            }
        )
        for src, dst in FIELDS.items():
            df[dst] = _num(raw[src]) if src in raw.columns else float("nan")
        df["rn_blank"] = raw.get("sumRn", pd.Series("", index=raw.index)).astype(str).str.strip().eq("")
        df["day_observed"] = df["avg_ta"].notna() | df["avg_rhm"].notna()
        fill = df["rn_blank"] & df["day_observed"]
        df.loc[fill, "sum_rn"] = 0.0
        df.loc[fill & df["hr1_max_rn"].isna(), "hr1_max_rn"] = 0.0
        df["source"] = "kma_asos_api"
        stamp = fetched or pd.Timestamp.now(tz=KST)
        df["fetched_at"] = pd.Series(stamp, index=df.index).astype("datetime64[ns, Asia/Seoul]")
        df = df.sort_values(["stn_id", "obs_date"]).drop_duplicates(["stn_id", "obs_date"], keep="last")
        return df.reset_index(drop=True)[cols]


# ---------------------------------------------------------------- 검증·선정
def compare_with_bundle(api: pd.DataFrame, bundle: pd.DataFrame, tol: float = 0.05) -> pd.DataFrame:
    """번들 asos_daily 와 겹치는 (지점, 일) 의 변수별 일치율(|차| ≤ tol)."""
    vars_ = [
        "avg_ta",
        "max_ta",
        "min_ta",
        "sum_rn",
        "avg_ws",
        "avg_rhm",
        "sum_ss_hr",
        "sum_gsr",
        "avg_ps",
        "avg_tca",
    ]
    m = api.merge(bundle, on=["stn_id", "obs_date"], suffixes=("_api", "_b"))
    rows = []
    for stn, g in m.groupby("stn_id"):
        row = {"stn_id": stn, "stn_nm": g["stn_nm_api"].iloc[0], "공통일": len(g)}
        for v in vars_:
            both = g[[f"{v}_api", f"{v}_b"]].dropna()
            row[v] = (
                round(100 * ((both[f"{v}_api"] - both[f"{v}_b"]).abs() <= tol).mean(), 1)
                if len(both)
                else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


def missing_table(
    df: pd.DataFrame,
    variables: tuple[str, ...] = ("avg_ta", "sum_rn", "avg_ws", "avg_rhm", "sum_ss_hr", "sum_gsr", "avg_tca"),
) -> pd.DataFrame:
    """관측소 × 연도 × 변수 결측률(%) (달력 일수 대비)."""
    d = df.assign(year=pd.to_datetime(df["obs_date"]).dt.year)
    out = []
    for (stn, nm, year), g in d.groupby(["stn_id", "stn_nm", "year"]):
        dd = pd.to_datetime(g["obs_date"])
        expected = (dd.max() - dd.min()).days + 1
        row = {"stn": f"{nm}({stn})", "연도": int(year), "기대일": int(expected)}
        for v in variables:
            row[v] = round(100 * (1 - g[v].notna().sum() / expected), 1)
        out.append(row)
    return pd.DataFrame(out)


def station_choice(asos: pd.DataFrame, sites_cfg: dict, algae: pd.DataFrame) -> pd.DataFrame:
    """지점별 후보 관측소의 기온(당일·7일 평균) vs 수질자료 수온(측정일) Spearman 상관."""
    rows = []
    wide = asos.pivot(index="obs_date", columns="stn_id", values="avg_ta").sort_index()
    wide.index = pd.to_datetime(wide.index)
    ma7 = wide.rolling(7, min_periods=4).mean()
    for site in sites_cfg["sites"]:
        wq = algae[algae["site_code"] == site["site_code"]][["obs_date", "iem_wtrtp"]].dropna()
        wq_idx = pd.to_datetime(wq["obs_date"])
        for cand in site.get("asos_candidates", []):
            stn = int(cand["stn_id"])
            if stn not in wide.columns:
                continue
            ta = wide[stn].reindex(wq_idx).to_numpy()
            ta7 = ma7[stn].reindex(wq_idx).to_numpy()
            wt = wq["iem_wtrtp"].to_numpy()
            ok = ~pd.isna(ta) & ~pd.isna(wt)
            ok7 = ~pd.isna(ta7) & ~pd.isna(wt)
            r1 = spearmanr(ta[ok], wt[ok]).correlation if ok.sum() > 10 else float("nan")
            r7 = spearmanr(ta7[ok7], wt[ok7]).correlation if ok7.sum() > 10 else float("nan")
            gsr_cov = asos.loc[asos["stn_id"] == stn, "sum_gsr"].notna().mean()
            rows.append(
                {
                    "station_id": site["station_id"],
                    "site": site["name"],
                    "stn_id": stn,
                    "stn_nm": cand["name"],
                    "거리 km": cand.get("distance_km"),
                    "n": int(ok.sum()),
                    "spearman 당일기온": round(float(r1), 4),
                    "spearman 7일평균기온": round(float(r7), 4),
                    "일사 보유율 %": round(100 * gsr_cov, 1),
                }
            )
    return pd.DataFrame(rows)


def _md(t: pd.DataFrame) -> str:
    if t.empty:
        return "(없음)"
    hdr = "| " + " | ".join(map(str, t.columns)) + " |\n|" + "---|" * len(t.columns)
    body = "\n".join(
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in t.itertuples(index=False)
    )
    return hdr + "\n" + body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=date.fromisoformat, default=date(2012, 1, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sites_cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    stations = {int(c["stn_id"]): c["name"] for s in sites_cfg["sites"] for c in s.get("asos_candidates", [])}
    col = KmaAsosCollector()
    frames = []
    for stn in sorted(stations):
        df = col.fetch(str(stn), args.start, args.end)
        frames.append(df)
        log.info("ASOS %s(%d): %d rows", stations[stn], stn, len(df))
    asos = pd.concat(frames, ignore_index=True)
    pq, csv = col.save(asos, f"kma_asos_daily_{args.start.year}_{args.end.year}")
    print(
        f"수집 {len(asos):,}행, 관측소 {asos['stn_id'].nunique()}개, "
        f"요청 {col.n_requests}회, 캐시 {col.n_cache_hits}회 → {pq.name}"
    )

    lines = [
        "# ASOS 관측소 선정 근거·검증 (T1-c)",
        "",
        f"- 수집: {args.start}~{args.end}, 관측소 {sorted(stations)}",
    ]
    if comp.available():
        bundle = comp.load_asos()
        cmp_t = compare_with_bundle(asos, bundle)
        lines += ["", "## 번들 asos_daily 와 일치율 (%, |차| ≤ 0.05)", _md(cmp_t)]
        choice = station_choice(asos, sites_cfg, comp.load_algae())
        lines += ["", "## 후보 관측소 기온 vs 수질 수온 Spearman (측정일 기준)", _md(choice)]
        best = (
            choice.sort_values(["station_id", "spearman 7일평균기온"], ascending=[True, False])
            .groupby("station_id")
            .head(1)
        )
        lines += [
            "",
            "## 1순위(7일 평균기온 상관 최대)",
            _md(best[["station_id", "site", "stn_id", "stn_nm", "spearman 7일평균기온"]]),
        ]
        print(choice.to_string(index=False))
        (ROOT / "reports" / "eda").mkdir(parents=True, exist_ok=True)
        choice.to_csv(ROOT / "reports" / "eda" / "asos_station_choice.csv", index=False, encoding="utf-8-sig")
    miss = missing_table(asos)
    lines += ["", "## 결측률 (관측소 × 연도 × 변수, %)", _md(miss)]
    out = ROOT / "reports" / "eda" / "asos_station_choice.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("MANIFEST 행:")
    print(
        col.manifest_row(
            id_="MT-01",
            name=f"ASOS 일자료 {len(stations)}개 관측소 (kma_asos_daily_{args.start.year}_{args.end.year})",
            org="기상청",
            endpoint="apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList",
            period=f"{asos['obs_date'].min()}~{asos['obs_date'].max()}",
            rows=len(asos),
            license_="공공누리 1유형(출처표시)",
            path=csv,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
