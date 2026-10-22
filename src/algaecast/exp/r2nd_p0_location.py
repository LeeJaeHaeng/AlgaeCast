# ruff: noqa: E501  (한국어 표 머리글)
"""EXP-005(2차) P0 — 2025-08 조류경보 채수 위치 변경 진단.

사전등록 `reports/experiments/EXP-005/PREREG_P2.md` 2절 정의를 그대로 쓴다.

a) 채수 위치 변경일 확정 근거: 조류경보제 API 필드(swmnDetailNm·detailAdres, 좌표 필드 유무)·대회 번들 열·
   운영매뉴얼(2025.8)·보도·측정 시계열 단절(채수 요일·간격, 인근 보 지점과의 짝 차이).
b) v1 CV 모델(≤2024 학습) 2025 log 잔차의 차이의 차이(DiD): 낙동강 4지점 vs 회남. 평균·분산 DiD,
   지점×기간 층별 부트스트랩 5,000회(시드 20261022). P2 적용 조건 판정. 민감도(판정에 쓰지 않음):
   지점별 확정 변경일 분할, 위치 경계를 건너는 행 제외, 지속성(B0) 잔차, 2020~2024 같은 달 위약(placebo) 연도.
c) 위치가 바뀌지 않은 대조 지점(낙동강 보 관찰지점 8곳, 대청호 추동·문의)으로 모델과 무관한 잔차
   (7일 지속성 잔차, 지점·월 기후값 편차) DiD.
d) 새 위치 측정의 수준·변동성: 2022~2023 시범 지점(취수구 500 m 상류) 짝 비교, 0값 비율, 주간 변동, 기간별 예측 성능.

2026 은 계산·열람 금지: 원자료는 읽은 즉시 2025-12-31 이후 측정을 버리고, 모델 잔차는 harness.load_baseline()
(≤2025)만 쓴다. 행 단위 중간물은 data/processed/exp/EXP-005b/P0/, 보고 산출물은 reports/experiments/EXP-005/P0/.

사용: python -m algaecast.exp.r2nd_p0_location
"""

from __future__ import annotations

import glob
import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, RAW_DIR
from algaecast.eval.metrics import compute_all
from algaecast.exp import harness as H
from algaecast.features.run import match_target

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

log = logging.getLogger(__name__)

T_START = time.time()
OUT_REP = H.EXP_REPORTS / "EXP-005" / "P0"
OUT_DATA = H.EXP_DATA / "EXP-005b" / "P0"
LAST = H.LAST_DATE
ALL_PARQUET = RAW_DIR / "nier_algae_all" / "nier_algae_all_2012_2026.parquet"
BUNDLE_MEASURE = RAW_DIR / "competition" / "algae_contest_2026" / "algae_measure.csv"
BUNDLE_STATIONS = RAW_DIR / "competition" / "algae_contest_2026" / "stations.csv"
CACHE_DIR = RAW_DIR / "cache"
BOOT_SEED = 20261022
N_BOOT = 5000
BUDGET_H = 4.0
PLAUSIBLE = {"iem_wtrtp": (-1.0, 40.0), "iem_ph": (4.0, 13.0), "iem_doc": (0.0, 30.0)}

# 사전등록 2절 기간(목표일 기준)
PRE = (pd.Timestamp("2025-01-01"), pd.Timestamp("2025-08-31"))
POST = (pd.Timestamp("2025-09-01"), pd.Timestamp("2025-10-31"))
N_SITES = ["HP", "GJGR", "CS", "MGMR"]
D_SITE = "DCHN"
CODE = {"HP": "2011G26", "GJGR": "2011G56", "CS": "2020G33", "MGMR": "2022G05", "DCHN": "3008G30"}
NAME = {"HP": "해평", "GJGR": "강정·고령", "CS": "칠서", "MGMR": "물금·매리", "DCHN": "회남"}
# 위치가 바뀌지 않은 대조 지점 — 운영매뉴얼(2025.8) 표3 조류관찰지점(보 상류 300~500 m, 낙동강물연구소 조사).
WEIRS = {
    "2007A25": "상주보(도남)",
    "2009A05": "낙단보(낙단)",
    "2009A30": "구미보(선산)",
    "2011A25": "칠곡보(칠곡)",
    "2011A55": "강정고령보(다사)",
    "2014A25": "달성보(논공)",
    "2014A70": "합천창녕보(덕곡)",
    "2020A32": "창녕함안보(함안)",
}
LAKE = {"3008G40": "대청호 추동", "3008G50": "대청호 문의"}
# 처리 지점 바로 위·아래의 보 관찰지점(본류 순서: 상주보 → 낙단보 → 구미보 → [해평] → 칠곡보 → [강정·고령] →
# 강정고령보 → 달성보 → 합천창녕보 → [칠서] → 창녕함안보 → [물금·매리])
NEIGHBORS = {
    "HP": ["2009A30", "2011A25"],
    "GJGR": ["2011A25", "2011A55"],
    "CS": ["2014A70", "2020A32"],
    "MGMR": ["2020A32"],
}
# 2022.5~12·2023 '상수원 구간 채수지점 이동 검토' 시범 지점(취수구 500 m 상류) — 매뉴얼 연혁 18)
PILOTS = {
    "GJGR": {"9999A98": "고령 지점 혼합(취수구 500 m 상류)", "9999A99": "고령 지점 표층(취수구 500 m 상류)"},
    "MGMR": {"7777A76": "매리 지점 혼합(취수구 500 m 상류)", "7777A77": "매리 지점 표층(취수구 500 m 상류)"},
}
TRIAL_CODES = {"HP": "2011A26", "GJGR": "2011A56", "CS": "2020A33"}  # 2013-02~2015-12 낙동강 시범운영 코드
OFFICIAL_WINDOW_START = pd.Timestamp(
    "2025-08-25"
)  # '8월 말' 첫 정기 채수일(월). 08-19 발표 "이달 말 즉시 추진"
SCAN_VARS = {
    "lc": "log10 세포수",
    "iem_wtrtp": "수온(℃)",
    "ltur": "log10 탁도",
    "iem_trp": "투명도(m)",
    "iem_ph": "pH",
    "iem_doc": "DO(mg/L)",
    "lchl": "log10 Chl-a",
}
# 운영매뉴얼(2025.8) 표2 새 위치 좌표(경도/위도, DMS) — 'p.24 표2' 낙동강 4지점 행
MANUAL_NEW_COORDS = {
    "HP": ("128°23'14.3\"", "36°10'10.3\"", "경상북도 구미시 해평면 문량리", "취수구 50m"),
    "GJGR": ("128°27'6.1\"", "35°50'50.7\"", "대구광역시 달성군 다사읍 매곡리", "취수구 50m"),
    "CS": ("128°28'55.9\"", "35°22'55.4\"", "경상남도 함안군 칠서면 계내리", "취수구 50m"),
    "MGMR": ("128°57'8.6\"", "35°20'6.9\"", "경상남도 김해시 상동면 매리", "취수구 50m"),
}
MANUAL_OLD_NOTE = {  # 운영매뉴얼(2025.8) 표2 주석 원문(p.24)
    "HP": "해평취수구 상류 2 km → 취수구 인근 50 m",
    "GJGR": "고령취수구 상류 2 km → 매곡취수구 인근 50 m",
    "CS": "칠서취수구 상류 4 km → 취수구 인근 50 m",
    "MGMR": "매리취수구 상류 3 km → 취수구 인근 50 m",
}
DOC_FACTS = [
    {
        "근거": "조류경보제 운영 매뉴얼(2025.8) 연혁 20)",
        "내용": "2025.08 녹조 신속 분석 체계(해평, 강정·고령, 칠서, 물금·매리) 운영 — 채수지점 이동(취수구 2~4 km 상류→취수구 인근), 발령일자(채수 3일차 오후→채수 당일)",
        "등급": "공식 문서(월 단위)",
        "출처": "https://www.water.or.kr/upload/board/2026/04/20260416110044_1.pdf (p.5)",
    },
    {
        "근거": "운영 매뉴얼(2025.8) 표2 주석",
        "내용": "낙동강 하천지점 시료채취 위치 변경 ①해평 해평취수구 상류 2km→취수구 인근 50m ②강정·고령 고령취수구 상류 2km→매곡취수구 인근 50m ③칠서 칠서취수구 상류 4km→취수구 인근 50m ④물금·매리 매리취수구 상류 3km→취수구 인근 50m",
        "등급": "공식 문서(날짜 없음)",
        "출처": "같은 문서 p.24",
    },
    {
        "근거": "운영 매뉴얼(2025.8) 2.5.1.1.2 시료채취 방법",
        "내용": "녹조 신속 분석 체계 운영 지점은 발령상황 구분 없이 취수구가 위치한 측면에서 취수구로부터 50 m 내외 지점의 상층·수심 1/3·2/3 혼합(옛 방식: 단면 최심부 수직 혼합, '경계' 이상이면 좌·중·우 3지점 × 수심별 혼합)",
        "등급": "공식 문서",
        "출처": "같은 문서 p.43~44",
    },
    {
        "근거": "운영 매뉴얼(2025.8) 연혁 14)",
        "내용": "2016.04 채수방법 변경(상수원: 층별 통합채수, 친수활동: 표층채수), 분석항목에 투명도·탁도 추가",
        "등급": "공식 문서(월 단위)",
        "출처": "같은 문서 p.5",
    },
    {
        "근거": "운영 매뉴얼(2025.8) 연혁 18)",
        "내용": "2022.5~12 조류경보제 개선 시범운영 — 상수원 구간 채수지점 이동 검토(취수구 2~4 km 상류→취수구 1 km 이내)",
        "등급": "공식 문서",
        "출처": "같은 문서 p.5",
    },
    {
        "근거": "이투데이 2025-08-19 12:00",
        "내용": "채수 위치를 원수 취수구 인근 50m 이내로 조정 … '이달 말 즉시 추진하겠다'. 해평·칠서취수장에 이동형 수질분석차량 각 1대 배치, 채수 당일 발령",
        "등급": "보도",
        "출처": "https://www.etoday.co.kr/news/view/2498096",
    },
    {
        "근거": "정책브리핑 2025-08-21",
        "내용": "녹조 채취 지점을 취수구 인근 50m 이내로 조정, 해평·칠서 이동형 수질분석차량, 매곡·매리는 국립환경과학원·낙동강물환경센터 활용, 당일 채수·당일 분석·당일 발표, 낙동강부터 우선 적용",
        "등급": "보도(정부)",
        "출처": "https://www.korea.kr/news/policyNewsView.do?newsId=156721747",
    },
]


