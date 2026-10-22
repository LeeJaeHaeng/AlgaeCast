# ruff: noqa: E501  (한국어 보고서 문장·표 머리글 — black 110 은 통과)
"""EXP-011 종합 — R1~R7 구성 요소 누적 결합(전진 선택, 시드 3개 평균) → v2 후보(CV 선택).

배경(EXP-004~010)
- 단일 시드 CV r2_raw 는 LightGBM 시드만 바꿔도 ±0.02~0.03 흔들리고(v1 0.173/0.185/0.207), 관측과 무관한
  난수 열 3~10개만 더해도 +0.035~+0.051 오른다. 그래서 이 실험은 모든 구성을 시드 3개(42·7·2026)로 학습해
  시드 평균으로 비교하고, 피처 요소는 같은 개수의 난수 열 대조군과 짝지어 '고유 효과'를 함께 본다.
- 원단위 R² 이득의 큰 몫은 '로그 공간 NNLS 앙상블 → 원단위에 맞는 점예측' 전환에서 나온다(새 정보가 아님).
  그래서 정보 축(F2·F4·T5·M3)과 점예측 축(P0~P3)을 따로 다루고 단계마다 따로 표시한다(이중 계산 방지).

구성 요소
- 정보 축: F2 = R2 상류 피처(lag 0·1단계·all4_diff 5열), F4 = R4 영양염(tp_np 3열, OPERATIONAL 공개 지연 60일),
  T5 = R5 전국 82지점 통합 학습(변형은 상위 후보 3개 중 CV 로), M3 = R3 속별 합산(G2 log smear)을 NNLS 구성원으로 추가.
- 점예측 축: P0 = v1 log 공간 NNLS(연도 확장), P1 = R1 r_combine(원단위 볼록 결합, 연도 확장), P2 = C1 smearing 단독,
  P3 = R1 rh_gated_c(참고 행만, 선택 대상 아님).

평가 프로토콜(이 실험 전용)
- 구성마다 시드별로 회귀 구성원(C1·C3·C2, M3 이면 속별 2부분)과 분위(q10·q50·q90, fit_quantiles 에 seed 전달)를
  학습하고 시드별 ``harness.metric_row`` 를 구한다. 시드 42 표준 표 + 시드 평균·최소·최대 + v1 대비 시드별 짝 차이 평균 Δ.
- 피처 요소 대조군: 같은 개수의 표준정규 난수 열(시드마다 다른 난수 → 3벌). 고유 효과 = Δ(피처) − Δ(대조군).
- 전진 선택(CV 만): v1(P0)에서 출발해 남은 정보 축 요소를 하나씩 더해 보고, 시드 평균 CV r2_raw 증가가 가장 크고
  (i) 시드 평균 Δrmse_log ≤ +0.01(v1 대비), (ii) 시드 평균 리드타임 ≥ v1, (iii) 피처 요소는 고유 효과 > 0 인 것을
  채택한다. 증가가 +0.01 미만이면 멈춘다. 최종 정보 구성 위에서 P0~P2 를 같은 (i)(ii) 조건 아래 CV 로 고른다.
- v2 후보: 누적 경로 구성 × P0~P2 중 채택 기준(시드 평균 Δr2_raw ≥ +0.10, Δrmse_log ≤ +0.01, 리드타임 ≥ v1)을
  만족하는 것 중 CV r2_raw 최대. 2025 는 확인용 표시만, 2026 은 읽지 않는다(harness.load_base·guard_no_2026).
- 최종 후보의 Δ CV r2_raw 는 (연도·지점) 블록 부트스트랩 95% 구간으로 보고한다.

공개 함수
- ``v2_candidate(df, seed=42) -> dict``: 최종 후보(``V2``) 구성의 OOF 구성원(c1·c1_none·c1_log·c3·c2·q10·q50·q90,
  M3 이면 cg·cg_micro·cg_rest)과 ens(P0)·pred(최종 점예측). df 는 ``harness.load_base()`` 형식.
- 조합 함수: ``Combo``·``parse_key``·``feature_cols``·``control_columns``·``frame_for``·``combo_members``·``point_preds``.

실행: ``python -m algaecast.exp.r_combo [--workers 4] [--fresh]`` → reports/experiments/EXP-011/, data/processed/exp/EXP-011/
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.config import ROOT
from algaecast.exp import harness as H

log = logging.getLogger(__name__)

EXP_ID = "EXP-011"
OUT_REPORT = H.EXP_REPORTS / EXP_ID
OUT_DATA = H.EXP_DATA / EXP_ID
CACHE = OUT_DATA / "cache"
FEATURES_PATH = OUT_DATA / "features.parquet"
BUDGET_HOURS = 6.0
TASK_START = "2026-10-22 09:16:36"  # 작업 착수(KST) — 시간 상한 기준

SEEDS: tuple[int, ...] = (42, 7, 2026)
CTRL_SALT = 20261022  # 대조군 난수 생성기 시드 앞부분(시드·열 수와 묶어 쓴다)
T5_VARIANTS: tuple[str, ...] = ("all_noembed_w5", "all_noembed_w10", "nakgeum_noembed_w5")
ELEMENTS: tuple[str, ...] = ("F2", "F4", "T5", "M3")
FEATURE_ELEMENTS: tuple[str, ...] = ("F2", "F4")
POINTS: tuple[str, ...] = ("P0", "P1", "P2", "P3")
SELECTABLE_POINTS: tuple[str, ...] = ("P0", "P1", "P2")
MIN_GAIN = 0.01  # 전진 선택: 시드 평균 CV r2_raw 증가가 이보다 작으면 멈춤
RMSE_SLACK = 0.01  # 채택 기준 rmse_log 악화 허용(v1 대비)
ADOPT_R2 = 0.10  # 채택 기준 r2_raw 상승(v1 대비)
W_STEP = 0.01  # P1 볼록 결합 가중치 격자
N_BOOT = 2000
BOOT_SEED = 42

ELEMENT_LABEL = {
    "F2": "F2 상류 피처(R2, lag0·1단계 5열)",
    "F4": "F4 영양염(R4 tp_np, 공개 지연 60일 3열)",
    "T5": "T5 전국 통합 학습(R5)",
    "M3": "M3 속별 합산 NNLS 구성원(R3 G2)",
}
POINT_LABEL = {
    "P0": "P0 log NNLS",
    "P1": "P1 원단위 볼록 결합",
    "P2": "P2 C1 smearing 단독",
    "P3": "P3 rh_gated_c(참고)",
}
T5_SHORT = {"all_noembed_w5": "전국·w5", "all_noembed_w10": "전국·w10", "nakgeum_noembed_w5": "낙동강금강·w5"}

# main() 의 CV 규칙 결과로 고정(다르면 main 이 경고). v2_candidate() 기본값.
V2: dict[str, str] = {"combo": "T5[nakgeum_noembed_w5]", "point": "P2"}
# 3.9 민감도(분위 v1 고정) 경로의 정보 축만 구성 — 선택 결과가 아닌 사용자 판단용 견고성 대안.
ROBUST_ALT: dict[str, str] = {"combo": "F2+M3", "point": "P0", "q_ref": "v1"}

OPERATIONAL_NOTES: dict[str, str] = {
    "F2": "상류 지점(해평·강정고령·칠서)은 우리 5지점 자신이라 추가 수집이 없다. 다만 lag 0 은 상류의 같은 날 채수값을 쓰므로 v1 `cell_log_t0` 와 같은 공개 시점 제약(2025-08 이전 공개는 채수 3일차)을 그대로 진다.",
    "F4": "수질측정망 DB(`NIER_WQDB_KEY`) 수집기 추가 필요. 공개 지연이 약 55일이라 OPERATIONAL(지연 60일) 설정만 운영에서 재현된다(월 1회 갱신이면 충분).",
    "T5": "예측 시점에는 우리 5지점 피처만 쓰므로 일일 파이프라인 부담은 없다. 재학습 때만 전국 82지점 조류(같은 API, ptNoList 없이)·ASOS 27곳·수문 자료와 다른 지점 표본 생성(약 25분)이 필요하다.",
    "M3": "속별 세포수는 v1 이 이미 받는 조류경보 API 응답 열이라 추가 수집이 없다. 속별 모델 2개(학습·예측)만 늘어난다.",
    "P1": "자료 추가 없음. 연도 확장으로 적합한 결합 가중치(합=1) 하나만 운영 설정에 더하면 된다.",
    "P2": "자료 추가 없음. C1(smearing) 예측을 그대로 점예측으로 쓴다(앙상블 생략).",
    "P3": "자료 추가 없음. 다만 EXP-004 검증에서 2025 확인 −0.657 로 견고성이 부족해 참고로만 둔다.",
}


# ================================================================ 1. 구성(조합) 정의
@dataclass(frozen=True)
class Combo:
    """정보 축 구성 하나. ctrl 은 대조군 난수 열 수(선택 후보 아님), ctrl_mask='F2' 는 F2 결측 위치를 따르는 진단용 난수."""

    f2: bool = False
    f4: bool = False
    t5: str = ""
    m3: bool = False
    ctrl: int = 0
    ctrl_mask: str = ""

    @property
    def key(self) -> str:
        parts = []
        if self.f2:
            parts.append("F2")
        if self.f4:
            parts.append("F4")
        if self.t5:
            parts.append(f"T5[{self.t5}]")
        if self.m3:
            parts.append("M3")
        if self.ctrl:
            parts.append(f"C{self.ctrl}" + ("m" if self.ctrl_mask else ""))
        return "+".join(parts) or "v1"

    @property
    def label(self) -> str:
        if self.key == "v1":
            return "v1 기준"
        parts = []
        if self.f2:
            parts.append("F2")
        if self.f4:
            parts.append("F4")
        if self.t5:
            parts.append(f"T5({T5_SHORT.get(self.t5, self.t5)})")
        if self.m3:
            parts.append("M3")
        base = "v1+" + "+".join(parts) if parts else "v1"
        if self.ctrl:
            base += f" + 대조 난수 {self.ctrl}열" + ("(F2 결측 위치)" if self.ctrl_mask else "")
        return base

    @property
    def base(self) -> Combo:
        """회귀·분위 구성원을 결정하는 부분(M3 제외)."""
        return replace(self, m3=False)

    @property
    def genus(self) -> Combo:
        """속별 모델을 결정하는 부분(피처 열만: T5·M3 제외 — 속별 타깃은 우리 5지점에만 있다)."""
        return replace(self, t5="", m3=False)

    def has(self, element: str) -> bool:
        return {"F2": self.f2, "F4": self.f4, "T5": bool(self.t5), "M3": self.m3}[element]

    def add(self, element: str, t5_variant: str = "") -> Combo:
        if element == "F2":
            return replace(self, f2=True)
        if element == "F4":
            return replace(self, f4=True)
        if element == "T5":
            if t5_variant not in T5_VARIANTS:
                raise ValueError(f"T5 변형은 {T5_VARIANTS} 중 하나: {t5_variant!r}")
            return replace(self, t5=t5_variant)
        if element == "M3":
            return replace(self, m3=True)
        raise ValueError(element)

    def with_control(self, k: int, mask: str = "") -> Combo:
        return replace(self, ctrl=k, ctrl_mask=mask)

    @property
    def elements(self) -> tuple[str, ...]:
        return tuple(e for e in ELEMENTS if self.has(e))


_KEY_RE = re.compile(r"^(F2|F4|T5\[([a-z0-9_]+)\]|M3|C(\d+)(m?))$")


def parse_key(key: str) -> Combo:
    """Combo.key 의 역함수."""
    if key == "v1":
        return Combo()
    c = Combo()
    for part in key.split("+"):
        m = _KEY_RE.match(part)
        if not m:
            raise ValueError(f"알 수 없는 구성 키 조각: {part!r}")
        if part == "F2":
            c = replace(c, f2=True)
        elif part == "F4":
            c = replace(c, f4=True)
        elif part == "M3":
            c = replace(c, m3=True)
        elif part.startswith("T5"):
            c = replace(c, t5=m.group(2))
        else:
            c = replace(c, ctrl=int(m.group(3)), ctrl_mask="F2" if m.group(4) else "")
    if c.key != key:
        raise ValueError(f"구성 키 순서가 표준과 다르다: {key!r} → {c.key!r}")
    return c


def f2_cols() -> list[str]:
    from algaecast.exp import r2_upstream as R2

    return R2.columns_for(int(R2.CHOSEN["depth"]), str(R2.CHOSEN["bundle"]))


def f4_cols() -> list[str]:
    from algaecast.exp import r4_nutrients as R4

    return list(R4.OPERATIONAL.cols)


def ctrl_cols(k: int) -> list[str]:
    return [f"ctrl_rnd_{i}" for i in range(k)]


def feature_cols(combo: Combo, base: list[str] | None = None) -> list[str]:
    """구성의 모델 피처: v1 30개 + F2(5) + F4(3) + 대조 난수 열. T5 의 플래그·임베딩 처리는 R5.variant_cols 가 한다."""
    cols = list(base if base is not None else H.base_columns())
    if combo.f2:
        cols += f2_cols()
    if combo.f4:
        cols += f4_cols()
    if combo.ctrl:
        cols += ctrl_cols(combo.ctrl)
    return cols


def control_columns(
    index: pd.Index, k: int, seed: int, mask: np.ndarray | None = None, salt: int = CTRL_SALT
) -> pd.DataFrame:
    """대조군: 관측과 무관한 표준정규 난수 k열. 생성기 시드 = (salt, 학습 시드, k) → 시드마다 다른 난수.

    mask (n, m) 가 있으면 i 번째 열은 mask[:, i % m] 가 False 인 행을 NaN 으로 둔다(진단용: 피처 결측 위치 흉내).
    """
    rng = np.random.default_rng([salt, int(seed), int(k)])
    vals = rng.standard_normal((len(index), k))
    if mask is not None:
        mask = np.asarray(mask, dtype=bool)
        for i in range(k):
            vals[~mask[:, i % mask.shape[1]], i] = np.nan
    return pd.DataFrame(vals, index=index, columns=ctrl_cols(k))


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """F2(R2 build_features)·F4(R4 OPERATIONAL) 새 열(같은 인덱스). 두 함수 모두 as_of 규칙(cut_as_of)으로 만든다."""
    from algaecast.exp import r2_upstream as R2
    from algaecast.exp import r4_nutrients as R4

    H.guard_no_2026(df)
    f2 = R2.build_features(df)[f2_cols()]
    f4 = R4.build_features(df, cfg=R4.OPERATIONAL)[f4_cols()]
    return pd.concat([f2, f4], axis=1)


def load_features(df: pd.DataFrame) -> pd.DataFrame:
    """저장한 F2·F4 열(키 대조 후). 없거나 키가 다르면 새로 만든다."""
    if FEATURES_PATH.exists():
        f = pd.read_parquet(FEATURES_PATH)
        same = (
            len(f) == len(df)
            and (f["station_id"].astype(str).to_numpy() == df["station_id"].astype(str).to_numpy()).all()
        )
        same = (
            same
            and (
                pd.to_datetime(f["base_date"]).to_numpy() == pd.to_datetime(df["base_date"]).to_numpy()
            ).all()
        )
        if same:
            return f[f2_cols() + f4_cols()].set_axis(df.index)
    return build_features(df)


def frame_for(df: pd.DataFrame, feats: pd.DataFrame | None, combo: Combo, seed: int) -> pd.DataFrame:
    """구성 학습 프레임: df(load_base 형식) + 필요한 새 열 + 대조 난수 열. 2026 행이 있으면 중단."""
    H.guard_no_2026(df)
    parts = [df]
    need = (f2_cols() if combo.f2 else []) + (f4_cols() if combo.f4 else [])
    if need or combo.ctrl_mask:
        if feats is None:
            raise ValueError("F2·F4 열이 필요한 구성인데 feats 가 없다")
        if need:
            parts.append(feats.loc[df.index, need])
    if combo.ctrl:
        mask = feats.loc[df.index, f2_cols()].notna().to_numpy() if combo.ctrl_mask == "F2" else None
        parts.append(control_columns(df.index, combo.ctrl, seed, mask=mask))
    out = pd.concat(parts, axis=1) if len(parts) > 1 else df
    H.guard_no_2026(out)
    return out


# ================================================================ 2. 시드별 구성원 학습
def own_quantiles(df: pd.DataFrame, cols: list[str], seed: int) -> dict[str, np.ndarray]:
    """quantile.cv_quantiles 와 같은 폴드·식이되 fit_quantiles 에 seed 를 넘긴다."""
    from algaecast.models.cv import year_folds
    from algaecast.models.quantile import fit_quantiles, predict_quantiles

    H.guard_no_2026(df)
    spec = H.v1_specs()["c1"]
    out = {k: np.full(len(df), np.nan) for k in ("q10", "q50", "q90")}
    for fo in year_folds(df, include_final=True):
        models = fit_quantiles(df.iloc[fo.train_idx], cols, spec, seed=seed)
        pr = predict_quantiles(models, df.iloc[fo.valid_idx], cols)
        for k in out:
            out[k][fo.valid_idx] = pr[k]
    return out


def own_members(df: pd.DataFrame, cols: list[str], seed: int) -> dict[str, np.ndarray]:
    """우리 5지점만: harness.run_members(seeds=(seed,)) 회귀 구성원 + 시드 분위."""
    H.guard_no_2026(df)
    out = H.run_members(df, cols, seeds=(seed,), quantiles=False)
    out.update(own_quantiles(df, cols, seed))
    return out


_OTHER: dict[str, pd.DataFrame] = {}


def _other_samples() -> pd.DataFrame:
    from algaecast.exp import r5_national as R5

    if "all" not in _OTHER:
        _OTHER["all"] = R5.load_other_samples()
    return _OTHER["all"]


def pooled_members(df: pd.DataFrame, cols: list[str], variant: str, seed: int) -> dict[str, np.ndarray]:
    """R5 통합 학습(r5_national.pooled_cv 와 같은 폴드·가중·smearing)이되 fold_members 에 seed 를 넘긴다.

    df 에만 있는 새 열(F2·F4·대조 난수)은 다른 지점 행에서 NaN 이다(R5.combine 의 reindex).
    """
    from algaecast.exp import r5_national as R5

    H.guard_no_2026(df)
    v = R5.VARIANTS[variant]
    if v.prior or v.site_hist:
        raise ValueError(f"EXP-011 은 prior·site_hist 변형을 쓰지 않는다: {variant}")
    other = _other_samples()
    other = other[R5.subset_mask(other, v.subset)]
    vcols = R5.variant_cols(cols, v)
    specs = H.v1_specs()
    comb, own = R5.combine(df, other, vcols)
    years = comb["base_date"].dt.year.to_numpy()
    sw_all = np.where(own, v.w_own, 1.0) if v.w_own != 1.0 else None
    keys = ["c1", "c1_none", "c1_log", "c3", "c2", "q10", "q50", "q90"]
    oof = {k: np.full(len(df), np.nan) for k in keys}
    for _name, _vy, tr_m, va_m in R5.fold_plan(years, own):
        tr, va = comb[tr_m].copy(), comb[va_m].copy()
        sw = None if sw_all is None else sw_all[tr_m]
        pr = R5.fold_members(
            tr, va, vcols, specs, sw, own[tr_m], smear_scope=v.smear_scope, quantiles=True, seed=seed
        )
        idx = np.where(va_m)[0]  # 우리 지점 행은 comb 앞부분 = df 행 위치
        for k in keys:
            oof[k][idx] = pr[k]
    return oof


def genus_members(df: pd.DataFrame, cols: list[str], seed: int) -> dict[str, np.ndarray]:
    """R3 선택 설정(G2: Microcystis + 나머지 3속, log, smearing)을 seed 로 학습한 속별 합산 cg."""
    from algaecast.exp import r3_genus as R3

    H.guard_no_2026(df)
    cfg = R3.CHOSEN
    tg = R3.genus_targets(df, R3.load_algae())
    spec = H.v1_specs()["c1"]
    parts = {
        p: R3.fit_component(df, cols, R3.part_target(tg, p), cfg["modes"][p], spec, seed=seed)[cfg["bias"]]
        for p in R3.LAYOUTS[cfg["layout"]]
    }
    out = {"cg": np.sum(list(parts.values()), axis=0)}
    out.update({f"cg_{p}": v for p, v in parts.items()})
    return out


def combo_members(
    df: pd.DataFrame, feats: pd.DataFrame | None, combo: Combo, seed: int
) -> dict[str, np.ndarray]:
    """구성 하나의 시드별 OOF 구성원(2020~2025 행만 값). 캐시 없이 바로 학습한다."""
    H.guard_no_2026(df)
    dfx = frame_for(df, feats, combo, seed)
    cols = feature_cols(combo)
    mem = pooled_members(dfx, cols, combo.t5, seed) if combo.t5 else own_members(dfx, cols, seed)
    if combo.m3:
        mem.update(genus_members(frame_for(df, feats, combo.genus, seed), feature_cols(combo.genus), seed))
    return mem


# ---------------------------------------------------------------- 캐시·병렬
def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_+\-]", "_", key)


def cache_path(kind: str, combo: Combo, seed: int) -> Path:
    c = combo.base if kind == "base" else combo.genus
    return CACHE / f"{kind}__{_safe(c.key)}__s{seed}.parquet"


def _job(args: tuple[str, str, int]) -> str:
    """병렬 작업 하나(별도 프로세스): kind ∈ {base, cg}. 결과를 캐시 parquet 로 쓴다."""
    kind, key, seed = args
    combo = parse_key(key)
    path = cache_path(kind, combo, seed)
    if path.exists():
        return str(path)
    t0 = time.time()
    df = H.load_base()
    feats = load_features(df)
    if kind == "base":
        c = combo.base
        dfx = frame_for(df, feats, c, seed)
        cols = feature_cols(c)
        mem = pooled_members(dfx, cols, c.t5, seed) if c.t5 else own_members(dfx, cols, seed)
    else:
        c = combo.genus
        mem = genus_members(frame_for(df, feats, c, seed), feature_cols(c), seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pd.DataFrame(mem).to_parquet(tmp, index=False)
    tmp.replace(path)
    return f"{path.name} {time.time() - t0:.0f}s"


def jobs_for(combos: Iterable[Combo], seeds: Iterable[int] = SEEDS) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    for c in combos:
        for s in seeds:
            for kind in ("base", "cg") if c.m3 else ("base",):
                if not cache_path(kind, c, s).exists():
                    job = (kind, (c.base if kind == "base" else c.genus).key, s)
                    if job not in out:
                        out.append(job)
    return out


def run_jobs(jobs: list[tuple[str, str, int]], workers: int, budget: H.Budget | None = None) -> None:
    """작업을 병렬(프로세스 workers 개, 각 LightGBM n_jobs=4)로 돌린다. 오래 걸리는 T5 를 먼저."""
    if not jobs:
        return
    jobs = sorted(jobs, key=lambda j: (0 if "T5" in j[1] else 1, j[1], j[2]))
    log.info("학습 작업 %d개(병렬 %d)", len(jobs), workers)
    if workers <= 1 or len(jobs) == 1:
        for j in jobs:
            if budget is not None:
                budget.check()
            log.info("  %s", _job(j))
        return
    from algaecast.exp import (
        r_combo as _self,  # __main__ 이 아닌 모듈 이름으로 넘겨 하위 프로세스가 import 한다
    )

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_self._job, j): j for j in jobs}
        for f in as_completed(futs):
            log.info("  %s", f.result())
    if budget is not None:
        budget.check()


def load_members(combo: Combo, seed: int) -> dict[str, np.ndarray]:
    o = pd.read_parquet(cache_path("base", combo, seed))
    mem = {k: o[k].to_numpy(dtype=float) for k in o.columns}
    if combo.m3:
        g = pd.read_parquet(cache_path("cg", combo, seed))
        mem.update({k: g[k].to_numpy(dtype=float) for k in g.columns})
    return mem


# ================================================================ 3. 점예측 축
def convex_weights(M: np.ndarray, obs: np.ndarray, step: float = W_STEP, chunk: int = 4096) -> np.ndarray:
    """합=1·비음수 격자(R1.simplex_grid) 중 원단위 MSE 최소 가중치. 후보를 나눠 계산해 4구성원도 메모리 안에서 푼다.

    동률이면 격자 순서상 앞의 후보(R1.select_params 의 argmin 과 같은 규칙).
    """
    from algaecast.exp.r1_variance_restore import simplex_grid

    W = simplex_grid(M.shape[1], step)
    best, best_err = W[0], np.inf
    for i in range(0, len(W), chunk):
        Wc = W[i : i + chunk]
        err = np.mean((Wc @ M.T - obs[None, :]) ** 2, axis=1)
        j = int(np.argmin(err))
        if err[j] < best_err:
            best_err, best = float(err[j]), Wc[j]
    return best.astype(float)


def convex_expanding(
    df: pd.DataFrame, members: dict[str, np.ndarray], fallback: np.ndarray
) -> tuple[np.ndarray, dict[int, dict[str, float] | None]]:
    """P1: 구성원 원단위 볼록 결합(연도 확장, R1 r_combine 과 같은 규칙). 적합 자료 없는 2020 은 fallback(P0)."""
    names = list(members)
    M = np.column_stack([np.asarray(members[k], dtype=float) for k in names])
    obs = df["target_cells"].to_numpy(dtype=float)
    years = H.years_of(df)
    rec: dict[int, dict[str, float] | None] = {}

    def fit(mask: np.ndarray) -> np.ndarray:
        return convex_weights(M[mask], obs[mask])

    def apply(state: np.ndarray | None, mask: np.ndarray) -> np.ndarray:
        if not mask.any():
            return np.empty(0)
        yv = int(years[mask][0])
        rec[yv] = (
            None if state is None else {k: round(float(w), 3) for k, w in zip(names, state, strict=True)}
        )
        if state is None:
            return np.asarray(fallback, dtype=float)[mask].copy()
        return np.clip(M[mask] @ state, 0.0, None)

    return H.expanding_fit_apply(df, fit, apply), rec


def member_names(m3: bool) -> tuple[str, ...]:
    return ("c1", "c3", "c2", "cg") if m3 else ("c1", "c3", "c2")


def point_preds(
    df: pd.DataFrame, mem: dict[str, np.ndarray], m3: bool, points: Iterable[str] = POINTS
) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    """점예측 축 P0~P3. (예측, 가중치 기록)"""
    from algaecast.exp import r1_variance_restore as R1

    H.guard_no_2026(df)
    names = member_names(m3)
    p0, w0 = H.ensemble_expanding(df, mem, names=names)
    preds: dict[str, np.ndarray] = {"P0": p0}
    info: dict[str, object] = {"P0": w0}
    points = tuple(points)
    if "P1" in points:
        preds["P1"], info["P1"] = convex_expanding(df, {k: mem[k] for k in names}, p0)
    if "P2" in points:
        preds["P2"] = np.asarray(mem["c1"], dtype=float).copy()
    if "P3" in points:
        pr = {k: mem[k] for k in ("c1", "c1_log", "c3", "c2", "q10", "q50", "q90")}
        pr["ens"] = p0
        preds["P3"], info["P3"] = R1.run_variant(df, pr, "rh_gated_c")
    return preds, info


# ================================================================ 4. 지표·요약
def r2_fast(obs: np.ndarray, pred: np.ndarray) -> float:
    """원단위 R²(= NSE) = 1 − Σ(o−p)²/Σ(o−ō)²."""
    sst = float(np.sum((obs - obs.mean()) ** 2))
    return float(1.0 - np.sum((obs - pred) ** 2) / sst) if sst > 0 else float("nan")


def year_r2(df: pd.DataFrame, pred: np.ndarray) -> dict[int, float]:
    obs = df["target_cells"].to_numpy(dtype=float)
    years = H.years_of(df)
    out = {}
    for y in H.CV_YEARS:
        m = (years == y) & np.isfinite(pred)
        out[int(y)] = r2_fast(obs[m], pred[m])
    return out


SUMMARY_METRICS: tuple[str, ...] = (
    "cv_r2_raw",
    "cv_nse_raw",
    "cv_rmse_log",
    "cv_r2_log",
    "cv_f1_10k",
    "cvfold_r2_raw",
    "cvfold_rmse_log",
    "lead_q90",
    "lead_point",
    "y2025_r2_raw",
    "y2025_rmse_log",
    *(f"cv{y}_r2_raw" for y in H.CV_YEARS),
)


class Evaluator:
    """(구성, 시드) → 점예측 P0~P3 의 표준 지표 행. 결과를 메모리에 모은다."""

    def __init__(self, df: pd.DataFrame, q_ref: str = "") -> None:
        """q_ref 가 있으면(민감도 진단) 분위 q10·q50·q90 를 그 구성(같은 시드)의 것으로 바꿔 평가한다 — 분위 모델 고정."""
        H.guard_no_2026(df)
        self.df = df
        self.q_ref = q_ref
        self.rows: dict[tuple[str, str, int], dict] = {}
        self.preds: dict[tuple[str, str, int], np.ndarray] = {}
        self.weights: dict[tuple[str, int], dict] = {}
        self.q90: dict[tuple[str, int], np.ndarray] = {}

    def evaluate(self, combo: Combo, seeds: Iterable[int] = SEEDS) -> None:
        for s in seeds:
            if (combo.key, "P0", s) in self.rows:
                continue
            mem = load_members(combo, s)
            if self.q_ref:
                ref = load_members(parse_key(self.q_ref), s)
                mem.update({k: ref[k] for k in ("q10", "q50", "q90")})
            preds, info = point_preds(self.df, mem, combo.m3)
            self.weights[(combo.key, s)] = {p: info.get(p) for p in ("P0", "P1")}
            self.q90[(combo.key, s)] = mem["q90"]
            suffix = f" (분위 {self.q_ref} 고정)" if self.q_ref else ""
            for p, pred in preds.items():
                r = H.metric_row(self.df, pred, mem["q90"], f"{combo.label} · {POINT_LABEL[p]}{suffix}")
                r.update({"key": combo.key, "point": p, "seed": int(s)})
                r.update({f"cv{y}_r2_raw": v for y, v in year_r2(self.df, pred).items()})
                self.rows[(combo.key, p, s)] = r
                self.preds[(combo.key, p, s)] = pred

    def row(self, key: str, point: str, seed: int) -> dict:
        return self.rows[(key, point, seed)]

    def summary(self, key: str, point: str = "P0", ref: tuple[str, str] = ("v1", "P0")) -> dict:
        """시드 평균·최소·최대 + 기준(ref, 같은 시드) 대비 짝 차이 평균 Δ."""
        rs = [self.rows[(key, point, s)] for s in SEEDS]
        bs = [self.rows[(ref[0], ref[1], s)] for s in SEEDS]
        out: dict = {"key": key, "point": point, "label": rs[0]["구성"]}
        for m in SUMMARY_METRICS:
            v = np.array([float(r[m]) for r in rs])
            out[f"{m}_mean"], out[f"{m}_min"], out[f"{m}_max"] = (
                float(v.mean()),
                float(v.min()),
                float(v.max()),
            )
            out[f"{m}_seeds"] = [float(x) for x in v]
            d = v - np.array([float(b[m]) for b in bs])
            out[f"d_{m}"] = float(d.mean())
        return out


# ================================================================ 5. 전진 선택
def candidate_record(
    ev: Evaluator, current: Combo, cand: Combo, element: str, v1: str = "v1", ctrl: Combo | None = None
) -> dict:
    """후보 하나의 판정 재료(시드 짝 차이 평균). 조건 (i)(ii)(iii) 와 적격 여부."""
    s_cand = ev.summary(cand.key)
    s_cur = ev.summary(cand.key, ref=(current.key, "P0"))
    s_v1 = ev.summary(v1)
    rec = {
        "element": element,
        "key": cand.key,
        "label": cand.label,
        "cv_r2_raw": s_cand["cv_r2_raw_mean"],
        "cv_r2_raw_min": s_cand["cv_r2_raw_min"],
        "cv_r2_raw_max": s_cand["cv_r2_raw_max"],
        "gain": s_cur["d_cv_r2_raw"],
        "gain_rmse": s_cur["d_cv_rmse_log"],
        "d_r2_v1": s_cand["d_cv_r2_raw"],
        "d_rmse_v1": s_cand["d_cv_rmse_log"],
        "lead": s_cand["lead_q90_mean"],
        "lead_v1": s_v1["lead_q90_mean"],
        "y2025_r2_raw": s_cand["y2025_r2_raw_mean"],
        "y2025_rmse_log": s_cand["y2025_rmse_log_mean"],
        "cvfold_r2_raw": s_cand["cvfold_r2_raw_mean"],
    }
    rec["ok_rmse"] = bool(rec["d_rmse_v1"] <= RMSE_SLACK + 1e-12)
    rec["ok_lead"] = bool(rec["lead"] >= rec["lead_v1"] - 1e-9)
    if ctrl is not None:
        s_ctrl = ev.summary(ctrl.key, ref=(current.key, "P0"))
        rec.update(
            {
                "ctrl_key": ctrl.key,
                "ctrl_gain": s_ctrl["d_cv_r2_raw"],
                "ctrl_gain_rmse": s_ctrl["d_cv_rmse_log"],
                "unique": rec["gain"] - s_ctrl["d_cv_r2_raw"],
                "unique_rmse": rec["gain_rmse"] - s_ctrl["d_cv_rmse_log"],
            }
        )
        rec["ok_ctrl"] = bool(rec["unique"] > 0)
    else:
        rec["ok_ctrl"] = True
    rec["eligible"] = bool(rec["ok_rmse"] and rec["ok_lead"] and rec["ok_ctrl"])
    return rec


def pick_t5(records: list[dict]) -> dict:
    """T5 변형 선택(CV): 조건 (i)(ii) 를 만족하는 변형 중 증가 최대, 없으면 증가 최대."""
    ok = [r for r in records if r["eligible"]]
    pool = ok or records
    return max(pool, key=lambda r: r["gain"])


def decide_step(records: list[dict], min_gain: float = MIN_GAIN) -> tuple[dict | None, str]:
    """적격 후보 중 증가 최대를 고르고, 증가가 min_gain 미만이면 멈춘다. (채택 후보 또는 None, 사유)"""
    elig = [r for r in records if r["eligible"]]
    if not elig:
        return None, "적격 후보 없음(조건 (i)(ii)(iii) 불만족)"
    best = max(elig, key=lambda r: r["gain"])
    if best["gain"] < min_gain:
        return None, f"적격 후보 최대 증가 {best['gain']:+.3f} < +{min_gain:.2f} → 멈춤"
    return best, f"{best['element']} 채택(증가 {best['gain']:+.3f})"


def step_candidates(current: Combo) -> tuple[dict[str, list[Combo]], dict[str, Combo]]:
    """현재 구성에서 더해 볼 후보(요소별, T5 는 변형 3개)와 피처 요소의 대조군 구성."""
    cands: dict[str, list[Combo]] = {}
    ctrls: dict[str, Combo] = {}
    for e in ELEMENTS:
        if current.has(e):
            continue
        if e == "T5":
            cands[e] = [current.add("T5", v) for v in T5_VARIANTS]
        else:
            cands[e] = [current.add(e)]
        if e in FEATURE_ELEMENTS:
            k = len(f2_cols()) if e == "F2" else len(f4_cols())
            ctrls[e] = current.with_control(k)
    return cands, ctrls


def forward_select(ev: Evaluator, workers: int, budget: H.Budget) -> dict:
    """v1(P0)에서 출발하는 전진 선택. 단계 기록과 경로를 돌려준다."""
    current = Combo()
    path = [current]
    steps: list[dict] = []
    diag: list[dict] = []
    run_jobs(jobs_for([current]), workers, budget)
    ev.evaluate(current)
    k = 0
    while True:
        k += 1
        cands, ctrls = step_candidates(current)
        if not cands:
            steps.append(
                {"step": k, "current": current.key, "records": [], "chosen": None, "reason": "남은 요소 없음"}
            )
            break
        combos = [c for cs in cands.values() for c in cs] + list(ctrls.values())
        extra = []
        if k == 1 and "F2" in cands:
            extra = [current.with_control(len(f2_cols()), mask="F2")]  # 진단: F2 결측 위치 난수
        run_jobs(jobs_for(combos + extra), workers, budget)
        for c in combos + extra:
            ev.evaluate(c)
        records: list[dict] = []
        t5_all: list[dict] = []
        for e, cs in cands.items():
            if e == "T5":
                t5_all = [candidate_record(ev, current, c, "T5") for c in cs]
                records.append({**pick_t5(t5_all), "t5_variants": t5_all})
            else:
                records.append(candidate_record(ev, current, cs[0], e, ctrl=ctrls.get(e)))
        for c in extra:
            diag.append({"step": k, **candidate_record(ev, current, c, "진단")})
        chosen, reason = decide_step(records)
        steps.append(
            {
                "step": k,
                "current": current.key,
                "records": records,
                "chosen": None if chosen is None else chosen["key"],
                "reason": reason,
            }
        )
        log.info("단계 %d: %s", k, reason)
        if chosen is None:
            break
        current = parse_key(chosen["key"])
        path.append(current)
    return {"steps": steps, "path": [c.key for c in path], "final": current.key, "diag": diag}


def choose_point(ev: Evaluator, key: str) -> tuple[str, list[dict]]:
    """최종 정보 구성 위 점예측 축 선택: (i)(ii) 를 만족하는 P0~P2 중 시드 평균 CV r2_raw 최대(P3 는 참고)."""
    recs = []
    lead_v1 = ev.summary("v1")["lead_q90_mean"]
    for p in POINTS:
        s = ev.summary(key, p)
        rec = {
            "point": p,
            "label": POINT_LABEL[p],
            "cv_r2_raw": s["cv_r2_raw_mean"],
            "cv_r2_raw_min": s["cv_r2_raw_min"],
            "cv_r2_raw_max": s["cv_r2_raw_max"],
            "d_r2_v1": s["d_cv_r2_raw"],
            "d_rmse_v1": s["d_cv_rmse_log"],
            "cv_rmse_log": s["cv_rmse_log_mean"],
            "lead": s["lead_q90_mean"],
            "cvfold_r2_raw": s["cvfold_r2_raw_mean"],
            "y2025_r2_raw": s["y2025_r2_raw_mean"],
            "y2025_rmse_log": s["y2025_rmse_log_mean"],
            "selectable": p in SELECTABLE_POINTS,
        }
        rec["ok"] = bool(rec["d_rmse_v1"] <= RMSE_SLACK + 1e-12 and rec["lead"] >= lead_v1 - 1e-9)
        recs.append(rec)
    pool = [r for r in recs if r["selectable"] and r["ok"]] or [r for r in recs if r["selectable"]]
    return max(pool, key=lambda r: r["cv_r2_raw"])["point"], recs


def adoption_mean(s: dict, lead_v1: float) -> dict:
    """채택 기준(시드 평균 Δ, v1 대비)."""
    lead_ok = s["lead_q90_mean"] >= lead_v1 - 1e-9
    return {
        "d_cv_r2_raw": s["d_cv_r2_raw"],
        "d_cv_rmse_log": s["d_cv_rmse_log"],
        "lead": s["lead_q90_mean"],
        "lead_v1": lead_v1,
        "lead_ok": bool(lead_ok),
        "pass": bool(s["d_cv_r2_raw"] >= ADOPT_R2 and s["d_cv_rmse_log"] <= RMSE_SLACK + 1e-12 and lead_ok),
    }


def v2_decision(ev: Evaluator, path: list[str]) -> dict:
    """누적 경로 구성 × P0~P2 중 채택 기준 통과 최대 CV r2_raw. 없으면 가장 가까운 구성."""
    lead_v1 = ev.summary("v1")["lead_q90_mean"]
    table = []
    for key in path:
        for p in SELECTABLE_POINTS:
            s = ev.summary(key, p)
            a = adoption_mean(s, lead_v1)
            table.append({"key": key, "point": p, "label": s["label"], "cv_r2_raw": s["cv_r2_raw_mean"], **a})
    passed = [t for t in table if t["pass"]]
    if passed:
        best = max(passed, key=lambda t: t["cv_r2_raw"])
        return {"found": True, "key": best["key"], "point": best["point"], "table": table, "nearest": None}
    ok2 = [t for t in table if t["d_cv_rmse_log"] <= RMSE_SLACK + 1e-12 and t["lead_ok"]]
    near = max(ok2 or table, key=lambda t: t["d_cv_r2_raw"])
    return {"found": False, "key": near["key"], "point": near["point"], "table": table, "nearest": near}


# ================================================================ 6. 블록 부트스트랩
def block_bootstrap(
    df: pd.DataFrame,
    cand: list[np.ndarray],
    base: list[np.ndarray],
    *,
    blocks: str = "year_site",
    n_boot: int = N_BOOT,
    seed: int = BOOT_SEED,
) -> dict:
    """CV(2020~2024) 행 블록 부트스트랩으로 시드 평균 Δr2_raw(cand − base) 분포. cand·base 는 시드별 예측 목록.

    블록 = (연도, 지점) 25개(기본) 또는 연도 5개. 같은 블록 뽑기를 모든 시드에 쓰고 시드 평균 Δ 를 낸다.
    블록 합(n, Σo, Σo², SSE)을 미리 구해 r2 = 1 − SSE/(Σo² − (Σo)²/n) 로 계산한다.
    """
    cv, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    years = H.years_of(df)
    sites = df["station_id"].astype(str).to_numpy()
    lab = (
        pd.Series([f"{y}_{s}" for y, s in zip(years, sites, strict=True)])
        if blocks == "year_site"
        else pd.Series(years.astype(str))
    )
    ids, uniq = pd.factorize(lab[cv])
    nb = len(uniq)
    o = obs[cv]
    agg = lambda v: np.bincount(ids, weights=v, minlength=nb)  # noqa: E731
    n_b, s1_b, s2_b = agg(np.ones_like(o)), agg(o), agg(o * o)
    sse_c = [agg((o - np.asarray(p, dtype=float)[cv]) ** 2) for p in cand]
    sse_b = [agg((o - np.asarray(p, dtype=float)[cv]) ** 2) for p in base]
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, nb, size=(n_boot, nb))
    C = np.zeros((n_boot, nb))
    np.add.at(C, (np.repeat(np.arange(n_boot), nb), draw.ravel()), 1.0)
    N, S1, S2 = C @ n_b, C @ s1_b, C @ s2_b
    sst = S2 - S1 * S1 / N
    d = np.mean([(C @ sb - C @ sc) / sst for sc, sb in zip(sse_c, sse_b, strict=True)], axis=0)
    full = float(
        np.mean([(sb.sum() - sc.sum()) / (o.var() * len(o)) for sc, sb in zip(sse_c, sse_b, strict=True)])
    )
    return {
        "blocks": blocks,
        "n_blocks": int(nb),
        "n_boot": int(n_boot),
        "delta": full,
        "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
        "median": float(np.median(d)),
        "p_gt0": float(np.mean(d > 0)),
        "p_ge_adopt": float(np.mean(d >= ADOPT_R2)),
    }


# ================================================================ 7. 재현 점검
def _maxdiff_log(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.log10(np.asarray(a, dtype=float) + 1), np.log10(np.asarray(b, dtype=float) + 1)
    ok = np.isfinite(a) & np.isfinite(b)
    return float(np.max(np.abs(a[ok] - b[ok]))) if ok.any() else float("nan")


def reproduction_checks(ev: Evaluator) -> list[dict]:
    """시드 42 결과가 이전 실험 산출물과 같은지(log10 최대 절대차)."""
    import pickle

    from algaecast.exp import r1_variance_restore as R1

    df = ev.df
    out = []

    def add(name: str, diffs: dict[str, float]) -> None:
        out.append({"점검": name, "log10 최대 절대차": {k: round(v, 12) for k, v in diffs.items()}})

    m = load_members(Combo(), 42)
    _, base = H.load_baseline()
    add(
        "v1 시드42 구성원 ↔ 하네스 기준 OOF",
        {k: _maxdiff_log(m[k], base[k]) for k in ("c1", "c3", "c2", "q10", "q50", "q90")},
    )
    add("v1 시드42 P0 ↔ 기준 ens", {"P0": _maxdiff_log(ev.preds[("v1", "P0", 42)], base["ens"])})
    r_comb, _ = R1.run_variant(df, base, "r_combine")
    rh, _ = R1.run_variant(df, base, "rh_gated_c")
    add("v1 시드42 P1 ↔ R1 r_combine", {"P1": _maxdiff_log(ev.preds[("v1", "P1", 42)], r_comb)})
    add("v1 시드42 P3 ↔ R1 rh_gated_c", {"P3": _maxdiff_log(ev.preds[("v1", "P3", 42)], rh)})
    p5 = H.EXP_DATA / "EXP-005" / "chosen_oof.parquet"
    if cache_path("base", Combo(f2=True), 42).exists() and p5.exists():
        o, mm = pd.read_parquet(p5), load_members(Combo(f2=True), 42)
        add(
            "F2 시드42 ↔ EXP-005 chosen_oof",
            {k: _maxdiff_log(mm[k], o[k]) for k in ("c1", "c3", "c2", "q90")},
        )
    p7 = H.EXP_DATA / "EXP-007" / "cache" / "tp_np_d60_primary.pkl"
    if cache_path("base", Combo(f4=True), 42).exists() and p7.exists():
        with p7.open("rb") as fh:
            got = pickle.load(fh)  # noqa: S301 — 이 저장소 실험(EXP-007)이 만든 로컬 캐시
        mm = load_members(Combo(f4=True), 42)
        add(
            "F4 시드42 ↔ EXP-007 tp_np 지연60 캐시",
            {k: _maxdiff_log(mm[k], got["mem"][k]) for k in ("c1", "c3", "c2", "q90")},
        )
    p8 = H.EXP_DATA / "EXP-008" / "oof_all_noembed_w5.parquet"
    c8 = Combo(t5="all_noembed_w5")
    if cache_path("base", c8, 42).exists() and p8.exists():
        o, mm = pd.read_parquet(p8), load_members(c8, 42)
        add(
            "T5(전국·w5) 시드42 ↔ EXP-008 oof",
            {k: _maxdiff_log(mm[k], o[k]) for k in ("c1", "c3", "c2", "q90")},
        )
    p6 = H.EXP_DATA / "EXP-006" / "chosen_oof.parquet"
    if cache_path("cg", Combo(m3=True), 42).exists() and p6.exists():
        o, mm = pd.read_parquet(p6), load_members(Combo(m3=True), 42)
        add("M3 cg 시드42 ↔ EXP-006 chosen_oof", {"cg": _maxdiff_log(mm["cg"], o["cg"])})
    return out


# ================================================================ 8. 공개: v2 후보
def v2_candidate(
    df: pd.DataFrame,
    seed: int = 42,
    *,
    combo: str | None = None,
    point: str | None = None,
    q_ref: str = "",
) -> dict:
    """최종 후보(V2) 구성의 OOF 구성원과 점예측(2020~2025 행, 나머지 NaN).

    반환: c1·c1_none·c1_log·c3·c2·q10·q50·q90(+M3 이면 cg·cg_micro·cg_rest), ens(P0), pred(최종 점예측),
    그리고 문자열 키 config(구성 키)·point(점예측 축). df 는 harness.load_base() 형식.
    combo·point 로 다른 구성을, q_ref(예: "v1")로 분위를 그 구성의 것으로 고정한 변형(3.9 민감도의 견고성 대안
    ``v2_candidate(df, combo=ROBUST_ALT["combo"], point="P0", q_ref="v1")``)을 만들 수 있다.
    """
    H.guard_no_2026(df)
    c = parse_key(combo or V2["combo"])
    p = point or V2["point"]
    feats = build_features(df) if (c.f2 or c.f4) else None
    mem = combo_members(df, feats, c, seed)
    if q_ref:
        ref = combo_members(df, feats, parse_key(q_ref).base, seed)
        mem.update({k: ref[k] for k in ("q10", "q50", "q90")})
    preds, _ = point_preds(df, mem, c.m3, points=("P0", p))
    out: dict = dict(mem)
    out["ens"] = preds["P0"]
    out["pred"] = preds[p]
    out["config"] = c.key
    out["point"] = p
    return out


# ================================================================ 9. 보고서
def _f(v: object, nd: int = 3, sign: bool = False) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, (int, np.integer)):
        return str(v)
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


def _rng(s: dict, m: str, nd: int = 3) -> str:
    return f"{_f(s[f'{m}_mean'], nd)} [{_f(s[f'{m}_min'], nd)}, {_f(s[f'{m}_max'], nd)}]"


def seed_table(ev: Evaluator, items: list[tuple[str, str]]) -> str:
    head = (
        "| 구성 | 점예측 | CV r2_raw 평균 [최소, 최대] | Δ r2_raw(v1 짝) | CV rmse_log 평균 [최소, 최대] | Δ rmse_log | "
        "리드타임 평균 [최소, 최대] | CV 폴드평균 r2_raw | 2025 r2_raw 평균 | 2025 rmse_log 평균 |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for key, p in items:
        s = ev.summary(key, p)
        lines.append(
            f"| {parse_key(key).label} | {POINT_LABEL[p]} | {_rng(s, 'cv_r2_raw')} | {_f(s['d_cv_r2_raw'], sign=True)} | "
            f"{_rng(s, 'cv_rmse_log')} | {_f(s['d_cv_rmse_log'], sign=True)} | {_rng(s, 'lead_q90', 2)} | "
            f"{_f(s['cvfold_r2_raw_mean'])} | {_f(s['y2025_r2_raw_mean'])} | {_f(s['y2025_rmse_log_mean'])} |"
        )
    return head + "\n".join(lines) + "\n"


def per_seed_table(ev: Evaluator, items: list[tuple[str, str]]) -> str:
    head = "| 구성 | 점예측 | " + " | ".join(f"시드 {s} r2_raw / rmse_log / 리드" for s in SEEDS) + " |\n"
    head += "|---|---|" + "---|" * len(SEEDS) + "\n"
    lines = []
    for key, p in items:
        cells = []
        for s in SEEDS:
            r = ev.row(key, p, s)
            cells.append(f"{_f(r['cv_r2_raw'])} / {_f(r['cv_rmse_log'])} / {r['lead_q90']}")
        lines.append(f"| {parse_key(key).label} | {POINT_LABEL[p]} | " + " | ".join(cells) + " |")
    return head + "\n".join(lines) + "\n"


def step_table(step: dict) -> str:
    head = (
        "| 후보 | 시드평균 CV r2_raw [최소, 최대] | 증가(현재 대비) | 대조군 증가 | 고유 효과 | 고유 효과(rmse_log) | "
        "Δ r2_raw(v1) | Δ rmse_log(v1) | 리드 평균(v1) | 2025 r2_raw | (i) | (ii) | (iii) | 적격 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for r in step["records"]:
        mark = " **(채택)**" if step["chosen"] == r["key"] else ""
        lines.append(
            f"| {r['label']}{mark} | {_f(r['cv_r2_raw'])} [{_f(r['cv_r2_raw_min'])}, {_f(r['cv_r2_raw_max'])}] | "
            f"{_f(r['gain'], sign=True)} | {_f(r.get('ctrl_gain'), sign=True)} | {_f(r.get('unique'), sign=True)} | "
            f"{_f(r.get('unique_rmse'), sign=True)} | {_f(r['d_r2_v1'], sign=True)} | {_f(r['d_rmse_v1'], sign=True)} | "
            f"{_f(r['lead'], 2)} ({_f(r['lead_v1'], 2)}) | {_f(r['y2025_r2_raw'])} | {_f(r['ok_rmse'])} | "
            f"{_f(r['ok_lead'])} | {_f(r['ok_ctrl']) if 'ctrl_key' in r else '해당 없음'} | {_f(r['eligible'])} |"
        )
        for t in r.get("t5_variants", []):
            if t["key"] == r["key"]:
                continue
            lines.append(
                f"| ㄴ(T5 변형 미선택) {t['label']} | {_f(t['cv_r2_raw'])} [{_f(t['cv_r2_raw_min'])}, {_f(t['cv_r2_raw_max'])}] | "
                f"{_f(t['gain'], sign=True)} | – | – | – | {_f(t['d_r2_v1'], sign=True)} | {_f(t['d_rmse_v1'], sign=True)} | "
                f"{_f(t['lead'], 2)} ({_f(t['lead_v1'], 2)}) | {_f(t['y2025_r2_raw'])} | {_f(t['ok_rmse'])} | "
                f"{_f(t['ok_lead'])} | 해당 없음 | {_f(t['eligible'])} |"
            )
    return head + "\n".join(lines) + "\n"


def cumulative_table(ev: Evaluator, path: list[str]) -> str:
    head = (
        "| 단계 | 정보 구성 | P0 log NNLS | P1 원단위 볼록 결합 | P2 C1 단독 | P3 rh_gated_c(참고) | rmse_log P0 / P1 / P2 | "
        "리드 평균 | 2025 r2_raw P0 / P1 / P2 |\n|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for i, key in enumerate(path):
        ss = {p: ev.summary(key, p) for p in POINTS}
        cells = " | ".join(
            f"{_f(ss[p]['cv_r2_raw_mean'])} ({_f(ss[p]['d_cv_r2_raw'], sign=True)})" for p in POINTS
        )
        rm = " / ".join(_f(ss[p]["cv_rmse_log_mean"]) for p in SELECTABLE_POINTS)
        y25 = " / ".join(_f(ss[p]["y2025_r2_raw_mean"]) for p in SELECTABLE_POINTS)
        lines.append(
            f"| {i} | {parse_key(key).label} | {cells} | {rm} | {_f(ss['P0']['lead_q90_mean'], 2)} | {y25} |"
        )
    return head + "\n".join(lines) + "\n"


def year_table(ev: Evaluator, items: list[tuple[str, str]]) -> str:
    head = (
        "| 구성 | 점예측 | "
        + " | ".join(str(y) for y in H.CV_YEARS)
        + " | 최저 연도 | CV 폴드 평균 | CV 통합 |\n"
    )
    head += "|---|---|" + "---|" * (len(H.CV_YEARS) + 3) + "\n"
    lines = []
    for key, p in items:
        s = ev.summary(key, p)
        ys = [s[f"cv{y}_r2_raw_mean"] for y in H.CV_YEARS]
        lines.append(
            f"| {parse_key(key).label} | {POINT_LABEL[p]} | "
            + " | ".join(_f(v) for v in ys)
            + f" | {_f(min(ys))} | {_f(s['cvfold_r2_raw_mean'])} | {_f(s['cv_r2_raw_mean'])} |"
        )
    return head + "\n".join(lines) + "\n"


def md_rows(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(h for _, h in cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = []
    for r in rows:
        cells = []
        for k, _ in cols:
            v = r.get(k)
            cells.append(
                _f(v, sign=k.startswith("d_")) if isinstance(v, (float, bool, np.floating)) else str(v)
            )
        body.append("| " + " | ".join(cells) + " |")
    return head + "\n".join(body) + "\n"


DEP_TESTS: tuple[str, ...] = (
    "tests/test_exp_harness.py",
    "tests/test_exp_r1_variance_restore.py",
    "tests/test_exp_r2_upstream.py",
    "tests/test_exp_r3_genus.py",
    "tests/test_exp_r4_nutrients.py",
    "tests/test_exp_r5_national.py",
)


def _pytest(paths: Iterable[str]) -> dict:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [ln for ln in p.stdout.strip().splitlines() if ln.strip()][-1:] or [""]
    return {"returncode": p.returncode, "summary": tail[0], "passed": p.returncode == 0}


def run_tests() -> dict:
    """자기 테스트(가벼움)와 재사용한 실험 모듈의 누수·가드 테스트를 하위 프로세스로 돌려 결과를 기록한다."""
    own = _pytest(["tests/test_exp_r_combo.py"])
    deps = _pytest(DEP_TESTS)
    return {**own, "deps": deps}


def protected_check() -> dict:
    cmd = [sys.executable, "scripts/exp_check_protected.py"]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    first = (p.stdout.strip().splitlines() or [""])[0]
    m = re.search(r"변경 (\d+)개", first)
    return {"returncode": p.returncode, "summary": first, "changed": int(m.group(1)) if m else -1}


# ================================================================ 10. 실행
def elapsed_hours() -> float:
    t0 = datetime.strptime(TASK_START, "%Y-%m-%d %H:%M:%S")
    return (datetime.now() - t0).total_seconds() / 3600


def analyze(ev: Evaluator, sel: dict) -> dict:
    """전진 선택 결과 위에서 점예측 축 선택·v2 판정·축 분해·블록 부트스트랩."""
    df = ev.df
    final = sel["final"]
    point, point_recs = choose_point(ev, final)
    ev.evaluate(Combo())
    v2 = v2_decision(ev, sel["path"])
    cand_key, cand_pt = v2["key"], v2["point"]
    lead_v1 = ev.summary("v1")["lead_q90_mean"]
    decomp = []
    for key, p, name in (
        (final, "P0", "정보 축만(최종 정보 구성 · P0)"),
        ("v1", point, f"점예측 축만(v1 · {point})"),
        (final, point, f"둘 다(최종 정보 구성 · {point})"),
    ):
        s = ev.summary(key, p)
        decomp.append(
            {
                "이름": name,
                "key": key,
                "point": p,
                **adoption_mean(s, lead_v1),
                "cv_r2_raw": s["cv_r2_raw_mean"],
            }
        )
    decomp_inter = decomp[2]["d_cv_r2_raw"] - decomp[0]["d_cv_r2_raw"] - decomp[1]["d_cv_r2_raw"]
    boots = {}
    targets = {
        "candidate": (cand_key, cand_pt),
        "info_only": (final, "P0"),
        "point_only": ("v1", point),
        "final_selected": (final, point),
    }
    for name, (key, p) in targets.items():
        cand = [ev.preds[(key, p, s)] for s in SEEDS]
        base = [ev.preds[("v1", "P0", s)] for s in SEEDS]
        boots[name] = {
            "key": key,
            "point": p,
            "year_site": block_bootstrap(df, cand, base, blocks="year_site"),
            "year": block_bootstrap(df, cand, base, blocks="year"),
        }
    return {
        "sel": sel,
        "final": final,
        "point": point,
        "point_recs": point_recs,
        "v2": v2,
        "decomp": decomp,
        "decomp_inter": decomp_inter,
        "boots": boots,
    }


def diag_2025(ev: Evaluator, items: list[tuple[str, str]]) -> list[dict]:
    """2025 확인 진단(선택에 쓰지 않음): SSE, 상위 3행 비중, 과대예측(예측 ≥ 10k 이고 관측+1 의 3배 초과) 행 수·SSE 비중.

    예측은 시드 평균(원단위). 관측 원값은 내보내지 않는다.
    """
    df = ev.df
    obs = df["target_cells"].to_numpy(dtype=float)
    m = H.years_of(df) == H.FINAL_YEAR
    o = obs[m]
    sst = float(np.sum((o - o.mean()) ** 2))
    out = []
    for key, p in items:
        pr = np.mean([ev.preds[(key, p, s)] for s in SEEDS], axis=0)[m]
        e = (o - pr) ** 2
        over = (pr >= H.T10K) & (pr > 3 * (o + 1))
        under = (o >= H.T10K) & (o > 3 * (pr + 1))
        out.append(
            {
                "key": key,
                "point": p,
                "label": _label(key, p),
                "r2_seedmean_pred": float(1 - e.sum() / sst),
                "sse_ratio_v1": float("nan"),
                "top3_share": float(np.sort(e)[::-1][:3].sum() / e.sum()),
                "n_over": int(over.sum()),
                "over_share": float(e[over].sum() / e.sum()),
                "n_under": int(under.sum()),
                "under_share": float(e[under].sum() / e.sum()),
                "sse": float(e.sum()),
            }
        )
    base = next((r["sse"] for r in out if r["key"] == "v1" and r["point"] == "P0"), None)
    for r in out:
        r["sse_ratio_v1"] = r["sse"] / base if base else float("nan")
    return out


def run_all(workers: int, budget: H.Budget) -> dict:
    df = H.load_base()
    H.guard_no_2026(df)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    feats = build_features(df)
    keyed = pd.concat([df[["station_id", "base_date"]].astype({"station_id": str}), feats], axis=1)
    keyed.to_parquet(FEATURES_PATH, index=False)
    ev = Evaluator(df)
    main_res = analyze(ev, forward_select(ev, workers, budget))
    repro = reproduction_checks(ev)
    # 민감도(진단, 선택에 쓰지 않음): 분위 모델을 v1 그대로 두고 회귀 구성원만 바꾸는 프로토콜(R2 보고서 제안 (b))
    ev_q = Evaluator(df, q_ref="v1")
    alt = analyze(ev_q, forward_select(ev_q, workers, budget))
    alt["ev"] = ev_q
    items = _uniq(
        [("v1", "P0"), ("v1", "P1"), ("v1", "P2")]
        + [(k, "P0") for k in main_res["sel"]["path"][1:]]
        + [(main_res["final"], p) for p in ("P1", "P2")]
        + [(main_res["v2"]["key"], main_res["v2"]["point"])]
    )
    d25 = diag_2025(ev, items)
    return {"df": df, "ev": ev, **main_res, "repro": repro, "alt": alt, "diag2025": d25}


def save_outputs(ctx: dict) -> None:
    """chosen_oof(시드 42, pred=최종 점예측)·점예측 전체(시드별)."""
    df, ev = ctx["df"], ctx["ev"]
    key, p = ctx["v2"]["key"], ctx["v2"]["point"]
    combo = parse_key(key)
    mem = load_members(combo, 42)
    preds = {k: mem[k] for k in mem}
    preds["ens"] = ev.preds[(key, "P0", 42)]
    preds["pred"] = ev.preds[(key, p, 42)]
    H.save_oof(df, preds, OUT_DATA / "chosen_oof.parquet")
    allp = {f"{k}|{pt}|s{s}": v for (k, pt, s), v in ev.preds.items()}
    H.save_oof(df, allp, OUT_DATA / "points_oof.parquet")
    alt = ctx["alt"]
    ka = alt["final"]
    ma = load_members(parse_key(ka), 42)
    ma.update({k: load_members(Combo(), 42)[k] for k in ("q10", "q50", "q90")})
    ma["pred"] = alt["ev"].preds[(ka, "P0", 42)]
    H.save_oof(df, ma, OUT_DATA / "robust_alt_oof.parquet")


def public_api_check(ctx: dict) -> list[dict]:
    """공개 함수 v2_candidate 를 캐시 없이 새로 학습해 저장 OOF(시드 42)와 대조한다."""
    df = ctx["df"]
    out = []
    o = pd.read_parquet(OUT_DATA / "chosen_oof.parquet")
    got = v2_candidate(df)
    out.append(
        {
            "점검": f"v2_candidate(df) ↔ chosen_oof ({got['config']} · {got['point']})",
            "log10 최대 절대차": {
                k: _maxdiff_log(got[k], o[k]) for k in ("c1", "c3", "c2", "q90", "ens", "pred")
            },
        }
    )
    a = pd.read_parquet(OUT_DATA / "robust_alt_oof.parquet")
    got = v2_candidate(df, combo=ROBUST_ALT["combo"], point=ROBUST_ALT["point"], q_ref=ROBUST_ALT["q_ref"])
    keys = [k for k in ("c1", "c3", "c2", "cg", "q90", "pred") if k in a.columns]
    out.append(
        {
            "점검": f"v2_candidate(df, combo={ROBUST_ALT['combo']}, point=P0, q_ref=v1) ↔ robust_alt_oof",
            "log10 최대 절대차": {k: _maxdiff_log(got[k], a[k]) for k in keys},
        }
    )
    return out


def _alt_json(alt: dict) -> dict:
    """민감도(분위 v1 고정) 결과 요약 — 선택에 쓰지 않음."""
    ev = alt["ev"]
    keys = list(
        dict.fromkeys(alt["sel"]["path"])
    )  # 용량을 줄이려고 경로 구성만(후보·대조군 값은 selection 기록에 있음)
    return {
        "note": "진단: 분위 q10·q50·q90 를 v1(같은 시드) 것으로 고정하고 회귀 구성원만 바꾼 프로토콜. 선택에 쓰지 않는다.",
        "robust_alt": ROBUST_ALT,
        "robust_alt_seed_mean": {m: ev.summary(alt["final"], "P0")[f"{m}_mean"] for m in SUMMARY_METRICS},
        "selection": alt["sel"],
        "point_axis": {"chosen": alt["point"], "records": alt["point_recs"]},
        "v2_like": {
            "found": alt["v2"]["found"],
            "key": alt["v2"]["key"],
            "point": alt["v2"]["point"],
            "table": alt["v2"]["table"],
        },
        "decomposition": {"rows": alt["decomp"], "interaction_d_r2": alt["decomp_inter"]},
        "bootstrap": alt["boots"],
        "summaries": [ev.summary(k, p) for k in keys for p in POINTS],
    }


def metrics_json(ctx: dict, tests: dict, prot: dict, status: str) -> dict:
    ev = ctx["ev"]
    keys = sorted({k for (k, _p, _s) in ev.rows})
    summaries = [ev.summary(k, p) for k in keys for p in POINTS]
    cand = ev.summary(ctx["v2"]["key"], ctx["v2"]["point"])
    return {
        "exp": EXP_ID,
        "status": status,
        "task_start": TASK_START,
        "elapsed_hours": round(elapsed_hours(), 3),
        "budget_hours": BUDGET_HOURS,
        "seeds": list(SEEDS),
        "protocol": {
            "min_gain": MIN_GAIN,
            "rmse_slack": RMSE_SLACK,
            "adopt_r2": ADOPT_R2,
            "t5_variants": list(T5_VARIANTS),
            "control": "표준정규 난수 열(같은 열 수, 생성기 시드 = (20261022, 학습 시드, 열 수))",
            "bootstrap": {"n_boot": N_BOOT, "seed": BOOT_SEED},
        },
        "selection": ctx["sel"],
        "point_axis": {"chosen": ctx["point"], "records": ctx["point_recs"]},
        "v2": {
            "found": ctx["v2"]["found"],
            "key": ctx["v2"]["key"],
            "point": ctx["v2"]["point"],
            "label": cand["label"],
            "table": ctx["v2"]["table"],
            "seed_mean": {m: cand[f"{m}_mean"] for m in SUMMARY_METRICS},
            "seed42": ev.row(ctx["v2"]["key"], ctx["v2"]["point"], 42),
        },
        "decomposition": {"rows": ctx["decomp"], "interaction_d_r2": ctx["decomp_inter"]},
        "bootstrap": ctx["boots"],
        "diag_2025": ctx["diag2025"],
        "sensitivity_fixed_quantiles": _alt_json(ctx["alt"]),
        "reproduction": ctx["repro"],
        "public_api_check": ctx.get("api_check", []),
        "tests": tests,
        "protected": prot,
        "summaries": summaries,
        "rows": [ev.rows[k] for k in sorted(ev.rows)],
        "weights": {f"{k}|s{s}": w for (k, s), w in ev.weights.items()},
        "operational_notes": OPERATIONAL_NOTES,
    }


def _uniq(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return list(dict.fromkeys(items))


def _label(key: str, point: str) -> str:
    return f"{parse_key(key).label} · {POINT_LABEL[point]}"


def boot_table(boots: dict) -> str:
    names = {
        "candidate": "v2 후보(또는 최근접) − v1",
        "final_selected": "최종 선택(정보 + 점예측) − v1",
        "info_only": "정보 축만(최종 정보 구성 · P0) − v1",
        "point_only": "점예측 축만(v1 · 선택 점예측) − v1",
    }
    head = (
        "| 비교 | 구성 | 블록 | 블록 수 | 시드평균 Δ CV r2_raw | 95% 구간 | 중앙값 | P(Δ>0) | P(Δ≥+0.10) |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for k, b in boots.items():
        for bl in ("year_site", "year"):
            r = b[bl]
            lines.append(
                f"| {names.get(k, k)} | {_label(b['key'], b['point'])} | {'(연도, 지점)' if bl == 'year_site' else '연도'} | "
                f"{r['n_blocks']} | {_f(r['delta'], sign=True)} | [{_f(r['ci95'][0], sign=True)}, {_f(r['ci95'][1], sign=True)}] | "
                f"{_f(r['median'], sign=True)} | {_f(r['p_gt0'], 2)} | {_f(r['p_ge_adopt'], 2)} |"
            )
    return head + "\n".join(lines) + "\n"


def _discussion(ctx: dict) -> list[str]:
    """해석(모든 수치는 ctx 에서 읽는다)."""
    ev = ctx["ev"]
    out: list[str] = []
    sv1 = ev.summary("v1")
    v1s = sv1["cv_r2_raw_seeds"]
    out.append(
        f"- **v1 시드 흔들림.** 같은 v1 설정에서 시드 42·7·2026 의 CV r2_raw 는 {', '.join(_f(v) for v in v1s)}"
        f"(평균 {_f(sv1['cv_r2_raw_mean'])}), rmse_log {', '.join(_f(v) for v in sv1['cv_rmse_log_seeds'])}, "
        f"리드타임 {', '.join(str(int(v)) for v in sv1['lead_q90_seeds'])}/20 이다. 단일 시드 비교의 잡음 폭이 이 정도이고, "
        f"리드타임 기준선도 시드 평균 {_f(sv1['lead_q90_mean'], 2)} 이다(시드 42 만 보면 18)."
    )
    steps = ctx["sel"]["steps"]

    def rec(step: int, element: str) -> dict | None:
        for st in steps:
            if st["step"] == step:
                for r in st["records"]:
                    if r["element"] == element:
                        return r
        return None

    def seeds_txt(key: str, m: str = "lead_q90") -> str:
        return "/".join(str(int(v)) for v in ev.summary(key)[f"{m}_seeds"])

    r_f2, r_f4, r_t5, r_m3 = (rec(1, e) for e in ELEMENTS)
    if r_f2 and r_f4 and r_t5 and r_m3:
        diag = ctx["sel"]["diag"][0] if ctx["sel"]["diag"] else None
        t5v = {t["key"]: t for t in r_t5.get("t5_variants", [])}
        t5txt = "; ".join(
            f"{T5_SHORT[parse_key(k).t5]} 증가 {_f(t['gain'], sign=True)}·Δrmse {_f(t['d_rmse_v1'], sign=True)}·리드 {_f(t['lead'], 2)}"
            + ("(적격)" if t["eligible"] else "(부적격)")
            for k, t in t5v.items()
        )
        out.append(
            f"- **단계 1.** 증가가 가장 큰 요소는 F2(상류 피처, {_f(r_f2['gain'], sign=True)})였고 대조군(난수 5열 {_f(r_f2['ctrl_gain'], sign=True)})을 "
            f"빼도 고유 효과 {_f(r_f2['unique'], sign=True)} 로 분명하다"
            + (
                f"(결측 위치까지 F2 와 같게 만든 난수 5열도 {_f(diag['gain'], sign=True)} 라, F2 의 효과는 '해평·회남 결측 = 지점 표시' 때문이 아니다)"
                if diag
                else ""
            )
            + f". 그러나 분위를 같은 피처로 다시 학습하면 q90 경보 포착이 시드별 {seeds_txt(r_f2['key'])}(평균 {_f(r_f2['lead'], 2)})로 줄어 "
            f"조건 (ii)(v1 {_f(r_f2['lead_v1'], 2)})에 걸렸다(EXP-005 에서 본 현상과 같다). F4(영양염, 지연 60일)는 증가 {_f(r_f4['gain'], sign=True)} 가 "
            f"같은 열 수 난수 대조군({_f(r_f4['ctrl_gain'], sign=True)})보다 작아 고유 효과 {_f(r_f4['unique'], sign=True)} — EXP-007 의 결론(난수와 구분 안 됨)이 "
            f"시드 평균으로도 재현됐다. T5 는 {t5txt}. 그래서 적격 후보 중 증가 최대인 **{r_t5['label']}**(증가 {_f(r_t5['gain'], sign=True)})가 "
            f"M3(증가 {_f(r_m3['gain'], sign=True)}, 적격)를 앞서 채택됐다."
        )
    r2_f2, r2_f4, r2_m3 = rec(2, "F2"), rec(2, "F4"), rec(2, "M3")
    if r2_f2 and r2_m3:
        out.append(
            f"- **단계 2(T5 위).** F2 의 증가가 {_f(r_f2['gain'] if r_f2 else float('nan'), sign=True)} → {_f(r2_f2['gain'], sign=True)} 로 크게 줄었다"
            f"(고유 효과 {_f(r2_f2.get('unique'), sign=True)}, 리드 {_f(r2_f2['lead'], 2)} 로 여전히 (ii) 불만족). 상류 지점 정보와 전국 통합 학습이 같은 것"
            "(같은 시기 유역 전체의 대발생 상태)을 상당 부분 겹쳐 담는다는 뜻이다. "
            + (f"F4 는 {_f(r2_f4['gain'], sign=True)}, " if r2_f4 else "")
            + f"M3 는 {_f(r2_m3['gain'], sign=True)}(적격)로 +{MIN_GAIN:.2f} 에 못 미쳐 정보 축 선택이 멈췄다."
        )
    final, pt = ctx["final"], ctx["point"]
    sF = {p: ev.summary(final, p) for p in POINTS}
    out.append(
        f"- **점예측 축(최종 정보 구성 {parse_key(final).label} 위).** 시드 평균 CV r2_raw P0 {_f(sF['P0']['cv_r2_raw_mean'])}, P1 {_f(sF['P1']['cv_r2_raw_mean'])}, "
        f"P2 {_f(sF['P2']['cv_r2_raw_mean'])}, P3(참고) {_f(sF['P3']['cv_r2_raw_mean'])}. 규칙대로 **{POINT_LABEL[pt]}** 를 골랐다"
        f"(rmse_log Δ {_f(sF[pt]['d_cv_rmse_log'], sign=True)} 로 (i) 만족). v1 위에서도 P2 는 {_f(ev.summary('v1', 'P2')['d_cv_r2_raw'], sign=True)} 를 주지만 "
        f"rmse_log {_f(ev.summary('v1', 'P2')['d_cv_rmse_log'], sign=True)} 로 (i) 를 넘는다. 최종 구성의 C1 은 v1 의 C1 보다 rmse_log 가 낮아"
        f"({_f(sF['P2']['cv_rmse_log_mean'])} vs {_f(ev.summary('v1', 'P2')['cv_rmse_log_mean'])}) P2 가 (i) 안에 들어온 것이다."
    )
    d = ctx["decomp"]
    out.append(
        f"- **이득의 출처(3.5).** 최종 Δr2_raw {_f(d[2]['d_cv_r2_raw'], sign=True)} 중 정보 축만으로 {_f(d[0]['d_cv_r2_raw'], sign=True)}, "
        f"점예측 축만으로 {_f(d[1]['d_cv_r2_raw'], sign=True)}(상호작용 {_f(ctx['decomp_inter'], sign=True)}). 공통 발견 (2)대로 이득의 큰 몫(약 "
        f"{_f(100 * d[1]['d_cv_r2_raw'] / d[2]['d_cv_r2_raw'], 0)}%)이 새 정보가 아니라 '로그 공간 NNLS → 원단위에 맞는 점예측' 전환에서 온다."
    )
    ck, cp = ctx["v2"]["key"], ctx["v2"]["point"]
    sc = ev.summary(ck, cp)
    ys = [sc[f"cv{y}_r2_raw_mean"] for y in H.CV_YEARS]
    yv = [sv1[f"cv{y}_r2_raw_mean"] for y in H.CV_YEARS]
    worse = [str(y) for y, a, b in zip(H.CV_YEARS, ys, yv, strict=True) if a < b - 0.005]
    bc = ctx["boots"]["candidate"]
    out.append(
        f"- **v2 후보의 견고성(CV 안).** 연도별로 보면 개선이 극단값이 많은 해에 몰린다(3.6: 2022 {_f(yv[2])} → {_f(ys[2])}, 2024 {_f(yv[4])} → {_f(ys[4])}). "
        f"v1 보다 나빠진 CV 연도: {', '.join(worse) if worse else '없음'}. CV 폴드 평균 r2_raw 는 {_f(sv1['cvfold_r2_raw_mean'])} → {_f(sc['cvfold_r2_raw_mean'])}"
        f"(Δ {_f(sc['d_cvfold_r2_raw'], sign=True)})로 통합 지표의 Δ {_f(sc['d_cv_r2_raw'], sign=True)} 보다 훨씬 작다. "
        f"(연도·지점) 블록 부트스트랩 95% 구간 [{_f(bc['year_site']['ci95'][0], sign=True)}, {_f(bc['year_site']['ci95'][1], sign=True)}] 은 0 을 넘지만 "
        f"P(Δ ≥ +0.10) = {_f(bc['year_site']['p_ge_adopt'], 2)}, 연도 블록(5개)으로는 [{_f(bc['year']['ci95'][0], sign=True)}, {_f(bc['year']['ci95'][1], sign=True)}] 로 0 을 포함한다."
    )
    dd = {(r["key"], r["point"]): r for r in ctx["diag2025"]}
    dc, d1 = dd.get((ck, cp)), dd.get(("v1", "P0"))
    p12 = [
        ev.summary(k, p)["y2025_r2_raw_mean"]
        for k in dict.fromkeys(["v1", *ctx["sel"]["path"][1:], final])
        for p in ("P1", "P2")
    ]
    if dc and d1:
        out.append(
            f"- **2025 확인(선택에 쓰지 않음).** v2 후보의 2025 r2_raw 는 시드 평균 {_f(sc['y2025_r2_raw_mean'])}(v1 {_f(sv1['y2025_r2_raw_mean'])}), "
            f"rmse_log {_f(sc['y2025_rmse_log_mean'])}(v1 {_f(sv1['y2025_rmse_log_mean'])})로 CV 이득이 2025 에 재현되지 않고 오히려 나빠진다. "
            f"2025 SSE 가 v1 의 {_f(dc['sse_ratio_v1'], 2)}배이고, 예측 ≥ 10k 인데 관측의 3배를 넘는 과대예측 {dc['n_over']}행이 SSE 의 {_f(100 * dc['over_share'], 0)}% 를 차지한다"
            f"(v1 은 {d1['n_over']}행·{_f(100 * d1['over_share'], 0)}%). P1·P2 를 쓴 모든 구성의 2025 r2_raw 가 {_f(min(p12))}~{_f(max(p12))} 로 P0 보다 낮아, "
            "점예측 축의 CV 이득이 2025 로 옮겨 가지 않는 것은 EXP-004·006 에 이어 이번에도 체계적으로 나타났다."
        )
    alt = ctx["alt"]
    ea = alt["ev"]
    path_a = alt["sel"]["path"]
    fa = alt["final"]
    sa0 = ea.summary(fa, "P0")
    ba = alt["boots"]["info_only"]
    va = alt["v2"]
    sva = ea.summary(va["key"], va["point"])
    ysa = [sa0[f"cv{y}_r2_raw_mean"] for y in H.CV_YEARS]
    worse_a = [str(y) for y, a, b in zip(H.CV_YEARS, ysa, yv, strict=True) if a < b - 0.005]
    out.append(
        f"- **민감도: 분위 v1 고정(3.9).** 리드타임 조건이 사라지면 경로가 {' → '.join(parse_key(k).label for k in path_a)} 로 바뀐다. "
        f"이 경로의 정보 축만(P0) 구성 {parse_key(fa).label} 은 시드 평균 CV r2_raw {_f(sa0['cv_r2_raw_mean'])}(Δ {_f(sa0['d_cv_r2_raw'], sign=True)}), "
        f"rmse_log Δ {_f(sa0['d_cv_rmse_log'], sign=True)}, CV 폴드 평균 {_f(sa0['cvfold_r2_raw_mean'])}(Δ {_f(sa0['d_cvfold_r2_raw'], sign=True)}), "
        f"v1 보다 나빠진 CV 연도 {', '.join(worse_a) if worse_a else '없음'}, 연도 블록 부트스트랩 [{_f(ba['year']['ci95'][0], sign=True)}, {_f(ba['year']['ci95'][1], sign=True)}], "
        f"2025 확인 {_f(sa0['y2025_r2_raw_mean'])} / rmse_log {_f(sa0['y2025_rmse_log_mean'])} 로, 점예측 축을 쓰지 않고도 "
        f"{'채택 기준을 넘고' if sa0['d_cv_r2_raw'] >= ADOPT_R2 and sa0['d_cv_rmse_log'] <= RMSE_SLACK else '기준에 근접하고'} CV 연도 간·2025 에서 가장 고르게 버틴다. "
        f"같은 최대 CV 규칙을 적용하면 이 프로토콜에서도 {_label(va['key'], va['point'])}(CV {_f(sva['cv_r2_raw_mean'])}, 2025 {_f(sva['y2025_r2_raw_mean'])})가 뽑힌다 — "
        "'CV r2_raw 최대' 규칙 자체가 2025 로 옮겨 가지 않는 점예측 축을 고르는 쪽으로 기운다."
    )
    out.append(
        f"- **판단 재료(사용자 결정용).** 규칙상 v2 후보는 {_label(ck, cp)} 이다(채택 기준 통과). 다만 위 견고성·2025 확인을 보면 이득의 대부분이 점예측 축과 "
        f"극단값 많은 해(2022·2024)에서 나온다. 견고성을 우선하면 정보 축만 쓰는 {parse_key(fa).label} · P0(분위 v1 유지, 이 프로토콜 밖 진단)가 대안이다. "
        "어느 쪽이든 v2 채택·재동결은 사용자가 정한다(EXP-PLAN)."
    )
    return out


def _alt_section(ctx: dict) -> list[str]:
    """3.9 민감도: 분위(q10·q50·q90) v1 고정 프로토콜 — 선택에 쓰지 않는 진단."""
    alt = ctx["alt"]
    ev = alt["ev"]
    sel = alt["sel"]
    v2 = alt["v2"]
    L = ["\n### 3.9 민감도(진단, 선택에 쓰지 않음): 분위 모델을 v1 그대로 두는 프로토콜\n"]
    L.append(
        "R2(EXP-005) 보고서가 종합 단계 선택지로 남긴 (b) 방식이다. 회귀 구성원(C1·C3·C2·cg)만 새 구성으로 학습하고 "
        "분위 q10·q50·q90 는 같은 시드의 v1 분위를 그대로 쓴다. 그래서 리드타임(q90≥10k)은 모든 구성에서 v1 과 같고 조건 (ii) 는 늘 만족한다. "
        "나머지 규칙(증가 +0.01, (i) rmse_log, (iii) 대조군, T5 변형 선택, 점예측 축 선택, 채택 기준)은 본 프로토콜과 같다. "
        "이 실험의 v2 후보는 본 프로토콜(3.4) 결과이고, 이 절은 사용자 판단용 참고다.\n"
    )
    for st in sel["steps"]:
        L.append(f"**단계 {st['step']}(분위 고정)** — 현재 구성: {parse_key(st['current']).label}\n")
        if st["records"]:
            L.append(step_table(st))
        L.append(f"\n판정: {st['reason']}\n")
    L.append("\n**누적 표(분위 고정)**\n")
    L.append(cumulative_table(ev, sel["path"]))
    L.append(f"\n점예측 축 선택(분위 고정): **{POINT_LABEL[alt['point']]}**\n")
    L.append(
        md_rows(
            v2["table"],
            [
                ("label", "구성"),
                ("point", "점예측"),
                ("cv_r2_raw", "CV r2_raw 평균"),
                ("d_cv_r2_raw", "Δ r2_raw"),
                ("d_cv_rmse_log", "Δ rmse_log"),
                ("lead", "리드 평균"),
                ("pass", "채택 기준"),
            ],
        )
    )
    s = ev.summary(v2["key"], v2["point"])
    b = alt["boots"]["candidate"]
    L.append(
        f"\n- 분위 고정 프로토콜의 {'후보' if v2['found'] else '최근접 구성'}: **{_label(v2['key'], v2['point'])}** — 시드 평균 CV r2_raw "
        f"{_f(s['cv_r2_raw_mean'])}(Δ {_f(s['d_cv_r2_raw'], sign=True)}), rmse_log Δ {_f(s['d_cv_rmse_log'], sign=True)}, "
        f"CV 폴드 평균 r2_raw {_f(s['cvfold_r2_raw_mean'])}, 2025 r2_raw {_f(s['y2025_r2_raw_mean'])} / rmse_log {_f(s['y2025_rmse_log_mean'])}. "
        f"(연도·지점) 블록 부트스트랩 Δ 95% [{_f(b['year_site']['ci95'][0], sign=True)}, {_f(b['year_site']['ci95'][1], sign=True)}], "
        f"연도 블록 [{_f(b['year']['ci95'][0], sign=True)}, {_f(b['year']['ci95'][1], sign=True)}].\n"
    )
    L.append("\n연도별 CV r2_raw(분위 고정 경로, 시드 평균)\n")
    L.append(
        year_table(
            ev, _uniq([("v1", "P0")] + [(k, "P0") for k in sel["path"][1:]] + [(v2["key"], v2["point"])])
        )
    )
    return L


def render(ctx: dict, tests: dict, prot: dict, status: str) -> str:
    """README.md(EXP-PLAN 7절 형식). 모든 수치는 ctx 에서 읽는다."""
    ev, sel = ctx["ev"], ctx["sel"]
    path, final, pt = sel["path"], ctx["final"], ctx["point"]
    v2 = ctx["v2"]
    ck, cp = v2["key"], v2["point"]
    sv1 = ev.summary("v1")
    sc = ev.summary(ck, cp)
    lead_v1 = sv1["lead_q90_mean"]
    adop = adoption_mean(sc, lead_v1)
    bc = ctx["boots"]["candidate"]["year_site"]
    L: list[str] = []
    L.append("# EXP-011 — 종합: 구성 요소 누적 결합(전진 선택, 시드 3개 평균) → v2 후보\n")
    L.append(
        f"상태: **{status}** · 착수 {TASK_START} KST · 보고서 작성 {datetime.now():%Y-%m-%d %H:%M} · 소요 {elapsed_hours():.2f}시간 / 상한 {BUDGET_HOURS:.0f}시간  \n"
        "코드 `src/algaecast/exp/r_combo.py`(실행 `python -m algaecast.exp.r_combo`) · 테스트 `tests/test_exp_r_combo.py` · "
        "행 단위 산출 `data/processed/exp/EXP-011/`(git 제외)\n"
    )
    verdict = "**채택 기준 통과**" if adop["pass"] else "**채택 기준 미달**"
    head = "v2 후보" if v2["found"] else "v2 후보 없음 — 가장 가까운 구성"
    L.append(
        f"**결론 한 줄**: {head}: **{_label(ck, cp)}** — 시드 평균 CV r2_raw {_f(sc['cv_r2_raw_mean'])}"
        f"(v1 {_f(sv1['cv_r2_raw_mean'])}, 짝 Δ {_f(adop['d_cv_r2_raw'], sign=True)}), rmse_log {_f(sc['cv_rmse_log_mean'])}"
        f"(Δ {_f(adop['d_cv_rmse_log'], sign=True)}), 리드타임 {_f(adop['lead'], 2)}/20(v1 {_f(lead_v1, 2)}) → {verdict}. "
        f"(연도·지점) 블록 부트스트랩 Δ CV r2_raw 95% 구간 [{_f(bc['ci95'][0], sign=True)}, {_f(bc['ci95'][1], sign=True)}]. "
        f"2025 확인(선택에 쓰지 않음) r2_raw {_f(sc['y2025_r2_raw_mean'])}(v1 {_f(sv1['y2025_r2_raw_mean'])}), "
        f"rmse_log {_f(sc['y2025_rmse_log_mean'])}(v1 {_f(sv1['y2025_rmse_log_mean'])}).\n"
    )
    alt = ctx["alt"]
    sa0 = alt["ev"].summary(alt["final"], "P0")
    yb = ctx["boots"]["candidate"]["year"]["ci95"]
    ph_y = (
        "연도 블록 부트스트랩 구간은 0 을 포함하며" if yb[0] <= 0 else "연도 블록 부트스트랩 구간도 0 을 넘고"
    )
    ph_25 = (
        "2025 확인에서 v1 보다 나쁘다"
        if sc["y2025_r2_raw_mean"] < sv1["y2025_r2_raw_mean"]
        else "2025 확인에서도 v1 이상이다"
    )
    L.append(
        f"**주의**: 이득의 약 {_f(100 * ctx['decomp'][1]['d_cv_r2_raw'] / max(ctx['decomp'][2]['d_cv_r2_raw'], 1e-9), 0)}% 는 점예측 축({POINT_LABEL[ctx['point']]})에서 오고, "
        f"CV 폴드 평균 Δ 는 {_f(sc['d_cvfold_r2_raw'], sign=True)}, {ph_y}, {ph_25}. "
        f"견고성 대안(진단, 분위 v1 유지): **{parse_key(alt['final']).label} · P0** — CV r2_raw {_f(sa0['cv_r2_raw_mean'])}(Δ {_f(sa0['d_cv_r2_raw'], sign=True)}), "
        f"rmse_log Δ {_f(sa0['d_cv_rmse_log'], sign=True)}, 폴드 평균 Δ {_f(sa0['d_cvfold_r2_raw'], sign=True)}, 2025 r2_raw {_f(sa0['y2025_r2_raw_mean'])}(3.9). "
        "v2 채택은 사용자가 정한다.\n"
    )
    # ---------------------------------------------------------------- 1
    L.append("## 1. 목적·설정\n")
    L.append(
        "- 목적: R1~R7(EXP-004~010)에서 효과가 보인 구성 요소를 v1 위에 하나씩 누적해, 원단위 R²·NSE 를 채택 기준"
        "(CV r2_raw +0.10, rmse_log 악화 0.01 이내, 리드타임 감소 없음)까지 올리는 v2 후보가 있는지 CV 로만 고른다.\n"
        "- 데이터: `harness.load_base()`(v1 학습·검증 2,566행, base_date ≤ 2025-12-31), v1 피처 30개(`harness.base_columns()`), "
        "하이퍼파라미터 v1 그대로(`harness.v1_specs()`). 새 원자료 수집 없음(R2·R3·R4·R5 가 받아 둔 원자료와 공개 API 를 재사용).\n"
        "- R6(자동측정망, 시드 평균 −0.018)·R7(희소 가중, +0.003)은 각 실험의 제외 권고대로 후보에 넣지 않았다.\n"
    )
    L.append("### 1.1 구성 요소(정보 축)\n")
    L.append(
        "| 요소 | 내용 | 새 열 | 재사용 API | 학습 |\n|---|---|---|---|---|\n"
        f"| F2 | R2 상류 지점 특징, lag 0·1단계·all4_diff | {', '.join(f'`{c}`' for c in f2_cols())} | `r2_upstream.build_features(df)` | 회귀·분위 재학습 |\n"
        f"| F4 | R4 영양염 tp_np, **공개 지연 60일(OPERATIONAL)** | {', '.join(f'`{c}`' for c in f4_cols())} | `r4_nutrients.build_features(df, cfg=OPERATIONAL)` | 회귀·분위 재학습 |\n"
        f"| T5 | R5 전국 82지점 통합 학습, 변형 {', '.join(f'`{v}`' for v in T5_VARIANTS)} 중 CV 로 | (`hydro_fac_available` 플래그) | `r5_national.fold_members(..., seed)` | 다른 지점 42,166행 + 우리 지점 가중, 평가는 우리 지점 행 |\n"
        "| M3 | R3 속별 합산(G2: Microcystis + 나머지 3속, log, smearing)을 NNLS 4번째 구성원 `cg` 로 | – | `r3_genus.fit_component(..., seed)` | 우리 5지점만(속별 타깃은 우리 지점에만 있음), 그 단계 정보 구성의 피처 열 사용 |\n"
    )
    L.append("### 1.2 점예측 축(정보 축과 독립 — 단계마다 따로 표시)\n")
    L.append(
        "| 축 | 내용 |\n|---|---|\n"
        "| P0 | v1 방식 log 공간 NNLS(합=1) 앙상블, 연도 확장(`harness.ensemble_expanding`; M3 이면 구성원 4개) |\n"
        "| P1 | R1 `r_combine`: 구성원 원단위 볼록 결합(합=1·비음수·0.01 격자, 원단위 MSE 최소), 연도 확장, 2020 은 P0 |\n"
        "| P2 | C1(smearing) 단독 점예측(앙상블 생략) |\n"
        "| P3 | R1 `rh_gated_c`(참고 행만 — EXP-004 검증 major: 2025 −0.657, 기본값으로 쓰지 말 것) |\n"
    )
    L.append("### 1.3 평가 프로토콜(이 실험 전용)\n")
    L.append(
        f"- 시드 S = {SEEDS}. 구성마다 시드별로 회귀 구성원(C1·C3·C2, M3 이면 속별 2부분)과 분위(q10·q50·q90; "
        "`quantile.fit_quantiles` 에 seed 를 넘기는 자체 루프, T5 는 `r5_national.fold_members(seed=...)`)를 학습하고 "
        "시드별 `harness.metric_row` 를 구한다.\n"
        "- 보고: (a) 시드 42 표준 표(R1~R7 표와 직접 비교), (b) 시드 평균·최소·최대, (c) v1 대비 시드별 짝 차이의 평균 Δ.\n"
        "- 피처 요소(F2·F4) 대조군: 같은 개수의 표준정규 난수 열(생성기 시드 = (20261022, 학습 시드, 열 수) → 시드마다 다른 난수 3벌)을 "
        "**현재 구성 위에** 더해 같은 방식으로 학습한다. 고유 효과 = Δ(피처) − Δ(대조군)(둘 다 현재 구성 대비 시드 짝 차이 평균). "
        "T5 위에서는 새 열·난수 열 모두 다른 지점 행에서 NaN 이다.\n"
        f"- 전진 선택(CV 만): v1(P0)에서 출발. 각 단계에서 남은 요소를 하나씩 더해 보고, 시드 평균 CV r2_raw 증가(현재 구성 대비 짝 차이 평균)가 "
        f"가장 크고 (i) 시드 평균 Δrmse_log(v1 대비) ≤ +{RMSE_SLACK:.2f}, (ii) 시드 평균 리드타임 ≥ v1, (iii) 피처 요소는 고유 효과 > 0 인 후보를 채택한다. "
        f"증가가 +{MIN_GAIN:.2f} 미만이면 멈춘다. T5 는 변형 3개 중 (i)(ii) 를 만족하는 것의 증가 최대 변형이 그 단계의 T5 후보다.\n"
        "- 점예측 축: 최종 정보 구성 위에서 P0~P2 중 (i)(ii) 를 만족하는 것의 시드 평균 CV r2_raw 최대(P3 는 참고).\n"
        f"- v2 후보: 누적 경로의 구성 × P0~P2 중 채택 기준(시드 평균 Δr2_raw ≥ +{ADOPT_R2:.2f}, Δrmse_log ≤ +{RMSE_SLACK:.2f}, 리드타임 ≥ v1)을 "
        "만족하는 것 중 CV r2_raw 최대. 없으면 'v2 후보 없음'과 (i)(ii) 를 만족하는 것 중 Δr2_raw 최대 구성을 보고한다.\n"
        f"- 블록 부트스트랩: CV 2020~2024 행을 (연도, 지점) 25블록(보조: 연도 5블록)으로 {N_BOOT}회 복원 추출(시드 {BOOT_SEED}), "
        "같은 블록 뽑기를 세 시드에 똑같이 써서 시드 평균 Δ CV r2_raw 분포를 낸다(예측 고정 — 학습 난수 변동은 시드 평균으로만 반영).\n"
        "- 2025 는 각 단계 확인용 표시만(선택에 쓰지 않음). 2026 은 읽지 않는다.\n"
    )
    L.append("### 1.4 재현 점검(시드 42 = 이전 실험 산출물)\n")
    L.append(
        "| 점검 | log10 최대 절대차 |\n|---|---|\n"
        + "\n".join(
            f"| {r['점검']} | {', '.join(f'{k} {v:.2e}' for k, v in r['log10 최대 절대차'].items())} |"
            for r in [*ctx["repro"], *ctx.get("api_check", [])]
        )
        + "\n"
    )
    L.append(
        "마지막 두 줄은 공개 함수 `v2_candidate` 를 캐시 없이 새로 학습해 저장 산출물과 대조한 결과다(학습이 결정적임을 함께 확인).\n"
    )
    # ---------------------------------------------------------------- 2
    L.append("## 2. 표준 표·보조 표\n")
    std_items = _uniq(
        [("v1", "P0")]
        + [(k, "P0") for k in path[1:]]
        + [("v1", p) for p in ("P1", "P2", "P3")]
        + [(final, p) for p in ("P1", "P2", "P3")]
        + [(ck, cp)]
    )
    L.append("### 2.1 (a) 시드 42 표준 표(R1~R7 표와 직접 비교용)\n")
    L.append(
        "정보 축 누적 경로(P0), v1 위 점예측 축(점예측 축만), 최종 정보 구성 위 점예측 축, v2 후보 순. 리드타임은 그 구성의 시드 42 q90 기준.\n"
    )
    L.append(H.standard_table([ev.row(k, p, 42) for k, p in std_items]))
    L.append("\n보조 표(시드 42)\n")
    L.append(H.detail_table([ev.row(k, p, 42) for k, p in std_items]))
    L.append("\n### 2.2 (b)(c) 시드 평균·최소·최대와 v1 대비 시드 짝 차이 평균 Δ\n")
    cand_items: list[tuple[str, str]] = [("v1", "P0")]
    for st in sel["steps"]:
        for r in st["records"]:
            cand_items.append((r["key"], "P0"))
            if r.get("ctrl_key"):
                cand_items.append((r["ctrl_key"], "P0"))
            for t in r.get("t5_variants", []):
                cand_items.append((t["key"], "P0"))
    cand_items += [(d["key"], "P0") for d in sel["diag"]]
    L.append("**정보 축 후보·대조군(P0, 단계 순)**\n")
    L.append(seed_table(ev, _uniq(cand_items)))
    L.append("\n**점예측 축(v1 위 / 누적 경로 위)**\n")
    pt_items = _uniq([("v1", p) for p in POINTS] + [(k, p) for k in path[1:] for p in POINTS])
    L.append(seed_table(ev, pt_items))
    L.append("\n**시드별 값(주요 구성)**\n")
    L.append(
        per_seed_table(
            ev, _uniq([("v1", "P0")] + [(k, "P0") for k in path[1:]] + [("v1", pt), (final, pt), (ck, cp)])
        )
    )
    # ---------------------------------------------------------------- 3
    L.append("\n## 3. 선택한 구성과 이유, 채택 판정\n")
    L.append("### 3.1 단계별 전진 선택(P0, 시드 평균)\n")
    L.append(
        "증가·대조군 증가·고유 효과는 현재 구성 대비 시드 짝 차이 평균, Δ(v1) 은 v1 대비. (i) rmse_log 조건, (ii) 리드타임 조건, (iii) 대조군보다 나음.\n"
    )
    for st in sel["steps"]:
        L.append(f"**단계 {st['step']}** — 현재 구성: {parse_key(st['current']).label}\n")
        if st["records"]:
            L.append(step_table(st))
        L.append(f"\n판정: {st['reason']}\n")
    if sel["diag"]:
        L.append("**진단(선택에 쓰지 않음): F2 결측 위치를 흉내 낸 난수 대조군**\n")
        L.append(
            "F2 열은 해평·회남 행에서 모두 NaN 이라 결측 자체가 지점 표시 역할을 할 수 있다. 같은 결측 위치를 가진 난수 5열의 효과:\n"
        )
        for d in sel["diag"]:
            L.append(
                f"- 단계 {d['step']}: {d['label']} — 시드 평균 CV r2_raw {_f(d['cv_r2_raw'])}, 증가 {_f(d['gain'], sign=True)}, "
                f"Δrmse_log(v1) {_f(d['d_rmse_v1'], sign=True)}, 리드 {_f(d['lead'], 2)}\n"
            )
    L.append("\n### 3.2 누적 표(정보 축 경로 × 점예측 축, 시드 평균 CV r2_raw, 괄호는 v1·P0 대비 짝 Δ)\n")
    L.append(cumulative_table(ev, path))
    L.append("\n### 3.3 점예측 축 선택(최종 정보 구성 위)\n")
    L.append(
        md_rows(
            ctx["point_recs"],
            [
                ("label", "점예측"),
                ("cv_r2_raw", "CV r2_raw 평균"),
                ("cv_r2_raw_min", "최소"),
                ("cv_r2_raw_max", "최대"),
                ("d_r2_v1", "Δ r2_raw(v1)"),
                ("cv_rmse_log", "CV rmse_log"),
                ("d_rmse_v1", "Δ rmse_log(v1)"),
                ("lead", "리드 평균"),
                ("cvfold_r2_raw", "CV 폴드평균 r2_raw"),
                ("y2025_r2_raw", "2025 r2_raw"),
                ("y2025_rmse_log", "2025 rmse_log"),
                ("ok", "(i)(ii) 만족"),
                ("selectable", "선택 대상"),
            ],
        )
    )
    L.append(f"\n선택: **{POINT_LABEL[pt]}**(최종 정보 구성 {parse_key(final).label} 위).\n")
    L.append("\n### 3.4 v2 후보와 채택 판정(시드 평균, v1 대비)\n")
    L.append(
        md_rows(
            v2["table"],
            [
                ("label", "구성"),
                ("point", "점예측"),
                ("cv_r2_raw", "CV r2_raw 평균"),
                ("d_cv_r2_raw", "Δ r2_raw"),
                ("d_cv_rmse_log", "Δ rmse_log"),
                ("lead", "리드 평균"),
                ("lead_ok", "리드 유지"),
                ("pass", "채택 기준"),
            ],
        )
    )
    if v2["found"]:
        L.append(
            f"\n- **v2 후보: {_label(ck, cp)}** — 채택 기준을 만족하는 누적 구성 중 시드 평균 CV r2_raw 최대. "
            f"Δr2_raw {_f(adop['d_cv_r2_raw'], sign=True)}, Δrmse_log {_f(adop['d_cv_rmse_log'], sign=True)}, 리드 {_f(adop['lead'], 2)} ≥ {_f(lead_v1, 2)}.\n"
        )
    else:
        L.append(
            f"\n- **v2 후보 없음.** 가장 가까운 구성: {_label(ck, cp)} — Δr2_raw {_f(adop['d_cv_r2_raw'], sign=True)}"
            f"(기준 +{ADOPT_R2:.2f}), Δrmse_log {_f(adop['d_cv_rmse_log'], sign=True)}, 리드 {_f(adop['lead'], 2)}(v1 {_f(lead_v1, 2)}).\n"
        )
    s42 = H.adoption(ev.row("v1", "P0", 42), ev.row(ck, cp, 42))
    L.append(
        f"- 참고(시드 42 단일, `harness.adoption`): Δr2_raw {_f(s42['d_cv_r2_raw'], sign=True)}, Δrmse_log {_f(s42['d_cv_rmse_log'], sign=True)}, "
        f"리드 유지 {_f(s42['lead_ok'])} → {'통과' if s42['pass'] else '미달'}.\n"
    )
    L.append("\n### 3.5 정보 축·점예측 축 분해(이중 계산 방지, 시드 평균 v1 대비 Δ)\n")
    L.append(
        md_rows(
            ctx["decomp"],
            [
                ("이름", "구분"),
                ("cv_r2_raw", "CV r2_raw 평균"),
                ("d_cv_r2_raw", "Δ r2_raw"),
                ("d_cv_rmse_log", "Δ rmse_log"),
                ("lead", "리드 평균"),
                ("pass", "채택 기준"),
            ],
        )
    )
    L.append(
        f"\n상호작용(둘 다 − 정보만 − 점예측만) = {_f(ctx['decomp_inter'], sign=True)}. "
        "정보 축의 Δ 와 점예측 축의 Δ 를 따로 더하면 안 되고, '둘 다' 행이 실제 결합 효과다.\n"
    )
    L.append("\n### 3.6 연도별 CV r2_raw(2020~2024)·폴드 평균(시드 평균)\n")
    yr_items = _uniq([("v1", "P0")] + [(k, "P0") for k in path[1:]] + [("v1", pt), (final, pt), (ck, cp)])
    L.append(year_table(ev, yr_items))
    L.append("\n### 3.7 블록 부트스트랩(Δ CV r2_raw, 시드 평균, v1·P0 대비)\n")
    L.append(boot_table(ctx["boots"]))
    L.append("\n### 3.8 2025 확인 진단(선택에 쓰지 않음, 시드 평균 예측)\n")
    L.append(
        "과대예측 = 예측 ≥ 10,000 이고 (관측+1) 의 3배 초과, 과소예측 = 관측 ≥ 10,000 이고 (예측+1) 의 3배 초과. 비중은 2025 원단위 SSE 대비.\n"
    )
    L.append(
        md_rows(
            ctx["diag2025"],
            [
                ("label", "구성"),
                ("r2_seedmean_pred", "2025 r2_raw(시드평균 예측)"),
                ("sse_ratio_v1", "SSE / v1 SSE"),
                ("top3_share", "상위 3행 SSE 비중"),
                ("n_over", "과대예측 행"),
                ("over_share", "과대예측 SSE 비중"),
                ("n_under", "과소예측 행"),
                ("under_share", "과소예측 SSE 비중"),
            ],
        )
    )
    L.extend(_alt_section(ctx))
    L.append("\n### 3.10 해석\n")
    L.extend(_discussion(ctx))
    L.append("\n### 3.11 운영 가능성 메모(일일 운영 파이프라인 재현성)\n")
    L.append(
        "| 요소 | 메모 |\n|---|---|\n"
        + "\n".join(f"| {k} | {v} |" for k, v in OPERATIONAL_NOTES.items())
        + "\n"
    )
    # ---------------------------------------------------------------- 4
    L.append("\n## 4. 누수·2026 점검\n")
    L.append(
        f"- 자기 테스트 `tests/test_exp_r_combo.py`: {tests.get('summary', '')} — 2026 가드(진입 함수 8곳·test 분할), 구성 키 왕복·조합, "
        "대조 난수(시드별 재현·서로 다름·결측 위치), 인덱스 정렬, 캐시 작업 분할, P1 결합 = R1 `recombine_raw`, 4구성원 단체 격자, "
        "P1 연도 확장 누수(컷 이후 관측·예측을 바꿔도 컷 이하 출력 동일), 점예측 축 구성, 전진 선택 규칙, 블록 부트스트랩.\n"
        "- 새 피처는 만들지 않았다. F2·F4 는 R2·R4 공개 API(`cut_as_of` 로 as_of 이후 행을 버리는 순수 함수)를 그대로 썼고, "
        "F4 는 운영 재현용 공개 지연 60일(OPERATIONAL)만 썼다. 재사용한 모듈의 테스트("
        + ", ".join(f"`{p.split('/')[-1]}`" for p in DEP_TESTS)
        + f")를 같은 실행에서 다시 돌렸다: {tests.get('deps', {}).get('summary', '실행 안 함')}.\n"
        "- 모든 학습 프레임은 `harness.load_base()`(base_date ≤ 2025-12-31, test 분할 없음)에서 오고 `guard_no_2026` 을 거친다(`frame_for`·`own_members`·"
        "`pooled_members`·`genus_members`·`point_preds`·`Evaluator`). 다른 지점 표본(EXP-008)도 `load_other_samples` 에서 가드를 거친다. "
        "`test_targets_DO_NOT_USE`·`posthoc_2026` 를 읽지 않고 test 행 예측을 만들지 않았다. 리드타임은 `harness.leadtime`(2025-12-31 까지).\n"
        "- 선택에 쓰는 값(전진 선택 증가·대조군·T5 변형·점예측 축·v2)은 모두 2020~2024 CV 지표다. P1 결합 가중치와 P0 NNLS 가중치는 연도 확장 적합"
        "(연도 Y 는 Y 이전 CV OOF, 2025 는 2020~2024). 2025 지표는 표에 표시만 했다.\n"
        f"- 보호 파일: `python scripts/exp_check_protected.py` → {prot.get('summary', '')}. 공유 파일(harness·기존 src·config·docs·MANIFEST)은 고치지 않았다.\n"
    )
    # ---------------------------------------------------------------- 5
    L.append("\n## 5. 소요 시간 / 상한, 한계, 다음 단계\n")
    keys_main = {k for (k, _p, _s) in ev.rows}
    keys_all = keys_main | {k for (k, _p, _s) in ctx["alt"]["ev"].rows}
    L.append(
        f"- 소요: 착수 {TASK_START} → 보고서 작성 {datetime.now():%H:%M}, {elapsed_hours():.2f}시간 / 상한 {BUDGET_HOURS:.0f}시간. "
        f"평가한 구성 {len(keys_all)}개(본 프로토콜 {len(keys_main)}개 + 민감도에서 추가 {len(keys_all - keys_main)}개, 대조군 포함) × 시드 {len(SEEDS)}개"
        "(병렬 프로세스 4개, LightGBM 스레드 4개씩, 캐시 `data/processed/exp/EXP-011/cache/`). 상한 초과 없음.\n"
    )
    L.extend(_limitations(ctx))
    L.append(
        "\n첨부: `metrics.json`(시드별 표준 지표 행 전체·요약·선택 기록·부트스트랩·재현 점검). 행 단위: `data/processed/exp/EXP-011/chosen_oof.parquet`"
        "(시드 42 v2 후보 구성원 + ens(P0) + pred(최종 점예측)), `points_oof.parquet`(구성·점예측·시드별 OOF), `robust_alt_oof.parquet`(3.9 견고성 대안, 시드 42, 분위 v1, pred = P0), `features.parquet`(F2·F4 열).\n"
    )
    return "\n".join(L)


def _limitations(ctx: dict) -> list[str]:
    """한계·다음 단계(결과에 따라 문장 일부가 바뀐다)."""
    alt = ctx["alt"]
    fa = parse_key(alt["final"]).label
    return [
        "- 한계\n"
        "  1. 시드 3개 평균도 학습 난수 잡음을 완전히 없애지 못한다(v1 시드 폭 0.04, 리드타임도 시드마다 ±1~3). 특히 분위를 다시 학습하면 q90 포착 수가 "
        "시드·피처 구성에 따라 흔들려, 조건 (ii) 가 정보의 질보다 분위 모델의 우연한 변화에 좌우될 수 있다(F2 탈락 사유).\n"
        "  2. 전진 선택은 탐욕적이다. 단계 1 에서 T5 를 고른 뒤 F2 의 증가가 크게 줄어(겹침), 순서가 바뀌면 경로가 달라진다(3.9 민감도에서 실제로 F2 → M3 경로).\n"
        "  3. T5 는 변형 3개 중 최대를 고르므로 다른 요소보다 선택 낙관이 조금 더 있다. 원단위 R² 는 소수 극단 행이 좌우한다(부트스트랩 구간·연도 표 참고).\n"
        "  4. 'CV r2_raw 최대' 규칙은 점예측 축(P1·P2)을 고르는 쪽으로 기우는데, 그 이득은 2025 확인에서 재현되지 않았다(3.8).\n"
        "  5. 하이퍼파라미터는 v1 그대로이며 통합 표본(4만 행)에 맞춘 재탐색은 하지 않았다. M3 의 속별 모델은 T5 위에서도 우리 5지점만으로 학습했다(속별 타깃이 우리 지점에만 있음).\n"
        "  6. F2 lag 0 은 상류의 같은 날 채수값을 쓴다(v1 `cell_log_t0` 와 같은 관행이나 2025-08 이전 공개는 채수 3일차). T5 는 운영 예측에는 부담이 없지만 재학습 자료가 크다.\n"
        "- 다음 단계 제안\n"
        f"  1. 사용자 결정: 규칙상 v2 후보(3.4)와 견고성 대안({fa} · P0, 분위 v1 유지, 3.9) 중 선택. 메인 세션의 `EXP-summary.md` 에 두 후보의 CV·폴드 평균·블록 구간·2025 확인을 나란히 싣는 것을 권한다.\n"
        "  2. 점예측 축을 쓰려면 원단위 결합의 과대예측을 줄이는 장치(예: P0 와 P2 사이 수축 계수를 연도 확장 CV 로 적합, 예측 상한)를 CV 로만 따로 검증한다.\n"
        "  3. 분위(경보) 모델과 회귀(점예측) 모델의 피처 구성을 분리해 고르는 설계(리드타임은 분위 모델로만 판정)를 프로토콜로 정할지 검토한다.\n"
        "  4. F4(영양염)·R6·R7 은 시드 평균·대조군 비교에서도 효과가 없어 v2 에서 제외한다.",
    ]


def _json_default(o: object) -> object:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    raise TypeError(type(o))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EXP-011 종합(누적 결합 → v2 후보)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fresh", action="store_true", help="학습 캐시를 지우고 처음부터")
    ap.add_argument("--no-tests", action="store_true", help="보고서 작성 때 자기 테스트를 돌리지 않음")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.fresh and CACHE.exists():
        shutil.rmtree(CACHE)
    budget = H.Budget(BUDGET_HOURS - elapsed_hours(), EXP_ID)
    status = "completed"
    ctx = run_all(a.workers, budget)
    if ctx["v2"]["key"] != V2["combo"] or ctx["v2"]["point"] != V2["point"]:
        log.warning(
            "V2 상수(%s)와 이번 선택(%s · %s)이 다르다 — 상수를 고칠 것",
            V2,
            ctx["v2"]["key"],
            ctx["v2"]["point"],
        )
    if ctx["alt"]["final"] != ROBUST_ALT["combo"]:
        log.warning(
            "ROBUST_ALT 상수(%s)와 민감도 경로 최종 구성(%s)이 다르다", ROBUST_ALT, ctx["alt"]["final"]
        )
    save_outputs(ctx)
    ctx["api_check"] = public_api_check(ctx)
    tests = {"passed": None, "summary": "실행 안 함(--no-tests)"} if a.no_tests else run_tests()
    prot = protected_check()
    OUT_REPORT.mkdir(parents=True, exist_ok=True)
    (OUT_REPORT / "README.md").write_text(render(ctx, tests, prot, status), encoding="utf-8", newline="\n")
    met = metrics_json(ctx, tests, prot, status)
    (OUT_REPORT / "metrics.json").write_text(
        json.dumps(met, ensure_ascii=False, indent=1, default=_json_default) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    log.info(
        "v2: %s · %s (found=%s), 소요 %.2fh",
        ctx["v2"]["key"],
        ctx["v2"]["point"],
        ctx["v2"]["found"],
        elapsed_hours(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
