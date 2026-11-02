# ruff: noqa: E501  (한국어 설명)
"""화면·문서 헤드라인 숫자의 전체 정밀도 원천 → reports/eval/headline_metrics.json.

표시 값은 이 파일의 값에서 **한 번만** 반올림한다(셋째 자리 표 값을 다시 둘째 자리로 반올림하는 이중 반올림 금지).

원천
- 2026(test 124조합): data/processed/posthoc_2026_T24.parquet(T24, 동결 a961caf 뒤 1회)·posthoc_2026_v21.parquet(v2.1·v1-fix 회귀)·
  posthoc_2026_v2.parquet(v2)·posthoc_2026.parquet(v1)의 예측·타깃으로 전체 정밀도 재계산.
  사후 검증 산출물을 다시 읽어 같은 지표를 정밀하게 계산할 뿐, 모델을 다시 돌리지 않는다.
- 2025 같은 252행·CV: reports/eval/tbl_holdout_2025_v21.json(eval/holdout_v21: v2.1·v1-fix·지속성, 수정 전 v2·v1 값 포함).
- T24(2026-10-28 운영사무국 답변 '학습은 24년까지'에 따른 사전등록 전환, v2.1 구성·대회 split=train 학습)가 제출·운영 모델이다.
  T24 는 v2.1 의 Final 폴드 적합 그 자체라 2025 같은 252행·CV 값은 v2.1 과 같다(same252_2025.t24 = v21 복사, FROZEN_T24 Δ 0).
  v2.1(최종 ≤2025)은 2026-10-23~28 제출·운영 이력, v1·v2 값은 수정 전 이력이다.
- v1 2025 공개값(256행, 2026-10-21): 4행이 2026-10-22 격리돼 다시 계산할 수 없다. 남은 가장 정밀한 기록인
  models/registry.json 의 v1 회귀 metrics_holdout(소수 넷째 자리)과 tbl_holdout_2025.md(셋째 자리, 지속성·PICP)를 쓴다.
  이 값들은 'precision' 을 함께 적고, 둘째 자리 반올림이 그 정밀도 안에서 한 가지로 정해지는지(unambiguous_2dp) 검사한다.
- 대회 공식 지표(운영사무국 공식 Q&A 2026-10-30 ①②): RMSE(log)·MAE(log)·R²(원단위 피어슨 r², 상관 음수·예측 상수면 0)·NSE.
  저장소 r2_raw 는 sklearn r2_score = NSE 라 공식 R² 가 아니다. 공식 R² 는 r2_official 키(2025·CV 는 OOF 캐시로, 2026 은 사후
  예측으로 계산)이며 같은 내용을 reports/eval/tbl_official_metrics.md 표로도 쓴다. 공식 참고지표 F1(10,000 초과)은 2025 만 다시 계산한다.
사용: python -m algaecast.eval.headline
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, MODELS_DIR, ROOT
from algaecast.eval.metrics import compute_all, f1_official, mae_log, nse_raw, r2_official, rmse_log

EVAL = ROOT / "reports" / "eval"
OUT = EVAL / "headline_metrics.json"
KEYS = ("rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k")
OFFICIAL_MD = EVAL / "tbl_official_metrics.md"


def round_once(x: float, nd: int = 2) -> float:
    """사람이 읽는 반올림(0.5 올림) 한 번. 전체 정밀도 값에만 쓴다."""
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))


def unambiguous(value: float, precision: int, nd: int = 2) -> bool:
    """precision 자리로 이미 반올림된 값의 실제 범위 [v−h, v+h) 가 nd 자리 반올림 경계를 걸치지 않는지."""
    h = 0.5 * 10.0 ** (-precision)
    return round_once(value - h + 1e-12, nd) == round_once(value + h - 1e-12, nd)


def posthoc(path: str, point: str = "pred_cell_count") -> dict:
    d = pd.read_parquet(DATA_DIR / "processed" / path)
    has = d[d["target_cells"].notna()]
    obs = has["target_cells"].to_numpy(dtype=float)
    m = compute_all(
        obs,
        has[point].to_numpy(dtype=float),
        q10=has["q10_cqr"].to_numpy(),
        q90=has["q90_cqr"].to_numpy(),
        p10k=has["p_alert"].to_numpy(),
    )
    b0 = np.clip(10 ** has["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    mb = compute_all(obs, b0)
    pred = has[point].to_numpy(dtype=float)
    return {
        "model": {k: float(m[k]) for k in (*KEYS, "picp80", "mpiw80_log", "brier_10k")}
        | {"r2_official": r2_official(obs, pred), "n": int(m["n"])},
        "b0": {k: float(mb[k]) for k in KEYS} | {"r2_official": r2_official(obs, b0), "n": int(mb["n"])},
    }


def oof_official(same: dict) -> dict:
    """2025 같은 252행·CV 2020~2024 통합의 공식 지표를 OOF 캐시로 계산한다(목표일 2026 행 없음 확인).

    T24 = v2.1 구성 Final 폴드 OOF(v21_oof.parquet 의 ens), B0·v1-fix = oof_predictions.parquet. 원천 JSON
    (tbl_holdout_2025_v21.json)의 n·rmse_log·nse_raw·r2_pearson_raw 와 같은 행인지 대조한 뒤 r2_official·f1_official 을 더한다.
    """
    k3 = ["station_id", "base_date", "target_date"]
    v = pd.read_parquet(DATA_DIR / "processed" / "v21_oof.parquet")
    o = pd.read_parquet(DATA_DIR / "processed" / "oof_predictions.parquet")
    for d in (v, o):
        d["base_date"], d["target_date"] = pd.to_datetime(d["base_date"]), pd.to_datetime(d["target_date"])
        d["station_id"] = d["station_id"].astype(str)
        assert (d["target_date"] < "2026-01-01").all(), "OOF 캐시에 목표일 2026 행이 있다"
    d = v.merge(o[[*k3, "b0", "ens_v1fix"]], on=k3, how="left")

    def block(obs: np.ndarray, pred: np.ndarray, *, f1: bool = True) -> dict:
        out = {
            "n": int(obs.size),
            "rmse_log": rmse_log(obs, pred),
            "mae_log": mae_log(obs, pred),
            "r2_official": r2_official(obs, pred),
            "nse_raw": nse_raw(obs, pred),
        }
        if f1:
            out["f1_10k_official"] = f1_official(obs, pred)
        return out

    h = d[(d["base_date"].dt.year == 2025) & (d["target_date"] <= "2025-12-31") & d["ens"].notna()]
    obs = h["target_cells"].to_numpy(dtype=float)
    res25 = {
        m: block(obs, h[c].to_numpy(dtype=float))
        for m, c in (("t24", "ens"), ("b0", "b0"), ("v1fix", "ens_v1fix"))
    }
    for m, key in (("t24", "v21"), ("b0", "b0"), ("v1fix", "v1fix")):
        ref = same["h2025"][key]
        assert res25[m]["n"] == ref["n"], (m, res25[m]["n"], ref["n"])
        for k in ("rmse_log", "nse_raw"):
            assert abs(res25[m][k] - ref[k]["value"]) < 1e-9, (m, k)
        if res25[m]["r2_official"] > 0:
            assert abs(res25[m]["r2_official"] - ref["r2_pearson_raw"]["value"]) < 1e-9, (m, "r2")
    cv = d[d["base_date"].dt.year.between(2020, 2024) & d["ens"].notna()]
    rcv = block(cv["target_cells"].to_numpy(dtype=float), cv["ens"].to_numpy(dtype=float), f1=False)
    ref = same["cv"]["v21"]
    assert rcv["n"] == ref["n_pooled"] and abs(rcv["nse_raw"] - ref["r2_raw_pooled"]) < 1e-9
    assert abs(rcv["rmse_log"] - ref["rmse_log_pooled"]) < 1e-9
    return {"same252_2025": res25, "cv_pooled": {"t24": rcv}}


def write_official_md(out: dict) -> None:
    """공식 지표 표(사람이 읽는 원천) — 방법설명서·README 가 인용한다."""
    o = out["official"]

    def f3(x: float) -> str:
        return f"{x:.3f}"

    s25, p26 = o["same252_2025"], out["posthoc2026"]
    rows = [
        ("2025 검증(같은 252행)", "T24(제출·운영)", s25["t24"], f3(s25["t24"]["f1_10k_official"])),
        ("2025 검증(같은 252행)", "B0 지속성", s25["b0"], f3(s25["b0"]["f1_10k_official"])),
        ("CV 2020~2024 OOF 통합", "T24 구성(= v2.1 구성)", o["cv_pooled"]["t24"], "—"),
        ("2026 사후(test 124, 블라인드 아님)", "T24(제출·운영)", p26["t24"], f"{p26['t24']['f1_10k']:.3f}*"),
        ("2026 사후(test 124, 블라인드 아님)", "B0 지속성", p26["b0"], f"{p26['b0']['f1_10k']:.3f}*"),
    ]
    lines = [
        "# 대회 공식 지표 — 제출·운영 모델 T24 (운영사무국 공식 Q&A 2026-10-30 ①②)",
        "",
        "- 공식 순위 지표 4개(가중치 동일, 지점 구분 없이 통합 계산): RMSE(log10(x+1)) · MAE(log10(x+1)) · "
        "R²(원단위 관측·예측의 피어슨 상관계수 제곱, 예측 상수·상관 음수면 0) · NSE(원단위 1 − SSE/SST).",
        "- 저장소의 `r2_raw` 는 sklearn r2_score = NSE 라 공식 R² 가 아니다. 공식 R² 는 `r2_official`"
        "(상관이 양수면 `r2_pearson_raw` 와 같다).",
        "- F1@10k 는 순위에 넣지 않는 참고지표다. 2025 행은 공식 정의(10,000 **초과**)로 다시 계산했다(저장소 `f1_10k` 는"
        " '이상' 기준이지만 경계값 행이 없어 같다). *2026 은 '이상' 기준 보고값이다.",
        "- 2025·CV 는 OOF 캐시(`data/processed/v21_oof.parquet`·`oof_predictions.parquet`), 2026 은 T24 동결(a961caf) 뒤 1회 계산한"
        " 사후 예측(`data/processed/posthoc_2026_T24.parquet`)을 다시 집계한 값이다(모델 재실행 없음). 예측은 반올림 전 실수값이다.",
        "",
        "| 구간 | 모델 | n | RMSE(log) | MAE(log) | R²(공식) | NSE | F1@10k(참고) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for seg, model, b, f1 in rows:
        lines.append(
            f"| {seg} | {model} | {b['n']} | {f3(b['rmse_log'])} | {f3(b['mae_log'])} | "
            f"{f3(b['r2_official'])} | {f3(b['nse_raw'])} | {f1} |"
        )
    lines += [
        "",
        "생성: `python -m algaecast.eval.headline`(reports/eval/headline_metrics.json 의 `official`·`posthoc2026` 와 같은 값)."
        " 이 모듈과 2026 사후 예측 parquet 은 사후 분석 자료라 공지 ⑧에 따라 제출 패키지에 넣지 않았다"
        "(비공개 저장소 보관, 요청 시 제공 — 재현 실행에는 필요 없음).",
    ]
    OFFICIAL_MD.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def table_row(md: str, prefix: str, cols: tuple[str, ...]) -> dict[str, float]:
    lines = (EVAL / md).read_text(encoding="utf-8").splitlines()
    head = next(ln for ln in lines if ln.startswith("| 모델"))
    names = [c.strip() for c in head.strip("|").split("|")]
    row = next(ln for ln in lines if ln.startswith(f"| {prefix}"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    out = {}
    for c in cols:
        v = cells[names.index(c)]
        out[c] = float(re.match(r"-?\d+(\.\d+)?", v).group(0))
    return out


def main() -> int:
    reg = json.loads((MODELS_DIR / "registry.json").read_text(encoding="utf-8"))
    v1reg = next(
        e for e in reg["versions"] if e["name"] == "regression" and e["version"] == "20261021_091108"
    )["metrics_holdout"]
    b0pub = table_row(
        "tbl_holdout_2025.md", "B0 지속성", ("rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k")
    )
    picp_pub = table_row("tbl_holdout_2025.md", "앙상블(채택)", ("PICP80(CQR)",))["PICP80(CQR)"]
    same = json.loads((EVAL / "tbl_holdout_2025_v21.json").read_text(encoding="utf-8"))
    p1, p2 = posthoc("posthoc_2026.parquet"), posthoc("posthoc_2026_v2.parquet")
    p21, pfix = posthoc("posthoc_2026_v21.parquet"), posthoc("posthoc_2026_v21.parquet", "pred_v1fix")
    p24 = posthoc("posthoc_2026_T24.parquet")
    limited = {
        "v1_2025_public": {
            "values": {k: v1reg[k] for k in ("rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k")},
            "precision": 4,
            "source": "models/registry.json regression 20261021_091108 metrics_holdout(256행, 2026-10-21 계산, 넷째 자리 기록)",
        },
        "b0_2025_public": {
            "values": b0pub,
            "precision": 3,
            "source": "reports/eval/tbl_holdout_2025.md B0 지속성(252행)",
        },
        "picp80_2025_public": {
            "values": {"picp80": picp_pub},
            "precision": 3,
            "source": "reports/eval/tbl_holdout_2025.md 앙상블(채택) PICP80(CQR)(252행, v2.1 재적합 분위·CQR)",
        },
    }
    for blk in limited.values():
        blk["unambiguous_2dp"] = {k: unambiguous(v, blk["precision"]) for k, v in blk["values"].items()}
    out = {
        "_about": "화면·문서 헤드라인 숫자의 전체 정밀도 원천. 표시 값은 여기서 한 번만 반올림한다(python -m algaecast.eval.headline).",
        "limited_precision": limited,
        "same252_2025": {
            **{
                m: {k: same["h2025"][m][k]["value"] for k in KEYS} | {"n": same["h2025"][m]["n"]}
                for m in ("v21", "v1fix", "b0")
            },
            # T24 = v2.1 Final 폴드(≤2024 적합, 같은 252행) — 값이 같다
            "t24": {k: same["h2025"]["v21"][k]["value"] for k in KEYS} | {"n": same["h2025"]["v21"]["n"]},
            **{
                m: {k: same["before"]["h2025"][m][k]["value"] for k in KEYS}
                | {"n": same["before"]["h2025"][m]["n"]}
                for m in ("v2", "v1")
            },
        },
        "cv_pooled_r2_raw": {
            **{m: same["cv"][m]["r2_raw_pooled"] for m in ("v21", "v1fix", "b0")},
            "t24": same["cv"]["v21"]["r2_raw_pooled"],
            **{m: same["before"]["cv"][m]["r2_raw_pooled"] for m in ("v2", "v1")},
        },
        "official": oof_official(same),
        "picp80_2025_same252": same["shared_2025"]["picp80"],
        "picp80_2025_same252_before": same["before"]["shared_2025"]["picp80"],
        "posthoc2026": {
            "t24": p24["model"],
            "v21": p21["model"],
            "v1fix": {k: v for k, v in pfix["model"].items() if k in (*KEYS, "r2_official", "n")},
            "v2": p2["model"],
            "v1": p1["model"],
            "b0": p1["b0"],
        },
    }
    assert p1["b0"] == p2["b0"] == p21["b0"] == p24["b0"], "사후 파일의 지속성 지표가 다르다(행이 다름)"
    # 2025 같은 252행의 공식 R²: T24·B0·v1-fix 는 OOF 로 계산(0 규칙 포함), 수정 전 v2·v1 은 NSE > 0 이라
    # 상관이 양수다(NSE ≤ 0 이 아니면 r > 0) → 피어슨 r² 그대로
    for m, blk in out["same252_2025"].items():
        if m in out["official"]["same252_2025"]:
            blk["r2_official"] = out["official"]["same252_2025"][m]["r2_official"]
        else:
            assert blk["nse_raw"] > 0, m
            blk["r2_official"] = blk["r2_pearson_raw"]
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    write_official_md(out)
    # 이중 반올림으로 달라지는 값 목록(점검용 출력)
    flat = []
    for sec in ("same252_2025", "posthoc2026"):
        for m, vals in out[sec].items():
            for k, v in vals.items():
                if k != "n":
                    flat.append((f"{sec}.{m}.{k}", v))
    for m, v in out["cv_pooled_r2_raw"].items():
        flat.append((f"cv_pooled_r2_raw.{m}", v))
    for name, v in flat:
        once, twice = round_once(v), round_once(round_once(v, 3))
        if once != twice:
            print(f"이중 반올림 차이: {name} = {v:.6f} → 한 번 {once:.2f} / 셋째 자리 거쳐 {twice:.2f}")
    for name, blk in limited.items():
        bad = [k for k, ok in blk["unambiguous_2dp"].items() if not ok]
        print(f"{name}: 정밀도 {blk['precision']}자리, 둘째 자리 결정 불가 {bad or '없음'}")
    print("→", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