# ---------------------------------------------------------------- 공통
def _elapsed_h() -> float:
    return (time.time() - T_START) / 3600


def _check_budget() -> None:
    if _elapsed_h() > BUDGET_H:
        raise H.BudgetExceeded(f"P0: 시간 상한 {BUDGET_H}h 초과({_elapsed_h():.2f}h)")


def dms_to_deg(s: str) -> float:
    """128°23'14.3\" → 십진 도."""
    s = s.replace("˚", "°").replace("“", '"').replace("”", '"')
    d, rest = s.split("°")
    m, rest = rest.split("'")
    sec = rest.replace('"', "").strip() or "0"
    return float(d) + float(m) / 60 + float(sec) / 3600


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(a)))


def load_algae_all() -> pd.DataFrame:
    """R5 전국 조류경보 원자료(82지점). 읽은 즉시 2025-12-31 이후 측정을 버린다."""
    a = pd.read_parquet(ALL_PARQUET)
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    a = a[a["obs_date"] <= LAST].copy()
    a = a.sort_values(["site_code", "obs_date"]).drop_duplicates(["site_code", "obs_date"], keep="last")
    for v, (lo, hi) in PLAUSIBLE.items():  # 물리적으로 불가능한 입력 오류(예: 수온 211.7℃)는 결측 처리
        a.loc[(a[v] < lo) | (a[v] > hi), v] = np.nan
    a["lc"] = np.log10(a["iem_bgalage_cell_co"] + 1)
    a["ltur"] = np.log10(a["iem_tur"] + 0.1)
    a["lchl"] = np.log10(a["iem_chla"] + 0.1)
    return a.reset_index(drop=True)


def load_bundle_measure() -> pd.DataFrame:
    """대회 번들 algae_measure.csv. 읽은 즉시 2025-12-31 이후 측정을 버린다."""
    b = pd.read_csv(BUNDLE_MEASURE, dtype=str, encoding="utf-8-sig")
    b["chck_de"] = pd.to_datetime(b["chck_de"])
    return b[b["chck_de"] <= LAST].copy()


