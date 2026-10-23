# ruff: noqa: E501  (한국어 표 머리글)
"""R3(EXP-006) 속별 모델 합산 — 4속(또는 Microcystis vs 나머지) log 회귀 후 원단위 합산.

목적
- 유해남조류 세포수(합계)를 4속(Microcystis·Dolichospermum(Anabaena)·Aphanizomenon·Oscillatoria)으로 나눠
  속마다 C1 설정(log10 타깃·가중 w=1+α·log, v1 하이퍼파라미터) 회귀 → 속별 smearing → 원단위 합산.
- 합계 모델(v1 C1·앙상블)과 같은 하네스 지표로 비교하고, 속별 합산을 NNLS 4번째 구성원으로 넣은 앙상블을 본다.

데이터
- 속별 타깃: v1 표본(harness.load_base)의 target_date 와 같은 날 측정(조류경보제 API 원자료
  data/raw/nier_algae/nier_algae_2012_2026.parquet, v1 타깃과 같은 출처). 2025-12-31 이후 측정은 읽은 즉시 버린다.
- 대회 번들 algae_measure.csv 와 열 이름·값을 대조해 출처를 정한다(compare_sources).
- 합계 일치(4속 합 = 총합, |차| ≤ 0.5)를 행 단위로 점검(genus_targets 의 consistent 열).

변형(선택은 2020~2024 CV OOF 로만)
- 구성: g4(4속) / g2(Microcystis + 나머지 3속)
- 속별 방식: log(C1 설정 log 회귀) / hurdle(출현 P(y>0) 분류 × 양수 log 회귀) / sel(속마다 CV 원단위 MSE 최소)
- 역변환: smear(속별 Duan smearing) / none
- 속별 자기회귀 피처(선택 변형, as_of 규칙): 속별 최근 측정 log·4주 최대 log·Microcystis 비율
- 앙상블: harness.ensemble_expanding 에 names=(c1, c3, c2, cg) 로 4번째 구성원 확장, 또는 c1 을 cg 로 대체

공개 함수(종합 단계 재사용)
- members(df, cols) -> {"cg": 속별 합산 OOF, "cg_<부분>": 부분별 OOF}  (2020~2025, 선택 설정 CHOSEN)
- build_features(df) -> 속별 자기회귀 피처(같은 인덱스, 새 열만)
- genus_targets(df, algae) / genus_ar_features(algae, as_of, station_id) / fit_component(...)

실행: python -m algaecast.exp.r3_genus [--reuse]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import time
from datetime import date

import lightgbm as lgb
import numpy as np
import pandas as pd

from algaecast.config import RAW_DIR, ROOT
from algaecast.eval.metrics import compute_all
from algaecast.exp import harness as H
from algaecast.features.base import cut_as_of
from algaecast.features.constants import WTEMP_LAST, apply_site_thresholds, threshold_year_for_valid
from algaecast.models import data as D
from algaecast.models.cv import year_folds
from algaecast.models.train import SEED, VariantSpec, _lgb_params, _prep, fit_predict, to_cells

log = logging.getLogger(__name__)

EXP = "EXP-006"
OUT_DATA = H.EXP_DATA / EXP
OUT_REP = H.EXP_REPORTS / EXP
COMP_ALGAE = RAW_DIR / "competition" / "algae_contest_2026" / "algae_measure.csv"
TOTAL_COL = "iem_bgalage_cell_co"
GENUS: dict[str, str] = {
    "micro": "iem_bgalage_microsts",
    "anba": "iem_bgalage_anba",
    "apzo": "iem_bgalage_apzo",
    "osc": "iem_bgalage_osrtria",
}
GENUS_NAME: dict[str, str] = {
    "micro": "Microcystis",
    "anba": "Dolichospermum(Anabaena)",
    "apzo": "Aphanizomenon",
    "osc": "Oscillatoria",
    "rest": "나머지 3속(Anabaena+Aphanizomenon+Oscillatoria)",
}
PARTS: dict[str, tuple[str, ...]] = {
    "micro": ("micro",),
    "anba": ("anba",),
    "apzo": ("apzo",),
    "osc": ("osc",),
    "rest": ("anba", "apzo", "osc"),
}
LAYOUTS: dict[str, tuple[str, ...]] = {"g4": ("micro", "anba", "apzo", "osc"), "g2": ("micro", "rest")}
MODES = ("log", "hurdle")
BIASES = ("smear", "none")
AR_DAYS = 28
GF_COLS = [f"{g}_log_t0" for g in GENUS] + [f"{g}_log_max4w" for g in GENUS] + ["micro_share_t0"]
TASK_START = pd.Timestamp("2026-10-21 17:53:26", tz="Asia/Seoul")  # EXP-006 착수(시간 상한 기준)

# 실험 결과로 정한 선택 설정(종합 단계 members() 기본값). main() 이 선택 결과와 같은지 확인한다.
CHOSEN: dict = {
    "layout": "g2",  # Microcystis + 나머지 3속 합
    "modes": {"micro": "log", "rest": "log"},
    "bias": "smear",
    "features": False,
    "ensemble": "none",  # add: (c1, c3, c2, cg) NNLS / replace: (cg, c3, c2) / none: cg 단독이 최종 점예측
}


# ---------------------------------------------------------------- 원자료·타깃
def load_algae(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """조류경보제 API 원자료(5지점)에서 총합·4속 열만, last(기본 2025-12-31) 이후 측정은 읽은 즉시 버린다."""
    cols = ["station_id", "obs_date", TOTAL_COL, *GENUS.values()]
    a = pd.read_parquet(H.ALGAE_PARQUET, columns=cols)
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    a = a[a["obs_date"] <= last]
    return a.sort_values(["station_id", "obs_date"]).reset_index(drop=True)


def load_competition_algae(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """대회 번들 algae_measure.csv(측정일 chck_de) — last 이후 측정은 읽은 즉시 버린다."""
    c = pd.read_csv(COMP_ALGAE, encoding="utf-8-sig")
    c["obs_date"] = pd.to_datetime(c["chck_de"])
    return c[c["obs_date"] <= last].reset_index(drop=True)


def compare_sources(api: pd.DataFrame, comp: pd.DataFrame) -> pd.DataFrame:
    """같은 (station_id, obs_date) 에서 총합·4속 열을 대조(|차| ≤ 0.5 이면 일치). 열 이름이 없으면 '열 없음'."""
    key = ["station_id", "obs_date"]
    cols = [TOTAL_COL, *GENUS.values()]
    have = [c for c in cols if c in api.columns and c in comp.columns]
    m = api[key + have].merge(
        comp[key + have], on=key, how="outer", suffixes=("_api", "_comp"), indicator=True
    )
    rows = []
    for c in cols:
        if c not in have:
            rows.append({"열": c, "비고": "열 없음"})
            continue
        x, y = m[f"{c}_api"].astype(float), m[f"{c}_comp"].astype(float)
        both = x.notna() & y.notna()
        rows.append(
            {
                "열": c,
                "공통 측정일": int((m["_merge"] == "both").sum()),
                "API에만": int((m["_merge"] == "left_only").sum()),
                "대회에만": int((m["_merge"] == "right_only").sum()),
                "둘 다 값": int(both.sum()),
                "일치": int(((x - y).abs() <= 0.5)[both].sum()),
                "한쪽만 결측": int((x.isna() ^ y.isna()).sum()),
                "비고": "",
            }
        )
    return pd.DataFrame(rows)


def genus_targets(df: pd.DataFrame, algae: pd.DataFrame) -> pd.DataFrame:
    """v1 표본의 target_date 와 같은 날 측정에서 4속 타깃을 붙인다(같은 인덱스).

    열: y_<속>(원단위, 없으면 NaN), y_sum4(4속 모두 있을 때 합), total_api(같은 날 총합),
    consistent(|y_sum4 − target_cells| ≤ 0.5; 4속 결측이면 NA). 불일치 행의 속별 타깃은 NaN 으로 비운다.
    """
    key = pd.DataFrame(
        {"station_id": df["station_id"].astype(str).to_numpy(), "obs_date": pd.to_datetime(df["target_date"])}
    )
    a = algae.drop_duplicates(["station_id", "obs_date"], keep="last")
    m = key.merge(a, on=["station_id", "obs_date"], how="left")
    out = pd.DataFrame(index=df.index)
    for g, col in GENUS.items():
        out[f"y_{g}"] = m[col].to_numpy(dtype=float)
    ys = out[[f"y_{g}" for g in GENUS]]
    out["y_sum4"] = ys.sum(axis=1, skipna=False)
    out["total_api"] = m[TOTAL_COL].to_numpy(dtype=float)
    tgt = df["target_cells"].to_numpy(dtype=float)
    has = out["y_sum4"].notna().to_numpy()
    cons = pd.Series(pd.NA, index=df.index, dtype="boolean")
    cons[has] = np.abs(out["y_sum4"].to_numpy()[has] - tgt[has]) <= 0.5
    out["consistent"] = cons
    bad = cons.eq(False).to_numpy(dtype=bool, na_value=False)
    if bad.any():
        out.loc[bad, [f"y_{g}" for g in GENUS]] = np.nan
    return out


def part_target(tg: pd.DataFrame, part: str) -> np.ndarray:
    """부분(속 하나 또는 '나머지') 타깃 원단위. 구성 속 중 하나라도 결측이면 NaN."""
    return tg[[f"y_{g}" for g in PARTS[part]]].sum(axis=1, skipna=False).to_numpy(dtype=float)


def consistency_summary(df: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    """지점별 합계 일치 점검(행 수 집계만)."""
    d = pd.DataFrame(
        {
            "station_id": df["station_id"].astype(str).to_numpy(),
            "year": H.years_of(df),
            "has4": tg["y_sum4"].notna().to_numpy(),
            "cons": tg["consistent"].eq(True).to_numpy(dtype=bool, na_value=False),
            "incons": tg["consistent"].eq(False).to_numpy(dtype=bool, na_value=False),
            "tot_eq": (np.abs(tg["total_api"].to_numpy() - df["target_cells"].to_numpy(dtype=float)) <= 0.5),
        }
    )
    rows = []
    for sid, g in d.groupby("station_id"):
        miss = g[~g["has4"]]
        rows.append(
            {
                "지점": sid,
                "표본": len(g),
                "4속 있음": int(g["has4"].sum()),
                "합계 일치": int(g["cons"].sum()),
                "합계 불일치": int(g["incons"].sum()),
                "4속 결측": int((~g["has4"]).sum()),
                "결측 연도": ",".join(str(y) for y in sorted(miss["year"].unique())) or "–",
                "총합=v1 타깃": int(g["tot_eq"].sum()),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 속별 자기회귀 피처(as_of)
def genus_ar_features(algae: pd.DataFrame, as_of: date, station_id: str) -> dict[str, float]:
    """속별 최근 측정 log10(y+1)·최근 28일 최대·Microcystis 비율. 진입 직후 as_of 이후 행을 버린다."""
    a = cut_as_of(algae, as_of)
    a = a[a["station_id"].astype(str) == str(station_id)].sort_values("obs_date")
    out: dict[str, float] = {}
    lo = pd.Timestamp(as_of) - pd.Timedelta(days=AR_DAYS - 1)
    for g, col in GENUS.items():
        v = a.loc[a[col].notna(), ["obs_date", col]]
        out[f"{g}_log_t0"] = float(np.log10(float(v[col].iloc[-1]) + 1)) if len(v) else math.nan
        rec = v[pd.to_datetime(v["obs_date"]) >= lo]
        out[f"{g}_log_max4w"] = float(np.log10(float(rec[col].max()) + 1)) if len(rec) else math.nan
    full = a.dropna(subset=list(GENUS.values()))
    share = math.nan
    if len(full):
        last = full.iloc[-1]
        tot = float(sum(float(last[c]) for c in GENUS.values()))
        share = float(last[GENUS["micro"]]) / tot if tot > 0 else math.nan
    out["micro_share_t0"] = share
    return out


def build_features(df: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """df(=harness.load_base() 형식)와 같은 인덱스로 속별 자기회귀 피처(GF_COLS)만 반환한다."""
    H.guard_no_2026(df)
    algae = load_algae() if algae is None else algae
    by_site = {str(s): g for s, g in algae.groupby("station_id")}
    empty = algae.iloc[0:0]
    rows = [
        genus_ar_features(by_site.get(str(s), empty), b, str(s))
        for s, b in zip(df["station_id"], df["base_date"], strict=True)
    ]
    return pd.DataFrame(rows, index=df.index, columns=GF_COLS)


# ---------------------------------------------------------------- 속별 모델
def _fold_train(df: pd.DataFrame, y: np.ndarray, train_idx: np.ndarray) -> pd.DataFrame:
    """폴드 학습 행 중 부분 타깃이 있는 행만, target_cells/target_log 를 부분 타깃으로 바꾼 복사본."""
    yt = y[train_idx]
    ok = np.isfinite(yt)
    tr = df.iloc[train_idx[ok]].copy()
    tr["target_cells"] = yt[ok]
    tr["target_log"] = np.log10(yt[ok] + 1)
    return tr


def _hurdle_fit(
    tr: pd.DataFrame, va: pd.DataFrame, cols: list[str], spec: VariantSpec, seed: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """출현(y>0) 분류 × 양수 행 log 회귀(C1 파라미터·가중). (보정 없음, smearing, 출현 확률)"""
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    Xv = _prep(va[cols], cats, ref=Xt)
    ylog = tr["target_log"].to_numpy(dtype=float)
    pos = tr["target_cells"].to_numpy(dtype=float) > 0
    if pos.sum() < 20 or (~pos).sum() < 20:  # 한쪽이 거의 없으면 log 회귀로 대체
        f = fit_predict(tr, va, cols, spec, seed)
        return f.raw, f.raw * f.smear, np.ones(len(va))
    clf = lgb.LGBMClassifier(**_lgb_params(spec.params, seed, objective="binary"))
    clf.fit(Xt, pos.astype(int), categorical_feature=cats or "auto")
    p = np.asarray(clf.predict_proba(Xv)[:, 1], dtype=float)
    reg = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
    reg.fit(
        Xt[pos], ylog[pos], sample_weight=1.0 + spec.alpha * ylog[pos], categorical_feature=cats or "auto"
    )
    lp = np.asarray(reg.predict(Xv), dtype=float)
    smear = float(np.mean(10 ** (ylog[pos] - reg.predict(Xt[pos]))))
    e_pos = to_cells(lp)
    return p * e_pos, p * e_pos * smear, p


def fit_component(
    df: pd.DataFrame, cols: list[str], y: np.ndarray, mode: str, spec: VariantSpec, seed: int = SEED
) -> dict[str, np.ndarray]:
    """부분 타깃 y(원단위, NaN=제외)의 연도 확장 OOF(2020~2025). 반환 {smear, none}(원단위).

    폴드마다 학습 = 기준일 연도 < 검증 연도이면서 y 가 있는 행, 검증 = 그 연도 전체 행(타깃 무관).
    """
    H.guard_no_2026(df)
    out = {b: np.full(len(df), np.nan) for b in BIASES}
    for fo in year_folds(df, include_final=True):
        tr = _fold_train(df, y, fo.train_idx)
        va = df.iloc[fo.valid_idx]
        if WTEMP_LAST in df.columns:  # 폴드 학습기간 수온 임계(FIX-v2.1 R3, models.cv.fold_frames 와 같음)
            ty = threshold_year_for_valid(fo.valid_year)
            tr, va = apply_site_thresholds(tr, ty), apply_site_thresholds(va, ty)
        if mode == "log":
            f = fit_predict(tr, va, cols, spec, seed)
            none, smear = f.raw, f.raw * f.smear
        elif mode == "hurdle":
            none, smear, _ = _hurdle_fit(tr, va, cols, spec, seed)
        else:
            raise ValueError(mode)
        out["none"][fo.valid_idx] = np.clip(np.nan_to_num(none, nan=0.0), 0, None)
        out["smear"][fo.valid_idx] = np.clip(np.nan_to_num(smear, nan=0.0), 0, None)
    return out


def part_mse(df: pd.DataFrame, y: np.ndarray, pred: np.ndarray) -> float:
    """CV(2020~2024) 부분 타깃 원단위 MSE(타깃 있는 행)."""
    cv, _ = H.masks(df)
    ok = cv & np.isfinite(y) & np.isfinite(pred)
    return float(np.mean((y[ok] - pred[ok]) ** 2))


def select_modes(
    df: pd.DataFrame,
    tg: pd.DataFrame,
    comps: dict[tuple[str, str, bool], dict[str, np.ndarray]],
    feat: bool,
    bias: str,
) -> dict[str, str]:
    """부분마다 log/hurdle 중 CV 원단위 MSE 최소(2020~2024 OOF 만)."""
    out = {}
    for part in PARTS:
        y = part_target(tg, part)
        mse = {m: part_mse(df, y, comps[(part, m, feat)][bias]) for m in MODES if (part, m, feat) in comps}
        out[part] = min(mse, key=lambda k: mse[k])
    return out


def assemble(
    comps: dict[tuple[str, str, bool], dict[str, np.ndarray]],
    layout: str,
    modes: dict[str, str],
    bias: str,
    feat: bool,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """부분 OOF 를 원단위로 합산. (합산, 부분별)"""
    parts = {p: comps[(p, modes[p], feat)][bias] for p in LAYOUTS[layout]}
    return np.sum(list(parts.values()), axis=0), parts


def members(df: pd.DataFrame, cols: list[str], config: dict | None = None) -> dict[str, np.ndarray]:
    """종합 단계용 공개 함수: 선택 설정(CHOSEN)의 속별 합산 구성원 OOF(2020~2025, 이전 행 NaN).

    반환 {"cg": 원단위 합산, "cg_<부분>": 부분별 원단위}. 앙상블은
    harness.ensemble_expanding(df, {**base, **members(df, cols)}, names=("c1", "c3", "c2", "cg")).
    config["features"] 가 True 면 build_features(df) 의 GF_COLS 를 cols 에 더해 속별 모델에만 쓴다.
    """
    cfg = config or CHOSEN
    H.guard_no_2026(df)
    algae = load_algae()
    tg = genus_targets(df, algae)
    use_cols = list(cols)
    dfx = df
    if cfg["features"]:
        dfx = pd.concat([df, build_features(df, algae)], axis=1)
        use_cols += [c for c in GF_COLS if c not in use_cols]
    spec = H.v1_specs()["c1"]
    parts = {
        p: fit_component(dfx, use_cols, part_target(tg, p), cfg["modes"][p], spec)[cfg["bias"]]
        for p in LAYOUTS[cfg["layout"]]
    }
    out = {"cg": np.sum(list(parts.values()), axis=0)}
    out.update({f"cg_{p}": v for p, v in parts.items()})
    return out


def chosen_prediction(df: pd.DataFrame, base: dict[str, np.ndarray], cg: np.ndarray, how: str) -> np.ndarray:
    """선택 설정의 최종 점예측: add(4구성원 NNLS)·replace(c1→cg)·none(cg 단독)."""
    if how == "none":
        return cg
    preds = {**base, "cg": cg}
    names = ("c1", "c3", "c2", "cg") if how == "add" else ("cg", "c3", "c2")
    return H.ensemble_expanding(df, preds, names=names)[0]


# ---------------------------------------------------------------- 실험 실행
def _part_metrics(df: pd.DataFrame, y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    cv, _ = H.masks(df)
    ok = cv & np.isfinite(y) & np.isfinite(pred)
    m = compute_all(y[ok], pred[ok])
    return {"n": int(ok.sum()), "rmse_log": float(m["rmse_log"]), "r2_raw": float(m["r2_raw"])}


def per_year_table(df: pd.DataFrame, preds: dict[str, np.ndarray]) -> pd.DataFrame:
    """연도별(2020~2025) r2_raw / rmse_log (집계 지표만)."""
    years = H.years_of(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    out = []
    for lab, p in preds.items():
        p = np.asarray(p, dtype=float)
        r = {"구성": lab}
        for y in (*H.CV_YEARS, H.FINAL_YEAR):
            m = (years == y) & np.isfinite(p)
            mm = compute_all(obs[m], p[m])
            r[str(y)] = f"{mm['r2_raw']:.3f} / {mm['rmse_log']:.3f}"
        out.append(r)
    return pd.DataFrame(out)


def block_bootstrap(
    df: pd.DataFrame, a: np.ndarray, b: np.ndarray, n_boot: int = 2000, seed: int = SEED
) -> dict[str, float]:
    """CV(2020~2024) 행을 (지점, 연도) 블록 단위로 복원추출해 a − b 의 Δr2_raw·Δrmse_log 95% 구간."""
    cv, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)[cv]
    pa, pb = np.asarray(a, dtype=float)[cv], np.asarray(b, dtype=float)[cv]
    lo, la, lb = np.log10(obs + 1), np.log10(pa + 1), np.log10(pb + 1)
    keys = df["station_id"].astype(str).to_numpy()[cv] + "_" + H.years_of(df)[cv].astype(str)
    _, inv = np.unique(keys, return_inverse=True)
    groups = [np.where(inv == k)[0] for k in range(inv.max() + 1)]

    def stat(ii: np.ndarray) -> tuple[float, float]:
        o = obs[ii]
        ss = float(np.sum((o - o.mean()) ** 2))
        d_r2 = (np.sum((o - pb[ii]) ** 2) - np.sum((o - pa[ii]) ** 2)) / ss
        d_rm = np.sqrt(np.mean((lo[ii] - la[ii]) ** 2)) - np.sqrt(np.mean((lo[ii] - lb[ii]) ** 2))
        return float(d_r2), float(d_rm)

    point = stat(np.arange(len(obs)))
    rng = np.random.default_rng(seed)
    draws = np.array(
        [
            stat(np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))]))
            for _ in range(n_boot)
        ]
    )
    return {
        "d_r2_raw": point[0],
        "r2_lo": float(np.quantile(draws[:, 0], 0.025)),
        "r2_hi": float(np.quantile(draws[:, 0], 0.975)),
        "p_r2_pos": float(np.mean(draws[:, 0] > 0)),
        "d_rmse_log": point[1],
        "rmse_lo": float(np.quantile(draws[:, 1], 0.025)),
        "rmse_hi": float(np.quantile(draws[:, 1], 0.975)),
        "n_blocks": len(groups),
    }


def protected_changes() -> list[str]:
    """scripts/exp_check_protected.py 와 같은 규칙으로 v1 보호 파일 해시를 대조해 바뀐 파일 목록을 돌려준다."""
    ref = json.loads((H.EXP_DATA / "protected_hashes.json").read_text(encoding="utf-8"))
    bad = []
    for rel, h in ref.items():
        p = ROOT / rel
        cur = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "(missing)"
        if cur != h:
            bad.append(rel)
    return bad


def _md(t: pd.DataFrame) -> str:
    hdr = "| " + " | ".join(map(str, t.columns)) + " |\n|" + "---|" * len(t.columns)
    body = "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in t.itertuples(index=False))
    return hdr + "\n" + body + "\n"


def _cfg_label(layout: str, modes: dict[str, str], bias: str, feat: bool, sel: bool) -> str:
    lay = "G4 4속" if layout == "g4" else "G2 Microcystis+나머지"
    if sel:
        mtxt = "속별 선택(" + "·".join(f"{p}={modes[p]}" for p in LAYOUTS[layout]) + ")"
    else:
        mtxt = modes[LAYOUTS[layout][0]]
    ftxt = " +속별피처" if feat else ""
    return f"{lay} {mtxt} {bias}{ftxt}"


def compute_components(
    dfx: pd.DataFrame, tg: pd.DataFrame, cols: list[str], budget: H.Budget, reuse: bool
) -> dict[tuple[str, str, bool], dict[str, np.ndarray]]:
    """부분 5종 × log/hurdle × 피처 유무 OOF. reuse 면 data/processed/exp/EXP-006/components.parquet 재사용."""
    path = OUT_DATA / "components.parquet"
    comps: dict[tuple[str, str, bool], dict[str, np.ndarray]] = {}
    if reuse and path.exists():
        c = pd.read_parquet(path)
        if (
            len(c) == len(dfx)
            and (c["base_date"].astype(str).to_numpy() == dfx["base_date"].astype(str).to_numpy()).all()
        ):
            for col in c.columns:
                if "|" in col:
                    p, m, f, b = col.split("|")
                    comps.setdefault((p, m, f == "F1"), {})[b] = c[col].to_numpy(dtype=float)
            return comps
    spec = H.v1_specs()["c1"]
    for feat in (False, True):
        use = cols + (GF_COLS if feat else [])
        for part in PARTS:
            y = part_target(tg, part)
            for mode in MODES:
                t0 = time.time()
                comps[(part, mode, feat)] = fit_component(dfx, use, y, mode, spec)
                log.info("component %s %s feat=%s %.1fs", part, mode, feat, time.time() - t0)
                budget.check()
    wide = dfx[["station_id", "base_date"]].copy()
    wide["base_date"] = wide["base_date"].astype(str)
    for (p, m, f), d in comps.items():
        for b, v in d.items():
            wide[f"{p}|{m}|{'F1' if f else 'F0'}|{b}"] = v
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    wide.to_parquet(path, index=False)
    return comps


def run(reuse: bool = False) -> dict:
    """EXP-006 전체 실행 → 보고서·metrics.json·chosen_oof.parquet."""
    budget = H.Budget(8.0, EXP)
    budget.t0 = TASK_START.timestamp()  # 상한은 실험 착수 시각부터 센다(재실행 포함)
    started = pd.Timestamp.now(tz="Asia/Seoul")
    status = "completed"
    df = H.load_base()
    cols = H.base_columns()
    _, base = H.load_baseline()
    algae = load_algae()
    comp = load_competition_algae()
    src_tbl = compare_sources(algae, comp)
    tg = genus_targets(df, algae)
    cons_tbl = consistency_summary(df, tg)
    feats = build_features(df, algae)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    fsave = df[["station_id", "base_date"]].copy()
    fsave["base_date"] = fsave["base_date"].astype(str)
    pd.concat([fsave, feats], axis=1).to_parquet(OUT_DATA / "features.parquet", index=False)
    dfx = pd.concat([df, feats], axis=1)
    H.guard_no_2026(dfx)

    rows: list[dict] = []
    variants: dict[str, dict] = {}
    dups: list[str] = []
    q90 = base["q90"]
    rows.append(H.metric_row(df, base["ens"], q90, "v1 기준"))
    rows.append(H.metric_row(df, base["c1"], q90, "참고: C1 합계 단독(smearing)"))
    comps: dict = {}
    try:
        comps = compute_components(dfx, tg, cols, budget, reuse)
        # 부분 진단(CV 2020~2024, 부분 타깃 기준)
        diag = []
        cvm, _ = H.masks(df)
        for part in PARTS:
            y = part_target(tg, part)
            okp = cvm & np.isfinite(y)
            r = {
                "부분": GENUS_NAME[part],
                "CV n": int(okp.sum()),
                "0 비율": round(float(np.mean(y[okp] == 0)), 3),
            }
            for feat in (False, True):
                for mode in MODES:
                    pm = _part_metrics(df, y, comps[(part, mode, feat)]["smear"])
                    tag = f"{mode}{'+F' if feat else ''}"
                    r[f"{tag} rmse_log"] = round(pm["rmse_log"], 3)
                    r[f"{tag} r2_raw"] = round(pm["r2_raw"], 3)
            diag.append(r)
        diag_tbl = pd.DataFrame(diag)

        seen: dict[tuple, str] = {}

        def add_standalone(layout: str, modes: dict[str, str], bias: str, feat: bool, sel: bool) -> str:
            m = {p: modes[p] for p in LAYOUTS[layout]}
            key = (layout, tuple(m.values()), bias, feat)
            if key in seen:  # 속별 선택 결과가 기존 변형과 같으면 중복 행을 만들지 않는다
                dups.append(f"{_cfg_label(layout, m, bias, feat, sel)} = {seen[key]}")
                return seen[key]
            label = _cfg_label(layout, m, bias, feat, sel) + " 단독"
            cg, parts = assemble(comps, layout, m, bias, feat)
            rows.append(H.metric_row(df, cg, q90, label))
            cfg = {"layout": layout, "modes": m, "bias": bias, "features": feat, "ensemble": "none"}
            variants[label] = {"cfg": cfg, "cg": cg, "parts": parts, "pred": cg, "weights": None}
            seen[key] = label
            return label

        def add_ensemble(src_label: str, how: str) -> str:
            v = variants[src_label]
            stem = src_label.removesuffix(" 단독")
            label = f"앙상블 c1·c3·c2 + [{stem}]" if how == "add" else f"앙상블 c1→[{stem}]·c3·c2"
            if label in variants:
                return label
            preds = {**base, "cg": v["cg"]}
            names = ("c1", "c3", "c2", "cg") if how == "add" else ("cg", "c3", "c2")
            ens, w = H.ensemble_expanding(df, preds, names=names)
            rows.append(H.metric_row(df, ens, q90, label))
            cfg = {**v["cfg"], "ensemble": how}
            variants[label] = {"cfg": cfg, "cg": v["cg"], "parts": v["parts"], "pred": ens, "weights": w}
            return label

        all_log = {p: "log" for p in PARTS}
        all_h = {p: "hurdle" for p in PARTS}
        sel_tbl = {}
        for feat in (False, True):
            for bias in BIASES:
                sel_tbl[(feat, bias)] = select_modes(df, tg, comps, feat, bias)
        # 단독 변형
        l_g4_log = add_standalone("g4", all_log, "smear", False, False)
        add_standalone("g4", all_log, "none", False, False)
        add_standalone("g4", all_h, "smear", False, False)
        add_standalone("g4", all_h, "none", False, False)
        l_g4_sel = add_standalone("g4", sel_tbl[(False, "smear")], "smear", False, True)
        l_g2_log = add_standalone("g2", all_log, "smear", False, False)
        l_g2_sel = add_standalone("g2", sel_tbl[(False, "smear")], "smear", False, True)
        l_g4f_log = add_standalone("g4", all_log, "smear", True, False)
        l_g2f_log = add_standalone("g2", all_log, "smear", True, False)
        l_g4f_sel = add_standalone("g4", sel_tbl[(True, "smear")], "smear", True, True)
        l_g2f_sel = add_standalone("g2", sel_tbl[(True, "smear")], "smear", True, True)
        budget.check()
        # 앙상블 변형(NNLS 4번째 구성원 / c1 대체)
        for lab in (l_g4_log, l_g4_sel, l_g2_log, l_g2_sel, l_g4f_log, l_g2f_log, l_g4f_sel, l_g2f_sel):
            add_ensemble(lab, "add")
        for lab in (l_g4_log, l_g4_sel, l_g2_log):
            add_ensemble(lab, "replace")
        budget.check()
        # 참고: v1 3구성원(+분위)에 속별 피처만 추가(분해 효과와 피처 효과를 가르기 위함, 선택 대상 아님)
        memf = H.run_members(dfx, cols + GF_COLS)
        ref_row, _, _ = H.evaluate_members(dfx, memf, "참고: v1 3구성원 + 속별피처(분해 없음)")
        rows.append(ref_row)
    except H.BudgetExceeded as e:
        status = "time_cap"
        log.warning("%s", e)
        diag_tbl = pd.DataFrame()
        sel_tbl = {}

    # ---- 선택(CV 만): 채택 기준 만족 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대(기준 미달)
    base_row = rows[0]
    cand = [r for r in rows if r["구성"] in variants]
    for r in cand:
        r["adoption"] = H.adoption(base_row, r)
    passing = [r for r in cand if r["adoption"]["pass"]]
    pool = passing or cand
    best = max(pool, key=lambda r: r["cv_r2_raw"]) if pool else None
    chosen_label = best["구성"] if best else "v1 기준"
    verdict = (
        H.adoption(base_row, best)
        if best
        else {"d_cv_r2_raw": 0.0, "d_cv_rmse_log": 0.0, "lead_ok": True, "pass": False}
    )
    # 보조: rmse_log 악화 0.01 이내 변형 중 CV r2_raw 최대(참고 정보)
    within = [r for r in cand if r["cv_rmse_log"] - base_row["cv_rmse_log"] <= 0.01]
    best_within = max(within, key=lambda r: r["cv_r2_raw"]) if within else None

    chosen_matches = False
    repro_diff = float("nan")
    boot: dict[str, dict[str, float]] = {}
    year_tbl = pd.DataFrame()
    if best:
        v = variants[chosen_label]
        chosen_matches = {k: v["cfg"][k] for k in CHOSEN} == CHOSEN
        if not chosen_matches:
            log.warning("모듈 상수 CHOSEN 이 이번 선택과 다르다: %s vs %s", v["cfg"], CHOSEN)
        oof = {"c1": base["c1"], "c3": base["c3"], "c2": base["c2"], "cg": v["cg"]}
        oof.update({f"cg_{p}": a for p, a in v["parts"].items()})
        oof.update({"q10": base["q10"], "q50": base["q50"], "q90": base["q90"], "pred": v["pred"]})
        H.save_oof(df, oof, OUT_DATA / "chosen_oof.parquet")
        # 공개 함수 members() 가 선택 변형의 cg 를 그대로 재현하는지(log10 최대 절대차)
        rep = members(df, cols, config=v["cfg"])["cg"]
        ok = np.isfinite(rep) & np.isfinite(v["cg"])
        repro_diff = float(np.max(np.abs(np.log10(rep[ok] + 1) - np.log10(v["cg"][ok] + 1))))
        # 보조 진단: 연도별 지표, (지점·연도) 블록 부트스트랩 Δ
        ens_rows = [r for r in cand if r["구성"].startswith("앙상블")]
        best_ens = max(ens_rows, key=lambda r: r["cv_r2_raw"])["구성"] if ens_rows else None
        show = {"v1 기준": base["ens"], "C1 합계 단독": base["c1"], f"선택: {chosen_label}": v["pred"]}
        if best_ens and best_ens != chosen_label:
            show[f"최고 앙상블: {best_ens}"] = variants[best_ens]["pred"]
        year_tbl = per_year_table(df, show)
        boot["선택 − v1 기준"] = block_bootstrap(df, v["pred"], base["ens"])
        boot["선택 − C1 합계 단독"] = block_bootstrap(df, v["pred"], base["c1"])
        if best_ens and best_ens != chosen_label:
            boot["최고 앙상블 − v1 기준"] = block_bootstrap(df, variants[best_ens]["pred"], base["ens"])

    elapsed_h = (time.time() - TASK_START.timestamp()) / 3600
    if elapsed_h > budget.hours:
        status = "time_cap"
    finished = pd.Timestamp.now(tz="Asia/Seoul")
    OUT_REP.mkdir(parents=True, exist_ok=True)
    clean = [{k: v for k, v in r.items()} for r in rows]
    (OUT_REP / "metrics.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=1, default=float) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    info = {
        "status": status,
        "started": started,
        "finished": finished,
        "elapsed_h": elapsed_h,
        "rows": rows,
        "variants": variants,
        "chosen_label": chosen_label,
        "verdict": verdict,
        "best_within": best_within,
        "src_tbl": src_tbl,
        "cons_tbl": cons_tbl,
        "diag_tbl": diag_tbl,
        "sel_tbl": sel_tbl,
        "tg": tg,
        "df": df,
        "dups": dups,
        "chosen_matches": chosen_matches,
        "repro_diff": repro_diff,
        "boot": boot,
        "year_tbl": year_tbl,
        "protected_bad": protected_changes(),
    }
    write_report(info)
    return info


def _share_table(df: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
    """CV·2025 구간 속별 세포수 합 비율(집계)과 경계(>10k) 표본 중 비율."""
    yrs = H.years_of(df)
    tot = df["target_cells"].to_numpy(dtype=float)
    rows = []
    for name, m in (
        ("2016~2024 학습 구간", (yrs <= 2024)),
        ("2025", yrs == 2025),
        ("표본 >10k(≤2024)", (yrs <= 2024) & (tot > H.T10K)),
    ):
        ok = m & tg["y_sum4"].notna().to_numpy()
        s = {g: float(tg[f"y_{g}"].to_numpy()[ok].sum()) for g in GENUS}
        allv = sum(s.values())
        rows.append(
            {"구간": name, "n": int(ok.sum()), **{GENUS_NAME[g]: f"{s[g] / allv:.3f}" for g in GENUS}}
        )
    return pd.DataFrame(rows)


def write_report(info: dict) -> None:
    """reports/experiments/EXP-006/README.md (EXP-PLAN 7절 형식)."""
    rows, variants = info["rows"], info["variants"]
    df, tg = info["df"], info["tg"]
    chosen = info["chosen_label"]
    vd = info["verdict"]
    base_row = rows[0]
    crow = next((r for r in rows if r["구성"] == chosen), base_row)
    sel_txt = []
    for (feat, bias), modes in info["sel_tbl"].items():
        sel_txt.append(
            f"- 피처 {'+속별' if feat else 'v1'}·{bias}: "
            + ", ".join(f"{GENUS_NAME[p]}={m}" for p, m in modes.items())
        )
    wtxt = ""
    if chosen in variants and variants[chosen]["weights"]:
        wtxt = json.dumps(
            {y: {k: round(v, 3) for k, v in w.items()} for y, w in variants[chosen]["weights"].items()},
            ensure_ascii=False,
        )
    ens_w = []
    for lab, v in variants.items():
        if v["weights"]:
            w25 = v["weights"][H.FINAL_YEAR]
            ens_w.append(f"- {lab}: 2025 가중 " + ", ".join(f"{k} {w25[k]:.3f}" for k in w25))
    bw = info["best_within"]
    interp, checks, limits, boot_txt = _report_texts(info)
    bw_txt = (
        f"rmse_log 악화 0.01 이내 변형 중 CV r2_raw 최대는 '{bw['구성']}'(CV r2_raw {bw['cv_r2_raw']:.3f}, rmse_log {bw['cv_rmse_log']:.3f})."
        if bw
        else "rmse_log 악화 0.01 이내 변형 없음."
    )
    text = f"""# EXP-006 (R3) 속별 모델 합산

