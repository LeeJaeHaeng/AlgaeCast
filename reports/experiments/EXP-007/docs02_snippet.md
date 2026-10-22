# docs/02_DATA_SPEC.md WQ-02 보강안(EXP-007, 메인 세션이 통합)

WQ-02 행 '수집 경로' 칸에 다음을 덧붙인다.

> **API 경로 확보(2026-10-21, EXP-007)**: 국립환경과학원 수질 DB OpenAPI `https://apis.data.go.kr/1480523/WaterQualityService/getWaterMeasuringList`(물환경 수질측정망 운영결과 DB, data.go.kr 개발계정 자동승인, 일 10,000건). 인자 `ptNoList`(측정소 코드 콤마 다중)·`wmyrList`(연)·`wmodList`(월, 생략 시 전체)·`pageNo`·`numOfRows`(5,000 확인)·`resultType=json`. 응답: `PT_NO`·`PT_NM`·`ADDR`·`ORG_NM`·`WMYR`·`WMOD`·`WMWK`(회차)·`WMCYMD`(측정일 YYYY.MM.DD)·`WMDEP`(수심, 호소만)·경위도 도분초(`LAT_DGR/MIN/SEC`, `LON_*`)·`ITEM_*`(앞뒤 공백 문자열, '정량한계미만' 토큰). `ITEM_DOC` 는 용존산소(DO), `ITEM_DTN`/`ITEM_DTP` 는 용존 총질소/총인, `ITEM_POP` 는 인산염인(PO4-P), `ITEM_CLOA` 는 Chl-a. 측정 빈도: 낙동강 본류 주 1회(구미 강정 2011A10 은 2015~ 연 37~40회, 2012~2014 월 1회), 대청호 월 1회(수심 3층 내외). **2026년분 제공(2026-08-27 까지, 공개 지연 약 2개월)** → GeoJSON 파일데이터(2025-12 까지)의 2026 공백을 메운다. 키 `.env` `NIER_WQDB_KEY`, 주소 `API_NIER_WQDB`. 수집기 `collect/nier_wq_measuring.py`, 원자료 `data/raw/nier_wqdb/`.

대표 측정소(피처용, sites.yaml `wq_station`): 해평 2011A10 강정(숭선교) · 강정고령 2011A55 다사(강정고령보 상류 500 m) · 칠서 2020A10 남지(남지교) · 물금매리 2022A10 물금(물금취수장) · 회남 3008B30 대청댐5(회남교, 표층).

피처 사용 규칙: obs_date ≤ base_date(공개 지연 반영 시 base_date − 30/60일) 측정만, 항목별 최근값·4주 평균·N/P 비·경과일(EXP-007 README).
