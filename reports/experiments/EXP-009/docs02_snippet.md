# EXP-009(R6) docs/02_DATA_SPEC.md 조각 — 메인 세션이 WQ-06 행에 통합

기존 WQ-06 행(수질자동측정망, water.nier.go.kr, 시간 단위 수온·DO·pH·Chl-a)을 아래로 바꾸는 안.

| ID | 데이터 | 기관 | 출처·접근 | 주요 변수 | 주기 | 용도 |
|---|---|---|---|---|---|---|
| WQ-06 | 수질자동측정망 운영결과 DB | 국립환경과학원 | data.go.kr #15081073 `apis.data.go.kr/1480523/WaterQualityService/getRealTimeWaterQualityList` (`siteId`, `startDate`·`endDate` yyyyMMddHHmmss 둘 다 필수, 기간 (start, end]); 키 `NIER_WQDB_KEY`. 항목 코드는 활용가이드 zip 의 코드표(M69 수온3·M70 pH3·M71 EC3·M72 DO3·M29 Chl-a·M27 TN·M28 TP·M06 TOC1 …; 포털 출력결과 표는 구버전). 측정소 좌표: 물환경정보시스템 GIS 층 B001 | 일평균 수온·pH·DO·EC·TOC·탁도·Chl-a·TN·TP(측정소별 상이) | 일(확정, 월 단위 공개 — 약 1.5~2.5개월 지연). 시간·미확정 자료는 물환경정보시스템 실시간/물모아 `autoNetworkConfirmed/autoMeasureData` | EXP-009: 5지점 최근접 본류 측정소(해평 S02012·다산 S02009·칠서 S02007·상동 S02017·대청호 S03003) 7일 추세 피처 — 원단위 개선 효과 없음(미채택). 수온 정밀화 대체 피처 후보 |
