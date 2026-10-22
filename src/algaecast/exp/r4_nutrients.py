# ruff: noqa: E501  (한국어 표·보고서 문자열)
"""R4(EXP-007) 영양염 피처 — 국립환경과학원 수질측정망(getWaterMeasuringList) 최근접 측정소.

데이터: ``data/raw/nier_wqdb/wq_measuring_2012_2026.parquet`` (수집기 ``collect/nier_wq_measuring.py``).
5지점마다 대표 측정소 1곳(``SITE_STATION``, 본류·상하류 관계 고려, 거리 표는 보고서)의 표층 측정값을 쓴다.
'정량한계미만'(PO4-P 약 30%, NH3-N 일부)은 0 으로 대치한다(측정은 됐고 값이 매우 작음 — 호소 측정소가 0 으로
보고하는 관행과 같게). 비율의 분모는 0.001 mg/L 로 하한.

피처(모두 ``wq_`` 접두사, as_of = base_date, 공개 지연 d 일이면 기준 시점 ref = as_of − d)
- ``wq_<항목>_last``: ref 이전(포함) 최근 측정값 — 항목 TN·TP·NO3-N·NH3-N·PO4-P·TDN·TDP·Chl-a·DO·EC·SS
- ``wq_<항목>_4w``: (ref − 27일, ref] 측정 평균
- ``wq_np_last``(TN/TP 최근)·``wq_np_4w``(4주 평균 TN/TP)·``wq_dinp_last``((NO3-N+NH3-N)/PO4-P 최근)
- ``wq_days_since``: as_of − 최근 측정일(일)

공개 함수(종합 단계 재사용)
- ``build_features(df, *, cfg=None, wq=None) -> pd.DataFrame`` — ``harness.load_base()`` 형식 df 를 받아
  같은 인덱스로 선택 설정(``CHOSEN`` = tp_np 지연 0일: wq_tp_last·wq_np_last·wq_days_since)의 새 열만 반환.
  운영 재현용은 ``build_features(df, cfg=OPERATIONAL)``(같은 열, 공개 지연 60일).
- ``nutrient_features(wq, as_of, site, *, delay_days=0, window_days=28) -> dict`` — 순수 피처 함수
  (진입 직후 ``cut_as_of``).
- ``load_wq() -> pd.DataFrame`` — 원자료 → 대표 측정소·표층·정량한계미만 0 대치.

실행: python -m algaecast.exp.r4_nutrients  → reports/experiments/EXP-007/, data/processed/exp/EXP-007/
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.nier_wq_measuring import CANDIDATES, OUT_DIR, OUT_NAME, surface_layer
from algaecast.config import CONFIG_DIR, RAW_DIR
from algaecast.exp import harness as H
from algaecast.features.base import cut_as_of

log = logging.getLogger(__name__)

EXP = "EXP-007"
OUT_DATA = H.EXP_DATA / EXP
OUT_REP = H.EXP_REPORTS / EXP
RAW_PATH = OUT_DIR / f"{OUT_NAME}.parquet"
GEOJSON_ZIP = RAW_DIR / "nier_wq" / "기후에너지환경부_물환경 수질측정망 정보(JSON)_20251231.zip"
T_START = datetime(2026, 10, 21, 17, 53, 26)  # 실험 시작(로컬 KST) — date 로 기록
HOURS_CAP = 8.0

SITE_STATION: dict[str, str] = {
    site: pt for site, cands in CANDIDATES.items() for pt, role in cands if role == "primary"
}
# 민감도: 바로 위(상류) 본류 측정소. 상류 후보가 없는 칠서(CS)는 대표 측정소 그대로.
UPSTREAM_STATION: dict[str, str] = {
    site: next((pt for pt, role in cands if role == "upstream"), SITE_STATION[site])
    for site, cands in CANDIDATES.items()
}
STATION_MAPS: dict[str, dict[str, str]] = {"primary": SITE_STATION, "upstream": UPSTREAM_STATION}
ITEMS: tuple[str, ...] = ("tn", "tp", "no3n", "nh3n", "po4p", "tdn", "tdp", "chla", "do", "ec", "ss")
NUTR: tuple[str, ...] = ("tn", "tp", "no3n", "nh3n", "po4p", "tdn", "tdp")
OTHER: tuple[str, ...] = ("chla", "do", "ec", "ss")
LOQ_ZERO: tuple[str, ...] = ("tp", "no3n", "nh3n", "po4p", "tdp")  # 정량한계미만이 나타나는 항목
P_FLOOR = 0.001  # mg/L, 비율 분모 하한
WINDOW_DAYS = 28


# ---------------------------------------------------------------- 원자료
def load_wq(path: Path = RAW_PATH, stations: tuple[str, ...] | None = None) -> pd.DataFrame:
    """대표·상류 측정소(기본)의 표층 측정 → obs_date(Timestamp)·pt_no·ITEMS. 정량한계미만은 0."""
    raw = pd.read_parquet(path)
    keep = list(stations or {*SITE_STATION.values(), *UPSTREAM_STATION.values()})
    raw = raw[raw["pt_no"].isin(keep)]
    s = surface_layer(raw)
    for c in LOQ_ZERO:
        flag = s.get(f"{c}_below_loq")
        if flag is not None:
            s.loc[flag.astype(bool) & s[c].isna(), c] = 0.0
    out = s[["pt_no", "obs_date", *ITEMS]].copy()
    out["obs_date"] = pd.to_datetime(out["obs_date"])
    return out.sort_values(["pt_no", "obs_date"]).reset_index(drop=True)


# ---------------------------------------------------------------- 순수 피처 함수
def _ratio(num: float, den: float) -> float:
    if not (np.isfinite(num) and np.isfinite(den)):
        return math.nan
    return float(num / max(den, P_FLOOR))


def feature_names() -> list[str]:
    """nutrient_features 가 돌려주는 키(순서 고정)."""
    names = [f"wq_{it}_{k}" for it in ITEMS for k in ("last", "4w")]
    return [*names, "wq_np_last", "wq_np_4w", "wq_dinp_last", "wq_days_since"]


def nutrient_features(
    wq: pd.DataFrame,
    as_of: date | pd.Timestamp,
    site: str,
    *,
    delay_days: int = 0,
    window_days: int = WINDOW_DAYS,
    station: str | None = None,
) -> dict[str, float]:
    """(원자료, as_of, site) → dict. as_of(=base_date) 이후 측정은 진입 즉시 버리고,
    공개 지연 ``delay_days`` 가 있으면 ref = as_of − delay_days 이후 측정도 버린다."""
    w = cut_as_of(wq, as_of)  # 누수 방지: as_of 이후 행 제거(진입 직후)
    ref = pd.Timestamp(as_of).normalize() - pd.Timedelta(days=int(delay_days))
    w = cut_as_of(w, ref)
    pt = station or SITE_STATION.get(site)
    w = w[w["pt_no"] == pt].sort_values("obs_date")
    out: dict[str, float] = dict.fromkeys(feature_names(), math.nan)
    if w.empty:
        return out
    d = pd.to_datetime(w["obs_date"])
    recent = w[d > ref - pd.Timedelta(days=window_days)]
    for it in ITEMS:
        s = w[it].dropna()
        out[f"wq_{it}_last"] = float(s.iloc[-1]) if len(s) else math.nan
        r = recent[it].dropna()
        out[f"wq_{it}_4w"] = float(r.mean()) if len(r) else math.nan
    both = w.dropna(subset=["tn", "tp"])
    if len(both):
        out["wq_np_last"] = _ratio(float(both["tn"].iloc[-1]), float(both["tp"].iloc[-1]))
    out["wq_np_4w"] = _ratio(out["wq_tn_4w"], out["wq_tp_4w"])
    din = w.dropna(subset=["no3n", "nh3n", "po4p"])
    if len(din):
        last = din.iloc[-1]
        out["wq_dinp_last"] = _ratio(float(last["no3n"] + last["nh3n"]), float(last["po4p"]))
    has_any = w[list(ITEMS)].notna().any(axis=1)
    if has_any.any():
        last_d = pd.to_datetime(w.loc[has_any, "obs_date"]).max()
        out["wq_days_since"] = float((pd.Timestamp(as_of).normalize() - last_d.normalize()).days)
    return out


# ---------------------------------------------------------------- 변형(설정)
@dataclass(frozen=True)
class FeatCfg:
    """피처 묶음 × 공개 지연."""

    name: str
    cols: tuple[str, ...]
    delay_days: int = 0
    stations: str = "primary"  # primary | upstream (STATION_MAPS)

    @property
    def label(self) -> str:
        up = ", 상류 측정소" if self.stations == "upstream" else ""
        return f"R4 {self.name} (지연 {self.delay_days}일{up})"


SETS: dict[str, tuple[str, ...]] = {
    "all": tuple(feature_names()),
    "nutr_last": (*(f"wq_{it}_last" for it in NUTR), "wq_np_last", "wq_dinp_last", "wq_days_since"),
    "nutr_4w": (*(f"wq_{it}_4w" for it in NUTR), "wq_np_4w", "wq_days_since"),
    "ratio_tp": (
        "wq_tp_last",
        "wq_po4p_last",
        "wq_tp_4w",
        "wq_np_last",
        "wq_np_4w",
        "wq_dinp_last",
        "wq_days_since",
    ),
    "other_last": (*(f"wq_{it}_last" for it in OTHER), "wq_days_since"),
    "tp_np": ("wq_tp_last", "wq_np_last", "wq_days_since"),
    "p_last": ("wq_tp_last", "wq_po4p_last", "wq_tdp_last", "wq_days_since"),
    "n_last": ("wq_tn_last", "wq_no3n_last", "wq_nh3n_last", "wq_tdn_last", "wq_days_since"),
}
DELAYS: tuple[int, ...] = (0, 30, 60)
VARIANTS: list[FeatCfg] = [FeatCfg(n, c, d) for d in DELAYS for n, c in SETS.items()] + [
    FeatCfg(n, SETS[n], 0, "upstream") for n in ("all", "nutr_last")
]
# 실행(main) 후 CV 규칙(EXP-PLAN 4절)으로 고른 설정 = build_features 기본값. 기준 미달(리드타임 17/20).
CHOSEN = FeatCfg("tp_np", SETS["tp_np"], 0)
# 운영 재현용 대안: 같은 묶음 + 공개 지연 60일(실제 API 지연 약 55일). CV r2_raw 거의 같고 리드타임 18/20 유지.
OPERATIONAL = FeatCfg("tp_np", SETS["tp_np"], 60)


def full_features(
    df: pd.DataFrame, wq: pd.DataFrame, delay_days: int, stations: str = "primary"
) -> pd.DataFrame:
    """df 각 행(station_id, base_date)에 대해 nutrient_features 전체 키 계산(같은 인덱스)."""
    mapping = STATION_MAPS[stations]
    by_pt = {pt: g for pt, g in wq.groupby("pt_no")}
    empty = wq.iloc[0:0]
    rows = []
    for sid, bd in zip(df["station_id"].astype(str), df["base_date"], strict=True):
        pt = mapping.get(sid, "")
        sub = by_pt.get(pt, empty)
        rows.append(nutrient_features(sub, pd.Timestamp(bd), sid, delay_days=delay_days, station=pt))
    return pd.DataFrame(rows, index=df.index, columns=feature_names())


def build_features(
    df: pd.DataFrame, *, cfg: FeatCfg | None = None, wq: pd.DataFrame | None = None, guard: bool = True
) -> pd.DataFrame:
    """종합 단계용: df(harness.load_base() 형식)와 같은 인덱스로 선택 설정의 새 열만 반환."""
    if guard:
        H.guard_no_2026(df)
    cfg = cfg or CHOSEN
    wq = load_wq() if wq is None else wq
    return full_features(df, wq, cfg.delay_days, cfg.stations)[list(cfg.cols)]


# ---------------------------------------------------------------- 측정소 거리 표
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def geojson_coords(zip_path: Path = GEOJSON_ZIP, year: int = 2025, month: int = 8) -> dict[str, tuple]:
    """수질측정망 정보(JSON) 월별 GeoJSON(압축 안의 압축)에서 측정소 좌표 {PTNO: (이름, 위도, 경도)}."""
    import io
    import zipfile

    if not zip_path.exists():
        return {}
    outer = zipfile.ZipFile(zip_path)
    inner_info = next(i for i in outer.infolist() if i.filename.endswith(f"{year}.zip"))
    inner = zipfile.ZipFile(io.BytesIO(outer.read(inner_info)))
    target = next(i for i in inner.infolist() if i.filename.endswith(f"_{month:02d}.geojson"))
    g = json.loads(inner.read(target).decode("utf-8"))
    return {
        f["properties"]["PTNO"]: (f["properties"]["PTNM"], f["properties"]["Y"], f["properties"]["X"])
        for f in g["features"]
    }


RELATION_KO = {"primary": "대표", "upstream": "상류", "downstream": "하류", "same_reach": "같은 구간"}


def station_distance_table() -> pd.DataFrame:
    """5지점 × 후보 측정소: 관계·주소·API 좌표 거리·GeoJSON 좌표 거리·측정 빈도."""
    sites = {
        s["station_id"]: s
        for s in yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))["sites"]
    }
    st = pd.read_csv(OUT_DIR / "wq_measuring_stations.csv", dtype={"pt_no": str}).set_index("pt_no")
    geo = geojson_coords()
    rows = []
    for sid, cands in CANDIDATES.items():
        la, lo = float(sites[sid]["lat"]), float(sites[sid]["lon"])
        for pt, role in cands:
            s = st.loc[pt]
            g = geo.get(pt)
            n_years = (pd.Timestamp(s["last_obs"]) - pd.Timestamp(s["first_obs"])).days / 365.25
            rows.append(
                {
                    "site": sid,
                    "site_name": sites[sid]["name"],
                    "pt_no": pt,
                    "pt_nm": s["pt_nm"],
                    "relation": role,
                    "addr": s["addr"],
                    "lat": round(float(s["lat"]), 6),
                    "lon": round(float(s["lon"]), 6),
                    "dist_api_km": round(haversine_km(la, lo, float(s["lat"]), float(s["lon"])), 2),
                    "dist_geojson_km": round(haversine_km(la, lo, g[1], g[2]), 2) if g else math.nan,
                    "dates_per_year": round(float(s["n_dates"]) / max(n_years, 1e-9), 1),
                    "first_obs": s["first_obs"],
                    "last_obs": s["last_obs"],
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 평가 보조
def block_bootstrap_delta(
    df: pd.DataFrame, pred_a: np.ndarray, pred_b: np.ndarray, *, n_boot: int = 1000, seed: int | None = None
) -> dict[str, float]:
    """CV(2020~2024) 행에서 (지점, 연도) 블록 부트스트랩 → r2_raw(b) − r2_raw(a) 분포 요약."""
    from algaecast.config import load_seed

    rng = np.random.default_rng(load_seed() if seed is None else seed)
    cv_mask, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)[cv_mask]
    a, b = np.asarray(pred_a, dtype=float)[cv_mask], np.asarray(pred_b, dtype=float)[cv_mask]
    blocks = (df["station_id"].astype(str) + "_" + H.years_of(df).astype(str)).to_numpy()[cv_mask]
    uniq = np.unique(blocks)
    idx_by = {u: np.where(blocks == u)[0] for u in uniq}

    def r2(o: np.ndarray, p: np.ndarray) -> float:
        return 1.0 - float(np.sum((o - p) ** 2)) / float(np.sum((o - o.mean()) ** 2))

    deltas = []
    for _ in range(n_boot):
        pick = np.concatenate([idx_by[u] for u in rng.choice(uniq, size=len(uniq), replace=True)])
        deltas.append(r2(obs[pick], b[pick]) - r2(obs[pick], a[pick]))
    d = np.asarray(deltas)
    return {
        "delta_point": r2(obs, b) - r2(obs, a),
        "q05": float(np.quantile(d, 0.05)),
        "q50": float(np.quantile(d, 0.5)),
        "q95": float(np.quantile(d, 0.95)),
        "p_le0": float((d <= 0).mean()),
    }


def choose(base: dict, rows: list[dict]) -> tuple[dict, bool]:
    """EXP-PLAN 4절: 채택 기준을 만족하는 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대(기준 미달)."""
    ok = [r for r in rows if H.adoption(base, r)["pass"]]
    pool = ok or rows
    best = max(pool, key=lambda r: r["cv_r2_raw"])
    return best, bool(ok)


def coverage_table(df: pd.DataFrame, feats: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """지점별 피처 가용률(TP 최근값 non-NaN)·경과일 중앙값 — 지연별."""
    out = []
    for d, f in feats.items():
        for sid, idx in df.groupby("station_id", observed=True).groups.items():
            ff = f.loc[idx]
            out.append(
                {
                    "지연(일)": d,
                    "지점": sid,
                    "행": len(ff),
                    "TP 최근값 가용률": round(float(ff["wq_tp_last"].notna().mean()), 3),
                    "PO4-P 최근값 가용률": round(float(ff["wq_po4p_last"].notna().mean()), 3),
                    "4주 TP 가용률": round(float(ff["wq_tp_4w"].notna().mean()), 3),
                    "경과일 중앙값": float(np.nanmedian(ff["wq_days_since"])),
                }
            )
    return pd.DataFrame(out)


def _md_table(d: pd.DataFrame) -> str:
    cols = list(d.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for r in d.itertuples(index=False):
        lines.append(
            "| " + " | ".join("–" if (isinstance(v, float) and np.isnan(v)) else str(v) for v in r) + " |"
        )
    return "\n".join(lines) + "\n"


def elapsed_hours() -> float:
    return (datetime.now() - T_START).total_seconds() / 3600


# ---------------------------------------------------------------- 실행
def _cache_path(key: str) -> Path:
    return OUT_DATA / "cache" / f"{key}.pkl"


def run_variant(
    df: pd.DataFrame, new: pd.DataFrame, cols0: list[str], label: str, key: str, *, fresh: bool = False
) -> tuple[dict, dict[str, np.ndarray], np.ndarray, dict]:
    """v1 피처 + 새 열로 C1·C3·C2·분위 재학습 → (지표 행, 구성원 OOF, 앙상블, 연도별 가중치). 결과는 캐시."""
    import pickle

    path = _cache_path(key)
    if path.exists() and not fresh:
        with path.open("rb") as fh:
            got = pickle.load(fh)  # noqa: S301 — 자기 실험이 만든 로컬 캐시
        if got.get("cols") == list(new.columns) and got.get("label") == label:
            return got["row"], got["mem"], got["ens"], got["w"]
    d2 = pd.concat([df, new], axis=1)
    H.guard_no_2026(d2)
    mem = H.run_members(d2, cols0 + list(new.columns))
    row, ens, w = H.evaluate_members(d2, mem, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(
            {"label": label, "cols": list(new.columns), "row": row, "mem": mem, "ens": ens, "w": w}, fh
        )
    return row, mem, ens, w


def placebo_frames(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """대조군: 관측과 무관한 난수 열(표준정규, config 시드 42 생성기 하나에서 차례로 뽑음).

    새 열을 넣는 것만으로 LightGBM 열 표본(feature_fraction)이 바뀌어 생기는 CV 변동 폭을 잰다.
    관측값이 아니므로 누수와 무관하다. 선택 후보에는 넣지 않는다.
    """
    from algaecast.config import load_seed

    rng = np.random.default_rng(load_seed())
    out = {}
    for name, k in PLACEBOS:
        cols = [f"noise_{name}_{i}" for i in range(k)]
        out[name] = pd.DataFrame(rng.standard_normal((len(df), k)), index=df.index, columns=cols)
    return out


PLACEBOS: tuple[tuple[str, int], ...] = (("3a", 3), ("3b", 3), ("3c", 3), ("3d", 3), ("10a", 10))


def main(argv: list[str] | None = None) -> int:  # noqa: C901  (실험 절차를 한 곳에)
    import argparse

    ap = argparse.ArgumentParser(description="EXP-007 R4 영양염 피처 실험")
    ap.add_argument("--fresh", action="store_true", help="변형별 캐시를 무시하고 다시 학습")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    budget = H.Budget(HOURS_CAP - elapsed_hours(), EXP)
    t0 = time.time()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_REP.mkdir(parents=True, exist_ok=True)

    df = H.load_base()
    cols0 = H.base_columns()
    _, base_preds = H.load_baseline()
    base_row = H.metric_row(df, base_preds["ens"], base_preds["q90"], "v1 기준")
    wq = load_wq()
    keys = sorted({(c.delay_days, c.stations) for c in VARIANTS})
    feats = {k: full_features(df, wq, *k) for k in keys}
    log.info("피처 계산 %.1f초", time.time() - t0)

    rows: list[dict] = []
    mems: dict[str, tuple[dict, np.ndarray]] = {}
    status = "completed"
    jobs: list[tuple[str, FeatCfg | None, pd.DataFrame, str]] = [
        (
            c.label,
            c,
            feats[(c.delay_days, c.stations)][list(c.cols)],
            f"{c.name}_d{c.delay_days}_{c.stations}",
        )
        for c in VARIANTS
    ]
    jobs += [
        (f"대조: 난수 열 {k}개({name})", None, frame, f"placebo_{name}")
        for (name, k), frame in zip(PLACEBOS, placebo_frames(df).values(), strict=True)
    ]
    placebo_rows: list[dict] = []
    for label, cfg, new, key in jobs:
        try:
            budget.check()
        except H.BudgetExceeded as exc:
            log.warning("%s", exc)
            status = "time_cap"
            break
        t1 = time.time()
        row, mem, ens, w = run_variant(df, new, cols0, label, key, fresh=args.fresh)
        row = dict(row)
        row.update(
            {
                "variant": cfg.name if cfg else f"placebo_{key}",
                "delay_days": cfg.delay_days if cfg else None,
                "stations": cfg.stations if cfg else None,
                "n_new_cols": new.shape[1],
                "weights": w,
                "adoption": H.adoption(base_row, row),
            }
        )
        (rows if cfg else placebo_rows).append(row)
        mems[label] = (mem, ens)
        log.info(
            "%s: CV r2_raw %.3f rmse_log %.3f lead %s (%.0f초)",
            label,
            row["cv_r2_raw"],
            row["cv_rmse_log"],
            row.get("lead_q90"),
            time.time() - t1,
        )

    best, passed = choose(base_row, rows)
    chosen_cfg = next(c for c in VARIANTS if c.label == best["구성"])
    if chosen_cfg != CHOSEN:
        log.warning("CV 규칙 선택(%s)이 모듈 상수 CHOSEN(%s)과 다르다 — CHOSEN 갱신 필요", chosen_cfg, CHOSEN)
    mem, ens = mems[best["구성"]]
    keep = {k: mem[k] for k in ("c1", "c3", "c2", "q10", "q50", "q90")}
    keep["pred"] = ens
    H.save_oof(df, keep, OUT_DATA / "chosen_oof.parquet")
    fcols = list(chosen_cfg.cols)
    fsave = pd.concat(
        [df[["station_id", "base_date"]], feats[(chosen_cfg.delay_days, chosen_cfg.stations)][fcols]], axis=1
    )
    fsave.to_parquet(OUT_DATA / "features.parquet", index=False)
    # 공개 지연 민감도: 같은 피처 묶음의 지연 0/30/60
    sens = [r for r in rows if r["variant"] == chosen_cfg.name and r["stations"] == "primary"]
    boot = block_bootstrap_delta(df, base_preds["ens"], ens)
    adopt = H.adoption(base_row, best)

    dist = station_distance_table()
    cov = coverage_table(df, {d: f for (d, s), f in feats.items() if s == "primary"})
    write_reports(
        base_row, rows, best, passed, adopt, chosen_cfg, sens, boot, dist, cov, status, t0, placebo_rows
    )
    write_snippets(dist)
    print(H.standard_table([base_row, *rows, *placebo_rows]))
    print("선택:", best["구성"], "채택 판정:", adopt, "부트스트랩:", boot)
    print("상태:", status, f"경과 {elapsed_hours():.2f}h")
    return 0


def _clean(r: dict) -> dict:
    out = {}
    for k, v in r.items():
        if isinstance(v, (np.floating, np.integer)):
            v = v.item()
        if isinstance(v, float) and not np.isfinite(v):
            v = None
        if isinstance(v, dict):
            v = {str(kk): _clean(vv) if isinstance(vv, dict) else vv for kk, vv in v.items()}
        out[k] = v
    return out


def interpretation(base_row: dict, rows: list[dict], best: dict, placebo_rows: list[dict]) -> str:
    """변형·대조군 분포로 본 해석 문단(집계 수치만)."""
    b = base_row["cv_r2_raw"]
    v = np.array([r["cv_r2_raw"] for r in rows])
    lines = [
        f"- 영양염 변형 {len(rows)}개의 CV r2_raw: {v.min():.3f}~{v.max():.3f}(중앙 {np.median(v):.3f}, v1 {b:.3f}). "
        f"v1 보다 높은 변형 {int((v > b).sum())}개, 리드타임(q90) 유지 변형 "
        f"{sum(1 for r in rows if r['adoption']['lead_ok'])}개, 채택 기준 통과 {sum(1 for r in rows if r['adoption']['pass'])}개."
    ]
    if placebo_rows:
        pv = np.array([r["cv_r2_raw"] for r in placebo_rows])
        p25 = np.array([r["y2025_r2_raw"] for r in placebo_rows])
        inside = pv.min() <= best["cv_r2_raw"] <= pv.max()
        lines.append(
            f"- 난수 열 대조군 {len(placebo_rows)}벌의 CV r2_raw: {pv.min():.3f}~{pv.max():.3f}"
            f"(v1 대비 {pv.min() - b:+.3f}~{pv.max() - b:+.3f}), 2025 r2_raw {p25.min():.3f}~{p25.max():.3f}. "
            + (
                f"선택 변형({best['cv_r2_raw']:.3f})이 대조군 범위 안에 있어 영양염 정보의 효과를 학습 난수 변동과 구분할 수 없다."
                if inside
                else (
                    f"선택 변형({best['cv_r2_raw']:.3f})은 대조군 범위 밖이지만, 대조군 폭"
                    f"({pv.max() - pv.min():.3f})을 고려하면 효과 크기는 채택 기준(+0.10)에 크게 못 미친다."
                )
            )
        )
    by_delay: dict[int, list[float]] = {}
    for r in rows:
        if r["stations"] == "primary":
            by_delay.setdefault(int(r["delay_days"]), []).append(r["cv_r2_raw"])
    med = {d: float(np.median(x)) for d, x in sorted(by_delay.items())}
    slow = all(m >= med.get(0, -1.0) - 0.005 for d, m in med.items() if d > 0)
    lines.append(
        "- 공개 지연별 CV r2_raw 중앙값: "
        + ", ".join(f"{d}일 {m:.3f}" for d, m in med.items())
        + (
            ". 최신 측정을 빼도(지연 30·60일) 값이 떨어지지 않아, 효과가 있다면 '당일 영양염 상태'보다 계절·연도 수준의 느린 정보에 가깝다."
            if slow
            else ". 지연이 길수록 값이 낮아져 최신 측정이 정보를 더한다."
        )
    )
    lines.append(
        f"- 선택 변형의 2025 확인: r2_raw {best['y2025_r2_raw']:.3f}(v1 {base_row['y2025_r2_raw']:.3f}), "
        f"rmse_log {best['y2025_rmse_log']:.3f}(v1 {base_row['y2025_rmse_log']:.3f})."
    )
    return "\n".join(lines) + "\n"


def write_reports(
    base_row: dict,
    rows: list[dict],
    best: dict,
    passed: bool,
    adopt: dict,
    cfg: FeatCfg,
    sens: list[dict],
    boot: dict,
    dist: pd.DataFrame,
    cov: pd.DataFrame,
    status: str,
    t0: float,
    placebo_rows: list[dict] | None = None,
) -> None:
    """README.md·metrics.json 작성(관측 원값 없음 — 집계 지표만)."""
    placebo_rows = placebo_rows or []
    (OUT_REP / "metrics.json").write_text(
        json.dumps(
            {
                "exp": EXP,
                "baseline": _clean(base_row),
                "variants": [_clean(r) for r in rows],
                "placebo": [_clean(r) for r in placebo_rows],
                "chosen": best["구성"],
                "chosen_cfg": {
                    "name": cfg.name,
                    "cols": list(cfg.cols),
                    "delay_days": cfg.delay_days,
                    "stations": cfg.stations,
                },
                "adoption": adopt,
                "criteria_met_by_any": passed,
                "bootstrap_cv_r2_raw_delta": boot,
                "status": status,
                "elapsed_hours": round(elapsed_hours(), 3),
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    tbl_rows = [base_row, *rows]
    sens_tbl = "| 공개 지연 | CV r2_raw | CV nse_raw | CV rmse_log | 2025 r2_raw | 2025 rmse_log | 리드타임 |\n|---|---|---|---|---|---|---|\n"
    for r in sens:
        sens_tbl += (
            f"| {r['delay_days']}일 | {r['cv_r2_raw']:.3f} | {r['cv_nse_raw']:.3f} | {r['cv_rmse_log']:.3f} | "
            f"{r['y2025_r2_raw']:.3f} | {r['y2025_rmse_log']:.3f} | {r['lead_q90']}/{r['lead_n']} |\n"
        )
    interp = interpretation(base_row, rows, best, placebo_rows)
    dist_show = dist.drop(columns=["lat", "lon"]).assign(relation=dist["relation"].map(RELATION_KO))
    verdict = "통과" if adopt["pass"] else "미달"
    if adopt["pass"]:
        next_step = (
            "채택 기준을 통과했다. 종합(EXP-011)에서 `build_features(df)`(선택 설정)를 누적 결합 후보로 넣고, "
            "운영 재현성(실제 공개 지연 약 2개월)을 위해 위 민감도 표의 지연 60일 수치도 함께 비교한다."
        )
    else:
        pv = [r["cv_r2_raw"] for r in placebo_rows]
        inside = bool(pv) and min(pv) <= best["cv_r2_raw"] <= max(pv)
        next_step = (
            f"단독으로는 채택 기준(CV r2_raw +0.10)에 못 미쳤다(CV r2_raw {adopt['d_cv_r2_raw']:+.3f}, 리드타임 "
            f"{'유지' if adopt['lead_ok'] else '감소'}). "
            + (
                "게다가 같은 개수의 난수 열을 더한 대조군도 비슷하거나 더 큰 CV 상승을 보여, 영양염(측정망) 피처의 고유 효과는 "
                "확인되지 않았다. 종합(EXP-011)에는 넣지 않는 것을 권한다. 넣어 보더라도 `build_features(df, cfg=OPERATIONAL)`"
                "(공개 지연 60일)로 운영 재현성을 지키고, 같은 열 수의 난수 대조군보다 나은지 함께 확인한다. "
                if inside
                else "종합(EXP-011)에서는 `build_features(df)`를 보조 후보로만 넣고, 운영 재현성(실제 공개 지연 약 2개월)을 "
                "고려해 `cfg=OPERATIONAL`(지연 60일) 수치를 함께 본다. "
            )
            + "다른 실험에도 해당하는 주의: v1 피처에 열을 더하기만 해도 CV r2_raw 가 +0.03~+0.05 움직이므로, "
            "그 크기의 개선은 난수 열 대조군과 비교해야 해석할 수 있다. 영양염 정보를 더 살리려면 주 1회 측정망 대신 "
            "수질자동측정망(R6, 일 단위 TN·TP) 쪽이 다음 후보다."
        )
    (OUT_REP / "README.md").write_text(
        README_TEMPLATE.format(
            exp=EXP,
            status_line=(
                ""
                if status == "completed"
                else "\n> **시간 상한 초과로 중단** — 아래는 중단 시점까지의 결과.\n"
            ),
            dist_table=_md_table(dist_show),
            cov_table=_md_table(cov),
            std_table=H.standard_table(tbl_rows),
            placebo_table=(H.standard_table([base_row, *placebo_rows]) if placebo_rows else "(실행 안 됨)\n"),
            interp=interp,
            detail_table=H.detail_table(tbl_rows),
            chosen=best["구성"],
            chosen_cols=", ".join(f"`{c}`" for c in cfg.cols),
            rule_note=(
                "채택 기준을 만족하는 변형 중 CV r2_raw 최대"
                if passed
                else "채택 기준을 만족하는 변형이 없어 CV r2_raw 최대 변형(**기준 미달**)"
            ),
            d_r2=adopt["d_cv_r2_raw"],
            d_rmse=adopt["d_cv_rmse_log"],
            lead_ok="유지" if adopt["lead_ok"] else "감소",
            verdict=verdict,
            boot_point=boot["delta_point"],
            boot_q05=boot["q05"],
            boot_q95=boot["q95"],
            boot_p=boot["p_le0"],
            sens_table=sens_tbl,
            weights=json.dumps(
                {str(k): {kk: round(vv, 3) for kk, vv in v.items()} for k, v in best["weights"].items()},
                ensure_ascii=False,
            ),
            elapsed=elapsed_hours(),
            run_min=(time.time() - t0) / 60,
            n_var=len(rows),
            n_planned=len(VARIANTS),
            next_step=next_step,
        ),
        encoding="utf-8",
    )


README_TEMPLATE = """# {exp} — R4 영양염(국립환경과학원 수질측정망) 피처
{status_line}
## 1. 목적·설정

