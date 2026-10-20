"""MT-05/06 기상청 단기예보 2.0 · 중기예보 발표분 수집기 (T1-e).

- 단기예보 ``API_KMA_VILAGE_FCST/getVilageFcst`` (base_date, base_time=0500, nx, ny):
  발표 당일~+3일(일부 +4일) 시간별 TMP/TMX/TMN/POP/PCP/REH/WSD/SKY/PTY
  → 일 단위 집계(TMX·TMN 그대로, TMP 평균, POP 최대, PCP 합, REH·WSD 평균).
- 중기예보 ``API_KMA_MID_FCST`` getMidTa(regId, tmFc=YYYYMMDD0600 → taMin3~10/taMax3~10),
  getMidLandFcst(regId → rnSt3Am.. 강수확률): 발표일 +3~+10일. (서비스 미승인 상태면 코드 30 → 건너뜀)
- 좌표→격자: ``latlon_to_grid`` (기상청 LCC, 공식 C 코드 이식).
- 출력 long: issued_at(KST), site_code, station_id, target_date, variable, value, source.
  과거 발표분은 API 로 받을 수 없어 **2026-10-21 이후 매일 누적**
  (``data/raw/kma_forecast/YYYY-MM-DD.csv``, 커밋 허용).

사용: python -m algaecast.collect.kma_forecast [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from algaecast.collect.base import KST, BaseCollector, CollectError, PortalError
from algaecast.config import CONFIG_DIR, RAW_DIR, get_env

log = logging.getLogger(__name__)

OUT_DIR = RAW_DIR / "kma_forecast"
LONG_COLS = ["issued_at", "site_code", "station_id", "target_date", "variable", "value", "source"]
VILAGE_BASE_TIME = "0500"  # 05시 발표분(06시 수집). 02/05/08/11/14/17/20/23시 발표
MID_TM_FC = "0600"


# ---------------------------------------------------------------- 격자 변환 (기상청 공식)
def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 단기예보 격자(nx, ny). Lambert Conformal Conic, 격자 5 km."""
    re_, grid = 6371.00877, 5.0
    slat1, slat2, olon, olat = map(math.radians, (30.0, 60.0, 126.0, 38.0))
    xo, yo = 210 / grid, 675 / grid  # 기준점 격자 (42, 135)
    re_ /= grid
    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = sf**sn * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re_ * sf / ro**sn
    ra = math.tan(math.pi * 0.25 + math.radians(lat) * 0.5)
    ra = re_ * sf / ra**sn
    theta = math.radians(lon) - olon
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return int(ra * math.sin(theta) + xo + 1.5), int(ro - ra * math.cos(theta) + yo + 1.5)


def parse_pcp(v: object) -> float | None:
    """'강수없음'→0, '1.0mm'→1.0, '30.0~50.0mm'→40.0, '50.0mm 이상'→50.0, '1mm 미만'→0.5."""
    s = str(v).strip()
    if not s or s in ("-", "nan", "None"):
        return None
    if "없음" in s:
        return 0.0
    if "미만" in s:
        return 0.5
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if not nums:
        return None
    return sum(nums) / len(nums)