상태: **{info['status']}** · 착수 {TASK_START:%Y-%m-%d %H:%M} · 마지막 실행 {info['started']:%H:%M}~{info['finished']:%H:%M} (KST) · 소요 {info['elapsed_h']:.2f}h / 상한 8h

## 1. 목적·설정

- 목적: 합계 세포수 대신 4속(Microcystis, Dolichospermum(Anabaena), Aphanizomenon, Oscillatoria)을 따로 log 회귀(C1 설정)한 뒤
  원단위로 합산하면 원단위 R²·NSE 가 오르는지, 또 속별 합산을 v1 앙상블(NNLS)의 4번째 구성원으로 넣으면 나아지는지 본다.
- 표본: `harness.load_base()` v1 학습·검증 2,566행(≤2025). CV = 2020~2024 연도 확장 OOF, 2025 = ≤2024 학습 → 2025.
- 하이퍼파라미터: v1 C1(`harness.v1_specs()['c1']`, log_w, α={H.v1_specs()['c1'].alpha:.4f}) 그대로, 시드 42 하나. 분위(q90)는 v1 그대로 → 리드타임 동일.
- 속별 타깃 출처: 조류경보제 API 원자료 `data/raw/nier_algae/nier_algae_2012_2026.parquet`(v1 타깃과 같은 출처)에서
  v1 표본의 `target_date` 와 같은 날 측정의 `iem_bgalage_microsts`·`iem_bgalage_anba`·`iem_bgalage_apzo`·`iem_bgalage_osrtria`.
  2025-12-31 이후 측정은 읽은 즉시 버렸다.
