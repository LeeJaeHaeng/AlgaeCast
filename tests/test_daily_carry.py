"""일일 러너 이력 이어 붙이기(carry_rows·carry_forward): 같은 회귀 버전일 때만, 이번 run 에 없는 키만 새 run_id 로 복사."""

from __future__ import annotations

import importlib.util
from types import ModuleType

import pandas as pd

from algaecast.config import ROOT


def _daily() -> ModuleType:
    spec = importlib.util.spec_from_file_location("daily_run", ROOT / "scripts" / "daily_run.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


PREV = [
    {
        "id": 1,
        "run_id": "old",
        "site_id": "2011G56",
        "base_date": "2025-08-04",
        "target_date": "2025-08-11",
        "pred_cell_count": 9.0,
    },
    {
        "id": 2,
        "run_id": "old",
        "site_id": "2011G56",
        "base_date": "2026-10-15",
        "target_date": "2026-10-22",
        "pred_cell_count": 7.0,
    },
    {
        "id": 3,
        "run_id": "old",
        "site_id": "2011G26",
        "base_date": "2026-10-15",
        "target_date": "2026-10-22",
        "pred_cell_count": 5.0,
    },
]


def test_carry_rows_skips_new_keys_and_drops_id() -> None:
    d = _daily()
    out = d.carry_rows(PREV, {("2011G56", "2026-10-15", "2026-10-22")}, "new")
    assert [(r["site_id"], r["base_date"]) for r in out] == [
        ("2011G56", "2025-08-04"),
        ("2011G26", "2026-10-15"),
    ]
    assert all(r["run_id"] == "new" and "id" not in r for r in out)
    assert out[0]["pred_cell_count"] == 9.0


class _Q:
    def __init__(self, data: list[dict], log: list) -> None:
        self.data, self.log = data, log

    def select(self, *a: object) -> _Q:
        return self

    def eq(self, *a: object) -> _Q:
        return self

    def range(self, a: int, b: int) -> _Q:
        self._slice = (a, b)
        return self

    def upsert(self, rows: list[dict], **kw: object) -> _Q:
        self.log.append(rows)
        return self

    def execute(self) -> _Q:
        if hasattr(self, "_slice"):
            a, b = self._slice
            return _Res(self.data[a : b + 1])
        return _Res([])


class _Res:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _SB:
    def __init__(self) -> None:
        self.log: list = []

    def table(self, name: str) -> _Q:
        return _Q(PREV, self.log)


def test_carry_forward_only_same_version() -> None:
    d = _daily()
    new = pd.DataFrame(
        {
            "site_id": ["2011G56"],
            "base_date": [pd.Timestamp("2026-10-15")],
            "target_date": [pd.Timestamp("2026-10-22")],
        }
    )
    sb = _SB()
    assert d.carry_forward(sb, {"run_id": "old", "model_version": "v1"}, "new", new, "v2") == 0
    assert sb.log == []
    n = d.carry_forward(sb, {"run_id": "old", "model_version": "v2"}, "new", new, "v2")
    assert n == 2 and len(sb.log) == 1 and {r["run_id"] for r in sb.log[0]} == {"new"}
    assert d.carry_forward(sb, None, "new", new, "v2") == 0