- 목적: 조류 증식의 제한 영양염(질소·인)과 수질 상태(Chl-a·DO·EC·SS)를 base_date 이전 측정으로 넣어 원단위 R²·NSE 를 높일 수 있는지 확인(EXP-PLAN 6절 R4).
- 데이터: 국립환경과학원 수질 DB OpenAPI `WaterQualityService/getWaterMeasuringList`(물환경 수질측정망 운영결과, data.go.kr, 2026-10-21 승인). 5지점 후보 측정소 13곳(본류만) 2012-01~2026-08 원자료 → `data/raw/nier_wqdb/wq_measuring_2012_2026.parquet`(수집기 `src/algaecast/collect/nier_wq_measuring.py`, 캐시·재시도 3회). 출처·sha256 은 `manifest_snippet.md`, 데이터 명세 보강은 `docs02_snippet.md`.
- 측정소 선택: 지점 좌표(config/sites.yaml, 근사)에서 거리 + 본류/지류·보·합류점 기준 상·하류 관계 + 주소(취수장·교량)로 대표 1곳. 지류(한천·금호강·남강·양산천 등)와 산단하천은 제외. 매핑은 `sites_snippet.yaml`.

{dist_table}
- 조류경보 측정점(조류 API `detail_adres`): 해평 '칠곡보 상류 22 km', 강정·고령 '강정고령보 상류 7 km', 칠서 '창녕함안보 상류 12 km', 물금·매리 '취수구 3 km', 회남 '회남대교'. sites.yaml 좌표는 근사값이라 거리는 참고치이고, 매핑은 주소·하천 구간으로 확정했다.
- 해평(HP)의 대표 측정소 이름이 '강정'(2011A10, 구미 고아읍 숭선교)이라 강정·고령(GJGR)과 헷갈리기 쉽다. 숭선교는 해평 측정점과 같은 구미보 하류·칠곡보 상류 구간이다(측정 빈도는 2015년부터 연 37~40회, 2012~2014 월 1회). 상류 후보 선산(2009A30)은 구미보 상류 500 m 라 보를 하나 건넌다.
- 강정·고령(GJGR)은 금호강 합류점(강정고령보 지점) 상류 측정소여야 한다. 조류 측정점(보 상류 7 km)은 상류 성주대교(2011A40)와 하류 다사(2011A55, 보 상류 500 m) 사이의 같은 보 구간에 있는 것으로 보이고(하천 거리 추정), 그 사이에 큰 지류 합류가 없어(하빈천 등 소하천만) 거리가 가장 가까운 다사를 대표로, 성주는 상류 민감도로 썼다(달성 2011A60 은 다사와 같은 지점 부근의 다른 기관 측정소).
- 회남(DCHN)은 근사 좌표 기준 최근접이 대청댐6(4.1 km)이지만, 주소가 '보은군 회남면 어성리 회남교'인 대청댐5(대청호, 3008B30)가 조류경보 측정점(회남대교)과 같은 곳이라 이를 대표로 했다. 호소 측정소는 같은 날 여러 수심을 재므로 가장 얕은 수심(표층)만 쓴다. 월 1회 측정.
- 항목: TN·TP·NO3-N·NH3-N·PO4-P·TDN(API `ITEM_DTN`)·TDP(`ITEM_DTP`)·Chl-a·DO(`ITEM_DOC` = 용존산소)·EC·SS. '정량한계미만'은 0 으로 대치(PO4-P 하천 측정소 약 27~37%, NH3-N 남지 9%). 비율 분모 하한 0.001 mg/L.
- 피처(as_of = base_date, 진입 직후 `cut_as_of`; 공개 지연 d 일이면 obs_date ≤ base_date − d): 항목별 최근값(`_last`)·4주 평균(`_4w`, ref − 27일~ref), N/P 비(`wq_np_last`, `wq_np_4w`), DIN/PO4-P(`wq_dinp_last`), 경과일(`wq_days_since`).
- 변형: 피처 묶음 8종 × 공개 지연 0·30·60일 + 상류 측정소 민감도 2종(`all`·`nutr_last`, 지연 0, 해평→선산 2009A30·강정고령→성주 2011A40·물금매리→삼랑진2 2020A60·회남→대청댐4 3008B10, 칠서는 대표 그대로) = {n_planned}개(실행 {n_var}개). 묶음: `all`(26열) / `nutr_last`(영양염 7 최근값 + N/P·DIN/P + 경과일, 10열) / `nutr_4w`(영양염 7 4주 평균 + N/P 4주 + 경과일, 9열) / `ratio_tp`(TP·PO4-P·비율, 7열) / `other_last`(Chl-a·DO·EC·SS 최근값 + 경과일, 5열) / `tp_np`(TP·N/P 최근값 + 경과일, 3열) / `p_last`(TP·PO4-P·TDP 최근값 + 경과일, 4열) / `n_last`(TN·NO3-N·NH3-N·TDN 최근값 + 경과일, 5열). 기존 v1 피처 30개에 더해 v1 하이퍼파라미터(C1·C3·C2·분위)로 재학습.
- 공개 지연 60일 변형을 추가한 이유: 2026-10-21 수집 시점 API 의 최신 측정일이 2026-08-27 로, 실제 공개 지연이 약 55일이었다(30일 가정은 낙관적).

