"""EXP-005 2차 P3 단기예보 피처의 누수 테스트(issued_at ≤ base_date 05시), 수집 기록 해석 규칙, 키 비노출 점검.

합성 발표분으로 검사한다. 네트워크는 쓰지 않는다(가짜 세션).
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from algaecast.collect import kma_apihub_fcst as K
from algaecast.collect import kma_fcst_grid_hist as G
from algaecast.exp import r2nd_p3_kmafcst as P

AS_OFS = [date(2024, 7, 15), date(2024, 9, 2), date(2021, 6, 7)]


def _issue(site: str, issued: pd.Timestamp, rng: np.random.Generator, horizon_days: int = 4) -> list[dict]:
    """발표 하나: 시간별 POP·SKY·PCP, 날마다 TMX(15시)·TMN(06시), 6시간 R06(구간 시작 시각)."""
    rows = []
    start = issued + pd.Timedelta(hours=1)
    end = issued.normalize() + pd.Timedelta(days=horizon_days)

    def add(t: pd.Timestamp, c: str, v: float) -> None:
        rows.append({"station_id": site, "issued_at": issued, "fcst_at": t, "category": c, "value": v})

    for t in pd.date_range(start, end, freq="h"):
        for c, lo, hi in (("POP", 0, 100), ("PCP", 0, 20), ("SKY", 1, 4)):
            add(t, c, rng.uniform(lo, hi))
        if t.hour == 15:
            add(t, "TMX", rng.uniform(0, 38))
        if t.hour == 6:
            add(t, "TMN", rng.uniform(-10, 25))
        if t.hour % 6 == 0:
            add(t, "R06", rng.uniform(0, 30))
    return rows


def _long(seed: int = 0, cats: tuple[str, ...] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for site in ("HP", "DCHN"):
        for d in (
            pd.date_range("2021-06-01", "2021-06-10", freq="D")
            .append(pd.date_range("2024-07-10", "2024-07-20", freq="D"))
            .append(pd.date_range("2024-08-28", "2024-09-06", freq="D"))
        ):
            for h in (2, 5, 8, 11, 14, 17, 20, 23):
                rows += _issue(site, d + pd.Timedelta(hours=h), rng)
    fc = pd.DataFrame(rows)
    if cats is not None:
        fc = fc[fc["category"].isin(cats)]
    fc = fc.reset_index(drop=True)
    fc.loc[fc.index[::37], "value"] = -99.0  # 결측 코드 섞기
    return fc


FC = _long(cats=("TMX", "TMN", "POP", "SKY", "PCP"))  # 단기예보(신형) 모양
FC_OLD = _long(seed=5, cats=("TMX", "TMN", "R06"))  # 구 동네예보 모양


def _tamper(fc: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    """cutoff(as_of 05:00) 뒤 발표분을 난수로 바꾸고 절반을 지운다."""
    rng = np.random.default_rng(seed)
    t = fc.copy()
    after = pd.to_datetime(t["issued_at"]) > P.issue_cutoff(as_of)
    t.loc[after, "value"] = rng.uniform(-1e4, 1e4, after.sum())
    return t.drop(index=t.index[after][::2]).reset_index(drop=True)


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    if a.keys() != b.keys():
        return False
    return all((math.isnan(a[k]) and math.isnan(b[k])) or a[k] == pytest.approx(b[k]) for k in a)


@pytest.mark.parametrize("fc", [FC, FC_OLD], ids=["new", "old"])
@pytest.mark.parametrize("as_of", AS_OFS)
@pytest.mark.parametrize("site", ["HP", "DCHN"])
def test_leak_after_cutoff_ignored(fc: pd.DataFrame, as_of: date, site: str) -> None:
    """issued_at > base_date 05:00 인 발표분을 바꾸거나 지워도 결과가 같다(같은 날 08시 이후 발표분 포함)."""
    base = P.forecast_features(fc, as_of, site)
    assert base["p3_fc_available"] == 1.0
    for seed in (1, 2, 3):
        assert _same(base, P.forecast_features(_tamper(fc, as_of, seed), as_of, site))


@pytest.mark.parametrize("as_of", AS_OFS)
def test_uses_0500_issue_of_base_date(as_of: date) -> None:
    """05시 발표분이 있으면 그것만 쓴다(지연 0시간). 다른 발표분을 모두 지워도 같다."""
    base = P.forecast_features(FC, as_of, "HP")
    assert base["p3_fc_issue_lag_h"] == 0.0
    only = FC[pd.to_datetime(FC["issued_at"]) == P.issue_cutoff(as_of)]
    assert _same(base, P.forecast_features(only, as_of, "HP"))


def test_fallback_to_previous_issue() -> None:
    """당일 02·05시 발표분이 없으면 직전 발표분(전날 23시)을 쓴다 — 지연 6시간."""
    as_of = date(2024, 7, 15)
    day = pd.Timestamp(as_of)
    drop = pd.to_datetime(FC["issued_at"]).isin([day + pd.Timedelta(hours=2), day + pd.Timedelta(hours=5)])
    out = P.forecast_features(FC[~drop], as_of, "HP")
    assert out["p3_fc_issue_lag_h"] == 6.0
    prev = FC[pd.to_datetime(FC["issued_at"]) == day - pd.Timedelta(hours=1)]
    assert _same(out, P.forecast_features(prev, as_of, "HP"))


def _day_rows(fc: pd.DataFrame, as_of: date, site: str, d: int) -> pd.DataFrame:
    g = fc[(fc["station_id"] == site) & (pd.to_datetime(fc["issued_at"]) == P.issue_cutoff(as_of))]
    g = g[pd.to_datetime(g["fcst_at"]).dt.normalize() == pd.Timestamp(as_of) + pd.Timedelta(days=d)].copy()
    g["v"] = g["value"].where(g["value"] > -90)
    return g


@pytest.mark.parametrize("d", [1, 2, 3])
def test_values_match_definition_new(d: int) -> None:
    """단기예보: TMX 최대·TMN 최소, POP 최대·SKY 평균·PCP 평균×24 는 09·15·21시 값만(-99 결측 제외)."""
    as_of = date(2024, 9, 2)
    out = P.forecast_features(FC, as_of, "DCHN")
    g = _day_rows(FC, as_of, "DCHN", d)
    smp = pd.to_datetime(g["fcst_at"]).dt.hour.isin([9, 15, 21])
    pick = {c: g.loc[g["category"] == c, "v"].dropna() for c in ("TMX", "TMN")}
    for c in ("POP", "SKY", "PCP"):
        pick[c] = g.loc[(g["category"] == c) & smp, "v"].dropna()
    assert out[f"p3_fc_ta_max_d{d}"] == pytest.approx(pick["TMX"].max())
    assert out[f"p3_fc_ta_min_d{d}"] == pytest.approx(pick["TMN"].min())
    assert out[f"p3_fc_pop_max_d{d}"] == pytest.approx(pick["POP"].max())
    assert out[f"p3_fc_sky_mean_d{d}"] == pytest.approx(pick["SKY"].mean())
    if len(pick["PCP"]) == 3:
        assert out[f"p3_fc_rn_day_d{d}"] == pytest.approx(pick["PCP"].mean() * 24)
    else:
        assert math.isnan(out[f"p3_fc_rn_day_d{d}"])


def test_values_match_definition_old() -> None:
    """구 동네예보: 강수량 = 그날 6시간 R06 4개 합(하나라도 결측이면 결측), POP·SKY 는 결측."""
    as_of = date(2024, 7, 15)
    out = P.forecast_features(FC_OLD, as_of, "HP")
    for d in (1, 2, 3):
        r06 = _day_rows(FC_OLD, as_of, "HP", d)
        r06 = r06.loc[r06["category"] == "R06", "v"]
        if r06.notna().sum() == 4:
            assert out[f"p3_fc_rn_day_d{d}"] == pytest.approx(r06.sum())
        else:
            assert math.isnan(out[f"p3_fc_rn_day_d{d}"])
        assert math.isnan(out[f"p3_fc_pop_max_d{d}"]) and math.isnan(out[f"p3_fc_sky_mean_d{d}"])


def test_no_issue_before_cutoff_is_missing() -> None:
    """05시 발표분이 없으면 02시 발표분(지연 3시간), 05시 이전 발표분이 하나도 없으면 전부 결측·available 0."""
    day = pd.Timestamp("2021-06-01")
    issued = pd.to_datetime(FC["issued_at"])
    out = P.forecast_features(FC[issued != day + pd.Timedelta(hours=5)], day.date(), "HP")
    assert out["p3_fc_available"] == 1.0 and out["p3_fc_issue_lag_h"] == 3.0
    out2 = P.forecast_features(FC[issued > day + pd.Timedelta(hours=5)], day.date(), "HP")
    assert out2["p3_fc_available"] == 0.0
    assert all(math.isnan(out2[c]) for c in P.FEATURE_COLS if c != "p3_fc_available")


def test_stale_issue_not_used() -> None:
    """24시간보다 오래된 발표분만 있으면 쓰지 않는다(몇 달 전 발표분을 '직전 발표분'으로 쓰지 않음)."""
    out = P.forecast_features(FC, date(2025, 1, 6), "HP")
    assert out["p3_fc_available"] == 0.0
    day = pd.Timestamp("2024-07-15")
    issued = pd.to_datetime(FC["issued_at"])
    keep = (issued <= day - pd.Timedelta(days=1, hours=1)) | (issued > day + pd.Timedelta(hours=5))
    assert P.forecast_features(FC[keep], day.date(), "HP")["p3_fc_available"] == 0.0


def test_pcp_strings_parsed() -> None:
    """PCP 가 문자열('강수없음'·'1mm 미만'·'30.0~50.0mm')이어도 숫자로 바꿔 09·15·21시 평균×24."""
    issued = pd.Timestamp("2024-07-15 05:00")
    day1 = pd.Timestamp("2024-07-16")
    fc = pd.DataFrame(
        {
            "station_id": "HP",
            "issued_at": issued,
            "fcst_at": [day1 + pd.Timedelta(hours=h) for h in (9, 15, 21)],
            "category": "PCP",
            "value": pd.Series(["강수없음", "1mm 미만", "30.0~50.0mm"], dtype=object),
        }
    )
    out = P.forecast_features(fc, date(2024, 7, 15), "HP")
    assert out["p3_fc_rn_day_d1"] == pytest.approx((0.0 + 0.5 + 40.0) / 3 * 24)


def test_bundles_nested_and_exclude_meta() -> None:
    assert set(P.BUNDLES["T"]) < set(P.BUNDLES["TS"]) < set(P.BUNDLES["TSR"]) == set(P.FC_COLS)
    assert not any(c in P.META_COLS for b in P.BUNDLES.values() for c in b)


def test_build_features_same_index() -> None:
    df = pd.DataFrame(
        {
            "station_id": ["HP", "DCHN", "GJGR", "HP"],
            "base_date": pd.to_datetime(["2024-07-15", "2024-09-02", "2024-07-15", "2025-01-06"]),
        },
        index=[10, 11, 12, 13],
    )
    out = P.build_features(df, FC)
    assert list(out.index) == [10, 11, 12, 13]
    assert list(out.columns) == P.FEATURE_COLS
    assert out.loc[10, "p3_fc_available"] == 1.0
    assert out.loc[12, "p3_fc_available"] == 0.0  # 원자료에 없는 지점
    assert out.loc[13, "p3_fc_available"] == 0.0  # 그 날짜 발표분 없음


def test_build_features_rejects_2026() -> None:
    df = pd.DataFrame({"station_id": ["HP"], "base_date": pd.to_datetime(["2026-05-04"])})
    with pytest.raises(RuntimeError):
        P.build_features(df, FC)


# ---------------------------------------------------------------- 수집 기록 해석
def _rec(tmfc: str, tmef: str, var: str, status: str, hp: float, http: int = 200) -> dict:
    return {
        "tmfc": tmfc,
        "tmef": tmef,
        "var": var,
        "http": http,
        "status": status,
        "site": {"HP": hp, "CS": -99.0},
    }


def test_calls_to_long_rules(tmp_path: Path) -> None:
    """0채움 TMX·SKY 는 버리고, POP·PCP 는 같은 시각 SKY 가 ok 일 때만, R06 은 전국 0도 쓰고 구간 시작으로 옮긴다."""
    recs = [
        _rec("2019071505", "2019071615", "TMX", "ok", 31.0),
        _rec("2019071505", "2019071606", "TMN", "zero_fill", 0.0),
        _rec("2019071505", "2019071612", "R06", "zero_fill", 0.0),
        _rec("2019071505", "2019071700", "R06", "ok", 4.5),
        _rec("2024071505", "2024071609", "SKY", "ok", 3.0),
        _rec("2024071505", "2024071609", "POP", "zero_fill", 0.0),
        _rec("2024071505", "2024071615", "SKY", "zero_fill", 0.0),
        _rec("2024071505", "2024071615", "POP", "ok", 60.0),
        _rec("2024071505", "2024071621", "PCP", "error", 1.0, http=403),
    ]
    p = tmp_path / "calls.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
    fc = P.calls_to_long(p)
    got = {(r.category, r.fcst_at.strftime("%Y%m%d%H")): r.value for r in fc.itertuples()}
    assert got == {
        ("TMX", "2019071615"): 31.0,
        ("R06", "2019071606"): 0.0,
        ("R06", "2019071618"): 4.5,
        ("SKY", "2024071609"): 3.0,
        ("POP", "2024071609"): 0.0,
    }
    assert set(fc["station_id"]) == {"HP"}  # CS 의 -99 는 결측


def test_grid_parse_and_summary() -> None:
    a = np.full((G.NY, G.NX), -99.0)
    a[100:150, 60:100] = 0.0
    land = a > -90
    assert G.summarize(a, land)["status"] == "zero_fill"
    a[120, 80] = 12.5
    s = G.summarize(a, land)
    assert s["status"] == "ok" and s["land_max"] == 12.5
    assert G.summarize(np.full((G.NY, G.NX), -99.0), land)["status"] == "missing"
    text = ",".join(f"{x:.2f}" for x in a.ravel())
    assert np.array_equal(G.parse_grid(text), a)
    assert G.parse_grid("1.0, 2.0") is None


def test_plan_calls_by_era() -> None:
    old, new = date(2019, 7, 15), date(2024, 7, 15)
    assert {c.var for c in G.temp_calls(old, "x", True)} == {"TMX", "TMN"}
    assert len(G.temp_calls(old, "x", True)) == 4
    assert len(G.temp_calls(new, "x", True)) == 6 and len(G.temp_calls(new, "x", False)) == 4
    assert G.sky_calls(old, "x", True) == [] and len(G.sky_calls(new, "x", True)) == 18
    assert {c.var for c in G.rain_calls(old, "x", True)} == {"R06"} and len(G.rain_calls(old, "x", True)) == 8
    assert {c.var for c in G.rain_calls(new, "x", True)} == {"PCP"} and len(G.rain_calls(new, "x", True)) == 9
    assert G.issue_ts(new, 5) == "2024071505" and G.issue_ts(new, -1) == "2024071423"
    for h in G.FALLBACK_HOURS:  # 발표시각은 언제나 기준일 05시 이하
        assert pd.to_datetime(G.issue_ts(new, h), format="%Y%m%d%H") <= P.issue_cutoff(new)


class _GridResp:
    def __init__(self, status: int, body: str) -> None:
        self.status_code = status
        self.content = body.encode("euc-kr")


class _GridSess:
    def __init__(self, status: int, body_fn) -> None:  # noqa: ANN001
        self.status, self.body_fn, self.params = status, body_fn, []

    def get(self, url: str, params: dict, timeout: int) -> _GridResp:
        self.params.append(dict(params))
        return _GridResp(self.status, self.body_fn(params))


def test_grid_fetch_never_records_key() -> None:
    secret = "GRIDSECRET_0123456789abcdef"
    sess = _GridSess(403, lambda p: '{"result": {"status": 403, "message": "echo ' + p["authKey"] + '"}}')
    rec = G.fetch(sess, G.Call("2024071505", "2024071615", "TMX"), secret, None)
    assert rec["status"] == "error" and secret not in json.dumps(rec, ensure_ascii=False)
    assert sess.params[0]["authKey"] == secret
    ok = _GridSess(200, lambda p: ",".join(["21.5"] * (G.NX * G.NY)))
    rec2 = G.fetch(ok, G.Call("2024071505", "2024071615", "TMX"), secret, None)
    assert rec2["status"] == "ok" and set(rec2["site"]) == {"HP", "GJGR", "CS", "MGMR", "DCHN"}
    assert secret not in json.dumps(rec2, ensure_ascii=False)


# ---------------------------------------------------------------- 접근 점검(키 비노출)
class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"
        self.headers = {"content-type": "application/json"}


class _Sess:
    def __init__(self, status: int, text_fn) -> None:  # noqa: ANN001
        self.status, self.text_fn, self.calls = status, text_fn, []

    def get(self, url: str, params: dict, timeout: int) -> _Resp:
        self.calls.append((url, dict(params)))
        return _Resp(self.status, self.text_fn(params))


def test_probe_never_exposes_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "SECRETKEY_abcdef123456"
    monkeypatch.setenv(K.KEY_ENV, secret)
    # 응답에 키가 섞여 돌아와도(에코) 기록에는 남지 않아야 한다
    sess = _Sess(
        403, lambda p: '{"result": {"status": 403, "message": "활용신청 필요 ' + p["authKey"] + '"}}'
    )
    rec = K.probe_one(K.ENDPOINTS[0], session=sess, sleep=lambda s: None)
    assert rec["http"] == 403 and rec["ok"] is False
    assert secret not in repr(rec)
    assert "authKey" not in rec["params"]
    assert sess.calls[0][1]["authKey"] == secret  # 요청에는 실어 보낸다


def test_diagnose_403_with_valid_key() -> None:
    res = [
        {"name": "단기예보 격자자료", "http": 403, "message": "활용신청이 필요한 API 입니다.", "ok": False},
        {"name": "단기예보구역 조회", "http": 200, "message": "#START7777", "ok": True},
    ]
    d = K.diagnose(res)
    assert d["key_valid"] and not d["data_access"]
    assert "403" in d["reason"]


def test_site_grids_in_domain() -> None:
    g = K.site_grids()
    assert {x["station_id"] for x in g} == {"HP", "GJGR", "CS", "MGMR", "DCHN"}
    assert all(1 <= x["nx"] <= 149 and 1 <= x["ny"] <= 253 for x in g)
