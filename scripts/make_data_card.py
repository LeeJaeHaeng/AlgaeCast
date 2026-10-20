"""대회 데이터 카드 생성 (T0-b): docs/DATA_CARD_COMPETITION.md 를 데이터에서 직접 계산해 쓴다.

docs/02_DATA_SPEC.md 2.1절 항목(행수·컬럼·자료형·기간·지점, 타깃 분포, sample_submission 구조, 주기)을
모두 포함한다. 손으로 숫자를 적지 않는다 — 이 스크립트를 다시 실행하면 같은 문서가 나와야 한다.

사용: python scripts/make_data_card.py
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd

from algaecast.collect import competition as comp
from algaecast.config import ROOT

OUT = ROOT / "docs" / "DATA_CARD_COMPETITION.md"
TABLE_DIR = ROOT / "reports" / "eda" / "data_card"
STATION_ORDER = ["HP", "GJGR", "CS", "MGMR", "DCHN"]
SPLIT_ORDER = ["train", "valid", "test", "excluded"]
KEY3 = ["station_id", "base_date", "target_date"]
CAUTION, WARNING, OUTBREAK = 1_000, 10_000, 1_000_000
T = comp.TARGET


# ---------------------------------------------------------------- 마크다운 유틸
def _auto_float(v: float) -> str:
    """1,000 이상은 정수 천단위, 정수값은 정수, 그 외 소수 둘째 자리."""
    if abs(v) >= 1000 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def md_table(df: pd.DataFrame, index: bool = True, floatfmt: str | None = None) -> str:
    d = df.reset_index() if index else df.copy()

    def fmt(v: object) -> str:
        if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
            return ""
        if isinstance(v, (bool, np.bool_)):
            return str(bool(v))
        if isinstance(v, (int, np.integer)):
            return str(int(v)) if 1900 <= int(v) <= 2100 else f"{int(v):,}"  # 연도는 콤마 없이
        if isinstance(v, (float, np.floating)):
            return floatfmt.format(float(v)) if floatfmt else _auto_float(float(v))
        return str(v)

    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, row in d.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in row.values) + " |")
    return "\n".join(lines)


def bullets(d: dict[str, object]) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in d.items())


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def save(name: str, df: pd.DataFrame) -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(TABLE_DIR / f"{name}.csv", encoding="utf-8-sig", lineterminator="\n")


def dtype_summary(df: pd.DataFrame) -> str:
    counts = df.dtypes.astype(str).value_counts()
    return ", ".join(f"{k}×{v}" for k, v in counts.items())


def keyset(df: pd.DataFrame, cols: list[str]) -> set[tuple]:
    return set(map(tuple, df[cols].values))


# ---------------------------------------------------------------- 섹션 계산
def sec_files(data: dict[str, pd.DataFrame]) -> str:
    keys = {
        "stations": "site_code",
        "algae": "(site_code, obs_date)",
        "dam_daily": "(dam_code, obs_date)",
        "asos": "(stn_id, obs_date)",
        "dam_operation_api": "(dam_name, obs_date)",
        "eval_pairs": "(station_id, base_date)",
        "sample_submission": "(station_id, base_date)",
    }
    rows = []
    for name, df in data.items():
        dcol = next((c for c in ("obs_date", "base_date") if c in df.columns), None)
        body = df.drop(columns=["source", "fetched_at"], errors="ignore")
        rows.append(
            {
                "표": name,
                "원본 파일": comp.FILES[name],
                "행": len(df),
                "열(표준화 후)": df.shape[1],
                "키": keys[name],
                "기간(min)": str(df[dcol].min()) if dcol else "(정적)",
                "기간(max)": str(df[dcol].max()) if dcol else "(정적)",
                "자료형": dtype_summary(body),
            }
        )
    t = pd.DataFrame(rows)
    save("files", t)
    return md_table(t, index=False)


def sec_columns(data: dict[str, pd.DataFrame]) -> str:
    parts = []
    for name, df in data.items():
        d = df.drop(columns=["source", "fetched_at"], errors="ignore")
        example = [str(d[c].dropna().iloc[0]) if d[c].notna().any() else "" for c in d.columns]
        info = pd.DataFrame(
            {
                "컬럼": d.columns,
                "dtype": d.dtypes.astype(str).values,
                "결측률": [pct(d[c].isna().mean()) for c in d.columns],
                "예시": example,
            }
        )
        parts.append(f"#### {name}\n\n" + md_table(info, index=False))
    return "\n\n".join(parts)


def sec_stations(data: dict[str, pd.DataFrame]) -> str:
    st = data["stations"].drop(columns=["source", "fetched_at"])
    st = st.set_index("station_id").loc[STATION_ORDER]
    g = data["algae"].groupby("station_id")
    st["측정 건수"] = g.size()
    st["첫 측정"] = g["obs_date"].min().astype(str)
    st["마지막 측정"] = g["obs_date"].max().astype(str)
    # 메타 원본(stations.csv) 복사는 저장하지 않고 측정 현황만 남긴다
    save("station_coverage", st[["site_code", "측정 건수", "첫 측정", "마지막 측정"]])
    return md_table(st)


def _per_station_target(s: pd.Series) -> pd.Series:
    v = s.dropna()
    return pd.Series(
        {
            "n": len(s),
            "결측": int(s.isna().sum()),
            "0값%": 100 * (v == 0).mean(),
            "p50": v.median(),
            "p90": v.quantile(0.9),
            "p99": v.quantile(0.99),
            "max": v.max(),
            "≥1k%": 100 * (v >= CAUTION).mean(),
            "≥10k%": 100 * (v >= WARNING).mean(),
            "≥1M n": int((v >= OUTBREAK).sum()),
        }
    )


def sec_target(data: dict[str, pd.DataFrame]) -> str:
    al = data["algae"]
    y = al[T]
    valid = y.dropna()
    overall = {
        "행": len(al),
        "결측": int(y.isna().sum()),
        "결측률": pct(y.isna().mean()),
        "0값(결측 제외)": int((valid == 0).sum()),
        "0값 비율": pct((valid == 0).mean()),
        "≥1,000 (관심)": pct((valid >= CAUTION).mean()),
        "≥10,000 (경계)": pct((valid >= WARNING).mean()),
        "≥1,000,000 (대발생)": int((valid >= OUTBREAK).sum()),
        "최대": f"{valid.max():,.0f}",
        "평균": f"{valid.mean():,.0f}",
        "log10(x+1) 평균": f"{np.log10(valid + 1).mean():.2f}",
    }
    q = valid.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
    q_df = pd.DataFrame({"분위수": [f"p{int(p * 100)}" for p in q.index], "cells/mL": q.values})

    by_site = al.groupby("station_id")[T].apply(_per_station_target).unstack().loc[STATION_ORDER]
    save("target_by_station", by_site)

    year = pd.to_datetime(al["obs_date"]).dt.year
    aly = al.assign(year=year)
    cnt = aly.pivot_table(index="year", columns="station_id", values=T, aggfunc="size", fill_value=0)
    cnt = cnt.reindex(columns=STATION_ORDER).astype(int)
    cnt["합계"] = cnt.sum(axis=1)
    save("count_by_year_station", cnt)

    def n_missing(s: pd.Series) -> int:
        return int(s.isna().sum())

    miss = aly.pivot_table(index="year", columns="station_id", values=T, aggfunc=n_missing, fill_value=0)
    miss = miss.reindex(columns=STATION_ORDER).astype(int)
    save("target_missing_by_year_station", miss)

    month = pd.to_datetime(al["obs_date"]).dt.month
    grp = al.assign(month=month).groupby("month")[T]
    by_month = pd.DataFrame(
        {
            "n": grp.size(),
            "결측": grp.apply(n_missing),
            "p50": grp.median(),
            "p90": grp.quantile(0.9),
            "경계초과율%": grp.apply(lambda s: 100 * (s.dropna() >= WARNING).mean()),
        }
    )
    save("target_by_month", by_month)

    genus_sum = al[list(comp.GENUS_COLS)].sum(axis=1, min_count=1)
    both = al[T].notna() & genus_sum.notna()
    mismatch = int((both & (np.abs(al[T] - genus_sum) > 0.5)).sum())
    has_oc = al["over_caution"].notna()
    oc_ok = bool(((al[T] >= WARNING).astype(int) == al["over_caution"])[has_oc].all())
    n_both = int(both.sum())
    consist = {
        "속별 4개 합 = 총 세포수 (오차 ≤0.5)": f"{n_both - mismatch:,} / {n_both:,} 행 (불일치 {mismatch:,})",
        "over_caution 파생 일치(세포수 ≥10,000)": str(oc_ok),
    }
    dom = al["dominant_genus"].fillna("(전부 0/결측)").value_counts().rename("n").to_frame()
    big = al.loc[al[T] >= 100_000, ["station_id", "obs_date", T, "dominant_genus"]]
    big = big.sort_values(T, ascending=False).head(10)
    big["obs_date"] = big["obs_date"].astype(str)

    return "\n\n".join(
        [
            "**전체**\n\n" + bullets(overall),
            "**분위수(결측 제외)**\n\n" + md_table(q_df, index=False, floatfmt="{:,.0f}"),
            "**지점별**\n\n" + md_table(by_site),
            "**연도 × 지점 측정 횟수**\n\n" + md_table(cnt),
            "**연도 × 지점 타깃 결측 건수**\n\n" + md_table(miss),
            "**월별 (전 지점 합산)**\n\n" + md_table(by_month),
            "**정합성 점검**\n\n" + bullets(consist),
            "**우점종(dominant_genus) 분포**\n\n" + md_table(dom),
            "**10만 cells/mL 이상 상위 10건**\n\n" + md_table(big, index=False, floatfmt="{:,.0f}"),
        ]
    )


def sec_wq_missing(data: dict[str, pd.DataFrame]) -> str:
    al = data["algae"]
    cols = comp.ALGAE_NUMERIC + comp.ALGAE_LOQ
    t = al.groupby("station_id")[cols].apply(lambda d: d.isna().mean() * 100).loc[STATION_ORDER].T
    t["전체"] = al[cols].isna().mean().values * 100
    t.index.name = "변수"
    save("wq_missing_by_station", t)
    loq = ", ".join(f"{c} {int(al[f'{c}_below_loq'].sum()):,}" for c in comp.ALGAE_LOQ)
    pend = ", ".join(f"{c} {int(al[f'{c}_pending'].sum()):,}" for c in comp.ALGAE_PENDING_COLS)
    pend_mask = al[[f"{c}_pending" for c in comp.ALGAE_PENDING_COLS]].any(axis=1)
    pend_dates = sorted({str(d) for d in al.loc[pend_mask, "obs_date"]})
    rng = al[cols].agg(["min", "max"]).T
    rng.index.name = "변수"
    return "\n\n".join(
        [
            "**변수별 결측률(%) × 지점** — 빈칸 + 아래 비수치 토큰을 모두 결측으로 센 값. "
            "README 의 13.7% / 85.9% / 84.5% 는 빈칸만 센 값이라 0.1%p 낮다.\n\n"
            + md_table(t, floatfmt="{:.1f}"),
            "**'정량한계미만' 건수** (결측으로 변환, `*_below_loq` 플래그 보존): " + loq,
            "**'분석중' 건수** (결측으로 변환, `*_pending` 플래그 보존, 측정일 "
            + ", ".join(pend_dates)
            + "): "
            + pend,
            "**값 범위**\n\n" + md_table(rng),
        ]
    )


def gap_stats(dates: Iterable[date]) -> pd.Series:
    d = pd.to_datetime(pd.Series(sorted(dates)))
    g = d.diff().dt.days.dropna()
    return pd.Series(
        {
            "n": len(d),
            "중앙값(일)": g.median(),
            "평균(일)": g.mean(),
            "7일 비율%": 100 * (g == 7).mean(),
            "≤4일 비율%": 100 * (g <= 4).mean(),
            "≥14일 비율%": 100 * (g >= 14).mean(),
            "최대 공백(일)": g.max(),
        }
    )


def _completeness(df: pd.DataFrame, key: str, name_col: str) -> pd.DataFrame:
    out = []
    for k, grp in df.groupby(key):
        d = pd.to_datetime(grp["obs_date"])
        full = pd.date_range(d.min(), d.max(), freq="D")
        missing = full.difference(pd.DatetimeIndex(d))
        window = f"{missing.min().date()}~{missing.max().date()}" if len(missing) else ""
        out.append(
            {
                key: k,
                name_col: grp[name_col].iloc[0],
                "시작": str(d.min().date()),
                "끝": str(d.max().date()),
                "행": len(grp),
                "기대 일수": len(full),
                "누락 일수": len(missing),
                "누락 구간": window,
            }
        )
    return pd.DataFrame(out).set_index(key)


def sec_frequency(data: dict[str, pd.DataFrame]) -> str:
    al = data["algae"]
    per_site = al.groupby("station_id")["obs_date"].apply(gap_stats).unstack().loc[STATION_ORDER]
    save("algae_gap_by_station", per_site)
    season = pd.to_datetime(al["obs_date"]).dt.month.between(5, 10)
    rows = []
    for label, mask in [("5~10월(조류 시즌)", season), ("11~4월", ~season)]:
        gaps = []
        for _, grp in al[mask].groupby("station_id"):
            g = pd.to_datetime(grp["obs_date"]).sort_values().diff().dt.days.dropna()
            gaps.append(g[g <= 30])  # 시즌 경계의 긴 공백 제외
        g = pd.concat(gaps)
        rows.append(
            {
                "구간": label,
                "간격 중앙값(일)": g.median(),
                "≤4일 비율%": 100 * (g <= 4).mean(),
                "7일 비율%": 100 * (g == 7).mean(),
                "n": len(g),
            }
        )
    season_t = pd.DataFrame(rows)
    dam_c = _completeness(data["dam_daily"], "dam_code", "dam_name")
    asos_c = _completeness(data["asos"], "stn_id", "stn_nm")
    save("dam_completeness", dam_c)
    save("asos_completeness", asos_c)
    return "\n\n".join(
        [
            "**조류경보제 측정 간격 (지점별)**\n\n" + md_table(per_site),
            "**같은 시즌 내 연속 측정 간격** (양끝 측정일이 같은 시즌인 간격만)\n\n"
            + md_table(season_t, index=False),
            "**댐 일자료 완결성**\n\n" + md_table(dam_c),
            "**ASOS 일자료 완결성**\n\n" + md_table(asos_c),
        ]
    )


def _reproduce_pairs(al: pd.DataFrame) -> set[tuple]:
    """README 매칭 규칙으로 (station_id, base_date, target_date) 집합을 재생성한다.

    기준일 = 실측 행이 있는 모든 날짜. 정답일 = base+7 에 가장 가까운 측정일(|차|≤3, 동률이면 이른 날짜).
    그 측정일의 세포수가 결측이면 조합 자체를 제외한다(다음 후보로 넘어가지 않음).
    """
    pairs: set[tuple] = set()
    for sid, g in al.groupby("station_id"):
        g = g.sort_values("obs_date")
        dates = pd.to_datetime(g["obs_date"]).to_numpy()
        values = g[T].to_numpy()
        for b in dates:
            diffs = np.abs((dates - (b + np.timedelta64(7, "D"))).astype("timedelta64[D]").astype(int))
            ok = np.flatnonzero(diffs <= 3)
            if len(ok):
                best = ok[np.argmin(diffs[ok])]  # argmin 은 첫 번째(이른 날짜)를 고른다
                if not np.isnan(values[best]):
                    pairs.add((sid, pd.Timestamp(b).date(), pd.Timestamp(dates[best]).date()))
    return pairs


def sec_eval(data: dict[str, pd.DataFrame]) -> str:
    ev, sub = data["eval_pairs"], data["sample_submission"]
    split_t = ev.pivot_table(
        index="split", columns="station_id", values="lag_days", aggfunc="size", fill_value=0
    )
    split_t = split_t.reindex(columns=STATION_ORDER).loc[SPLIT_ORDER].astype(int)
    split_t["합계"] = split_t.sum(axis=1)
    rng = ev.groupby("split").agg(
        base_min=("base_date", "min"),
        base_max=("base_date", "max"),
        target_max=("target_date", "max"),
        n=("lag_days", "size"),
    )
    rng = rng.loc[SPLIT_ORDER].astype({"base_min": str, "base_max": str, "target_max": str})
    lag = ev.pivot_table(index="lag_days", columns="split", values="station_id", aggfunc="size", fill_value=0)
    lag = lag[SPLIT_ORDER]
    lag["합계"] = lag.sum(axis=1)
    save("eval_split_by_station", split_t)
    save("eval_lag_by_split", lag)

    y = data["algae"].set_index(["station_id", "obs_date"])[T].to_dict()
    y_target = pd.Series([y.get(k) for k in zip(ev["station_id"], ev["target_date"], strict=True)])
    y_base = pd.Series([y.get(k) for k in zip(ev["station_id"], ev["base_date"], strict=True)])
    test_rows = ev.loc[ev["split"] == "test"]
    sub_counts = sub["station_id"].value_counts().reindex(STATION_ORDER)
    by_station = ", ".join(f"{k} {v}" for k, v in sub_counts.items())
    n_meas = len(data["algae"])
    scored = int((ev["split"] != "excluded").sum())
    repro = _reproduce_pairs(data["algae"])
    evset = keyset(ev, KEY3)
    checks = {
        "eval_pairs 행": len(ev),
        "README '93.7% 채점 대상' 재계산": (
            f"{len(ev):,} / {n_meas:,} = {100 * len(ev) / n_meas:.1f}% (excluded 포함); "
            f"실제 채점 train+valid+test {scored:,} / {n_meas:,} = {100 * scored / n_meas:.1f}%"
        ),
        "매칭 규칙 재현 (base+7 최근접 측정일 ±3일, 동률은 이른 날짜, 그 값이 결측이면 조합 제외)": (
            f"{len(repro & evset):,} / {len(evset):,} 일치, "
            f"규칙 초과 {len(repro - evset)}, 누락 {len(evset - repro)}"
        ),
        "target_date 측정값 존재(비결측)": f"{int(y_target.notna().sum()):,} / {len(ev):,}",
        "base_date 측정값 존재(비결측)": f"{int(y_base.notna().sum()):,} / {len(ev):,}",
        "채점 대상(train+valid+test)": int((ev["split"] != "excluded").sum()),
        "sample_submission 행": len(sub),
        "sample_submission == eval_pairs[test]": str(keyset(sub, KEY3) == keyset(test_rows, KEY3)),
        "sample_submission base_date 범위": (
            f"{sub['base_date'].min()} ~ {sub['base_date'].max()} ({sub['base_date'].nunique()}개 기준일)"
        ),
        "sample_submission 지점별": by_station,
        "pred_cells 예시값": f"min {sub['pred_cells'].min()}, max {sub['pred_cells'].max()}",
    }
    return "\n\n".join(
        [
            "**split × 지점**\n\n" + md_table(split_t),
            "**split 별 기간**\n\n" + md_table(rng),
            "**horizon(lag_days) 분포**\n\n" + md_table(lag),
            "**점검**\n\n" + bullets(checks),
        ]
    )


def sec_hydro(data: dict[str, pd.DataFrame]) -> str:
    dam = data["dam_daily"]

    def n_missing(s: pd.Series) -> int:
        return int(s.isna().sum())

    per_dam = dam.groupby(["dam_code", "dam_name", "basin"]).agg(
        행=("obs_date", "size"),
        시작=("obs_date", "min"),
        끝=("obs_date", "max"),
        rwl_med=("rwl", "median"),
        iqty_med=("iqty", "median"),
        iqty_max=("iqty", "max"),
        tdqty_med=("tdqty", "median"),
        rf_결측=("rf", n_missing),
        spdqty_결측=("spdqty", n_missing),
    )
    per_dam[["시작", "끝"]] = per_dam[["시작", "끝"]].astype(str)
    save("dam_summary", per_dam)
    neg = ", ".join(f"{c} {int((dam[c] < 0).sum())}" for c in comp.DAM_NUMERIC)
    api = data["dam_operation_api"]
    api_t = api.groupby(["basin", "dam_name"]).agg(
        행=("obs_date", "size"),
        시작=("obs_date", "min"),
        끝=("obs_date", "max"),
        저수율_min=("rsvwtrt", "min"),
        저수율_max=("rsvwtrt", "max"),
    )
    api_t[["시작", "끝"]] = api_t[["시작", "끝"]].astype(str)
    save("dam_api_summary", api_t)
    api_head = (
        f"**dam_operation_api (data.go.kr 15099049) — {api['obs_date'].nunique()}일 × "
        f"{api['dam_name'].nunique()}개 댐 = {len(api):,}행**"
    )
    return "\n\n".join(
        [
            "**dam_daily (WAMIS) 댐별 요약**\n\n" + md_table(per_dam),
            "**음수 값 건수**: " + neg,
            api_head + "\n\n" + md_table(api_t),
        ]
    )


def sec_weather(data: dict[str, pd.DataFrame]) -> str:
    asos = data["asos"]
    cols = list(comp.ASOS_RENAME.values())
    miss = asos.groupby(["stn_id", "stn_nm"])[cols].apply(lambda d: d.isna().mean() * 100).T
    miss.columns = [f"{i} {n}" for i, n in miss.columns]
    miss.index.name = "변수"
    save("asos_missing_by_station", miss)

    def n_missing(s: pd.Series) -> int:
        return int(s.isna().sum())

    def annual_rain(s: pd.Series) -> float:
        return float(s.sum() / (len(s) / 365.25))

    blank = asos.groupby(["stn_id", "stn_nm"])["rn_blank"].mean().mul(100).rename("sumRn 빈칸(무강수)%")
    summ = asos.groupby(["stn_id", "stn_nm"]).agg(
        avg_ta=("avg_ta", "mean"),
        max_ta_max=("max_ta", "max"),
        rn_연평균=("sum_rn", annual_rain),
        sum_gsr_결측=("sum_gsr", n_missing),
        avg_tca_결측=("avg_tca", n_missing),
    )
    save("asos_summary", summ)
    return "\n\n".join(
        [
            "**지점별 결측률(%)** — `sum_rn`/`hr1_max_rn` 은 빈칸→0 처리 후 값\n\n"
            + md_table(miss, floatfmt="{:.1f}"),
            "**무강수 빈칸 비율 및 요약**\n\n" + md_table(blank.to_frame().join(summ)),
        ]
    )


HEADER = """# 대회 제공 데이터 카드 (DATA_CARD_COMPETITION)

