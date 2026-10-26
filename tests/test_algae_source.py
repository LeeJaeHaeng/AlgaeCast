"""조류 원천 선택(collect/algae_source.py) — 패키지 구조 → 대회 번들, 저장소 구조 → 공공 API parquet.

- 선택 규칙: features.yaml algae_source = auto 이면 패키지 구조(src/config)에서 bundle, 저장소 구조에서 api.
- 번들 변환 결과는 API parquet 과 같은 열 이름·순서·형식이고, 겹치는 (지점, 측정일) 행에서 값이 같다
  (차이는 번들의 '분석중'이 API 에서 값이 된 2026-09-10 하루의 수질 보조 항목뿐, PREREG_contingency 6.0).
- 수집기 파생열(4속 합·일치 여부·단일/2회 연속 단계)은 수집기 tidy 와 같은 규칙으로 계산한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from algaecast.collect import algae_source as S
from algaecast.collect import competition as comp
from algaecast.collect import nier_algae as na

HAS_BOTH = comp.available() and S.API_PARQUET.exists()
need_data = pytest.mark.skipif(not HAS_BOTH, reason="대회 번들 또는 API 조류 parquet 없음 (git 미포함)")
PENDING_DAY = date(2026, 9, 10)  # 번들 '분석중' ↔ API 값(클로로필a·지오스민·2-MIB·MC-LR)


def test_resolve_source_rules() -> None:
    assert S.resolve_source("auto", package_layout=True) == "bundle"
    assert S.resolve_source("auto", package_layout=False) == "api"
    for layout in (True, False):
        assert S.resolve_source("bundle", package_layout=layout) == "bundle"
        assert S.resolve_source("api", package_layout=layout) == "api"
    with pytest.raises(ValueError):
        S.resolve_source("nier", package_layout=False)


def test_repo_default_is_api() -> None:
    S.configured_source.cache_clear()
    assert S.configured_source() == "auto"
    assert S.resolve_source() == "api"
    assert S.source_path() == "data/raw/nier_algae/nier_algae_2012_2026.parquet"


def test_load_algae_source_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = pd.DataFrame({"station_id": ["HP"], "obs_date": [date(2020, 1, 6)], "iem_wtrtp": [5.0], "x": [1]})
    p = tmp_path / "api.parquet"
    api.to_parquet(p, index=False)
    monkeypatch.setattr(S, "API_PARQUET", p)
    bundle = api.assign(iem_wtrtp=6.0)
    monkeypatch.setattr(S, "bundle_as_api", lambda: bundle.copy())
    got = S.load_algae_source(["iem_wtrtp", "station_id"], source="api")
    assert list(got.columns) == ["iem_wtrtp", "station_id"] and got["iem_wtrtp"].tolist() == [5.0]
    got = S.load_algae_source(["iem_wtrtp", "station_id"], source="bundle")
    assert list(got.columns) == ["iem_wtrtp", "station_id"] and got["iem_wtrtp"].tolist() == [6.0]
    monkeypatch.setattr(S, "configured_source", lambda: "bundle")
    assert S.load_algae_source()["iem_wtrtp"].tolist() == [6.0]


def test_collector_derived_same_rule_as_tidy() -> None:
    """수집기 tidy 출력에서 파생열을 지우고 다시 계산하면 같은 값(같은 규칙)."""
    rows = [
        ("2011G26", "2026.06.01", "1120", "325", "275", "0", "520"),
        ("2011G26", "2026.06.08", "12000", "12000", "0", "0", "0"),
        ("2011G26", "2026.06.15", "15000", "14000", "1000", "0", "0"),
        ("2011G26", "2026.06.22", "900", "900", "0", "0", "0"),
        ("2011G26", "2026.06.29", "800", "0", "0", "0", "0"),
        ("2011G26", "2026.07.06", "", "", "", "", ""),
        ("2011G56", "2026.06.01", "20000", "20000", "0", "0", "0"),
        ("2011G56", "2026.06.08", "30000", "30000", "0", "0", "0"),
    ]
    items = [
        {
            "swmnCode": code,
            "chckDe": d,
            "iemBgalageCellCo": tot,
            "iemBgalageMicrosts": a,
            "iemBgalageAnba": b,
            "iemBgalageOsrtria": c,
            "iemBgalageApzo": e,
        }
        for code, d, tot, a, b, c, e in rows
    ]
    df = na.tidy(items, pd.Timestamp("2026-10-20 15:00", tz="Asia/Seoul"))
    re = S.add_collector_derived(df.drop(columns=S.DERIVED_COLS))
    for c in S.DERIVED_COLS:
        pd.testing.assert_series_equal(re[c], df[c], check_names=True)
    assert re["alert_level_2consec"].tolist() == [0, 1, 2, 2, 0, 0, 0, 2]


@need_data
def test_bundle_as_api_format_and_overlap_values() -> None:
    api = pd.read_parquet(S.API_PARQUET)
    b = S.bundle_as_api()
    assert list(b.columns) == list(api.columns) == S.API_COLUMNS
    assert {c: str(b[c].dtype) for c in b.columns} == {c: str(api[c].dtype) for c in api.columns}
    na.SCHEMA.validate(b)
    assert (b["source"] == comp.SOURCE).all()
    key = ["site_code", "obs_date"]
    m = api.merge(b, on=key, how="outer", suffixes=("_api", "_bundle"), indicator=True)
    assert int((m["_merge"] == "right_only").sum()) == 0  # 번들에만 있는 행 없음
    api_only = m[m["_merge"] == "left_only"]
    assert len(api_only) == 40 and api_only["obs_date"].min() >= date(2026, 9, 14)
    both = m[m["_merge"] == "both"]
    assert len(both) == len(b) == 2939
    for c in api.columns:
        if c in key or c in ("source", "fetched_at"):
            continue
        x, y = both[f"{c}_api"].astype(object), both[f"{c}_bundle"].astype(object)
        same = (x == y).astype("boolean").fillna(False) | (x.isna() & y.isna())  # 결측끼리는 같다고 본다
        diff = both.loc[~same.to_numpy(dtype=bool), "obs_date"]
        assert set(diff) <= {PENDING_DAY}, f"{c}: {sorted(set(diff))[:5]}"
        if c in ("iem_bgalage_cell_co", "iem_wtrtp", *na.GENUS, "dominant_genus", *S.DERIVED_COLS):
            assert diff.empty, c  # 피처·타깃·파생에 쓰는 열은 겹치는 행 전부 같다


@need_data
def test_consumers_follow_bundle_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """원천 = bundle 이면 상류·속별·수온 임계 로더가 번들을 읽고, 겹치는 측정 값은 API 와 같다."""
    from algaecast.features import constants as K
    from algaecast.features import upstream as U
    from algaecast.models import genus as G

    api_up, api_genus, api_nier = U.load_algae(), G.load_target_algae(), K.load_nier()
    monkeypatch.setattr(S, "configured_source", lambda: "bundle")
    assert S.resolve_source() == "bundle"
    up, genus, nier = U.load_algae(), G.load_target_algae(), K.load_nier()
    last = pd.Timestamp(comp.load_algae()["obs_date"].max())
    pd.testing.assert_frame_equal(up, api_up[api_up["obs_date"] <= last].reset_index(drop=True))
    pd.testing.assert_frame_equal(genus, api_genus)  # 속별 타깃은 ≤2025 라 행까지 같다
    pd.testing.assert_frame_equal(
        nier.reset_index(drop=True), api_nier[api_nier["obs_date"] <= last].reset_index(drop=True)
    )
    assert K.check() == []  # 수온 임계(2019~2025)를 번들로 다시 계산해도 derived_constants.json 과 같다
    assert K.compute_site_thresholds(2025)["data_source"].startswith(S.SOURCE_PATHS["bundle"])


def test_align_and_transitions_follow_bundle_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """원천 = bundle 이면 정렬(load_sources)·전환 평가(official_events)도 번들을 읽는다(패키지에서 API 파일 없이 동작)."""
    from algaecast.align import run as A
    from algaecast.eval import transitions as T

    api_events = T.official_events(T.T10K)
    monkeypatch.setattr(S, "configured_source", lambda: "bundle")
    algae = A.load_sources()["algae"]
    expect = S.bundle_as_api()
    expect["obs_date"] = pd.to_datetime(expect["obs_date"])
    pd.testing.assert_frame_equal(algae.reset_index(drop=True), expect.reset_index(drop=True))
    last = pd.Timestamp(comp.load_algae()["obs_date"].max())
    ev = T.official_events(T.T10K)
    keep = api_events[pd.to_datetime(api_events["발령 측정일 D"]) <= last].reset_index(drop=True)
    pd.testing.assert_frame_equal(ev.reset_index(drop=True), keep)


def test_package_manifest_note() -> None:
    """패키지 MANIFEST 사본은 제목 바로 아래에 'API 조류 파일 미포함·번들 사용' 주를 단다."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "builder", Path(__file__).resolve().parents[1] / "scripts" / "build_submission_package.py"
    )
    b = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(b)
    out = b.package_manifest_text("# MANIFEST\n\n| WQ-01 | ... |\n")
    assert out.startswith("# MANIFEST\n\n> 제출 패키지 사본 주")
    assert "algae_measure.csv" in out and "| WQ-01 | ... |" in out
    assert not any(f.startswith(b.API_ALGAE_DIR + "/") for f in b.RAW_FILES)