# ---------------------------------------------------------------- a) 위치 변경일
def api_tag_inventory() -> dict:
    """캐시된 조류경보제 API(algaePreMeasure) XML 응답의 item 태그 목록(측정일 ≤ 2025-12-31 item 만 셈)."""
    tags: dict[str, int] = {}
    n_items = n_files = 0
    for f in sorted(glob.glob(str(CACHE_DIR / "*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(d, dict) or "algaePreMeasure" not in str(d.get("url", "")):
            continue
        try:
            root = ET.fromstring(d.get("text") or "")
        except ET.ParseError:
            continue
        n_files += 1
        for it in root.iter("item"):
            de = (it.findtext("chckDe") or "").strip()
            if not de or pd.Timestamp(de) > LAST:
                continue  # 2026 측정 item 은 태그도 세지 않는다
            n_items += 1
            for c in it:
                tags[c.tag] = tags.get(c.tag, 0) + 1
    coord_like = [
        t
        for t in tags
        if any(k in t.lower() for k in ("lat", "lon", "crd", "coord", "xpos", "ypos", "tmx", "tmy"))
    ]
    return {
        "n_files": n_files,
        "n_items_le_2025": n_items,
        "tags": sorted(tags),
        "coordinate_like_tags": coord_like,
    }


def field_table(a: pd.DataFrame, bundle: pd.DataFrame) -> pd.DataFrame:
    """지점별 조사위치 필드(값 종류 수·기간). API 원자료와 대회 번들 둘 다."""
    rows = []
    codes = (
        [CODE[s] for s in [*N_SITES, D_SITE]]
        + list(TRIAL_CODES.values())
        + [c for p in PILOTS.values() for c in p]
        + list(WEIRS)
        + list(LAKE)
    )
    for c in codes:
        s = a[a["site_code"] == c]
        if s.empty:
            continue
        rows.append(
            {
                "출처": "API(R5 원자료)",
                "지점코드": c,
                "swmn_nm": s["swmn_nm"].iloc[0],
                "swmn_detail_nm": " | ".join(sorted(s["swmn_detail_nm"].fillna("").unique())),
                "detail_adres": " | ".join(sorted(s["detail_adres"].fillna("").unique())),
                "값 종류(이름/주소)": f"{s['swmn_detail_nm'].nunique()}/{s['detail_adres'].nunique()}",
                "첫 측정": s["obs_date"].min().date().isoformat(),
                "마지막(≤2025)": s["obs_date"].max().date().isoformat(),
                "n": len(s),
            }
        )
    for sid, s in bundle.groupby("station_id"):
        rows.append(
            {
                "출처": "대회 번들 algae_measure",
                "지점코드": f"{s['swmn_code'].iloc[0]}({sid})",
                "swmn_nm": s["swmn_nm"].iloc[0],
                "swmn_detail_nm": " | ".join(sorted(s["swmn_detail_nm"].fillna("").unique())),
                "detail_adres": " | ".join(sorted(s["detail_adres"].fillna("").unique())),
                "값 종류(이름/주소)": f"{s['swmn_detail_nm'].nunique()}/{s['detail_adres'].nunique()}",
                "첫 측정": s["chck_de"].min().date().isoformat(),
                "마지막(≤2025)": s["chck_de"].max().date().isoformat(),
                "n": len(s),
            }
        )
    return pd.DataFrame(rows)


def coords_table() -> pd.DataFrame:
    """매뉴얼(2025.8) 새 위치 좌표 vs config/sites.yaml 좌표(읽기 전용)."""
    cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    by_id = {s["station_id"]: s for s in cfg["sites"]}
    rows = []
    for sid, (lon_s, lat_s, addr, rel) in MANUAL_NEW_COORDS.items():
        lon, lat = dms_to_deg(lon_s), dms_to_deg(lat_s)
        y = by_id.get(sid, {})
        d = haversine_km(lat, lon, float(y.get("lat", np.nan)), float(y.get("lon", np.nan))) if y else np.nan
        rows.append(
            {
                "지점": f"{NAME[sid]}({sid})",
                "매뉴얼 새 위치(경도/위도)": f"{lon_s}/{lat_s}",
                "십진(위도, 경도)": f"{lat:.4f}, {lon:.4f}",
                "주소": addr,
                "상대위치": rel,
                "옛 위치(표2 주석)": MANUAL_OLD_NOTE[sid],
                "sites.yaml 좌표와 거리(km)": round(d, 2),
                "sites.yaml location 메모": y.get("location", ""),
            }
        )
    return pd.DataFrame(rows)


def schedule_table(a: pd.DataFrame) -> pd.DataFrame:
    """채수 요일·간격: 2025-06-01~08-24 vs 2025-08-25~10-31 vs 2020~2024 같은 기간(9~10월)."""
    rows = []
    wins = {
        "2025-06~08-24": (pd.Timestamp("2025-06-01"), pd.Timestamp("2025-08-24")),
        "2025-08-25~10-31": (pd.Timestamp("2025-08-25"), pd.Timestamp("2025-10-31")),
    }
    for sid in [*N_SITES, D_SITE]:
        s = a[(a["site_code"] == CODE[sid])][["obs_date", "lc"]].copy()
        s["gap"] = s["obs_date"].diff().dt.days
        for lab, (lo, hi) in wins.items():
            x = s[(s["obs_date"] >= lo) & (s["obs_date"] <= hi)]
            rows.append(_sched_row(sid, lab, x))
        x = s[s["obs_date"].dt.year.between(2020, 2024) & s["obs_date"].dt.month.isin([9, 10])]
        rows.append(_sched_row(sid, "2020~2024 9~10월", x))
    return pd.DataFrame(rows)


def _sched_row(sid: str, lab: str, x: pd.DataFrame) -> dict:
    dow = x["obs_date"].dt.dayofweek
    return {
        "지점": sid,
        "구간": lab,
        "측정 수": len(x),
        "세포수 결측": int(x["lc"].isna().sum()),
        "월요일 비율": round(float((dow == 0).mean()), 2) if len(x) else np.nan,
        "목요일 비율": round(float((dow == 3).mean()), 2) if len(x) else np.nan,
        "간격 중앙값(일)": float(x["gap"].median()) if len(x) else np.nan,
    }


def paired_diff(a: pd.DataFrame, t_code: str, c_code: str, tol: int = 1) -> pd.DataFrame:
    """처리 지점 − 대조 지점 짝 차이(측정일 ±tol 일 최근접 짝). 변수: SCAN_VARS."""
    cols = list(SCAN_VARS)
    st = a[a["site_code"] == t_code][["obs_date", *cols]].sort_values("obs_date")
    sc = (
        a[a["site_code"] == c_code][["obs_date", *cols]]
        .rename(columns={"obs_date": "c_date"})
        .sort_values("c_date")
    )
    m = pd.merge_asof(
        st,
        sc,
        left_on="obs_date",
        right_on="c_date",
        direction="nearest",
        tolerance=pd.Timedelta(days=tol),
        suffixes=("", "_c"),
    ).dropna(subset=["c_date"])
    out = pd.DataFrame({"date": m["obs_date"].to_numpy(), "t_code": t_code, "c_code": c_code})
    for v in cols:
        out[v] = m[v].to_numpy() - m[v + "_c"].to_numpy()
    return out


def _split_shift(
    x: pd.DataFrame, v: str, cut: pd.Timestamp, lo: pd.Timestamp, hi: pd.Timestamp
) -> tuple[float, int, int]:
    w = x[(x["date"] >= lo) & (x["date"] <= hi)][["date", v]].dropna()
    pre, post = w[w["date"] < cut][v], w[w["date"] >= cut][v]
    if len(pre) < 4 or len(post) < 4:
        return np.nan, len(pre), len(post)
    return float(post.mean() - pre.mean()), len(pre), len(post)


def break_scan(pairs: pd.DataFrame) -> pd.DataFrame:
    """짝 차이의 2025 단절 탐색.

    - 최적 분할일: 2025-06-01~12-31 창에서 처리 지점 측정일(2025-07-07~10-27) 중 두 구간 SSE 최소.
    - 2025-08-25 분할 이동량과, 같은 달력(6/1~12/31, 8/25 분할)의 과거 연도 위약 분포(z·순위).
    """
    rows = []
    for (t_code, c_code), x in pairs.groupby(["t_code", "c_code"]):
        sid = next(k for k, v in CODE.items() if v == t_code)
        for v in SCAN_VARS:
            w = x[(x["date"] >= "2025-06-01") & (x["date"] <= LAST)][["date", v]].dropna()
            best = (None, np.inf, np.nan)
            for cd in w["date"][(w["date"] >= "2025-07-07") & (w["date"] <= "2025-10-27")]:
                pre, post = w[w["date"] < cd][v], w[w["date"] >= cd][v]
                if len(pre) < 4 or len(post) < 4:
                    continue
                sse = float(((pre - pre.mean()) ** 2).sum() + ((post - post.mean()) ** 2).sum())
                if sse < best[1]:
                    best = (cd, sse, float(post.mean() - pre.mean()))
            s25, n_pre, n_post = _split_shift(x, v, OFFICIAL_WINDOW_START, pd.Timestamp("2025-06-01"), LAST)
            plac = []
            for y in range(2016, 2025):
                sy, _, _ = _split_shift(
                    x, v, pd.Timestamp(f"{y}-08-25"), pd.Timestamp(f"{y}-06-01"), pd.Timestamp(f"{y}-12-31")
                )
                if np.isfinite(sy):
                    plac.append(sy)
            plac_a = np.asarray(plac)
            z = (
                (s25 - plac_a.mean()) / plac_a.std(ddof=1)
                if len(plac_a) >= 3 and np.isfinite(s25)
                else np.nan
            )
            rank = float((np.abs(plac_a) >= abs(s25)).mean()) if len(plac_a) and np.isfinite(s25) else np.nan
            rows.append(
                {
                    "지점": sid,
                    "대조(보)": WEIRS.get(c_code, LAKE.get(c_code, c_code)),
                    "변수": SCAN_VARS[v],
                    "var": v,
                    "최적 분할일": best[0].date().isoformat() if best[0] is not None else "",
                    "최적 분할 이동": round(best[2], 3) if np.isfinite(best[2]) else np.nan,
                    "08-25 분할 이동(2025)": round(s25, 3) if np.isfinite(s25) else np.nan,
                    "n(전/후)": f"{n_pre}/{n_post}",
                    "위약 연도 수": len(plac_a),
                    "위약 평균": round(float(plac_a.mean()), 3) if len(plac_a) else np.nan,
                    "위약 SD": round(float(plac_a.std(ddof=1)), 3) if len(plac_a) >= 2 else np.nan,
                    "z": round(float(z), 2) if np.isfinite(z) else np.nan,
                    "|위약|≥|2025| 비율": round(rank, 2) if np.isfinite(rank) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def method_2016_table(a: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    """2016-04 채수 방식 변경(층별 통합채수·투명도/탁도 추가)의 자료상 흔적과 v1 학습 행 영향."""
    rows = []
    bd = pd.to_datetime(base["base_date"])
    for sid in [*N_SITES, D_SITE]:
        s = a[a["site_code"] == CODE[sid]]
        first = {
            v: (s.loc[s[v].notna(), "obs_date"].min().date().isoformat() if s[v].notna().any() else "")
            for v in ("iem_bgalage_cell_co", "iem_wtrtp", "iem_trp", "iem_tur", "iem_chla")
        }
        tr = TRIAL_CODES.get(sid)
        t = a[a["site_code"] == tr] if tr else pd.DataFrame()
        rows.append(
            {
                "지점": f"{NAME[sid]}({sid})",
                "세포수 첫 측정": first["iem_bgalage_cell_co"],
                "수온 첫 측정": first["iem_wtrtp"],
                "투명도 첫 측정": first["iem_trp"],
                "탁도 첫 측정": first["iem_tur"],
                "Chl-a 첫 측정": first["iem_chla"],
                "v1 행(base<2016-04-01)": int(((base["station_id"] == sid) & (bd < "2016-04-01")).sum()),
                "v1 행(전체 ≤2025)": int((base["station_id"] == sid).sum()),
                "시범 코드(2013-02~2015-12)": (
                    f"{tr} {t['obs_date'].min().date()}~{t['obs_date'].max().date()} n={len(t)}"
                    if len(t)
                    else "-"
                ),
            }
        )
    for c, nm in [("2011A25", WEIRS["2011A25"]), ("2020A32", WEIRS["2020A32"])]:
        s = a[a["site_code"] == c]
        rows.append(
            {
                "지점": f"{nm}({c}) [대조]",
                "세포수 첫 측정": s.loc[s["iem_bgalage_cell_co"].notna(), "obs_date"]
                .min()
                .date()
                .isoformat(),
                "수온 첫 측정": s.loc[s["iem_wtrtp"].notna(), "obs_date"].min().date().isoformat(),
                "투명도 첫 측정": s.loc[s["iem_trp"].notna(), "obs_date"].min().date().isoformat(),
                "탁도 첫 측정": s.loc[s["iem_tur"].notna(), "obs_date"].min().date().isoformat(),
                "Chl-a 첫 측정": s.loc[s["iem_chla"].notna(), "obs_date"].min().date().isoformat(),
                "v1 행(base<2016-04-01)": 0,
                "v1 행(전체 ≤2025)": 0,
                "시범 코드(2013-02~2015-12)": "-",
            }
        )
    return pd.DataFrame(rows)


def method_2016_pairs(a: pd.DataFrame) -> pd.DataFrame:
    """2016-04 전후 짝 차이(서술용): 처리 지점(2013-02~2015-12 시범 코드 + 2016~ G 코드) − 인근 보, 6~10월.

    보 지점도 같은 시기 채수 방식이 바뀌었을 수 있어(2020-05 관찰지점 편입) 인과 추정이 아니라 표시용이다.
    회남은 같은 호수 추동·문의(같은 2016-04 변경 적용)와 비교한다.
    """
    rows = []
    eras = {"2013~2015(변경 전)": (2013, 2015), "2016-04~2019": (2016, 2019), "2020~2024": (2020, 2024)}
    for sid in [*TRIAL_CODES, D_SITE]:
        ctrl = NEIGHBORS.get(sid, list(LAKE))
        parts = []
        for c in ctrl:
            d = paired_diff(a, CODE[sid], c)
            if sid in TRIAL_CODES:
                d = pd.concat([paired_diff(a, TRIAL_CODES[sid], c), d], ignore_index=True)
            parts.append(d)
        d = pd.concat(parts, ignore_index=True)
        d = d[d["date"].dt.month.between(6, 10) & ~((d["date"] >= "2016-01-01") & (d["date"] < "2016-04-01"))]
        row = {"지점": f"{NAME[sid]}({sid})", "대조": ", ".join(WEIRS.get(c, LAKE.get(c, c)) for c in ctrl)}
        for lab, (y0, y1) in eras.items():
            x = d[d["date"].dt.year.between(y0, y1)]["lc"].dropna()
            row[f"{lab} 평균(n)"] = f"{x.mean():+.3f} ({len(x)})" if len(x) else ""
            row[f"{lab} SD"] = round(float(x.std(ddof=1)), 3) if len(x) > 1 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def confirm_dates(a: pd.DataFrame, scan: pd.DataFrame) -> pd.DataFrame:
    """지점별 확정 변경일 = 공식 '8월 말'(2025-08-25 주) 이후 그 지점의 첫 정기 채수일.

    자료 단절은 확정에 쓰지 않고 지지 여부만 표시한다(z 절댓값 ≥ 2 인 (대조, 변수) 조합 수).
    """
    rows = []
    for sid in N_SITES:
        s = a[(a["site_code"] == CODE[sid]) & (a["obs_date"] >= OFFICIAL_WINDOW_START)]
        first = s["obs_date"].min()
        around = a[
            (a["site_code"] == CODE[sid]) & (a["obs_date"] >= "2025-08-14") & (a["obs_date"] <= "2025-09-04")
        ]["obs_date"]
        sc = scan[scan["지점"] == sid]
        nz = int((sc["z"].abs() >= 2).sum())
        nz_lc = int(((sc["z"].abs() >= 2) & (sc["var"] == "lc")).sum())
        cps = sc["최적 분할일"].replace("", np.nan).dropna()
        n_cp_window = int(pd.to_datetime(cps).between("2025-08-18", "2025-09-08").sum())
        rows.append(
            {
                "지점": f"{NAME[sid]}({sid})",
                "확정 변경일": first.date().isoformat(),
                "근거 등급": "공식 문서·보도(월 단위 '2025-08 말') + 일 단위는 규칙(8월 말 첫 정기 채수일)",
                "8월 중순~9월 초 채수일": ", ".join(d.strftime("%m-%d") for d in around),
                "단절 지지(|z|≥2 조합/전체)": f"{nz}/{len(sc)} (세포수 {nz_lc})",
                "최적 분할일이 08-18~09-08 인 조합": f"{n_cp_window}/{len(cps)}",
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- b) DiD
def v1_residual_frame() -> pd.DataFrame:
    """v1 CV OOF(≤2025) log 잔차: ens(앙상블)·b0(지속성). 2020~2025 행만."""
    df, P = H.load_baseline()
    H.guard_no_2026(df)
    o = df[["station_id", "base_date", "target_date", "target_cells"]].copy()
    o["base_date"] = pd.to_datetime(o["base_date"])
    o["target_date"] = pd.to_datetime(o["target_date"])
    keep = (o["target_date"] <= LAST).to_numpy()  # 기준일 2025-12 → 목표일 2026-01 행은 즉시 버린다
    o, df = o[keep].copy(), df[keep]
    P = {k: np.asarray(v)[keep] for k, v in P.items()}
    o["ens"] = np.clip(P["ens"], 0, None)
    o["q10"], o["q90"] = P["q10"], P["q90"]
    o["b0"] = np.clip(10 ** df["cell_log_t0"].fillna(0).to_numpy(dtype=float) - 1, 0, None)
    o["e_ens"] = np.log10(o["target_cells"] + 1) - np.log10(o["ens"] + 1)
    o["e_b0"] = np.log10(o["target_cells"] + 1) - np.log10(o["b0"] + 1)
    o = o[o["ens"].notna() & o["target_cells"].notna()].reset_index(drop=True)
    if (o["target_date"] > LAST).any():
        raise RuntimeError("2026 목표일 행이 섞임")
    return o


def assign_period(
    dates: pd.Series, pre: tuple[pd.Timestamp, pd.Timestamp], post: tuple[pd.Timestamp, pd.Timestamp]
) -> pd.Series:
    d = pd.to_datetime(dates)
    out = pd.Series(np.full(len(d), None, dtype=object), index=d.index)
    out[(d >= pre[0]) & (d <= pre[1])] = "pre"
    out[(d >= post[0]) & (d <= post[1])] = "post"
    return out


def _stats_from_sums(S1: np.ndarray, S2: np.ndarray, n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = S1 / n
    var = (S2 - S1**2 / n) / (n - 1)
    return mean, var


def did_boot(
    frame: pd.DataFrame,
    value: str,
    treat: list[str],
    ctrl: list[str],
    *,
    site_ctrl: dict[str, list[str]] | None = None,
    n_boot: int = N_BOOT,
    seed: int = BOOT_SEED,
) -> dict:
    """평균·분산 DiD 와 지점×기간 층별 부트스트랩(백분위 95%).

    frame: site, period('pre'/'post'), value 열. 통합 평균은 처리 집단 행을 합친 평균(사전등록 2절).
    site_ctrl 이 있으면 지점별 Δ_s 의 대조를 지점마다 따로 둔다(없으면 ctrl 공통).
    부트스트랩: 생성기 np.random.default_rng(seed) 하나로 층 순서(처리→대조→지점별 대조, pre→post)대로 추출.
    """
    f = frame[frame["period"].isin(["pre", "post"])].dropna(subset=[value])
    extra = [c for v in (site_ctrl or {}).values() for c in v]
    sites = list(dict.fromkeys([*treat, *ctrl, *extra]))
    rng = np.random.default_rng(seed)
    S1, S2, N, B1, B2 = {}, {}, {}, {}, {}
    for s in sites:
        for p in ("pre", "post"):
            x = f[(f["site"] == s) & (f["period"] == p)][value].to_numpy(dtype=float)
            N[(s, p)] = len(x)
            S1[(s, p)], S2[(s, p)] = float(x.sum()), float((x**2).sum())
            if n_boot and len(x):
                idx = rng.integers(0, len(x), size=(n_boot, len(x)))
                xb = x[idx]
                B1[(s, p)], B2[(s, p)] = xb.sum(1), (xb**2).sum(1)

    def agg(group: list[str], p: str, boot: bool) -> tuple:
        if boot:
            s1 = sum(B1[(s, p)] for s in group)
            s2 = sum(B2[(s, p)] for s in group)
        else:
            s1 = np.array([sum(S1[(s, p)] for s in group)])
            s2 = np.array([sum(S2[(s, p)] for s in group)])
        n = np.array(float(sum(N[(s, p)] for s in group)))
        return _stats_from_sums(s1, s2, n)

    def change(group: list[str], boot: bool) -> tuple[np.ndarray, np.ndarray]:
        m0, v0 = agg(group, "pre", boot)
        m1, v1 = agg(group, "post", boot)
        return m1 - m0, np.log(v1 / v0)

    def did(tg: list[str], cg: list[str], boot: bool) -> tuple[np.ndarray, np.ndarray]:
        dm_t, dv_t = change(tg, boot)
        dm_c, dv_c = change(cg, boot)
        return dm_t - dm_c, dv_t - dv_c

    def summarize(tg: list[str], cg: list[str]) -> dict:
        ok = all(N[(s, p)] >= 2 for s in [*tg, *cg] for p in ("pre", "post"))
        if not ok:
            return {"mean": np.nan, "logvar": np.nan, "note": "표본 부족"}
        em, ev = did(tg, cg, False)
        out = {"mean": float(em[0]), "logvar": float(ev[0])}
        if n_boot:
            bm, bv = did(tg, cg, True)
            out["mean_ci"] = [float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))]
            out["logvar_ci"] = [float(np.percentile(bv, 2.5)), float(np.percentile(bv, 97.5))]
            out["mean_boot_var"] = float(np.var(bm, ddof=1))
        tm, tv = change(tg, False)
        cm, cv = change(cg, False)
        out.update(
            {
                "treat_mean_change": float(tm[0]),
                "ctrl_mean_change": float(cm[0]),
                "treat_logvar_change": float(tv[0]),
                "ctrl_logvar_change": float(cv[0]),
                "n_pre": int(sum(N[(s, "pre")] for s in tg)),
                "n_post": int(sum(N[(s, "post")] for s in tg)),
                "ctrl_n_pre": int(sum(N[(s, "pre")] for s in cg)),
                "ctrl_n_post": int(sum(N[(s, "post")] for s in cg)),
            }
        )
        return out

    res = {"pooled": summarize(treat, ctrl), "sites": {}, "treat": treat, "ctrl": ctrl}
    for s in treat:
        cg = (site_ctrl or {}).get(s, ctrl)
        res["sites"][s] = summarize([s], cg) | {"ctrl": cg}
    res["n"] = {f"{s}|{p}": N[(s, p)] for s in sites for p in ("pre", "post")}
    return res


def p2_condition(res: dict) -> dict:
    """사전등록 'P2 적용 조건': 지점별 Δ_s 부호 4지점 일치 + 통합 Δ 95% CI 0 미포함."""
    signs = {s: float(np.sign(res["sites"][s]["mean"])) for s in N_SITES}
    same = len(set(signs.values())) == 1 and 0.0 not in signs.values()
    lo, hi = res["pooled"]["mean_ci"]
    excl = bool(lo > 0 or hi < 0)
    return {
        "site_signs": signs,
        "signs_agree": bool(same),
        "pooled_ci_excludes_0": excl,
        "apply": bool(same and excl),
        "decision": "적용" if same and excl else "미적용(조건 미충족)",
    }


def _res_frame(
    o: pd.DataFrame, value: str, pre: tuple, post: tuple, *, by: str = "target_date"
) -> pd.DataFrame:
    f = pd.DataFrame({"site": o["station_id"].to_numpy(), value: o[value].to_numpy()})
    f["period"] = assign_period(o[by].reset_index(drop=True), pre, post).to_numpy()
    return f


def did_v1(o: pd.DataFrame, chg: dict[str, pd.Timestamp]) -> dict:
    """b) 본 분석(사전등록) + 민감도 + 위약 연도.

    사전등록 '2025 행' = 2025 폴드(기준일 2025, 학습 ≤2024) 행. 기준일 2024-12 → 목표일 2025-01 행은
    2024 폴드(학습 ≤2023)이므로 넣지 않는다. 위약 연도 Y 도 같은 규칙(기준일 Y 폴드 행).
    """
    out: dict = {}
    o_all = o
    o = o_all[o_all["base_date"].dt.year == H.FINAL_YEAR]
    f = _res_frame(o, "e_ens", PRE, POST)
    out["main"] = did_boot(f, "e_ens", N_SITES, [D_SITE])
    out["main"]["p2"] = p2_condition(out["main"])
    out["b0_main"] = did_boot(_res_frame(o, "e_b0", PRE, POST), "e_b0", N_SITES, [D_SITE])
    # 민감도 S1: 지점별 확정 변경일 분할(회남은 처리 지점과 같은 날짜 — 모두 2025-08-25)
    cut = min(chg.values())
    for val, key in (("e_ens", "s1_change_date"), ("e_b0", "b0_s1_change_date")):
        rows = []
        for s in [*N_SITES, D_SITE]:
            c = chg.get(s, cut)
            x = o[o["station_id"] == s]
            per = assign_period(
                x["target_date"].reset_index(drop=True),
                (PRE[0], c - pd.Timedelta(days=1)),
                (c, POST[1]),
            )
            rows.append(pd.DataFrame({"site": s, val: x[val].to_numpy(), "period": per.to_numpy()}))
        out[key] = did_boot(pd.concat(rows, ignore_index=True), val, N_SITES, [D_SITE])
    # 민감도 S2: S1 + 위치 경계를 건너는 행(base < 변경일 ≤ target) 제외
    for val, key in (("e_ens", "s2_no_crossing"), ("e_b0", "b0_s2_no_crossing")):
        rows = []
        for s in [*N_SITES, D_SITE]:
            c = chg.get(s, cut)
            x = o[o["station_id"] == s]
            x = x[~((x["base_date"] < c) & (x["target_date"] >= c))]
            per = assign_period(
                x["target_date"].reset_index(drop=True), (PRE[0], c - pd.Timedelta(days=1)), (c, POST[1])
            )
            rows.append(pd.DataFrame({"site": s, val: x[val].to_numpy(), "period": per.to_numpy()}))
        out[key] = did_boot(pd.concat(rows, ignore_index=True), val, N_SITES, [D_SITE])
    # 위약 연도(같은 달력, CV OOF 2020~2024): 점추정만
    plac = {}
    for val in ("e_ens", "e_b0"):
        plac[val] = {}
        for y in range(2020, 2026):
            pre_y = (pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-08-31"))
            post_y = (pd.Timestamp(f"{y}-09-01"), pd.Timestamp(f"{y}-10-31"))
            oy = o_all[o_all["base_date"].dt.year == y]
            r = did_boot(_res_frame(oy, val, pre_y, post_y), val, N_SITES, [D_SITE], n_boot=0)
            plac[val][y] = {
                "pooled_mean": r["pooled"]["mean"],
                "pooled_logvar": r["pooled"]["logvar"],
                **{f"{s}_mean": r["sites"][s]["mean"] for s in N_SITES},
            }
    out["placebo_years"] = plac
    return out


# ---------------------------------------------------------------- c) 모델과 무관한 잔차
def modelfree_residuals(a: pd.DataFrame) -> pd.DataFrame:
    """모든 대상·대조 지점의 (1) 7일 지속성 잔차(대회 매칭 규칙 +7±3일, 동률은 이른 날),
    (2) 지점·월 기후값(2020~2024 평균 log10 세포수) 편차. 측정일 ≤ 2025-12-31."""
    codes = {**{CODE[s]: s for s in [*N_SITES, D_SITE]}, **{c: c for c in WEIRS}, **{c: c for c in LAKE}}
    rows = []
    for code, site in codes.items():
        s = a[(a["site_code"] == code) & a["lc"].notna()][["obs_date", "lc"]].sort_values("obs_date")
        dates = pd.DatetimeIndex(s["obs_date"])
        lc = pd.Series(s["lc"].to_numpy(), index=dates)
        clim_src = s[s["obs_date"].dt.year.between(2020, 2024)]
        clim = clim_src.groupby(clim_src["obs_date"].dt.month)["lc"].mean()
        for d, v in lc.items():
            t = match_target(d, dates, 7, 3)
            rows.append(
                {
                    "site": site,
                    "code": code,
                    "obs_date": d,
                    "lc": v,
                    "target_date": t,
                    "e_pers": (lc[t] - v) if t is not None else np.nan,
                    "e_clim": v - clim.get(d.month, np.nan),
                }
            )
    return pd.DataFrame(rows)


def did_modelfree(m: pd.DataFrame) -> dict:
    """c) 대조 집단별 DiD(지속성 잔차는 목표일, 기후 편차는 측정일 기준 기간)."""
    sets = {"회남": [D_SITE], "낙동강 보 관찰지점 8": list(WEIRS), "대청호 추동·문의": list(LAKE)}
    out: dict = {}
    for val, by in (("e_pers", "target_date"), ("e_clim", "obs_date")):
        mm = m.dropna(subset=[val, by]).copy()
        f = pd.DataFrame({"site": mm["site"].to_numpy(), val: mm[val].to_numpy()})
        f["period"] = assign_period(mm[by].reset_index(drop=True), PRE, POST).to_numpy()
        out[val] = {}
        for nm, cg in sets.items():
            out[val][nm] = did_boot(f, val, N_SITES, cg)
        out[val]["인근 보(지점별)"] = did_boot(f, val, N_SITES, list(WEIRS), site_ctrl=NEIGHBORS)
        plac = {}
        for y in range(2020, 2026):
            pre_y = (pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-08-31"))
            post_y = (pd.Timestamp(f"{y}-09-01"), pd.Timestamp(f"{y}-10-31"))
            fy = pd.DataFrame({"site": mm["site"].to_numpy(), val: mm[val].to_numpy()})
            fy["period"] = assign_period(mm[by].reset_index(drop=True), pre_y, post_y).to_numpy()
            plac[y] = {}
            for nm, cg in sets.items():
                r = did_boot(fy, val, N_SITES, cg, n_boot=0)
                plac[y][nm] = {"pooled_mean": r["pooled"]["mean"], "pooled_logvar": r["pooled"]["logvar"]}
            r = did_boot(fy, val, N_SITES, list(WEIRS), site_ctrl=NEIGHBORS, n_boot=0)
            plac[y]["인근 보(지점별)"] = {f"{s}_mean": r["sites"][s]["mean"] for s in N_SITES}
        out[val]["placebo_years"] = plac
    return out


# ---------------------------------------------------------------- d) 수준·변동성
def pilot_pairs(a: pd.DataFrame) -> pd.DataFrame:
    """2022~2023 시범 지점(취수구 500 m 상류) − 공식 지점(옛 위치) 짝 차이 요약(같은 날 ±1일)."""
    rng = np.random.default_rng(BOOT_SEED)
    rows = []
    combos = []
    for sid, pil in PILOTS.items():
        for code, nm in pil.items():
            combos.append((sid, code, CODE[sid], f"{nm} − {NAME[sid]}(공식, 옛 위치)"))
        codes = list(pil)
        combos.append((sid, codes[1], codes[0], f"{pil[codes[1]]} − {pil[codes[0]]}"))
    for sid, t, c, lab in combos:
        d = paired_diff(a, t, c, tol=1)
        for v in ("lc", "iem_wtrtp", "ltur", "iem_trp", "iem_ph"):
            x = d[v].dropna().to_numpy()
            if len(x) < 5:
                continue
            bm = x[rng.integers(0, len(x), size=(N_BOOT, len(x)))].mean(1)
            rows.append(
                {
                    "지점": sid,
                    "비교": lab,
                    "변수": SCAN_VARS[v],
                    "n": len(x),
                    "기간": f"{d['date'].min().date()}~{d['date'].max().date()}",
                    "평균 차": round(float(x.mean()), 3),
                    "95% CI": f"[{np.percentile(bm, 2.5):.3f}, {np.percentile(bm, 97.5):.3f}]",
                    "차의 SD": round(float(x.std(ddof=1)), 3),
                    "중앙값": round(float(np.median(x)), 3),
                }
            )
    return pd.DataFrame(rows)


def level_variability_table(m: pd.DataFrame) -> pd.DataFrame:
    """9~10월: 2025(새 위치) vs 2020~2024(옛 위치) — 기후 편차 평균, 0값 비율, 주간 변동(SD of e_pers)."""
    groups = {
        **{s: [s] for s in [*N_SITES, D_SITE]},
        "보 관찰지점 8": list(WEIRS),
        "대청호 추동·문의": list(LAKE),
    }
    rows = []
    for g, members in groups.items():
        x = m[m["site"].isin(members)]
        so = x["obs_date"].dt.month.isin([9, 10])
        ja = x["obs_date"].dt.month.between(1, 8)
        h = x[so & x["obs_date"].dt.year.between(2020, 2024)]
        n = x[so & (x["obs_date"].dt.year == 2025)]
        p = x[ja & (x["obs_date"].dt.year == 2025)]
        hp = x[ja & x["obs_date"].dt.year.between(2020, 2024)]
        rows.append(
            {
                "집단": g,
                "n 9~10월(2025/과거)": f"{len(n)}/{len(h)}",
                "기후 편차 1~8월 2025": round(float(p["e_clim"].mean()), 3),
                "기후 편차 9~10월 2025": round(float(n["e_clim"].mean()), 3),
                "0값 비율 9~10월 2025": round(float((n["lc"] == 0).mean()), 3),
                "0값 비율 9~10월 과거": round(float((h["lc"] == 0).mean()), 3),
                "주간 변동 SD 9~10월 2025": round(float(n["e_pers"].std(ddof=1)), 3),
                "주간 변동 SD 9~10월 과거": round(float(h["e_pers"].std(ddof=1)), 3),
                "주간 변동 SD 1~8월 2025": round(float(p["e_pers"].std(ddof=1)), 3),
                "주간 변동 SD 1~8월 과거": round(float(hp["e_pers"].std(ddof=1)), 3),
            }
        )
    return pd.DataFrame(rows)


def skill_by_period(o: pd.DataFrame) -> pd.DataFrame:
    """연도·구간별 v1 앙상블 vs 지속성(B0) 성능 — 낙동강 4지점 통합과 회남(목표일 기준)."""
    rows = []
    for grp, sites in (("낙동강 4", N_SITES), ("회남", [D_SITE])):
        for y in range(2020, 2026):
            for lab, months in (("1~8월", range(1, 9)), ("9~10월", (9, 10))):
                x = o[
                    o["station_id"].isin(sites)
                    & (o["base_date"].dt.year == y)  # 폴드 y 행만(학습 ≤ y−1)
                    & (o["target_date"].dt.year == y)
                    & o["target_date"].dt.month.isin(list(months))
                ]
                if len(x) < 5:
                    continue
                obs = x["target_cells"].to_numpy(dtype=float)
                me = compute_all(obs, x["ens"].to_numpy(), x["q10"].to_numpy(), x["q90"].to_numpy())
                mb = compute_all(obs, x["b0"].to_numpy())
                rows.append(
                    {
                        "집단": grp,
                        "연도": y,
                        "구간": lab,
                        "n": len(x),
                        "관측≥10k": int((obs >= 10_000).sum()),
                        "rmse_log 앙상블": round(me["rmse_log"], 3),
                        "rmse_log B0": round(mb["rmse_log"], 3),
                        "r2_log 앙상블": round(me["r2_log"], 3),
                        "r2_log B0": round(mb["r2_log"], 3),
                        "F1@10k 앙상블": round(me["f1_10k"], 3),
                        "F1@10k B0": round(mb["f1_10k"], 3),
                        "구간 적중(q10~q90)": round(me["picp80"], 3),
                        "평균 잔차(앙상블)": round(float(x["e_ens"].mean()), 3),
                    }
                )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 그림(집계)
def _setup_fonts() -> None:
    for f in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
        if any(ft.name == f for ft in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False


INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SER = ["#2a78d6", "#eb6834", "#1baf7a"]


def fig_forest(b: dict, path: Path) -> None:
    """평균 DiD(통합·지점별) — 본 분석·민감도·B0 + 위약 연도 점."""
    _setup_fonts()
    labels = ["통합", *[f"{NAME[s]}" for s in N_SITES]]
    keys = [
        ("main", "사전등록 본 분석(v1, 9/1 분할)"),
        ("s2_no_crossing", "민감도: 8/25 분할·경계 행 제외"),
        ("b0_main", "B0 지속성 잔차"),
    ]
    fig, ax = plt.subplots(figsize=(7.6, 4.2), dpi=150)
    ypos = np.arange(len(labels))[::-1].astype(float)
    for k, (key, lab) in enumerate(keys):
        r = b[key]
        ests = [r["pooled"]["mean"], *[r["sites"][s]["mean"] for s in N_SITES]]
        cis = [r["pooled"]["mean_ci"], *[r["sites"][s]["mean_ci"] for s in N_SITES]]
        yy = ypos + (1 - k) * 0.22
        for y, (lo, hi) in zip(yy, cis, strict=True):
            ax.plot([lo, hi], [y, y], color=SER[k], lw=2, solid_capstyle="round")
        ax.scatter(ests, yy, s=36, color=SER[k], zorder=3, label=lab, edgecolor="white", linewidth=1.2)
    plac = b["placebo_years"]["e_ens"]
    for y in range(2020, 2025):
        vals = [plac[y]["pooled_mean"], *[plac[y][f"{s}_mean"] for s in N_SITES]]
        ax.scatter(vals, ypos - 0.38, s=12, color="#9a9890", marker="|", zorder=2)
    ax.scatter([], [], s=12, color="#9a9890", marker="|", label="위약 연도 2020~2024(v1 OOF, 같은 달력)")
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(ypos, labels, color=INK)
    ax.set_xlabel("평균 DiD (log10, 9~10월 - 1~8월, 회남 대조)", color=INK2)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.legend(fontsize=7.5, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    ax.set_title(
        "2025 채수 위치 변경 전후 잔차 차이의 차이(95% 부트스트랩 구간)", fontsize=10, color=INK, pad=34
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_paired_monthly(pairs: pd.DataFrame, path: Path) -> None:
    """처리 지점 − 인근 보 log10 세포수 짝 차이의 월평균: 2025 vs 2020~2024(연도별 월평균의 평균 ± SD)."""
    _setup_fonts()
    fig, axes = plt.subplots(2, 2, figsize=(8, 5.2), dpi=150, sharey=True)
    for ax, sid in zip(axes.ravel(), N_SITES, strict=True):
        x = pairs[(pairs["t_code"] == CODE[sid]) & pairs["c_code"].isin(NEIGHBORS[sid])].copy()
        x["y"], x["m"] = x["date"].dt.year, x["date"].dt.month
        hist = x[x["y"].between(2020, 2024)].groupby(["y", "m"])["lc"].mean().unstack(0)
        mu, sd = hist.mean(1), hist.std(1)
        cur = x[x["y"] == 2025].groupby("m")["lc"].mean()
        ax.fill_between(mu.index, mu - sd, mu + sd, color="#d9d8d2", lw=0)
        ax.plot(mu.index, mu.to_numpy(), color="#8a887f", lw=2, label="2020~2024 평균 ± SD")
        ax.plot(cur.index, cur.to_numpy(), color=SER[0], lw=2, marker="o", ms=4, label="2025")
        ax.axvline(8 + 25 / 31, color=SER[1], lw=1.2, ls="--")
        ax.axhline(0, color=GRID, lw=1)
        ax.set_title(f"{NAME[sid]} - {', '.join(WEIRS[c] for c in NEIGHBORS[sid])}", fontsize=8.5, color=INK)
        ax.set_xticks(range(1, 13))
        ax.tick_params(labelsize=7, colors=INK2)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0, 0].legend(fontsize=7, frameon=False)
    fig.supylabel("log10 세포수 짝 차이(처리 - 인근 보)", fontsize=8.5, color=INK2)
    fig.suptitle(
        "인근 보 관찰지점 대비 월평균 차이 — 점선: 2025-08-25(새 위치 시작)", fontsize=9.5, color=INK
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------- 표·저장
def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.to_numpy()) + " |")
    return "\n".join(lines)


def _f(v: float, nd: int = 3) -> str:
    return "" if v is None or not np.isfinite(v) else f"{v:+.{nd}f}"


def did_table(res: dict, label: str) -> pd.DataFrame:
    rows = []
    for key, r in [("통합(4지점)", res["pooled"]), *[(f"{NAME[s]}({s})", res["sites"][s]) for s in N_SITES]]:
        ci = r.get("mean_ci", [np.nan, np.nan])
        vci = r.get("logvar_ci", [np.nan, np.nan])
        rows.append(
            {
                "분석": label,
                "대상": key,
                "n 전/후": f"{r.get('n_pre', '')}/{r.get('n_post', '')}",
                "대조 n 전/후": f"{r.get('ctrl_n_pre', '')}/{r.get('ctrl_n_post', '')}",
                "처리 평균 변화": _f(r.get("treat_mean_change", np.nan)),
                "대조 평균 변화": _f(r.get("ctrl_mean_change", np.nan)),
                "평균 DiD": _f(r["mean"]),
                "95% CI": f"[{_f(ci[0])}, {_f(ci[1])}]",
                "분산 DiD(ln 비)": _f(r["logvar"], 2),
                "분산 95% CI": f"[{_f(vci[0], 2)}, {_f(vci[1], 2)}]",
            }
        )
    return pd.DataFrame(rows)


def placebo_table(plac: dict, cols: list[str]) -> pd.DataFrame:
    rows = []
    for y, r in plac.items():
        rows.append({"연도": y, **{c: _f(r.get(c, np.nan)) for c in cols}})
    return pd.DataFrame(rows)


def placebo_z(plac: dict, label: str) -> pd.DataFrame:
    """2025 값을 2020~2024 위약 연도 분포와 비교: z = (2025 − 평균)/SD, |위약| ≥ |2025| 인 연도 수."""
    rows = []
    keys = [k for k in plac[2025] if np.isfinite(plac[2025][k])]
    for k in keys:
        ref = np.array([plac[y][k] for y in range(2020, 2025) if np.isfinite(plac[y].get(k, np.nan))])
        v = plac[2025][k]
        z = (v - ref.mean()) / ref.std(ddof=1) if len(ref) >= 3 else np.nan
        rows.append(
            {
                "잔차·대조": label,
                "항목": k,
                "2025": _f(v),
                "위약 범위(2020~2024)": f"[{_f(ref.min())}, {_f(ref.max())}]",
                "z": round(float(z), 2) if np.isfinite(z) else np.nan,
                "|위약|≥|2025| 연도 수": f"{int((np.abs(ref) >= abs(v)).sum())}/{len(ref)}",
            }
        )
    return pd.DataFrame(rows)


def _jsonable(o: object) -> object:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating | float):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, pd.Timestamp):
        return o.date().isoformat()
    return o


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    OUT_REP.mkdir(parents=True, exist_ok=True)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    a = load_algae_all()
    bundle = load_bundle_measure()
    base_df, _ = H.load_baseline()

    # a)
    tags = api_tag_inventory()
    fields = field_table(a, bundle)
    coords = coords_table()
    sched = schedule_table(a)
    pairs = pd.concat(
        [paired_diff(a, CODE[s], c) for s in N_SITES for c in NEIGHBORS[s]]
        + [paired_diff(a, CODE[D_SITE], c) for c in LAKE],
        ignore_index=True,
    )
    pairs.to_parquet(OUT_DATA / "paired_diffs.parquet", index=False)
    scan = break_scan(pairs)
    m2016 = method_2016_table(a, base_df)
    m2016p = method_2016_pairs(a)
    conf = confirm_dates(a, scan)
    chg = {s: pd.Timestamp(d) for s, d in zip(N_SITES, conf["확정 변경일"], strict=True)}
    _check_budget()

    # b)
    o = v1_residual_frame()
    o.to_parquet(OUT_DATA / "v1_residuals_2020_2025.parquet", index=False)
    b = did_v1(o, chg)
    _check_budget()

    # c)
    m = modelfree_residuals(a)
    m.to_parquet(OUT_DATA / "modelfree_residuals.parquet", index=False)
    c = did_modelfree(m)
    _check_budget()

    # d)
    pil = pilot_pairs(a)
    lv = level_variability_table(m)
    sk = skill_by_period(o)

    fig_forest(b, OUT_REP / "did_forest.png")
    fig_paired_monthly(pairs, OUT_REP / "paired_monthly.png")

    results = {
        "generated": pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds"),
        "prereg": "reports/experiments/EXP-005/PREREG_P2.md 2절",
        "bootstrap": {"n": N_BOOT, "seed": BOOT_SEED, "strata": "지점×기간", "ci": "백분위 95%"},
        "periods": {"pre": [PRE[0], PRE[1]], "post": [POST[0], POST[1]], "basis": "target_date"},
        "change_dates": {s: chg[s] for s in N_SITES},
        "api_tags": tags,
        "p2_condition": b["main"]["p2"],
        "did_v1": b,
        "did_modelfree": c,
        "confirm_dates_table": conf.to_dict(orient="records"),
        "pilot_pairs": pil.to_dict(orient="records"),
        "level_variability": lv.to_dict(orient="records"),
        "skill_by_period": sk.to_dict(orient="records"),
    }

    # 자동 표(README 가 인용)
    t = ["# P0 자동 표 (r2nd_p0_location.main 이 생성 — 손으로 고치지 않는다)\n"]
    t.append("## a-1. 조사위치 필드(≤2025)\n\n" + _md(fields))
    t.append(
        f"\nAPI item 태그({tags['n_items_le_2025']} item, 캐시 {tags['n_files']} 파일): {', '.join(tags['tags'])}\n좌표류 태그: {tags['coordinate_like_tags'] or '없음'}\n"
    )
    t.append("## a-2. 매뉴얼(2025.8) 새 위치 좌표\n\n" + _md(coords))
    t.append("## a-3. 문서 근거\n\n" + _md(pd.DataFrame(DOC_FACTS)))
    t.append("## a-4. 채수 일정\n\n" + _md(sched))
    t.append(
        "## a-5. 짝 차이 단절 탐색(처리 − 인근 보, 2025-06~12, 8/25 분할 vs 과거 연도 위약)\n\n"
        + _md(scan.drop(columns=["var"]))
    )
    t.append("## a-6. 확정 변경일\n\n" + _md(conf))
    t.append("## a-7. 2016-04 채수 방식 변경 표시\n\n" + _md(m2016))
    t.append("\n6~10월 짝 차이(log10 세포수, 처리 − 대조) 시기별 — 서술용:\n\n" + _md(m2016p))
    dt = pd.concat(
        [
            did_table(b["main"], "본 분석(사전등록)"),
            did_table(b["s1_change_date"], "민감도 S1: 8/25 분할"),
            did_table(b["s2_no_crossing"], "민감도 S2: 8/25 분할·경계 행 제외"),
            did_table(b["b0_main"], "민감도 S3: B0 잔차"),
            did_table(b["b0_s2_no_crossing"], "민감도 S4: B0·8/25·경계 제외"),
        ],
        ignore_index=True,
    )
    t.append("## b-1. v1 잔차 DiD(낙동강 4 vs 회남)\n\n" + _md(dt))
    p2 = b["main"]["p2"]
    t.append(
        f"\nP2 적용 조건: 부호 {p2['site_signs']} 일치={p2['signs_agree']}, 통합 CI 0 미포함={p2['pooled_ci_excludes_0']} → **{p2['decision']}**\n"
    )
    cols = ["pooled_mean", "pooled_logvar", *[f"{s}_mean" for s in N_SITES]]
    t.append(
        "## b-2. 위약 연도(같은 달력: 9~10월 − 1~8월, v1 앙상블 잔차)\n\n"
        + _md(placebo_table(b["placebo_years"]["e_ens"], cols))
    )
    t.append("\nB0 잔차:\n\n" + _md(placebo_table(b["placebo_years"]["e_b0"], cols)))
    mf = []
    for val, lab in (("e_clim", "기후 편차"), ("e_pers", "7일 지속성 잔차")):
        for nm in ("회남", "낙동강 보 관찰지점 8", "대청호 추동·문의", "인근 보(지점별)"):
            mf.append(did_table(c[val][nm], f"{lab} | 대조: {nm}"))
    t.append("## c-1. 모델과 무관한 잔차 DiD\n\n" + _md(pd.concat(mf, ignore_index=True)))
    for val, lab in (("e_clim", "기후 편차"), ("e_pers", "7일 지속성 잔차")):
        rows = []
        for y, r in c[val]["placebo_years"].items():
            row = {"연도": y}
            for nm in ("회남", "낙동강 보 관찰지점 8", "대청호 추동·문의"):
                row[f"{nm} 평균"] = _f(r[nm]["pooled_mean"])
                row[f"{nm} 분산"] = _f(r[nm]["pooled_logvar"], 2)
            for s in N_SITES:
                row[f"{s}(인근 보)"] = _f(r["인근 보(지점별)"][f"{s}_mean"])
            rows.append(row)
        t.append(f"\n{lab} 위약 연도:\n\n" + _md(pd.DataFrame(rows)))
    zt = [
        placebo_z(b["placebo_years"]["e_ens"], "v1 앙상블 | 회남"),
        placebo_z(b["placebo_years"]["e_b0"], "B0 | 회남"),
    ]
    for val, lab in (("e_clim", "기후 편차"), ("e_pers", "7일 지속성")):
        pl = c[val]["placebo_years"]
        for nm in ("회남", "낙동강 보 관찰지점 8", "대청호 추동·문의", "인근 보(지점별)"):
            zt.append(placebo_z({y: pl[y][nm] for y in pl}, f"{lab} | {nm}"))
    zdf = pd.concat(zt, ignore_index=True)
    t.append(
        "## c-2. 2025 DiD 의 위약 연도 대비 위치(z, 같은 정의를 2020~2024 각 연도에 적용)\n\n" + _md(zdf)
    )
    t.append("## d-1. 시범 지점(취수구 500 m 상류, 2022~2023) 짝 비교\n\n" + _md(pil))
    t.append("## d-2. 수준·0값·주간 변동(9~10월 2025 vs 2020~2024)\n\n" + _md(lv))
    t.append("## d-3. 연도·구간별 v1 앙상블 vs B0(목표일 기준)\n\n" + _md(sk))
    (OUT_REP / "tables.md").write_text("\n\n".join(t) + "\n", encoding="utf-8")
    results["placebo_z"] = zdf.to_dict(orient="records")
    results["elapsed_h_run"] = _elapsed_h()
    (OUT_REP / "results.json").write_text(
        json.dumps(_jsonable(results), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    log.info("P0 완료 %.2f h, P2 판정: %s", _elapsed_h(), p2["decision"])
    print(json.dumps(_jsonable({"p2": p2, "pooled": b["main"]["pooled"]}), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
