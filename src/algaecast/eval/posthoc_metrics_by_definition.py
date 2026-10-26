# ruff: noqa: E501  (한국어 표)
"""회귀 지표 정의별 표 — 2025(같은 252행, ≤2024 학습 v2.1)·2026(test 124 조합, 저장된 사후 예측).

원단위 결정계수는 '어떤 정의로, 어떻게 모아 계산하느냐'에 따라 값이 크게 달라진다. 이 모듈은 같은 예측으로
정의별 값을 나란히 놓아 심사위원이 보고값의 정의를 바로 대조할 수 있게 한다. 새 예측은 하지 않는다.

- 2025: 연도 확장 OOF(data/processed/v21_oof.parquet 의 ens = ≤2024 학습 v2.1)와 B0(oof_predictions.parquet 의 b0).
  행 = 기준일 2025·목표일 ≤ 2025-12-31 의 252행(eval.holdout_v21 과 같은 행·같은 값).
- 2026: data/processed/posthoc_2026_v21.parquet(v2.1 동결 뒤 1회 만든 사후 예측·정답 병합본)만 읽는다
  (eval.posthoc_v21_detail.load_pred). 타깃 있는 test 124 조합. 2026 을 읽으므로 posthoc_ 이름(패키지 제외).
- B0 지속성: 가장 최근 측정(cell_log_t0)을 7일 뒤 값으로. 원단위 = clip(10^cell_log_t0 − 1, 0), 결측 → 0.
- 정의(eval.metrics.compute_all 과 같은 함수):
  · 원단위 결정계수 nse_raw = 1 − SSE/SST (SST 는 그 집계의 관측 평균 기준, = sklearn r2_score = r2_raw)
  · 원단위 상관계수 제곱 r2_pearson_raw = Pearson r²
  · 로그 RMSE·MAE: log10(x+1) 공간. (참고) 로그 결정계수 r2_log
  · 통합 = 5지점 행을 모두 모아 한 번 계산. 지점 평균 = 지점별로 계산한 값 5개의 단순 평균(가중 없음).
- 출력: reports/eval/tbl_metrics_by_definition.md·.json(집계 값만, 행 단위 정답 없음).
- 블라인드 아님: 2026 사후 예측은 v2.1 동결 뒤 1회 계산했지만 팀은 수정 전 v1·v2 의 2026 결과를 이미 봤다.
사용: python -m algaecast.eval.posthoc_metrics_by_definition
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, ROOT
from algaecast.eval.metrics import compute_all

EVAL = ROOT / "reports" / "eval"
OUT_MD = EVAL / "tbl_metrics_by_definition.md"
OUT_JSON = EVAL / "tbl_metrics_by_definition.json"
OOF_V21 = DATA_DIR / "processed" / "v21_oof.parquet"
OOF = DATA_DIR / "processed" / "oof_predictions.parquet"
REF_2025 = EVAL / "tbl_holdout_2025_v21.json"
REF_2026 = EVAL / "posthoc_2026_v21_summary.json"
REF_2026_SITES = EVAL / "posthoc_2026_v21_detail.json"
REF_2025_SITES = (
    EVAL / "tbl_by_site.md"
)  # 2025 지점별(같은 252행, 셋째 자리, v2.1 동결 커밋 217260e 에서 갱신)
REF_2025_SITE_LABEL = {"v21": "앙상블(채택)", "b0": "B0 지속성"}  # tbl_by_site.md 의 모델 이름

SITES: tuple[str, ...] = ("HP", "GJGR", "CS", "MGMR", "DCHN")
SITE_KO = {"HP": "해평", "GJGR": "강정·고령", "CS": "칠서", "MGMR": "물금·매리", "DCHN": "회남"}
MODELS = {"v21": "v2.1", "b0": "B0 지속성"}
N_2025 = 252
N_2026 = 124
# (키, 표 이름, 정의) — 주 지표 4개 + 참고 1개
DEFS: tuple[tuple[str, str, str], ...] = (
    ("nse_raw", "원단위 결정계수(=NSE)", "1 − SSE/SST, 원단위(cells/mL), SST 는 그 집계의 관측 평균 기준"),
    ("r2_pearson_raw", "원단위 상관계수 제곱(r²)", "Pearson r², 원단위 — 편향·척도 오차를 벌점하지 않음"),
    ("rmse_log", "로그 RMSE", "√mean((log10(o+1) − log10(p+1))²) — 대회 1차 지표"),
    ("mae_log", "로그 MAE", "mean(|log10(o+1) − log10(p+1)|)"),
    ("r2_log", "(참고) 로그 결정계수", "1 − SSE/SST, log10(x+1) 공간"),
)
METRIC_KEYS: tuple[str, ...] = tuple(k for k, _, _ in DEFS)
TOL = 1e-9  # 기존 보고값(전체 정밀도) 대조 허용 오차
TOL_3DP = 5e-4  # 셋째 자리 반올림 표 대조 허용 오차


# ---------------------------------------------------------------- 순수 함수
def b0_from_log(cell_log_t0: pd.Series | np.ndarray) -> np.ndarray:
    """B0 지속성 예측(원단위): 가장 최근 측정 log10(x+1) → clip(10^v − 1, 0). 결측은 0(측정 없음)."""
    v = pd.Series(np.asarray(cell_log_t0, dtype="float64")).fillna(0.0).to_numpy()
    return np.clip(10**v - 1.0, 0.0, None)


def _pick(m: Mapping[str, Any]) -> dict[str, float]:
    return {k: float(m[k]) for k in METRIC_KEYS}


def by_definition(
    df: pd.DataFrame,
    preds: Mapping[str, str],
    *,
    obs: str = "obs",
    site: str = "station_id",
    sites: tuple[str, ...] = SITES,
) -> dict[str, dict[str, Any]]:
    """모델별로 통합(전 행 한 번)·지점별·지점 평균(단순 평균) 지표를 계산한다.

    Args:
        df: 관측 열(obs)·지점 열(site)·예측 열(preds 의 값)을 가진 표. 결측 관측은 미리 제거할 것.
        preds: {모델 키: 예측 열 이름}.
        sites: 지점 순서(표에 없는 지점은 건너뜀).

    Returns:
        {모델 키: {"pooled": {지표: 값, "n": 행 수}, "sites": {지점: {지표: 값, "n": 행 수}},
                   "site_mean": {지표: 값}, "n_sites": 지점 수}}
    """
    if df[obs].isna().any():
        raise ValueError("관측 결측 행이 있다 — 호출 전에 제거할 것")
    out: dict[str, dict[str, Any]] = {}
    for key, col in preds.items():
        o_all = df[obs].to_numpy(dtype=float)
        p_all = df[col].to_numpy(dtype=float)
        pooled = {**_pick(compute_all(o_all, p_all)), "n": int(len(df))}
        per: dict[str, dict[str, float]] = {}
        for sid in sites:
            g = df[df[site].astype(str) == sid]
            if g.empty:
                continue
            m = compute_all(g[obs].to_numpy(dtype=float), g[col].to_numpy(dtype=float))
            per[sid] = {**_pick(m), "n": int(len(g))}
        site_mean = {k: float(np.mean([per[s][k] for s in per])) for k in METRIC_KEYS}
        out[key] = {"pooled": pooled, "sites": per, "site_mean": site_mean, "n_sites": len(per)}
    return out


# ---------------------------------------------------------------- 입력
def load_2025() -> pd.DataFrame:
    """2025 같은 252행: v2.1 연도 확장 OOF(≤2024 학습)와 B0. 2026 은 읽지 않는다."""
    v = pd.read_parquet(OOF_V21)
    o = pd.read_parquet(OOF)
    for d in (v, o):
        d["station_id"] = d["station_id"].astype(str)
        d["base_date"] = pd.to_datetime(d["base_date"])
        d["target_date"] = pd.to_datetime(d["target_date"])
    k3 = ["station_id", "base_date", "target_date"]
    m = v[[*k3, "ens", "target_cells"]].merge(
        o[[*k3, "b0", "cell_log_t0"]], on=k3, how="inner", validate="1:1"
    )
    fin = m[(m["base_date"].dt.year == 2025) & (m["target_date"] <= pd.Timestamp("2025-12-31"))]
    fin = fin[fin["target_cells"].notna()].reset_index(drop=True)
    if len(fin) != N_2025:
        raise SystemExit(f"중단: 2025 행이 {len(fin)}개 — holdout_v21 의 {N_2025}행과 다르다.")
    if not np.allclose(fin["b0"].to_numpy(float), b0_from_log(fin["cell_log_t0"]), rtol=0, atol=1e-9):
        raise SystemExit("중단: OOF 의 b0 가 지속성 정의(최근 측정을 7일 뒤 값으로)와 다르다.")
    return pd.DataFrame(
        {
            "station_id": fin["station_id"],
            "obs": fin["target_cells"].to_numpy(float),
            "v21": fin["ens"].to_numpy(float),
            "b0": fin["b0"].to_numpy(float),
        }
    )


def load_2026() -> pd.DataFrame:
    """2026 test 124 조합: 저장된 v2.1 사후 예측·정답 병합본만 읽는다(새 예측 없음)."""
    from algaecast.eval import posthoc_v21_detail as P21D  # 2026 사후 예측 로더(없으면 중단)

    pred = P21D.load_pred()
    has = pred[pred["target_cells"].notna()].reset_index(drop=True)
    if len(has) != N_2026:
        raise SystemExit(f"중단: 2026 타깃 행이 {len(has)}개 — test {N_2026} 조합과 다르다.")
    return pd.DataFrame(
        {
            "station_id": has["station_id"].astype(str),
            "obs": has["target_cells"].to_numpy(float),
            "v21": has["pred_cell_count"].to_numpy(float),
            "b0": b0_from_log(has["cell_log_t0"]),
        }
    )


# ---------------------------------------------------------------- 기존 보고값 대조
def _md_site_rows(path: Path, model_label: str) -> dict[str, dict[str, float]]:
    """tbl_by_site.md 같은 마크다운 표에서 한 모델의 지점별 값(셋째 자리)을 읽는다."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    head = [c.strip() for c in lines[0].strip("|").split("|")]
    out: dict[str, dict[str, float]] = {}
    for ln in lines[2:]:
        cells = dict(zip(head, (c.strip() for c in ln.strip("|").split("|")), strict=False))
        if cells.get("모델") == model_label:
            out[cells["station_id"]] = {k: float(cells[k]) for k in METRIC_KEYS if k in cells}
    return out


