# ruff: noqa: E501  (한국어 설명)
"""화면·문서 헤드라인 숫자의 전체 정밀도 원천 → reports/eval/headline_metrics.json.

표시 값은 이 파일의 값에서 **한 번만** 반올림한다(셋째 자리 표 값을 다시 둘째 자리로 반올림하는 이중 반올림 금지).

원천
- 2026(test 124조합): data/processed/posthoc_2026_v21.parquet(v2.1·v1-fix 회귀)·posthoc_2026_v2.parquet(v2)·posthoc_2026.parquet(v1)의
  예측·타깃으로 전체 정밀도 재계산.
  사후 검증 산출물을 다시 읽어 같은 지표를 정밀하게 계산할 뿐, 모델을 다시 돌리지 않는다.
- 2025 같은 252행·CV: reports/eval/tbl_holdout_2025_v21.json(eval/holdout_v21: v2.1·v1-fix·지속성, 수정 전 v2·v1 값 포함).
- v2.1(FIX-v2.1, 데이터 유래 상수 누수 수정판)이 제출·운영 모델이다. v1·v2 값은 수정 전 이력이다.
- v1 2025 공개값(256행, 2026-10-21): 4행이 2026-10-22 격리돼 다시 계산할 수 없다. 남은 가장 정밀한 기록인
  models/registry.json 의 v1 회귀 metrics_holdout(소수 넷째 자리)과 tbl_holdout_2025.md(셋째 자리, 지속성·PICP)를 쓴다.
  이 값들은 'precision' 을 함께 적고, 둘째 자리 반올림이 그 정밀도 안에서 한 가지로 정해지는지(unambiguous_2dp) 검사한다.
사용: python -m algaecast.eval.headline
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, MODELS_DIR, ROOT
from algaecast.eval.metrics import compute_all

EVAL = ROOT / "reports" / "eval"
OUT = EVAL / "headline_metrics.json"
KEYS = ("rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k", "f1_1k")


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
    return {
        "model": {k: float(m[k]) for k in (*KEYS, "picp80", "mpiw80_log", "brier_10k")} | {"n": int(m["n"])},
        "b0": {k: float(mb[k]) for k in KEYS} | {"n": int(mb["n"])},
    }


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
            **{
                m: {k: same["before"]["h2025"][m][k]["value"] for k in KEYS}
                | {"n": same["before"]["h2025"][m]["n"]}
                for m in ("v2", "v1")
            },
        },
        "cv_pooled_r2_raw": {
            **{m: same["cv"][m]["r2_raw_pooled"] for m in ("v21", "v1fix", "b0")},
            **{m: same["before"]["cv"][m]["r2_raw_pooled"] for m in ("v2", "v1")},
        },
        "picp80_2025_same252": same["shared_2025"]["picp80"],
        "picp80_2025_same252_before": same["before"]["shared_2025"]["picp80"],
        "posthoc2026": {
            "v21": p21["model"],
            "v1fix": {k: v for k, v in pfix["model"].items() if k in (*KEYS, "n")},
            "v2": p2["model"],
            "v1": p1["model"],
            "b0": p1["b0"],
        },
    }
    assert p1["b0"] == p2["b0"] == p21["b0"], "사후 파일의 지속성 지표가 다르다(행이 다름)"
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
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