### 피처 가용률(학습·검증 행, 지점별)

{cov_table}
## 2. 표준 표

{std_table}
### 보조 표

{detail_table}
### 공개 지연 민감도(선택 묶음)

{sens_table}
### 대조군: 관측과 무관한 난수 열(선택 후보 아님)

새 열을 더하는 것만으로 LightGBM 의 열 표본(feature_fraction 0.8)·분할 후보가 바뀌어 CV 값이 흔들린다. 그 폭을 재려고 표준정규 난수 열(3개 4벌, 10개 1벌; config 시드 42 생성기 하나에서 차례로 생성)을 v1 피처에 더해 같은 방식으로 학습했다.

{placebo_table}
{interp}
## 3. 선택한 변형과 채택 판정

- 선택: **{chosen}** — {rule_note}(EXP-PLAN 4절, CV 2020~2024 만 사용).
- 새 열: {chosen_cols}
- 채택 판정(`harness.adoption`): CV r2_raw {d_r2:+.3f}, CV rmse_log {d_rmse:+.3f}, 리드타임 {lead_ok} → **{verdict}**(기준: r2_raw +0.10 이상, rmse_log 악화 0.01 이내, 리드타임 감소 없음).
- (지점, 연도) 블록 부트스트랩(CV 행, 1,000회, 시드 42): v1 대비 CV r2_raw 차 {boot_point:+.3f}, 90% 구간 [{boot_q05:+.3f}, {boot_q95:+.3f}], 차 ≤ 0 비율 {boot_p:.2f}. 이 구간은 학습을 고정한 채 행 표본 변동만 반영하므로, 난수 열 대조군(2절)과 함께 읽어야 한다 — 대조군도 같은 크기의 차를 낸다면 영양염 효과의 증거가 아니다.
- 선택 변형 연도별 NNLS 가중치: {weights}

