"""EXP-005 2차 P3 단기예보 피처의 누수 테스트(issued_at ≤ base_date 05시)와 접근 점검 모듈의 키 비노출 점검.

원자료는 받지 못했으므로(API허브 403) 합성 발표분으로 검사한다. 네트워크는 쓰지 않는다(가짜 세션).
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.collect import kma_apihub_fcst as K
from algaecast.exp import r2nd_p3_kmafcst as P

AS_OFS = [date(2024, 7, 15), date(2024, 9, 2), date(2021, 6, 7)]
CATS = ("TMP", "TMX", "POP", "PCP", "SKY", "WSD")


def _issue(site: str, issued: pd.Timestamp, rng: np.random.Generator, horizon_days: int = 4) -> list[dict]:
    """발표 하나: 발표 다음 시각부터 horizon_days 일까지 시간별 TMP·POP·PCP·SKY·WSD, 날마다 TMX 1개."""
    rows = []
    start = issued + pd.Timedelta(hours=1)
    end = issued.normalize() + pd.Timedelta(days=horizon_days)
    for t in pd.date_range(start, end, freq="h"):
        for c, lo, hi in (("TMP", -5, 35), ("POP", 0, 100), ("PCP", 0, 20), ("SKY", 1, 4), ("WSD", 0, 9)):
            rows.append(
                {
                    "station_id": site,
                    "issued_at": issued,
                    "fcst_at": t,
                    "category": c,
                    "value": rng.uniform(lo, hi),
                }
            )
        if t.hour == 15:
            rows.append(
                {
                    "station_id": site,
                    "issued_at": issued,
                    "fcst_at": t,
                    "category": "TMX",
                    "value": rng.uniform(0, 38),
                }
            )
    return rows


def _long(seed: int = 0) -> pd.DataFrame:
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
    fc.loc[fc.index[::37], "value"] = -99.0  # 결측 코드 섞기
    return fc


FC = _long()


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


@pytest.mark.parametrize("as_of", AS_OFS)
@pytest.mark.parametrize("site", ["HP", "DCHN"])
def test_leak_after_cutoff_ignored(as_of: date, site: str) -> None:
    """issued_at > base_date 05:00 인 발표분을 바꾸거나 지워도 결과가 같다(같은 날 08시 이후 발표분 포함)."""
    base = P.forecast_features(FC, as_of, site)
    assert base["p3_fc_available"] == 1.0
    for seed in (1, 2, 3):
        assert _same(base, P.forecast_features(_tamper(FC, as_of, seed), as_of, site))


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


def test_values_match_definition() -> None:
    """+1일 값이 정의(TMX 최대·TMP 평균·PCP 합·POP 최대·SKY·WSD 평균, -99 결측 제외)와 같다."""
    as_of = date(2024, 9, 2)
    out = P.forecast_features(FC, as_of, "DCHN")
    g = FC[(FC["station_id"] == "DCHN") & (pd.to_datetime(FC["issued_at"]) == P.issue_cutoff(as_of))]
    g = g[pd.to_datetime(g["fcst_at"]).dt.normalize() == pd.Timestamp(as_of) + pd.Timedelta(days=1)]
    v = g["value"].where(g["value"] > -90)
    pick = {c: v[g["category"] == c].dropna() for c in CATS}
    assert out["p3_fc_ta_max_d1"] == pytest.approx(pick["TMX"].max())
    assert out["p3_fc_ta_mean_d1"] == pytest.approx(pick["TMP"].mean())
    assert out["p3_fc_rn_sum_d1"] == pytest.approx(pick["PCP"].sum())
    assert out["p3_fc_pop_max_d1"] == pytest.approx(pick["POP"].max())
    assert out["p3_fc_sky_mean_d1"] == pytest.approx(pick["SKY"].mean())
    assert out["p3_fc_ws_mean_d1"] == pytest.approx(pick["WSD"].mean())


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
    """PCP 가 문자열('강수없음'·'1mm 미만'·'30.0~50.0mm')이어도 숫자로 바꿔 합한다."""
    issued = pd.Timestamp("2024-07-15 05:00")
    t1 = pd.Timestamp("2024-07-16 01:00")
    fc = pd.DataFrame(
        {
            "station_id": "HP",
            "issued_at": issued,
            "fcst_at": [t1, t1 + pd.Timedelta(hours=1), t1 + pd.Timedelta(hours=2)],
            "category": "PCP",
            "value": pd.Series(["강수없음", "1mm 미만", "30.0~50.0mm"], dtype=object),
        }
    )
    out = P.forecast_features(fc, date(2024, 7, 15), "HP")
    assert out["p3_fc_rn_sum_d1"] == pytest.approx(0.0 + 0.5 + 40.0)


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
