"""운영 모델 v2 — 최종 모델 C = v1 로그 앙상블(C1·C3·C2) + 상류 피처 5열 + 속별 구성원 cg.

EXP-confirm(사전등록 확인 실험)을 통과한 구성 C 를 운영 경로로 옮긴다. 실험 코드와의 동등성은
scripts/check_v2_equivalence.py·tests/test_v2_equivalence.py 가 확인한다.

구성(V2Config 로 정의 — 피처 묶음·구성원·가중치를 바꿔 v1 이나 이후 예보 피처 추가 구성도 같은 경로로 돈다)
- 피처: v1 선택 피처 30개(config/features.yaml selected)
  + 묶음 'upstream'(features.upstream.UPSTREAM_COLS 5열).
  새 피처 묶음은 FEATURE_GROUPS 에 (열 목록, 생성 함수)로 등록하고 V2Config.feature_groups 에 이름을 넣는다.
- 구성원: c1 = C1 log 가중 회귀(smearing), c3 = C3 hurdle, c2 = C2 tweedie
  (모두 v1 하이퍼파라미터, config/model.yaml),
  cg = 속별 G2 합산(models.genus, C1 설정). 학습 피처는 모든 구성원이 같은 열(35)을 쓴다.
- 결합: log10(y+1) 공간 NNLS(합=1). 가중치는 2020~2024 연도 확장 CV OOF(시드 42)로 적합(fit_weights) —
  exp.harness.ensemble_expanding 의 2025 가중치와 같은 계산.
- 분위 q10/q50/q90·분류기(b)·CQR·운영점은 v1 동결본을 그대로 쓴다(레지스트리 classifier·quantile = v1 버전).

공개 함수
- config_v2() / config_v1() : 구성 정의
- load_training_frame()     : 최종 학습 행(기준일·목표일 ≤ 2025-12-31 인 학습·검증 행 전체) + 추가 피처
- ensure_features(df, cfg)  : 구성의 추가 피처 묶음을 붙인다(이미 있으면 그대로)
- cv_members(df, seed)      : 구성원별 연도 확장 OOF(2020~2025 행, 원단위)
- fit_weights(df, seed=42)  : 2020~2024 OOF NNLS 가중치
- fit_final(train_df)       : 전체 학습 → V2Model,  V2Model.predict(feat_df) → 원단위 예측

2026 규칙: 학습·가중치 적합 프레임에 기준일 또는 목표일이 2025-12-31 이후인 행이 있으면 중단한다(guard_train).
예측(2026 test·일일 as-of) 행의 피처는 원자료를 행의 기준일까지만 잘라 계산한다(features.upstream).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR
from algaecast.features.upstream import UPSTREAM_COLS, build_upstream
from algaecast.models import data as D
from algaecast.models import genus as G
from algaecast.models.cv import FINAL_VALID_YEAR, FOLD_YEARS, fold_frames, year_folds
from algaecast.models.ensemble import combine, nnls_weights
from algaecast.models.train import (
    HURDLE_THRESHOLD,
    SEED,
    VariantSpec,
    _lgb_params,
    _prep,
    feature_sets,
    to_cells,
)

log = logging.getLogger(__name__)

LAST_DATE = pd.Timestamp("2025-12-31")  # 학습 행의 기준일·목표일 상한
CV_YEARS: tuple[int, ...] = tuple(FOLD_YEARS)
FINAL_YEAR = FINAL_VALID_YEAR
KIND = "ensemble_v2"
FORMAT_VERSION = 1

FeatureBuilder = Callable[[pd.DataFrame, pd.DataFrame | None], pd.DataFrame]
# 추가 피처 묶음: 이름 → (열 목록, 생성 함수(df, 조류 원자료 또는 None) → 같은 인덱스의 열)
FEATURE_GROUPS: dict[str, tuple[list[str], FeatureBuilder]] = {
    "upstream": (list(UPSTREAM_COLS), build_upstream),
}


# ---------------------------------------------------------------- 구성
@dataclass(frozen=True)
class MemberDef:
    """앙상블 구성원 정의.

    name = 가중치 키, kind = 적합 방식, params = 하이퍼파라미터 출처(member_specs 키).
    """

    name: str
    kind: str  # log_w | hurdle | tweedie | genus
    params: str  # c1 | c3 | c2
    label: str = ""


V1_MEMBERS: tuple[MemberDef, ...] = (
    MemberDef("c1", "log_w", "c1", "회귀 C1(smearing)"),
    MemberDef("c3", "hurdle", "c3", "회귀 C3 hurdle"),
    MemberDef("c2", "tweedie", "c2", "회귀 C2 tweedie"),
)
GENUS_MEMBER = MemberDef("cg", "genus", "c1", "속별 cg(G2: Microcystis + 나머지 3속, smearing)")


@dataclass(frozen=True)
class V2Config:
    """모델 구성: 기본 피처·추가 피처 묶음·구성원·(고정) 가중치·시드."""

    name: str
    base_features: tuple[str, ...]
    feature_groups: tuple[str, ...] = ()
    members: tuple[MemberDef, ...] = V1_MEMBERS
    weights: tuple[tuple[str, float], ...] | None = None  # None 이면 fit_weights(2020~2024 OOF NNLS)
    seed: int = SEED

    @property
    def extra_features(self) -> list[str]:
        out: list[str] = []
        for g in self.feature_groups:
            out += [c for c in FEATURE_GROUPS[g][0] if c not in out]
        return out

    @property
    def cols(self) -> list[str]:
        base = list(self.base_features)
        return base + [c for c in self.extra_features if c not in base]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.members)

    def fixed_weights(self) -> dict[str, float] | None:
        return None if self.weights is None else {k: float(v) for k, v in self.weights}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base_features": list(self.base_features),
            "feature_groups": list(self.feature_groups),
            "extra_features": self.extra_features,
            "members": [
                {"name": m.name, "kind": m.kind, "params": m.params, "label": m.label} for m in self.members
            ],
            "weights": None if self.weights is None else [[k, float(v)] for k, v in self.weights],
            "seed": int(self.seed),
        }

    @classmethod
    def from_dict(cls, d: dict) -> V2Config:
        w = d.get("weights")
        return cls(
            name=str(d["name"]),
            base_features=tuple(d["base_features"]),
            feature_groups=tuple(d.get("feature_groups", ())),
            members=tuple(
                MemberDef(m["name"], m["kind"], m["params"], m.get("label", "")) for m in d["members"]
            ),
            weights=None if w is None else tuple((str(k), float(v)) for k, v in w),
            seed=int(d.get("seed", SEED)),
        )


def v1_features() -> tuple[str, ...]:
    """v1 선택 피처 30개(perc75)."""
    return tuple(feature_sets()["perc75"])


def config_v2() -> V2Config:
    """최종 모델 C: v1 30 + 상류 5, 구성원 c1·c3·c2·cg, 가중치는 OOF NNLS(fit_weights)."""
    return V2Config(
        name="v2_C",
        base_features=v1_features(),
        feature_groups=("upstream",),
        members=(*V1_MEMBERS, GENUS_MEMBER),
    )


def v1_weights() -> dict[str, float]:
    """config/model.yaml ensemble.weights(v1 동결 가중치)를 구성원 이름(c1·c3·c2)으로."""
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    w = cfg["ensemble"]["weights"]
    by_label = {m.label: m.name for m in V1_MEMBERS}
    return {by_label[k]: float(v) for k, v in w.items()}


def config_v1() -> V2Config:
    """v1 구성(피처 30, 구성원 3, config/model.yaml 가중치) — 같은 운영 경로로 v1 제출본을 재현하는 확인용."""
    w = v1_weights()
    return V2Config(
        name="v1",
        base_features=v1_features(),
        members=V1_MEMBERS,
        weights=tuple((m.name, w[m.name]) for m in V1_MEMBERS),
    )


def member_specs() -> dict[str, VariantSpec]:
    """구성원 하이퍼파라미터(v1 동결, config/model.yaml).

    c1 = selected, c3 = hurdle 스터디, c2 = tweedie 스터디.
    """
    from algaecast.models.tune import spec_from_params  # optuna 의존 — 학습할 때만 불러온다

    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    st = cfg["studies"]
    return {
        "c1": spec_from_params(cfg["selected"]["params"], "log_w"),
        "c3": spec_from_params(st["hurdle_rmse_log_perc75_S1"]["best_params"], "hurdle"),
        "c2": spec_from_params(st["tweedie_rmse_log_perc75_S1"]["best_params"], "tweedie"),
    }


# ---------------------------------------------------------------- 데이터·가드
def guard_train(df: pd.DataFrame) -> None:
    """학습·가중치 프레임 가드: 기준일·목표일 ≤ 2025-12-31, test 분할 없음, 타깃 있음."""
    for col in ("base_date", "target_date"):
        d = pd.to_datetime(df[col])
        if (d > LAST_DATE).any():
            raise RuntimeError(f"{col} > 2025-12-31 인 행 {int((d > LAST_DATE).sum())}개 — 학습 금지")
    if "split" in df.columns and (df["split"] == "test").any():
        raise RuntimeError("test 분할 행이 학습 프레임에 섞임")
    if not np.isfinite(df["target_cells"].to_numpy(dtype=float)).all():
        raise RuntimeError("타깃 결측 행이 학습 프레임에 섞임")


def ensure_features(df: pd.DataFrame, config: V2Config, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """구성의 추가 피처 묶음을 붙인 프레임(같은 인덱스). 묶음의 열이 모두 있으면 다시 계산하지 않는다.

    algae: 조류경보제 원자료(5지점). None 이면 각 생성 함수의 기본 원자료(data/raw)를 읽는다.
    """
    out = df
    for g in config.feature_groups:
        cols, builder = FEATURE_GROUPS[g]
        if all(c in out.columns for c in cols):
            continue
        new = builder(out, algae)[cols]
        out = pd.concat([out.drop(columns=[c for c in cols if c in out.columns]), new], axis=1)
    return out


def load_training_frame(
    strategy: str = "S1", config: V2Config | None = None, algae: pd.DataFrame | None = None
) -> pd.DataFrame:
    """최종 학습 행 + 추가 피처.

    학습·검증 행 중 기준일 ≤ 2025-12-31 이면서 목표일 ≤ 2025-12-31(행 순서 = v1 로더).
    """
    cfg = config or config_v2()
    df = D.load_train_valid(strategy)
    keep = (pd.to_datetime(df["base_date"]) <= LAST_DATE) & (pd.to_datetime(df["target_date"]) <= LAST_DATE)
    df = df[keep].reset_index(drop=True)
    guard_train(df)
    return ensure_features(df, cfg, algae)


def years_of(df: pd.DataFrame) -> np.ndarray:
    return pd.to_datetime(df["base_date"]).dt.year.to_numpy()


# ---------------------------------------------------------------- 구성원 적합·예측
def _fit_hurdle(tr: pd.DataFrame, cols: list[str], spec: VariantSpec, seed: int) -> dict:
    """C3: 출현(>1,000) 분류기 × 상·하 조건부 log 회귀(train.fit_predict 의 hurdle 분기와 같은 적합)."""
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    ylog = tr["target_log"].to_numpy(dtype=float)
    over = (tr["target_cells"].to_numpy(dtype=float) > HURDLE_THRESHOLD).astype(int)
    clf = lgb.LGBMClassifier(**_lgb_params(spec.cls_params, seed, objective="binary"))
    clf.fit(Xt, over, categorical_feature=cats or "auto")
    hi_mask = over == 1
    hi = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
    hi.fit(Xt[hi_mask], ylog[hi_mask], categorical_feature=cats or "auto")
    lo = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
    lo.fit(Xt[~hi_mask], ylog[~hi_mask], categorical_feature=cats or "auto")
    return {
        "kind": "hurdle",
        "clf": clf,
        "hi": hi,
        "lo": lo,
        "cats": cats,
        "categories": {c: list(Xt[c].cat.categories) for c in cats},
    }


def _fit_tweedie(tr: pd.DataFrame, cols: list[str], spec: VariantSpec, seed: int) -> dict:
    """C2: 원단위 tweedie(또는 poisson) 회귀(train.fit_predict 의 tweedie 분기와 같은 적합)."""
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    extra: dict[str, object] = {"objective": spec.objective_raw}
    if spec.objective_raw == "tweedie":
        extra["tweedie_variance_power"] = spec.variance_power
    m = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, **extra))
    m.fit(Xt, tr["target_cells"].to_numpy(dtype=float), categorical_feature=cats or "auto")
    return {
        "kind": "tweedie",
        "model": m,
        "cats": cats,
        "categories": {c: list(Xt[c].cat.categories) for c in cats},
    }


def fit_member(
    member: MemberDef,
    tr: pd.DataFrame,
    cols: list[str],
    specs: dict[str, VariantSpec],
    seed: int,
    genus_algae: pd.DataFrame | None = None,
) -> dict:
    """구성원 하나를 tr 행으로 적합한 객체(dict, LightGBM 모델 포함)."""
    spec = specs[member.params]
    if member.kind == "log_w":
        return G.fit_log_part(tr, cols, spec, seed)
    if member.kind == "hurdle":
        return _fit_hurdle(tr, cols, spec, seed)
    if member.kind == "tweedie":
        return _fit_tweedie(tr, cols, spec, seed)
    if member.kind == "genus":
        return G.fit_genus(tr, cols, spec, seed, algae=genus_algae)
    raise ValueError(f"알 수 없는 구성원 종류: {member.kind}")


def predict_member(obj: dict, feat: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """구성원 원단위 예측(NaN→0, 음수→0). log_w 는 smearing 적용, hurdle 은 p·E[hi] + (1−p)·E[lo]."""
    kind = obj["kind"]
    if kind == "log_w":
        return G.predict_log_part(obj, feat, cols)
    if kind == "genus":
        return G.predict_genus(obj, feat, cols)
    X = G.prep_x(feat, cols, obj["cats"], obj["categories"])
    if kind == "hurdle":
        p = np.asarray(obj["clf"].predict_proba(X)[:, 1], dtype=float)
        e_hi = to_cells(np.asarray(obj["hi"].predict(X), dtype=float))
        e_lo = to_cells(np.asarray(obj["lo"].predict(X), dtype=float))
        raw = p * e_hi + (1 - p) * e_lo
    elif kind == "tweedie":
        raw = np.clip(np.asarray(obj["model"].predict(X), dtype=float), 0, None)
    else:
        raise ValueError(f"알 수 없는 구성원 종류: {kind}")
    return np.clip(np.nan_to_num(raw, nan=0.0), 0, None)


def _genus_algae(config: V2Config) -> pd.DataFrame | None:
    return G.load_target_algae() if any(m.kind == "genus" for m in config.members) else None


# ---------------------------------------------------------------- CV·가중치
def cv_members(
    df: pd.DataFrame,
    seed: int | None = None,
    config: V2Config | None = None,
    *,
    specs: dict[str, VariantSpec] | None = None,
) -> dict[str, np.ndarray]:
    """구성원별 연도 확장 OOF(원단위). 폴드 = models.cv.year_folds(F1~F5 + Final: ≤2024 → 2025).

    2020~2025 행만 값이 있고 그 이전 행은 NaN. df 행 순서를 그대로 쓴다(LightGBM bagging 이 순서에 의존).
    """
    cfg = config or config_v2()
    seed = cfg.seed if seed is None else int(seed)
    df = ensure_features(df, cfg)
    guard_train(df)
    specs = specs or member_specs()
    galgae = _genus_algae(cfg)
    cols = cfg.cols
    out = {m.name: np.full(len(df), np.nan) for m in cfg.members}
    for fo in year_folds(df, include_final=True):
        tr, va = fold_frames(df, fo)
        for m in cfg.members:
            obj = fit_member(m, tr, cols, specs, seed, galgae)
            out[m.name][fo.valid_idx] = predict_member(obj, va, cols)
        log.info("CV 폴드 %s(검증 %d): 구성원 %s", fo.name, fo.valid_year, ",".join(cfg.names))
    return out


def fit_weights(
    df: pd.DataFrame,
    seed: int = SEED,
    config: V2Config | None = None,
    *,
    oof: dict[str, np.ndarray] | None = None,
    specs: dict[str, VariantSpec] | None = None,
) -> dict[str, float]:
    """2020~2024 CV OOF 로 log 공간 NNLS(합=1) 가중치(구성원 순서 유지). oof 를 주면 그것을 쓴다."""
    cfg = config or config_v2()
    guard_train(df)
    oof = oof if oof is not None else cv_members(df, seed, cfg, specs=specs)
    cv_mask = np.isin(years_of(df), CV_YEARS)
    obs = df["target_cells"].to_numpy(dtype=float)
    return nnls_weights({k: np.asarray(oof[k])[cv_mask] for k in cfg.names}, obs[cv_mask])


def oof_ensemble(df: pd.DataFrame, oof: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """2025(Final 폴드) 행에 가중치를 적용한 앙상블 OOF(그 외 행 NaN) — 2025 홀드아웃 지표용."""
    out = np.full(len(df), np.nan)
    fin = years_of(df) == FINAL_YEAR
    out[fin] = combine({k: np.asarray(oof[k])[fin] for k in weights}, weights)
    return out


# ---------------------------------------------------------------- 최종 모델
@dataclass
class V2Model:
    """적합한 v2 앙상블: 구성원(dict, LightGBM 모델 포함)·가중치·열·범주 정보.

    aux = 분류기·분위(v1 동결) 입력용 열·범주(v1 회귀 레지스트리와 같은 값) — predict_registry 가 쓴다.
    """

    config: V2Config
    members: dict[str, dict]
    weights: dict[str, float]
    cols: list[str]
    cats: list[str]
    categories: dict[str, list[str]]
    train_info: dict = field(default_factory=dict)
    aux: dict = field(default_factory=dict)

    def features(self, feat: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.DataFrame:
        """예측 행에 구성의 추가 피처를 붙인다(이미 있으면 그대로). 원자료는 행의 기준일까지만 쓴다."""
        return ensure_features(feat, self.config, algae)

    def predict_members(self, feat: pd.DataFrame, algae: pd.DataFrame | None = None) -> dict[str, np.ndarray]:
        f = self.features(feat, algae)
        return {k: predict_member(self.members[k], f, self.cols) for k in self.weights}

    def predict(self, feat: pd.DataFrame, algae: pd.DataFrame | None = None) -> np.ndarray:
        """원단위 예측(cells/mL, ≥0) = 10^(Σ w_k·log10(ŷ_k + 1)) − 1."""
        return combine(self.predict_members(feat, algae), self.weights)

    def to_registry(self) -> dict:
        """레지스트리 저장 객체(kind = ensemble_v2). 사용자 정의 클래스 없이 dict·LightGBM 객체만 담는다."""
        return {
            "kind": KIND,
            "format": FORMAT_VERSION,
            "config": self.config.to_dict(),
            "weights": dict(self.weights),
            "members": self.members,
            "cols": list(self.cols),
            "cats": list(self.cats),
            "categories": {k: list(v) for k, v in self.categories.items()},
            "train_info": dict(self.train_info),
            "aux": dict(self.aux),
        }

    @classmethod
    def from_registry(cls, obj: dict) -> V2Model:
        if obj.get("kind") != KIND:
            raise ValueError(f"ensemble_v2 객체가 아니다: kind={obj.get('kind')}")
        return cls(
            config=V2Config.from_dict(obj["config"]),
            members=obj["members"],
            weights={k: float(v) for k, v in obj["weights"].items()},
            cols=list(obj["cols"]),
            cats=list(obj["cats"]),
            categories={k: list(v) for k, v in obj["categories"].items()},
            train_info=dict(obj.get("train_info", {})),
            aux=dict(obj.get("aux", {})),
        )


def from_v1_registry(obj: dict) -> V2Model:
    """v1 동결 회귀 객체(kind = ensemble, models/regression/20261021_091108)를
    다시 학습하지 않고 V2Model 로 감싼다.

    v1 구성원 모델·smearing·가중치(config/model.yaml 과 같은 값)를 그대로 쓰므로 V2Model.predict 가
    v1 predict_registry 와 같은 값을 내야 한다(운영 예측 경로 확인용).
    """
    if obj.get("kind") != "ensemble":
        raise ValueError(f"v1 ensemble 객체가 아니다: kind={obj.get('kind')}")
    cfg = config_v1()
    by_label = {m.label: m.name for m in V1_MEMBERS}
    cats, categories = list(obj["cats"]), {k: list(v) for k, v in obj["categories"].items()}
    members: dict[str, dict] = {}
    for label, m in obj["members"].items():
        name = by_label[label]
        if m["kind"] == "log_w":
            members[name] = {"kind": "log_w", "model": m["model"], "smear": float(m["smear"])}
        elif m["kind"] == "hurdle":
            members[name] = {"kind": "hurdle", "clf": m["clf"], "hi": m["hi"], "lo": m["lo"]}
        else:
            members[name] = {"kind": "tweedie", "model": m["model"]}
        members[name].update({"cats": cats, "categories": categories})
    return V2Model(
        config=cfg,
        members=members,
        weights={by_label[k]: float(v) for k, v in obj["weights"].items()},
        cols=list(obj["cols"]),
        cats=cats,
        categories=categories,
        train_info={"source": "v1 frozen registry"},
    )


def train_info(df: pd.DataFrame, seed: int) -> dict:
    """학습 범위 요약(행 수·기준일·목표일 범위·지점별 행 수·시드)."""
    bd, td = pd.to_datetime(df["base_date"]), pd.to_datetime(df["target_date"])
    return {
        "n_rows": int(len(df)),
        "base_date_min": str(bd.min().date()),
        "base_date_max": str(bd.max().date()),
        "target_date_max": str(td.max().date()),
        "rule": "기준일 ≤ 2025-12-31 이면서 목표일 ≤ 2025-12-31 인 학습·검증 행 전체",
        "rows_by_site": {
            str(k): int(v) for k, v in df["station_id"].astype(str).value_counts().sort_index().items()
        },
        "seed": int(seed),
    }


def fit_final(
    train_df: pd.DataFrame,
    config: V2Config | None = None,
    weights: dict[str, float] | None = None,
    *,
    seed: int | None = None,
    specs: dict[str, VariantSpec] | None = None,
    algae: pd.DataFrame | None = None,
) -> V2Model:
    """train_df 전체로 구성원을 적합한 V2Model.

    weights 가 없으면 구성의 고정 가중치, 그것도 없으면 fit_weights(train_df)(2020~2024 OOF NNLS)를 쓴다.
    algae 는 추가 피처 계산용 조류 원자료(None 이면 data/raw).
    속별 타깃은 genus.load_target_algae(≤2025)만 쓴다.
    """
    cfg = config or config_v2()
    seed = cfg.seed if seed is None else int(seed)
    df = ensure_features(train_df, cfg, algae)
    guard_train(df)
    specs = specs or member_specs()
    if weights is None:
        weights = cfg.fixed_weights() or fit_weights(df, seed, cfg, specs=specs)
    w = {n: float(weights[n]) for n in cfg.names}
    cols = cfg.cols
    galgae = _genus_algae(cfg)
    members = {m.name: fit_member(m, df, cols, specs, seed, galgae) for m in cfg.members}
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(df[cols], cats)
    return V2Model(
        config=cfg,
        members=members,
        weights=w,
        cols=cols,
        cats=cats,
        categories={c: list(Xt[c].cat.categories) for c in cats},
        train_info=train_info(df, seed),
    )