## 4. 누수·2026 점검

- `tests/test_exp_r4_nutrients.py`: as_of(또는 as_of − 지연) 이후 측정을 난수로 바꾸고 절반 삭제·행 추가해도 피처가 같은지(지연 0·30·60), as_of 이전 값을 바꾸면 피처가 바뀌는지, 응답 파싱(정량한계미만·DMS)·표층 선택·build_features 인덱스 — 통과.
- 모델 프레임은 `harness.load_base()`(base_date ≤ 2025-12-31) + `guard_no_2026` 통과. 원자료에 2026-01~08 측정이 들어 있지만 피처는 base_date ≤ 2025-12-31 행에만 계산하고 2026 지표·그림은 만들지 않았다.
- `python scripts/exp_check_protected.py`: 보호 파일 변경 0개. 공유 파일(harness·기존 src·config·MANIFEST·docs) 수정 없음.

## 5. 소요 시간·한계·다음 단계

- 소요: 시작 2026-10-21 17:53 KST 부터 {elapsed:.2f}시간(상한 8시간). 마지막 실행 {run_min:.1f}분(변형별 학습 결과는 `data/processed/exp/{exp}/cache/` 재사용; `--fresh` 전체 재학습은 변형 31개 약 13~25분, 다른 실험과 CPU 를 나눠 쓴 시간 포함). 같은 입력으로 두 번 전체 학습해 지표가 소수 셋째 자리까지 같음(결정적)을 확인했다.
- 한계: (1) 측정망은 주 1회(해평 강정은 연 37회 내외, 회남은 월 1회)라 7일 예측 시점의 영양염 상태를 성기게 반영한다. (2) 실제 공개 지연이 약 2개월이라 운영(실시간)에서는 지연 60일 변형이 현실적인 값이다. (3) 회남은 월 1회·호소 표층이라 4주 평균이 자주 비어 있다. (4) 지점 좌표가 근사값이라 거리는 참고치다. (5) 단일 시드(v1 규칙)라 변형 간 차가 학습 난수에 크게 흔들린다(대조군 참고). 26개 변형 중 최댓값을 고르므로 선택 변형의 CV 값은 낙관적으로 치우친다(승자의 저주). 블록 부트스트랩은 행 표본 변동만 반영하고 학습 난수 변동은 반영하지 않는다.
- 다음 단계: {next_step}

