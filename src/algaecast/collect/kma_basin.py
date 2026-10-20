"""MT-02/03 유역 단위 기상 CSV 파서 — T1-c.

수동 다운로드 파일을 읽는다 (API 가 시계열을 주지 않음, docs/02 MT-03 참조):
- ``data/raw/kma/수문기상정보/*.csv`` (기상청 수문기상정보 #15133499:
  표준유역·중권역 면적강수량, 토양수분, 증발산량)
- ``data/raw/kma/유역단위_면적강수량/*.csv`` (기상청 유역단위 기후 면적강수량 #15152903)
sites.yaml ``basin_mid_code``(수자원단위지도 중권역 코드 = 조사지점코드 앞 4자리) 로 지점에 결합할 수 있게
long 포맷 ``data/raw/kma_basin/kma_basin_daily_long.parquet`` 로 저장한다.
파일이 없으면 건너뛰고 로그만 남긴다.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from algaecast.collect.base import CollectError
from algaecast.config import RAW_DIR

log = logging.getLogger(__name__)

DIRS = {
    "hydromet": RAW_DIR / "kma" / "수문기상정보",
    "basin_rain": RAW_DIR / "kma" / "유역단위_면적강수량",
}
OUT_DIR = RAW_DIR / "kma_basin"
ALIASES = {  # CSV 헤더(공백 제거·소문자) → 표준 컬럼. 파일 수령 후 실제 헤더에 맞춰 보정한다.
    "일자": "obs_date",
    "날짜": "obs_date",
    "일시": "obs_date",
    "관측일": "obs_date",
    "기준일": "obs_date",
    "중권역코드": "basin_mid_code",
    "중권역": "basin_mid_name",
    "표준유역코드": "basin_std_code",
    "표준유역": "basin_std_name",
    "대권역코드": "basin_large_code",
    "대권역": "basin_large_name",
    "강수량": "area_rain",
    "강수량(mm)": "area_rain",
    "면적강수량": "area_rain",
    "면적강수량(mm)": "area_rain",
    "토양수분": "soil_moisture",
    "토양수분(%)": "soil_moisture",
    "증발산량": "evapotranspiration",
    "증발산량(mm)": "evapotranspiration",
    "증발산": "evapotranspiration",
}
VALUE_COLS = ["area_rain", "soil_moisture", "evapotranspiration"]
UNITS = {"area_rain": "mm", "soil_moisture": "%", "evapotranspiration": "mm"}
LONG_COLS = ["basin_mid_code", "basin_std_code", "obs_date", "variable", "value", "unit", "source"]


def _read_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            continue
    raise CollectError(f"{path.name}: 인코딩 판별 실패")


def parse_file(path: Path, source: str) -> pd.DataFrame:
    raw = _read_csv(path)
    ren = {c: ALIASES.get(str(c).strip().replace(" ", "").lower(), None) for c in raw.columns}
    df = raw.rename(columns={k: v for k, v in ren.items() if v})
    if "obs_date" not in df.columns or not ({"basin_mid_code", "basin_std_code"} & set(df.columns)):
        raise CollectError(
            f"{path.name}: 일자/중권역(표준유역) 코드 컬럼 매핑 실패 — 헤더={list(raw.columns)[:12]}"
        )
    df["obs_date"] = pd.to_datetime(
        df["obs_date"].str.replace(".", "-", regex=False), errors="coerce"
    ).dt.date
    present = [v for v in VALUE_COLS if v in df.columns]
    if not present:
        raise CollectError(
            f"{path.name}: 값 컬럼(강수량/토양수분/증발산) 없음 — 헤더={list(raw.columns)[:12]}"
        )
    for v in present:
        df[v] = pd.to_numeric(
            df[v].str.replace(",", "", regex=False).where(df[v] != "", None), errors="coerce"
        )
    for c in ("basin_mid_code", "basin_std_code"):
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].astype(str).str.strip()
    if (df["basin_mid_code"] == "").all() and "basin_std_code" in df.columns:
        df["basin_mid_code"] = df["basin_std_code"].str[:4]  # 표준유역 코드 앞 4자리 = 중권역
    long = df.melt(
        id_vars=["basin_mid_code", "basin_std_code", "obs_date"],
        value_vars=present,
        var_name="variable",
        value_name="value",
    )
    long = long.dropna(subset=["obs_date", "value"])
    long["unit"] = long["variable"].map(UNITS)
    long["source"] = f"{source}:{path.name}"
    return long[LONG_COLS]


def load_all(dirs: dict[str, Path] | None = None) -> pd.DataFrame | None:
    dirs = DIRS if dirs is None else dirs
    frames = []
    for source, d in dirs.items():
        files = sorted(d.glob("*.csv")) if d.exists() else []
        if not files:
            log.info("%s: CSV 없음 (%s) — 건너뜀", source, d)
            continue
        for f in files:
            frames.append(parse_file(f, source))
            log.info("%s/%s: %d rows", source, f.name, len(frames[-1]))
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        ["basin_mid_code", "basin_std_code", "obs_date", "variable", "source"]
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    long = load_all()
    if long is None:
        print(
            "유역 기상 CSV 없음 — data/raw/kma/수문기상정보/, data/raw/kma/유역단위_면적강수량/ 에 두면 반영"
        )
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    long.to_parquet(OUT_DIR / "kma_basin_daily_long.parquet", index=False)
    print(f"{len(long):,}행 → {OUT_DIR / 'kma_basin_daily_long.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
