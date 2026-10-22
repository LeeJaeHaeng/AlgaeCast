"""MT-05c 기상청 API허브 단기예보 격자자료(``nph-dfs_shrt_grd``) 과거 발표분 → 5지점 격자값 (EXP-005 2차 P3).

2026-10-22 활용신청 승인 후 표본 호출로 확인한 사실(reports/experiments/EXP-005/P3/PROBE_GRID.md):

- 호출 1회 = 발표시각(tmfc) × 발효시각(tmef) × 변수(vars) 1개의 전국 격자 149×253(텍스트, 341 KB). 여러 변수를
  한 번에 요청하면 첫 변수만 온다. 결측은 -99.
- 2016-01 ~ 2021-06-29 발표분(구 동네예보)은 TMX·TMN·R06(6시간 강수량)만 값이 있고 POP·SKY·PTY·T3H·REH 는
  전국이 0으로 채워져 있다(실제 값 아님). 2021-06-30 발표분부터(단기예보) TMX·TMN·POP·SKY·PCP·TMP 가 있다.
- 05시 발표분의 +3일(글피) 값은 2021-09 에는 0채움, 2022-01 부터 있다. 구 동네예보는 +2일까지.
- 일부 발표분은 전 변수가 -99(예: 2021-03-15·2021-05-15 05시) → 직전 발표분으로 대체한다.

수집 단위는 5지점 격자 칸 값과 육지 격자 요약(0채움 판별용)뿐이다. 전국 격자 원본은 저장하지 않는다.
한도: 일반회원 일 20,000건·5 GB(341 KB × 약 1.4만 건).
호출마다 calls.jsonl 에 한 줄씩 추가하므로 끊겨도 이어받는다.

키 취급: ``authKey`` 는 요청 인자로만 쓰고 기록·출력하지 않는다(오류 문자열은 scrub).

사용: python -m algaecast.collect.kma_fcst_grid_hist [--phase temp|sky|rain|all] [--workers 4] [--dry-run]
      python -m algaecast.collect.kma_fcst_grid_hist --to-long   # calls.jsonl → fcst_long.parquet
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from algaecast.collect.base import KST
from algaecast.collect.kma_apihub_fcst import APIHUB, KEY_ENV, scrub, site_grids
from algaecast.config import ROOT, get_env

log = logging.getLogger(__name__)

URL = APIHUB + "typ01/cgi-bin/url/nph-dfs_shrt_grd"
OUT_DIR = ROOT / "data" / "raw" / "kma_fcst_grid"
CALLS = OUT_DIR / "calls.jsonl"
LONG = OUT_DIR / "fcst_long.parquet"
NX, NY = 149, 253
MISSING = -90.0
NEW_FROM = date(2021, 6, 30)  # 단기예보 체계(POP·SKY·PCP) 첫 발표일 — 표본 호출로 확인
D3_FROM = date(2021, 9, 16)  # +3일 값 시작 탐색 하한(2021-09-15 은 0채움 확인); 실제 시작일은 탐색으로 정한다
FIRST = date(2016, 1, 1)
LAST = date(2025, 12, 31)
FALLBACK_HOURS = (5, 2, -1, -4, -7)  # 05 → 02 → 전날 23 → 20 → 17 (05시 기준 24시간 안)
TEMP_HOURS = {"TMX": 15, "TMN": 6}
SKY_HOURS = (9, 15, 21)  # POP·SKY·PCP 표본 시각(일 3회)
R06_ENDS = (6, 12, 18, 24)  # 구 동네예보 6시간 강수량 끝 시각(24 = 다음 날 00시)

_lock = threading.Lock()


@dataclass(frozen=True)
class Call:
    tmfc: str  # YYYYMMDDHH
    tmef: str
    var: str

    @property
    def key(self) -> str:
        return f"{self.tmfc}|{self.tmef}|{self.var}"


def _ts(d: date, hour: int) -> str:
    return (datetime(d.year, d.month, d.day) + timedelta(hours=hour)).strftime("%Y%m%d%H")


def issue_ts(base: date, h: int) -> str:
    """기준일 기준 발표시각 문자열. h 가 음수면 전날(예: -1 → 전날 23시)."""
    return _ts(base, h) if h >= 0 else _ts(base - timedelta(days=1), 24 + h)


def is_new(base: date) -> bool:
    return base >= NEW_FROM


def temp_calls(base: date, tmfc: str, d3: bool) -> list[Call]:
    leads = (1, 2, 3) if (is_new(base) and d3) else (1, 2)
    return [
        Call(tmfc, _ts(base + timedelta(days=k), TEMP_HOURS[v]), v) for k in leads for v in ("TMX", "TMN")
    ]


def sky_calls(base: date, tmfc: str, d3: bool) -> list[Call]:
    if not is_new(base):
        return []  # 구 동네예보 POP·SKY 는 0채움
    leads = (1, 2, 3) if d3 else (1, 2)
    return [
        Call(tmfc, _ts(base + timedelta(days=k), h), v)
        for k in leads
        for h in SKY_HOURS
        for v in ("POP", "SKY")
    ]


def rain_calls(base: date, tmfc: str, d3: bool) -> list[Call]:
    if is_new(base):
        leads = (1, 2, 3) if d3 else (1, 2)
        return [Call(tmfc, _ts(base + timedelta(days=k), h), "PCP") for k in leads for h in SKY_HOURS]
    return [Call(tmfc, _ts(base + timedelta(days=k), h), "R06") for k in (1, 2) for h in R06_ENDS]


# ---------------------------------------------------------------- 호출·해석
def parse_grid(text: str) -> np.ndarray | None:
    vals = re.findall(r"-?\d+\.\d+", text)
    if len(vals) != NX * NY:
        return None
    return np.asarray(vals, dtype=float).reshape(NY, NX)


def land_mask(grid: np.ndarray) -> np.ndarray:
    return grid > MISSING


def summarize(grid: np.ndarray, land: np.ndarray) -> dict[str, Any]:
    """육지 격자 요약. status: ok / missing(전부 -99) / zero_fill(전부 0)."""
    x = grid[land]
    xv = x[x > MISSING]
    if xv.size == 0:
        return {"status": "missing", "land_valid": 0.0}
    st = "zero_fill" if bool((xv == 0).all()) else "ok"
    return {
        "status": st,
        "land_valid": round(float(xv.size / x.size), 4),
        "land_zero": round(float((xv == 0).mean()), 4),
        "land_mean": round(float(xv.mean()), 3),
        "land_max": round(float(xv.max()), 3),
    }


def fetch(
    sess: requests.Session, call: Call, key: str, land: np.ndarray | None, timeout: int = 90
) -> dict[str, Any]:
    rec: dict[str, Any] = {"tmfc": call.tmfc, "tmef": call.tmef, "var": call.var}
    try:
        r = sess.get(
            URL,
            params={"tmfc": call.tmfc, "tmef": call.tmef, "vars": call.var, "authKey": key},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        rec.update({"http": None, "status": "error", "message": scrub(str(exc), [key])[:200]})
        return rec
    rec["http"] = r.status_code
    text = r.content.decode("euc-kr", errors="replace")
    grid = parse_grid(text) if r.status_code == 200 else None
    if grid is None:
        rec.update({"status": "error", "message": scrub(text[:200], [key]).replace("\n", " ")})
        return rec
    rec.update(summarize(grid, land if land is not None else land_mask(grid)))
    rec["site"] = {g["station_id"]: float(grid[g["ny"] - 1, g["nx"] - 1]) for g in site_grids()}
    return rec


def done_keys(path: Path = CALLS) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("http") == 200 and rec.get("status") != "error":
                    out[f"{rec['tmfc']}|{rec['tmef']}|{rec['var']}"] = rec
    return out


def run_calls(calls: Iterable[Call], *, workers: int = 4, max_errors: int = 20) -> dict[str, dict[str, Any]]:
    """미완료 호출만 실행해 calls.jsonl 에 추가. 연속 오류가 max_errors 이상이면 멈춘다(한도 초과 등)."""
    key = get_env(KEY_ENV) or ""
    if not key:
        raise RuntimeError(f"{KEY_ENV} 가 .env 에 없다")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    have = done_keys()
    todo = list(dict.fromkeys(c for c in calls if c.key not in have))
    log.info("호출 대상 %d건(이미 받은 %d건 제외)", len(todo), len(have))
    sess = requests.Session()
    land = LAND
    state = {"err": 0, "stop": False, "n": 0}

    def one(c: Call) -> None:
        if state["stop"]:
            return
        rec = fetch(sess, c, key, land)
        rec["fetched_at"] = datetime.now(KST).isoformat(timespec="seconds")
        with _lock:
            with CALLS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            state["n"] += 1
            if rec["status"] == "error":
                state["err"] += 1
                if state["err"] >= max_errors:
                    state["stop"] = True
                    log.error(
                        "연속 오류 %d건 — 중단(마지막: HTTP %s %s)",
                        state["err"],
                        rec.get("http"),
                        rec.get("message"),
                    )
            else:
                state["err"] = 0
                have[c.key] = rec
            if state["n"] % 500 == 0:
                log.info("진행 %d/%d", state["n"], len(todo))

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))
    return have


LAND: np.ndarray | None = None


def init_land() -> np.ndarray:
    """육지 마스크(2024-06-01 05시 발표 → 06-02 15시 TMX 의 유효 격자). 0채움 판별의 기준."""
    global LAND
    key = get_env(KEY_ENV) or ""
    rec_text = requests.get(
        URL, params={"tmfc": "2024060105", "tmef": "2024060215", "vars": "TMX", "authKey": key}, timeout=90
    ).content.decode("euc-kr", errors="replace")
    grid = parse_grid(rec_text)
    if grid is None:
        raise RuntimeError("육지 마스크 격자를 받지 못했다")
    LAND = land_mask(grid)
    return LAND


# ---------------------------------------------------------------- 계획
def base_dates() -> list[date]:
    """실험 기준 행(≤2025, 타깃 있음)의 고유 기준일 중 2016-01-01 이후."""
    from algaecast.exp import harness as H

    b = pd.to_datetime(H.load_base()["base_date"]).dt.date
    return sorted(d for d in set(b) if FIRST <= d <= LAST)


def ok_temp(have: dict[str, dict[str, Any]], base: date, tmfc: str) -> bool:
    rec = have.get(Call(tmfc, _ts(base + timedelta(days=1), 15), "TMX").key)
    return bool(rec and rec.get("status") == "ok")


def find_d3_start(have: dict[str, dict[str, Any]], dates: list[date]) -> date:
    """+3일 TMX 값이 처음 있는 기준일(이분 탐색, 05시 발표). 범위: D3_FROM 이후 신형 기준일."""
    cand = [d for d in dates if d >= D3_FROM]
    lo, hi = 0, len(cand) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        d = cand[mid]
        c = Call(issue_ts(d, 5), _ts(d + timedelta(days=3), 15), "TMX")
        rec = run_calls([c], workers=1).get(c.key)
        if rec and rec.get("status") == "ok":
            hi = mid
        else:
            lo = mid + 1
    return cand[lo]


def choose_issue(
    have: dict[str, dict[str, Any]], dates: list[date], d3_from: date, workers: int
) -> dict[date, str]:
    """기준일별 사용할 발표시각: 05시 → 없으면 02 → 전날 23·20·17(05시 기준 24시간 안)."""
    chosen: dict[date, str] = {}
    pending = list(dates)
    for h in FALLBACK_HOURS:
        if not pending:
            break
        calls = [c for d in pending for c in temp_calls(d, issue_ts(d, h), d >= d3_from)]
        have = run_calls(calls, workers=workers)
        nxt = []
        for d in pending:
            tmfc = issue_ts(d, h)
            if ok_temp(have, d, tmfc):
                chosen[d] = tmfc
            else:
                nxt.append(d)
        pending = nxt
    if pending:
        log.warning("발표분을 찾지 못한 기준일 %d개: %s", len(pending), [str(d) for d in pending[:10]])
    return chosen


def plan_path() -> Path:
    return OUT_DIR / "plan.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--phase", default="all", choices=("temp", "sky", "rain", "all"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--to-long", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.to_long:
        from algaecast.exp.r2nd_p3_kmafcst import calls_to_long

        df = calls_to_long()
        df.to_parquet(LONG, index=False)
        log.info("fcst_long %d행 → %s", len(df), LONG)
        return 0
    dates = base_dates()
    n_new = sum(is_new(d) for d in dates)
    log.info("기준일 %d개(구형 %d · 신형 %d)", len(dates), len(dates) - n_new, n_new)
    if a.dry_run:
        est = sum(
            len(temp_calls(d, "x", True)) + len(sky_calls(d, "x", True)) + len(rain_calls(d, "x", True))
            for d in dates
        )
        log.info("05시 발표분만으로 최대 호출 %d건(+3일 포함 가정)", est)
        return 0
    init_land()
    have = done_keys()
    plan = json.loads(plan_path().read_text(encoding="utf-8")) if plan_path().exists() else {}
    if "d3_from" not in plan:
        plan["d3_from"] = str(find_d3_start(have, [d for d in dates if is_new(d)]))
        plan_path().write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    d3_from = date.fromisoformat(plan["d3_from"])
    log.info("+3일 값 시작 기준일 %s", d3_from)
    if "issue" not in plan or a.phase in ("temp", "all"):
        chosen = choose_issue(have, dates, d3_from, a.workers)
        plan["issue"] = {str(d): t for d, t in chosen.items()}
        plan_path().write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    issue = {date.fromisoformat(k): v for k, v in plan["issue"].items()}
    if a.phase in ("sky", "all"):
        run_calls([c for d, t in issue.items() for c in sky_calls(d, t, d >= d3_from)], workers=a.workers)
    if a.phase in ("rain", "all"):
        run_calls([c for d, t in issue.items() for c in rain_calls(d, t, d >= d3_from)], workers=a.workers)
    have = done_keys()
    log.info("완료 기록 %d건", len(have))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
