"""대회 제공 데이터 번들(datas_participants.zip, 생성 2026-09-12) 로더 — T0-b.

docs/02_DATA_SPEC.md 9절 규약으로 표준화한다.
- 지점 단위 자료(조류경보제·채점조합): ``site_code``(조사지점코드) + ``station_id``(대회 약어) + ``obs_date``
- 시설 단위 자료(댐·ASOS): ``dam_code`` / ``stn_id`` + ``obs_date``
  (시설→지점 결합은 config/sites.yaml 매핑으로 align 단계에서 수행)
- 공통: ``source``, ``fetched_at`` 컬럼, 모든 수치는 float, 날짜는 ``datetime.date``

원본 CSV 는 git 에 커밋하지 않는다(대회 규정). 파일이 없으면 ``FileNotFoundError`` 와 안내 메시지를 낸다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from algaecast.config import RAW_DIR

COMPETITION_DIR: Path = RAW_DIR / "competition" / "algae_contest_2026"
BUNDLE_ZIP: Path = RAW_DIR / "competition" / "datas_participants.zip"
SOURCE = "competition_bundle"
FETCHED_AT = pd.Timestamp("2026-09-12 00:00", tz="Asia/Seoul")  # README '생성일 26. 9. 12.'

TARGET = "iem_bgalage_cell_co"
GENUS_COLS: dict[str, str] = {
    "iem_bgalage_microsts": "Microcystis",
    "iem_bgalage_anba": "Anabaena",
    "iem_bgalage_osrtria": "Oscillatoria",
    "iem_bgalage_apzo": "Aphanizomenon",
}
ALGAE_NUMERIC = ["iem_wtrtp", "iem_ph", "iem_doc", "iem_trp", "iem_tur", "iem_chla", TARGET, *GENUS_COLS]
ALGAE_LOQ = ["iem_geosm", "iem_mib2", "iem_microstlr"]  # '정량한계미만' 문자열이 섞임
ALGAE_TEXT = ["river_lkmh_se", "swmn_nm", "swmn_detail_nm", "detail_adres", "dominant_genus"]
DAM_NUMERIC = ["rwl", "iqty", "tdqty", "edqty", "spdqty", "otltdqty", "itqty", "rf"]
ASOS_RENAME: dict[str, str] = {
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
    "avgTd": "avg_td",
    "avgPs": "avg_ps",
    "avgTca": "avg_tca",
    "avgTs": "avg_ts",
}
DAMAPI_NUMERIC = [
    "zerosevenhourprcptqy",
    "prcptqy",
    "pyacurf",
    "vyacurf",
    "oyaacurf",
    "inflowqy",
    "totdcwtrqy",
    "totdcwtrqyjo",
    "nowlowlevel",
    "lastlowlevel",
    "nyearlowlevel",
    "nowrsvwtqy",
    "lastrsvwtqy",
    "nyearrsvwtqy",
    "rsvwtrt",
    "dvlpqyacmtlacmslt",
]
FILES = {
    "stations": "stations.csv",
    "algae": "algae_measure.csv",
    "dam_daily": "dam_daily.csv",
    "asos": "asos_daily.csv",
    "dam_operation_api": "dam_operation_api.csv",
    "eval_pairs": "eval_pairs.csv",
    "sample_submission": "sample_submission.csv",
}
BELOW_LOQ = "정량한계미만"
PENDING = "분석중"  # 최신 측정일(2026-09-10) 일부 항목에 등장, 아직 분석 결과 미입력
ALGAE_TOKENS = frozenset({BELOW_LOQ, PENDING})
ALGAE_PENDING_COLS = ["iem_chla", *ALGAE_LOQ]  # '분석중' 이 실제로 나타나는 컬럼


def _path(name: str) -> Path:
    p = COMPETITION_DIR / FILES[name]
    if not p.exists():
        msg = (
            f"대회 데이터 파일이 없습니다: {p}\n"
            f"{BUNDLE_ZIP.name} 을 data/raw/competition/ 에 두고 안쪽 zip 의 algae_contest_2026/ 를 "
            f"{COMPETITION_DIR} 로 풀어 주세요 (git 커밋 금지)."
        )
        raise FileNotFoundError(msg)
    return p


def _read(name: str) -> pd.DataFrame:
    """원본을 전부 문자열로 읽는다(빈칸은 ''). 수치 변환은 호출자가 명시적으로 한다."""
    return pd.read_csv(_path(name), encoding="utf-8-sig", dtype=str, keep_default_na=False)


def _num(s: pd.Series, *, allow: frozenset[str] = frozenset()) -> pd.Series:
    """천 단위 콤마·선행 소수점·빈칸을 처리해 float 로 바꾼다.

    빈칸과 ``allow`` 에 든 토큰(예: '정량한계미만', '분석중')만 NaN 으로 허용한다. 그 밖의 비수치
    문자열이 있으면 ValueError 를 내서, 새 토큰이 조용히 결측으로 사라지는 일을 막는다.
    """
    cleaned = s.astype(str).str.strip().str.replace(",", "", regex=False)
    out = pd.to_numeric(cleaned.where(cleaned != "", None), errors="coerce").astype("float64")
    bad = cleaned[(cleaned != "") & out.isna() & ~cleaned.isin(allow)]
    if len(bad):
        msg = f"{s.name}: 알 수 없는 비수치 값 {bad.value_counts().head(5).to_dict()}"
        raise ValueError(msg)
    return out


def _date(s: pd.Series) -> pd.Series:
    """YYYY-MM-DD 또는 YYYY.MM.DD 문자열을 datetime.date 로 바꾼다 (Asia/Seoul 달력 날짜, tz 없음)."""
    return pd.to_datetime(s.str.strip().str.replace(".", "-", regex=False), format="%Y-%m-%d").dt.date


def _stamp(df: pd.DataFrame) -> pd.DataFrame:
    df["source"] = SOURCE
    df["fetched_at"] = FETCHED_AT
    return df


def load_stations() -> pd.DataFrame:
    """지점 메타 5행: site_code(=swmn_code), station_id, basin, asos_stn_id, asos_alt_stn_id ..."""
    raw = _read("stations")
    alt = raw["asos_alt"].str.extract(r"^(\d+)")[0]
    df = pd.DataFrame(
        {
            "site_code": raw["swmn_code"],
            "station_id": raw["station_id"],
            "station_name": raw["station_name"],
            "water_body": raw["swmn_nm"],
            "river_lake": raw["river_lake"],
            "section": raw["section"],
            "basin": raw["suge"],
            "asos_stn_id": raw["asos_stn_id"].astype(int),
            "asos_stn_nm": raw["asos_stn_nm"],
            "asos_alt_stn_id": pd.to_numeric(alt, errors="coerce").astype("Int64"),
            "service_start": pd.to_numeric(raw["service_start"], errors="coerce").astype("Int64"),
            "note": raw["note"],
        }
    )
    return _stamp(df)


def load_algae() -> pd.DataFrame:
    """조류경보제 측정자료. 타깃은 ``iem_bgalage_cell_co`` (cells/mL). (site_code, obs_date) 유일."""
    raw = _read("algae")
    df = pd.DataFrame(
        {"site_code": raw["swmn_code"], "station_id": raw["station_id"], "obs_date": _date(raw["chck_de"])}
    )
    for c in ALGAE_NUMERIC:
        df[c] = _num(raw[c], allow=ALGAE_TOKENS)
    for c in ALGAE_LOQ:
        df[c] = _num(raw[c], allow=ALGAE_TOKENS)
        df[f"{c}_below_loq"] = raw[c].str.strip().eq(BELOW_LOQ)
    for c in ALGAE_PENDING_COLS:
        df[f"{c}_pending"] = raw[c].str.strip().eq(PENDING)
    for c in ALGAE_TEXT:
        df[c] = raw[c].where(raw[c] != "", None)
    oc = raw["over_caution"].where(raw["over_caution"] != "", None)
    df["over_caution"] = pd.to_numeric(oc, errors="coerce").astype("Int64")
    df = _stamp(df).sort_values(["site_code", "obs_date"], ignore_index=True)
    dup = int(df.duplicated(["site_code", "obs_date"]).sum())
    if dup:
        msg = f"algae_measure: (site_code, obs_date) 중복 {dup}건"
        raise ValueError(msg)
    return df


def load_dam_daily() -> pd.DataFrame:
    """WAMIS 기반 다목적댐 일자료 15개소. 키는 (dam_code, obs_date)."""
    raw = _read("dam_daily")
    df = pd.DataFrame(
        {
            "dam_code": raw["dam_code"],
            "dam_name": raw["dam_name"],
            "basin": raw["suge"],
            "obs_date": _date(raw["obs_date"]),
        }
    )
    for c in DAM_NUMERIC:
        df[c] = _num(raw[c])
    return _stamp(df).sort_values(["dam_code", "obs_date"], ignore_index=True)


def load_asos(*, rain_blank_as_zero: bool = True) -> pd.DataFrame:
    """ASOS 일자료 6개 지점. 키는 (stn_id, obs_date). 컬럼은 snake_case 로 변환.

    기상청 일자료는 무강수일의 ``sumRn``/``hr1MaxRn`` 을 빈칸으로 준다('0.0' 은 흔적 강수). 기본값으로
    **관측이 있었던 날**(기온 또는 습도 값 존재, ``day_observed``)에 한해 0 을 채우고, 관측소 결측일
    (예: 의령군 2023-03-20~23)은 NaN 으로 둔다. 원래 빈칸 여부는 ``rn_blank`` 에 남긴다.
    ``rain_blank_as_zero=False`` 면 모두 NaN 유지.
    """
    raw = _read("asos")
    df = pd.DataFrame(
        {"stn_id": raw["stnId"].astype(int), "stn_nm": raw["stnNm"], "obs_date": _date(raw["tm"])}
    )
    for src, dst in ASOS_RENAME.items():
        df[dst] = _num(raw[src])
    df["rn_blank"] = raw["sumRn"].str.strip().eq("")
    df["day_observed"] = raw["avgTa"].str.strip().ne("") | raw["avgRhm"].str.strip().ne("")
    if rain_blank_as_zero:
        fill = df["rn_blank"] & df["day_observed"]
        df.loc[fill, "sum_rn"] = 0.0
        df.loc[fill & raw["hr1MaxRn"].str.strip().eq(""), "hr1_max_rn"] = 0.0
    return _stamp(df).sort_values(["stn_id", "obs_date"], ignore_index=True)


def load_dam_operation_api() -> pd.DataFrame:
    """공공데이터포털 다목적댐 운영정보 API 스냅샷(2026 녹조 시즌, 보조). 키는 (dam_name, obs_date)."""
    raw = _read("dam_operation_api")
    df = pd.DataFrame({"dam_name": raw["damnm"], "basin": raw["suge"], "obs_date": _date(raw["obs_date"])})
    for c in DAMAPI_NUMERIC:
        df[c] = _num(raw[c])
    return _stamp(df).sort_values(["dam_name", "obs_date"], ignore_index=True)


def load_eval_pairs() -> pd.DataFrame:
    """채점 대상 (지점, 기준일, 정답측정일) 조합 + split(train/valid/test/excluded)."""
    raw = _read("eval_pairs")
    codes = load_stations().set_index("station_id")["site_code"]
    df = pd.DataFrame(
        {
            "site_code": raw["station_id"].map(codes),
            "station_id": raw["station_id"],
            "base_date": _date(raw["base_date"]),
            "target_date": _date(raw["target_date"]),
            "lag_days": raw["lag_days"].astype(int),
            "split": raw["split"],
        }
    )
    if df["site_code"].isna().any():
        msg = "eval_pairs: stations.csv 에 없는 station_id"
        raise ValueError(msg)
    return _stamp(df)


def load_sample_submission() -> pd.DataFrame:
    """제출 형식 예시(124행). 컬럼 순서·행 순서를 그대로 유지한다."""
    raw = _read("sample_submission")
    return pd.DataFrame(
        {
            "station_id": raw["station_id"],
            "base_date": _date(raw["base_date"]),
            "target_date": _date(raw["target_date"]),
            "pred_cells": pd.to_numeric(raw["pred_cells"], errors="coerce").astype("Int64"),
        }
    )


def load() -> dict[str, pd.DataFrame]:
    """번들 전체를 표준 컬럼명으로 반환한다."""
    return {
        "stations": load_stations(),
        "algae": load_algae(),
        "dam_daily": load_dam_daily(),
        "asos": load_asos(),
        "dam_operation_api": load_dam_operation_api(),
        "eval_pairs": load_eval_pairs(),
        "sample_submission": load_sample_submission(),
    }


def available() -> bool:
    """번들 CSV 가 모두 있으면 True (테스트 skip 판단용)."""
    return all((COMPETITION_DIR / f).exists() for f in FILES.values())
