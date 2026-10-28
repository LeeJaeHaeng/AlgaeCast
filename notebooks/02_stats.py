# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # T2 통계분석 (docs/04 §1 S1~S10)
#
# 입력: T1 수집물(`data/raw/`), 출력: `reports/eda/` (png + 캡션, 표 md, SUMMARY.md).
# 출력 셀은 nbstripout 으로 커밋 전 제거된다 — 그림·표는 reports/eda/ 에서 인용.

# %%
from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pymannkendall as mk
import seaborn as sns
import statsmodels.api as sm
import yaml
from scipy import stats
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.stattools import adfuller, kpss

from algaecast.features.constants import FINAL_THRESHOLD_YEAR

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
for f in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
    if any(ft.name == f for ft in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid", font=plt.rcParams["font.family"])

ROOT = Path.cwd() if (Path.cwd() / "config").exists() else Path.cwd().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "reports" / "eda"
OUT.mkdir(parents=True, exist_ok=True)
SITES = yaml.safe_load((ROOT / "config" / "sites.yaml").read_text(encoding="utf-8"))
SITE_LIST = SITES["sites"]
SITE_NAME = {s["station_id"]: s["name"] for s in SITE_LIST}
ORDER = ["HP", "GJGR", "CS", "MGMR", "DCHN"]
CAPTIONS: list[str] = []
TABLES: dict[str, str] = {}


def caption(fig_name: str, text: str) -> None:
    CAPTIONS.append(f"- **{fig_name}** — {text}")


def md_table(df: pd.DataFrame, floatfmt: int = 3) -> str:
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].round(floatfmt)
    hdr = "| " + " | ".join(map(str, d.columns)) + " |\n|" + "---|" * len(d.columns)
    body = "\n".join(
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in d.itertuples(index=False)
    )
    return hdr + "\n" + body