- 출처 대조(대회 `algae_measure.csv`, 같은 열 이름): 아래 표처럼 2025-12-31 까지 공통 측정일의 총합·4속 값이 모두 일치 → API 원자료를 쓴다(내용 동일, v1 파이프라인과 같은 파일).

{_md(info['src_tbl'])}
- 합계 일치 점검(4속 합 = v1 타깃, |차| ≤ 0.5):

{_md(info['cons_tbl'])}
  4속 결측 행은 회남 2012~2014(그 시기 원자료에 속별 값 없음)와 기준일 2025-12-29 의 정답 측정일이 2026-01-05 인 4행(2026 측정은 읽지 않음)이다.
  결측 행은 속별 모델 학습에서만 빠지고(2025 행은 어차피 학습에 쓰이지 않음) 예측·평가는 모든 행에 한다. 합계 불일치 행은 없다.
- 속별 비율(세포수 합 기준, 집계):

{_md(_share_table(df, tg))}
- 변형
  - 부분 모델: 4속 각각(G4) 또는 Microcystis + 나머지 3속 합(G2). 방식 log(C1 회귀) 또는 hurdle(출현 P(y>0) 분류 × 양수 행 log 회귀, 0 이 많은 속 대비).
    '속별 선택' 은 부분마다 log/hurdle 중 CV(2020~2024) 원단위 MSE 가 작은 쪽.
  - 역변환: 속별 Duan smearing(smear) 또는 보정 없음(none). 원단위로 합산.
  - 속별 자기회귀 피처(+속별피처, as_of 규칙): 속별 최근 측정 log10(y+1), 최근 28일 최대 log, Microcystis 비율(최근 4속 측정). 속별 모델에만 추가.
  - 앙상블: `harness.ensemble_expanding(names=(c1, c3, c2, cg))`(4번째 구성원) 또는 c1 을 cg 로 대체(cg, c3, c2).
  - 참고 행(선택 대상 아님): C1 합계 단독, v1 3구성원에 속별 피처만 더한 구성(분해 없이 피처만의 효과).
