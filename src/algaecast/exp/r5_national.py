# ruff: noqa: E501  (한국어 표·설명 문자열)
"""EXP-008(R5) 전국 조류경보 지점 통합 학습.

조류경보제 API 를 ``ptNoList`` 없이 받은 전 지점(82개, ``collect/nier_algae_all.py``) 중 우리 5지점을 뺀 지점의
일 단위 달력·피처를 v1 함수(``align.run.build_site_daily``·``apply_strategy`` S1, ``features.run.build_samples``)로
만들어 우리 5지점 v1 행(``features_S1`` 값 그대로, ``harness.load_base()``)과 합쳐 LightGBM(C1·C3·C2·분위, v1
파라미터)을 학습한다. 폴드는 기준일 연도(모든 지점이 valid 연도 미만만 학습), 평가는 우리 5지점 행만.

지점 메타(좌표·ASOS·수문) 결정 규칙
- 좌표: (1) 우리 5지점은 sites.yaml lat/lon, (2) 상세주소가 우리 지점과 같은 옛 지점(2013~2015 취수장 지점)과
  시범 지점은 ``COORD_REF`` 의 기준 지점 좌표, (3) 수질측정망(GeoJSON, ``data/raw/nier_wq``) 측정소 코드가 조사지점
  코드와 같으면 그 좌표, (4) 같은 중권역(코드 앞 4자리) 측정소 중 상세지점명 또는 수계명 앞 2글자가 측정소명에
  들어가는 측정소 좌표 평균, (5) 그 밖에는 같은 중권역 측정소 좌표 평균.
- ASOS: 기상청 지점정보(``collect/kma_stn_info.py``, 이력 중앙값 좌표) 기준 haversine 최근접 ASOS 중 그 지점 측정
  기간의 일평균기온 보유율 ≥ 90 % 인 첫 관측소. 변수 전부 같은 관측소(v1 의 일사 대체 규칙 없음).
- 수문: ``HYDRO_MAP`` 에 있는 지점만(낙동강 보·하굿둑 = 보 운영자료, 진양·용담·대청호 = 댐 운영자료, 상류 본댐
  목록·연속수위 관측소는 같은 구간의 우리 지점 설정을 따름). 그 밖은 결측이며 ``hydro_fac_available`` = 0 이 플래그.
- 수온 임계(``wtemp_minus_site_thresh``): 다른 지점은 v1 5지점 값의 중앙값 22.9 ℃.

2026 차단: 전 지점 원자료를 읽은 직후 obs_date ≤ 2025-12-31 만 남기고, 달력도 2025-12-31 에서 끝낸다. 학습 프레임은
``harness.guard_no_2026`` 을 통과한다.

공개 함수
- ``members(df, cols, *, variant=CHOSEN)`` → {c1, c1_none, c1_log, c3, c2, q10, q50, q90} OOF(df 행 순서, 2020~2025).
  df 는 ``harness.load_base()`` 형식(우리 5지점), cols 는 피처 열. 다른 지점 표본은
  ``data/processed/exp/EXP-008/other_samples.parquet`` 에서 읽고(없으면 만든다) df 에만 있는 열은 NaN 으로 채운다.
- ``pooled_cv(df_own, other, cols, ...)`` → 위와 같은 OOF(가중·임베딩 등 설정을 직접 줄 때).

사용: python -m algaecast.exp.r5_national [--step meta|samples|train|report|all] [--workers 4] [--variants a,b]
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import logging
import math
import re
import time
import zipfile
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest import mock

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

from algaecast.collect.kma_asos import KmaAsosCollector
from algaecast.collect.nier_algae import SITES as OWN_SITES
from algaecast.config import CONFIG_DIR, RAW_DIR
from algaecast.exp import harness as H
from algaecast.models import data as D
from algaecast.models.quantile import QUANTILES
from algaecast.models.train import HURDLE_THRESHOLD, SEED, VariantSpec, _lgb_params, _prep, to_cells

log = logging.getLogger(__name__)

EXP = "EXP-008"
OUT_DATA = H.EXP_DATA / EXP
OUT_REP = H.EXP_REPORTS / EXP
ALGAE_ALL = RAW_DIR / "nier_algae_all" / "nier_algae_all_2012_2026.parquet"
ASOS_STN = RAW_DIR / "kma_stn_info" / "asos_stations.csv"
ASOS_ALL_DIR = RAW_DIR / "kma_asos_all"
ASOS_ALL = ASOS_ALL_DIR / "kma_asos_all_daily_2012_2025.parquet"
WQ_ZIP = RAW_DIR / "nier_wq" / "기후에너지환경부_물환경 수질측정망 정보(JSON)_20251231.zip"
META_PATH = OUT_DATA / "sites_meta.csv"
SAMPLES_PATH = OUT_DATA / "other_samples.parquet"
CAL_START = date(2012, 1, 1)
CAL_END = date(2025, 12, 31)
OWN_IDS = set(OWN_SITES.values())
ASOS_MIN_COVERAGE = 0.9
STARTED = "2026-10-21 17:53:26"  # 실험 시작(KST) — 시간 상한 12h 기준
DEFAULT_WTEMP_THRESH = 22.9  # v1 5지점 site_caution_wtemp 중앙값

BASIN2 = {
    "10": "한강", "11": "안성천", "12": "한강서해", "13": "한강동해",
    "20": "낙동강", "21": "형산강", "22": "태화강", "23": "회야수영", "24": "낙동강동해", "25": "낙동강남해",
    "30": "금강", "31": "삽교천", "32": "금강서해", "33": "만경동진",
    "40": "섬진강", "41": "섬진강남해", "50": "영산강", "51": "탐진강", "52": "영산강남해", "53": "영산강서해",
}  # fmt: skip
PILOT_BASIN = {"5555": "금강", "6666": "낙동강", "7777": "낙동강", "9999": "낙동강"}

# 좌표 기준 지점(옛 지점·시범 지점 → 우리 지점 또는 다른 지점 코드). 근거는 보고서 2절.
COORD_REF: dict[str, str] = {
    "2011A26": "HP",  # 구미광역취수장(칠곡보 상류 22 km) = 해평 옛 지점
    "2011A56": "GJGR",  # 고령광역취수장(강정고령보 상류 7 km) = 강정·고령 옛 지점
    "2020A33": "CS",  # 창원칠서취수장(창녕함안보 상류 12 km) = 칠서 옛 지점
    "2011A55": "GJGR",  # 강정고령보 상류 500 m(우리 지점과 약 7 km)
    "2020A32": "CS",  # 창녕함안보 상류 300 m(우리 지점과 약 12 km)
    "7777A76": "MGMR", "7777A77": "MGMR",  # 매리 지점(시범, 혼합·표층)
    "9999A98": "GJGR", "9999A99": "GJGR",  # 고령 지점(시범, 혼합·표층)
    "6666A55": "HP",  # 구미낙동강레포츠체험센터(구미시)
    "6666A66": "GJGR",  # 레포츠밸리(보 상류 12 km, 위치 불확실 → 대구권 근사)
    "6666A77": "CS",  # 본포수변생태공원(창원 본포, 칠서 하류)
    "6666A88": "MGMR",  # 화명수상레포츠타운(부산 화명, 물금 하류)
    "5555A44": "DCHN",  # 서화천(옥천, 대청호 상류)
    "5555A55": "3012A42",  # 웅포대교(금강 하류) → 백제보 좌표
    "1011G50": "1010G60",  # 의암호 신연교(춘천): 중권역 1011 측정소 4곳이 인제 쪽이라 춘천호 춘성교 좌표로 대체
}  # fmt: skip

# 수문 연결(가용 지점만). kw = 보 K-water 코드, dam = 댐 코드, ref = 상류 본댐·연속수위 설정을 빌려 올 우리 지점,
# dams = 상류 본댐 목록 직접 지정.
_HP_UP = ["2001110", "2002110", "2002111", "2004101"]
HYDRO_MAP: dict[str, dict] = {
    "2007A25": {"kw": "2007601", "dams": _HP_UP},  # 상주보
    "2009A05": {"kw": "2009601", "dams": [*_HP_UP, "2008110"]},  # 낙단보
    "2009A30": {"kw": "2009602", "dams": [*_HP_UP, "2008110"]},  # 구미보
    "2011A25": {"kw": "2011601", "ref": "HP"},  # 칠곡보
    "2011A26": {"kw": "2011601", "ref": "HP"},
    "6666A55": {"kw": "2009602", "dams": [*_HP_UP, "2008110"]},
    "2011A55": {"kw": "2011602", "ref": "GJGR"},  # 강정고령보
    "2011A56": {"kw": "2011602", "ref": "GJGR"},
    "9999A98": {"kw": "2011602", "ref": "GJGR"},
    "9999A99": {"kw": "2011602", "ref": "GJGR"},
    "2014A25": {"kw": "2014601", "dams_ref": "GJGR"},  # 달성보
    "2014A70": {"kw": "2014602", "dams_ref": "GJGR"},  # 합천창녕보
    "2020A32": {"kw": "2017601", "ref": "CS"},  # 창녕함안보
    "2020A33": {"kw": "2017601", "ref": "CS"},
    "6666A77": {"kw": "2017601", "dams_ref": "CS"},
    "7777A76": {"kw": "2022510", "ref": "MGMR"},  # 낙동강하굿둑
    "7777A77": {"kw": "2022510", "ref": "MGMR"},
    "6666A88": {"kw": "2022510", "dams_ref": "MGMR"},
    "2018G20": {"dam": "2018110"},  # 진양호 = 남강댐
    "2018G30": {"dam": "2018110"},
    "3001G20": {"dam": "3001110"},  # 용담호
    "3001G40": {"dam": "3001110"},
    "3008G40": {"dam": "3008110", "ref": "DCHN"},  # 대청호 추동·문의
    "3008G50": {"dam": "3008110", "ref": "DCHN"},
    "5555A44": {"dams_ref": "DCHN"},
    "3012A07": {"dams": ["3001110", "3008110"]},  # 세종보(보 운영자료 없음, 상류 본댐만)
    "3012A32": {"dams": ["3001110", "3008110"]},  # 공주보
    "3012A42": {"dams": ["3001110", "3008110"]},  # 백제보
    "5555A55": {"dams": ["3001110", "3008110"]},
}


# ================================================================ 1. 지점 메타
def haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(np.asarray(lat2, dtype=float))
    dphi = p2 - p1
    dl = np.radians(np.asarray(lon2, dtype=float) - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def sites_yaml() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))


def own_site(station_id: str) -> dict:
    for s in sites_yaml()["sites"]:
        if s["station_id"] == station_id:
            return s
    raise KeyError(station_id)


def load_wq_stations(path: Path = WQ_ZIP) -> pd.DataFrame:
    """수질측정망 월별 GeoJSON(2016~2025, 압축 안 압축)을 메모리에서 읽어 측정소 코드·이름·좌표(최근값)."""
    rows = []
    z = zipfile.ZipFile(path)
    for inner in sorted(n for n in z.namelist() if n.endswith(".zip")):
        z2 = zipfile.ZipFile(io.BytesIO(z.read(inner)), metadata_encoding="cp949")
        for n in sorted(z2.namelist()):
            if not n.endswith(".geojson"):
                continue
            js = json.loads(z2.read(n).decode("utf-8"))
            for ft in js["features"]:
                pr = ft["properties"]
                rows.append(
                    {
                        "ptno": str(pr["PTNO"]),
                        "ptnm": re.sub(r"\s*\(\d{4}\)", "", re.sub(r"<[^>]+>", "", str(pr["PTNM"]))).strip(),
                        "lon": float(pr["X"]),
                        "lat": float(pr["Y"]),
                    }
                )
    wq = pd.DataFrame(rows)
    return wq.drop_duplicates("ptno", keep="last").reset_index(drop=True)


def _coord_from_wq(row: pd.Series, wq: pd.DataFrame) -> tuple[float, float, str, str]:
    code = row["site_code"]
    hit = wq[wq["ptno"] == code]
    if len(hit):
        return float(hit["lat"].iloc[0]), float(hit["lon"].iloc[0]), "수질측정망 동일 코드", code
    same = wq[wq["ptno"].str[:4] == code[:4]]
    if same.empty:
        return math.nan, math.nan, "좌표 없음", ""
    detail = str(row.get("swmn_detail_nm") or "").strip()
    if detail:
        h = same[same["ptnm"] == detail]
        if len(h):
            return (
                float(h["lat"].mean()),
                float(h["lon"].mean()),
                "중권역 측정소명=상세지점명",
                ",".join(h["ptno"]),
            )
    nm = str(row.get("swmn_nm") or "").strip()[:2]
    if nm:
        h = same[same["ptnm"].str.contains(nm, regex=False)]
        if len(h):
            return (
                float(h["lat"].mean()),
                float(h["lon"].mean()),
                "중권역 측정소명⊃수계명 앞 2글자",
                ",".join(h["ptno"]),
            )
    return (
        float(same["lat"].mean()),
        float(same["lon"].mean()),
        "중권역 측정소 평균",
        f"{code[:4]}*({len(same)})",
    )


def site_coordinates(sites: pd.DataFrame, wq: pd.DataFrame) -> pd.DataFrame:
    """지점별 (lat, lon, coord_method, coord_ref). 규칙은 모듈 설명 참조."""
    out = {}
    own_addr = {}
    for code, sid in OWN_SITES.items():
        s = own_site(sid)
        out[code] = (float(s["lat"]), float(s["lon"]), "sites.yaml(우리 지점)", sid)
        a = sites.loc[sites["site_code"] == code, "detail_adres"]
        if len(a):
            own_addr[str(a.iloc[0])] = code
    pending = []
    for _, r in sites.iterrows():
        code = r["site_code"]
        if code in out:
            continue
        ref = COORD_REF.get(code)
        if ref is None and str(r["detail_adres"]) in own_addr:
            ref = OWN_SITES[own_addr[str(r["detail_adres"])]]
        if ref is not None:
            pending.append((code, ref))
            continue
        out[code] = _coord_from_wq(r, wq)
    for code, ref in pending:
        if ref in OWN_IDS:
            s = own_site(ref)
            out[code] = (float(s["lat"]), float(s["lon"]), "기준 지점 좌표(COORD_REF)", ref)
        else:
            lat, lon = out[ref][:2]
            out[code] = (lat, lon, "기준 지점 좌표(COORD_REF)", ref)
    return pd.DataFrame(
        [
            {"site_code": k, "lat": v[0], "lon": v[1], "coord_method": v[2], "coord_ref": v[3]}
            for k, v in out.items()
        ]
    )


def asos_coverage(asos: pd.DataFrame, stn: int, start: date, end: date = CAL_END) -> float:
    a = asos[(asos["stn_id"] == stn)]
    d = pd.to_datetime(a["obs_date"])
    m = (d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))
    n_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    return float(a.loc[m, "avg_ta"].notna().sum()) / n_days if n_days > 0 else 0.0


def collect_asos(stns: list[int], have: pd.DataFrame | None = None) -> pd.DataFrame:
    """ASOS 일자료(2012~2025)를 관측소별로 받아 합친다(캐시 사용, 원자료는 data/raw/kma_asos_all/)."""
    col = KmaAsosCollector(out_dir=ASOS_ALL_DIR)
    frames = [] if have is None else [have]
    done = set() if have is None else set(have["stn_id"].unique())
    for s in stns:
        if s in done:
            continue
        try:
            df = col.fetch(str(s), CAL_START, CAL_END)
        except Exception as exc:  # noqa: BLE001 — 관측소 하나 실패는 다음 후보로 넘긴다
            log.warning("ASOS %s 수집 실패: %s", s, exc)
            df = pd.DataFrame({"stn_id": [s], "obs_date": [CAL_START], "avg_ta": [np.nan]})
        frames.append(df)
        done.add(s)
        log.info("ASOS %s: %d행 (요청 %d, 캐시 %d)", s, len(df), col.n_requests, col.n_cache_hits)
    out = pd.concat(frames, ignore_index=True)
    out["obs_date"] = pd.to_datetime(out["obs_date"]).dt.date
    return out


def basin_of(code: str) -> str:
    return PILOT_BASIN.get(code[:4]) or BASIN2.get(code[:2], "기타")


def facility_type_of(row: pd.Series) -> str:
    code = row["site_code"]
    hm = HYDRO_MAP.get(code, {})
    if hm.get("kw") == "2022510":
        return "하굿둑 상류"
    if hm.get("kw") or str(row["swmn_nm"]).endswith("보"):
        return "보"
    if str(row["river_lkmh_se"]) == "호소":
        return "댐"
    return "하천"


def build_meta(*, refresh_asos: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """지점 메타(좌표·ASOS·수문·범주)와 그에 쓰인 ASOS 일자료를 만든다. → (meta, asos)"""
    sites = pd.read_csv(RAW_DIR / "nier_algae_all" / "sites_all.csv", dtype={"site_code": str})
    wq = load_wq_stations()
    coords = site_coordinates(sites, wq)
    st = pd.read_csv(ASOS_STN)
    meta = sites.merge(coords, on="site_code", how="left")
    have = pd.read_parquet(ASOS_ALL) if ASOS_ALL.exists() and not refresh_asos else None
    asos = have
    rows = []
    for _, r in meta.iterrows():
        code = r["site_code"]
        if code in OWN_SITES:
            rows.append({"site_code": code, "asos_stn": int(own_site(OWN_SITES[code])["asos_primary"])})
            continue
        d = haversine_km(r["lat"], r["lon"], st["lat"].to_numpy(), st["lon"].to_numpy())
        order = np.argsort(d)
        start = max(CAL_START, pd.Timestamp(r["first_obs"]).date())
        chosen = None
        for k in order[:6]:
            stn = int(st["stn_id"].iloc[k])
            if asos is None or stn not in set(asos["stn_id"].unique()):
                asos = collect_asos([stn], asos)
            cov = asos_coverage(asos, stn, start)
            if cov >= ASOS_MIN_COVERAGE:
                chosen = (
                    stn,
                    str(st["stn_nm"].iloc[k]),
                    float(d[k]),
                    cov,
                    int(np.where(order == k)[0][0]) + 1,
                )
                break
        if chosen is None:
            raise RuntimeError(f"{code}: 보유율 {ASOS_MIN_COVERAGE} 이상인 ASOS 없음(가까운 6곳)")
        rows.append(
            {
                "site_code": code,
                "asos_stn": chosen[0],
                "asos_nm": chosen[1],
                "asos_km": round(chosen[2], 1),
                "asos_coverage": round(chosen[3], 3),
                "asos_rank": chosen[4],
            }
        )
    meta = meta.merge(pd.DataFrame(rows), on="site_code", how="left")
    meta["basin"] = meta["site_code"].map(basin_of)
    meta["facility_type"] = meta.apply(facility_type_of, axis=1)
    meta["hydro"] = meta["site_code"].map(lambda c: json.dumps(HYDRO_MAP.get(c, {}), ensure_ascii=False))
    meta["is_own"] = meta["site_code"].isin(list(OWN_SITES))
    assert asos is not None
    used = sorted(set(meta.loc[~meta["is_own"], "asos_stn"].astype(int)))
    asos = asos[asos["stn_id"].isin(used)].copy()
    ASOS_ALL_DIR.mkdir(parents=True, exist_ok=True)
    asos.to_parquet(ASOS_ALL, index=False)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    meta.to_csv(META_PATH, index=False, encoding="utf-8-sig", lineterminator="\n")
    return meta, asos


# ================================================================ 2. 일 달력·피처
def pseudo_site(r: pd.Series) -> dict:
    """다른 지점 → v1 피처 함수가 읽는 sites.yaml 형식의 지점 dict."""
    code = r["site_code"]
    hm = HYDRO_MAP.get(code, {})
    s: dict = {
        "site_code": code,
        "station_id": code,
        "name": f"{r['swmn_nm']} {r['swmn_detail_nm']}",
        "basin": r["basin"],
        "facility_type": r["facility_type"],
        "asos_primary": int(r["asos_stn"]),
        "asos_by_var": {
            "ta": "primary",
            "rn": "primary",
            "ws": "primary",
            "hm": "primary",
            "ss": "primary",
            "si": "primary",
        },
        "upstream_dams": [],
        "dataon_stations": [],
        "intake_capacity_tpd": None,
        "intake_weight": None,
    }
    if hm.get("kw"):
        s["facility_kwater_code"] = hm["kw"]
    if hm.get("dam"):
        s["facility_dam_code"] = hm["dam"]
    ref = hm.get("ref")
    if ref:
        o = own_site(ref)
        s["upstream_dams"] = list(o.get("upstream_dams", []))
        s["dataon_stations"] = list(o.get("dataon_stations", []))
    if hm.get("dams_ref"):
        s["upstream_dams"] = list(own_site(hm["dams_ref"]).get("upstream_dams", []))
    if hm.get("dams"):
        s["upstream_dams"] = list(hm["dams"])
    return s


@contextmanager
def pseudo_sites(extra: dict[str, dict]) -> Iterator[None]:
    """v1 피처 함수의 ``site_by_code``·수온 임계 조회에 다른 지점 dict 를 보탠다(파일은 건드리지 않음)."""
    from algaecast.features import base as fb
    from algaecast.features import hydro as fh
    from algaecast.features import time_site as ft
    from algaecast.features import water as fw

    orig = fb.site_by_code

    def sbc(code: str) -> dict:
        return extra[code] if code in extra else orig(code)

    cfg = copy.deepcopy(fb.feature_cfg())
    for s in extra.values():
        cfg["site_caution_wtemp"].setdefault(s["station_id"], DEFAULT_WTEMP_THRESH)
    with (
        mock.patch.object(fw, "site_by_code", sbc),
        mock.patch.object(fh, "site_by_code", sbc),
        mock.patch.object(ft, "site_by_code", sbc),
        mock.patch.object(fw, "feature_cfg", lambda: cfg),
    ):
        yield


def load_algae_all(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """전 지점 원자료를 읽은 즉시 obs_date ≤ 2025-12-31 만 남긴다."""
    a = pd.read_parquet(ALGAE_ALL)
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    return a[a["obs_date"] <= last].reset_index(drop=True)


def site_daily(site: dict, src: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """v1 align(build_site_daily → apply_strategy S1) 으로 2012-01-01~2025-12-31 일 달력."""
    from algaecast.align.run import apply_strategy, build_site_daily, load_cfg

    sites_cfg, feat_cfg = load_cfg()
    base = build_site_daily(site, src, sites_cfg, feat_cfg, CAL_END, start=CAL_START)
    d = apply_strategy(base, "S1", feat_cfg)
    d["obs_date"] = pd.to_datetime(d["obs_date"])
    return d


def site_samples(daily: pd.DataFrame, site: dict, extra: dict[str, dict]) -> pd.DataFrame:
    """v1 ``features.run.build_samples`` 로 (지점, 측정일) 표본·타깃을 만든다(타깃 없는 행 제외)."""
    from algaecast.features.base import feature_cfg
    from algaecast.features.run import build_samples

    with pseudo_sites(extra):
        s = build_samples(daily, site, feature_cfg())
    return s[s["target_log"].notna()].reset_index(drop=True)


def _worker(args: tuple[pd.DataFrame, dict, dict[str, dict]]) -> pd.DataFrame:
    daily, site, extra = args
    t0 = time.time()
    out = site_samples(daily, site, extra)
    log.info("%s 표본 %d (%.0fs)", site["site_code"], len(out), time.time() - t0)
    return out


def build_other_samples(meta: pd.DataFrame, *, workers: int = 4) -> pd.DataFrame:
    """우리 5지점을 뺀 지점의 표본(v1 피처 전부 + 메타). → other_samples.parquet"""
    from algaecast.align.run import load_sources

    src = load_sources()
    src.pop("forecast", None)
    src["algae"] = load_algae_all()
    asos = pd.read_parquet(ASOS_ALL)
    asos["obs_date"] = pd.to_datetime(asos["obs_date"])
    src["asos"] = asos
    others = meta[~meta["is_own"]]
    extra = {r["site_code"]: pseudo_site(r) for _, r in others.iterrows()}
    jobs = [(site_daily(extra[c], src), extra[c], extra) for c in extra]
    log.info("일 달력 %d개 완료 → 표본 생성(workers=%d)", len(jobs), workers)
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(_worker, jobs))
    else:
        parts = [_worker(j) for j in jobs]
    out = pd.concat([p for p in parts if len(p)], ignore_index=True)
    out = out[pd.to_datetime(out["base_date"]) <= H.LAST_DATE]
    out = out[pd.to_datetime(out["target_date"]) <= H.LAST_DATE].reset_index(drop=True)
    H.guard_no_2026(out)
    m = meta.set_index("site_code")
    out["river_lkmh_se"] = out["site_code"].map(m["river_lkmh_se"])
    out["asos_stn"] = out["site_code"].map(m["asos_stn"])
    for c in D.CAT_COLS:
        if c in out:
            out[c] = out[c].astype(str)
    out.to_parquet(SAMPLES_PATH, index=False)
    return out


def load_other_samples() -> pd.DataFrame:
    o = pd.read_parquet(SAMPLES_PATH)
    H.guard_no_2026(o)
    return o


# ================================================================ 3. 통합 학습
@dataclass(frozen=True)
class Variant:
    label: str
    embed: bool = True  # station_id 범주형(지점 임베딩)
    w_own: float = 1.0  # 우리 5지점 행 가중(다른 지점 = 1)
    subset: str = "all"  # all | nakgeum(낙동강·금강 권역) | river(하천) | none(우리 5지점만)
    flag: bool = True  # hydro_fac_available(수문 결측 플래그) 포함
    smear_scope: str = "own"  # C1 smearing 계수를 우리 지점 학습 행(own) / 전체(all)로
    site_hist: bool = False  # 수치 지점 임베딩: 지난해까지 측정 이력(평균 log 세포수·10k 초과 비율·측정 수)
    prior: bool = (
        False  # 전이: 다른 지점만으로 학습한 C1 log 예측을 피처(pooled_prior)로, 구성원은 우리 지점만 학습
    )


VARIANTS: dict[str, Variant] = {
    "own_only": Variant("우리 5지점만(재현 점검)", embed=False, subset="none", flag=False, smear_scope="all"),
    "all_embed": Variant("전 지점+지점 임베딩"),
    "all_noembed": Variant("전 지점, 임베딩 없음", embed=False),
    "all_embed_w5": Variant("전 지점+임베딩, 우리 지점 가중×5", w_own=5.0),
    "all_embed_w20": Variant("전 지점+임베딩, 우리 지점 가중×20", w_own=20.0),
    "nakgeum_embed": Variant("낙동강·금강 권역+임베딩", subset="nakgeum"),
    "river_embed": Variant("하천 지점만+임베딩", subset="river"),
    # 2차(1차 결과를 보고 추가 — 선택은 같은 CV 규칙)
    "all_noembed_w5": Variant("전 지점, 임베딩 없음, 우리 지점 가중×5", embed=False, w_own=5.0),
    "all_embed_w10": Variant("전 지점+임베딩, 우리 지점 가중×10", w_own=10.0),
    "all_hist": Variant("전 지점+지점 이력(수치 임베딩)", embed=False, site_hist=True),
    "all_hist_w5": Variant("전 지점+지점 이력, 우리 지점 가중×5", embed=False, site_hist=True, w_own=5.0),
    "prior_own": Variant("다른 지점 모델 예측을 피처로(우리 지점만 학습)", embed=False, prior=True),
    # 3차(임베딩 없음 × 가중·부분집합 격자 마무리)
    "all_noembed_w10": Variant("전 지점, 임베딩 없음, 우리 지점 가중×10", embed=False, w_own=10.0),
    "all_noembed_w20": Variant("전 지점, 임베딩 없음, 우리 지점 가중×20", embed=False, w_own=20.0),
    "nakgeum_noembed_w5": Variant(
        "낙동강·금강 권역, 임베딩 없음, 가중×5", embed=False, w_own=5.0, subset="nakgeum"
    ),
    "river_noembed_w5": Variant("하천 지점만, 임베딩 없음, 가중×5", embed=False, w_own=5.0, subset="river"),
}
SITE_HIST_COLS = ["site_hist_mean_log", "site_hist_frac10k", "site_hist_n"]
PRIOR_COL = "pooled_prior"
CHOSEN = "all_noembed_w5"  # EXP-PLAN 4절 규칙(CV r2_raw 최대, 기준 미달)으로 고른 변형 — members() 기본값


def subset_mask(other: pd.DataFrame, subset: str) -> np.ndarray:
    code = other["site_code"].astype(str)
    if subset == "all":
        return np.ones(len(other), dtype=bool)
    if subset == "none":
        return np.zeros(len(other), dtype=bool)
    if subset == "nakgeum":
        return code.str[:2].isin(["20", "30"]).to_numpy() | code.str[:4].isin(list(PILOT_BASIN)).to_numpy()
    if subset == "river":
        return (other["river_lkmh_se"].astype(str) == "하천").to_numpy()
    raise ValueError(subset)


def variant_cols(cols: list[str], v: Variant) -> list[str]:
    drop = {"station_id", "hydro_fac_available", PRIOR_COL, *SITE_HIST_COLS}
    out = [c for c in cols if c not in drop]
    if v.flag:
        out.append("hydro_fac_available")
    if v.site_hist:
        out += SITE_HIST_COLS
    if v.prior:
        out.append(PRIOR_COL)
    if v.embed:
        out.append("station_id")
    return out


def site_history_features(algae: pd.DataFrame, station_id: str, year: int) -> dict[str, float]:
    """지점 이력(수치 임베딩): 기준 연도 1월 1일 **이전** 측정만 — 평균 log10(세포수+1), 10,000 이상 비율, 측정 수.

    base_date 는 그 해 1월 1일 이후이므로 as_of 규칙을 만족한다(``cut_as_of`` 를 year−1 년 12월 31일로 적용).
    """
    from algaecast.features.base import cut_as_of

    a = algae[algae["station_id"].astype(str) == station_id]
    a = cut_as_of(a, date(year - 1, 12, 31))
    c = a["iem_bgalage_cell_co"].astype(float).dropna()
    if c.empty:
        return {"site_hist_mean_log": math.nan, "site_hist_frac10k": math.nan, "site_hist_n": 0.0}
    return {
        "site_hist_mean_log": float(np.log10(c + 1).mean()),
        "site_hist_frac10k": float((c >= H.T10K).mean()),
        "site_hist_n": float(len(c)),
    }


def site_history_table(algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """(station_id, year) → 지점 이력 피처. 원자료는 2025-12-31 까지만(load_algae_all)."""
    algae = load_algae_all() if algae is None else algae
    rows = []
    for s in sorted(algae["station_id"].astype(str).unique()):
        for y in range(CAL_START.year, H.FINAL_YEAR + 1):
            rows.append({"station_id": s, "year": y, **site_history_features(algae, s, y)})
    return pd.DataFrame(rows)


def add_site_history(comb: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    key = pd.DataFrame({"station_id": comb["station_id"].astype(str), "year": comb["base_date"].dt.year})
    m = key.merge(table, on=["station_id", "year"], how="left")
    out = comb.copy()
    for c in SITE_HIST_COLS:
        out[c] = m[c].to_numpy()
    return out


def fit_prior(oth: pd.DataFrame, target: pd.DataFrame, cols: list[str], spec: VariantSpec) -> np.ndarray:
    """다른 지점 행만으로 v1 C1(log 가중 회귀)을 학습해 target 행의 log10 예측을 낸다."""
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(oth[cols], cats)
    Xp = _prep(target[cols], cats, ref=Xt)
    y = oth["target_log"].to_numpy(dtype=float)
    m = lgb.LGBMRegressor(**_lgb_params(spec.params, SEED, objective="regression"))
    _fit(m, Xt, y, 1.0 + spec.alpha * y, cats)
    return np.asarray(m.predict(Xp), dtype=float)


def combine(df_own: pd.DataFrame, other: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    """우리 5지점 행(앞) + 다른 지점 행(뒤). 범주 열은 문자열로 통일, 없는 열은 NaN."""
    need = list(dict.fromkeys([*cols, "station_id", "site_code", "base_date", "target_cells", "target_log"]))
    a = df_own[need].copy()
    b = other.reindex(columns=need).copy()
    for c in D.CAT_COLS:
        if c in need:
            a[c] = a[c].astype(str)
            b[c] = b[c].astype(str)
    a["base_date"] = pd.to_datetime(a["base_date"])
    b["base_date"] = pd.to_datetime(b["base_date"])
    out = pd.concat([a, b], ignore_index=True) if len(b) else a.reset_index(drop=True)
    H.guard_no_2026(out)
    own = np.zeros(len(out), dtype=bool)
    own[: len(a)] = True
    return out, own


def fold_plan(years: np.ndarray, own: np.ndarray) -> list[tuple[str, int, np.ndarray, np.ndarray]]:
    """(이름, valid 연도, 학습 행 mask, 평가 행 mask). 학습 = 모든 지점의 기준일 연도 < valid 연도,
    평가 = 우리 지점의 valid 연도 행. v1 year_folds 와 같은 경계(Final: ≤2024 → 2025)."""
    plan = []
    for i, vy in enumerate((*H.CV_YEARS, H.FINAL_YEAR)):
        name = f"F{i + 1}" if vy != H.FINAL_YEAR else "Final"
        tr = years < vy
        va = own & (years == vy)
        if tr.any() and va.any():
            plan.append((name, vy, tr, va))
    return plan


def _fit(model: lgb.LGBMModel, X: pd.DataFrame, y: np.ndarray, w: np.ndarray | None, cats: list[str]) -> None:
    model.fit(X, y, sample_weight=w, categorical_feature=cats or "auto")


def fold_members(
    tr: pd.DataFrame,
    va: pd.DataFrame,
    cols: list[str],
    specs: dict[str, VariantSpec],
    sw: np.ndarray | None,
    own_tr: np.ndarray,
    *,
    smear_scope: str = "own",
    quantiles: bool = True,
    seed: int = SEED,
) -> dict[str, np.ndarray]:
    """한 폴드: v1 fit_predict(C1 log_w·C3 hurdle·C2 tweedie)·fit_quantiles 와 같은 식 + 표본 가중 sw."""
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    Xv = _prep(va[cols], cats, ref=Xt)
    ylog = tr["target_log"].to_numpy(dtype=float)
    yraw = tr["target_cells"].to_numpy(dtype=float)
    out: dict[str, np.ndarray] = {}
    # C1
    s1 = specs["c1"]
    w = 1.0 + s1.alpha * ylog
    if sw is not None:
        w = w * sw
    m = lgb.LGBMRegressor(**_lgb_params(s1.params, seed, objective="regression"))
    _fit(m, Xt, ylog, w, cats)
    lp = np.asarray(m.predict(Xv), dtype=float)
    resid = ylog - m.predict(Xt)
    scope = own_tr if smear_scope == "own" and own_tr.any() else np.ones(len(tr), dtype=bool)
    smear = float(np.mean(10 ** resid[scope]))
    raw = to_cells(lp)
    out["c1_none"] = np.clip(np.nan_to_num(raw, nan=0.0), 0, None)
    out["c1"] = np.clip(np.nan_to_num(raw * smear if smear else raw, nan=0.0), 0, None)
    out["c1_log"] = lp
    # C3 hurdle
    s3 = specs["c3"]
    over = (yraw > HURDLE_THRESHOLD).astype(int)
    clf = lgb.LGBMClassifier(**_lgb_params(s3.cls_params, seed, objective="binary"))
    _fit(clf, Xt, over, sw, cats)
    p = np.asarray(clf.predict_proba(Xv)[:, 1], dtype=float)
    hi = over == 1
    reg_hi = lgb.LGBMRegressor(**_lgb_params(s3.params, seed, objective="regression"))
    _fit(reg_hi, Xt[hi], ylog[hi], None if sw is None else sw[hi], cats)
    reg_lo = lgb.LGBMRegressor(**_lgb_params(s3.params, seed, objective="regression"))
    _fit(reg_lo, Xt[~hi], ylog[~hi], None if sw is None else sw[~hi], cats)
    e_hi = to_cells(np.asarray(reg_hi.predict(Xv), dtype=float))
    e_lo = to_cells(np.asarray(reg_lo.predict(Xv), dtype=float))
    out["c3"] = np.clip(np.nan_to_num(p * e_hi + (1 - p) * e_lo, nan=0.0), 0, None)
    # C2 tweedie
    s2 = specs["c2"]
    extra: dict = {"objective": s2.objective_raw}
    if s2.objective_raw == "tweedie":
        extra["tweedie_variance_power"] = s2.variance_power
    m2 = lgb.LGBMRegressor(**_lgb_params(s2.params, seed, **extra))
    _fit(m2, Xt, yraw, sw, cats)
    out["c2"] = np.clip(
        np.nan_to_num(np.clip(np.asarray(m2.predict(Xv), dtype=float), 0, None), nan=0.0), 0, None
    )
    # 분위(C1 파라미터, objective=quantile)
    if quantiles:
        wq = 1.0 + s1.alpha * ylog
        if sw is not None:
            wq = wq * sw
        lpq = {}
        for q in QUANTILES:
            mq = lgb.LGBMRegressor(**_lgb_params(s1.params, seed, objective="quantile", alpha=q))
            _fit(mq, Xt, ylog, wq, cats)
            lpq[q] = np.asarray(mq.predict(Xv), dtype=float)
        lo, mid, hi_q = lpq[0.1], lpq[0.5], lpq[0.9]
        lo, hi_q = np.minimum(lo, hi_q), np.maximum(lo, hi_q)
        mid = np.clip(mid, lo, hi_q)
        out.update({"q10": to_cells(lo), "q50": to_cells(mid), "q90": to_cells(hi_q)})
    return out


def pooled_cv(
    df_own: pd.DataFrame,
    other: pd.DataFrame,
    cols: list[str],
    *,
    v: Variant | None = None,
    specs: dict[str, VariantSpec] | None = None,
    quantiles: bool = True,
    budget: H.Budget | None = None,
) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    """통합 학습 OOF(df_own 행 순서, 2020~2025 만 값) + 폴드별 학습 표본 수 표.

    cols 는 ``variant_cols`` 결과(임베딩·플래그·지점 이력·prior 열 포함). v 의 w_own·smear_scope·site_hist·prior 를 따른다.
    """
    v = v or Variant("기본")
    H.guard_no_2026(df_own)
    specs = specs or H.v1_specs()
    extra_cols = [c for c in cols if c in (*SITE_HIST_COLS, PRIOR_COL)]
    base_cols = [c for c in cols if c not in extra_cols]
    comb, own = combine(df_own, other, base_cols)
    if v.site_hist:
        comb = add_site_history(comb, site_history_table())
    years = comb["base_date"].dt.year.to_numpy()
    sw_all = np.where(own, v.w_own, 1.0) if v.w_own != 1.0 else None
    keys = ["c1", "c1_none", "c1_log", "c3", "c2"] + (["q10", "q50", "q90"] if quantiles else [])
    oof = {k: np.full(len(df_own), np.nan) for k in keys}
    cells = comb["target_cells"].to_numpy(dtype=float)
    prior_cols = [c for c in base_cols if c != "station_id"]
    stats = []
    for name, vy, tr_m, va_m in fold_plan(years, own):
        if budget is not None:
            budget.check()
        fit_m = tr_m & own if v.prior else tr_m
        tr = comb[fit_m].copy()
        va = comb[va_m].copy()
        if v.prior:
            oth = comb[tr_m & ~own]
            pp = fit_prior(oth, pd.concat([tr, va]), prior_cols, specs["c1"])
            tr[PRIOR_COL], va[PRIOR_COL] = pp[: len(tr)], pp[len(tr) :]
        sw = None if sw_all is None else sw_all[fit_m]
        pr = fold_members(tr, va, cols, specs, sw, own[fit_m], smear_scope=v.smear_scope, quantiles=quantiles)
        idx = np.where(va_m)[0]  # own 행은 comb 앞부분 → df_own 위치와 같다
        for k in keys:
            oof[k][idx] = pr[k]
        stats.append(
            {
                "폴드": name,
                "valid 연도": vy,
                "학습 n(우리 5지점)": int((tr_m & own).sum()),
                "학습 n(통합)": int(tr_m.sum()),
                ">10k(우리 5지점)": int(((cells >= H.T10K) & tr_m & own).sum()),
                ">10k(통합)": int(((cells >= H.T10K) & tr_m).sum()),
                "학습 지점 수": int(comb.loc[tr_m, "station_id"].nunique()),
            }
        )
        log.info("%s(%d): 학습 %d행 → 평가 %d행", name, vy, int(fit_m.sum()), int(va_m.sum()))
    return oof, pd.DataFrame(stats)


def members(df: pd.DataFrame, cols: list[str], *, variant: str | None = None) -> dict[str, np.ndarray]:
    """공개: 선택한 통합 학습 설정으로 우리 5지점 df 행의 OOF(c1·c1_none·c1_log·c3·c2·q10·q50·q90, 2020~2025).

    df = ``harness.load_base()`` 형식, cols = 모델 피처(지점 임베딩 ``station_id``·플래그는 변형 설정이 붙인다).
    다른 지점 표본에 없는 열(다른 실험의 새 피처 등)은 NaN 으로 들어간다.
    """
    v = VARIANTS[variant or CHOSEN]
    other = load_other_samples() if SAMPLES_PATH.exists() else build_other_samples(build_meta()[0])
    other = other[subset_mask(other, v.subset)]
    oof, _ = pooled_cv(df, other, variant_cols(cols, v), v=v)
    return oof


# ================================================================ 4. 실행·보고
def _md(t: pd.DataFrame) -> str:
    def fmt(x: object) -> str:
        if isinstance(x, float):
            return (
                "–"
                if not np.isfinite(x)
                else f"{x:,.3f}".rstrip("0").rstrip(".") if abs(x) < 1000 else f"{x:,.0f}"
            )
        return str(x)

    hdr = "| " + " | ".join(map(str, t.columns)) + " |\n|" + "---|" * len(t.columns)
    body = "\n".join("| " + " | ".join(fmt(v) for v in r) + " |" for r in t.itertuples(index=False))
    return hdr + "\n" + body + "\n"


def run_variants(names: list[str], budget: H.Budget) -> list[dict]:
    """변형별 통합 학습 → 표준 지표. 변형마다 variant_<이름>.json(지표·폴드 표본 수)·oof_<이름>.parquet 저장."""
    df = H.load_base()
    cols = H.base_columns()
    other_all = load_other_samples()
    rows = []
    for name in names:
        budget.check()
        v = VARIANTS[name]
        t0 = time.time()
        other = other_all[subset_mask(other_all, v.subset)]
        oof, st = pooled_cv(df, other, variant_cols(cols, v), v=v, budget=budget)
        row, ens, w = H.evaluate_members(df, oof, v.label)
        row["variant"] = name
        row["minutes"] = round((time.time() - t0) / 60, 1)
        row["weights"] = {str(k): {kk: round(vv, 3) for kk, vv in ww.items()} for k, ww in w.items()}
        oof["pred"] = ens
        rows.append(row)
        H.save_oof(df, oof, OUT_DATA / f"oof_{name}.parquet")
        (OUT_DATA / f"variant_{name}.json").write_text(
            json.dumps(
                {"row": row, "stats": st.to_dict(orient="records")}, ensure_ascii=False, indent=1, default=str
            )
            + "\n",
            encoding="utf-8",
        )
        log.info(
            "%s: CV r2_raw %.3f rmse_log %.3f lead %s/%s (%.1f분)",
            name, row["cv_r2_raw"], row["cv_rmse_log"], row.get("lead_q90"), row.get("lead_n"), row["minutes"],
        )  # fmt: skip
    return rows


def load_variant_results() -> tuple[list[dict], dict[str, pd.DataFrame]]:
    rows, stats = [], {}
    for name in VARIANTS:
        p = OUT_DATA / f"variant_{name}.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            rows.append(d["row"])
            stats[name] = pd.DataFrame(d["stats"])
    return rows, stats


def per_site_table(df: pd.DataFrame, preds: dict[str, np.ndarray]) -> pd.DataFrame:
    """우리 지점별 CV(2020~2024) r2_raw·rmse_log(구성별)."""
    from algaecast.eval.metrics import compute_all

    obs = df["target_cells"].to_numpy(dtype=float)
    cv, _ = H.masks(df)
    sid = df["station_id"].astype(str).to_numpy()
    rows = []
    for s in ["HP", "GJGR", "CS", "MGMR", "DCHN"]:
        r: dict = {"지점": s, "CV n": int((cv & (sid == s)).sum())}
        for lab, p in preds.items():
            m = cv & (sid == s) & np.isfinite(p)
            mm = compute_all(obs[m], p[m])
            r[f"{lab} r2_raw"] = float(mm["r2_raw"])
            r[f"{lab} rmse_log"] = float(mm["rmse_log"])
        rows.append(r)
    return pd.DataFrame(rows)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_snippets(meta: pd.DataFrame, other: pd.DataFrame) -> None:
    """manifest_snippet.md·docs02_snippet.md·sites_snippet.yaml(통합은 메인 세션)."""
    OUT_REP.mkdir(parents=True, exist_ok=True)
    algae_csv = ALGAE_ALL.with_suffix(".csv")
    a = pd.read_parquet(ALGAE_ALL, columns=["site_code", "obs_date", "fetched_at"])
    stn_csv = RAW_DIR / "kma_stn_info" / "kma_stn_list.csv"
    stn = pd.read_csv(stn_csv)
    asos = pd.read_parquet(ASOS_ALL)
    lines = [
        "# EXP-008 MANIFEST 조각(data/raw/MANIFEST.md 통합용)",
        "",
        "| ID | 이름 | 기관 | 엔드포인트 | 기간 | 수집 일시 | 행 | 라이선스 | 경로 | sha256 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| WQ-01b | 조류경보제 조회서비스 전 지점({a['site_code'].nunique()}개, ptNoList 없음) | 기후에너지환경부 국립환경과학원 | "
        f"apis.data.go.kr/1480523/nieragainstalgae/algaePreMeasure (wmyrList 연도별, numOfRows 10000) | "
        f"{a['obs_date'].min()}~{a['obs_date'].max()} | {pd.Timestamp(a['fetched_at'].max()):%Y-%m-%d %H:%M} KST | {len(a):,} | 공공누리 1유형 | "
        f"data/raw/nier_algae_all/{algae_csv.name} | {_sha256(algae_csv)} |",
        f"| MT-01b | 기상청 관측지점 정보(지점번호·위경도·이력) | 기상청 기상자료개방포털 | data.kma.go.kr/tmeta/stn/selectStnList.do (pgmNo=123) | 현행+이력 | "
        f"2026-10-21 18:03 KST | {len(stn):,} | 공공누리 1유형 | data/raw/kma_stn_info/kma_stn_list.csv | {_sha256(stn_csv)} |",
        f"| MT-01c | ASOS 일자료 — 다른 지점 최근접 관측소 {asos['stn_id'].nunique()}곳 | 기상청 | apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList | "
        f"2012-01-01~2025-12-31 | {pd.Timestamp(asos['fetched_at'].max()):%Y-%m-%d %H:%M} KST | {len(asos):,} | 공공누리 1유형 | "
        f"data/raw/kma_asos_all/{ASOS_ALL.name} | {_sha256(ASOS_ALL)} |",
        "",
        "- 보조 산출(같은 폴더): `sites_all.csv`(지점 목록·기간·측정 수), `token_report.csv`(알 수 없는 문자열 — 이번 수집 0건), "
        "`asos_stations.csv`(ASOS 대표 좌표 = 이력 중앙값).",
        "- 수질측정망 GeoJSON(`data/raw/nier_wq/` zip)은 좌표 근사에만 읽었다(압축은 메모리에서만 해제).",
        "",
    ]
    (OUT_REP / "manifest_snippet.md").write_text("\n".join(lines), encoding="utf-8")
    d2 = [
        "# EXP-008 docs/02_DATA_SPEC.md 조각",
        "",
        "| ID | 데이터 | 제공 | 주기 | 용도 | 비고 |",
        "|---|---|---|---|---|---|",
        "| WQ-01b | 조류경보제 전 지점 측정(82개 지점, 2012~) | 국립환경과학원(data.go.kr #15126738) | 주 1~2회 | 통합 학습 표본(R5) | ptNoList 없이 연도별 조회. 우리 5지점 값은 WQ-01 과 100 % 일치 |",
        "| MT-01b | 기상청 관측지점 정보 | 기상청 기상자료개방포털 | 수시 | 다른 지점 최근접 ASOS 결정 | 인증 불필요, 이력 행 중앙값 좌표 |",
        "| MT-01c | ASOS 일자료(추가 관측소) | 기상청(data.go.kr #15059093) | 일 | 다른 지점 기상 피처 | MT-01 과 같은 API·수집기 |",
        "",
    ]
    (OUT_REP / "docs02_snippet.md").write_text("\n".join(d2), encoding="utf-8")
    n_samp = other.groupby("site_code").size()
    n_10k = other.assign(o=other["target_cells"] >= H.T10K).groupby("site_code")["o"].sum()
    items = []
    for _, r in meta[~meta["is_own"]].iterrows():
        c = r["site_code"]
        items.append(
            {
                "site_code": c,
                "name": f"{r['swmn_nm']} {r['swmn_detail_nm']}",
                "river_lake": r["river_lkmh_se"],
                "basin": r["basin"],
                "facility_type": r["facility_type"],
                "lat": round(float(r["lat"]), 5),
                "lon": round(float(r["lon"]), 5),
                "coord_method": r["coord_method"],
                "coord_ref": str(r["coord_ref"]),
                "asos_primary": int(r["asos_stn"]),
                "asos_name": r["asos_nm"],
                "asos_distance_km": float(r["asos_km"]),
                "hydro": HYDRO_MAP.get(c, {}),
                "samples_le_2025": int(n_samp.get(c, 0)),
                "samples_over_10k": int(n_10k.get(c, 0)),
            }
        )
    head = (
        "# EXP-008 전국 조류경보 지점 메타(통합 학습용, 우리 5지점 제외). config/sites.yaml 에 넣을 때는 별도 키\n"
        "# (예: national_alert_sites) 로 두고 v1 sites 목록과 섞지 않는다. 좌표는 근사(coord_method 참조).\n"
    )
    (OUT_REP / "sites_snippet.yaml").write_text(
        head + yaml.safe_dump({"national_alert_sites": items}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def select_variant(base: dict, rows: list[dict]) -> tuple[dict, bool]:
    """EXP-PLAN 4절: 채택 기준 만족 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대(기준 미달)."""
    cand = [r for r in rows if r["variant"] != "own_only"]
    ok = [r for r in cand if H.adoption(base, r)["pass"]]
    pool = ok or cand
    best = max(pool, key=lambda r: r["cv_r2_raw"])
    return best, bool(ok)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", default="all", choices=["meta", "samples", "train", "report", "all"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--started", default=STARTED, help="실험 시작 시각(시간 상한 기준, KST)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s %(message)s")
    budget = H.Budget(12.0, EXP)
    budget.t0 = pd.Timestamp(args.started, tz="Asia/Seoul").timestamp()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    if args.step in ("meta", "all"):
        meta, asos = build_meta()
        print(
            meta[
                ["site_code", "swmn_nm", "swmn_detail_nm", "coord_method", "asos_stn", "asos_nm", "asos_km"]
            ].to_string()
        )
    if args.step in ("samples", "all"):
        meta = pd.read_csv(META_PATH, dtype={"site_code": str})
        t0 = time.time()
        other = build_other_samples(meta, workers=args.workers)
        print(
            f"다른 지점 표본 {len(other):,}행, 지점 {other['site_code'].nunique()}개 ({(time.time() - t0) / 60:.1f}분)"
        )
    if args.step in ("train", "all"):
        names = [n.strip() for n in args.variants.split(",") if n.strip()]
        run_variants(names, budget)
    if args.step in ("report", "all"):
        report_draft()
    log.info("경과 %.2fh / 상한 12h", budget.elapsed_h)
    return 0


def baseline_row() -> dict:
    row = json.loads((H.EXP_REPORTS / "EXP-baseline" / "baseline_metrics.json").read_text(encoding="utf-8"))
    row["구성"] = "v1 기준"
    row["variant"] = "v1"
    return row


def report_draft() -> dict:
    """metrics.json·chosen_oof.parquet·조각 파일·표 초안(OUT_DATA/report_tables.md). README 해석은 별도로 쓴다."""
    base = baseline_row()
    rows, stats = load_variant_results()
    chosen, passed = select_variant(base, rows)
    adopt = H.adoption(base, chosen)
    df = H.load_base()
    o = pd.read_parquet(OUT_DATA / f"oof_{chosen['variant']}.parquet")
    if not (o["base_date"].astype(str).to_numpy() == df["base_date"].astype(str).to_numpy()).all():
        raise RuntimeError("OOF 행 순서가 load_base() 와 다름")
    keep = ["c1", "c3", "c2", "q10", "q50", "q90", "pred"]
    H.save_oof(df, {k: o[k].to_numpy(dtype=float) for k in keep}, OUT_DATA / "chosen_oof.parquet")
    OUT_REP.mkdir(parents=True, exist_ok=True)
    order = ["own_only", *[n for n in VARIANTS if n != "own_only"]]
    rows = sorted(rows, key=lambda r: order.index(r["variant"]))
    (OUT_REP / "metrics.json").write_text(
        json.dumps([base, *rows], ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8"
    )
    meta = pd.read_csv(META_PATH, dtype={"site_code": str})
    other = load_other_samples()
    write_snippets(meta, other)
    _, bo = H.load_baseline()
    preds = {"v1": bo["ens"], chosen["variant"]: o["pred"].to_numpy(dtype=float)}
    adopt_rows = [{"구성": r["구성"], **H.adoption(base, r)} for r in rows]
    parts = [
        "## 표준 표\n",
        H.standard_table([base, *rows]),
        "\n## 보조 표\n",
        H.detail_table([base, *rows]),
        "\n## 채택 판정(변형별)\n",
        _md(pd.DataFrame(adopt_rows)),
        f"\n선택: {chosen['variant']} ({chosen['구성']}), 기준 만족 변형 있음={passed}, adoption={adopt}\n",
        "\n## 폴드별 학습 표본(전 지점 변형)\n",
        _md(stats.get("all_embed", next(iter(stats.values())))),
        "\n## 폴드별 학습 표본(선택 변형)\n",
        _md(stats[chosen["variant"]]),
        "\n## 지점별 CV\n",
        _md(per_site_table(df, preds)),
        "\n## 변형별 NNLS 가중치·소요(분)\n",
        "\n".join(
            f"- {r['variant']}: {r['minutes']}분, {json.dumps(r['weights'], ensure_ascii=False)}"
            for r in rows
        ),
        "\n",
    ]
    (OUT_DATA / "report_tables.md").write_text("\n".join(parts), encoding="utf-8")
    return {"chosen": chosen, "passed": passed, "adoption": adopt}


if __name__ == "__main__":
    raise SystemExit(main())
