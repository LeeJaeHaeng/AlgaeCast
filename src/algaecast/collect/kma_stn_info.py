"""EXP-008(R5) 기상청 관측지점 정보(지점번호·지점명·위도·경도·해발고도) 수집기.

- 출처: 기상자료개방포털 '지상 관측지점 정보' 목록 ``data.kma.go.kr/tmeta/stn/selectStnList.do``
  (pgmNo=123, 인증 불필요, GET). 한 번에 전 지점·이전 이력(위치 변경 행)을 받는다.
- 이 실험에서는 ASOS(종관) 지점번호 90~299 만 쓴다. 이전 이력이 여러 행이면 위·경도 중앙값을 대표 좌표로 둔다
  (목록에 시작·종료일 열이 없어 시점별 좌표를 고를 수 없음 — 이전 거리는 대개 수 km 이내).
- 출력: ``data/raw/kma_stn_info/kma_stn_list.csv``(+parquet, 전 행), ``asos_stations.csv``(대표 좌표).

사용: python -m algaecast.collect.kma_stn_info
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date

import pandas as pd

from algaecast.collect.base import BaseCollector, CollectError

log = logging.getLogger(__name__)
URL = "https://data.kma.go.kr/tmeta/stn/selectStnList.do"
PARAMS = {"pgmNo": "123", "pageIndex": "1", "schListCnt": "20000", "serviceSe": "F00101"}
ASOS_RANGE = (90, 299)


def parse_station_html(html: str) -> pd.DataFrame:
    """목록 HTML → (stn_id, stn_nm, lat, lon, alt). 주석 처리된 열은 제거한다."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    cap = html.find("조회 자료 결과")
    s0 = html.find("<tbody>", cap if cap >= 0 else 0)
    s1 = html.find("</tbody>", s0)
    if s0 < 0 or s1 < 0:
        raise CollectError("기상청 지점정보 표를 찾지 못함")
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html[s0:s1], flags=re.S):
        tds = [re.sub(r"<[^>]+>", "", t).strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
        if len(tds) >= 5 and tds[0].isdigit():
            rows.append(tds[:5])
    df = pd.DataFrame(rows, columns=["stn_id", "stn_nm", "lat", "lon", "alt"])
    df["stn_id"] = df["stn_id"].astype(int)
    for c in ("lat", "lon", "alt"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def asos_representative(df: pd.DataFrame) -> pd.DataFrame:
    """ASOS 지점(90~299, 남한 위도 < 38.7)의 대표 좌표(이력 중앙값)와 이력 행 수·최대 이동거리 근사."""
    a = df[df["stn_id"].between(*ASOS_RANGE) & (df["lat"] < 38.7)]
    g = a.groupby("stn_id")
    out = pd.DataFrame(
        {
            "stn_nm": g["stn_nm"].last(),
            "lat": g["lat"].median(),
            "lon": g["lon"].median(),
            "n_hist": g.size(),
            "lat_range": g["lat"].max() - g["lat"].min(),
            "lon_range": g["lon"].max() - g["lon"].min(),
        }
    )
    return out.reset_index()


class KmaStnInfoCollector(BaseCollector):
    source = "kma_stn_info"
    key_env = None
    timeout = 180

    def is_cacheable(self, text: str) -> bool:
        return "조회 자료 결과" in text and "<tbody>" in text

    def fetch_all(self) -> pd.DataFrame:
        res = self.get(URL, dict(PARAMS), ttl=None)
        return parse_station_html(res.text)

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        df = self.fetch_all()
        return df[df["stn_id"] == int(site_code)]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    col = KmaStnInfoCollector()
    df = col.fetch_all()
    pq, csv = col.save(df, "kma_stn_list")
    rep = asos_representative(df)
    rep.to_csv(col.out_dir / "asos_stations.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    print(f"지점정보 {len(df):,}행, 지점 {df['stn_id'].nunique()}개, ASOS 대표좌표 {len(rep)}개 → {pq.name}")
    print(
        col.manifest_row(
            id_="MT-01b",
            name="기상청 관측지점 정보(지점번호·위경도, kma_stn_list)",
            org="기상청 기상자료개방포털",
            endpoint="data.kma.go.kr/tmeta/stn/selectStnList.do (pgmNo=123)",
            period="현행+이력",
            rows=len(df),
            license_="공공누리 1유형(출처표시)",
            path=csv,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
