"""HY-05 DataON 「댐유역 하천 일평균수위」 국가참조표준 엑셀 파서 (T1-d).

입력: ``data/raw/dataon/**/댐유역 하천 일평균수위*.xlsx`` (DOI 10.20925/KSRD.74670854.v5, 2010~2024, 187개소).
파일 형식이 연도마다 다르다(2026-10-20 확인):
- wide: 2010-2014 / 2015-2019 / 2021 / 2022 / 2023('일평균수위' 시트) / 2024
  — 1행 메타, 2행 헤더(일자 + 관측소명 186열),
  날짜는 ``20100101`` 정수 또는 ``2024년01월01일``. 해발표고(El.m) 지점은 이름 앞 ``*`` 가 붙기도 한다.
- matrix: 2020 — '관측소 정보' 시트(일련번호·댐명·관측소명)
  + 관측소별 시트(일 × 월 행렬, 헤더에 WAMIS 수위관측소 코드).
출력 long: station_code(WAMIS 수위코드), station_name, dam_name, obs_date, wl(m), source.
저장: ``data/raw/dataon/dataon_level_daily_long.parquet`` (원자료 비커밋 원칙 → git 제외).
라이선스 CC BY-NC-SA(DataON 표기, DOI 10.20925/KSRD.74670854.v5) — 가공물도 같은 조건으로만 재배포.
파일이 없으면 스키마만 두고 건너뛴다.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import yaml

from algaecast.collect.base import CollectError
from algaecast.config import CONFIG_DIR, RAW_DIR, ROOT

log = logging.getLogger(__name__)

DATAON_DIR = RAW_DIR / "dataon"
OUT_PATH = DATAON_DIR / "dataon_level_daily_long.parquet"
CONT_PATH = DATAON_DIR / "level_continuous_long.parquet"
CUTOVER = date(2025, 1, 1)  # 이 날부터 WAMIS
LONG_COLS = ["station_code", "station_name", "dam_name", "obs_date", "wl", "source"]
SCHEMA = pa.DataFrameSchema(
    {
        "station_code": pa.Column(str, pa.Check.str_matches(r"^\d{7}$")),
        "station_name": pa.Column(str),
        "dam_name": pa.Column(str, nullable=True),
        "obs_date": pa.Column(object, pa.Check(lambda s: s.map(lambda v: type(v) is date).all())),
        "wl": pa.Column(float, nullable=False),
        "source": pa.Column(str),
    },
    unique=["station_code", "obs_date"],
    strict=False,
)


def norm_name(name: object) -> str:
    """'*경주시(감포댐)', '1. 태백시(무사교) 수위관측소' → '경주시(감포댐)'."""
    s = str(name).strip()
    s = re.sub(r"^\d+\.\s*", "", s)
    s = re.sub(r"\s*수위\s*관측소$", "", s)
    return s.lstrip("*").replace(" ", "")


def _parse_date(v: object) -> date | None:
    s = str(v).strip()
    m = re.match(r"^(\d{4})\D*(\d{1,2})\D*(\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def station_catalog(matrix_file: Path) -> pd.DataFrame:
    """2020 파일에서 (관측소명 → WAMIS 코드, 댐명) 목록을 만든다."""
    xl = pd.ExcelFile(matrix_file)
    info = xl.parse("관측소 정보", header=None, skiprows=2).iloc[:, :3]
    info.columns = ["no", "dam_name", "station_name"]
    info = info.dropna(subset=["station_name"])
    info["station_name"] = info["station_name"].map(norm_name)
    codes: dict[str, str] = {}
    for sh in xl.sheet_names[1:]:
        head = xl.parse(sh, header=None, nrows=2)
        m = re.search(r",\s*(\d{7})\)", str(head.iloc[1, 0]))
        if m:
            codes[norm_name(head.iloc[0, 0])] = m[1]
    info["station_code"] = info["station_name"].map(codes)
    missing = info["station_code"].isna().sum()
    if missing:
        names = info.loc[info["station_code"].isna(), "station_name"].tolist()
        log.warning("관측소 코드 없음 %d개: %s", missing, names)
    cat = info[["station_code", "station_name", "dam_name"]].dropna(subset=["station_code"])
    return cat.reset_index(drop=True)


def parse_wide(path: Path, sheet: str | int = 0) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    hdr_idx = next(i for i in range(min(5, len(raw))) if _parse_date(raw.iloc[i + 1, 0]) is not None)
    header = [norm_name(c) for c in raw.iloc[hdr_idx]]
    body = raw.iloc[hdr_idx + 1 :].copy()
    body.columns = header
    body = body.rename(columns={header[0]: "obs_date"})
    body["obs_date"] = body["obs_date"].map(_parse_date)
    body = body.dropna(subset=["obs_date"])
    long = body.melt(id_vars="obs_date", var_name="station_name", value_name="wl")
    long["wl"] = pd.to_numeric(long["wl"], errors="coerce")
    long = long.dropna(subset=["wl"])
    long["source"] = f"dataon_v5:{path.name}"
    return long


def parse_matrix(path: Path) -> pd.DataFrame:
    """2020 형식: 관측소별 시트, 행 = 일(1~31), 열 = 월(1,3,5,… 홀수 열)."""
    xl = pd.ExcelFile(path)
    year_m = re.search(r"\((\d{4})\)", path.name)
    year = int(year_m[1]) if year_m else 2020
    frames = []
    for sh in xl.sheet_names[1:]:
        df = xl.parse(sh, header=None)
        name = norm_name(df.iloc[0, 0])
        head_row = next(i for i in range(10) if "Month" in str(df.iloc[i, 0]) or "Date" in str(df.iloc[i, 0]))
        month_cols = {
            c: int(m[1])
            for c in df.columns[1:]
            if (m := re.match(r"^(\d{1,2})월", str(df.iloc[head_row, c]).strip()))
        }
        rows = []
        for i in range(head_row + 1, len(df)):
            d = pd.to_numeric(df.iloc[i, 0], errors="coerce")
            if pd.isna(d) or not 1 <= int(d) <= 31:
                continue
            for c, mth in month_cols.items():
                v = pd.to_numeric(df.iloc[i, c], errors="coerce")
                if pd.isna(v):
                    continue
                try:
                    rows.append({"obs_date": date(year, mth, int(d)), "station_name": name, "wl": float(v)})
                except ValueError:
                    continue
        frames.append(pd.DataFrame(rows))
    long = pd.concat(frames, ignore_index=True)
    long["source"] = f"dataon_v5:{path.name}"
    return long


def _is_matrix(path: Path) -> bool:
    return "관측소 정보" in pd.ExcelFile(path).sheet_names


def load_all(root: Path = DATAON_DIR) -> pd.DataFrame | None:
    files = sorted(p for p in root.rglob("댐유역 하천 일평균수위*.xlsx") if not p.name.startswith("~$"))
    if not files:
        log.info("DataON 일평균수위 xlsx 없음 (%s) — 건너뜀", root)
        return None
    matrix = [p for p in files if _is_matrix(p)]
    if not matrix:
        raise CollectError("관측소 코드 출처(2020 형식 '관측소 정보' 시트) 파일이 없어 코드 매핑 불가")
    cat = station_catalog(matrix[0])
    frames = []
    for p in files:
        if p in matrix:
            part = parse_matrix(p)
        else:
            sheets = pd.ExcelFile(p).sheet_names
            part = parse_wide(p, "일평균수위" if "일평균수위" in sheets else 0)
        log.info("%s: %d rows, %d stations", p.name, len(part), part["station_name"].nunique())
        frames.append(part)
    long = pd.concat(frames, ignore_index=True).merge(cat, on="station_name", how="left")
    unknown = long.loc[long["station_code"].isna(), "station_name"].unique().tolist()
    if unknown:
        log.warning("코드 매핑 안 된 관측소 %d개(제외): %s", len(unknown), unknown[:10])
        long = long.dropna(subset=["station_code"])
    long = long.sort_values(["station_code", "obs_date", "source"])
    long = long.drop_duplicates(["station_code", "obs_date"], keep="last")
    return SCHEMA.validate(long[LONG_COLS].reset_index(drop=True))


def coverage_table(long: pd.DataFrame, sites_cfg: dict) -> pd.DataFrame:
    """지점별 dataon_stations 의 기간·행수·결측률."""
    rows = []
    for s in sites_cfg["sites"]:
        for ent in s.get("dataon_stations", []):
            code = str(ent["code"]) if isinstance(ent, dict) else str(ent)
            g = long[long["station_code"] == code]
            if g.empty:
                rows.append({"station_id": s["station_id"], "code": code, "name": "(파일에 없음)"})
                continue
            d0, d1 = g["obs_date"].min(), g["obs_date"].max()
            expected = (d1 - d0).days + 1
            rows.append(
                {
                    "station_id": s["station_id"],
                    "code": code,
                    "name": g["station_name"].iloc[0],
                    "dam": g["dam_name"].iloc[0],
                    "기간": f"{d0}~{d1}",
                    "행": len(g),
                    "결측%": round(100 * (1 - len(g) / expected), 1),
                }
            )
    return pd.DataFrame(rows)


def compare_with_wamis(long: pd.DataFrame, tol: float = 0.05) -> pd.DataFrame | None:
    """T1-b hydro long(WAMIS wl_dtdata, 보 상·하류 수위)과 같은 수위관측소 코드의 일치율.

    hydro long 은 보 코드 + wl_up/wl_down 으로 저장돼 있어
    sites.yaml weirs 의 wl_up/wl_down 관측소 코드로 되돌린다.
    """
    hydro = ROOT / "data" / "raw" / "hydro" / "hydro_daily_long.parquet"
    if not hydro.exists():
        return None
    weirs = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8")).get("weirs", {})
    key = {}
    for bo, w in weirs.items():
        for var in ("wl_up", "wl_down"):
            if w.get(var):
                key[(str(w.get("wamis_bo_code", bo)), var)] = str(w[var])
    h = pd.read_parquet(hydro)
    h = h[h["variable"].isin(["wl_up", "wl_down"]) & (h["source"] == "wamis_wl_dtdata")].copy()
    h["station_code"] = [key.get((c, v)) for c, v in zip(h["facility_code"], h["variable"], strict=True)]
    h = h.dropna(subset=["station_code"])[["station_code", "obs_date", "value"]]
    m = long.merge(h, on=["station_code", "obs_date"])
    if m.empty:
        return None
    rows = []
    for code, g in m.groupby("station_code"):
        rows.append(
            {
                "code": code,
                "name": g["station_name"].iloc[0],
                "공통일": len(g),
                "일치율 %": round(100 * ((g["wl"] - g["value"]).abs() <= tol).mean(), 1),
                "평균차 m": round(float((g["wl"] - g["value"]).mean()), 3),
            }
        )
    return pd.DataFrame(rows)


def site_station_codes(sites_cfg: dict) -> list[str]:
    codes: list[str] = []
    for s in sites_cfg["sites"]:
        for ent in s.get("dataon_stations", []):
            c = str(ent["code"]) if isinstance(ent, dict) else str(ent)
            if c not in codes:
                codes.append(c)
    return codes


def fetch_wamis_levels(codes: list[str], start: date, end: date) -> pd.DataFrame:
    """WAMIS wl_dtdata 로 같은 수위관측소를 수집 (연도 실패는 건너뜀)."""
    from algaecast.collect.wamis import WamisLevelCollector

    col = WamisLevelCollector()
    frames = []
    for c in codes:
        try:
            df = col.fetch(c, start, end)
        except CollectError as exc:
            log.warning("WAMIS %s 실패: %s", c, exc)
            continue
        if not df.empty:
            frames.append(df.rename(columns={"obscd": "station_code"})[["station_code", "obs_date", "wl"]])
    if not frames:
        return pd.DataFrame(columns=["station_code", "obs_date", "wl"])
    out = pd.concat(frames, ignore_index=True)
    out["station_code"] = out["station_code"].astype(str)
    out["source"] = "wamis_wl_dtdata"
    log.info("WAMIS 수위: 요청 %d회, 캐시 %d회", col.n_requests, col.n_cache_hits)
    return out


def offset_table(dataon: pd.DataFrame, wamis: pd.DataFrame, tol: float = 0.05) -> pd.DataFrame:
    """겹치는 구간(2020~2024) 관측소별 일치율·기준면 오프셋(중앙값 차, DataON − WAMIS)."""
    m = dataon.merge(wamis, on=["station_code", "obs_date"], suffixes=("_d", "_w"))
    rows = []
    for code, g in m.groupby("station_code"):
        diff = g["wl_d"] - g["wl_w"]
        med = float(diff.median())
        rows.append(
            {
                "code": code,
                "name": g["station_name"].iloc[0],
                "공통일": len(g),
                "일치율 %": round(100 * (diff.abs() <= tol).mean(), 1),
                "오프셋 m(중앙값)": round(med, 3),
                "MAD m": round(float((diff - med).abs().median()), 3),
                "보정 후 일치율 %": round(100 * ((diff - med).abs() <= tol).mean(), 1),
                "기준면 차이": "Y" if abs(med) > tol else "N",
            }
        )
    return pd.DataFrame(rows)


def continuous_series(
    dataon: pd.DataFrame, wamis: pd.DataFrame, offsets: pd.DataFrame, cutover: date
) -> pd.DataFrame:
    """DataON(≤cutover 전날) + WAMIS(≥cutover) 연속 시계열.

    wl_adj = WAMIS 값에 오프셋을 더해 DataON 기준면으로 정렬.
    """
    off = offsets.set_index("code")["오프셋 m(중앙값)"] if not offsets.empty else pd.Series(dtype=float)
    names = dataon.drop_duplicates("station_code").set_index("station_code")[["station_name", "dam_name"]]
    keep = ["station_code", "station_name", "dam_name", "obs_date", "wl", "source"]
    d = dataon[dataon["obs_date"] < cutover][keep].copy()
    d["offset_m"] = 0.0
    d["wl_adj"] = d["wl"]
    w = wamis[wamis["obs_date"] >= cutover].copy()
    w = w[w["station_code"].isin(names.index)]
    w["station_name"] = w["station_code"].map(names["station_name"])
    w["dam_name"] = w["station_code"].map(names["dam_name"])
    w["offset_m"] = w["station_code"].map(off).fillna(0.0)
    w["wl_adj"] = w["wl"] + w["offset_m"]
    cols = ["station_code", "station_name", "dam_name", "obs_date", "wl", "wl_adj", "offset_m", "source"]
    out = pd.concat([d[cols], w[cols]], ignore_index=True)
    return out.sort_values(["station_code", "obs_date"]).reset_index(drop=True)


def _md(t: pd.DataFrame) -> str:
    if t is None or t.empty:
        return "(없음)"
    hdr = "| " + " | ".join(map(str, t.columns)) + " |\n|" + "---|" * len(t.columns)
    body = "\n".join(
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in t.itertuples(index=False)
    )
    return hdr + "\n" + body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=DATAON_DIR)
    ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    long = load_all()
    if long is None:
        print("DataON 일평균수위 파일 없음 — data/raw/dataon/ 에 xlsx 를 두면 반영")
        return 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    long.to_parquet(OUT_PATH, index=False)
    sites_cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    cov = coverage_table(long, sites_cfg)
    cmp_t = compare_with_wamis(long)
    codes = site_station_codes(sites_cfg)
    wamis = fetch_wamis_levels(codes, date(2020, 1, 1), date.today())
    offsets = offset_table(long[long["station_code"].isin(codes)], wamis)
    bad = {
        str(e["code"])
        for s_ in sites_cfg["sites"]
        for e in s_.get("dataon_stations", [])
        if isinstance(e, dict) and e.get("wamis_ok") is False
    }
    cont = continuous_series(
        long[long["station_code"].isin(codes)], wamis[~wamis["station_code"].isin(bad)], offsets, CUTOVER
    )
    cont.to_parquet(CONT_PATH, index=False)
    n_w = int((cont["source"] == "wamis_wl_dtdata").sum())
    print(
        f"연속 시계열 {len(cont):,}행 (WAMIS {CUTOVER}~ {n_w:,}행, 최근 {cont['obs_date'].max()}) "
        f"→ {CONT_PATH.name}"
    )
    print(offsets.to_string(index=False))
    print(
        f"{len(long):,}행, 관측소 {long['station_code'].nunique()}개, "
        f"{long['obs_date'].min()}~{long['obs_date'].max()} → {OUT_PATH.name}"
    )
    print(cov.to_string(index=False))
    rep = ROOT / "reports" / "eda" / "dataon_level_coverage.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(
        "# DataON 댐유역 하천 일평균수위 — 지점 매핑·커버리지 (T1-d)\n\n"
        f"- 전체 {len(long):,}행, 관측소 {long['station_code'].nunique()}개, "
        f"{long['obs_date'].min()}~{long['obs_date'].max()}\n\n## 지점별 dataon_stations\n"
        + _md(cov)
        + "\n\n## (T1-b hydro long) 하굿둑 WAMIS 와 일치율 (|차| ≤ 0.05 m)\n"
        + _md(cmp_t)
        + "\n\n## DataON vs WAMIS wl_dtdata 겹침 구간(2020~2024) 일치율·기준면 오프셋 (DataON − WAMIS)\n"
        + _md(offsets)
        + f"\n\n- 연속 시계열: DataON ≤{CUTOVER - timedelta(days=1)}, WAMIS ≥{CUTOVER} (`{CONT_PATH.name}`, "
        + "`wl_adj` = WAMIS + 오프셋). 하굿둑 외측(2022697)은 조석 영향으로 `use: false`.\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
