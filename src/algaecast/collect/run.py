"""make collect 진입점: 수집기를 순서대로 실행하고 요약표를 출력한다 (T1-g).

각 소스는 별도 프로세스(``python -m ...``)로 실행해 한 소스의 실패가 다른 소스를 막지 않는다.
실패 소스는 상태 FAIL 로 표시하고 계속 진행하며, 종료코드는 모두 성공일 때만 0.

사용: python -m algaecast.collect.run [--start 2012-01-01] [--end 오늘] [--only a,b] [--skip a,b]
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date

from algaecast.config import ROOT

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    name: str
    module: str
    args: tuple[str, ...] = ()
    takes_range: bool = True
    note: str = ""


STEPS: tuple[Step, ...] = (
    Step("nier_algae", "algaecast.collect.nier_algae", note="WQ-01 조류경보제"),
    Step("kwater_dam+wamis", "algaecast.collect.kwater_dam", note="HY-01/02/03/06 댐·보 (WAMIS 포함)"),
    Step("kma_asos", "algaecast.collect.kma_asos", note="MT-01 ASOS 일자료"),
    Step("kma_basin", "algaecast.collect.kma_basin", takes_range=False, note="MT-02/03 CSV(있으면)"),
    Step(
        "dataon_level", "algaecast.collect.dataon_level", takes_range=False, note="HY-05 DataON xlsx(있으면)"
    ),
    Step("kma_forecast", "algaecast.collect.kma_forecast", takes_range=False, note="MT-05/06 오늘 발표분"),
    Step(
        "nier_forecast(mulmoa)",
        "scripts.snapshot_mulmoa_forecast",
        takes_range=False,
        note="WQ-04 물모아 스냅샷",
    ),
)


def _date_arg(s: str) -> date:
    return date.today() if s.strip().lower() == "today" else date.fromisoformat(s)


def run_step(step: Step, start: date, end: date) -> dict:
    if step.module.startswith("scripts."):
        cmd = [sys.executable, str(ROOT / "scripts" / (step.module.split(".", 1)[1] + ".py"))]
    else:
        cmd = [sys.executable, "-m", step.module]
    if step.takes_range:
        cmd += ["--start", start.isoformat(), "--end", end.isoformat()]
    cmd += list(step.args)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    sec = time.perf_counter() - t0
    out_lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    err_lines = [ln for ln in (proc.stderr or "").splitlines() if ln.strip()]
    picked = [ln for ln in out_lines if not ln.startswith(("#", "|", "-", "=", " "))]
    summary = picked[-1] if picked else (err_lines[-1] if err_lines else "")
    return {
        "step": step.name,
        "status": "OK" if proc.returncode == 0 else "FAIL",
        "sec": round(sec, 1),
        "summary": summary[:120],
        "returncode": proc.returncode,
        "stderr_tail": "\n".join(err_lines[-5:]),
    }


def format_table(rows: list[dict]) -> str:
    w = max(len(r["step"]) for r in rows)
    lines = [f"{'소스'.ljust(w)}  상태  초      요약", "-" * (w + 60)]
    for r in rows:
        lines.append(f"{r['step'].ljust(w)}  {r['status']:<4}  {r['sec']:>6}  {r['summary']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=_date_arg, default=date(2012, 1, 1))
    ap.add_argument("--end", type=_date_arg, default=date.today(), help="YYYY-MM-DD 또는 today")
    ap.add_argument("--only", default="", help="쉼표 구분 소스 이름")
    ap.add_argument("--skip", default="")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    only = {s for s in args.only.split(",") if s}
    skip = {s for s in args.skip.split(",") if s}
    rows = []
    for step in STEPS:
        if (only and step.name not in only) or step.name in skip:
            continue
        log.info("▶ %s (%s)", step.name, step.note)
        r = run_step(step, args.start, args.end)
        if r["status"] == "FAIL":
            log.error("%s 실패 (rc=%s)\n%s", step.name, r["returncode"], r["stderr_tail"])
        rows.append(r)
    print("\n== make collect 요약 ==")
    print(format_table(rows))
    return 0 if all(r["status"] == "OK" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
