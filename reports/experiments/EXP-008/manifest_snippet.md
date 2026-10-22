# EXP-008 MANIFEST 조각(data/raw/MANIFEST.md 통합용)

| ID | 이름 | 기관 | 엔드포인트 | 기간 | 수집 일시 | 행 | 라이선스 | 경로 | sha256 |
|---|---|---|---|---|---|---|---|---|---|
| WQ-01b | 조류경보제 조회서비스 전 지점(82개, ptNoList 없음) | 기후에너지환경부 국립환경과학원 | apis.data.go.kr/1480523/nieragainstalgae/algaePreMeasure (wmyrList 연도별, numOfRows 10000) | 2012-01-03~2026-10-15 | 2026-10-21 18:01 KST | 51,714 | 공공누리 1유형 | data/raw/nier_algae_all/nier_algae_all_2012_2026.csv | 9eff872a0ef547adfb7bbe0cc77a2ad796e0214e4d8fead31fd4fce709250038 |
| MT-01b | 기상청 관측지점 정보(지점번호·위경도·이력) | 기상청 기상자료개방포털 | data.kma.go.kr/tmeta/stn/selectStnList.do (pgmNo=123) | 현행+이력 | 2026-10-21 18:03 KST | 14,928 | 공공누리 1유형 | data/raw/kma_stn_info/kma_stn_list.csv | 715170386aa3508114df6d6b496f023798a4ce012de36dee1ade0965343dcbdf |
| MT-01c | ASOS 일자료 — 다른 지점 최근접 관측소 27곳 | 기상청 | apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList | 2012-01-01~2025-12-31 | 2026-10-21 18:14 KST | 138,076 | 공공누리 1유형 | data/raw/kma_asos_all/kma_asos_all_daily_2012_2025.parquet | addccc0d6160ac217dc25803b8d709fda964080bda532f71fe7af2967dc2c320 |

- 보조 산출(같은 폴더): `sites_all.csv`(지점 목록·기간·측정 수), `token_report.csv`(알 수 없는 문자열 — 이번 수집 0건), `asos_stations.csv`(ASOS 대표 좌표 = 이력 중앙값).
- 수질측정망 GeoJSON(`data/raw/nier_wq/` zip)은 좌표 근사에만 읽었다(압축은 메모리에서만 해제).
