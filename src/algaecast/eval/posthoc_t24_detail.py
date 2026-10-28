# ruff: noqa: E501  (한국어 표)
"""2026 사후 계산(T24) 세부 집계 — 저장된 T24 사후 예측을 다시 집계만 한다(예측을 다시 하지 않는다).

- 입력(읽기만)
  · data/processed/posthoc_2026_T24.parquet: eval.posthoc_t24 가 T24 동결 커밋 a961caf 뒤 1회 만든 2026 예측·타깃
    (sha256 42d48a55…, 261행 중 test 124 조합에만 타깃). 해시가 다르면 중단한다.
  · data/processed/posthoc_2026_v21.parquet: v2.1(이력) 사후 예측 — 비교 열과 절차 재현 확인에만 쓴다.
  · 측정 원자료(공공 API·대회 번들 조류, eval.posthoc_answer_source 와 같은 로더), 2020~2025 OOF(oof_predictions.parquet).
- 출력: reports/experiments/contingency_T24/tbl_holdout_2026_posthoc_T24_detail.md · posthoc_2026_T24_detail.json
  1) 지점별 2026 지표(T24·v2.1(이력)·B0 지속성, test 124 조합)
  2) 정의별 지표(5지점 통합·지점 평균; eval.posthoc_metrics_by_definition 과 같은 함수) — 2025 같은 252행·2026 test 124
  3) 관심(1k) 사건 리드타임: 공공 API 사건(eval.posthoc.leadtime_2026)과 번들 정답만(번들 사건·번들 재사용 가능 기준일)
  4) 경계(10k) 리드 API/번들 대조와 2020~2026 합계(감시 = OOF q90≥1만 + 2026 T24 q90_cqr≥1만)
  5) 강정·고령 4~6월 1k 기준 점등(방법설명서 표 10-2 원천)
  6) 정답을 번들 값으로 바꿔 계산한 2026 지표(T24)
- 절차 확인: 같은 함수로 v2.1 저장 예측을 집계해 기존 보고값(posthoc_2026_v21_detail.json·tbl_metrics_by_definition.json·
  tbl_posthoc_answer_source.json)을 그대로 재현하는지 먼저 본다(다르면 중단). T24 통합 지표는 posthoc_2026_T24_summary.json 과
  같아야 한다.
- 블라인드 아님: 팀은 v2.1 의 2026 결과를 이미 본 뒤 T24 를 사전등록(960d76f)·동결(a961caf)했다. 2026 예측은 T24 동결 뒤
  1회(2026-10-26 13:19 KST)뿐이고 이 모듈은 그 저장본을 다시 집계한다.
사용: python -m algaecast.eval.posthoc_t24_detail
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT
from algaecast.eval import posthoc as PH
from algaecast.eval import posthoc_answer_source as AS
from algaecast.eval import posthoc_metrics_by_definition as MD
from algaecast.eval.metrics import compute_all
from algaecast.eval.transitions import T1K, T10K, leadtime_table, load_oof

EVAL = ROOT / "reports" / "eval"
OUT_DIR = ROOT / "reports" / "experiments" / "contingency_T24"
OUT_MD = OUT_DIR / "tbl_holdout_2026_posthoc_T24_detail.md"
OUT_JSON = OUT_DIR / "posthoc_2026_T24_detail.json"
SUMMARY = OUT_DIR / "posthoc_2026_T24_summary.json"
PRED_T24 = DATA_DIR / "processed" / "posthoc_2026_T24.parquet"
PRED_V21 = DATA_DIR / "processed" / "posthoc_2026_v21.parquet"
SHA_T24 = "42d48a55455af4598d47d847d61eaad418f8c35a9765c5fbe27bc67fb585124b"
COMMIT = "a961caf"
KEYS = ["n", "rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k"]
SITE_KO = AS.SITE_KO
TOL = 1e-12


def load_t24() -> pd.DataFrame:
    """T24 저장 예측(해시 확인). 없거나 해시가 다르면 중단 — 여기서 예측을 새로 만들지 않는다."""
    if not PRED_T24.exists():
        raise SystemExit(
            f"{PRED_T24} 가 없다. T24 2026 사후 예측은 eval.posthoc_t24 로 1회만 만든다(사본 산출물을 복사)."
        )
    sha = hashlib.sha256(PRED_T24.read_bytes()).hexdigest()
    if sha != SHA_T24:
        raise SystemExit(f"중단: {PRED_T24.name} sha256 {sha[:12]}… ≠ 동결 뒤 1회 산출물 {SHA_T24[:12]}…")
    return AS.load_pred(PRED_T24)


def site_table(t24: pd.DataFrame, v21: pd.DataFrame) -> pd.DataFrame:
    """지점별 2026 지표(test 124 조합)."""
    rows = []
    for sid in AS.SITES:
        g = t24[(t24["station_id"] == sid) & t24["target_cells"].notna()]
        h = v21.loc[g.index]
        obs = g["target_cells"].to_numpy(dtype=float)
        b0 = np.clip(10 ** g["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
        for label, p in (
            ("T24", g["pred_cell_count"].to_numpy(dtype=float)),
            ("v2.1(이력)", h["pred_cell_count"].to_numpy(dtype=float)),
            ("B0 지속성", b0),
        ):
            m = compute_all(obs, p)
            rows.append({"지점": SITE_KO[sid], "station_id": sid, "모델": label, **{k: m[k] for k in KEYS}})
    return pd.DataFrame(rows)


def lead_compare(
    pred: pd.DataFrame,
    lv: float,
    ev_api: pd.DataFrame,
    ev_bun: pd.DataFrame,
    m_api: pd.DataFrame,
    m_bun: pd.DataFrame,
    usable: pd.Series,
    undetermined: pd.Index,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """API 사건(전 기준일)·번들 사건(번들 재사용 가능 기준일) 리드 — eval.posthoc_answer_source 와 같은 규칙·표 형식."""
    rl = AS.rules_2026(pred, lv)
    s_api, d_api = AS.leadtime_from(pred, ev_api, m_api, rl, lv)
    ref_s, ref_d = PH.leadtime_2026(pred, lv, point=True)
    ref_s = ref_s.rename(columns={"경보 총수(2026)": "경보 총수"})
    pd.testing.assert_frame_equal(
        s_api.reset_index(drop=True), ref_s.reset_index(drop=True), check_dtype=False
    )
    pd.testing.assert_frame_equal(
        d_api.reset_index(drop=True), ref_d.reset_index(drop=True), check_dtype=False
    )
    s_bun, d_bun = AS.leadtime_from(pred[usable], ev_bun, m_bun, rl, lv)

    def f(x: object) -> str:
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:g}"

    a, b = s_api.set_index("방식"), s_bun.set_index("방식")
    comp = [
        {
            "방식": name,
            "사건 수 API/번들": f"{int(a.loc[name, '사건 수'])}/{int(b.loc[name, '사건 수'])}",
            "선행 탐지 API/번들": f"{int(a.loc[name, '선행 탐지 수'])}/{int(b.loc[name, '선행 탐지 수'])}",
            "중앙 리드 E API/번들": f"{f(a.loc[name, '중앙 리드(E, 일)'])}/{f(b.loc[name, '중앙 리드(E, 일)'])}",
            "중앙 리드 D API/번들": f"{f(a.loc[name, '중앙 리드(D, 일)'])}/{f(b.loc[name, '중앙 리드(D, 일)'])}",
            f"경보 총수 API({len(pred)}행)": int(a.loc[name, "경보 총수"]),
            f"경보 총수 번들({int(usable.sum())}행)": int(b.loc[name, "경보 총수"]),
            "번들 기간 안 미확정 행의 경보": int(rl[name].loc[undetermined].sum()),
        }
        for name in rl
    ]
    return pd.DataFrame(comp), d_api, s_api, d_bun


def combined(s_oof: pd.DataFrame, d_oof: pd.DataFrame, s26: pd.DataFrame, d26: pd.DataFrame) -> dict:
    """2020~2026 합계(eval.posthoc_answer_source.main 의 합계와 같은 식)."""
    so, s2 = s_oof.set_index("방식"), s26.set_index("방식")
    w = AS.RULE_WATCH
    n_ev = int(so.loc["q90≥임계", "사건 수"] + s2.loc[w, "사건 수"])
    det = int(so.loc["q90≥임계", "선행 탐지 수"] + s2.loc[w, "선행 탐지 수"])
    leads = [*d_oof[d_oof["방식"] == "q90≥임계"]["리드(E)"], *d26[d26["방식"] == w]["리드(E)"]]
    leads_d = [*d_oof[d_oof["방식"] == "q90≥임계"]["리드(D)"], *d26[d26["방식"] == w]["리드(D)"]]
    b0 = int(so.loc[AS.RULE_B0, "선행 탐지 수"] + s2.loc[AS.RULE_B0, "선행 탐지 수"])
    return {
        "사건 수": n_ev,
        "감시 포착": det,
        "포착 비율": det / n_ev,
        "중앙 리드(E, 일)": float(np.median(leads)),
        "중앙 리드(D, 일)": float(np.median(leads_d)),
        "지속성 포착": b0,
    }


def _check_equal(name: str, got: Mapping, ref: Mapping) -> None:
    a = json.loads(json.dumps(AS.clean(dict(got)), ensure_ascii=False))
    b = json.loads(json.dumps(AS.clean(dict(ref)), ensure_ascii=False))
    if a != b:
        raise SystemExit(f"중단: 절차 재현 실패 — {name}\n계산 {a}\n기존 {b}")


def def_table(by_def: Mapping[str, Mapping]) -> pd.DataFrame:
    """정의 × 집계 행, 2025(T24 = v2.1 Final 폴드)·2026(T24·v2.1 이력)·B0 열."""
    rows = []
    for mk, name, _ in MD.DEFS:
        for scope, label in (("pooled", "5지점 통합"), ("site_mean", "지점별 값의 평균")):
            rows.append(
                {
                    "지표": name,
                    "집계": label,
                    "2025 T24(=v2.1 Final 폴드)": MD._f(by_def["2025"]["t24"][scope][mk]),
                    "2025 B0 지속성": MD._f(by_def["2025"]["b0"][scope][mk]),
                    "2026 T24": MD._f(by_def["2026"]["t24"][scope][mk]),
                    "2026 v2.1(이력)": MD._f(by_def["2026"]["v21"][scope][mk]),
                    "2026 B0 지속성": MD._f(by_def["2026"]["b0"][scope][mk]),
                }
            )
    return pd.DataFrame(rows)


def def_site_table(res: Mapping) -> pd.DataFrame:
    """2026 지점별 정의별 값."""
    rows = []
    for sid in AS.SITES:
        for key, lab in (("t24", "T24"), ("v21", "v2.1(이력)"), ("b0", "B0 지속성")):
            per = res[key]["sites"].get(sid)
            if per is None:
                continue
            rows.append(
                {
                    "지점": f"{SITE_KO[sid]}({sid})",
                    "모델": lab,
                    "n": per["n"],
                    **{name: MD._f(per[mk]) for mk, name, _ in MD.DEFS},
                }
            )
    return pd.DataFrame(rows)


def interpretation(by_def: Mapping[str, Mapping]) -> str:
    """해석 한 줄(값은 계산 결과에서 채운다)."""

    def gain(yr: str, sc: str) -> float:
        return 100 * (1 - by_def[yr]["t24"][sc]["rmse_log"] / by_def[yr]["b0"][sc]["rmse_log"])

    raw = [
        by_def[y]["t24"][s][k]
        for y in ("2025", "2026")
        for s in ("pooled", "site_mean")
        for k in ("nse_raw", "r2_pearson_raw")
    ]
    return (
        f"T24 원단위 설명력은 정의(NSE·r²)·집계·해에 따라 {min(raw):.2f}~{max(raw):.2f} 로 흔들리지만(모두 0.6 아래), "
        f"로그 RMSE 는 두 해 모두 지속성보다 {gain('2025', 'pooled'):.0f}%·{gain('2026', 'pooled'):.0f}% 작다"
        f"(지점 평균 {gain('2025', 'site_mean'):.0f}%·{gain('2026', 'site_mean'):.0f}%)."
    )


def main() -> int:
    t24 = load_t24()
    v21 = AS.load_pred(PRED_V21)
    k3 = ["station_id", "base_date", "target_date"]
    if not t24[k3].equals(v21[k3]):
        raise SystemExit("중단: T24·v2.1 저장 예측의 (지점, 기준일, 목표일) 행이 다르다.")
    if not t24["target_cells"].equals(v21["target_cells"]) or not t24["cell_log_t0"].equals(
        v21["cell_log_t0"]
    ):
        raise SystemExit("중단: T24·v2.1 저장 예측의 타깃·최근 관측이 다르다.")
    test = t24["target_cells"].notna()
    summ = json.loads(SUMMARY.read_text(encoding="utf-8"))
    lab_t24 = next(k for k in summ["overall"] if k.startswith("T24"))

    # 1) 지점별 — v2.1 행은 기존 detail json 과 같아야 한다(절차 재현)
    sites = site_table(t24, v21)
    old = {
        (r["station_id"], r["모델"]): r
        for r in json.loads((EVAL / "posthoc_2026_v21_detail.json").read_text(encoding="utf-8"))["sites"]
    }
    for r in sites[sites["모델"] == "v2.1(이력)"].to_dict(orient="records"):
        ref = old[(r["station_id"], "v2.1")]
        if max(abs(float(r[k]) - float(ref[k])) for k in KEYS) > TOL:
            raise SystemExit(f"중단: v2.1 지점별 재현 실패 {r['station_id']}")

    # 2) 정의별 — 2025 같은 252행(Final 폴드 OOF = ≤2024 적합 = T24 학습 행), 2026 test 124
    d25 = MD.load_2025().rename(columns={"v21": "t24"})
    has = t24[test].reset_index(drop=True)
    d26 = pd.DataFrame(
        {
            "station_id": has["station_id"].astype(str),
            "obs": has["target_cells"].to_numpy(float),
            "t24": has["pred_cell_count"].to_numpy(float),
            "v21": v21.loc[test, "pred_cell_count"].to_numpy(float),
            "b0": MD.b0_from_log(has["cell_log_t0"]),
        }
    )
    by_def = {
        "2025": MD.by_definition(d25, {"t24": "t24", "b0": "b0"}),
        "2026": MD.by_definition(d26, {"t24": "t24", "v21": "v21", "b0": "b0"}),
    }
    for mk in MD.METRIC_KEYS:
        got, ref = by_def["2026"]["t24"]["pooled"][mk], float(summ["overall"][lab_t24][mk])
        if abs(got - ref) > 1e-9:
            raise SystemExit(f"중단: 2026 T24 통합 {mk} {got} ≠ 사후 요약 {ref}")
    old_def = json.loads((EVAL / "tbl_metrics_by_definition.json").read_text(encoding="utf-8"))["results"]
    for scope in ("pooled", "site_mean"):
        for mk in MD.METRIC_KEYS:
            if abs(by_def["2026"]["v21"][scope][mk] - old_def["2026"]["v21"][scope][mk]) > 1e-9:
                raise SystemExit(f"중단: v2.1 정의별 재현 실패 2026 {scope} {mk}")
            if abs(by_def["2025"]["t24"][scope][mk] - old_def["2025"]["v21"][scope][mk]) > 1e-9:
                raise SystemExit(f"중단: 2025 정의별(같은 252행) 재현 실패 {scope} {mk}")

    # 3)·4) 리드타임 — API 사건과 번들 정답만
    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    horizon, tol = int(cfg["target"]["horizon_days"]), int(cfg["target"]["match_tolerance_days"])
    bundle, api = AS.load_measurements()
    diffs_model = AS.diff_rows(api, bundle, AS.MODEL_ALGAE_COLS)
    diffs_up = AS.diff_rows(api, bundle, AS.UPSTREAM_ALGAE_COLS)
    rows = AS.base_row_check(t24, api, bundle, diffs_model, horizon, tol, diffs_up)
    usable = rows["번들 재사용 가능"]
    undetermined = rows[rows["번들 기간 안"] & ~usable].index
    m_api, m_bun = AS.meas_for_window(api), AS.meas_for_window(bundle)
    old_as = json.loads((EVAL / "tbl_posthoc_answer_source.json").read_text(encoding="utf-8"))
    lead: dict[str, dict] = {}
    for lv, key in ((T10K, "10k"), (T1K, "1k")):
        ev_api, ev_bun = AS.events_from(api, lv, 2026), AS.events_from(bundle, lv, 2026)
        comp_v21, *_ = lead_compare(v21, lv, ev_api, ev_bun, m_api, m_bun, usable, undetermined)
        for got, ref in zip(
            comp_v21.to_dict(orient="records"), old_as[f"lead_2026_{key}"]["compare"], strict=True
        ):
            _check_equal(f"v2.1 리드 {key} {got['방식']}", got, ref)
        comp, d_api, s_api, d_bun = lead_compare(t24, lv, ev_api, ev_bun, m_api, m_bun, usable, undetermined)
        lead[key] = {
            "compare": comp,
            "api_detail": d_api,
            "api_summary": s_api,
            "bundle_detail": d_bun,
            "n_events_api": int(len(ev_api)),
            "n_events_bundle": int(len(ev_bun)),
        }
    w = lead["10k"]["api_summary"].set_index("방식")
    for rule, k in ((AS.RULE_WATCH, "watch"), (AS.RULE_ALERT, "alert"), (AS.RULE_POINT, "point")):
        if (
            int(w.loc[rule, "선행 탐지 수"]) != summ["T24"][k]["detected"]
            or float(w.loc[rule, "중앙 리드(E, 일)"]) != summ["T24"][k]["median_lead_e"]
        ):
            raise SystemExit(f"중단: 경계 리드 {k} 가 사후 요약과 다르다.")

    # 2020~2026 합계(경계) — 2020~2025 는 OOF(v2.1 구성 폴드 = T24 와 같음), 2026 은 T24
    o, thr = load_oof()
    o20 = o[o["year"] >= 2020]
    ro = {k: v.loc[o20.index] for k, v in AS.rules_oof(o, T10K).items()}
    s_o_api, d_o_api = AS.leadtime_from(o20, AS.events_from(api, T10K, 2020), m_api, ro, T10K)
    s_o_bun, d_o_bun = AS.leadtime_from(o20, AS.events_from(bundle, T10K, 2020), m_bun, ro, T10K)
    lt_ref, _ = leadtime_table(o, thr, T10K)
    if int(s_o_api.set_index("방식").loc["q90≥임계", "선행 탐지 수"]) != int(
        lt_ref.set_index("방식").loc["q90≥임계", "선행 탐지 수"]
    ):
        raise SystemExit("중단: 2020~2025 OOF 리드가 tbl_leadtime 과 다르다.")
    s26_bun = AS.leadtime_from(
        t24[usable], AS.events_from(bundle, T10K, 2026), m_bun, AS.rules_2026(t24, T10K), T10K
    )[0]
    comb = {
        "api": combined(s_o_api, d_o_api, lead["10k"]["api_summary"], lead["10k"]["api_detail"]),
        "bundle_only": combined(s_o_bun, d_o_bun, s26_bun, lead["10k"]["bundle_detail"]),
    }

    # 5) 강정·고령 4~6월(1k)
    gj = PH.gjgr_may18(t24)
    first_watch = gj[gj["감시(1k): q90_cqr≥1k"]]["base_date"].min()

    # 6) 번들 정답으로 바꾼 2026 지표
    obs_saved = t24["target_cells"].astype(float)
    obs_bun = AS.bundle_targets(t24, bundle).where(test)
    met_saved, met_bun = AS.metrics_with(t24, obs_saved), AS.metrics_with(t24, obs_bun)
    met_diff = AS.max_abs_diff(met_saved, met_bun)

    note = (
        f"- T24 동결 커밋 `{COMMIT}` 뒤 1회(2026-10-26 13:19 KST) 만든 2026 사후 예측(`data/processed/posthoc_2026_T24.parquet`, "
        f"sha256 `{SHA_T24[:16]}…`)을 다시 집계한 표다. 예측은 다시 하지 않았다.\n"
        "- T24 의 2026 은 블라인드가 아니다: 팀은 v2.1 의 2026 결과를 이미 봤다. T24 는 사전등록(PREREG_contingency 7절, 커밋 960d76f)대로 "
        f"학습·동결했고(동결 커밋 `{COMMIT}`), 2026 사후 계산은 그 뒤 한 번만 했다. 결과와 무관하게 모델·전환 규칙을 바꾸지 않는다.\n"
        "- 같은 함수로 v2.1(이력) 저장 예측을 집계하면 기존 보고값(posthoc_2026_v21_detail.json·tbl_metrics_by_definition.json·"
        "tbl_posthoc_answer_source.json)과 같다(절차 재현 확인). T24 통합 값은 posthoc_2026_T24_summary.json 과 같다.\n"
        "- 리드타임 정의는 2026 경계 사건 표와 같다(첫 초과 측정일 E 이전 28일 안, 직전 초과 다음 날부터). 관심 = 1,000 cells/mL. "
        "번들 = 대회 번들 algae_measure.csv(2026-09-10, 해평·강정고령 09-07 까지)만으로 만든 사건과, 번들만으로 같은 예측이 나오는 기준일.\n"
    )
    comb_rows = "\n".join(
        f"| {lab} | {v['사건 수']} | {v['감시 포착']} | {v['포착 비율']:.3f} | {v['중앙 리드(E, 일)']:g} | "
        f"{v['중앙 리드(D, 일)']:g} | {v['지속성 포착']} |"
        for lab, v in (("2020~2026 공공 API", comb["api"]), ("2020~2026 번들 정답만", comb["bundle_only"]))
    )
    md = (
        "# 2026 사후 계산 세부 — T24(지점별·정의별·관심 1k 리드타임·번들 정답·강정·고령 4~6월)\n\n"
        + note
        + "\n## 1. 지점별 2026 지표(test 124 조합)\n"
        + PH._md(sites.drop(columns=["station_id"]))
        + "\n\n## 2. 정의별 지표(5지점 통합·지점 평균)\n\n"
        + "2025 = 같은 252행(Final 폴드 OOF: ≤2024 적합 = T24 학습 행, v2.1 Final 폴드와 같은 값), 2026 = test 124 조합.\n\n"
        + MD._md(def_table(by_def))
        + "\n\n**해석**: "
        + interpretation(by_def)
        + "\n\n### 2026 지점별(정의별)\n\n"
        + MD._md(def_site_table(by_def["2026"]))
        + f"\n\n## 3. 리드타임 — 2026 관심(1k) 사건(API {lead['1k']['n_events_api']}건·번들 {lead['1k']['n_events_bundle']}건)\n\n"
        + PH._md(lead["1k"]["compare"])
        + "\n\n### 관심(1k) 사건별 상세(API)\n"
        + PH._md(lead["1k"]["api_detail"])
        + "\n\n### 관심(1k) 사건별 상세(번들 정답만)\n"
        + PH._md(lead["1k"]["bundle_detail"])
        + "\n\n## 4. 경계(10k) 리드 API/번들과 2020~2026 합계\n\n"
        + PH._md(lead["10k"]["compare"])
        + "\n\n| 집계 | 사건 수 | 감시 포착 | 포착 비율 | 중앙 리드(E, 일) | 중앙 리드(D, 일) | 지속성 포착 |\n"
        + "|---|---|---|---|---|---|---|\n"
        + comb_rows
        + "\n\n## 5. 강정·고령 4~6월 — 1k 기준 점등 시점(T24, 방법설명서 표 10-2 원천)\n"
        + PH._md(gj, nd=1)
        + "\n\n## 6. 정답을 번들 값으로 바꾼 2026 지표(T24, test 124 조합)\n\n"
        + f"저장 정답과 번들 정답의 지표 최대 절대 차 {met_diff:.1e}.\n\n"
        + PH._md(pd.DataFrame([{"정답": "저장(격리 로더)", **met_saved}, {"정답": "번들", **met_bun}]))
        + "\n"
    )
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")
    payload = {
        "_about": "T24 2026 사후 세부 재집계(python -m algaecast.eval.posthoc_t24_detail). 저장 예측 재집계, 예측 재실행 없음. 블라인드 아님.",
        "commit": COMMIT,
        "source": f"data/processed/posthoc_2026_T24.parquet sha256 {SHA_T24}",
        "sites": sites.to_dict(orient="records"),
        "by_definition": by_def,
        "lead_1k": {
            k: lead["1k"][k]
            for k in ("compare", "api_detail", "bundle_detail", "n_events_api", "n_events_bundle")
        },
        "lead_10k": {k: lead["10k"][k] for k in ("compare", "api_detail", "bundle_detail")},
        "combined_2020_2026": comb,
        "gjgr_2026_1k": gj.drop(columns=["target_cells"]).to_dict(orient="records"),
        "gjgr_first_watch_1k_base_date": (
            None if pd.isna(first_watch) else str(pd.Timestamp(first_watch).date())
        ),
        "metrics_2026_bundle_answers": {"saved": met_saved, "bundle": met_bun, "max_abs_diff": met_diff},
    }
    payload = {
        k: (
            {
                kk: (vv.to_dict(orient="records") if isinstance(vv, pd.DataFrame) else vv)
                for kk, vv in v.items()
            }
            if isinstance(v, dict)
            else v
        )
        for k, v in payload.items()
    }
    OUT_JSON.write_text(
        json.dumps(AS.clean(payload), ensure_ascii=False, indent=1, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(sites.round(3).to_string(index=False))
    print(def_table(by_def).to_string(index=False))
    print(interpretation(by_def))
    print(lead["1k"]["compare"].to_string(index=False))
    print(lead["10k"]["compare"].to_string(index=False))
    print(comb)
    print(gj.round(1).to_string(index=False))
    print("번들 정답 지표 최대 차", met_diff)
    print("→", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