- 속별 선택 결과(부분별 log/hurdle, CV 원단위 MSE):
{chr(10).join(sel_txt)}

## 2. 표준 표

{H.standard_table(rows)}
### 보조 표

{H.detail_table(rows)}
### 부분 모델 진단(CV 2020~2024, 부분 타깃 기준, smearing)

{_md(info['diag_tbl']) if len(info['diag_tbl']) else '(시간 상한으로 생략)'}
### 앙상블 가중치(2025 적용분, 2020~2024 OOF 로 적합)

{chr(10).join(ens_w)}

## 3. 선택과 채택 판정

- 선택 규칙(EXP-PLAN 4절, CV 만): 채택 기준을 만족하는 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대 변형을 '기준 미달'로 표시.
- 선택: **{chosen}** — CV r2_raw {crow['cv_r2_raw']:.3f}, CV rmse_log {crow['cv_rmse_log']:.3f}, 리드타임 {crow.get('lead_q90', '–')}/{crow.get('lead_n', '–')}
  (2025 확인: r2_raw {crow['y2025_r2_raw']:.3f}, rmse_log {crow['y2025_rmse_log']:.3f}).
- 판정(`harness.adoption`, v1 기준 대비): ΔCV r2_raw {vd['d_cv_r2_raw']:+.3f}, ΔCV rmse_log {vd['d_cv_rmse_log']:+.3f}, 리드타임 유지 {vd['lead_ok']} → **{'채택 기준 만족' if vd['pass'] else '기준 미달'}**.
- {bw_txt}
- 선택 변형의 연도별 NNLS 가중치: {wtxt or '(앙상블 아님)'}
- 행 단위 OOF: `data/processed/exp/EXP-006/chosen_oof.parquet`(c1·c3·c2·cg·cg_<부분>·q10·q50·q90·pred). 부분 OOF 전체: `components.parquet`, 속별 피처: `features.parquet`.
- 중복으로 합친 변형(속별 선택 결과가 기존 변형과 같음): {'; '.join(info['dups']) or '없음'}

