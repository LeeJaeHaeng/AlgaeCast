# ruff: noqa: E501  (한국어 표·보고서 문자열)
"""EXP-005 2차 P1 — 변화량 타깃 구성원 + 성장 기작 피처 + 지점 절대 수준 약화(원단위 R² 고도화 2차).

사용자 지시(요지)
- 타깃 Δ = log10(target+1) − log10(t0+1) 로 학습하고, 예측 뒤 t0(= cell_log_t0)에 더해 복원한다.
- 모델: LightGBM(일반)·LightGBM linear_tree·GAM 을 비교한다(GAM 은 설치된 sklearn SplineTransformer + RidgeCV).
- 성장 기작 피처: 속별 최적 수온 기반 성장률(Q10 형태), 체류시간 역수(희석률), 일사·일조, 수온×체류시간 상호작용.
- 지점의 절대 수준을 담는 피처(지점 범주, 지점 임계 수온 편차, 4주 최대·1~3주 전 log 등 긴 창)를 약화한 버전도 비교한다.

정의
- t0: features.ar.make_ar_features 의 cell_log_t0 = base_date(포함) 이전 마지막 유효 측정의 log10(세포수+1).
  v1 표본은 모두 base_date 가 측정일(days_since_obs = 0)이라 t0 는 기준일 측정이다.
- 구성원 OOF: harness 와 같은 연도 확장 폴드(models.cv.year_folds, Final 포함). 예측 Δ̂ 은 그 폴드 학습 Δ 범위로 자른 뒤
  lp = t0 + Δ̂ (log10), 원단위 = to_cells(lp)(none). smear 는 연도 확장 Duan 계수(연도 Y 는 Y 이전 CV OOF 잔차로 적합,
  2020 은 계수 1, 2025 는 2020~2024 전체) — harness.expanding_fit_apply.
- 결합: C 구성원(c1·c3·c2·cg, 캐시 "C")에 Δ 구성원 d 를 더하는 add, c1 을 d 로 바꾸는 rep. harness.ensemble_expanding(연도 확장
  NNLS, log 공간). solo(d 단독 점예측)는 진단용이고 선택 후보가 아니다. 분위는 v1 동결(q90=None) 그대로다.
- 피처 묶음: base = v1 30 + F2 5(C 와 같음), mech = base + 성장 기작 9열, weak = 약화 기본 열 + F2(상류 절대 log 제외) + 기작 9열,
  weak0 = weak 에서 cell_log_t0 도 뺀 진단용. 대조군 mechK/weakK = 기작 9열을 같은 결측 위치의 표준정규 난수(harness2.noise_like)로.
  C+mech(수준 타깃 C 구성원에 기작 9열)와 C+mechK, PREREG 의 K5(C + 난수 5열)도 함께 본다.
- 분해 진단: 같은 모델 종류의 수준 타깃 구성원(lvl)을 같은 방식으로 더해, 이득이 '변화량 타깃' 때문인지 '구성원 종류 추가' 때문인지 본다.

선택 규칙(실행 전 확정, CV 2020~2024 OOF·탐색 시드 5개 평균만)
- 후보: add/rep × {gbm, lin, gam} × {base, mech, weak} × {none, smear}(36개) + C+mech.
- 적격: 시드 평균 Δ CV rmse_log(C 대비) ≤ +0.01, 기작 피처를 쓰는 후보는 고유 효과 Δ(피처) − Δ(같은 구조 대조군) > 0.
  리드타임은 분위 v1 동결이라 모두 같다(18/20).
- 적격 후보 중 시드 평균 CV r2_raw 최대를 고른다. 2025(전체·1~8월·9~10월)는 보고만 한다(harness2.explore_check 는 참고 판정).

as_of 규칙: make_mech_features 는 진입 직후 features.base.cut_as_of 로 as_of 이후 행을 버린다. 일 단위 달력
(data/interim/daily_<지점>_S1.parquet, 읽기 전용)은 읽는 즉시 2025-12-31 이후 행을 버린다. 약화 열은 같은 행의 v1 피처
(이미 as_of 규칙으로 만든 값)끼리의 차이다.

공개 함수(종합 단계 재사용)
- build_features(df) -> DataFrame : 성장 기작 9열(MECH_COLS, 같은 인덱스). df = harness.load_base() 형식.
- weak_frame(df) -> DataFrame : 약화 상대 열 3개(WEAK_REL).
- members(df, seed) -> dict : 선택 설정(CHOSEN)의 OOF 구성원(C 의 c1·c3·c2·cg + d, d_log).
- builder(df, seed) -> {"pred", "q90": None, ...} : 선택 설정 점예측(harness2.Builder 형식).
- member_oof(dfx, cols, model, seed, target) -> {"lp", "none", "smear"} : 구성원 하나의 OOF.

실행: python -m algaecast.exp.r2nd_p1_change [--fresh]
→ reports/experiments/EXP-005/P1/(README.md 는 손으로, tables.md·metrics.json 은 자동), data/processed/exp/EXP-005b/P1/
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import date, datetime
from functools import lru_cache

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import SplineTransformer

from algaecast.config import DATA_DIR
from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.exp import r_combo as RC
from algaecast.features.ar import _genus_cat
from algaecast.features.base import cut_as_of, site_by_code
from algaecast.features.hydro import _storage_mcm
from algaecast.models import data as D
from algaecast.models.cv import year_folds
from algaecast.models.train import LOG_CAP, VariantSpec, _lgb_params, _prep, to_cells

log = logging.getLogger(__name__)

PX = "P1"
OUT_DATA = H2.EXP_DIR / PX
OUT_REPORT = H2.REPORT_DIR / PX
INTERIM = DATA_DIR / "interim"
BUDGET_HOURS = 8.0
TASK_START = "2026-10-22 12:11:57"  # 착수(KST) — 시간 상한 기준
SITES: tuple[str, ...] = ("HP", "GJGR", "CS", "MGMR", "DCHN")
SEC_PER_DAY = 86_400.0
LN10 = math.log(10.0)
WIN = 7  # 일 — 기작 피처 창

# ---------------------------------------------------------------- 문헌값(속별 최적 수온·Q10)
# 키는 features.ar._genus_cat 범주(Dolichospermum → Anabaena). 우점 속이 none/other 면 generic.
T_OPT: dict[str, float] = {
    "Microcystis": 27.5,
    "Anabaena": 25.0,
    "Aphanizomenon": 28.0,
    "Oscillatoria": 24.0,
    "generic": 29.2,
}
T_OPT_SRC: dict[str, str] = {
    "Microcystis": "You J, Mallery K, Hong J, Hondzo M (2018) Temperature effects on growth and buoyancy of Microcystis aeruginosa. J. Plankton Res. 40(1):16–28 — 5~35℃ 배양, cardinal temperature 모형의 최적 27.5℃",
    "Anabaena": "Robarts RD, Zohary T (1987) N.Z. J. Mar. Freshw. Res. 21:391–399(남조류 4속 성장 최적은 대개 25℃ 이상) + Shang L 외 (2025) Life 15(12):1933(Anabaena sp. 10·25·35℃ 중 25℃ 최대) — 확신 중간",
    "Aphanizomenon": "Mehnert G 외 (2010) Competitiveness of invasive and native cyanobacteria from temperate freshwaters under various light and temperature conditions. J. Plankton Res. 32:1009–1021 — A. gracile 최적 28℃",
    "Oscillatoria": "Savadova K 외 (2018) Toxins 10(11):445 — Planktothrix(옛 Oscillatoria) agardhii 최적 20~28℃의 가운데 24℃(Oberhaus 외 2007 J. Phycol.: 25℃ 부근 경쟁 우위)",
    "generic": "Lürling M, Eshetu F, Faassen EJ, Kosten S, Huszar VLM (2013) Comparison of cyanobacterial and green algal growth rates at different temperatures. Freshw. Biol. 58(3):552–559 — 남조류 평균 최적 29.2℃",
}
# Lürling 외(2013) 남조류 평균 성장률 20℃ 0.42 d⁻¹, 최적(29.2℃) 0.92 d⁻¹ 에서 유도: (0.92/0.42)^(10/9.2) ≈ 2.35.
# (참고: 식물플랑크톤 일반 Eppley 1972 Fish. Bull. 70:1063–1085 의 Q10 1.88)
Q10 = 2.35
MU_OPT = 0.92  # d⁻¹, Lürling 외(2013) 남조류 최적 수온 평균 성장률
T_MAX = 35.0  # ℃, 최적 위 감소 구간이 0 이 되는 상한(You 외 2018·Lürling 외 2013 실험 상한)

MECH_COLS: tuple[str, ...] = (
    "mu_micro7",  # Microcystis 수온 성장률(일 수온별 μ 의 7일 평균, d⁻¹)
    "mu_dolicho7",  # Dolichospermum(Anabaena)
    "mu_dom7",  # 기준일 우점 속의 μ(없으면 generic)
    "dil_rate7",  # 희석률 = 7일 평균 방류량 × 86400 / 저수량(d⁻¹) = 체류시간 역수
    "net_growth7",  # 일별 (μ_dom − 희석률) 7일 평균(d⁻¹)
    "si_mean7",  # 일사량 7일 평균(MJ m⁻² d⁻¹)
    "ss_mean7",  # 일조시간 7일 평균(h d⁻¹)
    "wtemp_x_res",  # 수온 7일 평균 × log10(체류시간 일)
    "growth_pot_h",  # μ_dom × min(체류시간, horizon) / ln10 — 체류 한도 안 잠재 log10 증가
)
DAILY_COLS: tuple[str, ...] = (
    "obs_date",
    "wtemp",
    "si",
    "ss",
    "fac_outflow",
    "fac_storage",
    "is_obs",
    "genus_obs",
)

# 약화 버전: 지점 범주·지점 임계 수온 편차·긴 창 절대 수준 열을 빼고 t0 기준 상대 열로 바꾼다.
WEAK_DROP: tuple[str, ...] = (
    "basin",
    "facility_type",
    "wtemp_minus_site_thresh",
    "cell_max_4w",
    "cell_log_lag1w",
    "cell_log_lag3w",
    "up1_cell_log",
)
WEAK_REL: tuple[str, ...] = ("cell_max4w_rel", "cell_chg_1w", "cell_chg_3w")

MODELS: tuple[str, ...] = ("gbm", "lin", "gam")
# linear_tree 잎 선형식 L2(linear_lambda) 후보와 선택값. 선택 = base 묶음 Δ 구성원의 CV(2020~2024) rmse_log 시드 평균 최소
# (원단위 R² 가 아니라 로그 적합도로 고른다). select_lin_lambda 가 다시 계산해 이 값과 같은지 확인한다.
LIN_LAMBDAS: tuple[float, ...] = (0.0, 1.0, 10.0, 100.0)
LIN_LAMBDA = 100.0
FEATURE_SETS: tuple[str, ...] = ("base", "mech", "mechK", "weak", "weakK", "weak0")
FORMS: tuple[str, ...] = ("add", "rep", "solo")
BIASES: tuple[str, ...] = ("none", "smear")
CTRL_OF: dict[str, str] = {"mech": "mechK", "weak": "weakK"}

# 선택 결과(실행 후 기록 — main 이 고른 설정과 같아야 한다)
CHOSEN: dict = {
    "kind": "ens",
    "form": "add",
    "model": "gbm",
    "fs": "base",
    "bias": "none",
    "target": "delta",
}


# ================================================================ 1. 성장 기작 피처(as_of 순수 함수)
def mu_temp(t: np.ndarray | float, genus: str) -> np.ndarray:
    """속별 수온 성장률(d⁻¹): T ≤ T_opt 는 Q10 형태 μ_opt·Q10^((T−T_opt)/10), 위는 2차 감소(T_MAX 에서 0)."""
    t = np.asarray(t, dtype=float)
    topt = T_OPT.get(genus, T_OPT["generic"])
    with np.errstate(invalid="ignore"):
        up = Q10 ** ((t - topt) / 10.0)
        down = np.clip(1.0 - ((t - topt) / (T_MAX - topt)) ** 2, 0.0, None)
    return MU_OPT * np.where(t <= topt, up, down)


def _nanmean(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else math.nan


def make_mech_features(
    daily: pd.DataFrame, as_of: date, site_code: str, horizon_days: float
) -> dict[str, float]:
    """(일 단위 달력, as_of, 지점) → 성장 기작 9열. as_of 이후 행은 진입 직후 버린다."""
    d = cut_as_of(daily, as_of)
    out = dict.fromkeys(MECH_COLS, math.nan)
    if d.empty:
        return out
    dates = pd.to_datetime(d["obs_date"]).dt.normalize()
    w = d[dates >= pd.Timestamp(as_of) - pd.Timedelta(days=WIN - 1)]
    obs = d[d["is_obs"].astype(bool)]
    g = obs["genus_obs"].dropna()
    dom = _genus_cat(g.iloc[-1]) if len(g) else "none"
    dom = dom if dom in T_OPT else "generic"
    wt = w["wtemp"].astype(float).to_numpy()
    mu_dom = mu_temp(wt, dom)
    out["mu_micro7"] = _nanmean(mu_temp(wt, "Microcystis"))
    out["mu_dolicho7"] = _nanmean(mu_temp(wt, "Anabaena"))
    out["mu_dom7"] = _nanmean(mu_dom)
    # 저수량(10^6 m³): 최근 양수 값, 없으면 제원(sites.yaml)
    st = d["fac_storage"].astype(float)
    st = st.where(st > 0).dropna()
    v_last = float(st.iloc[-1]) if len(st) else _storage_mcm(site_by_code(site_code))
    q = w["fac_outflow"].astype(float).to_numpy()
    q7 = _nanmean(q)
    if np.isfinite(v_last) and v_last > 0 and np.isfinite(q7):
        dil = max(q7, 0.0) * SEC_PER_DAY / (v_last * 1e6)
        out["dil_rate7"] = dil
        vd = (
            w["fac_storage"].astype(float).where(w["fac_storage"].astype(float) > 0).fillna(v_last).to_numpy()
        )
        dd = np.clip(q, 0.0, None) * SEC_PER_DAY / (vd * 1e6)
        out["net_growth7"] = _nanmean(mu_dom - dd)
        tau = 1.0 / dil if dil > 0 else math.nan
        t7 = _nanmean(wt)
        out["wtemp_x_res"] = t7 * math.log10(tau) if np.isfinite(tau) and np.isfinite(t7) else math.nan
        if np.isfinite(tau) and np.isfinite(out["mu_dom7"]) and np.isfinite(horizon_days):
            out["growth_pot_h"] = out["mu_dom7"] * min(tau, float(horizon_days)) / LN10
    out["si_mean7"] = _nanmean(w["si"].astype(float).to_numpy())
    out["ss_mean7"] = _nanmean(w["ss"].astype(float).to_numpy())
    return out


def load_daily(site: str) -> pd.DataFrame:
    """일 단위 달력(S1, 읽기 전용) — 2025-12-31 이후 행은 읽는 즉시 버린다."""
    d = pd.read_parquet(INTERIM / f"daily_{site}_S1.parquet", columns=list(DAILY_COLS))
    d["obs_date"] = pd.to_datetime(d["obs_date"])
    return d[d["obs_date"] <= H.LAST_DATE].reset_index(drop=True)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """성장 기작 9열(같은 인덱스). df = harness.load_base() 형식."""
    H.guard_no_2026(df)
    rows: dict[int, dict[str, float]] = {}
    sid = df["station_id"].astype(str)
    for site in sorted(sid.unique()):
        daily = load_daily(site)
        g = df[sid == site]
        for i, bd, hz in zip(g.index, g["base_date"], g["horizon_days"], strict=True):
            rows[i] = make_mech_features(daily, bd, site, float(hz))
    return pd.DataFrame.from_dict(rows, orient="index").reindex(df.index)[list(MECH_COLS)]


def weak_frame(df: pd.DataFrame) -> pd.DataFrame:
    """약화 상대 열: 4주 최대 − t0, t0 − 1주 전, t0 − 3주 전(같은 행 v1 피처끼리의 차)."""
    t0 = df["cell_log_t0"].astype(float)
    return pd.DataFrame(
        {
            "cell_max4w_rel": df["cell_max_4w"].astype(float) - t0,
            "cell_chg_1w": t0 - df["cell_log_lag1w"].astype(float),
            "cell_chg_3w": t0 - df["cell_log_lag3w"].astype(float),
        },
        index=df.index,
    )


# ================================================================ 2. 구성원(Δ 타깃) OOF
@lru_cache(maxsize=1)
def _spec() -> VariantSpec:
    return H.v1_specs()["c1"]


class Gam:
    """가법 모형: 수치 열마다 3차 B-스플라인(분위 매듭 5개, 바깥은 상수) + 결측 지시 + 범주 원핫 → 표준화 → RidgeCV(GCV).

    매듭이 4개 미만(값 종류가 적은 열)이면 선형 항으로 둔다. 결측은 학습 중앙값으로 채운다. 하이퍼파라미터는 고정.
    """

    def __init__(self, n_knots: int = 5, alphas: tuple[float, ...] = tuple(np.logspace(-1, 4, 11))) -> None:
        self.n_knots, self.alphas = n_knots, alphas

    def _design(self, X: pd.DataFrame) -> np.ndarray:
        Z = X[self.nums].astype(float)
        parts = []
        for c in self.nums:
            x = Z[c].fillna(self.med[c]).to_numpy(dtype=float).reshape(-1, 1)
            parts.append(self.splines[c].transform(x) if c in self.splines else x)
        for c in self.miss:
            parts.append(Z[c].isna().to_numpy(dtype=float).reshape(-1, 1))
        for c in self.cats:
            v = X[c].astype(str).to_numpy()
            parts.append(np.column_stack([(v == lv).astype(float) for lv in self.levels[c]]))
        return np.column_stack(parts)

    def fit(self, X: pd.DataFrame, y: np.ndarray, w: np.ndarray) -> Gam:
        self.nums, self.cats = D.numeric_and_categorical(list(X.columns))
        Z = X[self.nums].astype(float)
        self.med = Z.median().fillna(0.0)
        self.miss = [c for c in self.nums if Z[c].isna().any()]
        self.splines: dict[str, SplineTransformer] = {}
        for c in self.nums:
            x = Z[c].fillna(self.med[c]).to_numpy(dtype=float)
            q = np.unique(np.percentile(x, np.linspace(0, 100, self.n_knots)))
            if len(q) >= 4:
                self.splines[c] = SplineTransformer(
                    knots=q.reshape(-1, 1), degree=3, extrapolation="constant"
                ).fit(x.reshape(-1, 1))
        self.levels = {c: sorted(X[c].astype(str).unique()) for c in self.cats}
        M = self._design(X)
        self.mu, self.sd = M.mean(axis=0), M.std(axis=0)
        self.sd[self.sd == 0] = 1.0
        self.ridge = RidgeCV(alphas=self.alphas).fit((M - self.mu) / self.sd, y, sample_weight=w)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.ridge.predict((self._design(X) - self.mu) / self.sd), dtype=float)


def fit_predict_model(
    tr: pd.DataFrame,
    va: pd.DataFrame,
    cols: list[str],
    y: np.ndarray,
    w: np.ndarray,
    model: str,
    seed: int,
    lin_lambda: float | None = None,
) -> np.ndarray:
    """학습 행(tr, 타깃 y, 가중 w) → 검증 행 예측. gbm/lin 은 v1 C1 하이퍼파라미터(n_jobs=4).

    lin(linear_tree): LightGBM 권고대로 수치 열을 학습 행 평균·표준편차로 표준화한다(분기에는 영향 없음, 잎 선형식에만 영향).
    잎 선형식의 L2 linear_lambda 는 v1 에 없는 새 값이라 CV(구성원 log 지표)로 한 번 고른 LIN_LAMBDA 를 쓴다.
    """
    if model == "gam":
        return Gam().fit(tr[cols], y, w).predict(va[cols])
    nums, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    Xv = _prep(va[cols], cats, ref=Xt)
    extra: dict[str, object] = {"objective": "regression"}
    if model == "lin":
        mu = Xt[nums].astype(float).mean()
        sd = Xt[nums].astype(float).std().replace(0.0, 1.0).fillna(1.0)
        Xt[nums] = (Xt[nums].astype(float) - mu) / sd
        Xv[nums] = (Xv[nums].astype(float) - mu) / sd
        extra["linear_tree"] = True
        extra["linear_lambda"] = LIN_LAMBDA if lin_lambda is None else lin_lambda
    elif model != "gbm":
        raise ValueError(model)
    m = lgb.LGBMRegressor(**_lgb_params(_spec().params, seed, **extra))
    m.fit(Xt, y, sample_weight=w, categorical_feature=cats or "auto")
    return np.asarray(m.predict(Xv), dtype=float)


def expanding_smear(df: pd.DataFrame, lp: np.ndarray) -> tuple[np.ndarray, dict[int, float]]:
    """연도 확장 Duan 계수: 연도 Y 는 Y 이전 CV OOF 의 10^(log10(관측+1) − lp) 평균(2020 은 1, 2025 는 2020~2024)."""
    obs_log = df["target_log"].to_numpy(dtype=float)
    years = H.years_of(df)
    facs: dict[int, float] = {}

    def fit(m: np.ndarray) -> float | None:
        e = obs_log[m] - lp[m]
        e = e[np.isfinite(e)]
        return float(np.mean(10.0**e)) if len(e) else None

    def apply(s: object, m: np.ndarray) -> np.ndarray:
        f = 1.0 if s is None else float(s)  # type: ignore[arg-type]
        facs[int(years[m][0])] = f
        return to_cells(lp[m]) * f

    return H.expanding_fit_apply(df, fit, apply), facs


def member_oof(
    dfx: pd.DataFrame,
    cols: list[str],
    model: str,
    seed: int,
    target: str = "delta",
    lin_lambda: float | None = None,
) -> dict[str, np.ndarray]:
    """구성원 하나의 연도 확장 OOF(2020~2025). target = delta(Δ = log − t0) | level(log).

    반환: lp(log10 예측), none(원단위 10^lp − 1), smear(연도 확장 Duan), smear_fac(행별 적용 계수).
    """
    H.guard_no_2026(dfx)
    ylog = dfx["target_log"].to_numpy(dtype=float)
    off = dfx["cell_log_t0"].to_numpy(dtype=float) if target == "delta" else np.zeros(len(dfx))
    if target not in ("delta", "level"):
        raise ValueError(target)
    y = ylog - off
    alpha = _spec().alpha
    lp = np.full(len(dfx), np.nan)
    for fo in year_folds(dfx, include_final=True):
        ok = np.isfinite(y[fo.train_idx])
        tri = fo.train_idx[ok]
        ytr = y[tri]
        p = fit_predict_model(
            dfx.iloc[tri], dfx.iloc[fo.valid_idx], cols, ytr, 1.0 + alpha * ylog[tri], model, seed, lin_lambda
        )
        lp[fo.valid_idx] = off[fo.valid_idx] + np.clip(p, ytr.min(), ytr.max())
    lp = np.where(np.isfinite(lp), np.clip(lp, 0.0, LOG_CAP), np.nan)
    smear, facs = expanding_smear(dfx, lp)
    years = H.years_of(dfx)
    fac = np.array([facs.get(int(yv), np.nan) for yv in years])
    return {"lp": lp, "none": to_cells(lp), "smear": smear, "smear_fac": fac}


# ================================================================ 3. 피처 묶음·구성·빌더
class Feats:
    """한 번 만든 F2(상류 5열)·성장 기작 9열·약화 상대 3열."""

    def __init__(self, df: pd.DataFrame, mech: pd.DataFrame | None = None) -> None:
        self.f2 = H2.f2_frame(df)
        self.mech = build_features(df) if mech is None else mech.loc[df.index, list(MECH_COLS)]
        self.weak = weak_frame(df)


def fs_frame(df: pd.DataFrame, feats: Feats, fs: str, seed: int) -> tuple[pd.DataFrame, list[str]]:
    """피처 묶음 fs 의 학습 프레임과 열 목록. 대조 묶음(…K)은 기작 9열을 같은 결측 위치의 난수로 바꾼다."""
    if fs not in FEATURE_SETS:
        raise ValueError(fs)
    v1, f2c = H.base_columns(), list(feats.f2.columns)
    parts = [df, feats.f2]
    if fs.startswith("weak"):
        parts.append(feats.weak)
        cols = [c for c in v1 + f2c if c not in WEAK_DROP] + list(WEAK_REL)
        if fs == "weak0":
            cols.remove("cell_log_t0")
    else:
        cols = v1 + f2c
    extra = None
    if fs in ("mech", "weak", "weak0"):
        extra = feats.mech
    elif fs in ("mechK", "weakK"):
        extra = H2.noise_like(feats.mech, seed)
    if extra is not None:
        parts.append(extra)
        cols = cols + list(extra.columns)
    dfx = pd.concat(parts, axis=1)
    H.guard_no_2026(dfx)
    return dfx, cols


def member_name(model: str, fs: str, target: str = "delta") -> str:
    return f"P1_m_{model}_{fs}" + ("_lvl" if target == "level" else "")


def member(df: pd.DataFrame, feats: Feats, model: str, fs: str, seed: int, target: str = "delta") -> dict:
    """구성원 OOF(캐시: P1_m_<model>_<fs>[_lvl]_<seed>)."""

    def build(d: pd.DataFrame, s: int) -> dict[str, np.ndarray]:
        dfx, cols = fs_frame(d, feats, fs, s)
        o = member_oof(dfx, cols, model, s, target)
        return {"pred": o["smear"], "q90": None, **o}

    return H2.run_cached(df, member_name(model, fs, target), seed, build)


def variant_name(form: str, model: str, fs: str, bias: str, target: str = "delta") -> str:
    return f"P1_{form}_{model}_{fs}_{bias}" + ("_lvl" if target == "level" else "")


def ens_builder(feats: Feats, form: str, model: str, fs: str, bias: str, target: str = "delta") -> H2.Builder:
    """C 구성원 + 구성원 d 결합(add: 5개, rep: c1 → d, solo: d 단독). 분위는 v1 동결(q90=None)."""

    def build(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        m = member(df, feats, model, fs, seed, target)
        if form == "solo":
            return {"pred": m[bias], "q90": None}
        c = H2.run_cached(df, "C", seed, H2.c_pred)
        mem = {k: c[f"m_{k}"] for k in H2.C_NAMES}
        mem["d"] = m[bias]
        names = (*H2.C_NAMES, "d") if form == "add" else ("d", "c3", "c2", "cg")
        pred, w = H.ensemble_expanding(df, mem, names=names)
        years = H.years_of(df)
        wd = np.array([w.get(int(y), {}).get("d", np.nan) for y in years])
        return {"pred": pred, "q90": None, "w_d": wd}

    return build


def c_extra_builder(feats: Feats, kind: str) -> H2.Builder:
    """C 의 수준 타깃 구성원에 열 추가: mech(기작 9열)·mechK(같은 결측 난수 9열)·K5(PREREG 대조: 난수 5열)."""

    def build(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        if kind == "mech":
            extra = feats.mech
        elif kind == "mechK":
            extra = H2.noise_like(feats.mech, seed)
        elif kind == "K5":
            extra = RC.control_columns(df.index, 5, seed)
        else:
            raise ValueError(kind)
        return H2.c_pred(df, seed, extra=extra)

    return build


# ================================================================ 4. 공개 API(선택 설정)
def members(df: pd.DataFrame, seed: int, feats: Feats | None = None) -> dict[str, np.ndarray]:
    """선택 설정(CHOSEN)의 OOF 구성원: C 의 c1·c3·c2·cg(캐시 "C") + d(Δ 구성원, CHOSEN bias), d_log."""
    H.guard_no_2026(df)
    feats = feats or Feats(df)
    c = H2.run_cached(df, "C", seed, H2.c_pred)
    out = {k: c[f"m_{k}"] for k in H2.C_NAMES}
    if CHOSEN["kind"] == "ens":
        m = member(df, feats, CHOSEN["model"], CHOSEN["fs"], seed, CHOSEN["target"])
        out["d"], out["d_log"] = m[CHOSEN["bias"]], m["lp"]
    return out


def builder(df: pd.DataFrame, seed: int, feats: Feats | None = None) -> dict[str, np.ndarray]:
    """선택 설정 점예측(harness2.Builder 형식). q90=None → v1 동결 분위."""
    feats = feats or Feats(df)
    if CHOSEN["kind"] == "cmech":
        return c_extra_builder(feats, "mech")(df, seed)
    return ens_builder(
        feats, CHOSEN["form"], CHOSEN["model"], CHOSEN["fs"], CHOSEN["bias"], CHOSEN["target"]
    )(df, seed)


# ================================================================ 5. 실행·선택·표
def select_lin_lambda(df: pd.DataFrame, feats: Feats) -> dict:
    """linear_lambda 를 base 묶음 Δ 구성원의 CV rmse_log(탐색 시드 평균) 최소로 고른다. 결과는 OUT_DATA/lin_lambda.json 캐시."""
    path = OUT_DATA / "lin_lambda.json"
    if path.exists():
        got = json.loads(path.read_text(encoding="utf-8"))
        if got.get("candidates") == list(LIN_LAMBDAS):
            return got
    cv, _ = H.masks(df)
    obs_log = df["target_log"].to_numpy(dtype=float)
    score: dict[str, float] = {}
    for lam in LIN_LAMBDAS:
        vals = []
        for s in H2.EXPLORE_SEEDS:
            dfx, cols = fs_frame(df, feats, "base", s)
            lp = member_oof(dfx, cols, "lin", s, "delta", lin_lambda=lam)["lp"]
            vals.append(float(np.sqrt(np.mean((obs_log[cv] - lp[cv]) ** 2))))
        score[str(lam)] = float(np.mean(vals))
        log.info("linear_lambda %.1f: CV rmse_log %.4f", lam, score[str(lam)])
    best = min(LIN_LAMBDAS, key=lambda v: score[str(v)])
    out = {"candidates": list(LIN_LAMBDAS), "cv_rmse_log": score, "chosen": best}
    H2.write_json(path, out)
    return out


def elapsed_hours() -> float:
    t0 = datetime.strptime(TASK_START, "%Y-%m-%d %H:%M:%S")
    return (datetime.now() - t0).total_seconds() / 3600


def plan(feats: Feats) -> list[dict]:
    """평가할 구성 목록(이름·빌더·역할). 역할: cand(선택 후보)·ctrl(대조군)·diag(진단)."""
    items: list[dict] = []

    def add(name: str, build: H2.Builder, role: str, **meta: object) -> None:
        items.append({"name": name, "build": build, "role": role, **meta})

    add("P1_Cmech", c_extra_builder(feats, "mech"), "cand", kind="cmech", fs="mech", ctrl="P1_CmechK")
    add("P1_CmechK", c_extra_builder(feats, "mechK"), "ctrl", kind="cmech", fs="mechK")
    add("P1_K5", c_extra_builder(feats, "K5"), "ctrl", kind="k5", fs="K5")
    for model in MODELS:
        for fs in ("base", "mech", "weak", "mechK", "weakK"):
            for form in ("add", "rep"):
                for bias in BIASES:
                    nm = variant_name(form, model, fs, bias)
                    role = "ctrl" if fs.endswith("K") else "cand"
                    # 새 피처가 없는 base 는 PREREG_FINAL 의 K(C + 난수 5열)를 대조군으로 본다(보고용, 적격 조건 아님)
                    ctrl = (
                        variant_name(form, model, CTRL_OF[fs], bias)
                        if fs in CTRL_OF
                        else ("P1_K5" if fs == "base" else None)
                    )
                    meta = {
                        "kind": "ens",
                        "form": form,
                        "model": model,
                        "fs": fs,
                        "bias": bias,
                        "target": "delta",
                    }
                    add(nm, ens_builder(feats, form, model, fs, bias), role, ctrl=ctrl, **meta)
        for fs in ("base", "mech", "weak"):
            for bias in BIASES:
                meta = {
                    "kind": "ens",
                    "form": "solo",
                    "model": model,
                    "fs": fs,
                    "bias": bias,
                    "target": "delta",
                }
                add(
                    variant_name("solo", model, fs, bias),
                    ens_builder(feats, "solo", model, fs, bias),
                    "diag",
                    **meta,
                )
        for bias in BIASES:  # 분해: 같은 모델 종류의 수준 타깃 구성원을 더함
            meta = {
                "kind": "ens",
                "form": "add",
                "model": model,
                "fs": "base",
                "bias": bias,
                "target": "level",
            }
            add(
                variant_name("add", model, "base", bias, "level"),
                ens_builder(feats, "add", model, "base", bias, "level"),
                "diag",
                **meta,
            )
    for form in ("add", "rep"):
        meta = {
            "kind": "ens",
            "form": form,
            "model": "gbm",
            "fs": "weak0",
            "bias": "smear",
            "target": "delta",
        }
        add(
            variant_name(form, "gbm", "weak0", "smear"),
            ens_builder(feats, form, "gbm", "weak0", "smear"),
            "diag",
            **meta,
        )
    return items


def run_all(
    df: pd.DataFrame, feats: Feats, budget: H.Budget, res: dict[str, tuple[list[dict], dict]]
) -> list[dict]:
    """모든 구성을 탐색 시드로 평가(캐시)해 res(이름 → (시드별 행, 평균 행))에 채운다. 반환: 구성 목록."""
    items = plan(feats)
    for k, it in enumerate(items):
        budget.check()
        t = time.time()
        res[it["name"]] = H2.evaluate(df, it["name"], it["build"])
        log.info(
            "[%d/%d] %s CV r2_raw %.4f (%.0fs, 누적 %.2fh)",
            k + 1,
            len(items),
            it["name"],
            res[it["name"]][1]["cv_r2_raw"],
            time.time() - t,
            elapsed_hours(),
        )
    return items


def summarize(items: list[dict], res: dict, base_rows: list[dict]) -> pd.DataFrame:
    """구성별 시드 평균·C 대비 짝 차이·대조군 고유 효과·적격·탐색 판정."""
    out = []
    for it in items:
        rows, mean = res[it["name"]]
        ctrl_rows = res[it["ctrl"]][0] if it.get("ctrl") else None
        ex = H2.explore_check(mean, rows, base_rows, ctrl_rows)
        r = {
            "name": it["name"],
            "role": it["role"],
            **{k: it.get(k) for k in ("kind", "form", "model", "fs", "bias", "target", "ctrl")},
            **{k: mean[k] for k in mean if k not in ("구성",)},
            "d_cv_r2_raw": H2.paired_delta(rows, base_rows, "cv_r2_raw"),
            "d_cv_rmse_log": H2.paired_delta(rows, base_rows, "cv_rmse_log"),
            "d_y25_r2_raw": H2.paired_delta(rows, base_rows, "y25_r2_raw"),
            "d_y25_rmse_log": H2.paired_delta(rows, base_rows, "y25_rmse_log"),
            "d_y25b_rmse_log": H2.paired_delta(rows, base_rows, "y25b_rmse_log"),
            "d_cvfold_r2_raw": H2.paired_delta(rows, base_rows, "cvfold_r2_raw"),
            "d_vs_ctrl": ex["d_vs_ctrl"],
            "explore": ex,
        }
        uses_feat = it.get("fs") in ("mech", "weak")
        r["eligible"] = bool(
            it["role"] == "cand"
            and r["d_cv_rmse_log"] <= 0.01
            and mean["lead_q90"] >= 18.0
            and (not uses_feat or (np.isfinite(r["d_vs_ctrl"]) and r["d_vs_ctrl"] > 0))
        )
        out.append(r)
    return pd.DataFrame(out)


def choose(summary: pd.DataFrame) -> dict:
    el = summary[summary["eligible"]]
    if el.empty:
        best = summary[summary["role"] == "cand"].sort_values("cv_r2_raw", ascending=False).iloc[0]
        return {"name": best["name"], "eligible": False}
    best = el.sort_values("cv_r2_raw", ascending=False).iloc[0]
    return {"name": best["name"], "eligible": True}


def year_r2(df: pd.DataFrame, rows_pred: list[np.ndarray]) -> dict[int, float]:
    """연도별 CV r2_raw(시드 평균)."""
    obs = df["target_cells"].to_numpy(dtype=float)
    years = H.years_of(df)
    out = {}
    for yv in (*H.CV_YEARS, 2025):
        m = (years == yv) & (pd.to_datetime(df["target_date"]).dt.year.to_numpy() <= 2025)
        vals = []
        for p in rows_pred:
            o, q = obs[m], p[m]
            vals.append(1.0 - float(np.sum((o - q) ** 2)) / float(np.sum((o - o.mean()) ** 2)))
        out[int(yv)] = float(np.mean(vals))
    return out


def load_preds(df: pd.DataFrame, name: str, key: str = "pred") -> list[np.ndarray]:
    out = []
    for s in H2.EXPLORE_SEEDS:
        o = pd.read_parquet(H2.cache_path(name, s))
        if len(o) != len(df):
            raise RuntimeError(f"캐시 행 수 불일치: {name} {s}")
        out.append(o[key].to_numpy(dtype=float))
    return out


def member_quality(df: pd.DataFrame) -> pd.DataFrame:
    """구성원 단독 로그 지표(CV): rmse_log·r2_log(lp 기준)와 smear 계수(2025 적용값), 시드 평균."""
    obs_log = df["target_log"].to_numpy(dtype=float)
    cv, _ = H.masks(df)
    years = H.years_of(df)
    rows = []
    for model in MODELS:
        for fs in ("base", "mech", "weak", "mechK", "weakK", "weak0"):
            for target in ("delta", "level"):
                nm = member_name(model, fs, target)
                if not H2.cache_path(nm, H2.EXPLORE_SEEDS[0]).exists():
                    continue
                r, s25 = [], []
                for s in H2.EXPLORE_SEEDS:
                    o = pd.read_parquet(H2.cache_path(nm, s))
                    lp = o["lp"].to_numpy(dtype=float)
                    e = obs_log[cv] - lp[cv]
                    r.append(
                        (
                            float(np.sqrt(np.mean(e**2))),
                            1 - float(np.sum(e**2) / np.sum((obs_log[cv] - obs_log[cv].mean()) ** 2)),
                        )
                    )
                    s25.append(float(np.nanmean(o["smear_fac"].to_numpy(dtype=float)[years == 2025])))
                rows.append(
                    {
                        "구성원": nm,
                        "CV rmse_log": float(np.mean([a for a, _ in r])),
                        "CV r2_log": float(np.mean([b for _, b in r])),
                        "2025 smear 계수": float(np.mean(s25)),
                    }
                )
    # 참고: C 구성원 c1(로그 smear in-fold)
    t0 = df["cell_log_t0"].to_numpy(dtype=float)
    e0 = obs_log[cv] - t0[cv]
    rows.append(
        {
            "구성원": "지속성 B0(t0)",
            "CV rmse_log": float(np.sqrt(np.mean(e0**2))),
            "CV r2_log": 1 - float(np.sum(e0**2) / np.sum((obs_log[cv] - obs_log[cv].mean()) ** 2)),
            "2025 smear 계수": math.nan,
        }
    )
    return pd.DataFrame(rows)


def _md(t: pd.DataFrame, nd: int = 3) -> str:
    cols = list(t.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                cells.append("–" if not np.isfinite(v) else f"{v:.{nd}f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def label(name: str) -> str:
    if name == "C":
        return "C(기준 모델)"
    return name.removeprefix("P1_")


def feature_summary(df: pd.DataFrame, feats: Feats) -> pd.DataFrame:
    """기작 피처 가용률·분포와 Δ 와의 순위 상관(관측값 없는 집계).

    상관은 기준일 ≤2024 행만 쓴다. Δ|t0 = Δ − (t0 십분위 구간의 Δ 평균): 평균 회귀(높으면 내려감)를 뺀 변화량.
    """
    m = feats.mech
    cv, fin = H.masks(df)
    tr = pd.Series(H.years_of(df) <= 2024, index=df.index)
    warm = pd.Series(pd.to_datetime(df["base_date"]).dt.month.between(5, 10).to_numpy(), index=df.index)
    dlt = (df["target_log"] - df["cell_log_t0"]).astype(float)
    t0 = df["cell_log_t0"].astype(float)
    bins = pd.qcut(t0[tr].rank(method="first"), 10, labels=False)
    edges = [t0[tr][bins == b].max() for b in range(9)]
    grp = np.searchsorted(np.asarray(edges), t0.to_numpy(), side="left")
    grp_mean = dlt[tr].groupby(grp[tr.to_numpy()]).mean()
    resid = dlt - pd.Series(grp, index=df.index).map(grp_mean)
    rows = []
    for c in MECH_COLS:
        x = m[c].astype(float)
        rows.append(
            {
                "열": c,
                "가용률 전체": float(x.notna().mean()),
                "가용률 CV": float(x[cv].notna().mean()),
                "가용률 2025": float(x[fin].notna().mean()),
                "중앙값": float(x.median()),
                "p10": float(x.quantile(0.1)),
                "p90": float(x.quantile(0.9)),
                "Spearman(Δ)": float(x[tr].corr(dlt[tr], method="spearman")),
                "Spearman(Δ|t0)": float(x[tr].corr(resid[tr], method="spearman")),
                "Spearman(Δ|t0) 5~10월": float(x[tr & warm].corr(resid[tr & warm], method="spearman")),
            }
        )
    return pd.DataFrame(rows)


def peak_diag(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """CV 봉우리 진단(집계): 관측 상위 10행·상위 1% 행의 SSE 비중과 평균 log10 오차(예측 − 관측), 시드 평균.

    names 는 캐시 구성 이름(pred 사용). 'B0' 는 지속성(t0), 'm:<구성원>' 은 구성원 none(10^lp − 1).
    """
    cv, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    idx = np.where(cv)[0]
    order = idx[np.argsort(-obs[idx], kind="stable")]
    top10, top1 = order[:10], order[: max(1, len(order) // 100)]
    rows = []
    for nm in names:
        if nm == "B0":
            preds = [10 ** df["cell_log_t0"].to_numpy(dtype=float) - 1]
        elif nm.startswith("m:"):
            preds = load_preds(df, nm[2:], "none")
        else:
            preds = load_preds(df, nm)
        share, e10, e1 = [], [], []
        for p in preds:
            se = (obs - p) ** 2
            share.append(float(se[top10].sum() / se[idx].sum()))
            e = np.log10(p + 1) - np.log10(obs + 1)
            e10.append(float(e[top10].mean()))
            e1.append(float(e[top1].mean()))
        rows.append(
            {
                "구성": "지속성 B0(t0)" if nm == "B0" else label(nm.removeprefix("m:")),
                "상위 10행 SSE 비중": float(np.mean(share)),
                "상위 10행 평균 log 오차": float(np.mean(e10)),
                f"상위 1%({len(top1)}행) 평균 log 오차": float(np.mean(e1)),
            }
        )
    return pd.DataFrame(rows)


def gain_share(df: pd.DataFrame, feats: Feats, model_fs: tuple[str, str], seed: int = 11) -> pd.DataFrame:
    """Final 폴드(≤2024 학습) Δ gbm 의 gain 중요도 상위 열(진단)."""
    _, fs = model_fs
    dfx, cols = fs_frame(df, feats, fs, seed)
    years = H.years_of(dfx)
    tr = dfx[years <= 2024]
    y = (tr["target_log"] - tr["cell_log_t0"]).to_numpy(dtype=float)
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    mdl = lgb.LGBMRegressor(
        **_lgb_params(_spec().params, seed, objective="regression", importance_type="gain")
    )
    mdl.fit(
        Xt,
        y,
        sample_weight=1.0 + _spec().alpha * tr["target_log"].to_numpy(dtype=float),
        categorical_feature=cats or "auto",
    )
    g = pd.Series(mdl.feature_importances_, index=cols, dtype=float)
    g = g / g.sum()
    return g.sort_values(ascending=False).rename("gain 비중").reset_index().rename(columns={"index": "열"})


def write_outputs(
    df: pd.DataFrame,
    feats: Feats,
    items: list[dict],
    res: dict,
    base_rows: list[dict],
    status: str,
    t_start: float,
) -> dict:
    """tables.md(자동)·metrics.json·행 단위 중간물. README.md 는 따로 쓴다."""
    OUT_REPORT.mkdir(parents=True, exist_ok=True)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    base_mean = H2.mean_rows(base_rows, "C(기준 모델)")
    summ = summarize(items, res, base_rows)
    pick = choose(summ)
    best = summ.set_index("name").loc[pick["name"]]

    # 표준 표(주): C + 묶음별 대표(후보 중 CV 최대) + 대조군 + 선택
    def top(mask: pd.Series) -> list[str]:
        s = summ[mask].sort_values("cv_r2_raw", ascending=False)
        return list(s["name"].head(1))

    key_names: list[str] = []
    for model in MODELS:
        for fs in ("base", "mech", "weak"):
            key_names += top((summ["model"] == model) & (summ["fs"] == fs) & (summ["role"] == "cand"))
    key_names += ["P1_Cmech", "P1_CmechK", "P1_K5"]
    if pick["name"] not in key_names:
        key_names.insert(0, pick["name"])
    # 선택 구성의 대조군
    ctrl = summ.set_index("name").loc[pick["name"], "ctrl"]
    if isinstance(ctrl, str) and ctrl not in key_names:
        key_names.append(ctrl)
    entries = [(base_mean, base_rows)] + [
        ({**res[n][1], "구성": label(n)}, res[n][0]) for n in dict.fromkeys(key_names)
    ]
    main_tab = H2.table2(entries, base_rows)
    all_entries = [(base_mean, base_rows)] + [
        ({**res[it["name"]][1], "구성": label(it["name"])}, res[it["name"]][0]) for it in items
    ]
    full_tab = H2.table2(all_entries, base_rows)
    # 요약 표(전 구성 한 줄씩)
    cols = [
        ("name", "구성"), ("role", "역할"), ("cv_r2_raw", "CV r2_raw"), ("d_cv_r2_raw", "ΔC CV r2_raw"),
        ("d_vs_ctrl", "대조군 대비"), ("d_cv_rmse_log", "ΔC CV rmse_log"), ("d_cvfold_r2_raw", "ΔC 폴드평균 r2_raw"),
        ("y25_r2_raw", "2025 r2_raw"), ("d_y25_rmse_log", "ΔC 2025 rmse_log"), ("d_y25b_rmse_log", "ΔC 2025 9~10 rmse_log"),
        ("eligible", "적격(CV)"),
    ]  # fmt: skip
    s2 = summ[[c for c, _ in cols]].rename(columns=dict(cols)).sort_values("CV r2_raw", ascending=False)
    s2["구성"] = s2["구성"].map(label)
    mq = member_quality(df)
    fsum = feature_summary(df, feats)
    pk = peak_diag(
        df,
        list(
            dict.fromkeys(
                [
                    "C",
                    pick["name"],
                    "P1_add_gbm_base_none_lvl",
                    "P1_solo_gbm_base_none",
                    "m:P1_m_gbm_base",
                    "B0",
                ]
            )
        ),
    )
    # 선택·C 연도별
    yr = {
        "C": year_r2(df, load_preds(df, "C")),
        pick["name"]: year_r2(df, load_preds(df, pick["name"])),
    }
    yr_tab = pd.DataFrame(yr).T
    yr_tab.index = [label(i) for i in yr_tab.index]
    # 부트스트랩(참고): 선택 − C, 선택 − 대조군
    boot = {}
    boot["vs_C"] = CF.bootstrap_ci(df, load_preds(df, pick["name"]), load_preds(df, "C"))
    if isinstance(ctrl, str):
        boot["vs_ctrl"] = CF.bootstrap_ci(df, load_preds(df, pick["name"]), load_preds(df, ctrl))
    # 선택의 NNLS 가중치(d)
    wd = None
    if best["kind"] == "ens" and best["form"] in ("add", "rep"):
        years = H.years_of(df)
        ws = [
            pd.read_parquet(H2.cache_path(pick["name"], s))["w_d"].to_numpy(dtype=float)
            for s in H2.EXPLORE_SEEDS
        ]
        wd = {int(y): float(np.mean([w[years == y][0] for w in ws])) for y in (*H.CV_YEARS, 2025)}
    # 행 단위 중간물
    feats.mech.assign(
        station_id=df["station_id"].astype(str), base_date=df["base_date"].astype(str)
    ).to_parquet(OUT_DATA / "mech_features.parquet")
    H.save_oof(
        df,
        {"C_s11": load_preds(df, "C")[0], f"{pick['name']}_s11": load_preds(df, pick["name"])[0]},
        OUT_DATA / "chosen_oof_seed11.parquet",
    )
    txt = (
        "# P1 자동 표(손으로 고치지 않음)\n\n"
        f"상태: {status}. 탐색 시드 {list(H2.EXPLORE_SEEDS)} 평균. ΔC = C 대비 시드 짝 차이. 대조군 대비 = Δ(구성) − Δ(같은 구조 대조군).\n\n"
        "## 1. 주 표(C + 묶음별 대표 + 대조군 + 선택)\n\n"
        + main_tab
        + "\n## 2. 전 구성 요약(CV r2_raw 내림차순)\n\n"
        + _md(s2.reset_index(drop=True))
        + "\n## 3. 구성원 단독 로그 지표(CV, 시드 평균)\n\n"
        + _md(mq)
        + "\n## 4. 성장 기작 피처 가용률·분포(집계)\n\n"
        + _md(fsum)
        + "\n## 5. 연도별 r2_raw(시드 평균, 2025 는 목표일 ≤2025-12-31)\n\n"
        + _md(yr_tab.reset_index().rename(columns={"index": "구성"}))
        + f"\n## 6. (연도·지점) 블록 부트스트랩 2,000회(참고, 탐색 시드)\n\n{json.dumps(boot, ensure_ascii=False)}\n"
        + f"\n## 7. 선택 구성 NNLS 가중치(d, 연도별 시드 평균)\n\n{json.dumps(wd, ensure_ascii=False)}\n"
        + "\n## 8. CV 봉우리 진단(집계, 시드 평균)\n\n"
        + _md(pk)
        + "\n## 9. 전 구성 표준 표\n\n"
        + full_tab
    )
    (OUT_REPORT / "tables.md").write_text(txt, encoding="utf-8")
    gs = gain_share(df, feats, ("gbm", "mech"))
    (OUT_REPORT / "gain_share_gbm_mech.md").write_text(
        "# Δ gbm(mech) Final 폴드 gain 비중(시드 11, 진단)\n\n" + _md(gs.head(25)), encoding="utf-8"
    )
    chosen_mean = res[pick["name"]][1]
    metrics = {
        "experiment": "EXP-005 2차 P1",
        "status": status,
        "seeds": list(H2.EXPLORE_SEEDS),
        "chosen": {
            "name": pick["name"],
            "eligible": pick["eligible"],
            **{k: best[k] for k in ("kind", "form", "model", "fs", "bias", "target")},
        },
        "chosen_seedmean": chosen_mean,
        "chosen_seed_rows": res[pick["name"]][0],
        "C_seedmean": base_mean,
        "d_vs_C": {
            "cv_r2_raw": float(best["d_cv_r2_raw"]),
            "cv_rmse_log": float(best["d_cv_rmse_log"]),
            "y25_r2_raw": float(best["d_y25_r2_raw"]),
            "y25b_rmse_log": float(best["d_y25b_rmse_log"]),
        },
        "d_vs_control": float(best["d_vs_ctrl"]) if np.isfinite(best["d_vs_ctrl"]) else None,
        "explore_check": best["explore"],
        "bootstrap": boot,
        "year_r2_raw": yr,
        "nnls_w_d": wd,
        "summary": json.loads(summ.drop(columns=["explore"]).to_json(orient="records", force_ascii=False)),
        "member_quality": json.loads(mq.to_json(orient="records", force_ascii=False)),
        "feature_summary": json.loads(fsum.to_json(orient="records", force_ascii=False)),
        "peak_diag": json.loads(pk.to_json(orient="records", force_ascii=False)),
        "literature": {"T_OPT": T_OPT, "T_OPT_SRC": T_OPT_SRC, "Q10": Q10, "MU_OPT": MU_OPT, "T_MAX": T_MAX},
        "lin_lambda": json.loads((OUT_DATA / "lin_lambda.json").read_text(encoding="utf-8")),
        "elapsed_hours": round(elapsed_hours(), 2),
        "run_minutes": round((time.time() - t_start) / 60, 1),
    }
    H2.write_json(OUT_REPORT / "metrics.json", metrics)
    return metrics


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="P1_ 캐시를 지우고 다시 계산")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t_start = time.time()
    budget = H.Budget(max(BUDGET_HOURS - elapsed_hours(), 0.01), "P1")
    if args.fresh:
        for p in (H2.EXP_DIR / "cache").glob("P1_*.parquet"):
            p.unlink()
    df = H.load_base()
    H.guard_no_2026(df)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    mpath = OUT_DATA / "mech_features.parquet"
    mech = None
    if mpath.exists() and not args.fresh:
        m = pd.read_parquet(mpath)
        if (
            len(m) == len(df)
            and (m["base_date"].astype(str).to_numpy() == df["base_date"].astype(str).to_numpy()).all()
        ):
            mech = m[list(MECH_COLS)].set_axis(df.index)
    feats = Feats(df, mech)
    lam = select_lin_lambda(df, feats)
    if lam["chosen"] != LIN_LAMBDA:
        raise RuntimeError(
            f"LIN_LAMBDA 상수({LIN_LAMBDA})가 CV 선택값({lam['chosen']})과 다르다 — 상수를 고치고 P1_m_lin_* 캐시를 지운 뒤 다시 실행"
        )
    base_rows = H2.baseline_c(df)
    status = "completed"
    items: list[dict] = []
    res: dict = {}
    try:
        items = run_all(df, feats, budget, res)
    except H.BudgetExceeded as e:
        status = f"time_cap: {e}"
        items = [it for it in plan(feats) if it["name"] in res]
    metrics = write_outputs(df, feats, items, res, base_rows, status, t_start)
    print(
        json.dumps(
            {
                "chosen": metrics["chosen"],
                "d_vs_C": metrics["d_vs_C"],
                "d_vs_control": metrics["d_vs_control"],
                "explore": metrics["explore_check"],
            },
            ensure_ascii=False,
            indent=1,
            default=float,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__: list[str] = [
    "CHOSEN",
    "Feats",
    "Gam",
    "build_features",
    "builder",
    "make_mech_features",
    "member_oof",
    "members",
    "mu_temp",
    "weak_frame",
]