# ---------------------------------------------------------------- 수집기
class _Kma(BaseCollector):
    def is_cacheable(self, text: str) -> bool:
        try:
            return json.loads(text)["response"]["header"]["resultCode"] == "00"
        except (ValueError, KeyError, TypeError):
            return False

    @staticmethod
    def parse(text: str) -> list[dict]:
        try:
            body = json.loads(text)["response"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CollectError(f"기상청 응답 형식 오류: {text.lstrip()[:100]!r}") from exc
        h = body["header"]
        if h.get("resultCode") == "03":  # NO_DATA
            return []
        if h.get("resultCode") != "00":
            raise CollectError(f"기상청 resultCode={h.get('resultCode')} {h.get('resultMsg')}")
        items = body["body"].get("items") or {}
        raw = items.get("item") if isinstance(items, dict) else None
        return raw if isinstance(raw, list) else ([raw] if raw else [])


class VilageFcstCollector(_Kma):
    source = "kma_vilage_fcst"
    schema = None

    def fetch(
        self, site_code: str, start: date, end: date
    ) -> pd.DataFrame:  # pragma: no cover - 인터페이스용
        raise NotImplementedError("fetch_site(site, issue_date) 사용")

    def fetch_site(self, site: dict, issue_date: date, base_time: str = VILAGE_BASE_TIME) -> pd.DataFrame:
        nx, ny = latlon_to_grid(float(site["lat"]), float(site["lon"]))
        res = self.get(
            get_env("API_KMA_VILAGE_FCST", required=True) + "/getVilageFcst",
            {
                "serviceKey": self.service_key(),
                "pageNo": "1",
                "numOfRows": "1000",
                "dataType": "JSON",
                "base_date": issue_date.strftime("%Y%m%d"),
                "base_time": base_time,
                "nx": str(nx),
                "ny": str(ny),
            },
            ttl=timedelta(days=36500),  # 발표분은 불변
        )
        items = self.parse(res.text)
        issued = datetime.strptime(f"{issue_date:%Y%m%d}{base_time}", "%Y%m%d%H%M").replace(tzinfo=KST)
        return self.tidy(items, site, issued)

    @staticmethod
    def tidy(items: list[dict], site: dict, issued: datetime) -> pd.DataFrame:
        if not items:
            return pd.DataFrame(columns=LONG_COLS)
        df = pd.DataFrame(items)
        df["target_date"] = pd.to_datetime(df["fcstDate"]).dt.date
        out: list[dict] = []

        def add(td: date, var: str, val: float | None) -> None:
            if val is not None and not pd.isna(val):
                out.append({"target_date": td, "variable": var, "value": float(val)})

        for td, g in df.groupby("target_date"):
            cat = g.set_index("category")
            num = pd.to_numeric(g["fcstValue"], errors="coerce")
            for c, var, agg in (
                ("TMP", "ta_mean", "mean"),
                ("POP", "pop_max", "max"),
                ("REH", "rh_mean", "mean"),
                ("WSD", "ws_mean", "mean"),
                ("SKY", "sky_mean", "mean"),
            ):
                vals = num[g["category"] == c]
                if len(vals):
                    add(td, var, getattr(vals, agg)())
            for c, var in (("TMX", "ta_max"), ("TMN", "ta_min")):
                if c in cat.index:
                    add(td, var, pd.to_numeric(cat.loc[[c], "fcstValue"], errors="coerce").iloc[0])
            pcp = [parse_pcp(v) for v in g.loc[g["category"] == "PCP", "fcstValue"]]
            pcp = [p for p in pcp if p is not None]
            if pcp:
                add(td, "rn_sum", sum(pcp))
            add(td, "n_hours", (g["category"] == "TMP").sum())
        res = pd.DataFrame(out)
        res["issued_at"] = issued
        res["site_code"] = site["site_code"]
        res["station_id"] = site["station_id"]
        res["source"] = "kma_vilage_fcst"
        return res[LONG_COLS]


class MidFcstCollector(_Kma):
    source = "kma_mid_fcst"
    schema = None

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("fetch_site(site, issue_date) 사용")

    def _call(self, ep: str, reg_id: str, tm_fc: str) -> list[dict]:
        return self.parse(
            self.get(
                get_env("API_KMA_MID_FCST", required=True) + f"/{ep}",
                {
                    "serviceKey": self.service_key(),
                    "pageNo": "1",
                    "numOfRows": "10",
                    "dataType": "JSON",
                    "regId": reg_id,
                    "tmFc": tm_fc,
                },
                ttl=timedelta(days=36500),
            ).text
        )

    def fetch_site(self, site: dict, issue_date: date) -> pd.DataFrame:
        tm_fc = f"{issue_date:%Y%m%d}{MID_TM_FC}"
        ta = self._call("getMidTa", site["kma_mid_reg_id_ta"], tm_fc)
        land = self._call("getMidLandFcst", site["kma_mid_reg_id_land"], tm_fc)
        issued = datetime.strptime(tm_fc, "%Y%m%d%H%M").replace(tzinfo=KST)
        return self.tidy(ta[0] if ta else {}, land[0] if land else {}, site, issued)

    @staticmethod
    def tidy(ta: dict, land: dict, site: dict, issued: datetime) -> pd.DataFrame:
        out = []
        base = issued.date()
        for d in range(3, 11):
            td = base + timedelta(days=d)
            for key, var in ((f"taMin{d}", "ta_min"), (f"taMax{d}", "ta_max")):
                v = pd.to_numeric(ta.get(key), errors="coerce")
                if not pd.isna(v):
                    out.append({"target_date": td, "variable": var, "value": float(v)})
            pops = [
                pd.to_numeric(land.get(k), errors="coerce") for k in (f"rnSt{d}Am", f"rnSt{d}Pm", f"rnSt{d}")
            ]
            pops = [p for p in pops if not pd.isna(p)]
            if pops:
                out.append({"target_date": td, "variable": "pop_max", "value": float(max(pops))})
        res = pd.DataFrame(out, columns=["target_date", "variable", "value"])
        res["issued_at"] = issued
        res["site_code"] = site["site_code"]
        res["station_id"] = site["station_id"]
        res["source"] = "kma_mid_fcst"
        return res[LONG_COLS]


# ---------------------------------------------------------------- 적재·조회
def load_all(out_dir: Path = OUT_DIR) -> pd.DataFrame:
    files = sorted(out_dir.glob("*.csv")) if out_dir.exists() else []
    if not files:
        return pd.DataFrame(columns=LONG_COLS)
    df = pd.concat([pd.read_csv(f, dtype={"site_code": str}) for f in files], ignore_index=True)
    df["issued_at"] = pd.to_datetime(df["issued_at"], utc=True).dt.tz_convert("Asia/Seoul")
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    return df.drop_duplicates(["issued_at", "site_code", "target_date", "variable", "source"], keep="last")


def forecasts_as_of(df: pd.DataFrame, base_date: date) -> pd.DataFrame:
    """base_date 당일 06시까지 발표된 예보만 (누수 방지: issued_at ≤ base_date 06:00 KST)."""
    cutoff = datetime.combine(base_date, datetime.min.time()).replace(hour=6, tzinfo=KST)
    return df[df["issued_at"] <= cutoff]


def collect_day(issue_date: date, sites: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    frames = []
    vil = VilageFcstCollector()
    for s in sites:
        try:
            frames.append(vil.fetch_site(s, issue_date))
        except (CollectError, PortalError, RuntimeError) as exc:
            notes.append(f"단기 {s['station_id']}: {exc}")
    mid = MidFcstCollector()
    for s in sites:
        try:
            frames.append(mid.fetch_site(s, issue_date))
        except (CollectError, PortalError, RuntimeError) as exc:
            notes.append(f"중기 {s['station_id']}: {exc}")
            if "30" in str(exc) or "등록되지 않은" in str(exc):
                notes.append("중기예보 서비스 미승인 — 나머지 지점 생략")
                break
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=LONG_COLS)
    return df, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", type=date.fromisoformat, default=date.today(), help="발표일(KST)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sites = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))["sites"]
    df, notes = collect_day(args.date, sites)
    for n in notes:
        log.warning(n)
    if df.empty:
        print("예보 수집 결과 없음")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.date:%Y-%m-%d}.csv"
    if out.exists():
        prev = pd.read_csv(out, dtype={"site_code": str})
        prev["issued_at"] = pd.to_datetime(prev["issued_at"], utc=True).dt.tz_convert("Asia/Seoul")
        prev["target_date"] = pd.to_datetime(prev["target_date"]).dt.date
        df = pd.concat([prev, df], ignore_index=True).drop_duplicates(
            ["issued_at", "site_code", "target_date", "variable", "source"], keep="last"
        )
    df = df.sort_values(["source", "site_code", "target_date", "variable"])
    df.to_csv(out, index=False, encoding="utf-8", lineterminator="\n")
    print(
        f"{out.name}: {len(df)}행 (단기 {int((df['source'] == 'kma_vilage_fcst').sum())}, "
        f"중기 {int((df['source'] == 'kma_mid_fcst').sum())}), 지점 {df['site_code'].nunique()}"
    )
    print(df.head(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
