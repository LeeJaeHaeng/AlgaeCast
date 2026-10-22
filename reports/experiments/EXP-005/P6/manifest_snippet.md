# MANIFEST 조각 — P6 상류 댐 추가 수집(HY-06b)

| ID | 이름 | 기관 | 엔드포인트 | 기간 | 수집 일시 | 건수 | 라이선스 | 파일 | sha256 |
|---|---|---|---|---|---|---|---|---|---|
| HY-06b | 영천댐 일자료(WAMIS 2012210) | 환경부 한강홍수통제소 | wkd/mn_dtdata?damcd=2012210 | 2012-01-01~2025-12-31 | 2026-10-22 12:20 KST | 5,079 | 공공누리 1유형(WAMIS 개방 API) | data/raw/wamis_dam_extra/wamis_dam_extra_daily.parquet | (아래) |
| HY-06b | 운문댐 일자료(WAMIS 2021210) | 환경부 한강홍수통제소 | wkd/mn_dtdata?damcd=2021210 | 2012-01-01~2025-12-31 | 2026-10-22 12:20 KST | 5,114 | 공공누리 1유형(WAMIS 개방 API) | data/raw/wamis_dam_extra/wamis_dam_extra_daily.parquet | (아래) |

- `data/raw/wamis_dam_extra/wamis_dam_extra_daily.parquet` sha256 `33204755cab6ea7baa08e59395eefef83a1b7401b2e5d76dbdcf6d6eb321aea9`
- `data/raw/wamis_dam_extra/wamis_dam_extra_daily.csv` sha256 `a87e71bdb240ac79ceee61671e068b41c930088cbee8c73d99017407a24a8262`
- 변수: rwl 저수위(EL.m), iqty 유입량, tdqty 총방류량, edqty 발전, spdqty 여수로, otltdqty 기타 방류, itqty 취수량(㎥/s), rf 강우(mm). 2026 은 요청하지 않았다(END = 2025-12-31).
- 수집기: `src/algaecast/collect/wamis_extra_dams.py`(기존 `WamisDamDailyCollector` 재사용, 캐시 `data/raw/cache/`).
