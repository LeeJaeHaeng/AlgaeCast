# MANIFEST 추가 행(EXP-007, 메인 세션이 data/raw/MANIFEST.md 에 통합)

| id | 데이터명 | 기관 | 엔드포인트/URL | 기간 | 수집일시 | 행수 | 라이선스 | sha256 |
|----|---------|------|---------------|------|---------|------|---------|--------|
| WQ-02b | 물환경 수질측정망 운영결과 DB — 5지점 후보 측정소 13곳(본류: 2009A30 선산·2011A10 강정·2011A20 구미·2011A40 성주·2011A55 다사·2011A60 달성·2020A10 남지·2020A32 함안·2020A60 삼랑진2·2022A10 물금·3008B10 대청댐4·3008B20 대청댐6·3008B30 대청댐5(대청호)), 17항목(TN·TP·NO3-N·NH3-N·PO4-P·DTN·DTP·Chl-a·DO·EC·SS·수온·pH·BOD·COD·TOC·유량), 호소는 수심별 행 포함 (`data/raw/nier_wqdb/wq_measuring_2012_2026.parquet/.csv`, 측정소표 `wq_measuring_stations.csv`) | 기후에너지환경부 국립환경과학원 | apis.data.go.kr/1480523/WaterQualityService/getWaterMeasuringList (ptNoList=13곳 콤마, wmyrList 연 단위, numOfRows=5000, resultType=json, 2012~2026 15요청; 키 `.env` NIER_WQDB_KEY) | 2012-01-03~2026-08-27 | 2026-10-21 17:58 KST | 8,350 | 이용허락범위 제한 없음(data.go.kr 활용신청 표기) | a8a02b1f1b1f4815 |

- sha256 전체: `a8a02b1f1b1f48151d962423ab09a1b55fee697134586e81876502e2781b9cb3`
- 측정일(WMCYMD) 없는 응답 3행(대청댐4·6)은 시점을 알 수 없어 제외.
- 2026-10-21 수집 시점 최신 측정일 2026-08-27(공개 지연 약 55일).
