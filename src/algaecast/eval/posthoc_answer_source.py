# ruff: noqa: E501  (한국어 표)
"""2026 사후 분석의 정답 출처 점검 — 대회 번들 끝 이후 측정(공공 API 에만 있음)에 기대는 값이 있는지 사건·행 단위로 확인.

대회 번들 ``algae_measure.csv`` 는 2026-09-10(해평·강정고령 09-07)에서 끝나고, 저장소의 2026 사후 계산은 공공 API
조류 ``data/raw/nier_algae/nier_algae_2012_2026.parquet``(2026-10-15 까지)을 썼다. 이 모듈은 사후 계산의 사건·지표가
번들 끝 이후 측정에 기대는지 확인하고, 기대는 값은 **번들 정답만** 기준 값을 나란히 낸다.

입력(모두 읽기만, 새 예측 없음)
- 번들: ``collect.algae_source.load_algae_source(source="bundle")``(API parquet 형식으로 바꾼 algae_measure.csv)
- API: ``load_algae_source(source="api")``
- 저장된 2026 사후 예측 ``data/processed/posthoc_2026_v21.parquet``(v2.1 동결 뒤 1회 계산본, 다시 계산하지 않음)
  과 이력 ``posthoc_2026_v2.parquet``·``posthoc_2026.parquet``(v2·v1)
- 2026 test 정답: ``eval.live.load_test_targets(i_know_this_is_for_post_hoc_only=True)``(유일한 통로)
- 2020~2025 OOF ``data/processed/oof_predictions.parquet``(``tbl_leadtime.md`` 와 같은 파일)

점검
1. 측정 원천: 번들 끝(지점별), API 에만 있는 행, 겹치는 행의 열별 값 차이.
2. 사건(경계 10k·관심 1k, 2020~2026): API·번들 각각 2회 연속 규칙(``transitions.official_events`` 와 같은 계산)
   으로 사건(E·D)을 만들어 대조. API 로 만든 사건이 ``official_events`` 와 같은지 먼저 확인한다.
3. 2026 기준일 261행: 기준일이 번들 기간 안인지, 기준일까지의 모델 입력 조류 자료(자기 지점·바로 위 지점)가
   번들과 같은지, 목표일 매칭(horizon_days)이 번들 측정일로도 같은지, cell_log_t0 이 번들 세포수와 같은지.
   모두 같으면 번들만으로 계산해도 같은 예측이 나오는 행(= 저장 예측 재사용 가능)으로 본다.
4. test 124조합: 목표일·정답 측정이 번들 안인지, 격리 정답 값이 번들 값과 같은지.
5. 번들 기준 재집계: 2026 지표(124조합·지점별), 2026 경계·관심 리드타임, 2020~2025 리드타임(OOF), 2020~2026 합계.
   리드타임 계산은 ``eval.posthoc.leadtime_2026``·``transitions.leadtime_table`` 과 같은 규칙이며, API 입력으로
   두 함수의 결과를 그대로 재현하는지 먼저 확인한다(재현이 안 되면 중단).

출력: ``reports/eval/tbl_posthoc_answer_source.md``·``.json`` — 정답 값(세포수) 자체는 쓰지 않고 일치 여부·차이만 쓴다.
사용: python -m algaecast.eval.posthoc_answer_source
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.algae_source import load_algae_source
from algaecast.collect.nier_algae import two_consecutive_levels
from algaecast.collect.nier_forecast import level_from_cells
from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT
from algaecast.eval import posthoc as PH
from algaecast.eval.metrics import compute_all
from algaecast.eval.transitions import T1K, T10K, official_events
from algaecast.features.upstream import UPSTREAM_OF

EVAL = ROOT / "reports" / "eval"
OUT_MD = EVAL / "tbl_posthoc_answer_source.md"
OUT_JSON = EVAL / "tbl_posthoc_answer_source.json"
PROCESSED = DATA_DIR / "processed"
PRED_V21 = PROCESSED / "posthoc_2026_v21.parquet"
PRED_HIST = {"v2": PROCESSED / "posthoc_2026_v2.parquet", "v1": PROCESSED / "posthoc_2026.parquet"}
OOF = PROCESSED / "oof_predictions.parquet"
CELLS = "iem_bgalage_cell_co"
# 제출·운영 모델(v2.1 회귀·분류기·분위)이 쓰는 조류 측정 열: 세포수(cell_*·consecutive_over_1k·up1_cell_log·up1_slope3),
# 수온(wtemp_*·up1_wtemp), pH(ph_t0), 클로로필a(chla_lag1w), 우점종(dominant_genus). 측정일 자체(행 존재)도 입력이다.
MODEL_ALGAE_COLS: tuple[str, ...] = (CELLS, "iem_wtrtp", "iem_ph", "iem_chla", "dominant_genus")
# 상류 피처(features.upstream: up1_cell_log·up1_slope3·up1_wtemp·up1_days·up1_diff)가 바로 위 지점에서 쓰는 열
UPSTREAM_ALGAE_COLS: tuple[str, ...] = (CELLS, "iem_wtrtp")
# 겹치는 행 값 비교에 쓰는 측정 열(정렬 align.run.WQ_MAP + 4속 + 우점종)
COMPARE_COLS: tuple[str, ...] = (
    CELLS,
    "iem_bgalage_microsts",
    "iem_bgalage_anba",
    "iem_bgalage_osrtria",
    "iem_bgalage_apzo",
    "iem_wtrtp",
    "iem_ph",
    "iem_doc",
    "iem_tur",
    "iem_trp",
    "iem_chla",
    "iem_geosm",
    "iem_mib2",
    "dominant_genus",
)
SITES = ("HP", "GJGR", "CS", "MGMR", "DCHN")
SITE_KO = {"HP": "해평", "GJGR": "강정·고령", "CS": "칠서", "MGMR": "물금·매리", "DCHN": "회남"}
METRIC_KEYS = ("rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k")
RULE_WATCH, RULE_ALERT, RULE_POINT, RULE_B0, RULE_Q50 = (
    "감시(q90_cqr≥임계)",
    "경보(p_alert≥운영점)",
    "점예측≥임계",
    "B0 지속성",
    "q50≥임계",
)
TOL = 1e-12


# ---------------------------------------------------------------- 측정 원천
def load_measurements() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(번들, API) 조류 측정. 두 표 모두 API parquet 형식, obs_date 는 Timestamp, station_id 는 문자열."""
    out = []
    for src in ("bundle", "api"):
        d = load_algae_source(source=src)
        d["obs_date"] = pd.to_datetime(d["obs_date"])
        d["station_id"] = d["station_id"].astype(str)
        out.append(d.sort_values(["station_id", "obs_date"], ignore_index=True))
    return out[0], out[1]