- 생성: `python scripts/make_data_card.py` (수치는 전부 코드로 계산, 손 편집 금지)
- 원본: `data/raw/competition/datas_participants.zip` → `algae_contest_2026/`
  (번들 생성 2026-09-12, sha256 앞 16자리 `91fa7321637bbce1`)
- 로더: `algaecast.collect.competition.load()` — 표준 컬럼(`site_code`/`station_id`/`dam_code`/`stn_id`,
  `obs_date`, `source`, `fetched_at`), 수치 float, 날짜 date
- 타깃: `{target}` (유해남조류 4속 합계, cells/mL). 정답 = base_date+7일에 가장 가까운 측정일(±3일) 값
- 보조 표 CSV: `reports/eda/data_card/`
"""

NOTE_FILES = (
    "번들에는 CSV 외에 `README.md`(과제·매칭 규칙·분할), `03_collect_dataset.py`(주최 측 수집 스크립트, "
    "WAMIS 댐코드의 1차 출처), `06_data_dictionary.xlsx`(필드 정의·경보기준)가 있다. "
    "'열(표준화 후)' 은 `source`·`fetched_at` 메타 2열을 포함한 수이고, "
    "자료형 요약과 9절 컬럼 사전은 메타를 제외한다. "
    "`sample_submission` 은 제출 포맷 보존을 위해 4열 그대로 둔다."
)
NOTE_STATIONS = (
    "`asos_alt_stn_id` 는 주 관측소 결측 시 대체 관측소(칠서만 창원 155). "
    "물금·매리는 2020-05 조류경보제 편입, 회남은 2012-04 부터 수록."
)
NOTE_ALERT = (
    "경보 단계(상수원 구간, 2회 연속 기준): 관심 ≥1,000 / 경계 ≥10,000 / 대발생 ≥1,000,000 cells/mL. "
    "표의 비율은 단일 측정 기준이다."
)
NOTE_SUBMIT = (
    "제출 파일은 `sample_submission.csv` 와 동일한 행·순서·컬럼"
    "(`station_id, base_date, target_date, pred_cells`), UTF-8, `pred_cells` 는 정수 cells/mL."
)


def main() -> int:
    if not comp.available():
        print("대회 데이터 번들이 없습니다:", comp.COMPETITION_DIR)
        return 1
    data = comp.load()
    sections = [
        HEADER.format(target=T),
        "## 1. 파일 구성\n\n" + sec_files(data) + "\n\n" + NOTE_FILES,
        "## 2. 지점 (stations.csv + 측정 현황)\n\n" + sec_stations(data) + "\n\n" + NOTE_STATIONS,
        f"## 3. 타깃 분포 — `{T}`\n\n" + sec_target(data) + "\n\n" + NOTE_ALERT,
        "## 4. 수질 변수 결측·범위 (algae_measure.csv)\n\n" + sec_wq_missing(data),
        "## 5. 주기 확인\n\n" + sec_frequency(data),
        "## 6. 채점 조합 (eval_pairs.csv) 와 제출 형식 (sample_submission.csv)\n\n"
        + sec_eval(data)
        + "\n\n"
        + NOTE_SUBMIT,
        "## 7. 수문 (dam_daily.csv, dam_operation_api.csv)\n\n" + sec_hydro(data),
        "## 8. 기상 (asos_daily.csv)\n\n" + sec_weather(data),
        "## 9. 컬럼 사전 (표준화 후)\n\n" + sec_columns(data),
    ]
    doc = "\n\n".join(sections) + "\n"
    OUT.write_text(doc, encoding="utf-8", newline="\n")
    print(f"written: {OUT} ({len(doc):,} chars); tables: {TABLE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
