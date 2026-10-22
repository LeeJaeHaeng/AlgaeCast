# ruff: noqa: E501  (한국어 표 머리글·라벨)
"""R7(EXP-010) 희소 사건(>10,000 cells/mL) 회귀용 재표본·가중 비교.

무엇을 바꾸나
- 회귀 구성원(C1, 필요 시 C3·C2)의 **학습 구간 표본·가중치만** 바꾼다. 피처·하이퍼파라미터(v1)·분위 모델(q10/q50/q90)
  은 그대로라 리드타임(q90≥10k) 포착 수는 기준과 같다.
- 처리(Treatment) = 가중치 함수 + 재표본
  · 가중치: v1(C1 은 1+α·log10(y+1), α=v1 값 / C3·C2 는 무가중), ``log``(1+a·log10(y+1), a 변경),
    ``rel``(관련도 함수 φ=sigmoid(k·(log10(y+1)−log10(10,001))), w=1+b·φ), ``dens``(DenseWeight: 1−γ·정규화 KDE 밀도, 평균 1)
  · 재표본: ``dup``(>10k 행을 총 r배로 복제), ``smogn``(SMOGN: >10k 희소 집합 안 k-NN 이웃이 안전 거리 안이면
    SMOTER 보간, 아니면 가우스 잡음), ``smoter``(보간만), ``gn``(가우스 잡음만), ``under``(≤10k 정상 표본 유지 비율)
- 재표본·가중은 **각 폴드의 학습 구간(base_date 연도 < 검증 연도) 안에서만** 한다. 검증 행·2025 행에는 적용하지 않는다
  (검증 행은 예측 입력으로만 쓰이고 타깃은 읽지 않는다).
- smearing 계수는 원본 학습 행(합성·복제 제외)의 잔차로만 계산한다.

공개 API(종합 단계 EXP-011 재사용)
- ``members(df, cols, config=None, *, quantiles=True) -> dict[str, np.ndarray]``
  선택한 설정(CHOSEN)으로 회귀 구성원 OOF(원단위, 2020~2025, 나머지 NaN)와 q10·q50·q90(v1 방식) 반환.
  ``df`` 는 ``harness.load_base()`` 형식(+추가 피처 열), ``cols`` 는 학습 피처 목록.
  앙상블: ``harness.ensemble_expanding(df, out, member_names(CHOSEN))``.
- ``cv_member(df, cols, member, treat)``: 구성원 하나의 CV OOF(처리 적용).
- ``resample_train(tr, cols, treat, rng)``: 학습 구간 프레임 재표본(합성 행 포함).
- ``sample_weights(ylog, treat, spec, member)``: 가중치 함수.

실행: ``python -m algaecast.exp.r7_rare_resample`` → reports/experiments/EXP-010/, data/processed/exp/EXP-010/
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import gaussian_kde

from algaecast.exp import harness as H
from algaecast.models import data as D
from algaecast.models.cv import year_folds
from algaecast.models.quantile import cv_quantiles
from algaecast.models.train import SEED, VariantSpec, _lgb_params, _prep, to_cells

log = logging.getLogger(__name__)

EXP = "EXP-010"
OUT_DATA = H.EXP_DATA / EXP
OUT_REP = H.EXP_REPORTS / EXP
START = "2026-10-21 17:53:26"  # 세션 시작(시간 상한 기준)
HOURS = 4.0
RARE_LOG = float(np.log10(H.T10K + 1))  # 희소 기준: target_cells > 10,000 ⇔ target_log > log10(10,001)
REL_K = 5.0  # 관련도 sigmoid 기울기(log10 1단위당) — 10k 에서 0.5, 3,160 에서 ≈0.08, 31,600 에서 ≈0.92
LOG_CAP = 7.0
BASE_MEMBERS = ("c1", "c3", "c2")
MEMBER_SPEC = {"c1": "c1", "c1r": "c1", "c3": "c3", "c2": "c2"}  # 구성원 → v1 사양 키


# ---------------------------------------------------------------- 처리 정의
@dataclass(frozen=True)
class Treatment:
    """학습 구간 처리: 가중치 함수 + 재표본(검증 행에는 적용하지 않음)."""

    weight: str = "v1"  # v1 | log | rel | dens
    w_param: float = 0.0  # log: a, rel: b, dens: γ
    resample: str = "none"  # none | dup | smogn | smoter | gn
    r_param: float = 0.0  # dup: 총 배수 r, smogn·smoter·gn: 희소 1건당 합성 수 p
    under: float = 1.0  # ≤10k 정상 표본 유지 비율(1 = 유지)
    k: int = 5  # SMOGN k-NN
    pert: float = 0.02  # SMOGN 가우스 잡음 크기(표준편차 배수 상한)

    def label(self) -> str:
        parts = []
        if self.weight == "log":
            parts.append(f"가중 1+a·log(a={self.w_param:g})")
        elif self.weight == "rel":
            parts.append(f"관련도 가중(b={self.w_param:g})")
        elif self.weight == "dens":
            parts.append(f"밀도역수 가중(γ={self.w_param:g})")
        if self.resample == "dup":
            parts.append(f"복제×{self.r_param:g}")
        elif self.resample == "smogn":
            parts.append(f"SMOGN(p={self.r_param:g})")
        elif self.resample == "smoter":
            parts.append(f"SMOTER만(p={self.r_param:g})")
        elif self.resample == "gn":
            parts.append(f"가우스잡음만(p={self.r_param:g})")
        if self.under < 1.0:
            parts.append(f"정상 {self.under:.0%} 유지")
        return " + ".join(parts) if parts else "v1"

    @property
    def is_random(self) -> bool:
        return self.resample in ("smogn", "smoter", "gn") or self.under < 1.0

    @property
    def is_v1(self) -> bool:
        return self == Treatment()


Config = dict[str, Treatment]  # 구성원(c1·c3·c2·c1r) → 처리. 빠진 기본 구성원은 v1


def member_names(config: Config) -> tuple[str, ...]:
    """앙상블 구성원 이름(기본 c1·c3·c2 + 추가 구성원)."""
    return BASE_MEMBERS + tuple(k for k in config if k not in BASE_MEMBERS)


def config_label(config: Config) -> str:
    if not config or all(t.is_v1 for t in config.values()):
        return "v1"
    if "c1r" in config:
        return f"4구성원(+c1r {config['c1r'].label()})"
    ts = {k: t for k, t in config.items() if not t.is_v1}
    labs = {t.label() for t in ts.values()}
    who = "·".join(k.upper() for k in BASE_MEMBERS if k in ts)
    return (
        f"{who} {labs.pop()}"
        if len(labs) == 1
        else " / ".join(f"{k.upper()} {t.label()}" for k, t in ts.items())
    )


# ---------------------------------------------------------------- 가중치 함수
def sample_weights(ylog: np.ndarray, treat: Treatment, spec: VariantSpec, member: str) -> np.ndarray | None:
    """학습 행 가중치. v1: C1 계열은 1+α·log10(y+1), C3·C2 는 None(무가중)."""
    ylog = np.asarray(ylog, dtype=float)
    if treat.weight == "v1":
        return 1.0 + spec.alpha * ylog if MEMBER_SPEC[member] == "c1" else None
    if treat.weight == "log":
        return 1.0 + treat.w_param * ylog
    if treat.weight == "rel":
        return 1.0 + treat.w_param * relevance(ylog)
    if treat.weight == "dens":
        return dense_weight(ylog, treat.w_param)
    raise ValueError(treat.weight)


def relevance(ylog: np.ndarray, k: float = REL_K) -> np.ndarray:
    """관련도 함수 φ(y) ∈ (0,1): log10 공간 sigmoid, 경계(10,000)에서 0.5."""
    return expit(k * (np.asarray(ylog, dtype=float) - RARE_LOG))


def dense_weight(ylog: np.ndarray, gamma: float, eps: float = 1e-6) -> np.ndarray:
    """DenseWeight(Steininger et al. 2021): w = max(1 − γ·p'(y), ε), p' = min-max 정규화 KDE 밀도, 평균 1."""
    y = np.asarray(ylog, dtype=float)
    if len(y) < 3 or np.ptp(y) == 0:
        return np.ones_like(y)
    p = gaussian_kde(y)(y)
    pn = (p - p.min()) / (p.max() - p.min()) if np.ptp(p) > 0 else np.zeros_like(p)
    w = np.maximum(1.0 - gamma * pn, eps)
    return w / w.mean()


# ---------------------------------------------------------------- 재표본(학습 구간 안)
def _int_like(x: np.ndarray) -> bool:
    v = x[np.isfinite(x)]
    return bool(len(v)) and bool(np.all(v == np.round(v)))


def heom(an: np.ndarray, ac: np.ndarray, bn: np.ndarray, bc: np.ndarray, span: np.ndarray) -> np.ndarray:
    """HEOM 거리(행별 쌍): 수치 |a−b|/범위(결측 → 1), 범주 불일치 1. an·bn (n, p), ac·bc (n, q)."""
    d = np.abs(an - bn) / span
    d = np.where(np.isnan(d), 1.0, d)
    c = (ac != bc).astype(float)
    return np.sqrt((d**2).sum(axis=-1) + c.sum(axis=-1))


def smogn_synth(
    tr: pd.DataFrame,
    cols: list[str],
    n_per_seed: float,
    rng: np.random.Generator,
    *,
    mode: str = "smogn",
    k: int = 5,
    pert: float = 0.02,
) -> tuple[pd.DataFrame, dict]:
    """학습 구간의 희소(>10k) 행 사이에서 합성 행 생성(SMOGN, Branco et al. 2017 방식, 새 패키지 없음).

    - 희소 집합 R 안 HEOM 거리로 k-NN. 안전 거리 maxD_i = (seed i 에서 R 의 다른 행까지 거리 중앙값)/2.
    - 이웃까지 거리 < maxD_i → SMOTER: x = x_i + u·(x_nb − x_i)(u~U(0,1) 하나), 범주는 둘 중 무작위,
      타깃(log10)은 새 점과 두 점의 거리 역가중 평균. 결측은 seed 값 유지.
    - 아니면 가우스 잡음: x = x_i + N(0, (sd_a·min(maxD_i, pert))²), 범주 seed 유지, 타깃 log10 에도 같은 잡음.
    - mode='smoter' 는 보간만, 'gn' 은 잡음만. 정수형 열(예: horizon_days)은 반올림.
    반환: (합성 행: cols + target_log + target_cells, 정보)
    """
    ylog_all = tr["target_log"].to_numpy(dtype=float)
    rare = ylog_all > RARE_LOG
    nr = int(rare.sum())
    total = int(round(n_per_seed * nr))
    info = {"n_rare": nr, "n_synth": 0, "smoter_frac": float("nan")}
    if nr < 2 or total <= 0:
        return tr.iloc[:0][[*cols, "target_log", "target_cells"]].copy(), info
    nums, cats = D.numeric_and_categorical(cols)
    xa = tr[nums].to_numpy(dtype=float)
    span = np.nanmax(xa, axis=0) - np.nanmin(xa, axis=0)
    span = np.where(np.isfinite(span) & (span > 0), span, 1.0)
    R = tr.loc[rare]
    xn = R[nums].to_numpy(dtype=float)
    xc = R[cats].astype(str).to_numpy() if cats else np.empty((nr, 0), dtype=object)
    yr = ylog_all[rare]
    dist = heom(xn[:, None, :], xc[:, None, :], xn[None, :, :], xc[None, :, :], span)
    np.fill_diagonal(dist, np.inf)
    kk = min(k, nr - 1)
    nn = np.argsort(dist, axis=1, kind="stable")[:, :kk]
    off = np.where(np.isinf(dist), np.nan, dist)
    maxd = np.nanmedian(off, axis=1) / 2.0
    counts = np.full(nr, total // nr)
    extra = total - counts.sum()
    if extra:
        counts[rng.choice(nr, size=extra, replace=False)] += 1
    si = np.repeat(np.arange(nr), counts)
    m = len(si)
    nb = nn[si, rng.integers(0, kk, size=m)]
    dsn = dist[si, nb]
    if mode == "smogn":
        use_sm = dsn < maxd[si]
    elif mode == "smoter":
        use_sm = np.ones(m, dtype=bool)
    elif mode == "gn":
        use_sm = np.zeros(m, dtype=bool)
    else:
        raise ValueError(mode)
    xs, xb = xn[si], xn[nb]
    gap = rng.uniform(size=m)[:, None]
    new_s = np.where(np.isnan(xb), xs, xs + gap * (xb - xs))
    pick_nb = rng.uniform(size=(m, xc.shape[1])) < 0.5
    cat_s = np.where(pick_nb, xc[nb], xc[si])
    sd = np.nan_to_num(np.nanstd(xn, axis=0), nan=0.0)
    p = np.minimum(maxd[si], pert)
    new_g = xs + rng.normal(size=xs.shape) * sd[None, :] * p[:, None]
    new_n = np.where(use_sm[:, None], new_s, new_g)
    new_c = np.where(use_sm[:, None], cat_s, xc[si])
    d1 = heom(new_n, new_c, xs, xc[si], span)
    d2 = heom(new_n, new_c, xb, xc[nb], span)
    ys, yb = yr[si], yr[nb]
    tot = d1 + d2
    y_sm = np.where(tot > 0, (d2 * ys + d1 * yb) / np.where(tot > 0, tot, 1.0), (ys + yb) / 2)
    y_gn = ys + rng.normal(size=m) * float(np.std(yr)) * p
    y_new = np.clip(np.where(use_sm, y_sm, y_gn), 0.0, LOG_CAP)
    for j in range(len(nums)):
        if _int_like(xa[:, j]):
            new_n[:, j] = np.round(new_n[:, j])
    out = pd.DataFrame(new_n, columns=nums)
    for j, c in enumerate(cats):
        out[c] = new_c[:, j]
    out["target_log"] = y_new
    out["target_cells"] = 10**y_new - 1
    info.update({"n_synth": m, "smoter_frac": float(use_sm.mean())})
    return out[[*cols, "target_log", "target_cells"]], info


def resample_train(
    tr: pd.DataFrame, cols: list[str], treat: Treatment, rng: np.random.Generator
) -> tuple[pd.DataFrame, np.ndarray, dict]:
    """학습 구간 프레임 → (재표본 프레임, 원본 행 여부, 정보). 원본 행이 앞에 온다. 검증 행은 넣지 말 것."""
    base = tr[[*cols, "target_log", "target_cells"]]
    ylog = base["target_log"].to_numpy(dtype=float)
    info: dict = {"n_train": len(base), "n_rare": int((ylog > RARE_LOG).sum()), "n_synth": 0}
    if treat.under < 1.0:
        normal = np.where(ylog <= RARE_LOG)[0]
        drop = rng.choice(normal, size=int(round(len(normal) * (1 - treat.under))), replace=False)
        keep = np.setdiff1d(np.arange(len(base)), drop)
        base = base.iloc[keep]
        info["n_dropped"] = int(len(drop))
    if treat.resample == "none":
        return base, np.ones(len(base), dtype=bool), info
    if treat.resample == "dup":
        rare = base[base["target_log"].to_numpy(dtype=float) > RARE_LOG]
        reps = max(int(round(treat.r_param)) - 1, 0)
        extra = pd.concat([rare] * reps) if reps and len(rare) else base.iloc[:0]
        info["n_synth"] = len(extra)
    elif treat.resample in ("smogn", "smoter", "gn"):
        extra, si = smogn_synth(
            base, cols, treat.r_param, rng, mode=treat.resample, k=treat.k, pert=treat.pert
        )
        info.update({"n_synth": si["n_synth"], "smoter_frac": si["smoter_frac"]})
    else:
        raise ValueError(treat.resample)
    aug = pd.concat([base, extra], ignore_index=True)
    is_orig = np.r_[np.ones(len(base), dtype=bool), np.zeros(len(extra), dtype=bool)]
    return aug, is_orig, info


# ---------------------------------------------------------------- 적합(train.fit_predict 와 같은 계산 + 외부 가중치)
def fit_member(
    tr: pd.DataFrame,
    is_orig: np.ndarray,
    va: pd.DataFrame,
    cols: list[str],
    spec: VariantSpec,
    w: np.ndarray | None,
    seed: int = SEED,
) -> tuple[np.ndarray, np.ndarray | None, float]:
    """(검증 원단위 예측, log 예측 또는 None, smearing 계수). 처리 없음이면 train.fit_predict 와 같은 값."""
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    Xv = _prep(va[cols], cats, ref=Xt)
    ylog = tr["target_log"].to_numpy(dtype=float)
    yraw = tr["target_cells"].to_numpy(dtype=float)
    cf = cats or "auto"
    if spec.kind == "log_w":
        m = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
        m.fit(Xt, ylog, sample_weight=w, categorical_feature=cf)
        lp = np.asarray(m.predict(Xv), dtype=float)
        resid = (ylog - m.predict(Xt))[is_orig]
        return to_cells(lp), lp, float(np.mean(10**resid))
    if spec.kind == "tweedie":
        extra = {"objective": spec.objective_raw}
        if spec.objective_raw == "tweedie":
            extra["tweedie_variance_power"] = spec.variance_power
        m = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, **extra))
        m.fit(Xt, yraw, sample_weight=w, categorical_feature=cf)
        return np.clip(np.asarray(m.predict(Xv), dtype=float), 0, None), None, 1.0
    if spec.kind == "hurdle":
        over = (yraw > 1000.0).astype(int)
        clf = lgb.LGBMClassifier(**_lgb_params(spec.cls_params, seed, objective="binary"))
        clf.fit(Xt, over, sample_weight=w, categorical_feature=cf)
        p = np.asarray(clf.predict_proba(Xv)[:, 1], dtype=float)
        hi = over == 1
        reg_hi = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
        reg_hi.fit(Xt[hi], ylog[hi], sample_weight=None if w is None else w[hi], categorical_feature=cf)
        reg_lo = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
        reg_lo.fit(Xt[~hi], ylog[~hi], sample_weight=None if w is None else w[~hi], categorical_feature=cf)
        e_hi = to_cells(np.asarray(reg_hi.predict(Xv), dtype=float))
        e_lo = to_cells(np.asarray(reg_lo.predict(Xv), dtype=float))
        raw = p * e_hi + (1 - p) * e_lo
        return raw, np.log10(raw + 1), 1.0
    raise ValueError(spec.kind)


def cv_member(
    df: pd.DataFrame,
    cols: list[str],
    member: str,
    treat: Treatment,
    *,
    specs: dict[str, VariantSpec] | None = None,
    seed: int = SEED,
    rs_seed: int = SEED,
) -> tuple[dict[str, np.ndarray], list[dict]]:
    """구성원 하나의 연도 확장 CV OOF(2020~2025). 재표본·가중은 폴드 학습 구간에만.

    반환: ({'pred': 원단위(C1 계열은 smearing), 'none': 보정 전, 'log': log 예측}, 폴드별 정보)
    """
    H.guard_no_2026(df)
    specs = specs or H.v1_specs()
    spec = specs[MEMBER_SPEC[member]]
    n = len(df)
    out = {k: np.full(n, np.nan) for k in ("pred", "none", "log")}
    infos: list[dict] = []
    years = H.years_of(df)
    for fo in year_folds(df, include_final=True):
        if years[fo.train_idx].max() >= fo.valid_year:
            raise RuntimeError("학습 구간에 검증 연도 이상 행이 섞임")
        tr, va = df.iloc[fo.train_idx], df.iloc[fo.valid_idx]
        rng = np.random.default_rng([rs_seed, fo.valid_year])
        aug, is_orig, info = resample_train(tr, cols, treat, rng)
        w = sample_weights(aug["target_log"].to_numpy(dtype=float), treat, spec, member)
        raw, lp, smear = fit_member(aug, is_orig, va, cols, spec, w, seed)
        pred = raw * smear if (spec.kind == "log_w" and smear) else raw
        out["pred"][fo.valid_idx] = np.clip(np.nan_to_num(pred, nan=0.0), 0, None)
        out["none"][fo.valid_idx] = np.clip(np.nan_to_num(raw, nan=0.0), 0, None)
        if lp is not None:
            out["log"][fo.valid_idx] = lp
        infos.append({"fold": fo.name, "valid_year": fo.valid_year, **info, "smear": smear})
    return out, infos


def _member_keys(member: str, res: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    d = {member: res["pred"]}
    if MEMBER_SPEC[member] == "c1":
        d[f"{member}_none"], d[f"{member}_log"] = res["none"], res["log"]
    return d


# ---------------------------------------------------------------- 공개: 종합 단계용
# 선택 결과(EXP-010 main 실행 후 CV 규칙으로 정함). 보고서 3절 참고.
CHOSEN: Config = {"c1": Treatment(weight="log", w_param=0.25)}  # 기준 미달(ΔCV r2_raw +0.003)


def members(
    df: pd.DataFrame,
    cols: list[str],
    config: Config | None = None,
    *,
    quantiles: bool = True,
    rs_seed: int = SEED,
) -> dict[str, np.ndarray]:
    """선택 설정(CHOSEN)으로 회귀 구성원 OOF(원단위, 2020~2025)와 q10·q50·q90(v1 방식, 처리 없음).

    반환 키: c1·c1_none·c1_log·c3·c2(+추가 구성원) · q10·q50·q90. 앙상블은
    ``harness.ensemble_expanding(df, out, member_names(config))``.
    """
    config = CHOSEN if config is None else config
    H.guard_no_2026(df)
    specs = H.v1_specs()
    out: dict[str, np.ndarray] = {}
    for m in member_names(config):
        res, _ = cv_member(df, cols, m, config.get(m, Treatment()), specs=specs, rs_seed=rs_seed)
        out.update(_member_keys(m, res))
    if quantiles:
        out.update(cv_quantiles(df, cols, specs["c1"]))
    return out


# ---------------------------------------------------------------- 실험 실행
def stage1_grid() -> list[Config]:
    """1단계: C1 에만 처리(C3·C2 는 v1)."""
    T = Treatment
    ts = [
        *(T(weight="log", w_param=a) for a in (0.25, 0.5, 1.0, 2.0)),
        *(T(weight="rel", w_param=b) for b in (1.0, 3.0, 9.0)),
        *(T(weight="dens", w_param=g) for g in (0.5, 0.8)),
        *(T(resample="dup", r_param=r) for r in (2, 3, 5)),
        *(T(resample="smogn", r_param=p) for p in (1, 2, 4)),
        T(resample="smogn", r_param=2, under=0.8),
        T(resample="smoter", r_param=2),
        T(resample="gn", r_param=2),
    ]
    return [{"c1": t} for t in ts]


def stage2_grid(best: list[Treatment]) -> list[Config]:
    """2단계: 1단계 상위 처리를 C3·C2 에도 적용, 또는 C1 v1 + 처리 C1 을 4번째 구성원으로."""
    out: list[Config] = []
    for t in best:
        out += [
            {"c1": t, "c3": t},
            {"c1": t, "c2": t},
            {"c1": t, "c3": t, "c2": t},
            {"c1r": t},
        ]
    return out


def select(rows: list[dict], base: dict) -> tuple[dict, bool]:
    """EXP-PLAN 4절: 채택 기준 만족 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대(기준 미달)."""
    ok = [r for r in rows if H.adoption(base, r)["pass"]]
    pool = ok or rows
    return max(pool, key=lambda r: r["cv_r2_raw"]), bool(ok)


def family(t: Treatment) -> str:
    """처리 계열: 가중(가중치 함수만) · 복제 · 합성(SMOGN·SMOTER·가우스잡음·과소표본)."""
    if t.resample == "dup":
        return "복제"
    if t.resample in ("smogn", "smoter", "gn") or t.under < 1.0:
        return "합성"
    return "가중"


def _stage2_seeds(rows: list[dict]) -> list[Treatment]:
    """1단계 계열(가중·복제·합성)별로 C1 단독 CV r2_raw 최대 처리(CV 만 사용).

    앙상블(log 공간 NNLS)이 C1 변화를 희석하므로 처리 효과는 C1 단독 CV 지표로 고른다.
    """
    best: dict[str, tuple[float, Treatment]] = {}
    for r in rows:
        t = Treatment(**r["config"]["c1"])
        v = r["c1_alone"]["cv_r2_raw"]
        f = family(t)
        if f not in best or v > best[f][0]:
            best[f] = (v, t)
    return [best[f][1] for f in ("가중", "복제", "합성") if f in best]


def _evaluate(df: pd.DataFrame, preds: dict[str, np.ndarray], names: tuple[str, ...], label: str) -> tuple:
    ens, w = H.ensemble_expanding(df, preds, names)
    return H.metric_row(df, ens, preds["q90"], label), ens, w


def _fmt(v: float, nd: int = 3) -> str:
    return "–" if v is None or not np.isfinite(v) else f"{v:.{nd}f}"


BIAS_BINS = ((0.0, 3.0, "<1,000"), (3.0, RARE_LOG, "1,000~10,000"), (RARE_LOG, 99.0, ">10,000"))


def bias_by_bin(df: pd.DataFrame, pred: np.ndarray) -> dict[str, tuple[int, float]]:
    """CV(2020~2024) 행의 관측 농도 구간별 log10 평균 편향(예측 − 관측)과 행 수(집계값만)."""
    cv, _ = H.masks(df)
    lo = np.log10(df["target_cells"].to_numpy(dtype=float) + 1)
    e = np.log10(np.asarray(pred, dtype=float) + 1) - lo
    out = {}
    for a, b, name in BIAS_BINS:
        m = cv & (lo >= a) & (lo < b) & np.isfinite(e)
        out[name] = (int(m.sum()), float(e[m].mean()) if m.any() else float("nan"))
    return out


def bias_table(df: pd.DataFrame, items: list[tuple[str, np.ndarray]]) -> str:
    rows = [(lab, bias_by_bin(df, p)) for lab, p in items]
    names = [n for *_, n in BIAS_BINS]
    head = "| 구성원 | " + " | ".join(f"{n} (n={rows[0][1][n][0]})" for n in names) + " |\n"
    head += "|---" * (len(names) + 1) + "|\n"
    return (
        head
        + "\n".join(f"| {lab} | " + " | ".join(f"{b[n][1]:+.3f}" for n in names) + " |" for lab, b in rows)
        + "\n"
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    budget = H.Budget(HOURS, EXP)
    budget.t0 = time.mktime(time.strptime(START, "%Y-%m-%d %H:%M:%S"))  # 로컬 시각 기준
    t_run = time.time()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_REP.mkdir(parents=True, exist_ok=True)
    df = H.load_base()
    cols = H.base_columns()
    _, base = H.load_baseline()
    specs = H.v1_specs()
    H.guard_no_2026(df)

    # 0) 재현 점검: 처리 없음(v1) = 하네스 기준 OOF
    rep, _ = cv_member(df, cols, "c1", Treatment(), specs=specs)
    repro = float(np.nanmax(np.abs(np.log10(rep["pred"] + 1) - np.log10(base["c1"] + 1))))
    log.info("C1 재현 log10 최대차 %.3g", repro)

    base_preds = {k: base[k] for k in ("c1", "c3", "c2", "q10", "q50", "q90")}
    base_row, _, base_w = _evaluate(df, base_preds, BASE_MEMBERS, "v1 기준(하네스 재현)")
    base_row.update({"stage": 0, "config": {}})
    base_c1 = H.metric_row(df, base["c1"], base["q90"], "v1 C1 단독(앙상블 없음)")

    cache: dict[tuple[str, Treatment], tuple[dict, list[dict]]] = {}

    def run(config: Config, stage: int) -> tuple[dict, dict[str, np.ndarray], dict]:
        preds = dict(base_preds)
        infos = {}
        for m in member_names(config):
            t = config.get(m, Treatment())
            if t.is_v1 and m in BASE_MEMBERS:
                continue
            key = (m, t)
            if key not in cache:
                cache[key] = cv_member(df, cols, m, t, specs=specs)
            res, inf = cache[key]
            preds.update(_member_keys(m, res))
            infos[m] = inf
        lab = config_label(config)
        row, ens, w = _evaluate(df, preds, member_names(config), lab)
        row.update(
            {
                "stage": stage,
                "config": {k: asdict(v) for k, v in config.items()},
                "weights_2025": {k: round(v, 3) for k, v in w[2025].items()},
                "weights": {int(y): {k: round(v, 3) for k, v in wy.items()} for y, wy in w.items()},
                "synth_final": {m: next(i for i in inf if i["fold"] == "Final") for m, inf in infos.items()},
            }
        )
        c1key = "c1r" if "c1r" in config else "c1"
        c1row = H.metric_row(df, preds[c1key], preds["q90"], f"{lab} — C1 단독")
        row["c1_alone"] = {k: c1row[k] for k in c1row if k.startswith(("cv_", "y2025_"))}
        row["c1_alone_row"] = c1row
        preds["pred"] = ens
        log.info(
            "%-45s CV r2_raw %.3f rmse_log %.3f | C1 단독 CV r2_raw %.3f rmse_log %.3f",
            lab, row["cv_r2_raw"], row["cv_rmse_log"], c1row["cv_r2_raw"], c1row["cv_rmse_log"],
        )  # fmt: skip
        return row, preds, w

    rows: list[dict] = []
    all_preds: dict[str, dict[str, np.ndarray]] = {}
    status = "completed"
    try:
        for cfg in stage1_grid():
            budget.check()
            r, p, _ = run(cfg, 1)
            rows.append(r)
            all_preds[r["구성"]] = p
        seeds = _stage2_seeds(rows)
        for cfg in stage2_grid(seeds):
            budget.check()
            r, p, _ = run(cfg, 2)
            if r["구성"] in all_preds:
                continue
            rows.append(r)
            all_preds[r["구성"]] = p
    except H.BudgetExceeded as e:
        log.warning("%s", e)
        status = "time_cap"

    chosen, passed = select(rows, base_row)
    adopt = H.adoption(base_row, chosen)
    chosen_cfg = {k: Treatment(**v) for k, v in chosen["config"].items()}
    cp = all_preds[chosen["구성"]]
    names = member_names(chosen_cfg)
    oof = {k: cp[k] for k in (*names, "q10", "q50", "q90", "pred")}
    H.save_oof(df, oof, OUT_DATA / "chosen_oof.parquet")
    # 모든 변형의 앙상블 점예측(행 단위, data/processed/exp 아래만)
    H.save_oof(
        df, {r["구성"]: all_preds[r["구성"]]["pred"] for r in rows}, OUT_DATA / "variants_ens_oof.parquet"
    )

    # 무작위 재표본이면 재표본 시드 민감도(보고용, 선택에 쓰지 않음)
    robust: list[dict] = []
    if status == "completed" and any(t.is_random for t in chosen_cfg.values()):
        for rs in (SEED + 1, SEED + 2):
            preds = dict(base_preds)
            for m in names:
                t = chosen_cfg.get(m, Treatment())
                if t.is_v1 and m in BASE_MEMBERS:
                    continue
                res, _ = cv_member(df, cols, m, t, specs=specs, rs_seed=rs)
                preds.update(_member_keys(m, res))
            rr, _, _ = _evaluate(df, preds, names, f"{chosen['구성']} (재표본 시드 {rs})")
            robust.append(rr)

    s1_rows = [r for r in rows if r["stage"] == 1]
    btab = bias_table(
        df,
        [("v1 C1", base["c1"]), ("v1 C3", base["c3"]), ("v1 C2", base["c2"])]
        + [(f"{r['구성']}", all_preds[r["구성"]]["c1"]) for r in s1_rows],
    )
    elapsed = budget.elapsed_h
    metrics = [base_row, *rows]
    (OUT_REP / "metrics.json").write_text(
        json.dumps(
            {
                "exp": EXP,
                "status": status,
                "chosen": chosen["구성"],
                "chosen_passed_rule": passed,
                "adoption": adopt,
                "c1_repro_log10_maxdiff": repro,
                "rows": metrics,
                "robustness": robust,
                "elapsed_h": elapsed,
            },
            ensure_ascii=False,
            indent=1,
            default=float,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_report(
        base_row,
        base_c1,
        base_w,
        rows,
        chosen,
        passed,
        adopt,
        robust,
        repro,
        status,
        elapsed,
        time.time() - t_run,
        btab,
    )
    print(
        "선택:", chosen["구성"], f"CV r2_raw {chosen['cv_r2_raw']:.3f} rmse_log {chosen['cv_rmse_log']:.3f}"
    )
    print("채택 판정:", adopt)
    return 0


def _write_report(
    base_row: dict,
    base_c1: dict,
    base_w: dict,
    rows: list[dict],
    chosen: dict,
    passed: bool,
    adopt: dict,
    robust: list[dict],
    repro: float,
    status: str,
    elapsed_h: float,
    run_s: float,
    btab: str = "",
) -> None:
    s1 = [r for r in rows if r["stage"] == 1]
    s2 = [r for r in rows if r["stage"] == 2]
    ordered = [base_row, *sorted(rows, key=lambda r: -r["cv_r2_raw"])]

    def c1w(wd: dict, key: str) -> str:
        cv = [wd[y][key] for y in (2021, 2022, 2023, 2024) if key in wd.get(y, {})]
        return f"{np.mean(cv):.3f} / {wd[2025][key]:.3f}" if cv else "–"

    bw = {int(y): v for y, v in base_w.items()}
    c1_lines = [
        f"| v1 C1 | {_fmt(base_c1['cv_r2_raw'])} | {_fmt(base_c1['cv_nse_raw'])} | {_fmt(base_c1['cv_rmse_log'])} | "
        f"{_fmt(base_c1['cv_f1_10k'])} | {_fmt(base_c1['y2025_r2_raw'])} | {_fmt(base_c1['y2025_rmse_log'])} | {c1w(bw, 'c1')} | – |"
    ]
    for r in s1 + s2:
        c = r["c1_alone"]
        sy = r.get("synth_final", {})
        syn = ", ".join(
            f"{m}: 희소 {v.get('n_rare', '–')}·합성 {v.get('n_synth', 0)}"
            for m, v in sy.items()
            if v.get("n_synth")
        )
        key = "c1r" if "c1r" in r["config"] else "c1"
        c1_lines.append(
            f"| {r['구성']} | {_fmt(c['cv_r2_raw'])} | {_fmt(c['cv_nse_raw'])} | {_fmt(c['cv_rmse_log'])} | "
            f"{_fmt(c['cv_f1_10k'])} | {_fmt(c['y2025_r2_raw'])} | {_fmt(c['y2025_rmse_log'])} | "
            f"{c1w(r['weights'], key)} | {syn or '–'} |"
        )
    c1_tab = (
        "| 변형(C1 계열 구성원) | CV r2_raw | CV nse_raw | CV rmse_log | CV F1@10k | 2025 r2_raw | 2025 rmse_log | "
        "앙상블 내 NNLS 가중(2021~2024 평균 / 2025) | Final 폴드 희소·합성 행 |\n"
        "|---|---|---|---|---|---|---|---|---|\n" + "\n".join(c1_lines) + "\n"
    )
    top_c1 = sorted(s1, key=lambda r: -r["c1_alone"]["cv_r2_raw"])[:3]
    ref_rows = [base_row, base_c1, *(r["c1_alone_row"] for r in top_c1)]
    ref_adopt = "\n".join(
        f"- {r['구성']}: ΔCV r2_raw {a['d_cv_r2_raw']:+.3f}, ΔCV rmse_log {a['d_cv_rmse_log']:+.3f} → {'만족' if a['pass'] else '미달'}"
        for r in ref_rows[1:]
        for a in [H.adoption(base_row, r)]
    )
    ens_r2 = [r["cv_r2_raw"] for r in s1]
    c1_r2 = [r["c1_alone"]["cv_r2_raw"] for r in s1]
    zero_c1 = sum(1 for r in s1 if all(r["weights"][y]["c1"] < 0.005 for y in (2021, 2022, 2023, 2024, 2025)))
    rmse_ok = [r for r in rows if r["cv_rmse_log"] - base_row["cv_rmse_log"] <= 0.01]
    best_ok = max(rmse_ok, key=lambda r: r["cv_r2_raw"]) if rmse_ok else None
    rob_txt = ""
    if robust:
        rr = [chosen, *robust]
        r2 = np.array([r["cv_r2_raw"] for r in rr])
        rm = np.array([r["cv_rmse_log"] for r in rr])
        rob_txt = (
            "\n### 재표본 시드 민감도(보고용, 선택에 쓰지 않음)\n\n"
            "| 재표본 시드 | CV r2_raw | CV rmse_log |\n|---|---|---|\n"
            + "\n".join(
                f"| {s} | {_fmt(r['cv_r2_raw'])} | {_fmt(r['cv_rmse_log'])} |"
                for s, r in zip((SEED, SEED + 1, SEED + 2), rr, strict=False)
            )
            + f"\n\n3시드 평균 CV r2_raw {r2.mean():.3f} (sd {r2.std(ddof=1):.3f}), rmse_log {rm.mean():.3f} (sd {rm.std(ddof=1):.3f}).\n"
        )
    verdict = "만족" if adopt["pass"] else "미달"
    txt = f"""# EXP-010 (R7) 희소 사건(>10,000 cells/mL) 재표본·가중

상태: {"완료" if status == "completed" else "시간 상한 초과로 중단"} · 실행 `python -m algaecast.exp.r7_rare_resample` · 코드 `src/algaecast/exp/r7_rare_resample.py`

## 1. 목적·설정

- 목적: 경계(10,000 cells/mL) 초과 희소 표본을 학습에서 더 크게 다뤄 원단위 R²·NSE(고농도 오차가 지배)를 올릴 수 있는지 확인.
- 데이터: `harness.load_base()`(v1 학습·검증 행, ≤2025), 피처 v1 30개(`base_columns()`), 하이퍼파라미터 v1(`v1_specs()`). 새 외부 자료 없음.
- 처리 위치: 각 연도 확장 폴드의 **학습 구간 안에서만** 재표본·가중(검증 연도·2025 행은 예측 입력으로만 사용).
  분위 모델(q10/q50/q90)은 v1 그대로 → 리드타임(q90≥10k) 포착 수는 모든 변형이 기준과 같다.
- 평가: 처리한 구성원 → 연도 확장 NNLS 앙상블(`harness.ensemble_expanding`) → `harness.metric_row`.
- 변형
  - 가중치 함수(C1 의 v1 가중 1+α·log10(y+1), α={specs_alpha():.3f} 를 대체): 1+a·log10(y+1)(a=0.25·0.5·1·2),
    관련도 함수 φ=sigmoid({REL_K:g}·(log10(y+1)−log10(10,001))) 로 w=1+b·φ(b=1·3·9),
    DenseWeight w=max(1−γ·p'(y),ε)(γ=0.5·0.8, p'=학습 구간 log 타깃 KDE 밀도 min-max 정규화, 평균 1 정규화).
  - 가중 복제: >10k 학습 행을 총 r배(r=2·3·5).
  - SMOGN(새 패키지 없이 구현): >10k 희소 집합 안 HEOM 거리 k=5 이웃, 안전 거리(이웃 거리 중앙값/2) 안이면 SMOTER 보간
    (수치 x_i+u·(x_nb−x_i), 범주 무작위, 타깃 log10 거리 역가중), 밖이면 가우스 잡음(sd·min(maxD, 0.02)). 희소 1건당
    합성 p=1·2·4건, p=2 + 정상(≤10k) 80% 유지(과소표본), 성분 분리(SMOTER만·가우스잡음만, p=2).
  - 2단계(자동, CV 만 사용): 1단계 계열(가중·복제·합성)별 **C1 단독** CV r2_raw 최대 처리를 C3·C2 에도 적용
    (C1·C3 / C1·C2 / C1·C3·C2), 또는 v1 C1 을 두고 처리한 C1 을 4번째 구성원(c1r)으로 추가. 1단계에서 앙상블(log 공간
    NNLS)이 C1 변화를 거의 지우는 것이 CV 로 확인돼(앙상블 CV r2_raw {min(ens_r2):.3f}~{max(ens_r2):.3f} 대 C1 단독
    {min(c1_r2):.3f}~{max(c1_r2):.3f}) 후보를 C1 단독 CV 기준으로 고른다. (설계 변경 기록: 첫 실행은 2단계 후보를 앙상블
    CV r2_raw 로 골라 가장 약한 처리(a=0.25)만 확장됐다. 그 결과를 보고 CV 근거로 기준을 바꿔 다시 실행했다.)
- 재현 점검: 처리 없음(v1)으로 돌린 C1 OOF 와 하네스 기준 OOF 의 log10 최대 절대차 = {repro:.3g}.
- 변형 수: 1단계 {len(s1)}개 + 2단계 {len(s2)}개 = {len(rows)}개.

## 2. 표준 표(앙상블 점예측, CV r2_raw 내림차순)

{H.standard_table(ordered)}
### 보조 표

{H.detail_table(ordered)}
### C1 계열 구성원 단독 지표(앙상블 전)

{c1_tab}
1단계 C1 변형 {len(s1)}개 중 {zero_c1}개는 2021~2025 모든 연도에서 앙상블 C1 가중치가 0.005 미만(사실상 C3·C2 조합).

### 참고: C1 단독을 점예측으로 쓸 때(앙상블 없음, 선택 후보 아님)

1단계 C1 단독 CV r2_raw 상위 3개와 v1 C1 단독. 분위(q90)는 v1 그대로라 리드타임은 같다.

{H.standard_table(ref_rows)}
{ref_adopt}

## 3. 선택한 변형과 채택 판정

- 선택: **{chosen["구성"]}** ({"채택 기준을 만족하는 변형 중 CV r2_raw 최대" if passed else "채택 기준을 만족하는 변형이 없어 CV r2_raw 최대 변형 — 기준 미달"}).
- 선택 변형 2025 NNLS 가중치: {json.dumps(chosen.get("weights_2025", {}), ensure_ascii=False)}
- `adoption(v1 기준, 선택)`: ΔCV r2_raw {adopt["d_cv_r2_raw"]:+.3f}, ΔCV rmse_log {adopt["d_cv_rmse_log"]:+.3f}, 리드타임 유지 {adopt["lead_ok"]} → **{verdict}**.
- 참고(rmse_log 조건만 만족하는 변형 중 CV r2_raw 최대): {best_ok["구성"] + f" (CV r2_raw {best_ok['cv_r2_raw']:.3f}, rmse_log {best_ok['cv_rmse_log']:.3f})" if best_ok else "없음"}.
{rob_txt}
## 4. 누수·2026 점검

- 모든 프레임 `harness.guard_no_2026` 통과(base_date ≤ 2025-12-31, test 분할 없음). 2026 행·test 타깃 파일은 읽지 않았다.
- 재표본·가중은 `cv_member` 안에서 폴드 학습 구간(`year_folds` train_idx, 연도 < 검증 연도)만 받아 수행하고, 학습 구간에
  검증 연도 이상 행이 있으면 중단한다. 검증 행 타깃은 지표 계산에만 쓴다.
- 테스트 `tests/test_exp_r7_rare_resample.py`: `test_future_rows_do_not_change_oof`(연도 Y 이상 행의 타깃·Y 초과 행의
  피처를 난수로 바꿔도 연도 Y OOF 가 비트 단위로 같음, 처리 4종 × C1·C3), `test_resample_receives_only_training_years`,
  `test_smogn_synth_properties`, `test_resample_train_counts`, `test_weight_functions`, `test_config_helpers`,
  `test_v1_treatment_reproduces_baseline_c1`(처리 없음 = 하네스 기준 C1 OOF, 차이 0).
- 테스트 실행 결과·보호 파일 점검: TEST_RESULT_PLACEHOLDER

## 5. 소요 시간·한계·다음 단계

- 소요: 세션 시작 {START} 부터 보고서 작성까지 {elapsed_h:.2f}시간(상한 {HOURS:g}시간), 이 실행 {run_s / 60:.1f}분.
- 해석
  1. **희소 강조는 고농도 과소예측을 조금 줄이는 대신 저농도 과대예측을 늘린다.** 아래 표(CV 행, 관측 구간별 log10 평균
     편향, 예측 − 관측)에서 관련도 가중·복제·SMOGN 계열은 >10,000 구간 과소예측이 v1 보다 줄지만(0 에 가까워짐), 1+a·log
     가중은 a 가 클수록 오히려 커진다. 모든 처리에서 행의 대부분인 <1,000 구간 과대예측은 v1 과 같거나 커진다.

{btab}
  2. **앙상블이 처리 효과를 지운다.** 연도 확장 NNLS(log 공간, 합=1)는 log 오차가 큰 처리 C1 에 가중치를 더 적게 준다
     (v1 C1 도 2021~2024 평균 {np.mean([bw[y]["c1"] for y in (2021, 2022, 2023, 2024)]):.3f} 로 작고, 강한 처리일수록 0 에 가까워진다 — 위 C1 표의 NNLS 가중 열).
     그래서 C1 만 바꾼 변형의 앙상블은 C3·C2 조합으로 수렴하고 CV r2_raw 가 {min(ens_r2):.3f}~{max(ens_r2):.3f} 에 머문다(v1 {base_row["cv_r2_raw"]:.3f}).
  3. **C1 단독 개선도 작다.** v1 C1 단독 CV r2_raw {base_c1["cv_r2_raw"]:.3f}(rmse_log {base_c1["cv_rmse_log"]:.3f}) 대비 최대
     {max(c1_r2):.3f}({top_c1[0]["구성"]}, rmse_log {top_c1[0]["c1_alone"]["cv_rmse_log"]:.3f}). 복제·SMOGN 계열은 v1 C1 단독을
     넘지 못했다. 희소 표본이 Final 폴드 기준 {s1[-1]["synth_final"].get("c1", {}).get("n_rare", "–") if s1 and s1[-1].get("synth_final") else "약 200"}건뿐이고, 같은 사건 주변 표본끼리 보간·복제해도 새 정보가 생기지 않는 것으로 보인다.
  4. **C3·C2 에 적용해도 나아지지 않는다.** 2단계 C2 포함 변형은 앙상블 CV r2_raw 가 기준 이하이고 rmse_log 가 악화된다(표 2).
- 한계: 원단위 CV R² 는 극소수 극단 사건이 좌우해 변형 간 0.01~0.03 차이는 잡음 수준이다. LightGBM 시드 1개, 하이퍼파라미터는
  v1 고정(가중·재표본 변경 뒤 재튜닝 없음). SMOGN 은 희소 기준 1개(>10k)의 단순화 구현이다(관련도 함수 기반 다중 bump 아님).
- 다음 단계(EXP-011 제안): R7 단독은 채택하지 않는다. 병목은 '앙상블(log 공간 NNLS)이 원단위 R² 를 C1 단독
  {base_c1["cv_r2_raw"]:.3f} → 앙상블 {base_row["cv_r2_raw"]:.3f} 로 낮추는 구조'이므로, R1(분산 반영 복원·폭 보정)이나 앙상블 적합 기준
  검토와 함께 볼 때만 희소 가중 C1(예: `members(df, cols, {{"c1": Treatment(weight="rel", w_param=1.0)}})`)을 후보
  구성원으로 다시 시험할 가치가 있다. 참고 표처럼 v1 C1 단독은 ΔCV r2_raw {H.adoption(base_row, base_c1)["d_cv_r2_raw"]:+.3f}·ΔCV rmse_log
  {H.adoption(base_row, base_c1)["d_cv_rmse_log"]:+.3f} 로 rmse_log 조건만 근소하게 넘는다 — 앙상블 구성 자체가 종합 단계의 검토 대상이다.
"""
    (OUT_REP / "README.md").write_text(txt, encoding="utf-8", newline="\n")


def specs_alpha() -> float:
    return float(H.v1_specs()["c1"].alpha)


__all__ = [
    "CHOSEN",
    "Treatment",
    "cv_member",
    "members",
    "member_names",
    "resample_train",
    "sample_weights",
    "smogn_synth",
]


if __name__ == "__main__":
    raise SystemExit(main())
