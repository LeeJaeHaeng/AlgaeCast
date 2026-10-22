# ruff: noqa: E501  (한국어 표 머리글·보고서 문자열)
"""EXP-005(2차) P6 — 상류 댐 호소 지점의 최근 세포수 × 댐 방류량을 하류 지점 피처로 연결.

사용자 지시: R5 에서 수집한 전국 조류경보 지점(82개) 중 상류 댐 호소 지점의 최근 세포수와 해당 댐 방류량을 하류
지점 피처로 연결한다. 기준 모델 C(v1 로그 앙상블 + R2 상류 피처 5열 + R3 속별 구성원, 분위 v1 동결)에 새 열을 더해
탐색 시드 5개(harness2.EXPLORE_SEEDS)와 같은 결측 위치의 난수 대조군으로 평가한다.

연결 표(LINKS, 거리·이동시간은 가정 — README 표 참고)
- 해평(HP)·강정·고령(GJGR): 상류 댐(안동·임하·영주·군위·성덕·김천부항) 호소에 조류경보 지점이 없다 → 새 열 모두 NaN.
- 칠서(CS): 영천호(2012G20) × 영천댐(금호강 경유, 확실), 진양호(2018G20·2018G30) × 남강댐(남강 합류점과 측정지점의
  상대 위치 미확인 — sites.yaml upstream_dams_uncertain).
- 물금·매리(MGMR): 영천호 × 영천댐, 진양호 × 남강댐, 운문호(2021G10·2021G20) × 운문댐(동창천 → 밀양강 경유).
- 회남(DCHN, 대청호 자체가 호소): 상류 호소 지점 용담호(3001G20·3001G40) × 용담댐(금강 본류).
- 제외: 공산지(2012G55·2012G56, 대구 공산댐 — 방류 자료 없음), 밀양댐(호소 조류 지점 없음).

댐 방류 = 하천 방류 q_river = 총방류량 tdqty − 취수량 itqty(도수로로 빠지는 생활·공업용수 제외, 0 이상).
남강·용담은 기존 수문 자료(data/raw/hydro/hydro_daily_long.parquet, v1 align 과 같은 소스 우선순위), 영천·운문은
새 수집(collect/wamis_extra_dams.py, WAMIS mn_dtdata 2012~2025)이다. 남강댐 tdqty 에는 사천만(가화천) 방류가
섞여 있어 분리하지 못한다(한계).

새 피처(하류 지점 s, 기준일 as_of, 연결 r ∈ LINKS[s], lag_r = 0 또는 이동시간 기반)
- 연결 r: c_r = 호소 지점들의 obs_date ≤ as_of − lag_r 최근 유효 세포수(지점별 최근값의 최대, 경과 ≤ MAX_STALE+lag 일),
  q_r = [as_of − lag_r − 6, as_of − lag_r] 하천 방류 평균(유효 4일 이상), 플럭스 f_r = c_r · q_r.
- dam_cell_log    = log10(Σ f_r / Σ q_r + 1)   방류 가중 세포수(방류수의 평균 농도) — "최근 세포수"
- dam_days        = max_r (as_of − 사용한 측정일)  — "경과일"
- dam_q_log       = log10(Σ q_r + 1)            — "방류량"(7일 평균, ㎥/s)
- dam_load_log    = log10(Σ f_r + 1)            — "곱"(세포수 × 방류량 플럭스, cells/mL·㎥/s)
- dam_contrib_log = log10(Σ f_r / max(Q_down, 1) + 1)  희석 기여 농도(하류 시설 7일 평균 유량으로 나눔:
  CS 창녕함안보·MGMR 하굿둑 방류량, DCHN 대청댐 유입량; data/interim/daily_<지점>_S1 읽기 전용)

as_of 규칙: make_dam_features·link_state 는 진입 직후 features.base.cut_as_of 로 as_of 이후 행을 버리고, lag 이 있으면
as_of − lag 로 한 번 더 자른다. 원자료는 읽은 즉시 2025-12-31 이후 측정을 버린다(harness.LAST_DATE).

공개 함수(종합 단계 재사용)
- build_features(df) -> DataFrame: df = harness.load_base() 형식, 선택 설정(CHOSEN)의 새 열(같은 인덱스).
- members(df, seed) -> dict: C + 선택 피처의 회귀 구성원 OOF(c1·c1_none·c1_log·c3·c2·cg·cg_*).
- builder(df, seed) -> {"pred", "q90"(None = v1 동결), "m_c1"...}: harness2.Builder 형식.
- make_dam_features(algae, release, down, as_of, station_id, lag_mode, horizon_days) -> dict: 순수 함수(행 하나).

실행: python -m algaecast.exp.r2nd_p6_damres → reports/experiments/EXP-005/P6/(tables.md·metrics.json),
행 단위 중간물 data/processed/exp/EXP-005b/P6/, 구성별 OOF 캐시 data/processed/exp/EXP-005b/cache/P6_*.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, RAW_DIR
from algaecast.eval.metrics import compute_all
from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.features.base import cut_as_of, window_days

log = logging.getLogger(__name__)

PX = "P6"
OUT_DATA = H2.EXP_DIR / PX
OUT_REPORT = H2.REPORT_DIR / PX
BUDGET_HOURS = 4.0
TASK_START = "2026-10-22 12:11:58"  # 작업 착수(KST) — 시간 상한 기준
ALGAE_ALL = RAW_DIR / "nier_algae_all" / "nier_algae_all_2012_2026.parquet"
HYDRO_LONG = RAW_DIR / "hydro" / "hydro_daily_long.parquet"
EXTRA_DAMS = RAW_DIR / "wamis_dam_extra" / "wamis_dam_extra_daily.parquet"
INTERIM = DATA_DIR / "interim"
HYDRO_SRC_PRIORITY = {"bundle_wamis": 0, "kwater_sluice_delist": 1, "wamis_mn_dtdata": 2, "kwater_damapi": 3}

REL_WINDOW = 7  # 방류 평균 창(일)
MIN_VALID = 4  # 창 안 유효 일수 하한
MAX_STALE = 35  # 호소 측정 경과일 상한(일) — 넘으면 결측
LAG_CAP = 28
Q_DOWN_FLOOR = 1.0  # ㎥/s
V_TRIB_KMD = 43.2  # 자유 흐름 지류 0.5 m/s
V_MAIN_KMD = 8.64  # 보로 막힌 낙동강 본류 0.1 m/s
V_LAKE_KMD = 4.32  # 호소 상류부 0.05 m/s

COLS: tuple[str, ...] = ("dam_cell_log", "dam_days", "dam_q_log", "dam_load_log", "dam_contrib_log")
BUNDLES: dict[str, tuple[str, ...]] = {
    "core4": ("dam_cell_log", "dam_days", "dam_q_log", "dam_load_log"),
    "core5": COLS,
    "load2": ("dam_load_log", "dam_contrib_log"),
}
LAG_MODES: tuple[str, ...] = ("0", "travel")
LINK_SETS: tuple[str, ...] = ("all", "certain")


@dataclass(frozen=True)
class Link:
    """상류 댐 호소 지점 → 하류 지점 연결 하나(거리는 가정, km)."""

    reservoir: str
    sites: tuple[str, ...]  # 조류경보 지점 코드(nier_algae_all site_code)
    dam_code: str
    dam_name: str
    trib_km: float  # 댐 → 본류 합류(자유 흐름 지류)
    main_km: float  # 합류 → 하류 지점(보로 막힌 본류)
    lake_km: float  # 호소 상류 끝 → 하류 지점(호소 구간)
    certain: bool
    via: str

    @property
    def km(self) -> float:
        return self.trib_km + self.main_km + self.lake_km

    @property
    def travel_days(self) -> float:
        return self.trib_km / V_TRIB_KMD + self.main_km / V_MAIN_KMD + self.lake_km / V_LAKE_KMD


_YC = ("영천호", ("2012G20",), "2012210", "영천")
_NG = ("진양호", ("2018G20", "2018G30"), "2018110", "남강")
_UM = ("운문호", ("2021G10", "2021G20"), "2021210", "운문")
_YD = ("용담호", ("3001G20", "3001G40"), "3001110", "용담")

# 거리 가정: 강정고령보→칠서 87 km·칠서→물금매리 60 km 는 R2(r2_upstream.RIVER_KM, sites.yaml 검증 거리) 값,
# 나머지(지류 구간·호소 구간)는 지도 기준 대략값(±30%, 미검증).
LINKS: dict[str, tuple[Link, ...]] = {
    "HP": (),
    "GJGR": (),
    "CS": (
        Link(*_YC, trib_km=95, main_km=87, lake_km=0, certain=True, via="자호천→금호강→낙동강(강정고령보)"),
        Link(
            *_NG,
            trib_km=75,
            main_km=2,
            lake_km=0,
            certain=False,
            via="남강→낙동강(남지, 측정지점과의 상하류 미확인)",
        ),
    ),
    "MGMR": (
        Link(*_YC, trib_km=95, main_km=147, lake_km=0, certain=True, via="자호천→금호강→낙동강"),
        Link(*_NG, trib_km=75, main_km=62, lake_km=0, certain=True, via="남강→낙동강(남지)→칠서→물금·매리"),
        Link(*_UM, trib_km=55, main_km=11, lake_km=0, certain=True, via="동창천→밀양강→낙동강(삼랑진)"),
    ),
    "DCHN": (Link(*_YD, trib_km=105, main_km=0, lake_km=20, certain=True, via="금강 본류→대청호 상류부"),),
}
EXCLUDED_NOTES: tuple[str, ...] = (
    "해평·강정·고령: 상류 다목적댐(안동·임하·영주·군위·성덕·김천부항) 호소에 조류경보 지점이 없다(82지점 목록 확인).",
    "공산지(2012G55·2012G56, 대구 공산댐 → 동화천 → 금호강): 방류 자료가 없어 제외.",
    "밀양댐(2021110): 방류 자료는 있으나 밀양호에 조류경보 지점이 없어 제외.",
    "대청호 추동·문의(3008G40·3008G50): 회남의 하류(같은 호소)라 상류 연결 대상이 아니다.",
)

# 변형: 이름 → (lag 방식, 연결 집합, 묶음). 첫 행이 사용자 지시 그대로의 기본 구성.
VARIANTS: dict[str, tuple[str, str, str]] = {
    "core4_lag0_all": ("0", "all", "core4"),
    "core5_lag0_all": ("0", "all", "core5"),
    "load2_lag0_all": ("0", "all", "load2"),
    "core4_travel_all": ("travel", "all", "core4"),
    "core4_lag0_certain": ("0", "certain", "core4"),
}
# main() 의 CV 선택 결과로 고정(다르면 main 이 경고). build_features·builder 기본값.
# 2026-10-22 main() 결과: CV 기준(Δ ≥ +0.08·대조 대비 ≥ +0.04)을 만족한 변형이 없어 고유 효과 최대 변형('기준 미달').
CHOSEN: dict[str, str] = {"variant": "load2_lag0_all"}


# ---------------------------------------------------------------- 원자료(2025-12-31 이후는 읽은 즉시 버림)
def link_sites() -> list[str]:
    return sorted({s for ls in LINKS.values() for lk in ls for s in lk.sites})


def link_dams() -> list[str]:
    return sorted({lk.dam_code for ls in LINKS.values() for lk in ls})


def load_reservoir_algae(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """연결 호소 지점의 측정(site_code·obs_date·cells). obs_date > last 는 읽은 즉시 버린다."""
    a = pd.read_parquet(ALGAE_ALL, columns=["site_code", "obs_date", "iem_bgalage_cell_co"])
    a["obs_date"] = pd.to_datetime(a["obs_date"]).dt.normalize()
    a = a[a["obs_date"] <= last]
    a = a[a["site_code"].astype(str).isin(link_sites())].rename(columns={"iem_bgalage_cell_co": "cells"})
    a["site_code"] = a["site_code"].astype(str)
    a["cells"] = a["cells"].astype(float)
    return a.sort_values(["site_code", "obs_date"]).reset_index(drop=True)


def load_dam_release(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """연결 댐 일자료 → dam_code·obs_date·q_total(tdqty)·q_intake(itqty)·q_river(= tdqty − itqty, ≥ 0)."""
    h = pd.read_parquet(HYDRO_LONG, columns=["facility_code", "obs_date", "variable", "value", "source"])
    h["obs_date"] = pd.to_datetime(h["obs_date"]).dt.normalize()
    h = h[
        (h["obs_date"] <= last)
        & h["facility_code"].isin(link_dams())
        & h["variable"].isin(["tdqty", "itqty"])
    ]
    h = h.assign(prio=h["source"].map(HYDRO_SRC_PRIORITY).fillna(9)).sort_values("prio")
    h = h.drop_duplicates(["facility_code", "variable", "obs_date"], keep="first")
    w1 = h.pivot_table(index=["facility_code", "obs_date"], columns="variable", values="value").reset_index()
    e = pd.read_parquet(EXTRA_DAMS, columns=["facility_code", "obs_date", "tdqty", "itqty"])
    e["obs_date"] = pd.to_datetime(e["obs_date"]).dt.normalize()
    e = e[(e["obs_date"] <= last) & e["facility_code"].isin(link_dams())]
    w = pd.concat([w1[["facility_code", "obs_date", "tdqty", "itqty"]], e], ignore_index=True)
    w = w.drop_duplicates(["facility_code", "obs_date"], keep="first")
    out = pd.DataFrame(
        {
            "dam_code": w["facility_code"].astype(str),
            "obs_date": w["obs_date"],
            "q_total": w["tdqty"].astype(float),
            "q_intake": w["itqty"].astype(float),
        }
    )
    out["q_river"] = (out["q_total"] - out["q_intake"].fillna(0.0)).clip(lower=0.0)
    return out.sort_values(["dam_code", "obs_date"]).reset_index(drop=True)


def load_down_flow(last: pd.Timestamp = H.LAST_DATE) -> dict[str, pd.DataFrame]:
    """하류 지점 시설 일 유량(읽기 전용 interim): CS·MGMR = fac_outflow(보·하굿둑 방류), DCHN = fac_inflow(대청댐 유입)."""
    out = {}
    for s, col in (("CS", "fac_outflow"), ("MGMR", "fac_outflow"), ("DCHN", "fac_inflow")):
        d = pd.read_parquet(INTERIM / f"daily_{s}_S1.parquet", columns=["obs_date", col])
        d["obs_date"] = pd.to_datetime(d["obs_date"]).dt.normalize()
        d = d[d["obs_date"] <= last].rename(columns={col: "q_down"})
        out[s] = d.sort_values("obs_date").reset_index(drop=True)
    return out


# ---------------------------------------------------------------- 순수 피처 함수
def lag_days(link: Link, lag_mode: str, horizon_days: float = 7.0) -> int:
    """lag 0 이면 0, travel 이면 clip(round(T − horizon), 0, LAG_CAP). T 는 연결의 이동시간 가정(일)."""
    if lag_mode == "0":
        return 0
    if lag_mode != "travel":
        raise ValueError(f"lag_mode 는 {LAG_MODES} 중 하나: {lag_mode}")
    return int(np.clip(np.round(link.travel_days - float(horizon_days)), 0, LAG_CAP))


def link_state(algae_r: pd.DataFrame, release_r: pd.DataFrame, as_of: date, lag: int) -> dict[str, float]:
    """연결 하나 → {cells, days, q}. 진입 직후 cut_as_of(as_of), 다시 as_of − lag 로 자른다."""
    a = cut_as_of(algae_r, as_of)
    r = cut_as_of(release_r, as_of)
    t0 = pd.Timestamp(as_of)
    cutoff = t0 - pd.Timedelta(days=int(lag))
    a = a[(pd.to_datetime(a["obs_date"]) <= cutoff) & a["cells"].notna()]
    out = {"cells": math.nan, "days": math.nan, "q": math.nan}
    if len(a):
        a = a.assign(obs_date=pd.to_datetime(a["obs_date"]))
        last = a.sort_values("obs_date").groupby("site_code").tail(1)
        last = last[(t0 - last["obs_date"]).dt.days <= MAX_STALE + int(lag)]
        if len(last):
            out["cells"] = float(last["cells"].max())
            out["days"] = float((t0 - last["obs_date"].max()).days)
    q = window_days(r, cutoff.date(), REL_WINDOW, "q_river").astype(float).dropna()
    if len(q) >= MIN_VALID:
        out["q"] = float(q.mean())
    return out


def make_dam_features(
    algae: pd.DataFrame,
    release: pd.DataFrame,
    down: pd.DataFrame | None,
    as_of: date,
    station_id: str,
    lag_mode: str = "0",
    horizon_days: float = 7.0,
    link_set: str = "all",
) -> dict[str, float]:
    """(호소 측정, 댐 방류, 하류 유량, as_of, 지점) → dam_* 5열 dict. 연결이 없는 지점은 모두 NaN.

    algae: site_code·obs_date·cells, release: dam_code·obs_date·q_river, down: obs_date·q_down(없으면 contrib NaN).
    """
    algae = cut_as_of(algae, as_of)
    release = cut_as_of(release, as_of)
    down = cut_as_of(down, as_of) if down is not None else None
    out = {c: math.nan for c in COLS}
    links = [lk for lk in LINKS.get(str(station_id), ()) if link_set == "all" or lk.certain]
    states = []
    for lk in links:
        lag = lag_days(lk, lag_mode, horizon_days)
        st = link_state(
            algae[algae["site_code"].isin(lk.sites)], release[release["dam_code"] == lk.dam_code], as_of, lag
        )
        if np.isfinite(st["cells"]) and np.isfinite(st["q"]):
            states.append(st)
    if not states:
        return out
    q_sum = float(sum(s["q"] for s in states))
    flux = float(sum(s["cells"] * s["q"] for s in states))
    c_mix = flux / q_sum if q_sum > 0 else float(max(s["cells"] for s in states))
    out["dam_cell_log"] = math.log10(max(c_mix, 0.0) + 1.0)
    out["dam_days"] = float(max(s["days"] for s in states))
    out["dam_q_log"] = math.log10(q_sum + 1.0)
    out["dam_load_log"] = math.log10(max(flux, 0.0) + 1.0)
    if down is not None:
        qd = window_days(down, as_of, REL_WINDOW, "q_down").astype(float).dropna()
        if len(qd) >= MIN_VALID:
            out["dam_contrib_log"] = math.log10(max(flux, 0.0) / max(float(qd.mean()), Q_DOWN_FLOOR) + 1.0)
    return out


# ---------------------------------------------------------------- 표 단위 생성
def build_variant_features(
    df: pd.DataFrame,
    lag_mode: str,
    link_set: str = "all",
    *,
    algae: pd.DataFrame | None = None,
    release: pd.DataFrame | None = None,
    down: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """df(load_base 형식) 각 행에 make_dam_features 적용 → dam_* 5열(같은 인덱스).

    속도를 위해 행마다 [as_of − 120일, as_of + 30일] 로 미리 자른 부분만 넘긴다(as_of 이후 행도 일부 넘어가며,
    순수 함수가 진입 직후 cut_as_of 로 버린다 — 누수 테스트 대상).
    """
    H.guard_no_2026(df)
    algae = load_reservoir_algae() if algae is None else algae
    release = load_dam_release() if release is None else release
    down = load_down_flow() if down is None else down
    ad = pd.to_datetime(algae["obs_date"]).to_numpy()
    rd = pd.to_datetime(release["obs_date"]).to_numpy()
    recs = []
    for sid, bd, hz in zip(
        df["station_id"].astype(str),
        pd.to_datetime(df["base_date"]),
        df["horizon_days"].astype(float),
        strict=True,
    ):
        if not LINKS.get(sid):
            recs.append({c: math.nan for c in COLS})
            continue
        lo, hi = (bd - pd.Timedelta(days=120)).to_datetime64(), (bd + pd.Timedelta(days=30)).to_datetime64()
        a = algae[(ad >= lo) & (ad <= hi)]
        r = release[(rd >= lo) & (rd <= hi)]
        dn = down.get(sid)
        if dn is not None:
            dd = dn["obs_date"].to_numpy()
            dn = dn[(dd >= lo) & (dd <= hi)]
        recs.append(make_dam_features(a, r, dn, bd.date(), sid, lag_mode, hz, link_set))
    return pd.DataFrame(recs, index=df.index, columns=list(COLS))


def variant_frame(feats: dict[tuple[str, str], pd.DataFrame], variant: str) -> pd.DataFrame:
    lag_mode, link_set, bundle = VARIANTS[variant]
    return feats[(lag_mode, link_set)][list(BUNDLES[bundle])]


def build_features(df: pd.DataFrame, variant: str | None = None) -> pd.DataFrame:
    """선택 설정(CHOSEN, 또는 variant)의 새 열만(같은 인덱스). df = harness.load_base() 형식."""
    variant = variant or CHOSEN["variant"]
    lag_mode, link_set, bundle = VARIANTS[variant]
    return build_variant_features(df, lag_mode, link_set)[list(BUNDLES[bundle])]


def members(df: pd.DataFrame, seed: int, variant: str | None = None) -> dict[str, np.ndarray]:
    """C + 선택 피처의 회귀 구성원 OOF(c1·c1_none·c1_log·c3·c2·cg·cg_*). 분위는 학습하지 않는다(v1 동결)."""
    return H2.c_members(df, seed, build_features(df, variant))


def builder(df: pd.DataFrame, seed: int, variant: str | None = None) -> dict[str, np.ndarray]:
    """harness2.Builder 형식: C + 선택 피처의 점예측(연도 확장 NNLS c1·c3·c2·cg), q90 = None(v1 동결)."""
    return H2.c_pred(df, seed, build_features(df, variant))


# ---------------------------------------------------------------- 실험 실행
def _budget() -> H.Budget:
    b = H.Budget(BUDGET_HOURS, PX)
    b.t0 = datetime.strptime(TASK_START, "%Y-%m-%d %H:%M:%S").timestamp()
    return b


def all_features(df: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    """변형에 필요한 (lag, 연결 집합) 피처 표를 만들고 data/processed/exp/EXP-005b/P6/ 에 저장한다."""
    algae, release, down = load_reservoir_algae(), load_dam_release(), load_down_flow()
    out = {}
    for key in sorted({(v[0], v[1]) for v in VARIANTS.values()}):
        f = build_variant_features(df, key[0], key[1], algae=algae, release=release, down=down)
        out[key] = f
        save = pd.concat([df[["station_id", "base_date"]].astype(str), f], axis=1)
        OUT_DATA.mkdir(parents=True, exist_ok=True)
        save.to_parquet(OUT_DATA / f"features_lag{key[0]}_{key[1]}.parquet", index=False)
    return out


def availability(df: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """지점·구간별 새 열 가용률(dam_load_log 유효 비율)."""
    m = H2.scope_masks(df)
    sid = df["station_id"].astype(str).to_numpy()
    ok = f["dam_load_log"].notna().to_numpy()
    rows = []
    for s in ("HP", "GJGR", "CS", "MGMR", "DCHN"):
        rec: dict = {"지점": s}
        for k, nm in (("cv", "CV"), ("y25", "2025")):
            mm = m[k] & (sid == s)
            rec[f"{nm} n"] = int(mm.sum())
            rec[f"{nm} 가용률"] = float(ok[mm].mean()) if mm.any() else math.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def site_deltas(df: pd.DataFrame, preds: list[np.ndarray], base: list[np.ndarray]) -> pd.DataFrame:
    """지점별 CV r2_raw·rmse_log 의 시드 짝 차이 평균(구성 − C)."""
    cv, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    sid = df["station_id"].astype(str).to_numpy()
    rows = []
    for s in ("HP", "GJGR", "CS", "MGMR", "DCHN"):
        m = cv & (sid == s)
        dr, dm = [], []
        for p, b in zip(preds, base, strict=True):
            a1, b1 = compute_all(obs[m], p[m]), compute_all(obs[m], b[m])
            dr.append(a1["r2_raw"] - b1["r2_raw"])
            dm.append(a1["rmse_log"] - b1["rmse_log"])
        rows.append(
            {"지점": s, "n": int(m.sum()), "Δr2_raw": float(np.mean(dr)), "Δrmse_log": float(np.mean(dm))}
        )
    return pd.DataFrame(rows)


def residual_corr(df: pd.DataFrame, f: pd.DataFrame, c_preds: list[np.ndarray]) -> pd.DataFrame:
    """C 시드 평균 log 잔차(CV 행)와 새 열의 Spearman 상관(지점별) — C 가 못 쓰는 정보가 있는지 진단."""
    cv, _ = H.masks(df)
    obs = np.log10(df["target_cells"].to_numpy(dtype=float) + 1)
    pr = np.mean([np.log10(p + 1) for p in c_preds], axis=0)
    res = obs - pr
    sid = df["station_id"].astype(str).to_numpy()
    rows = []
    for s in ("CS", "MGMR", "DCHN"):
        m = cv & (sid == s)
        rec: dict = {"지점": s, "n": int(m.sum())}
        for c in COLS:
            x = pd.Series(f[c].to_numpy()[m])
            rec[c] = float(x.corr(pd.Series(res[m]), method="spearman")) if x.notna().sum() > 20 else math.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def raw_corr(df: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """CV 행 Spearman: 새 열 ↔ log10 목표 세포수, 새 열 ↔ 자기 지점 최근 세포수(cell_log_t0)·R2 상류(up1_cell_log).

    새 열이 하류 세포수와 상관이 있어도 C 가 이미 가진 정보(자기·상류 지점 최근값, 계절)와 겹치면 증분이 없다.
    """
    cv, _ = H.masks(df)
    y = pd.Series(np.log10(df["target_cells"].to_numpy(dtype=float) + 1))
    f2 = H2.f2_frame(df)
    own = pd.Series(df["cell_log_t0"].to_numpy(dtype=float))
    up1 = pd.Series(f2["up1_cell_log"].to_numpy(dtype=float))
    sid = df["station_id"].astype(str).to_numpy()
    rows = []
    for s in ("CS", "MGMR", "DCHN"):
        m = cv & (sid == s)
        rec: dict = {"지점": s, "n": int(m.sum())}
        for c in ("dam_cell_log", "dam_load_log", "dam_contrib_log"):
            x = pd.Series(f[c].to_numpy()[m])
            rec[f"{c}↔목표"] = float(x.corr(y[m].reset_index(drop=True), method="spearman"))
        rec["cell_log_t0↔목표(참고)"] = float(
            own[m].reset_index(drop=True).corr(y[m].reset_index(drop=True), method="spearman")
        )
        x = pd.Series(f["dam_cell_log"].to_numpy()[m])
        rec["dam_cell_log↔cell_log_t0"] = float(x.corr(own[m].reset_index(drop=True), method="spearman"))
        u = up1[m].reset_index(drop=True)
        rec["dam_cell_log↔up1_cell_log"] = (
            float(x.corr(u, method="spearman")) if u.notna().sum() > 20 else math.nan
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def _md(t: pd.DataFrame, nd: int = 3) -> str:
    def fmt(v: object) -> str:
        if isinstance(v, float):
            return "–" if not np.isfinite(v) else f"{v:.{nd}f}"
        return str(v)

    head = "| " + " | ".join(t.columns) + " |\n|" + "---|" * len(t.columns) + "\n"
    return (
        head
        + "\n".join("| " + " | ".join(fmt(v) for v in r) + " |" for r in t.itertuples(index=False))
        + "\n"
    )


def link_table() -> pd.DataFrame:
    rows = []
    for s, ls in LINKS.items():
        if not ls:
            rows.append(
                {
                    "하류 지점": s,
                    "상류 호소(지점 코드)": "없음",
                    "댐": "–",
                    "경로": "–",
                    "거리 km": math.nan,
                    "이동시간 가정 일": math.nan,
                    "travel lag(일, 7일 선행)": math.nan,
                    "확실성": "–",
                }
            )
        for lk in ls:
            rows.append(
                {
                    "하류 지점": s,
                    "상류 호소(지점 코드)": f"{lk.reservoir}({'·'.join(lk.sites)})",
                    "댐": f"{lk.dam_name}({lk.dam_code})",
                    "경로": lk.via,
                    "거리 km": float(lk.km),
                    "이동시간 가정 일": float(lk.travel_days),
                    "travel lag(일, 7일 선행)": float(lag_days(lk, "travel", 7.0)),
                    "확실성": "확실" if lk.certain else "불확실",
                }
            )
    return pd.DataFrame(rows)


def choose(results: dict[str, dict]) -> tuple[str, bool]:
    """CV 전용 규칙: (시드 평균 ΔCV r2_raw ≥ +0.08) 그리고 (대조군 대비 ≥ +0.04) 인 변형 중 CV r2_raw 최대.

    없으면 대조군 대비 고유 효과(Δ − Δ대조)가 가장 큰 변형을 '기준 미달'로 고른다(2025 는 쓰지 않음).
    """
    ok = [
        v for v, r in results.items() if r["check"]["d_cv_r2_raw"] >= 0.08 and r["check"]["d_vs_ctrl"] >= 0.04
    ]
    if ok:
        return max(ok, key=lambda v: results[v]["mean"]["cv_r2_raw"]), True
    return max(results, key=lambda v: results[v]["own_effect"]), False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    budget = _budget()
    t_run = time.time()
    df = H.load_base()
    H.guard_no_2026(df)
    OUT_REPORT.mkdir(parents=True, exist_ok=True)
    base_rows = H2.baseline_c(df)
    c_mean = H2.mean_rows(base_rows, "C(기준 모델)")
    c_preds = [H2.run_cached(df, "C", s, H2.c_pred)["pred"] for s in H2.EXPLORE_SEEDS]
    feats = all_features(df)
    log.info("피처 생성 %.1f분", (time.time() - t_run) / 60)
    results: dict[str, dict] = {}
    entries = [(c_mean, base_rows)]
    stopped = ""
    for v in VARIANTS:
        try:
            budget.check()
        except H.BudgetExceeded as exc:
            stopped = str(exc)
            log.warning("시간 상한 초과로 중단: %s", exc)
            break
        extra = variant_frame(feats, v)

        def build_f(d: pd.DataFrame, s: int, x: pd.DataFrame = extra) -> dict[str, np.ndarray]:
            return H2.c_pred(d, s, x)

        def build_k(d: pd.DataFrame, s: int, x: pd.DataFrame = extra) -> dict[str, np.ndarray]:
            return H2.c_pred(d, s, H2.noise_like(x, s))

        rows, mean = H2.evaluate(df, f"{PX}_{v}", build_f)
        krows, kmean = H2.evaluate(df, f"{PX}_{v}_ctrl", build_k)
        mean["구성"], kmean["구성"] = f"C + {v}", f"C + {v} 대조군(난수 {extra.shape[1]}열)"
        chk = H2.explore_check(mean, rows, base_rows, krows)
        preds = [H2.run_cached(df, f"{PX}_{v}", s, build_f)["pred"] for s in H2.EXPLORE_SEEDS]
        kpreds = [H2.run_cached(df, f"{PX}_{v}_ctrl", s, build_k)["pred"] for s in H2.EXPLORE_SEEDS]
        d_k = H2.paired_delta(krows, base_rows, "cv_r2_raw")
        results[v] = {
            "rows": rows,
            "mean": mean,
            "ctrl_rows": krows,
            "ctrl_mean": kmean,
            "check": chk,
            "d_ctrl_vs_c": d_k,
            "own_effect": chk["d_cv_r2_raw"] - d_k,
            "n_cols": int(extra.shape[1]),
            "site_feat": site_deltas(df, preds, c_preds),
            "site_ctrl": site_deltas(df, kpreds, c_preds),
            "preds": preds,
        }
        entries += [(mean, rows), (kmean, krows)]
        log.info(
            "%s: ΔCV r2_raw %+.4f, 대조 %+.4f, 고유 %+.4f (%.2fh)",
            v,
            chk["d_cv_r2_raw"],
            d_k,
            results[v]["own_effect"],
            budget.elapsed_h,
        )
    chosen, meets = choose(results) if results else ("", False)
    if chosen and chosen != CHOSEN["variant"]:
        log.warning(
            "CV 선택 결과(%s)가 CHOSEN(%s)과 다르다 — CHOSEN 을 고쳐야 한다", chosen, CHOSEN["variant"]
        )
    boot = {}
    if chosen:
        lo, hi, med = CF.bootstrap_ci(df, results[chosen]["preds"], c_preds)
        boot = {"lo": lo, "hi": hi, "median": med}
    key0 = ("0", "all")
    txt = ["# P6 자동 생성 표(손으로 고치지 않음)\n"]
    txt.append("## 연결 표\n\n" + _md(link_table(), 1))
    txt.append("## 새 열 가용률(dam_load_log 유효, lag 0·전체 연결)\n\n" + _md(availability(df, feats[key0])))
    txt.append("## 표준 표(시드 평균, ΔC = C 대비 시드 짝 차이)\n\n" + H2.table2(entries, base_rows))
    summ = []
    for v, r in results.items():
        c = r["check"]
        summ.append(
            {
                "변형": v,
                "열 수": r["n_cols"],
                "CV r2_raw": r["mean"]["cv_r2_raw"],
                "ΔC r2_raw": c["d_cv_r2_raw"],
                "Δ대조 r2_raw": r["d_ctrl_vs_c"],
                "고유 효과": r["own_effect"],
                "ΔC rmse_log": H2.paired_delta(r["rows"], base_rows, "cv_rmse_log"),
                "Δ대조 rmse_log": H2.paired_delta(r["ctrl_rows"], base_rows, "cv_rmse_log"),
                "시드 min~max": f"{r['mean']['cv_r2_raw_min']:.3f}~{r['mean']['cv_r2_raw_max']:.3f}",
                "2025 Δr2_raw": H2.paired_delta(r["rows"], base_rows, "y25_r2_raw"),
                "2025 9~10월 Δrmse_log": H2.paired_delta(r["rows"], base_rows, "y25b_rmse_log"),
                "탐색 판정": "충족" if c["meets_explore"] else "미충족",
            }
        )
    txt.append("## 변형 요약(시드 평균)\n\n" + _md(pd.DataFrame(summ), 3))
    for v, r in results.items():
        t = r["site_feat"].merge(r["site_ctrl"], on=["지점", "n"], suffixes=("(피처)", "(대조)"))
        txt.append(f"## 지점별 CV 시드 짝 차이 — {v}\n\n" + _md(t, 3))
    txt.append(
        "## C 잔차와 새 열의 Spearman 상관(CV 행, lag 0·전체 연결)\n\n"
        + _md(residual_corr(df, feats[key0], c_preds))
    )
    txt.append(
        "## 새 열 ↔ 목표·기존 피처 Spearman 상관(CV 행, lag 0·전체 연결)\n\n" + _md(raw_corr(df, feats[key0]))
    )
    if chosen:
        txt.append(
            f"## 선택\n\n- 선택 변형: {chosen}({'CV 기준 충족' if meets else '기준 미달 — 고유 효과 최대'})\n"
            f"- (연도·지점) 블록 부트스트랩 2,000회 ΔCV r2_raw(선택 − C) 95% 구간 [{boot['lo']:+.3f}, {boot['hi']:+.3f}], 중앙 {boot['median']:+.3f}\n"
        )
    if stopped:
        txt.append(f"\n**시간 상한 초과로 중단**: {stopped}\n")
    (OUT_REPORT / "tables.md").write_text("\n".join(txt), encoding="utf-8")
    metrics = {
        "chosen": chosen,
        "chosen_meets_cv_rule": meets,
        "bootstrap_chosen_vs_c": boot,
        "c_mean": c_mean,
        "c_rows": base_rows,
        "variants": {
            v: {
                k: (r[k] if k not in ("site_feat", "site_ctrl") else r[k].to_dict(orient="records"))
                for k in (
                    "mean",
                    "rows",
                    "ctrl_mean",
                    "ctrl_rows",
                    "check",
                    "d_ctrl_vs_c",
                    "own_effect",
                    "n_cols",
                    "site_feat",
                    "site_ctrl",
                )
            }
            for v, r in results.items()
        },
        "availability": availability(df, feats[key0]).to_dict(orient="records"),
        "links": link_table().to_dict(orient="records"),
        "stopped": stopped,
        "elapsed_h_since_task_start": budget.elapsed_h,
        "run_minutes": (time.time() - t_run) / 60,
    }
    H2.write_json(OUT_REPORT / "metrics.json", metrics)
    print("\n".join(txt))
    print(
        f"선택 {chosen} (기준 충족 {meets}), 실행 {(time.time() - t_run) / 60:.1f}분, 착수 후 {budget.elapsed_h:.2f}h"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
