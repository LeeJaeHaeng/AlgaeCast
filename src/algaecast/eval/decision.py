"""의사결정 변환 (T5, docs/04 §7): SHAP 상위 3 → 그룹명 문장, 설비 배치 우선순위(p_over_10k × 취수 가중치)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR

GROUP_KO = {
    "ar": "최근 남조류 추세",
    "water": "수온·수질",
    "hydro": "수문(보·댐 운영)",
    "weather": "기상",
    "forecast": "기상 예보",
    "time_site": "계절·지점 특성",
}
_PREFIX = {
    "ar": (
        "cell_",
        "days_since_obs",
        "dominant_genus",
        "alert_level",
        "consecutive_over",
        "chla_",
        "cells_missing",
    ),
    "water": ("wtemp", "ph_t0", "do_t0", "turb_t0", "transp_t0"),
    "hydro": (
        "weir_",
        "inflow",
        "outflow",
        "storage",
        "residence",
        "upstream_dam",
        "dam_release",
        "level_cont",
    ),
    "weather": ("ta_", "rn_", "dry_days", "ss_sum", "si_sum", "ws_", "hm_"),
    "forecast": ("fc_",),
    "time_site": (
        "month_",
        "doy_",
        "season_day",
        "year",
        "site_code",
        "station_id",
        "basin",
        "facility_type",
        "intake_",
        "catchment",
        "total_storage",
        "n_upstream",
        "horizon_days",
    ),
}
FEATURE_KO = {
    "cell_log_t0": "최근 측정 세포수",
    "cell_max_4w": "최근 4주 최대 세포수",
    "cell_log_lag1w": "1주 전 세포수",
    "cell_log_lag3w": "3주 전 세포수",
    "cell_slope_3": "최근 3회 증가 기울기",
    "consecutive_over_1k": "관심 기준 연속 초과 횟수",
    "chla_lag1w": "1주 전 클로로필-a",
    "wtemp_ma14": "14일 평균 수온",
    "wtemp_minus_site_thresh": "지점 관심 임계 대비 수온",
    "wtemp_diff7": "7일 수온 변화",
    "ph_t0": "pH",
    "ta_degree_days20": "30일 적산 기온",
    "rn_sum30": "30일 누적 강수",
    "hm_mean7": "7일 평균 습도",
    "ws_mean7": "7일 평균 풍속",
    "season_day": "조류 시즌 경과일",
    "horizon_days": "예측 선행일",
    "weir_outflow_t0": "보 방류량",
    "weir_outflow_ma7": "보 7일 평균 방류량",
    "weir_storage_rate_t0": "보 저수율",
    "weir_residence_proxy": "보 체류시간 대리",
    "inflow_t0": "상류 댐 유입량",
    "outflow_t0": "상류 댐 방류량",
    "outflow_change7": "상류 댐 방류 7일 변화",
    "storage_rate_t0": "상류 댐 저수율",
    "level_cont_t0": "연속 수위 편차",
    "level_cont_diff7": "연속 수위 7일 변화",
    "dominant_genus": "우점속",
    "facility_type": "시설 유형",
    "basin": "수계",
}


def group_of(feature: str) -> str:
    for g, ps in _PREFIX.items():
        if any(feature.startswith(p) for p in ps):
            return g
    return "etc"


def explain_sentence(shap_row: pd.Series, *, top: int = 3) -> str:
    """SHAP 값(피처명→기여, log10 공간) 상위 |기여| 3개를 그룹명·방향으로 담당자 문장화."""
    s = shap_row.dropna()
    if s.empty:
        return "근거 산출 불가"
    pos = s.abs().sort_values(ascending=False).head(top)
    total = s.abs().sum() or 1.0
    parts = []
    for f in pos.index:
        share = 100 * abs(s[f]) / total
        direction = "상승 요인" if s[f] > 0 else "하락 요인"
        parts.append(f"{GROUP_KO.get(group_of(f), f)}({FEATURE_KO.get(f, f)}) {direction} {share:.0f}%")
    return "주요 근거: " + ", ".join(parts)


def deployment_priority(p_over: pd.Series, *, as_of: str | None = None) -> pd.DataFrame:
    """지점별 경계 초과 확률 × 취수 가중치(sites.yaml intake_weight) → 설비 배치 우선순위."""
    cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    rows = []
    for s in cfg["sites"]:
        sid = s["station_id"]
        if sid not in p_over.index:
            continue
        p = float(p_over[sid])
        w = float(s.get("intake_weight", 0.5))
        rows.append(
            {
                "station_id": sid,
                "지점": s["name"],
                "p_over_10k": p,
                "취수 가중치": w,
                "우선도": p * w,
                "취수능력(톤/일)": s.get("intake_capacity_tpd"),
                "권고": _advice(p),
            }
        )
    d = pd.DataFrame(rows).sort_values("우선도", ascending=False).reset_index(drop=True)
    d.insert(0, "순위", np.arange(1, len(d) + 1))
    if as_of:
        d.insert(1, "기준일", as_of)
    return d


def _advice(p: float) -> str:
    if p >= 0.7:
        return "제거설비 선제 배치·고도정수 전환 준비"
    if p >= 0.4:
        return "감시 강화·설비 대기"
    return "통상 운영"