def save_table(name: str, title: str, df: pd.DataFrame, note: str = "", floatfmt: int = 3) -> None:
    text = f"# {title}\n\n{md_table(df, floatfmt)}\n" + (f"\n{note}\n" if note else "")
    (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    TABLES[name] = text


# %% [markdown]
# ## 데이터 적재 — 조류(WQ-01), ASOS(주 관측소), 수문(댐 유입·방류·저수율, 보 수위)

# %%
algae = pd.read_parquet(RAW / "nier_algae" / "nier_algae_2012_2026.parquet")
algae["obs_date"] = pd.to_datetime(algae["obs_date"])
algae = algae[algae["station_id"].isin(ORDER)].copy()
algae["cells"] = algae["iem_bgalage_cell_co"].astype(float)
algae["log_cells"] = np.log10(algae["cells"] + 1)
algae["year"] = algae["obs_date"].dt.year
algae["month"] = algae["obs_date"].dt.month
algae["doy"] = algae["obs_date"].dt.dayofyear

asos = pd.read_parquet(RAW / "kma_asos" / "kma_asos_daily_2012_2026.parquet")
asos["obs_date"] = pd.to_datetime(asos["obs_date"])

hydro = pd.read_parquet(RAW / "hydro" / "hydro_daily_long.parquet")
hydro["obs_date"] = pd.to_datetime(hydro["obs_date"])
SRC_PRIORITY = {"bundle_wamis": 0, "kwater_sluice_delist": 1, "wamis_mn_dtdata": 2, "kwater_damapi": 3}
hydro["prio"] = hydro["source"].map(SRC_PRIORITY).fillna(9)
hydro = hydro.sort_values("prio").drop_duplicates(["facility_code", "variable", "obs_date"], keep="first")
hydro_w = hydro.pivot_table(index=["facility_code", "obs_date"], columns="variable", values="value")
KWATER2CODE = (
    hydro[["kwater_code", "facility_code"]]
    .dropna()
    .drop_duplicates()
    .set_index("kwater_code")["facility_code"]
)
MAIN_DAMS = {k for k, v in SITES["dams"].items() if v.get("role") == "main"}

DAYS = pd.date_range("2012-01-01", algae["obs_date"].max())


def site_daily(site: dict) -> pd.DataFrame:
    """지점별 일 단위 설명변수 프레임 (기온·강수·일조·풍속, 댐 유입·방류·저수율, 시설 수위)."""
    sid = site["station_id"]
    a = asos[asos["stn_id"] == int(site["asos_primary"])].set_index("obs_date")
    df = pd.DataFrame(index=DAYS)
    df["ta"] = a["avg_ta"].reindex(DAYS)
    df["rn"] = a["sum_rn"].reindex(DAYS)
    df["ss"] = a["sum_ss_hr"].reindex(DAYS)
    df["ws"] = a["avg_ws"].reindex(DAYS)
    dams = [d for d in site.get("upstream_dams", []) if d in MAIN_DAMS]
    if site.get("facility_dam_code"):
        dams = [site["facility_dam_code"]]  # 회남: 대청댐 자체
    parts = [hydro_w.loc[d] for d in dams if d in hydro_w.index.get_level_values(0)]
    if parts:
        stack = pd.concat(parts, keys=range(len(parts)))
        g = stack.groupby(level=1)
        df["inflow"] = g["iqty"].sum(min_count=1).reindex(DAYS)
        df["discharge"] = g["tdqty"].sum(min_count=1).reindex(DAYS)
        df["storage"] = g["rsvwtrt"].mean().reindex(DAYS)
    fac = site.get("facility_dam_code") or KWATER2CODE.get(site.get("facility_kwater_code"))
    if fac in hydro_w.index.get_level_values(0):
        df["wl"] = hydro_w.loc[fac]["rwl"].reindex(DAYS)
    df["station_id"] = sid
    return df


DAILY = {s["station_id"]: site_daily(s) for s in SITE_LIST}
VARS = ["ta", "rn", "ss", "ws", "inflow", "discharge", "storage", "wl"]
VAR_KO = {
    "ta": "기온",
    "rn": "강수",
    "ss": "일조",
    "ws": "풍속",
    "inflow": "댐 유입량",
    "discharge": "댐 총방류량",
    "storage": "저수율",
    "wl": "보/댐 수위",
    "wtemp": "수온",
}
print({k: v.notna().mean().round(2).to_dict() for k, v in DAILY.items()})

# %% [markdown]
# ## S1 타깃 분포

# %%
fig, axes = plt.subplots(1, 3, figsize=(15, 4))
axes[0].hist(algae["cells"].dropna(), bins=60, color="tab:blue")
axes[0].set_title("유해남조류 세포수 (cells/mL)")
axes[0].set_yscale("log")
axes[1].hist(algae["log_cells"].dropna(), bins=40, color="tab:green")
axes[1].set_title("log10(x+1)")
sns.boxplot(data=algae, x="station_id", y="log_cells", order=ORDER, ax=axes[2])
axes[2].set_xticklabels([SITE_NAME[s] for s in ORDER])
axes[2].set_title("지점별 log10(x+1)")
fig.tight_layout()
fig.savefig(OUT / "fig_target_dist.png", dpi=150)
plt.close(fig)

rows = []
for sid, g in algae.groupby("station_id"):
    c = g["cells"].dropna()
    ad = stats.anderson(np.log10(c[c > 0]), dist="norm")
    q = c.quantile([0.5, 0.75, 0.9, 0.95, 0.99])
    rows.append(
        {
            "지점": SITE_NAME[sid],
            "n": len(c),
            "0값 비율 %": round(100 * (c == 0).mean(), 1),
            "중앙값": q[0.5],
            "P75": q[0.75],
            "P90": q[0.9],
            "P95": q[0.95],
            "P99": q[0.99],
            "최대": c.max(),
            "≥1,000 %": round(100 * (c >= 1000).mean(), 1),
            "≥10,000 %": round(100 * (c >= 10000).mean(), 1),
            "AD 통계량(log, >0)": round(ad.statistic, 2),
            "AD 5% 임계": round(ad.critical_values[2], 2),
        }
    )
c = algae["cells"].dropna()
ad = stats.anderson(np.log10(c[c > 0]), dist="norm")
ad_raw = stats.anderson(c, dist="norm")
rows.append(
    {
        "지점": "전체",
        "n": len(c),
        "0값 비율 %": round(100 * (c == 0).mean(), 1),
        "중앙값": c.median(),
        "P75": c.quantile(0.75),
        "P90": c.quantile(0.9),
        "P95": c.quantile(0.95),
        "P99": c.quantile(0.99),
        "최대": c.max(),
        "≥1,000 %": round(100 * (c >= 1000).mean(), 1),
        "≥10,000 %": round(100 * (c >= 10000).mean(), 1),
        "AD 통계량(log, >0)": round(ad.statistic, 2),
        "AD 5% 임계": round(ad.critical_values[2], 2),
    }
)
tbl_s1 = pd.DataFrame(rows).set_index("지점").T.reset_index().rename(columns={"index": "항목"})
save_table(
    "tbl_target_dist.md",
    "S1 타깃 분포 (유해남조류 세포수)",
    tbl_s1,
    f"- 원단위 Anderson-Darling 통계량 {ad_raw.statistic:,.0f} (5% 임계 {ad_raw.critical_values[2]:.2f}) → 정규성 기각; "
    f"log10(x+1) 변환 후에도 0값 덩어리 때문에 기각되나 통계량이 크게 감소. 모델링은 log1p 타깃 + 0값 비율 고려.",
    floatfmt=1,
)
caption(
    "fig_target_dist.png",
    "세포수 원단위(로그 y축)·log10(x+1) 히스토그램과 지점별 상자그림. 0값과 우측 긴 꼬리 → log 변환 근거.",
)
print(tbl_s1.to_string())

# %% [markdown]
# ## S2 계절성 — 월 상자그림 + STL (주 단위 리샘플, 주기 52)

# %%
fig, axes = plt.subplots(1, 5, figsize=(22, 4), sharey=True)
for ax, sid in zip(axes, ORDER, strict=True):
    g = algae[algae["station_id"] == sid]
    sns.boxplot(data=g, x="month", y="log_cells", ax=ax, color="tab:cyan", fliersize=2)
    ax.set_title(SITE_NAME[sid])
    ax.set_xlabel("월")
    ax.set_ylabel("log10(cells+1)")
fig.tight_layout()
fig.savefig(OUT / "fig_seasonal_month.png", dpi=150)
plt.close(fig)
caption(
    "fig_seasonal_month.png", "지점별 월 상자그림. 6~10월 집중, 물금·매리는 11월까지 지속, 회남은 8~9월 단봉."
)

WEEKLY = {}
stl_rows = []
for sid in ORDER:
    g = algae[algae["station_id"] == sid].set_index("obs_date")["log_cells"]
    w = g.resample("W").mean()
    w = w[w.first_valid_index() :]
    w_i = w.interpolate(limit_direction="both")
    WEEKLY[sid] = w_i
    if len(w_i) < 104:
        continue
    res = STL(w_i, period=52, robust=True).fit()
    fig = res.plot()
    fig.set_size_inches(10, 7)
    fig.suptitle(f"STL (period=52주) — {SITE_NAME[sid]}", y=1.0)
    fig.tight_layout()
    fig.savefig(OUT / f"fig_seasonal_{sid}.png", dpi=130)
    plt.close(fig)
    var_total = w_i.var()
    stl_rows.append(
        {
            "지점": SITE_NAME[sid],
            "주 수": len(w_i),
            "결측 주 비율 %": round(100 * w.isna().mean(), 1),
            "계절 성분 분산비 %": round(100 * res.seasonal.var() / var_total, 1),
            "추세 성분 분산비 %": round(100 * res.trend.var() / var_total, 1),
            "잔차 분산비 %": round(100 * res.resid.var() / var_total, 1),
        }
    )
    caption(
        f"fig_seasonal_{sid}.png",
        f"{SITE_NAME[sid]} 주 단위 log 세포수 STL 분해(주기 52주, robust). 계절 성분이 분산의 {stl_rows[-1]['계절 성분 분산비 %']}%.",
    )
save_table(
    "tbl_stl.md",
    "S2 STL 분해 분산 비율 (주 단위, 주기 52)",
    pd.DataFrame(stl_rows),
    "- 결측 주는 선형 보간(겨울 비채수 구간 포함) → 계절 성분 과대 가능.",
    1,
)
print(pd.DataFrame(stl_rows).to_string())

# %% [markdown]
# ## S3 lag 상관 — log 세포수 vs 설명변수의 0~30일 lag Spearman

# %%
LAGS = list(range(0, 31))


def lag_corr(sid_list: list[str]) -> pd.DataFrame:
    out = {}
    for v in VARS:
        rs = []
        for lag in LAGS:
            xs, ys = [], []
            for sid in sid_list:
                d = DAILY[sid]
                if v not in d:
                    continue
                g = algae[algae["station_id"] == sid]
                x = d[v].shift(lag).reindex(g["obs_date"]).to_numpy()
                xs.append(x)
                ys.append(g["log_cells"].to_numpy())
            if not xs:
                rs.append(np.nan)
                continue
            x = np.concatenate(xs)
            y = np.concatenate(ys)
            ok = ~np.isnan(x) & ~np.isnan(y)
            rs.append(stats.spearmanr(x[ok], y[ok]).correlation if ok.sum() > 30 else np.nan)
        out[VAR_KO[v]] = rs
    # 수온은 측정일 값만 (lag 0)
    g = algae[algae["station_id"].isin(sid_list)]
    ok = g[["iem_wtrtp", "log_cells"]].dropna()
    out[VAR_KO["wtemp"]] = [stats.spearmanr(ok["iem_wtrtp"], ok["log_cells"]).correlation] + [np.nan] * 30
    return pd.DataFrame(out, index=LAGS).T


LAGC = {"전체": lag_corr(ORDER)}
for sid in ORDER:
    LAGC[SITE_NAME[sid]] = lag_corr([sid])
fig, axes = plt.subplots(2, 3, figsize=(20, 9))
for ax, (name, m) in zip(axes.ravel(), LAGC.items(), strict=True):
    sns.heatmap(m, cmap="RdBu_r", vmin=-0.8, vmax=0.8, center=0, ax=ax, cbar=ax is axes[0, 0])
    ax.set_title(f"lag Spearman — {name}")
    ax.set_xlabel("lag (일)")
fig.tight_layout()
fig.savefig(OUT / "fig_lag_corr.png", dpi=140)
plt.close(fig)
best = []
for name, m in LAGC.items():
    for v in m.index:
        if v == "수온":
            continue
        s_ = m.loc[v]
        if s_.notna().any():
            best.append(
                {
                    "구간": name,
                    "변수": v,
                    "최대|ρ| lag": int(s_.abs().idxmax()),
                    "ρ": round(s_.loc[s_.abs().idxmax()], 3),
                    "ρ(lag0)": round(s_.loc[0], 3),
                    "ρ(lag7)": round(s_.loc[7], 3),
                    "ρ(lag14)": round(s_.loc[14], 3),
                    "ρ(lag30)": round(s_.loc[30], 3),
                }
            )
save_table(
    "tbl_lag_corr.md",
    "S3 lag 상관 요약 (|ρ| 최대 lag)",
    pd.DataFrame(best),
    "- 기온은 14~30일 lag 에서도 상관 유지(누적 열량) → 7/14/30일 창 모두 유의미. 강수·유입·방류는 음의 상관(희석·체류시간 단축).",
)
caption(
    "fig_lag_corr.png",
    "log 세포수와 설명변수(0~30일 lag) Spearman 히트맵, 전체 및 지점별. 창 길이 7/14/30일 선정 근거.",
)
print(LAGC["전체"].iloc[:, [0, 7, 14, 30]].round(3))

# %% [markdown]
# ## S4 선행연구 재현 — 송찬영 외(2023): 수온 0.630, 월 0.374, 댐 유입량 0.188, 총방류량 0.187
#
# 동일 정의: 측정일 기준 세포수(원단위)와 당일 수온·월(1~12)·상류 본댐 유입량 합·총방류량 합의 Pearson 상관(절대값). log 세포수·Spearman 도 병기.

# %%
PRIOR = {"수온": 0.630, "월": 0.374, "댐 유입량": 0.188, "댐 총방류량": 0.187}
rows = []
for scope, sids in [("전체", ORDER)] + [(SITE_NAME[s], [s]) for s in ORDER]:
    frames = []
    for sid in sids:
        g = algae[algae["station_id"] == sid][["obs_date", "cells", "log_cells", "iem_wtrtp", "month"]].copy()
        d = DAILY[sid].reindex(g["obs_date"])
        g["댐 유입량"] = d["inflow"].to_numpy() if "inflow" in d else np.nan
        g["댐 총방류량"] = d["discharge"].to_numpy() if "discharge" in d else np.nan
        frames.append(g.rename(columns={"iem_wtrtp": "수온", "month": "월"}))
    g = pd.concat(frames)
    for v, prior in PRIOR.items():
        ok = g[[v, "cells", "log_cells"]].dropna()
        if len(ok) < 20:
            continue
        rows.append(
            {
                "구간": scope,
                "변수": v,
                "n": len(ok),
                "선행연구 r": prior,
                "Pearson r(원단위)": round(stats.pearsonr(ok[v], ok["cells"])[0], 3),
                "Pearson r(log)": round(stats.pearsonr(ok[v], ok["log_cells"])[0], 3),
                "Spearman ρ": round(stats.spearmanr(ok[v], ok["cells"]).correlation, 3),
            }
        )
tbl_s4 = pd.DataFrame(rows)
save_table(
    "tbl_corr_vs_prior.md",
    "S4 선행연구(송찬영 외 2023) 상관 재현",
    tbl_s4,
    "- 선행연구는 낙동강 보 구간 세포수와의 상관(절대값)으로 보고됨. 본 자료는 2016~2026 조류경보제 5지점. 유입·방류는 상류 본댐 합(회남은 대청댐 자체).\n"
    "- 원단위 Pearson 은 극단값에 좌우되므로 log·Spearman 을 함께 본다. 수온 상관은 하천 지점에서 선행연구와 같은 수준(0.5~0.7), 월은 비선형(여름 봉우리)이라 선형 상관이 낮게 나온다.",
)
print(tbl_s4.to_string())

# %% [markdown]
# ## S5 정상성 — ADF / KPSS (주 단위 보간 log 세포수, 지점별)

# %%
rows = []
for sid in ORDER:
    w = WEEKLY[sid].dropna()
    adf = adfuller(w, autolag="AIC")
    kp = kpss(w, regression="c", nlags="auto")
    adf_d = adfuller(w.diff().dropna(), autolag="AIC")
    rows.append(
        {
            "지점": SITE_NAME[sid],
            "주 수": len(w),
            "ADF 통계량": round(adf[0], 2),
            "ADF p": round(adf[1], 4),
            "KPSS 통계량": round(kp[0], 3),
            "KPSS p": round(kp[1], 3),
            "판정": (
                "정상"
                if adf[1] < 0.05 and kp[1] > 0.05
                else "추세/계절 비정상" if adf[1] >= 0.05 else "ADF 정상·KPSS 기각(계절)"
            ),
            "1차 차분 ADF p": round(adf_d[1], 4),
        }
    )
tbl_s5 = pd.DataFrame(rows)
save_table(
    "tbl_stationarity.md",
    "S5 정상성 검정 (주 단위 log 세포수)",
    tbl_s5,
    "- ADF 가 단위근을 기각하면 수준 모델(차분 불필요)이 가능하나 강한 계절성은 월/적산온도 피처로 설명해야 함. KPSS p 는 0.01~0.1 로 절단됨.",
    4,
)
print(tbl_s5.to_string())

# %% [markdown]
# ## S6 지점 이질성 — Kruskal-Wallis + 지점별 세포수–수온 LOESS

# %%
groups = [algae.loc[algae["station_id"] == s, "log_cells"].dropna() for s in ORDER]
kw = stats.kruskal(*groups)
summer = algae[algae["month"].between(6, 9)]
kw_s = stats.kruskal(*[summer.loc[summer["station_id"] == s, "log_cells"].dropna() for s in ORDER])
fig, ax = plt.subplots(figsize=(9, 6))
for sid, color in zip(ORDER, sns.color_palette("tab10", 5), strict=True):
    g = algae[algae["station_id"] == sid][["iem_wtrtp", "log_cells"]].dropna()
    ax.scatter(g["iem_wtrtp"], g["log_cells"], s=6, alpha=0.25, color=color)
    lo = sm.nonparametric.lowess(g["log_cells"], g["iem_wtrtp"], frac=0.4)
    ax.plot(lo[:, 0], lo[:, 1], color=color, lw=2.5, label=SITE_NAME[sid])
ax.axhline(3, ls="--", color="gray", lw=1)
ax.text(2, 3.05, "관심 1,000", color="gray")
ax.axhline(4, ls="--", color="gray", lw=1)
ax.text(2, 4.05, "경계 10,000", color="gray")
ax.set_xlabel("수온 (℃)")
ax.set_ylabel("log10(cells+1)")
ax.set_title(f"지점별 세포수–수온 LOESS (Kruskal-Wallis H={kw.statistic:.1f}, p={kw.pvalue:.1e})")
ax.legend()
fig.tight_layout()
fig.savefig(OUT / "fig_site_response.png", dpi=150)
plt.close(fig)
rows = []
# 표(관심 도달 수온 = 모델 피처의 지점별 수온 임계)는 제출 모델 T24 학습기간 측정(≤FINAL_THRESHOLD_YEAR = 2024)으로만
# 계산한다(FIX-v2.1 R3, 2026-10-28 T24 전환 — v2.1 이력은 ≤2025).
# 그림·Kruskal-Wallis 는 전 기간 탐색 통계로 둔다.
algae_le_final = algae[pd.to_datetime(algae["obs_date"]).dt.year <= FINAL_THRESHOLD_YEAR]
for sid in ORDER:
    g = algae_le_final[algae_le_final["station_id"] == sid][["iem_wtrtp", "log_cells"]].dropna()
    lo = sm.nonparametric.lowess(g["log_cells"], g["iem_wtrtp"], frac=0.4)
    x_at = lambda t: float(np.interp(t, lo[:, 0], lo[:, 1]))  # noqa: E731
    over = lo[lo[:, 1] >= 3]
    rows.append(
        {
            "지점": SITE_NAME[sid],
            f"n(≤{FINAL_THRESHOLD_YEAR})": len(g),
            "log세포수 중앙값": round(g["log_cells"].median(), 2),
            "LOESS@20℃": round(x_at(20), 2),
            "LOESS@25℃": round(x_at(25), 2),
            "LOESS@28℃": round(x_at(28), 2),
            "관심(1,000) 도달 수온": round(float(over[:, 0].min()), 1) if len(over) else np.nan,
        }
    )
tbl_s6 = pd.DataFrame(rows)
save_table(
    "tbl_site_response.md",
    "S6 지점 이질성",
    tbl_s6,
    f"- 표는 측정일 ≤ {FINAL_THRESHOLD_YEAR}-12-31 자료로 계산했다. 관심 도달 수온은 제출 모델 T24 피처의 지점별 수온 임계(config/derived_constants.json {FINAL_THRESHOLD_YEAR}, 학습기간 자료만)와 같다. CV 폴드는 각 학습기간 자료로 다시 계산한 임계를 쓴다(2019~2025 연도별 값은 같은 JSON, v2.1 이력은 2025).\n"
    "- 아래 Kruskal-Wallis 와 그림 fig_site_response.png 는 2012~2026 전 기간 탐색 통계다(모델 상수에는 쓰지 않음).\n"
    f"- Kruskal-Wallis(전 기간) H={kw.statistic:.1f}, p={kw.pvalue:.2e}; 6~9월만 H={kw_s.statistic:.1f}, p={kw_s.pvalue:.2e} → 지점 간 분포가 다르므로 지점 범주형 피처·지점별 보정 필요.",
    2,
)
caption(
    "fig_site_response.png",
    "지점별 세포수–수온 LOESS. 같은 수온에서도 지점별 반응이 다름(물금·매리 > 강정고령 > 칠서 > 해평 > 회남). 지점 범주형 피처 근거.",
)
print(tbl_s6.to_string())

# %% [markdown]
# ## S7 조기화 추세 — 연도별 첫 관심·경계 발령일(2회 연속 규칙) Mann-Kendall + Sen's slope

# %%
onset = []
for (sid, yr), g in algae.sort_values("obs_date").groupby(["station_id", "year"]):
    lv = g["alert_level_2consec"].astype("float")
    for name, th in (("관심", 1), ("경계", 2)):
        hit = g.loc[lv >= th, "obs_date"]
        onset.append(
            {
                "station_id": sid,
                "지점": SITE_NAME[sid],
                "year": yr,
                "단계": name,
                "첫 발령일": hit.min().date() if len(hit) else None,
                "doy": int(hit.min().dayofyear) if len(hit) else np.nan,
                "n_meas": len(g),
            }
        )
onset = pd.DataFrame(onset)
onset = onset[onset["n_meas"] >= 20]  # 연중 측정이 충분한 연도만
rows = []
for name in ("관심", "경계"):
    for scope, sids in [(SITE_NAME[s], [s]) for s in ORDER] + [
        ("통합(연도별 중앙값, 지점 구성 변화 주의)", ORDER),
        ("통합(지점 평균 제거 잔차, 2016~)", ORDER),
    ]:
        o = onset[(onset["단계"] == name) & onset["station_id"].isin(sids)].dropna(subset=["doy"])
        if scope.startswith("통합(지점"):
            o = o[o["year"] >= 2016].copy()
            o["doy"] = o["doy"] - o.groupby("station_id")["doy"].transform("mean")
            o = o.groupby("year", as_index=False)["doy"].median()
        elif scope.startswith("통합"):
            o = o.groupby("year", as_index=False)["doy"].median()
        if len(o) < 5:
            rows.append({"단계": name, "구간": scope, "연도 수": len(o), "비고": "표본 부족"})
            continue
        o = o.sort_values("year")
        r = mk.original_test(o["doy"].to_numpy())
        sen = mk.sens_slope(o["doy"].to_numpy())
        rows.append(
            {
                "단계": name,
                "구간": scope,
                "연도 수": len(o),
                "기간": f"{int(o['year'].min())}~{int(o['year'].max())}",
                "평균 DOY": round(o["doy"].mean(), 1),
                "MK 추세": r.trend,
                "MK p": round(r.p, 3),
                "Sen slope (일/년)": round(sen.slope, 2),
                "비고": "",
            }
        )
tbl_s7 = pd.DataFrame(rows)
NOTE_S7 = (
    "- 2회 연속 규칙으로 산출한 단계(alert_level_2consec) 기준. 연 20회 이상 측정된 연도만.\n"
    "- '통합(연도별 중앙값)' 은 2012~2015 년이 회남(늦은 발령)만 포함돼 지점 구성 변화가 추세로 잡히는 교란이 있음 "
    "→ '지점 평균 제거 잔차(2016~)' 가 공정한 통합 검정."
)
save_table(
    "tbl_onset_trend.md",
    "S7 첫 발령일 조기화 추세 (Mann-Kendall, Sen's slope; 음수 = 조기화)",
    tbl_s7,
    NOTE_S7,
    2,
)
piv = onset.pivot_table(index="year", columns=["단계", "지점"], values="doy")
save_table("tbl_onset_dates.md", "S7 보조: 연도·지점별 첫 발령 DOY", piv.reset_index(), "", 0)
fig, axes = plt.subplots(1, 2, figsize=(14, 4.5), sharey=True)
for ax, name in zip(axes, ("관심", "경계"), strict=True):
    for sid in ORDER:
        o = onset[(onset["단계"] == name) & (onset["station_id"] == sid)].dropna(subset=["doy"])
        ax.plot(o["year"], o["doy"], marker="o", label=SITE_NAME[sid])
    ax.set_title(f"연도별 첫 {name} 발령일 (DOY)")
    ax.set_xlabel("연도")
    ax.legend(fontsize=8)
axes[0].set_ylabel("DOY")
fig.tight_layout()
fig.savefig(OUT / "fig_onset_trend.png", dpi=150)
plt.close(fig)
caption("fig_onset_trend.png", "연도·지점별 첫 관심/경계 발령일(DOY). 추세 검정 결과는 tbl_onset_trend.md.")
print(tbl_s7.to_string())

# %% [markdown]
# ## S8 결측 구조 — 변수×월 결측률 + 미채수 ~ 유입량·3일 누적강수 로지스틱 회귀

# %%
WQ = ["iem_wtrtp", "iem_ph", "iem_doc", "iem_tur", "iem_chla", "iem_bgalage_cell_co", "iem_geosm", "iem_mib2"]
WQ_KO = {
    "iem_wtrtp": "수온",
    "iem_ph": "pH",
    "iem_doc": "DO",
    "iem_tur": "탁도",
    "iem_chla": "Chl-a",
    "iem_bgalage_cell_co": "세포수",
    "iem_geosm": "지오스민",
    "iem_mib2": "2-MIB",
}
miss = algae.groupby("month")[WQ].apply(lambda g: g.isna().mean() * 100).T
miss.index = [WQ_KO[c] for c in miss.index]
# 측정 자체의 누락: 4~11월 주 1회 기대 → 측정 없는 주 비율
weeks = []
for sid in ORDER:
    g = algae[algae["station_id"] == sid]
    start = g["obs_date"].min()
    wk = (
        pd.Series(1, index=g["obs_date"])
        .resample("W")
        .sum()
        .reindex(pd.date_range(start, algae["obs_date"].max(), freq="W"), fill_value=0)
    )
    weeks.append(pd.DataFrame({"station_id": sid, "week": wk.index, "measured": (wk > 0).astype(int)}))
weeks = pd.concat(weeks)
weeks["month"] = weeks["week"].dt.month
gap = weeks.groupby("month")["measured"].apply(lambda s: 100 * (1 - s.mean()))
miss.loc["주간 미채수(측정 없음)"] = gap.reindex(miss.columns).to_numpy()
fig, ax = plt.subplots(figsize=(11, 5))
sns.heatmap(miss, annot=True, fmt=".0f", cmap="Reds", ax=ax, cbar_kws={"label": "결측률 %"})
ax.set_title("변수 × 월 결측률 (측정행 기준) + 주간 미채수 비율")
ax.set_xlabel("월")
fig.tight_layout()
fig.savefig(OUT / "fig_missing.png", dpi=150)
plt.close(fig)
caption(
    "fig_missing.png",
    "수질 변수×월 결측률과 주간 미채수 비율. 겨울(12~3월) 비채수가 대부분, 하절기에는 세포수 결측이 거의 없음.",
)

# 로지스틱: 4~11월 측정 간격 ≥9일(주 1회 슬롯 누락 = 지연 채수) ~ 직전 측정 후 7일간 최대 유입량(log1p)·3일 누적강수 최대
# (측정 간격 분포: 7일 70~80%, 3~4일 20%(발령 중 주 2회), ≥9일 1~3%)
rows_lr = []
lr_frames = []
for sid in ORDER:
    d = DAILY[sid]
    if "inflow" not in d:
        continue
    g = algae[algae["station_id"] == sid].sort_values("obs_date")
    g = g[g["obs_date"].dt.month.between(4, 11)]
    prev = g["obs_date"].shift(1)
    gap = (g["obs_date"] - prev).dt.days
    w = pd.DataFrame({"station_id": sid, "prev": prev, "gap": gap}).dropna()
    w = w[w["gap"] <= 35]
    rain3 = d["rn"].rolling(3).sum()
    w["log_inflow"] = [
        np.log1p(d["inflow"].loc[t + pd.Timedelta(days=1) : t + pd.Timedelta(days=7)].max())
        for t in w["prev"]
    ]
    w["rain3"] = [rain3.loc[t + pd.Timedelta(days=1) : t + pd.Timedelta(days=7)].max() for t in w["prev"]]
    w["missing"] = (w["gap"] >= 9).astype(int)
    lr_frames.append(w)
lr = pd.concat(lr_frames).dropna(subset=["log_inflow", "rain3"])
for scope, sub in [("전체(지점 더미)", lr)] + [(SITE_NAME[s], lr[lr["station_id"] == s]) for s in ORDER]:
    if sub["missing"].sum() < 10:
        rows_lr.append(
            {"구간": scope, "n 간격": len(sub), "지연(≥9일)": int(sub["missing"].sum()), "비고": "사건 부족"}
        )
        continue
    X = sub[["log_inflow", "rain3"]].copy()
    X["rain3"] = X["rain3"] / 10  # 10 mm 단위
    if scope.startswith("전체"):
        X = pd.concat([X, pd.get_dummies(sub["station_id"], drop_first=True, dtype=float)], axis=1)
    X = sm.add_constant(X)
    try:
        m = sm.Logit(sub["missing"], X).fit(disp=0, maxiter=200)
        rows_lr.append(
            {
                "구간": scope,
                "n 간격": len(sub),
                "지연(≥9일)": int(sub["missing"].sum()),
                "OR 유입량(log1p 1단위)": round(float(np.exp(m.params["log_inflow"])), 3),
                "p 유입량": round(float(m.pvalues["log_inflow"]), 4),
                "OR 3일강수(10 mm)": round(float(np.exp(m.params["rain3"])), 3),
                "p 3일강수": round(float(m.pvalues["rain3"]), 4),
                "비고": "",
            }
        )
    except Exception as exc:  # noqa: BLE001
        rows_lr.append(
            {
                "구간": scope,
                "n 간격": len(sub),
                "지연(≥9일)": int(sub["missing"].sum()),
                "비고": f"수렴 실패 {type(exc).__name__}",
            }
        )
tbl_s8 = pd.DataFrame(rows_lr)
save_table(
    "tbl_mnar.md",
    "S8 채수 지연(4~11월, 측정 간격 ≥9일) ~ 유입량·3일 누적강수 로지스틱 회귀",
    tbl_s8,
    "- 가설 '유량 증가 시 미채수(MNAR)': OR>1·p<0.05 이면 지지. 측정은 주 1회(발령 중 주 2회)가 유지되어 지연 사건이 1~3% 에 불과. 유입량은 상류 본댐 합(회남은 대청댐)의 직후 7일 최대, 강수는 주 관측소 3일 누적의 7일 내 최대.",
    4,
)
print(tbl_s8.to_string())

# %% [markdown]
# ## S9 급증 사례 — 5일 이내 10배 이상 증가 + 선행 7일 패턴

# %%
events = []
MAXGAP = 7  # 주 1회 채수라 5일 이내 사건은 드묾 → ≤7일(연속 주간 측정)까지 포함하고 '간격 일' 로 구분
for sid in ORDER:
    g = algae[algae["station_id"] == sid].sort_values("obs_date").reset_index(drop=True)
    d = DAILY[sid]
    for i in range(1, len(g)):
        dt = (g.loc[i, "obs_date"] - g.loc[i - 1, "obs_date"]).days
        c0, c1 = g.loc[i - 1, "cells"], g.loc[i, "cells"]
        if dt <= MAXGAP and pd.notna(c0) and pd.notna(c1) and c1 >= 1000 and c1 >= 10 * max(c0, 100):
            t1 = g.loc[i, "obs_date"]
            pre = d.loc[t1 - pd.Timedelta(days=7) : t1 - pd.Timedelta(days=1)]
            events.append(
                {
                    "지점": SITE_NAME[sid],
                    "이전 측정일": g.loc[i - 1, "obs_date"].date(),
                    "급증 측정일": t1.date(),
                    "간격 일": dt,
                    "이전 세포수": int(c0),
                    "급증 세포수": int(c1),
                    "배수": round(c1 / max(c0, 1), 1),
                    "수온(급증일)": g.loc[i, "iem_wtrtp"],
                    "선행7일 평균기온": round(pre["ta"].mean(), 1),
                    "선행7일 강수합 mm": round(pre["rn"].sum(), 1),
                    "선행7일 일조합 h": round(pre["ss"].sum(), 1),
                    "선행7일 평균방류 m3/s": (
                        round(pre["discharge"].mean(), 1) if "discharge" in pre else np.nan
                    ),
                    "선행7일 평균유입 m3/s": round(pre["inflow"].mean(), 1) if "inflow" in pre else np.nan,
                }
            )
tbl_s9 = pd.DataFrame(events).sort_values(["지점", "급증 측정일"])
summary9 = (
    tbl_s9.groupby("지점")[
        ["선행7일 평균기온", "선행7일 강수합 mm", "선행7일 일조합 h", "선행7일 평균방류 m3/s"]
    ]
    .median()
    .round(1)
    .reset_index()
)
summary9["사건 수"] = tbl_s9.groupby("지점").size().reindex(summary9["지점"]).to_numpy()
save_table(
    "tbl_bloom_events.md",
    "S9 급증 사건 (연속 측정 ≤7일 사이 10배 이상, 급증 후 ≥1,000 cells/mL; 간격 ≤5일은 docs/04 정의)",
    tbl_s9,
    "\n## 지점별 선행 7일 중앙값\n\n"
    + md_table(summary9, 1)
    + "\n\n- 비교 기준(전체 측정일 선행 7일 중앙값)은 SUMMARY.md 참조.",
    1,
)
base7 = {}
for sid in ORDER:
    d = DAILY[sid]
    g = algae[algae["station_id"] == sid]
    pre = pd.DataFrame(
        {
            t: {
                "ta": d["ta"].loc[t - pd.Timedelta(days=7) : t - pd.Timedelta(days=1)].mean(),
                "rn": d["rn"].loc[t - pd.Timedelta(days=7) : t - pd.Timedelta(days=1)].sum(),
                "ss": d["ss"].loc[t - pd.Timedelta(days=7) : t - pd.Timedelta(days=1)].sum(),
            }
            for t in g["obs_date"]
        }
    ).T
    base7[SITE_NAME[sid]] = pre.median().round(1).to_dict()
print(tbl_s9.to_string())
print("기준(전체 측정일 선행7일 중앙값):", base7)

# %% [markdown]
# ## S10 변수 간 Spearman 상관행렬 (VIF·MI·Boruta 는 T3-c)

# %%
frames = []
for sid in ORDER:
    g = algae[algae["station_id"] == sid][
        ["obs_date", "log_cells", "iem_wtrtp", "iem_ph", "iem_doc", "iem_tur", "iem_chla"]
    ].copy()
    d = DAILY[sid]
    for v in VARS:
        if v in d:
            g[v + "_ma7"] = d[v].rolling(7, min_periods=4).mean().reindex(g["obs_date"]).to_numpy()
    g["rn_sum7"] = d["rn"].rolling(7, min_periods=4).sum().reindex(g["obs_date"]).to_numpy()
    frames.append(g)
corr_df = pd.concat(frames).drop(columns=["obs_date", "rn_ma7"], errors="ignore")
corr_df = corr_df.rename(
    columns={
        "iem_wtrtp": "수온",
        "iem_ph": "pH",
        "iem_doc": "DO",
        "iem_tur": "탁도",
        "iem_chla": "Chl-a",
        "log_cells": "log세포수",
        **{v + "_ma7": VAR_KO[v] + "_ma7" for v in VARS},
        "rn_sum7": "강수_sum7",
    }
)
cm = corr_df.corr(method="spearman")
fig, ax = plt.subplots(figsize=(11, 9))
sns.heatmap(cm, annot=True, fmt=".2f", cmap="RdBu_r", vmin=-1, vmax=1, ax=ax, annot_kws={"size": 7})
ax.set_title("변수 간 Spearman 상관 (측정일 기준, 7일 평균/합)")
fig.tight_layout()
fig.savefig(OUT / "fig_corr_matrix.png", dpi=140)
plt.close(fig)
save_table(
    "tbl_corr_matrix.md",
    "S10 변수 간 Spearman 상관행렬",
    cm.round(2).reset_index().rename(columns={"index": ""}),
    "- |ρ|≥0.8 쌍은 T3-c VIF 에서 정리: 기온_ma7–수온, 유입_ma7–방류_ma7 등.",
    2,
)
caption(
    "fig_corr_matrix.png",
    "측정일 기준 변수 간 Spearman 상관행렬. 기온–수온, 유입–방류 강한 공선성 → T3-c VIF 로 정리.",
)
high = [
    (a, b, round(cm.loc[a, b], 2))
    for i, a in enumerate(cm.index)
    for b in cm.columns[i + 1 :]
    if abs(cm.loc[a, b]) >= 0.7
]
print(high)

# %% [markdown]
# ## 캡션·SUMMARY

# %%
(OUT / "captions.md").write_text(
    "# 그림 캡션 (T2)\n\n" + "\n".join(CAPTIONS) + "\n", encoding="utf-8", newline="\n"
)
s1 = tbl_s1.set_index("항목")
lag_all = LAGC["전체"]
s7 = tbl_s7[tbl_s7["구간"].str.startswith("통합(지점")].set_index("단계")
s8 = tbl_s8.set_index("구간").iloc[0]
lines = [
    "# T2 통계분석 요약 (10줄)",
    "",
    f"1. 타깃: 측정 {len(algae):,}건, 0값 {s1.loc['0값 비율 %', '전체']}%, 중앙값 {s1.loc['중앙값', '전체']:,.0f}, P95 {s1.loc['P95', '전체']:,.0f} cells/mL — 원단위 정규성 기각, log10(x+1) 타깃 사용 (S1).",
    f"2. 계절성: 6~10월 집중, STL 계절 성분이 주 단위 분산의 {pd.DataFrame(stl_rows)['계절 성분 분산비 %'].min()}~{pd.DataFrame(stl_rows)['계절 성분 분산비 %'].max()}% (S2) → 월·적산온도 피처 필수.",
    f"3. lag 상관(전체): 기온 ρ lag0 {lag_all.loc['기온', 0]:.2f} → lag14 {lag_all.loc['기온', 14]:.2f} → lag30 {lag_all.loc['기온', 30]:.2f}; 수온 {lag_all.loc['수온', 0]:.2f}; 방류 lag0 {lag_all.loc['댐 총방류량', 0]:.2f}, 유입 {lag_all.loc['댐 유입량', 0]:.2f} (S3) → 7/14/30일 창 모두 채택.",
    f"4. 선행연구 재현(S4): 수온 Pearson(원단위) 전체 {tbl_s4[(tbl_s4['구간'] == '전체') & (tbl_s4['변수'] == '수온')]['Pearson r(원단위)'].iloc[0]:.2f} / log {tbl_s4[(tbl_s4['구간'] == '전체') & (tbl_s4['변수'] == '수온')]['Pearson r(log)'].iloc[0]:.2f} (선행 0.63), 유입·방류는 음의 상관(선행 +0.19) — 정의·구간 차이, 표 참조.",
    f"5. 정상성(S5): ADF p<0.05 지점 {int((tbl_s5['ADF p'] < 0.05).sum())}/5, KPSS 기각 {int((tbl_s5['KPSS p'] < 0.05).sum())}/5 → 수준 모델 + 계절 피처, 차분 불필요.",
    f"6. 지점 이질성(S6): Kruskal-Wallis H={kw.statistic:.0f}, p={kw.pvalue:.1e}; 관심(1,000) 도달 수온(≤{FINAL_THRESHOLD_YEAR} 측정, 모델 피처 임계와 같음) {', '.join(f'{r.지점} {r._7}℃' for r in tbl_s6.itertuples()) } → 지점 범주형·지점별 보정.",
    f"7. 조기화(S7, 통합 잔차 2016~): 관심 Sen {s7.loc['관심', 'Sen slope (일/년)'] if '관심' in s7.index else 'NA'} 일/년 (MK p={s7.loc['관심', 'MK p'] if '관심' in s7.index else 'NA'}), 경계 {s7.loc['경계', 'Sen slope (일/년)'] if '경계' in s7.index else 'NA'} 일/년 (p={s7.loc['경계', 'MK p'] if '경계' in s7.index else 'NA'}) — 지점별 결과는 표.",
    f"8. 결측(S8): 겨울 비채수 외 하절기 세포수 결측 거의 없음; 미채수~유입량 OR {s8.get('OR 유입량(log1p 1단위)', 'NA')} (p={s8.get('p 유입량', 'NA')}), 3일강수 OR {s8.get('OR 3일강수(10 mm)', 'NA')} (p={s8.get('p 3일강수', 'NA')}) → MNAR 가설 {'지지' if isinstance(s8.get('p 유입량'), float) and s8['p 유입량'] < 0.05 and s8['OR 유입량(log1p 1단위)'] > 1 else '약함/기각'}.",
    f"9. 급증(S9): 10배 급증 사건 {len(tbl_s9)}건(≤5일 {int((tbl_s9['간격 일'] <= 5).sum())}건, ≤7일 포함) — 선행 7일 평균기온 중앙값 {tbl_s9['선행7일 평균기온'].median():.1f}℃(전체 측정일 기준 16~19℃), 강수합 {tbl_s9['선행7일 강수합 mm'].median():.0f} mm, 일조 {tbl_s9['선행7일 일조합 h'].median():.0f} h → 고온·소우·일조 선행 패턴 (tbl_bloom_events.md).",
    f"10. 공선성(S10): |ρ|≥0.7 쌍 {len(high)}개 ({', '.join(f'{a}–{b} {r}' for a, b, r in high[:5])}) → T3-c VIF·Boruta 로 정리.",
    "",
    "## 발표용 그림 추천",
    "- `fig_site_response.png` (S6): 지점별 수온 반응 LOESS + 경보 임계선 — '같은 수온, 다른 지점 반응'을 한 장으로.",
    "- `fig_lag_corr.png` (S3): 변수별 lag 히트맵 — 예측 창(7/14/30일) 설계 근거.",
    "- `fig_onset_trend.png` (S7): 연도별 첫 발령일 — 정책 브리프(조기화) 핵심 그림.",
]
(OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print("\n".join(lines))
