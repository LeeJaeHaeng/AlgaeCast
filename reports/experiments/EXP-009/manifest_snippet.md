# EXP-009(R6) MANIFEST 조각 — 메인 세션이 data/raw/MANIFEST.md 에 통합

| id | 데이터명 | 기관 | 엔드포인트/URL | 기간 | 수집일시 | 행수 | 라이선스 | sha256 |
|----|---------|------|---------------|------|---------|------|---------|--------|
| WQ-06 | 수질자동측정망 운영결과 DB(일평균) — 자동측정소 15곳(주 5: 해평 S02012·다산 S02009·칠서 S02007·상동 S02017·대청호 S03003, 차순위 5: 도개 S02021·왜관 S02003·청암 S02006·창암 S02008·장계 S03007, 참고 5: 감천 S02030·남강 S02024·양산 S02056·강창 S02004·현도 S03009), M01~M100 원값 + 통합 변수(wtemp·ph·do·ec·toc·turb·tn·tp·chla·po4p·nh3n·no3n) (`collect/nier_autowq.py` → `data/raw/nier_autowq/autowq_daily.parquet/.csv`) | 기후에너지환경부 국립환경과학원 | apis.data.go.kr/1480523/WaterQualityService/getRealTimeWaterQualityList (siteId, startDate·endDate=yyyyMMddHHmmss 연 단위 (Y−1)1231000000~Y1231000000, numOfRows 500, resultType=JSON; 227요청, 키 NIER_WQDB_KEY) | 2012-01-01~2026-08-31 (일; 월 단위 확정 공개, 2026-10-21 기준 최신 2026-08-31) | 2026-10-21 18:03 KST | 73,476 | 이용허락범위 제한 없음(data.go.kr #15081073) | 429bd018869c0aa8 |
| WQ-06 메타 | 수질자동측정소 목록 77곳 — 코드·이름·수계·설치연도·주소·위치 설명·측정항목 + WGS84 좌표 (`data/raw/nier_autowq/stations.csv`) | 국립환경과학원 물환경정보시스템 | 목록: https://water.nier.go.kr/web/autoMeasure/confirm/toastList?ATTR_1=2&querySn=65 (키 불필요) / 좌표: http://211.114.21.35:8080/arcgis/rest/services/reach_V3/MapServer/96/query (물환경정보시스템 GIS, 층 B001 '수질자동측정망') | 2026-10-21 현행 | 2026-10-21 18:03 KST | 77 | 물환경정보시스템 이용약관(공공 정보) | f6013dd7cc624c5e |

비고
- 항목 코드 의미는 data.go.kr 포털 '출력결과' 표(구버전: m69=납 등)가 아니라 활용가이드 zip(`국립환경과학원_openAPI_활용가이드_수질DB.zip`, 2022-10-07)의 '물환경 수질자동측정망(실시간) 운영결과 DB_물 환경_코드_코드명.xlsx' 를 따른다(M69 수온3, M70 pH3, M71 EC3, M72 DO3, M73 탁도3, M27 TN, M28 TP, M29 Chl-a, M06 TOC1 …). 조류경보제 측정값과 대조: 수온 r = 0.997~0.999(낙동강 4곳)·0.90(대청호), Chl-a r = 0.64~0.74.
- 2026 행(2026-01-01~08-31)은 원자료에 들어 있으나 EXP-009 는 읽는 즉시 버린다(지표·그림 미사용).
- 조류경보 5지점 좌표(거리 계산용)는 같은 GIS 서비스 층 I002 '상수원구간'에서 조회(EXP-009 sites_snippet.yaml).
- 물모아 Open API(`MULMOA_API_KEY`)는 2026-10-21 시험에서 `autoNetworkConfirmed/autoMeasureSites` 가 User-Agent 헤더를 붙이면 정상(code 00) 응답 — MANIFEST 의 '키 승인 대기' 표기는 갱신 필요(이 실험은 사용하지 않음).