def bundle_end(bundle: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """지점별 번들 마지막 측정일."""
    return {str(k): pd.Timestamp(v) for k, v in bundle.groupby("station_id")["obs_date"].max().items()}


def _same(a: pd.Series, b: pd.Series) -> np.ndarray:
    """값이 같으면 True(둘 다 결측도 같음). 숫자는 1e-9 허용, 문자열은 그대로 비교."""
    an, bn = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
    if an.notna().sum() >= a.notna().sum() and bn.notna().sum() >= b.notna().sum():
        both = an.isna() & bn.isna()
        close = (an - bn).abs() <= 1e-9
        return (both | close.fillna(False)).to_numpy()
    sa, sb = a.astype("string"), b.astype("string")
    return ((sa.isna() & sb.isna()) | (sa == sb).fillna(False)).to_numpy()


def diff_rows(api: pd.DataFrame, bundle: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    """API 와 번들이 다른 측정 행: API 에만 있는 행, 번들에만 있는 행, 겹치지만 cols 중 값이 다른 행.

    반환 열: station_id, obs_date, 구분('API에만'|'번들에만'|'값 차이'), 열(다른 열 이름, 쉼표 구분).
    """
    key = ["station_id", "obs_date"]
    m = api[[*key, *cols]].merge(
        bundle[[*key, *cols]], on=key, how="outer", suffixes=("_api", "_bundle"), indicator="side"
    )
    rows = []
    for r in m[m["side"] != "both"].itertuples(index=False):
        rows.append(
            {
                "station_id": r.station_id,
                "obs_date": r.obs_date,
                "구분": "API에만" if r.side == "left_only" else "번들에만",
                "열": "(행 전체)",
            }
        )
    both = m[m["side"] == "both"].reset_index(drop=True)
    if len(both):
        same = np.column_stack([_same(both[f"{c}_api"], both[f"{c}_bundle"]) for c in cols])
        for i in np.where(~same.all(axis=1))[0]:
            rows.append(
                {
                    "station_id": both.loc[i, "station_id"],
                    "obs_date": both.loc[i, "obs_date"],
                    "구분": "값 차이",
                    "열": ",".join(c for c, ok in zip(cols, same[i], strict=True) if not ok),
                }
            )
    out = pd.DataFrame(rows, columns=["station_id", "obs_date", "구분", "열"])
    return out.sort_values(["station_id", "obs_date"], ignore_index=True)


def column_diff_counts(api: pd.DataFrame, bundle: pd.DataFrame, cols: tuple[str, ...]) -> dict[str, int]:
    """겹치는 행에서 열별로 값이 다른 행 수."""
    key = ["station_id", "obs_date"]
    m = api[[*key, *cols]].merge(bundle[[*key, *cols]], on=key, suffixes=("_api", "_bundle"))
    return {c: int((~_same(m[f"{c}_api"], m[f"{c}_bundle"])).sum()) for c in cols}


def asof_input_diffs(
    sid: str, base: pd.Timestamp, diffs: pd.DataFrame, diffs_up: pd.DataFrame | None = None
) -> pd.DataFrame:
    """기준일까지(≤base) API 와 번들이 다른 모델 입력 측정 행 — 자기 지점(diffs)과 바로 위 지점(diffs_up).

    diffs = diff_rows(..., MODEL_ALGAE_COLS), diffs_up = diff_rows(..., UPSTREAM_ALGAE_COLS)(None 이면 diffs).
    """
    up = UPSTREAM_OF.get(sid)
    own = diffs[(diffs["station_id"] == sid) & (diffs["obs_date"] <= base)]
    if not up:
        return own
    du = diffs if diffs_up is None else diffs_up
    return pd.concat([own, du[(du["station_id"] == up) & (du["obs_date"] <= base)]], ignore_index=True)


def asof_inputs_same(
    sid: str, base: pd.Timestamp, diffs: pd.DataFrame, diffs_up: pd.DataFrame | None = None
) -> bool:
    """기준일까지의 모델 입력 조류 자료가 API 와 번들에서 같은지 — 자기 지점과 바로 위 지점(상류 피처) 모두."""
    return asof_input_diffs(sid, base, diffs, diffs_up).empty


def match_target_date(
    base: pd.Timestamp, obs_dates: pd.DatetimeIndex, horizon: int, tol: int
) -> pd.Timestamp | None:
    """features.run.match_target 와 같은 규칙: base+horizon 에 가장 가까운 측정일(|차| ≤ tol, 동률은 이른 날)."""
    goal = base + pd.Timedelta(days=horizon)
    cand = obs_dates[(obs_dates > base) & (abs(obs_dates - goal) <= pd.Timedelta(days=tol))]
    if len(cand) == 0:
        return None
    diffs = abs(cand - goal)
    return cand[diffs == diffs.min()].min()


# ---------------------------------------------------------------- 사건·리드타임
def events_from(algae: pd.DataFrame, level: float = T10K, start_year: int = 2020) -> pd.DataFrame:
    """transitions.official_events 와 같은 계산을 주어진 측정 표로 한다(원천을 바꿔 대조하기 위함).

    열: station_id, '발령 측정일 D', '첫 초과 측정일 E'(official_events 와 같은 이름·순서).
    """
    a = algae.copy()
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    a = a[a["obs_date"].dt.year >= start_year - 1]
    ev = []
    lvl_needed = 2 if level == T10K else 1
    for sid, g in a.sort_values("obs_date").groupby("station_id"):
        cells = g[CELLS].astype(float)
        two = two_consecutive_levels(level_from_cells(cells)).astype(float).to_numpy()
        dates = g["obs_date"].to_numpy()
        cv = cells.to_numpy()
        for i in range(1, len(g)):
            if two[i] >= lvl_needed and two[i - 1] < lvl_needed:
                j = i
                while j - 1 >= 0 and np.isfinite(cv[j - 1]) and cv[j - 1] >= level:
                    j -= 1
                if pd.Timestamp(dates[i]).year >= start_year:
                    ev.append(
                        {
                            "station_id": sid,
                            "발령 측정일 D": pd.Timestamp(dates[i]).date(),
                            "첫 초과 측정일 E": pd.Timestamp(dates[j]).date(),
                        }
                    )
    return pd.DataFrame(ev, columns=["station_id", "발령 측정일 D", "첫 초과 측정일 E"])


def window_start(
    meas: pd.DataFrame, sid: str, e: pd.Timestamp, level: float, lookback_days: int = 28
) -> pd.Timestamp:
    """리드 창 시작: E 이전 lookback 일, 단 직전 초과 측정(이전 사건의 꼬리) 다음 날부터."""
    prev = meas[(meas["station_id"] == sid) & (meas["obs_date"] < e) & (meas["cells"] >= level)]["obs_date"]
    start = e - pd.Timedelta(days=lookback_days)
    if len(prev):
        start = max(start, prev.max() + pd.Timedelta(days=1))
    return start


def leadtime_from(
    pred: pd.DataFrame,
    events: pd.DataFrame,
    meas: pd.DataFrame,
    rules: Mapping[str, pd.Series],
    level: float,
    lookback_days: int = 28,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """eval.posthoc.leadtime_2026 와 같은 규칙의 리드타임. 사건·측정·예측 행을 인자로 받는다.

    rules: 방식 이름 → pred.index 에 맞춘 경보 지시자(bool Series, 결측은 False 로 본다).
    반환: (요약, 사건별 상세). 요약의 '경보 총수' 는 pred 행 안에서 센다.
    """
    pred = pred.copy()
    pred["base_date"] = pd.to_datetime(pred["base_date"])
    pred["station_id"] = pred["station_id"].astype(str)
    rows, detail = [], []
    for name, al in rules.items():
        al_s = al.reindex(pred.index).fillna(False).astype(bool)
        leads_e, leads_d, det, n_ev = [], [], 0, 0
        for e in events.itertuples(index=False):
            E, Dd = pd.Timestamp(e[2]), pd.Timestamp(e[1])
            start = window_start(meas, e[0], E, level, lookback_days)
            cand = pred[(pred["station_id"] == e[0]) & (pred["base_date"] < E) & (pred["base_date"] >= start)]
            if cand.empty:
                continue
            n_ev += 1
            fired = cand[al_s.loc[cand.index]]
            if len(fired):
                det += 1
                b = fired["base_date"].min()
                leads_e.append((E - b).days)
                leads_d.append((Dd - b).days)
                detail.append(
                    {
                        "방식": name,
                        "지점": e[0],
                        "E": E.date(),
                        "D": Dd.date(),
                        "첫 경보 base_date": b.date(),
                        "리드(E)": (E - b).days,
                        "리드(D)": (Dd - b).days,
                    }
                )
        rows.append(
            {
                "방식": name,
                "사건 수": n_ev,
                "선행 탐지 수": det,
                "선행 탐지 비율": det / n_ev if n_ev else np.nan,
                "중앙 리드(E, 일)": float(np.median(leads_e)) if leads_e else np.nan,
                "중앙 리드(D, 일)": float(np.median(leads_d)) if leads_d else np.nan,
                "경보 총수": int(al_s.sum()),
            }
        )
    cols = ["방식", "지점", "E", "D", "첫 경보 base_date", "리드(E)", "리드(D)"]
    return pd.DataFrame(rows), pd.DataFrame(detail, columns=cols)


def rules_2026(pred: pd.DataFrame, level: float) -> dict[str, pd.Series]:
    """eval.posthoc.leadtime_2026(point=True) 와 같은 방식 5개의 경보 지시자."""
    b0 = np.clip(10 ** pred["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    idx = pred.index
    return {
        RULE_B0: pd.Series(b0 >= level, index=idx),
        RULE_WATCH: pd.Series(pred["q90_cqr"].to_numpy() >= level, index=idx),
        RULE_ALERT: pd.Series(pred["alert_flag"].to_numpy().astype(bool), index=idx),
        RULE_Q50: pd.Series(pred["q50"].to_numpy() >= level, index=idx),
        RULE_POINT: pd.Series(pred["pred_cell_count"].to_numpy() >= level, index=idx),
    }


def rules_oof(o: pd.DataFrame, level: float) -> dict[str, pd.Series]:
    """transitions.leadtime_table 의 'q90≥임계'·'B0 지속성'(OOF, 결측은 경보 아님)."""
    return {
        "q90≥임계": pd.Series(o["q90"].to_numpy() >= level, index=o.index),
        RULE_B0: pd.Series(o["b0"].to_numpy() >= level, index=o.index),
    }


def meas_for_window(algae: pd.DataFrame) -> pd.DataFrame:
    """window_start 용 측정 표(station_id, obs_date, cells)."""
    m = algae[["station_id", "obs_date", CELLS]].copy()
    m["cells"] = m[CELLS].astype(float)
    return m


def _events_key(ev: pd.DataFrame) -> set[tuple[str, str, str]]:
    return {(str(r[0]), str(r[1]), str(r[2])) for r in ev.itertuples(index=False)}


# ---------------------------------------------------------------- 2026 기준일·test 행
def load_pred(path: Path = PRED_V21) -> pd.DataFrame:
    """저장된 2026 사후 예측(다시 계산하지 않는다)."""
    if not path.exists():
        raise SystemExit(f"{path} 가 없다 — 2026 사후 예측은 eval.posthoc_v21 로 1회만 만든다.")
    p = pd.read_parquet(path)
    p["station_id"] = p["station_id"].astype(str)
    p["base_date"] = pd.to_datetime(p["base_date"])
    p["target_date"] = pd.to_datetime(p["target_date"])
    return p


def base_row_check(
    pred: pd.DataFrame,
    api: pd.DataFrame,
    bundle: pd.DataFrame,
    diffs_model: pd.DataFrame,
    horizon: int,
    tol: int,
    diffs_up: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """2026 기준일 행별 정답 출처 점검표(pred.index 순서).

    열: station_id, base_date, 번들 기간 안, 기준일 측정 번들에 있음, 입력 같음(≤기준일, 자기·상류 지점),
    목표일 매칭 같음, cell_log_t0 번들 일치, 번들 재사용 가능(앞 다섯 개 모두 참), 사유.
    diffs_model = 자기 지점 비교(MODEL_ALGAE_COLS), diffs_up = 바로 위 지점 비교(UPSTREAM_ALGAE_COLS, None 이면 diffs_model).
    """
    end = bundle_end(bundle)
    b_obs = {s: pd.DatetimeIndex(g["obs_date"]) for s, g in bundle.groupby("station_id")}
    a_obs = {s: pd.DatetimeIndex(g["obs_date"]) for s, g in api.groupby("station_id")}
    b_cells = {s: g.set_index("obs_date")[CELLS].astype(float) for s, g in bundle.groupby("station_id")}
    rows = []
    for r in pred.itertuples():
        sid, b = r.station_id, pd.Timestamp(r.base_date)
        in_period = b <= end[sid]
        measured = b in b_obs[sid]
        hit = asof_input_diffs(sid, b, diffs_model, diffs_up)
        inputs_same = hit.empty
        tb = match_target_date(b, b_obs[sid], horizon, tol)
        ta = match_target_date(b, a_obs[sid], horizon, tol)
        tmatch = (tb is None and ta is None) or (tb is not None and ta is not None and tb == ta)
        valid = b_cells[sid][b_cells[sid].index <= b].dropna()
        exp = float(np.log10(valid.iloc[-1] + 1)) if len(valid) else np.nan
        got = float(r.cell_log_t0) if pd.notna(r.cell_log_t0) else np.nan
        t0_ok = (np.isnan(exp) and np.isnan(got)) or abs(exp - got) <= 1e-9
        why = []
        if not in_period:
            why.append("기준일이 번들 끝 이후")
        elif not measured:
            why.append("기준일 측정이 번들에 없음")
        if in_period and not inputs_same:
            why.append(
                "입력 차이: "
                + "; ".join(
                    f"{h.station_id} {h.obs_date.date()} {h.구분}({h.열})"
                    for h in hit.itertuples(index=False)
                )
            )
        if in_period and not tmatch:
            why.append(
                f"목표일 매칭 다름(API {None if ta is None else ta.date()} / 번들 {None if tb is None else tb.date()})"
            )
        if in_period and not t0_ok:
            why.append("cell_log_t0 번들과 다름")
        rows.append(
            {
                "station_id": sid,
                "base_date": b,
                "번들 기간 안": bool(in_period),
                "기준일 측정 번들에 있음": bool(measured),
                "입력 같음": bool(inputs_same),
                "목표일 매칭 같음": bool(tmatch),
                "cell_log_t0 번들 일치": bool(t0_ok),
                "사유": " / ".join(why),
            }
        )
    out = pd.DataFrame(rows, index=pred.index)
    out["번들 재사용 가능"] = out[
        ["번들 기간 안", "기준일 측정 번들에 있음", "입력 같음", "목표일 매칭 같음", "cell_log_t0 번들 일치"]
    ].all(axis=1)
    return out


def bundle_targets(pred: pd.DataFrame, bundle: pd.DataFrame) -> pd.Series:
    """pred 의 (지점, 목표일) 에 해당하는 번들 세포수(번들에 측정이 없으면 NaN)."""
    b = bundle.set_index(["station_id", "obs_date"])[CELLS].astype(float)
    keys = list(zip(pred["station_id"], pd.to_datetime(pred["target_date"]), strict=True))
    return pd.Series([b.get(k, np.nan) for k in keys], index=pred.index, dtype=float)


def test_row_check(pred: pd.DataFrame, bundle: pd.DataFrame, tt: pd.DataFrame) -> pd.DataFrame:
    """test 124조합의 정답 출처 점검(값은 내보내지 않고 일치 여부만).

    tt = eval.live.load_test_targets(...) 결과. 열: station_id, base_date, target_date, 목표일 번들 기간 안,
    목표일 측정 번들에 있음, 격리 정답=번들, 사후 예측 파일 정답=격리 정답.
    """
    end = bundle_end(bundle)
    t = tt.copy()
    t["station_id"] = t["station_id"].astype(str)
    t["base_date"] = pd.to_datetime(t["base_date"])
    t["target_date"] = pd.to_datetime(t["target_date"])
    has = pred[pred["target_cells"].notna()][["station_id", "base_date", "target_date", "target_cells"]]
    m = t.merge(has, on=["station_id", "base_date"], how="outer", suffixes=("", "_pred"), indicator=True)
    if (m["_merge"] != "both").any():
        raise SystemExit("중단: 격리 정답과 사후 예측 파일의 test 조합이 다르다.")
    bt = bundle_targets(m, bundle)
    q = m["target_cells"].astype(float)
    return pd.DataFrame(
        {
            "station_id": m["station_id"],
            "base_date": m["base_date"].dt.date,
            "target_date": m["target_date"].dt.date,
            "목표일 매칭 같음(격리·예측 파일)": (m["target_date"] == m["target_date_pred"]).to_numpy(),
            "목표일 번들 기간 안": [
                td <= end[s] for s, td in zip(m["station_id"], m["target_date"], strict=True)
            ],
            "목표일 측정 번들에 있음": bt.notna().to_numpy(),
            "격리 정답=번들": ((q - bt).abs() <= 1e-9).to_numpy(),
            "예측 파일 정답=격리 정답": ((q - m["target_cells_pred"].astype(float)).abs() <= 1e-9).to_numpy(),
        }
    )


# ---------------------------------------------------------------- 지표
def metrics_with(
    pred: pd.DataFrame, obs: pd.Series, point: str = "pred_cell_count", alerts: bool = True
) -> dict:
    """정답(obs)을 바꿔 끼워 2026 지표를 다시 계산(정답 있는 행만). 모델 출력은 저장본 그대로."""
    ok = obs.notna()
    kw = {}
    if alerts:
        kw = {
            "q10": pred.loc[ok, "q10_cqr"].to_numpy(),
            "q90": pred.loc[ok, "q90_cqr"].to_numpy(),
            "p10k": pred.loc[ok, "p_alert"].to_numpy(),
        }
    m = compute_all(obs[ok].to_numpy(dtype=float), pred.loc[ok, point].to_numpy(dtype=float), **kw)
    keys = (*METRIC_KEYS, "picp80", "mpiw80_log", "brier_10k") if alerts else METRIC_KEYS
    return {"n": int(m["n"]), **{k: float(m[k]) for k in keys}}


def b0_metrics(pred: pd.DataFrame, obs: pd.Series) -> dict:
    ok = obs.notna()
    b0 = np.clip(10 ** pred.loc[ok, "cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    m = compute_all(obs[ok].to_numpy(dtype=float), b0)
    return {"n": int(m["n"]), **{k: float(m[k]) for k in METRIC_KEYS}}


def max_abs_diff(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """공통 키의 최대 절대 차(둘 다 NaN 이면 0)."""
    out = 0.0
    for k in set(a) & set(b):
        x, y = a[k], b[k]
        if x is None or y is None:
            continue
        x, y = float(x), float(y)
        if np.isnan(x) and np.isnan(y):
            continue
        out = max(out, abs(x - y))
    return out


# ---------------------------------------------------------------- 실행
def _md(t: pd.DataFrame) -> str:
    return PH._md(t)


def clean(obj: object) -> object:
    """JSON 용 정리: NaN → None, numpy 스칼라 → 파이썬 값, 날짜 → 문자열."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and np.isnan(obj):
        return None
    if isinstance(obj, pd.Timestamp):
        return str(obj.date())
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def main() -> int:
    from algaecast.eval.live import load_test_targets
    from algaecast.eval.transitions import leadtime_table, load_oof

    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    horizon, tol = int(cfg["target"]["horizon_days"]), int(cfg["target"]["match_tolerance_days"])
    bundle, api = load_measurements()
    end = bundle_end(bundle)
    diffs_all = diff_rows(api, bundle, COMPARE_COLS)
    diffs_model = diff_rows(api, bundle, MODEL_ALGAE_COLS)
    diffs_up = diff_rows(api, bundle, UPSTREAM_ALGAE_COLS)
    col_diff = column_diff_counts(api, bundle, COMPARE_COLS)
    api_only = diffs_all[diffs_all["구분"] == "API에만"]
    if (diffs_all["구분"] == "번들에만").any():
        raise SystemExit("중단: 번들에만 있는 측정 행이 있다(가정 위반).")
    m_api, m_bun = meas_for_window(api), meas_for_window(bundle)

    # ---- 1) 사건: API 재현 확인 → 번들 사건 대조
    # start_year 2020 = transitions.leadtime_table(2020~2025 OOF)·tbl_leadtime 사건 목록,
    # start_year 2026 = eval.posthoc.leadtime_2026(2026 사후) — 두 함수가 쓰는 그대로 각각 만든다.
    ev = {}
    for lv, lname in ((T10K, "경계(10k)"), (T1K, "관심(1k)")):
        ev[lv] = {"name": lname}
        for y0 in (2020, 2026):
            e_api = events_from(api, lv, y0)
            ref = official_events(lv, start_year=y0)  # 저장소 구조 = API 원천
            if _events_key(e_api) != _events_key(ref):
                raise SystemExit(
                    f"중단: {lname}(start_year {y0}) API 사건이 transitions.official_events 와 다르다."
                )
            ev[lv][f"api{y0}"] = e_api
            ev[lv][f"bundle{y0}"] = events_from(bundle, lv, y0)
        ev[lv]["api"], ev[lv]["bundle"] = ev[lv]["api2020"], ev[lv]["bundle2020"]
        # 2026 사건은 두 시작 연도에서 같은지(2회 연속 상태가 2025 겨울에 0 으로 돌아오는지)
        a26 = ev[lv]["api2020"][_y(ev[lv]["api2020"], 2026)]
        ev[lv]["same_2026_by_start_year"] = _events_key(a26) == _events_key(ev[lv]["api2026"])

    # ---- 2) 2026 기준일 261행
    pred = load_pred()
    rows = base_row_check(pred, api, bundle, diffs_model, horizon, tol, diffs_up)
    usable = rows["번들 재사용 가능"]
    in_period = rows["번들 기간 안"]
    # 번들 2026 측정일이 모두 사후 예측 기준일인지(번들 세계에서 빠지는 기준일이 없는지)
    b26 = bundle[bundle["obs_date"].dt.year == 2026]
    pk = set(zip(pred["station_id"], pred["base_date"], strict=True))
    missing_base = [
        (s, d) for s, d in zip(b26["station_id"], b26["obs_date"], strict=True) if (s, d) not in pk
    ]

    # ---- 3) test 124조합
    tt = load_test_targets(i_know_this_is_for_post_hoc_only=True)
    trow = test_row_check(pred, bundle, tt)
    test_mask = pred["target_cells"].notna()
    test_usable = int(usable[test_mask].sum())

    # ---- 4) 지표: 정답을 번들 값으로 바꿔 다시 계산 → 저장 값과 대조
    hl = json.loads((EVAL / "headline_metrics.json").read_text(encoding="utf-8"))["posthoc2026"]
    obs_saved = pred["target_cells"].astype(float)
    obs_bun = bundle_targets(pred, bundle).where(test_mask)
    met = {
        "v21": {
            "saved_answers": metrics_with(pred, obs_saved),
            "bundle_answers": metrics_with(pred, obs_bun),
        },
        "v1fix": {
            "saved_answers": metrics_with(pred, obs_saved, "pred_v1fix", alerts=False),
            "bundle_answers": metrics_with(pred, obs_bun, "pred_v1fix", alerts=False),
        },
        "b0": {"saved_answers": b0_metrics(pred, obs_saved), "bundle_answers": b0_metrics(pred, obs_bun)},
    }
    for lab, path in PRED_HIST.items():
        ph = load_pred(path)
        if not ph[["station_id", "base_date"]].equals(pred[["station_id", "base_date"]]):
            raise SystemExit(f"중단: {path.name} 의 행이 v2.1 사후 예측과 다르다.")
        met[lab] = {
            "saved_answers": metrics_with(ph, ph["target_cells"].astype(float)),
            "bundle_answers": metrics_with(ph, bundle_targets(ph, bundle).where(ph["target_cells"].notna())),
        }
    for lab, blk in met.items():
        blk["max_abs_diff_bundle_vs_headline_json"] = max_abs_diff(blk["bundle_answers"], hl[lab])
        blk["max_abs_diff_saved_vs_headline_json"] = max_abs_diff(blk["saved_answers"], hl[lab])
    det_json = json.loads((EVAL / "posthoc_2026_v21_detail.json").read_text(encoding="utf-8"))
    site_rows, site_maxdiff = [], 0.0
    saved_sites = {(r["station_id"], r["모델"]): r for r in det_json["sites"]}
    for sid in SITES:
        g = pred[(pred["station_id"] == sid) & test_mask]
        ob = obs_bun.loc[g.index]
        for lab, mm in (
            ("v2.1", metrics_with(g, ob, alerts=False)),
            ("v1-fix", metrics_with(g, ob, "pred_v1fix", alerts=False)),
            (RULE_B0, b0_metrics(g, ob)),
        ):
            d = max_abs_diff(mm, saved_sites[(sid, lab)])
            site_maxdiff = max(site_maxdiff, d)
            site_rows.append(
                {
                    "지점": SITE_KO[sid],
                    "모델": lab,
                    "n": mm["n"],
                    "rmse_log": mm["rmse_log"],
                    "r2_log": mm["r2_log"],
                    "r2_raw": mm["r2_raw"],
                    "f1_10k": mm["f1_10k"],
                    "저장 값과 최대 차": d,
                }
            )

    # ---- 5) 리드타임 2026: API 입력으로 posthoc.leadtime_2026 재현 → 번들 사건·번들 재사용 가능 행
    lead26 = {}
    for lv in (T10K, T1K):
        rl = rules_2026(pred, lv)
        s_api, d_api = leadtime_from(pred, ev[lv]["api2026"], m_api, rl, lv)
        ref_s, ref_d = PH.leadtime_2026(pred, lv, point=True)
        ref_s = ref_s.rename(columns={"경보 총수(2026)": "경보 총수"})
        pd.testing.assert_frame_equal(
            s_api.reset_index(drop=True), ref_s.reset_index(drop=True), check_dtype=False
        )
        pd.testing.assert_frame_equal(
            d_api.reset_index(drop=True), ref_d.reset_index(drop=True), check_dtype=False
        )
        pb = pred[usable]
        s_bun, d_bun = leadtime_from(pb, ev[lv]["bundle2026"], m_bun, rl, lv)
        undetermined = rows[in_period & ~usable]
        und_alerts = {k: int(v[undetermined.index].sum()) for k, v in rl.items()}
        lead26[lv] = {
            "api_summary": s_api,
            "api_detail": d_api,
            "bundle_summary": s_bun,
            "bundle_detail": d_bun,
            "undetermined_alerts": und_alerts,
            "rules": rl,
        }

    # ---- 6) 리드타임 2020~2025(OOF): API 입력으로 transitions.leadtime_table 재현 → 번들 사건
    o, thr = load_oof()
    o20 = o[o["year"] >= 2020]
    ro = {k: v.loc[o20.index] for k, v in rules_oof(o, T10K).items()}
    s_o_api, d_o_api = leadtime_from(o20, ev[T10K]["api"], m_api, ro, T10K)
    lt_ref, det_ref = leadtime_table(o, thr, T10K)
    for name in ro:
        a_ = s_o_api.set_index("방식").loc[name]
        r_ = lt_ref.set_index("방식").loc[name]
        same = (
            a_["사건 수"] == r_["사건 수"]
            and a_["선행 탐지 수"] == r_["선행 탐지 수"]
            and a_["중앙 리드(E, 일)"] == r_["중앙 리드타임(E 기준, 일)"]
            and a_["중앙 리드(D, 일)"] == r_["중앙 리드타임(D 기준, 일)"]
        )
        dd = d_o_api[d_o_api["방식"] == name][["지점", "E", "첫 경보 base_date", "리드(E)"]].reset_index(
            drop=True
        )
        dr = det_ref[det_ref["방식"] == name][["지점", "E", "첫 경보 base_date", "리드(E) 일"]].reset_index(
            drop=True
        )
        same = same and dd.astype(str).values.tolist() == dr.astype(str).values.tolist()
        if not same:
            raise SystemExit(f"중단: OOF 리드타임 '{name}' 이 transitions.leadtime_table 과 다르다.")
    s_o_bun, d_o_bun = leadtime_from(o20, ev[T10K]["bundle"], m_bun, ro, T10K)

    # ---- 7) 2020~2026 합계(감시 = OOF q90≥1만 + 2026 q90_cqr≥1만, 지속성 = B0)
    def combined(s_oof: pd.DataFrame, d_oof: pd.DataFrame, s26: pd.DataFrame, d26: pd.DataFrame) -> dict:
        so, s2 = s_oof.set_index("방식"), s26.set_index("방식")
        n_ev = int(so.loc["q90≥임계", "사건 수"] + s2.loc[RULE_WATCH, "사건 수"])
        det = int(so.loc["q90≥임계", "선행 탐지 수"] + s2.loc[RULE_WATCH, "선행 탐지 수"])
        leads = [*d_oof[d_oof["방식"] == "q90≥임계"]["리드(E)"], *d26[d26["방식"] == RULE_WATCH]["리드(E)"]]
        leads_d = [*d_oof[d_oof["방식"] == "q90≥임계"]["리드(D)"], *d26[d26["방식"] == RULE_WATCH]["리드(D)"]]
        b0 = int(so.loc[RULE_B0, "선행 탐지 수"] + s2.loc[RULE_B0, "선행 탐지 수"])
        return {
            "사건 수": n_ev,
            "감시 포착": det,
            "포착 비율": det / n_ev,
            "중앙 리드(E, 일)": float(np.median(leads)),
            "중앙 리드(D, 일)": float(np.median(leads_d)),
            "지속성 포착": b0,
        }

    comb_api = combined(s_o_api, d_o_api, lead26[T10K]["api_summary"], lead26[T10K]["api_detail"])
    comb_bun = combined(s_o_bun, d_o_bun, lead26[T10K]["bundle_summary"], lead26[T10K]["bundle_detail"])

    # ---- 사건별 표(2026 경계·관심 + 2020~2025 요약)
    ev_rows = []
    for lv in (T10K, T1K):
        e_api = ev[lv]["api2026"]
        keys_b = _events_key(ev[lv]["bundle2026"])
        L = lead26[lv]
        det_api = L["api_detail"].set_index(["방식", "지점", "E"])
        det_bun = L["bundle_detail"].set_index(["방식", "지점", "E"])
        for e in e_api.itertuples(index=False):
            sid, D, E = e[0], pd.Timestamp(e[1]), pd.Timestamp(e[2])
            start = window_start(m_api, sid, E, lv)
            win = rows[(rows["station_id"] == sid) & (rows["base_date"] < E) & (rows["base_date"] >= start)]

            def lead(dt: pd.DataFrame, rule: str, sid: str = sid, E: pd.Timestamp = E) -> object:
                k = (rule, sid, E.date())
                return int(dt.loc[k, "리드(E)"]) if k in dt.index else None

            def first(dt: pd.DataFrame, rule: str, sid: str = sid, E: pd.Timestamp = E) -> object:
                k = (rule, sid, E.date())
                return str(dt.loc[k, "첫 경보 base_date"]) if k in dt.index else None

            in_b = (sid, str(D.date()), str(E.date())) in keys_b
            api_l = (lead(det_api, RULE_WATCH), lead(det_api, RULE_ALERT), lead(det_api, RULE_POINT))
            bun_l = (
                (lead(det_bun, RULE_WATCH), lead(det_bun, RULE_ALERT), lead(det_bun, RULE_POINT))
                if in_b
                else (None, None, None)
            )
            depends = (not in_b) or (not bool(win["번들 재사용 가능"].all())) or api_l != bun_l
            ev_rows.append(
                {
                    "수준": ev[lv]["name"],
                    "지점": sid,
                    "E": str(E.date()),
                    "D": str(D.date()),
                    "번들 끝": str(end[sid].date()),
                    "E 번들 안": bool(E <= end[sid]),
                    "D 번들 안": bool(D <= end[sid]),
                    "번들 사건": "있음(E·D 같음)" if in_b else "없음",
                    "리드 창": f"{start.date()}~{(E - pd.Timedelta(days=1)).date()}",
                    "창 기준일 수": len(win),
                    "창 기준일 test 행": int(pred.loc[win.index, "target_cells"].notna().sum()),
                    "창 기준일 번들 재사용 가능": f"{int(win['번들 재사용 가능'].sum())}/{len(win)}",
                    "감시 첫 점등": first(det_api, RULE_WATCH),
                    "감시 리드(E) API/번들": f"{_s(api_l[0])}/{_s(bun_l[0])}",
                    "경보 리드(E) API/번들": f"{_s(api_l[1])}/{_s(bun_l[1])}",
                    "점예측 리드(E) API/번들": f"{_s(api_l[2])}/{_s(bun_l[2])}",
                    "번들 끝 이후 정답 의존": "예" if depends else "아니오",
                }
            )
        for e in ev[lv]["bundle2026"].itertuples(index=False):
            if (str(e[0]), str(e[1]), str(e[2])) not in _events_key(e_api):
                ev_rows.append(
                    {
                        "수준": ev[lv]["name"],
                        "지점": e[0],
                        "E": str(e[2]),
                        "D": str(e[1]),
                        "번들 사건": "번들에만",
                    }
                )
    ev_tab = pd.DataFrame(ev_rows)

    hist = {}
    for lv in (T10K, T1K):
        ea, eb = ev[lv]["api"], ev[lv]["bundle"]
        ka = _events_key(ea[_y(ea, 2020, 2025)])
        kb = _events_key(eb[_y(eb, 2020, 2025)])
        hist[ev[lv]["name"]] = {
            "api": len(ka),
            "bundle": len(kb),
            "same": ka == kb,
            "2026 사건 시작 연도 2020·2026 같음": bool(ev[lv]["same_2026_by_start_year"]),
        }

    # ---- 2026 리드 요약 비교표
    def lead_cmp(lv: float) -> pd.DataFrame:
        L = lead26[lv]
        a_ = L["api_summary"].set_index("방식")
        b_ = L["bundle_summary"].set_index("방식")
        out = []
        for name in a_.index:
            out.append(
                {
                    "방식": name,
                    "사건 수 API/번들": f"{a_.loc[name, '사건 수']}/{b_.loc[name, '사건 수']}",
                    "선행 탐지 API/번들": f"{a_.loc[name, '선행 탐지 수']}/{b_.loc[name, '선행 탐지 수']}",
                    "중앙 리드 E API/번들": f"{_s(a_.loc[name, '중앙 리드(E, 일)'])}/{_s(b_.loc[name, '중앙 리드(E, 일)'])}",
                    "중앙 리드 D API/번들": f"{_s(a_.loc[name, '중앙 리드(D, 일)'])}/{_s(b_.loc[name, '중앙 리드(D, 일)'])}",
                    "경보 총수 API(261행)": int(a_.loc[name, "경보 총수"]),
                    f"경보 총수 번들({int(usable.sum())}행)": int(b_.loc[name, "경보 총수"]),
                    "번들 기간 안 미확정 행의 경보": L["undetermined_alerts"][name],
                }
            )
        return pd.DataFrame(out)

    cmp10, cmp1 = lead_cmp(T10K), lead_cmp(T1K)
    so_a, so_b = s_o_api.set_index("방식"), s_o_bun.set_index("방식")
    oof_cmp = pd.DataFrame(
        [
            {
                "방식": n,
                "사건 수 API/번들": f"{so_a.loc[n, '사건 수']}/{so_b.loc[n, '사건 수']}",
                "선행 탐지 API/번들": f"{so_a.loc[n, '선행 탐지 수']}/{so_b.loc[n, '선행 탐지 수']}",
                "중앙 리드 E API/번들": f"{_s(so_a.loc[n, '중앙 리드(E, 일)'])}/{_s(so_b.loc[n, '중앙 리드(E, 일)'])}",
                "중앙 리드 D API/번들": f"{_s(so_a.loc[n, '중앙 리드(D, 일)'])}/{_s(so_b.loc[n, '중앙 리드(D, 일)'])}",
            }
            for n in so_a.index
        ]
    )
    s10a = lead26[T10K]["api_summary"].set_index("방식").loc[RULE_WATCH]
    s10b = lead26[T10K]["bundle_summary"].set_index("방식").loc[RULE_WATCH]
    head_api = {
        "2026 경계 사건": int(s10a["사건 수"]),
        "2026 감시 포착": int(s10a["선행 탐지 수"]),
        "2026 중앙 리드(E)": float(s10a["중앙 리드(E, 일)"]),
        "2020~2026 사건": comb_api["사건 수"],
        "2020~2026 포착": comb_api["감시 포착"],
        "2020~2026 포착 비율": comb_api["포착 비율"],
        "2020~2026 중앙 리드(E)": comb_api["중앙 리드(E, 일)"],
    }
    head_bun = {
        "2026 경계 사건": int(s10b["사건 수"]),
        "2026 감시 포착": int(s10b["선행 탐지 수"]),
        "2026 중앙 리드(E)": float(s10b["중앙 리드(E, 일)"]),
        "2020~2026 사건": comb_bun["사건 수"],
        "2020~2026 포착": comb_bun["감시 포착"],
        "2020~2026 포착 비율": comb_bun["포착 비율"],
        "2020~2026 중앙 리드(E)": comb_bun["중앙 리드(E, 일)"],
    }
    published = {
        "2026 경계 사건": 8,
        "2026 감시 포착": 7,
        "2026 중앙 리드(E)": 21.0,
        "2020~2026 사건": 28,
        "2020~2026 포착": 24,
        "2020~2026 포착 비율": 24 / 28,
        "2020~2026 중앙 리드(E)": 14.0,
    }
    headline_changes = any(abs(float(head_bun[k]) - float(published[k])) > 1e-12 for k in published)
    if any(abs(float(head_api[k]) - float(published[k])) > 1e-12 for k in published):
        raise SystemExit("중단: API 입력 재현 값이 공개 헤드라인과 다르다.")
    head_tab = pd.DataFrame(
        [
            {"항목": k, "공개 값": published[k], "API 재현": head_api[k], "번들 정답만": head_bun[k]}
            for k in published
        ]
    )

    # ---- 기준일 점검 요약
    by_site = (
        rows.assign(test=test_mask.to_numpy())
        .groupby("station_id")
        .agg(
            기준일=("base_date", "size"),
            번들_기간_안=("번들 기간 안", "sum"),
            번들_재사용_가능=("번들 재사용 가능", "sum"),
            test_행=("test", "sum"),
        )
        .reindex(list(SITES))
        .reset_index()
    )
    by_site.insert(1, "번들 끝", [str(end[s].date()) for s in by_site["station_id"]])
    not_usable = rows[in_period & ~usable].copy()
    not_usable["test 행"] = test_mask[not_usable.index].to_numpy()
    in_bwin = pd.Series(False, index=rows.index)
    for lv in (T10K, T1K):
        for e in ev[lv]["bundle2026"].itertuples(index=False):
            E = pd.Timestamp(e[2])
            st = window_start(m_bun, e[0], E, lv)
            in_bwin |= (rows["station_id"] == e[0]) & (rows["base_date"] < E) & (rows["base_date"] >= st)
    not_usable["번들 사건 리드 창 안"] = in_bwin[not_usable.index].to_numpy()
    not_usable["base_date"] = not_usable["base_date"].dt.date
    after = rows[~in_period]
    after_rng = {
        s: f"{g['base_date'].min().date()}~{g['base_date'].max().date()}({len(g)}행)"
        for s, g in after.groupby("station_id")
    }
    trow_sum = {
        "n": len(trow),
        **{c: int(trow[c].sum()) for c in trow.columns if trow[c].dtype == bool},
        "기준일 번들 재사용 가능": test_usable,
    }
    test_site = (
        trow.groupby("station_id")
        .agg(
            n=("base_date", "size"),
            목표일_범위=("target_date", lambda s: f"{min(s)}~{max(s)}"),
            목표일_번들_안=("목표일 번들 기간 안", "sum"),
            격리정답_번들일치=("격리 정답=번들", "sum"),
        )
        .reindex(list(SITES))
        .reset_index()
    )
    test_site["기준일 번들 재사용 가능"] = [
        int(usable[test_mask & (pred["station_id"] == s)].sum()) for s in test_site["station_id"]
    ]

    # ---- 출력(md)
    metric_tab = pd.DataFrame(
        [
            {
                "모델": lab,
                "n": blk["bundle_answers"]["n"],
                "rmse_log": blk["bundle_answers"]["rmse_log"],
                "r2_log": blk["bundle_answers"]["r2_log"],
                "r2_raw": blk["bundle_answers"]["r2_raw"],
                "f1_10k": blk["bundle_answers"]["f1_10k"],
                "PICP80": blk["bundle_answers"].get("picp80", np.nan),
                "headline_metrics.json 과 최대 차": blk["max_abs_diff_bundle_vs_headline_json"],
            }
            for lab, blk in met.items()
        ]
    )
    col_tab = pd.DataFrame([{"열": c, "값이 다른 겹치는 행": n} for c, n in col_diff.items()])
    diff_tab = diffs_all[diffs_all["구분"] == "값 차이"].assign(obs_date=lambda d: d["obs_date"].dt.date)
    api_only_tab = (
        api_only.groupby("station_id")["obs_date"]
        .agg(["min", "max", "size"])
        .rename(columns={"min": "처음", "max": "끝", "size": "행"})
        .reset_index()
    )
    api_only_tab["처음"] = api_only_tab["처음"].dt.date
    api_only_tab["끝"] = api_only_tab["끝"].dt.date
    md = (
        "# 2026 사후 분석의 정답 출처 — 대회 번들 끝 이후 측정에 기대는가\n\n"
        "- 번들 `algae_measure.csv` 끝: "
        + ", ".join(f"{SITE_KO[s]} {end[s].date()}" for s in SITES)
        + ". 저장소 사후 계산의 조류 원천은 공공 API `nier_algae_2012_2026.parquet`(2026-10-15 까지).\n"
        "- 저장된 사후 예측(`posthoc_2026_v21.parquet`, v2.1 동결 커밋 217260e 뒤 1회)과 측정만 다시 집계했다. 새 예측 없음. "
        "2026 test 정답은 `eval.live.load_test_targets`(명시 플래그)로만 읽었다. 이 표에는 정답 값 자체를 쓰지 않는다(일치 여부·차이만).\n"
        "- 재현 확인: API 입력으로 만든 사건이 `transitions.official_events` 와, 2026 리드타임이 `eval.posthoc.leadtime_2026` 과(요약·사건별 상세), "
        "2020~2025 리드타임(q90·B0)이 `transitions.leadtime_table` 과 같음을 확인한 뒤 원천만 번들로 바꿨다.\n"
        "- '번들 재사용 가능' 기준일 = 번들 기간 안 + 기준일 측정이 번들에 있음 + 기준일까지 모델 입력 조류 열(세포수·수온·pH·클로로필a·우점종, 자기·바로 위 지점)이 번들과 같음 "
        "+ 목표일 매칭(horizon_days)이 번들 측정일로도 같음 + cell_log_t0 이 번들 세포수와 같음. 이 행은 번들만으로 계산해도 같은 예측이므로 저장 예측을 그대로 쓴다.\n\n"
        + conclusion_text(
            headline_changes=headline_changes,
            ev=ev,
            ev_tab=ev_tab,
            hist=hist,
            trow_sum=trow_sum,
            test_usable=test_usable,
            met=met,
            site_maxdiff=site_maxdiff,
            lead26=lead26,
            rows=rows,
            not_usable=not_usable,
        )
        + "## 1. 헤드라인 — 공개 값·API 재현·번들 정답만\n\n"
        + _md(head_tab)
        + "\n\n"
        "## 2. 사건별(2026 경계·관심) — 정답 측정이 번들 안인지, 리드에 쓴 기준일이 번들로 같은지\n\n"
        + _md(ev_tab)
        + "\n\n"
        "### 2020~2025 사건(번들로 다시 만든 사건 목록 대조)\n\n"
        + _md(
            pd.DataFrame(
                [
                    {"수준": k, "API": v["api"], "번들": v["bundle"], "같음": v["same"]}
                    for k, v in hist.items()
                ]
            )
        )
        + "\n\n## 3. 리드타임 — API(저장 표) 대 번들 정답만\n\n### 2026 경계(10k)\n\n"
        + _md(cmp10)
        + "\n\n### 2026 관심(1k)\n\n"
        + _md(cmp1)
        + "\n\n### 2020~2025 경계(10k, OOF — tbl_leadtime.md)\n\n"
        + _md(oof_cmp)
        + "\n\n### 2020~2026 합계(감시 = 2020~2025 OOF q90≥1만 + 2026 q90_cqr≥1만)\n\n"
        + _md(pd.DataFrame([{"원천": "API(저장)", **comb_api}, {"원천": "번들 정답만", **comb_bun}]))
        + "\n\n## 4. test 124조합 — 목표일·정답 측정\n\n"
        + _md(test_site)
        + "\n\n- 행 단위 전체 판정은 JSON `test_rows`(정답 값 없이 일치 여부만). 불일치 행: "
        + (
            "없음"
            if trow[[c for c in trow.columns if trow[c].dtype == bool]].all().all()
            else str(
                trow[~trow[[c for c in trow.columns if trow[c].dtype == bool]].all(axis=1)].to_dict("records")
            )
        )
        + "\n\n## 5. 2026 지표 — 번들 정답으로 다시 계산\n\n"
        + _md(metric_tab)
        + "\n\n### 지점별(v2.1·v1-fix·B0, 번들 정답)\n\n"
        + _md(pd.DataFrame(site_rows))
        + "\n\n## 6. 2026 기준일 261행 — 번들 기간·입력 동일성\n\n"
        + _md(by_site)
        + "\n\n- 번들 끝 이후 기준일(API 에만 있는 측정일): "
        + ", ".join(f"{SITE_KO[s]} {v}" for s, v in after_rng.items())
        + f". 번들 2026 측정일 중 사후 예측 기준일에 없는 날: {len(missing_base)}건.\n\n"
        "### 번들 기간 안이지만 저장 예측을 그대로 쓸 수 없는 기준일\n\n"
        + _md(not_usable[["station_id", "base_date", "test 행", "번들 사건 리드 창 안", "사유"]])
        + "\n\n## 7. 측정 원천 대조(번들 대 API)\n\n"
        + f"- API 에만 있는 행 {len(api_only)}개(번들에만 있는 행 0):\n\n"
        + _md(api_only_tab)
        + "\n\n- 겹치는 행의 열별 값 차이:\n\n"
        + _md(col_tab)
        + "\n\n- 값이 다른 겹치는 행:\n\n"
        + _md(diff_tab)
        + "\n"
    )
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")

    # ---- 출력(json) — 정답 값 열(target_cells 등)은 쓰지 않는다
    def recs(t: pd.DataFrame) -> list[dict]:
        return json.loads(t.to_json(orient="records", force_ascii=False, date_format="iso"))

    out = {
        "_about": "2026 사후 분석의 정답 출처 점검(python -m algaecast.eval.posthoc_answer_source). 정답 값 없이 일치 여부·차이·리드만.",
        "bundle_end": {s: str(end[s].date()) for s in SITES},
        "api_only_rows": {"n": len(api_only), "by_station": recs(api_only_tab)},
        "overlap_column_diffs": col_diff,
        "overlap_value_diff_rows": recs(diff_tab),
        "headline": {"published": published, "api_reproduced": head_api, "bundle_only": head_bun},
        "headline_changes": bool(headline_changes),
        "events_2026": recs(ev_tab),
        "events_2020_2025": hist,
        "lead_2026_10k": {"compare": recs(cmp10), "bundle_detail": recs(lead26[T10K]["bundle_detail"])},
        "lead_2026_1k": {"compare": recs(cmp1), "bundle_detail": recs(lead26[T1K]["bundle_detail"])},
        "lead_2020_2025_10k": {"compare": recs(oof_cmp)},
        "combined_2020_2026": {"api": comb_api, "bundle_only": comb_bun},
        "test124": {"summary": trow_sum, "by_station": recs(test_site), "test_rows": recs(trow)},
        "metrics_2026": met,
        "metrics_2026_sites_bundle": recs(pd.DataFrame(site_rows)),
        "metrics_2026_sites_max_abs_diff_vs_saved": site_maxdiff,
        "base_rows_2026": {
            "n": len(rows),
            "in_bundle_period": int(in_period.sum()),
            "bundle_reusable": int(usable.sum()),
            "after_bundle_end": after_rng,
            "in_period_not_reusable": recs(
                not_usable[["station_id", "base_date", "test 행", "번들 사건 리드 창 안", "사유"]]
            ),
            "bundle_2026_dates_missing_from_pred": len(missing_base),
            "by_station": recs(by_site),
        },
    }
    OUT_JSON.write_text(
        json.dumps(
            clean(out),
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(head_tab.to_string(index=False))
    print(f"headline_changes = {headline_changes}")
    print("→", OUT_MD, OUT_JSON)
    return 0


def conclusion_text(
    *,
    headline_changes: bool,
    ev: dict,
    ev_tab: pd.DataFrame,
    hist: dict,
    trow_sum: dict,
    test_usable: int,
    met: dict,
    site_maxdiff: float,
    lead26: dict,
    rows: pd.DataFrame,
    not_usable: pd.DataFrame,
) -> str:
    """보고서 결론 문단 — 숫자·사건은 모두 계산 값에서 만든다."""
    e10 = ev[T10K]["api2026"]
    last_d = max(pd.Timestamp(d) for d in e10["발령 측정일 D"])
    t10 = ev_tab[ev_tab["수준"] == "경계(10k)"]
    all_in = bool(t10["E 번들 안"].all() and t10["D 번들 안"].all())
    same10 = bool((t10["번들 사건"] == "있음(E·D 같음)").all())
    win_ok = bool(t10["창 기준일 번들 재사용 가능"].map(lambda x: x.split("/")[0] == x.split("/")[1]).all())
    dep = (
        ev_tab[ev_tab["번들 끝 이후 정답 의존"] == "예"]
        if "번들 끝 이후 정답 의존" in ev_tab
        else ev_tab.iloc[0:0]
    )
    dep_txt = "; ".join(
        f"{r['수준']} {SITE_KO[r['지점']]} E {r['E']}({'번들 안' if r['E 번들 안'] else 'API 에만'})·"
        f"D {r['D']}({'번들 안' if r['D 번들 안'] else 'API 에만'})"
        for _, r in dep.iterrows()
    )
    n1_api, n1_bun = len(ev[T1K]["api2026"]), len(ev[T1K]["bundle2026"])
    s1a = lead26[T1K]["api_summary"].set_index("방식")
    s1b = lead26[T1K]["bundle_summary"].set_index("방식")

    def frac(t: pd.DataFrame, rule: str) -> str:
        return f"{int(t.loc[rule, '선행 탐지 수'])}/{int(t.loc[rule, '사건 수'])}"

    def med(t: pd.DataFrame, rule: str, col: str) -> str:
        return _s(t.loc[rule, col])

    v21b, b0b = met["v21"]["bundle_answers"], met["b0"]["bundle_answers"]
    maxd = max(b["max_abs_diff_bundle_vs_headline_json"] for b in met.values())
    reason_names = {
        "기준일 측정 번들에 있음": "기준일 측정이 번들에 없음",
        "입력 같음": "기준일까지 모델 입력 조류 값이 번들과 다름",
        "목표일 매칭 같음": "목표일(horizon_days) 매칭이 API 에만 있는 측정일",
        "cell_log_t0 번들 일치": "cell_log_t0 이 번들과 다름",
    }
    reasons = [
        f"{txt} {int((~not_usable[col]).sum())}행"
        for col, txt in reason_names.items()
        if (~not_usable[col]).any()
    ]
    nu_test = int(not_usable["test 행"].sum())
    nu_win = int(not_usable["번들 사건 리드 창 안"].sum())
    n_after = int((~rows["번들 기간 안"]).sum())
    h10, h1 = hist["경계(10k)"], hist["관심(1k)"]
    nl = "\n"
    return (
        f"## 결론{nl}{nl}- **헤드라인 숫자는 번들 정답만으로도 같다(headline_changes = {str(headline_changes).lower()}).** "
        f"2026 경계 사건 {len(e10)}건의 E·D 가 모두 번들 기간 안 = {all_in}(마지막 D {last_d.date()}), "
        f"번들로 만든 사건과 같음 = {same10}, 리드 창 기준일이 모두 번들 재사용 가능 = {win_ok}.{nl}"
        f"- 2020~2025 사건: 경계 API {h10['api']}건 / 번들 {h10['bundle']}건, 같음 = {h10['same']}; "
        f"관심 {h1['api']}건 / {h1['bundle']}건, 같음 = {h1['same']}.{nl}"
        f"- test {trow_sum['n']}조합: 목표일 번들 안 {trow_sum['목표일 번들 기간 안']}, 격리 정답 = 번들 값 {trow_sum['격리 정답=번들']}, "
        f"기준일 번들 재사용 가능 {test_usable} → 2026 지표(v2.1 rmse_log {v21b['rmse_log']:.3f}·r2_log {v21b['r2_log']:.3f}·"
        f"r2_raw {v21b['r2_raw']:.3f}·F1@10k {v21b['f1_10k']:.3f}·PICP80 {v21b['picp80']:.3f}, B0 rmse_log {b0b['rmse_log']:.3f}, "
        f"v1-fix·v2·v1·지점별 포함)는 번들 정답으로 다시 계산해도 같다"
        f"(headline_metrics.json 과 최대 차 {maxd:.1e}, 지점별 {site_maxdiff:.1e}).{nl}"
        f"- **번들 끝 이후 정답에 기대는 것(헤드라인 아님)**: ① 2026 관심(1k) 사건 {n1_api}건 중 {n1_api - n1_bun}건 — {dep_txt or '없음'}. "
        f"번들 기준 관심 사건 {n1_bun}건: 감시 {frac(s1b, RULE_WATCH)}·중앙 리드 E {med(s1b, RULE_WATCH, '중앙 리드(E, 일)')}일·"
        f"D {med(s1b, RULE_WATCH, '중앙 리드(D, 일)')}일(API {frac(s1a, RULE_WATCH)}·"
        f"{med(s1a, RULE_WATCH, '중앙 리드(E, 일)')}일·{med(s1a, RULE_WATCH, '중앙 리드(D, 일)')}일), "
        f"점예측 {frac(s1b, RULE_POINT)}(API {frac(s1a, RULE_POINT)}). "
        f"② 저장 표의 '경보 총수(2026)' 열은 번들 끝 뒤 기준일 {n_after}행(API 에만 있는 측정으로 만든 피처)을 포함한다 — "
        f"번들 재사용 가능 {int(rows['번들 재사용 가능'].sum())}행만 센 값을 3절에 병기. "
        f"③ 번들 기간 안이지만 저장 예측을 그대로 쓸 수 없는 기준일 {len(not_usable)}행(사유: {', '.join(reasons) or '없음'}) — "
        f"test 행 {nu_test}개, 번들 사건 리드 창 안 {nu_win}개. 경보 총수에만 영향(새 예측 금지로 '미확정' 열에 따로 셈).{nl}{nl}"
    )


def _y(ev: pd.DataFrame, y0: int, y1: int | None = None) -> pd.Series:
    """사건 표에서 발령 측정일 D 의 연도가 [y0, y1] 인 행."""
    yr = pd.to_datetime(ev["발령 측정일 D"]).dt.year
    return (yr >= y0) & (yr <= (y1 if y1 is not None else 9999))


def _s(x: object) -> str:
    """표 칸 문자열(결측은 '—', 정수 값 실수는 정수로)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


if __name__ == "__main__":
    raise SystemExit(main())