def reported_checks(res: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """계산값과 기존 보고값(같은 정의)을 대조한 행 목록. res = {"2025": by_definition(...), "2026": ...}."""
    rows: list[dict[str, Any]] = []

    def add(item: str, mk: str, got: float, ref: float, tol: float, src: str) -> None:
        diff = abs(got - ref)
        rows.append(
            {
                "항목": item,
                "지표": mk,
                "계산": got,
                "기존 보고": ref,
                "차이": diff,
                "허용": tol,
                "일치": bool(diff <= tol),
                "원천": src,
            }
        )

    r25 = json.loads(REF_2025.read_text(encoding="utf-8"))["h2025"]
    for key in MODELS:
        for mk in (*METRIC_KEYS, "r2_raw"):
            got = res["2025"][key]["pooled"]["nse_raw" if mk == "r2_raw" else mk]
            add(f"2025 {MODELS[key]} 통합", mk, got, float(r25[key][mk]["value"]), TOL, REF_2025.name)
    s26 = json.loads(REF_2026.read_text(encoding="utf-8"))["overall"]
    lab26 = {
        "v21": next(k for k in s26 if k.startswith("v2.1")),
        "b0": next(k for k in s26 if k.startswith("B0")),
    }
    for key in MODELS:
        for mk in (*METRIC_KEYS, "r2_raw"):
            got = res["2026"][key]["pooled"]["nse_raw" if mk == "r2_raw" else mk]
            add(f"2026 {MODELS[key]} 통합", mk, got, float(s26[lab26[key]][mk]), TOL, REF_2026.name)
    d26 = json.loads(REF_2026_SITES.read_text(encoding="utf-8"))["sites"]
    lab_site = {"v21": "v2.1", "b0": "B0 지속성"}
    for rec in d26:
        key = next((k for k, v in lab_site.items() if v == rec["모델"]), None)
        if key is None:
            continue
        sid = rec["station_id"]
        for mk in METRIC_KEYS:
            got = res["2026"][key]["sites"][sid][mk]
            add(f"2026 {MODELS[key]} {sid}", mk, got, float(rec[mk]), TOL, REF_2026_SITES.name)
    if REF_2025_SITES.exists():
        for key, label in REF_2025_SITE_LABEL.items():
            for sid, vals in _md_site_rows(REF_2025_SITES, label).items():
                for mk, ref in vals.items():
                    got = res["2025"][key]["sites"][sid][mk]
                    add(f"2025 {MODELS[key]} {sid}", mk, got, ref, TOL_3DP, REF_2025_SITES.name)
    return rows


# ---------------------------------------------------------------- 표
def _f(x: float, nd: int = 3) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def main_table(res: Mapping[str, Mapping[str, Any]]) -> pd.DataFrame:
    """지표 정의 × 집계(통합·지점 평균) 행, 2025·2026 × v2.1·B0 열."""
    rows = []
    for mk, name, _ in DEFS:
        for scope, label in (("pooled", "5지점 통합"), ("site_mean", "지점별 값의 평균")):
            row = {"지표": name, "집계": label}
            for yr in ("2025", "2026"):
                for key in MODELS:
                    row[f"{yr} {MODELS[key]}"] = _f(res[yr][key][scope][mk])
            rows.append(row)
    return pd.DataFrame(rows)


def site_table(res_year: Mapping[str, Any]) -> pd.DataFrame:
    """한 해의 지점별 값(부록)."""
    rows = []
    for sid in SITES:
        for key in MODELS:
            per = res_year[key]["sites"].get(sid)
            if per is None:
                continue
            rows.append(
                {
                    "지점": f"{SITE_KO[sid]}({sid})",
                    "모델": MODELS[key],
                    "n": per["n"],
                    **{name: _f(per[mk]) for mk, name, _ in DEFS},
                }
            )
    return pd.DataFrame(rows)


def interpretation(res: Mapping[str, Mapping[str, Any]]) -> str:
    """해석 한 줄(값은 계산 결과에서 채운다)."""
    yrs, scopes = ("2025", "2026"), ("pooled", "site_mean")

    def gain(yr: str, sc: str) -> float:  # 지속성 대비 로그 RMSE 감소율(%)
        return 100 * (1 - res[yr]["v21"][sc]["rmse_log"] / res[yr]["b0"][sc]["rmse_log"])

    raw = [res[y]["v21"][s][k] for y in yrs for s in scopes for k in ("nse_raw", "r2_pearson_raw")]
    return (
        f"원단위 설명력은 정의(NSE·r²)·집계·해에 따라 {min(raw):.2f}~{max(raw):.2f} 로 흔들리지만(모두 0.6 아래), "
        f"로그 RMSE 는 두 해 모두 지속성보다 {gain('2025', 'pooled'):.0f}%·{gain('2026', 'pooled'):.0f}% 작다"
        f"(지점 평균 {gain('2025', 'site_mean'):.0f}%·{gain('2026', 'site_mean'):.0f}%)."
    )


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def render_md(res: Mapping[str, Mapping[str, Any]], checks: list[dict[str, Any]], line: str) -> str:
    n_ok = sum(c["일치"] for c in checks)
    defs = "\n".join(f"- **{name}**: {d}" for _, name, d in DEFS)
    chk = pd.DataFrame(checks)
    summary = (
        chk.groupby("원천")
        .agg(대조_수=("일치", "size"), 일치_수=("일치", "sum"), 최대_차이=("차이", "max"))
        .reset_index()
        .rename(columns={"대조_수": "대조 수", "일치_수": "일치 수", "최대_차이": "최대 차이"})
    )
    summary["최대 차이"] = summary["최대 차이"].map(lambda x: f"{x:.1e}")
    head = chk[chk["항목"].str.contains("통합")][["항목", "지표", "계산", "기존 보고", "일치"]].copy()
    head["계산"] = head["계산"].map(lambda x: f"{x:.6f}")
    head["기존 보고"] = head["기존 보고"].map(lambda x: f"{x:.6f}")
    return (
        "# 회귀 지표 정의별 표 — 2025(같은 252행)·2026(test 124 조합), v2.1 vs 지속성(B0)\n\n"
        "> 2026 은 v2.1 동결(커밋 217260e) 뒤 1회 만든 저장된 사후 예측을 다시 집계했다(예측 재실행 없음). "
        "블라인드 아님(팀은 수정 전 v1·v2 의 2026 결과를 이미 봤다).\n\n"
        "- 2025: ≤2024 학습 v2.1 의 연도 확장 OOF(eval.holdout_v21 과 같은 252행). 2026: v2.1(≤2025 학습) 사후 예측.\n"
        "- B0 지속성 = 가장 최근 측정을 7일 뒤 값으로. 통합 = 5지점 행을 모아 한 번 계산, "
        "지점 평균 = 지점별 값 5개의 단순 평균(가중 없음). 지점별 결정계수는 그 지점 관측 평균을 기준으로 하므로 "
        "지점 간 수준 차이로 얻는 설명력이 빠진다.\n\n"
        "## 정의(eval.metrics.compute_all 과 같은 함수)\n\n"
        f"{defs}\n\n"
        "## 1. 정의별 표\n\n" + _md(main_table(res)) + "\n\n"
        f"**해석**: {line}\n\n"
        "## 2. 기존 보고값 대조\n\n"
        f"{n_ok}/{len(checks)} 항목 일치(전체 정밀도 원천은 차이 ≤ {TOL:g}, 셋째 자리 표는 ≤ {TOL_3DP:g}).\n\n"
        + _md(summary)
        + "\n\n### 통합 값 대조(전체 정밀도)\n\n"
        + _md(head)
        + "\n\n## 부록 A. 2025 지점별(같은 252행)\n\n"
        + _md(site_table(res["2025"]))
        + "\n\n## 부록 B. 2026 지점별(test 124 조합)\n\n"
        + _md(site_table(res["2026"]))
        + "\n"
    )


def main() -> int:
    d25 = load_2025()
    d26 = load_2026()
    preds = {k: k for k in MODELS}
    res = {"2025": by_definition(d25, preds), "2026": by_definition(d26, preds)}
    checks = reported_checks(res)
    line = interpretation(res)
    OUT_MD.write_text(render_md(res, checks, line), encoding="utf-8", newline="\n")
    payload = {
        "_about": "회귀 지표 정의별 값(집계만). 2025 = 같은 252행(≤2024 학습 v2.1 OOF), 2026 = test 124 조합(저장된 v2.1 사후 예측, 블라인드 아님). python -m algaecast.eval.posthoc_metrics_by_definition",
        "definitions": {mk: {"name": name, "definition": d} for mk, name, d in DEFS},
        "aggregation": {
            "pooled": "5지점 행을 모아 한 번 계산",
            "site_mean": "지점별 값 5개의 단순 평균(가중 없음)",
        },
        "models": MODELS,
        "results": res,
        "interpretation": line,
        "checks": {
            "n": len(checks),
            "n_match": int(sum(c["일치"] for c in checks)),
            "max_abs_diff_full_precision": float(max(c["차이"] for c in checks if c["허용"] == TOL)),
            "rows": checks,
        },
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(main_table(res).to_string(index=False))
    print(line)
    bad = [c for c in checks if not c["일치"]]
    print(f"대조 {len(checks) - len(bad)}/{len(checks)} 일치")
    for c in bad:
        print("불일치:", c)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
