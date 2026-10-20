# data/raw MANIFEST — 외부 데이터 출처·라이선스·수집 기록 (docs/02_DATA_SPEC.md 10절 양식)

원본 파일은 git 에 커밋하지 않는다. 이 문서만 커밋한다. 해시는 sha256 앞 16자리.

| id | 데이터명 | 기관 | 엔드포인트/URL | 기간 | 수집일시 | 행수 | 라이선스 | sha256 |
|----|---------|------|---------------|------|---------|------|---------|--------|
| COMP-sample | 04_sample_data_public.xlsx (대회 공개 샘플, 시트 ①~⑦) | KISTI / K-water | 대회 문제 상세 페이지 | 2026-07~08 샘플 | 2026-10-20 | ①93 ②64 ③64 ④63 ⑤80 ⑥80 ⑦9 | 대회 규정(폐기·제3자 제공 금지) | 7bb9fc52f28c4625 |
| COMP-bundle | datas_participants.zip (수질·수문·기상 CSV, 지점정보, 예측대상, 제출예시, README) | KISTI / K-water | 대회 문제 상세 페이지(로그인) | - | **미수령** (T0-b 전 다운로드 필요) | - | 대회 규정 | - |
| HY-05 | 댐유역 하천 일평균수위 (국가참조표준, DOI v5; 연도별 xlsx 7개, 186개 관측소) | K-water (DataON 등재) | https://dataon.kisti.re.kr/search/view.do?mode=view&svcId=683386b621f469db2f44fb1ff25fe4ca (DOI 10.20925/KSRD.74670854.v5, 2025-12-16 개정) | 2010-01-01~2024-12-31 | 2026-10-20 12:15 KST | 연 365~366행 x 186열 (2024 는 표준편차 시트 포함) | CC BY-NC-SA (DataON 표기; 국가참조표준센터/K-water 오재우·이영창·이재용) — 비영리 조건 확인됨, 방법설명서에 출처·라이선스 명기 | b6eb3e4ccd00faec |
| HY-05b | 대청댐 유역 수위 관측국 시간수위 (DOI v1; 대청댐·조정지댐·송천·수통·옥천·유구·청성·호탄) | K-water (DataON 등재) | https://dataon.kisti.re.kr/search/f47de0aae74f029bbb26094a4b44e26c (DOI 10.20925/KSRD.18381495.v1, 번들 DSDETL221128-011-1) | 2012-10-01 01시~ (시간 단위) | 2026-10-20 12:15 KST | 6,612 | CC BY-NC-SA (DataON 표기; 국가참조표준센터/K-water 정구열, 2013-12-19 제정) | 3108457ad652109f |

## API 인증키 점검 (2026-10-20, 개발계정, 활용기간 2026-10-20 ~ 2028-10-20)
키는 `.env` 의 `DATA_GO_KR_KEY` 에만 보관한다. 재점검: `python scripts/check_api_keys.py`

| 서비스 | 엔드포인트 | 필수 파라미터 | 일일 트래픽 | 결과 |
|---|---|---|---|---|
| 기상청 ASOS 일자료 (MT-01, #15059093) | `/1360000/AsosDalyInfoService/getWthrDataList` | dataCd=ASOS, dateCd=DAY, startDt/endDt(YYYYMMDD), stnIds, dataType=JSON | 10,000 | 00 NORMAL_SERVICE. 대전(133) 2026-10-01~10 일자료 수신, 60여 필드(avgTa, sumRn, avgWs, avgRhm, sumSsHr, sumGsr, avgTs ...) |
| 기상청 ASOS 시간자료 | `/1360000/AsosHourlyInfoService/getWthrDataList` | dataCd=ASOS, dateCd=HR, startDt/startHh/endDt/endHh, stnIds | 10,000 | 00 NORMAL_SERVICE. 시간별 ta, rn, ws, hm, ss, icsr, ts 등 |
| K-water 다목적댐 운영 정보 (HY-01 보조, #15099049) | `/B500001/dam/multipurPoseDam/multipurPoseDamlist` | vdate(선택일), tdate(전일), ldate(전년 동일), vtime=07, _type=json. **4개 모두 필수**, 없으면 totalCount 0 | **100** | 00 NORMAL SERVICE. 21개 댐 일 스냅샷(suge, damnm, prcptqy, inflowqy, totdcwtrqy, totdcwtrqyjo, nowlowlevel, nowrsvwtqy, rsvwtrt ...). 댐코드 없음(댐명으로 매핑) |
| 국립환경과학원 조류경보제 (WQ-01, #15126738) | `/1480523/nieragainstalgae/algaePreMeasure` | pageNo, numOfRows (XML 전용) | 10,000 | 00 NORMAL SERVICE. totalCount 60,838. 필드: swmnCode, swmnNm, swmnDetailNm, chckDe, iemWtrtp, iemPh, iemDoc, iemTrp, iemTur, iemChla, iemBgalageCellCo, iemBgalageMicrosts/Anba/Osrtria/Apzo, iemGeosm, iemMib2, iemMicrostlr (전부 문자열, 경보단계·우점종 필드 없음) |