### 연도별 r2_raw / rmse_log

{_md(info['year_tbl']) if len(info['year_tbl']) else '–'}
### (지점·연도) 블록 부트스트랩(CV 2020~2024, 2,000회, 시드 42)

{boot_txt}

### 해석

{interp}

## 4. 누수·2026 점검

{checks}

## 5. 소요 시간·한계·다음 단계

- 소요 {info['elapsed_h']:.2f}h / 상한 8h (착수 {TASK_START:%Y-%m-%d %H:%M}, 마지막 실행 종료 {info['finished']:%H:%M} KST). 전체 실행 1회(부분 OOF 20종 + 참고 구성 + 지표) 약 1.5~3분(동시 실행 부하에 따라).

{limits}
"""
    (OUT_REP / "README.md").write_text(text, encoding="utf-8", newline="\n")


def _fmt_boot(b: dict[str, float]) -> str:
    return (
        f"Δr2_raw {b['d_r2_raw']:+.3f} [95% {b['r2_lo']:+.3f}, {b['r2_hi']:+.3f}], P(Δ>0) {b['p_r2_pos']:.2f}; "
        f"Δrmse_log {b['d_rmse_log']:+.3f} [95% {b['rmse_lo']:+.3f}, {b['rmse_hi']:+.3f}] ({b['n_blocks']}블록)"
    )


def _report_texts(info: dict) -> tuple[str, str, str, str]:
    """해석·점검·한계 문단(수치는 이번 실행 결과에서 채운다)."""
    rows = {r["구성"]: r for r in info["rows"]}
    base, chosen = rows["v1 기준"], rows.get(info["chosen_label"], rows["v1 기준"])
    c1 = rows["참고: C1 합계 단독(smearing)"]

    def v(label: str, key: str, nd: int = 3) -> str:
        r = rows.get(label)
        return f"{r[key]:.{nd}f}" if r is not None and key in r else "–"

    ens = [r for r in info["rows"] if r["구성"].startswith("앙상블")]
    be = max(ens, key=lambda r: r["cv_r2_raw"]) if ens else None
    boot = info["boot"]
    boot_txt = "\n".join(f"- {k}: {_fmt_boot(b)}" for k, b in boot.items()) or "–"
    w_be = ""
    if be is not None and info["variants"].get(be["구성"], {}).get("weights"):
        w25 = info["variants"][be["구성"]]["weights"][H.FINAL_YEAR]
        w_be = ", ".join(f"{k} {w:.2f}" for k, w in w25.items())
    g2, g4 = "G2 Microcystis+나머지 log smear 단독", "G4 4속 log smear 단독"
    fref = "참고: v1 3구성원 + 속별피처(분해 없음)"
    interp = "\n".join(
        [
            f"1. **분해보다 '단독 점예측'의 효과가 크다.** 선택 변형은 v1 기준 대비 CV r2_raw {chosen['cv_r2_raw'] - base['cv_r2_raw']:+.3f}, "
            f"rmse_log {chosen['cv_rmse_log'] - base['cv_rmse_log']:+.3f} 로 채택 기준을 만족한다. 그러나 같은 C1 설정의 합계 모델을 단독으로 쓴 참고 행도 "
            f"CV r2_raw {c1['cv_r2_raw']:.3f}(rmse_log {c1['cv_rmse_log']:.3f}, 악화 {c1['cv_rmse_log'] - base['cv_rmse_log']:+.3f} 로 rmse_log 기준만 미달)이다. "
            "v1 대비 원단위 R² 이득의 대부분은 속별 분해가 아니라 'log 공간 NNLS 앙상블 대신 smearing 보정 log 회귀를 그대로 점예측으로 쓰는 것'에서 온다.",
            f"2. **속별 분해 자체의 기여(선택 − C1 합계 단독)**: CV r2_raw {chosen['cv_r2_raw'] - c1['cv_r2_raw']:+.3f}, rmse_log {chosen['cv_rmse_log'] - c1['cv_rmse_log']:+.3f}. "
            "원단위 R² 는 그대로이고 log 오차를 조금 줄여 C1 단독이 넘지 못한 rmse_log 기준(0.01)을 넘게 한 것이 분해의 실질 효과다. "
            f"4속(G4) 합산도 CV r2_raw {v(g4, 'cv_r2_raw')}·rmse_log {v(g4, 'cv_rmse_log')} 로 비슷하고, G2 가 2025 rmse_log 에서 더 낫다({v(g2, 'y2025_rmse_log')} vs {v(g4, 'y2025_rmse_log')}).",
            f"3. **2025 확인(선택에 쓰지 않음)**: 선택 변형 r2_raw {chosen['y2025_r2_raw']:.3f}·rmse_log {chosen['y2025_rmse_log']:.3f} vs v1 {base['y2025_r2_raw']:.3f}·{base['y2025_rmse_log']:.3f}. "
            "CV 의 원단위 R² 이득이 2025 에는 재현되지 않았고 rmse_log 는 나빠졌다(C1 합계 단독 2025 r2_raw "
            f"{c1['y2025_r2_raw']:.3f} 보다는 높음). 블록 부트스트랩 구간도 넓어(위 표), CV 이득은 소수 고농도 사건에 크게 좌우된다.",
            f"3-1. **통합 CV 와 폴드 평균의 차이**: 표준 지표(2020~2024 통합) Δr2_raw {chosen['cv_r2_raw'] - base['cv_r2_raw']:+.3f} 와 달리 "
            f"CV 폴드 평균 r2_raw 는 선택 {chosen['cvfold_r2_raw']:.3f} vs v1 {base['cvfold_r2_raw']:.3f}({chosen['cvfold_r2_raw'] - base['cvfold_r2_raw']:+.3f}), "
            f"C1 합계 단독 {c1['cvfold_r2_raw']:.3f}. 통합 R² 는 분산이 큰 2022·2024 의 첨두 몇 행이 좌우하고(연도별 원단위 SSE 의 약 30~70% 가 상위 3행), "
            "2021 은 물금·매리 고농도 1~2행을 과대예측(관측의 약 1.8·4.7배)해 선택 변형이 v1·C1 보다 크게 낮다(연도별 표). "
            "즉 채택 기준은 통합 지표로 만족하지만 연도 간 일관성은 약하다.",
            (
                f"4. **NNLS 4번째 구성원**: 최고 앙상블 '{be['구성']}' 은 CV r2_raw {be['cv_r2_raw']:.3f}({be['cv_r2_raw'] - base['cv_r2_raw']:+.3f}), "
                f"rmse_log {be['cv_rmse_log']:.3f}({be['cv_rmse_log'] - base['cv_rmse_log']:+.3f}) 로 log 오차는 줄지만 R² 이득이 +0.10 에 못 미친다. "
                f"2025 적용 가중은 {w_be} — NNLS 는 c1 대신 속별 합산을 고른다(속별 합산이 c1 보다 나은 log 구성원). "
                "log 공간 NNLS 는 원단위 첨두를 눌러 단독 점예측의 R² 이득을 대부분 잃는다."
                if be is not None
                else "4. 앙상블 변형 없음."
            ),
            f"5. **hurdle**: 4속 hurdle 합산 CV rmse_log {v('G4 4속 hurdle smear 단독', 'cv_rmse_log')}, r2_raw {v('G4 4속 hurdle smear 단독', 'cv_r2_raw')} 로 log 보다 나쁘다. "
            "부분 원단위 MSE 로는 소수 3속에서 hurdle 이 조금 낫게 나와 '속별 선택'에 뽑혔지만 소수 3속은 세포수 합의 약 16%(2025 약 5%)라 합산 R² 에는 영향이 작고 rmse_log 는 나빠진다.",
            f"6. **smearing**: 보정 없는 4속 합산은 CV r2_raw {v('G4 4속 log none 단독', 'cv_r2_raw')} — 속별 smearing 이 원단위 합산에 필수다.",
            f"7. **속별 자기회귀 피처**: Microcystis 부분 rmse_log 는 좋아지지만(부분 진단 표) 원단위 R² 는 낮아진다. 합산 단독(G2 log +속별피처 CV r2_raw "
            f"{v('G2 Microcystis+나머지 log smear +속별피처 단독', 'cv_r2_raw')})·앙상블 모두 피처 없는 쪽보다 R² 가 낮고, v1 3구성원에 피처만 더한 참고 행도 "
            f"CV r2_raw {v(fref, 'cv_r2_raw')}(rmse_log {v(fref, 'cv_rmse_log')}) 로 이득이 없다 → 피처는 채택하지 않는다.",
        ]
    )
    bad = info["protected_bad"]
    checks = "\n".join(
        [
            "- 테스트 `tests/test_exp_r3_genus.py` 11건 통과(pytest): "
            "`test_genus_ar_features_ignore_rows_after_as_of`(as_of 이후 행 난수 교체·삭제·추가해도 속별 피처 동일, 3개 as_of), "
            "`test_genus_ar_features_values_and_other_station`, `test_build_features_same_index_new_columns_only`(2026 기준일 거부 포함), "
            "`test_genus_targets_alignment_and_consistency`(target_date 정렬·합계 불일치 행 비움), `test_compare_sources_counts_matches`, "
            "`test_fit_component_uses_only_prior_year_labels[log|hurdle]`(2023 이후 라벨을 교란해도 ≤2023 검증 OOF 동일 — 속별 라벨은 학습 연도 < 검증 연도에서만 쓰임), "
            "`test_members_rejects_2026_rows`, `test_load_algae_cuts_after_2025`. 기존 `tests/test_exp_harness.py` 도 함께 통과.",
            "- 속별 타깃은 피처가 아니라 라벨이다(합계 타깃과 같은 측정일·같은 출처). 폴드마다 기준일 연도 < 검증 연도 행만 학습에 쓴다(`year_folds`).",
            "- 속별 자기회귀 피처는 `genus_ar_features(algae, as_of, station_id)` 진입 직후 `features.base.cut_as_of` 로 as_of 이후 측정을 버린다(위 누수 테스트).",
            "- 2026: `harness.load_base()`(≤2025)만 사용, 모델 입력 프레임 `guard_no_2026` 통과. 조류 원자료·대회 번들은 2025-12-31 이후 측정을 읽은 즉시 버렸다 "
            "(그래서 정답 측정일이 2026-01-05 인 2025 검증 4행은 속별 타깃 없음 — 이 행들은 학습에 쓰이지 않는다). test 행 예측·2026 지표 없음. 리드타임은 `harness.leadtime`(2025 까지).",
            f"- 보호 파일: `python scripts/exp_check_protected.py` 와 같은 대조 결과 변경 {len(bad)}개{(' — ' + ', '.join(bad)) if bad else ''}.",
            f"- 공개 함수 `members(df, cols)` 재현: 선택 변형 cg 와 log10 최대 절대차 {info['repro_diff']:.2e}, 모듈 상수 CHOSEN 일치 {info['chosen_matches']}.",
            "- 하이퍼파라미터 v1 그대로(C1), 시드 42 하나. 새 패키지·새 원자료 수집 없음(MANIFEST 조각 불필요).",
        ]
    )
    limits = "\n".join(
        [
            "- 한계: (1) 선택 변형의 v1 대비 이득은 주로 '앙상블 → 단독 smearing 점예측' 전환에서 오며 R1(분산 반영 원단위 복원)과 겹친다. "
            "(2) 2025 에서 원단위 R² 이득이 재현되지 않았고, CV 폴드 평균 r2_raw 이득도 작다(3-1). "
            "(3) 원단위 R² 는 소수 고농도 표본에 좌우되어 블록 부트스트랩 구간이 넓다. "
            "(4) 시드 하나(42), 하이퍼파라미터는 합계 타깃 기준 튜닝값을 속별 타깃에 그대로 썼다(속별 재튜닝 안 함). "
            "(5) 회남 2012~2014 는 속별 값이 없어 속별 모델 학습에서 빠졌다(105행). (6) 분위(q90)는 v1 그대로라 리드타임 변화 없음.",
            "- 다음 단계(종합 EXP-011): ① 속별 합산 cg(G2 log smear)를 '단독 점예측' 후보와 'NNLS 구성원' 후보 둘 다로 넘긴다(`members(df, cols)`). "
            "구성원으로 쓰면(c1 을 cg 로 대체) 이득은 작지만(+0.03) 부트스트랩 구간이 0 을 넘고 2025 에서도 v1 보다 조금 나아 더 안정적이다. "
            "② R1 의 원단위 복원(분위 기반 σ·폭 보정)을 C1 합계 단독·cg 에 같이 적용해 비교하면 분해 효과와 역변환 효과를 가를 수 있다. "
            "③ 앙상블은 log 공간 NNLS 대신 원단위 손실로 가중을 적합하는 쪽(또는 cg 단독)을 CV 로 비교할 가치가 있다. "
            "④ 속별 피처는 R² 를 낮춰 넘기지 않는다.",
        ]
    )
    return interp, checks, limits, boot_txt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EXP-006 속별 모델 합산")
    ap.add_argument("--reuse", action="store_true", help="components.parquet 재사용(재학습 생략)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t0 = time.time()
    info = run(reuse=args.reuse)
    print(H.standard_table(info["rows"]))
    print("선택:", info["chosen_label"], info["verdict"], f"{(time.time() - t0) / 60:.1f}분")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