첨부: `metrics.json`(모든 변형·대조군 지표), `manifest_snippet.md`, `docs02_snippet.md`, `sites_snippet.yaml`. 행 단위 OOF·피처: `data/processed/exp/{exp}/chosen_oof.parquet`, `features.parquet`.
"""


def write_snippets(dist: pd.DataFrame) -> None:
    """manifest_snippet.md·docs02_snippet.md·sites_snippet.yaml (통합은 메인 세션)."""
    import hashlib

    pq = RAW_PATH
    raw = pd.read_parquet(pq)
    sha = hashlib.sha256(pq.read_bytes()).hexdigest()
    fetched = pd.to_datetime(raw["fetched_at"]).min().strftime("%Y-%m-%d %H:%M KST")
    period = f"{raw['obs_date'].min()}~{raw['obs_date'].max()}"
    (OUT_REP / "manifest_snippet.md").write_text(
        "# MANIFEST 추가 행(EXP-007, 메인 세션이 data/raw/MANIFEST.md 에 통합)\n\n"
        "| id | 데이터명 | 기관 | 엔드포인트/URL | 기간 | 수집일시 | 행수 | 라이선스 | sha256 |\n"
        "|----|---------|------|---------------|------|---------|------|---------|--------|\n"
        f"| WQ-02b | 물환경 수질측정망 운영결과 DB — 5지점 후보 측정소 13곳(본류: 2009A30 선산·2011A10 강정·2011A20 구미·"
        "2011A40 성주·2011A55 다사·2011A60 달성·2020A10 남지·2020A32 함안·2020A60 삼랑진2·2022A10 물금·3008B10 대청댐4·"
        "3008B20 대청댐6·3008B30 대청댐5(대청호)), 17항목(TN·TP·NO3-N·NH3-N·PO4-P·DTN·DTP·Chl-a·DO·EC·SS·수온·pH·BOD·COD·TOC·유량), "
        "호소는 수심별 행 포함 (`data/raw/nier_wqdb/wq_measuring_2012_2026.parquet/.csv`, 측정소표 `wq_measuring_stations.csv`) "
        "| 기후에너지환경부 국립환경과학원 | apis.data.go.kr/1480523/WaterQualityService/getWaterMeasuringList "
        "(ptNoList=13곳 콤마, wmyrList 연 단위, numOfRows=5000, resultType=json, 2012~2026 15요청; 키 `.env` NIER_WQDB_KEY) "
        f"| {period} | {fetched} | {len(raw):,} | 이용허락범위 제한 없음(data.go.kr 활용신청 표기) | {sha[:16]} |\n\n"
        f"- sha256 전체: `{sha}`\n"
        "- 측정일(WMCYMD) 없는 응답 3행(대청댐4·6)은 시점을 알 수 없어 제외.\n"
        "- 2026-10-21 수집 시점 최신 측정일 2026-08-27(공개 지연 약 55일).\n",
        encoding="utf-8",
    )
    (OUT_REP / "docs02_snippet.md").write_text(
        "# docs/02_DATA_SPEC.md WQ-02 보강안(EXP-007, 메인 세션이 통합)\n\n"
        "WQ-02 행 '수집 경로' 칸에 다음을 덧붙인다.\n\n"
        "> **API 경로 확보(2026-10-21, EXP-007)**: 국립환경과학원 수질 DB OpenAPI `https://apis.data.go.kr/1480523/WaterQualityService/getWaterMeasuringList`"
        "(물환경 수질측정망 운영결과 DB, data.go.kr 개발계정 자동승인, 일 10,000건). 인자 `ptNoList`(측정소 코드 콤마 다중)·`wmyrList`(연)·`wmodList`(월, 생략 시 전체)·"
        "`pageNo`·`numOfRows`(5,000 확인)·`resultType=json`. 응답: `PT_NO`·`PT_NM`·`ADDR`·`ORG_NM`·`WMYR`·`WMOD`·`WMWK`(회차)·`WMCYMD`(측정일 YYYY.MM.DD)·`WMDEP`(수심, 호소만)·"
        "경위도 도분초(`LAT_DGR/MIN/SEC`, `LON_*`)·`ITEM_*`(앞뒤 공백 문자열, '정량한계미만' 토큰). `ITEM_DOC` 는 용존산소(DO), `ITEM_DTN`/`ITEM_DTP` 는 용존 총질소/총인, `ITEM_POP` 는 인산염인(PO4-P), `ITEM_CLOA` 는 Chl-a. "
        "측정 빈도: 낙동강 본류 주 1회(구미 강정 2011A10 은 2015~ 연 37~40회, 2012~2014 월 1회), 대청호 월 1회(수심 3층 내외). "
        "**2026년분 제공(2026-08-27 까지, 공개 지연 약 2개월)** → GeoJSON 파일데이터(2025-12 까지)의 2026 공백을 메운다. 키 `.env` `NIER_WQDB_KEY`, 주소 `API_NIER_WQDB`. "
        "수집기 `collect/nier_wq_measuring.py`, 원자료 `data/raw/nier_wqdb/`.\n\n"
        "대표 측정소(피처용, sites.yaml `wq_station`): 해평 2011A10 강정(숭선교) · 강정고령 2011A55 다사(강정고령보 상류 500 m) · 칠서 2020A10 남지(남지교) · 물금매리 2022A10 물금(물금취수장) · 회남 3008B30 대청댐5(회남교, 표층).\n\n"
        "피처 사용 규칙: obs_date ≤ base_date(공개 지연 반영 시 base_date − 30/60일) 측정만, 항목별 최근값·4주 평균·N/P 비·경과일(EXP-007 README).\n",
        encoding="utf-8",
    )
    lines = [
        "# config/sites.yaml 추가안(EXP-007): 각 site 항목에 wq_station(대표)·wq_station_candidates(후보, 거리 km)",
        "# 거리는 sites.yaml 근사 좌표 ↔ 수질 DB API 측정소 좌표(도분초→십진) haversine. relation 은 하천 흐름 기준.",
        "wq_station_source: 국립환경과학원 수질 DB getWaterMeasuringList (2026-10-21)",
        "sites:",
    ]
    for sid, g in dist.groupby("site", sort=False):
        prim = g[g["relation"] == "primary"].iloc[0]
        lines.append(f"  {sid}:")
        lines.append(
            f'    wq_station: {{ pt_no: "{prim.pt_no}", name: "{prim.pt_nm}", addr: "{prim.addr}", '
            f"lat: {prim.lat}, lon: {prim.lon}, distance_km: {prim.dist_api_km} }}"
        )
        lines.append("    wq_station_candidates:")
        for r in g.itertuples(index=False):
            lines.append(
                f'      - {{ pt_no: "{r.pt_no}", name: "{r.pt_nm}", relation: {r.relation}, '
                f"distance_km: {r.dist_api_km}, dates_per_year: {r.dates_per_year} }}"
            )
    (OUT_REP / "sites_snippet.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
