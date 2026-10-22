# ruff: noqa: E501  (한국어 문서 문자열·MANIFEST 표)
"""HY-06b WAMIS 댐 일자료 추가 수집 — 대회 번들 15개 댐에 없는 상류 댐(영천·운문), 2차 실험 P6 전용.

조류경보제 상수원 호소 지점이 있는 낙동강 상류 댐 가운데 영천댐(영천호 2012G20, 금호강 경유 → 칠서·물금·매리 상류)과
운문댐(운문호 2021G10·2021G20, 동창천 → 밀양강 경유 → 물금·매리 상류)은 기존 수문 자료(data/raw/hydro)에 없다.
기존 수집기 ``WamisDamDailyCollector``(WAMIS 개방 API ``wkd/mn_dtdata``, 인증키 불필요, 연 단위 요청·URL 해시 캐시
``data/raw/cache/``·재시도 3회 지수 백오프)를 그대로 써서 2012-01-01~2025-12-31 만 요청한다(2026 은 요청하지 않음).

WAMIS 댐코드: 2012210 영천, 2021210 운문(docs/reference/sites_facts_verified.json 의 WAMIS 댐 목록 49개).
출력: ``data/raw/wamis_dam_extra/wamis_dam_extra_daily.{parquet,csv}`` (열은 wamis_dam 과 같다: facility_code, obs_date,
rwl, iqty, tdqty, edqty, spdqty, otltdqty, itqty, rf, source, fetched_at).

실행: ``python -m algaecast.collect.wamis_extra_dams`` → 수집 요약(건수·기간·sha256)을 표준 출력과
``reports/experiments/EXP-005/P6/manifest_snippet.md`` 에 쓴다(MANIFEST 통합은 메인 세션).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from algaecast.collect.base import KST
from algaecast.collect.wamis import WamisDamDailyCollector
from algaecast.config import RAW_DIR, ROOT

log = logging.getLogger(__name__)

EXTRA_DAMS: dict[str, str] = {"2012210": "영천", "2021210": "운문"}
OUT_DIR = RAW_DIR / "wamis_dam_extra"
OUT_NAME = "wamis_dam_extra_daily"
START = date(2012, 1, 1)
END = date(2025, 12, 31)  # 2026 은 요청하지 않는다
LAST_TS = pd.Timestamp(END)
SNIPPET = ROOT / "reports" / "experiments" / "EXP-005" / "P6" / "manifest_snippet.md"


def collect(codes: dict[str, str] | None = None, start: date = START, end: date = END) -> pd.DataFrame:
    """영천·운문 댐 일자료(2012~2025)를 받아 저장하고 반환한다."""
    codes = EXTRA_DAMS if codes is None else codes
    if end > END:
        raise ValueError("2026 자료는 요청하지 않는다")
    col = WamisDamDailyCollector(out_dir=OUT_DIR)
    parts = []
    for code, name in codes.items():
        d = col.fetch(code, start, end)
        log.info("WAMIS 댐 %s(%s): %d행 %s~%s", code, name, len(d), d["obs_date"].min(), d["obs_date"].max())
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df = df[pd.to_datetime(df["obs_date"]) <= pd.Timestamp(END)].reset_index(drop=True)
    pq, _ = col.save(df, OUT_NAME)
    log.info("저장 %s (요청 %d, 캐시 적중 %d)", pq, col.n_requests, col.n_cache_hits)
    return df


def load_extra_dams(last: pd.Timestamp = LAST_TS) -> pd.DataFrame:
    """저장한 영천·운문 일자료. last 이후 행은 읽은 즉시 버린다."""
    d = pd.read_parquet(OUT_DIR / f"{OUT_NAME}.parquet")
    d["obs_date"] = pd.to_datetime(d["obs_date"]).dt.normalize()
    return d[d["obs_date"] <= last].reset_index(drop=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_snippet(df: pd.DataFrame) -> str:
    """MANIFEST 조각(수집 일시·건수·기간·sha256)."""
    pq, csv = OUT_DIR / f"{OUT_NAME}.parquet", OUT_DIR / f"{OUT_NAME}.csv"
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    lines = [
        "# MANIFEST 조각 — P6 상류 댐 추가 수집(HY-06b)",
        "",
        "| ID | 이름 | 기관 | 엔드포인트 | 기간 | 수집 일시 | 건수 | 라이선스 | 파일 | sha256 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for code, name in EXTRA_DAMS.items():
        g = df[df["facility_code"] == code]
        period = f"{g['obs_date'].min()}~{g['obs_date'].max()}" if len(g) else "–"
        lines.append(
            f"| HY-06b | {name}댐 일자료(WAMIS {code}) | 환경부 한강홍수통제소 | wkd/mn_dtdata?damcd={code} | "
            f"{period} | {now} | {len(g):,} | 공공누리 1유형(WAMIS 개방 API) | "
            f"data/raw/wamis_dam_extra/{OUT_NAME}.parquet | (아래) |"
        )
    lines += [
        "",
        f"- `data/raw/wamis_dam_extra/{OUT_NAME}.parquet` sha256 `{_sha256(pq)}`",
        f"- `data/raw/wamis_dam_extra/{OUT_NAME}.csv` sha256 `{_sha256(csv)}`",
        "- 변수: rwl 저수위(EL.m), iqty 유입량, tdqty 총방류량, edqty 발전, spdqty 여수로, otltdqty 기타 방류, "
        "itqty 취수량(㎥/s), rf 강우(mm). 2026 은 요청하지 않았다(END = 2025-12-31).",
        "- 수집기: `src/algaecast/collect/wamis_extra_dams.py`(기존 `WamisDamDailyCollector` 재사용, 캐시 `data/raw/cache/`).",
        "",
    ]
    txt = "\n".join(lines)
    SNIPPET.parent.mkdir(parents=True, exist_ok=True)
    SNIPPET.write_text(txt, encoding="utf-8")
    return txt


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    df = collect()
    print(write_snippet(df))
    for code, name in EXTRA_DAMS.items():
        g = df[df["facility_code"] == code]
        print(name, code, len(g), "tdqty 결측", int(g["tdqty"].isna().sum()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
