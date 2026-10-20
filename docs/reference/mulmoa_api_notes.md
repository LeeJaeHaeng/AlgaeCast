# 물모아(mulmoa.go.kr) 데이터 접근 메모 — 2026-10-20 조사

국가 통합물관리정보플랫폼 '물모아'(환경부·국립환경과학원, 2025-04 개통). 벤치마크 WQ-04 'AI 녹조 정밀 예측 정보'와
WQ-02 수질측정망 2026년분의 접근 경로. 원본 HTML/JS/JSON 샘플은 조사 당시 scratchpad 에 저장(저장소 미포함).

## 1. 공식 Open API (인증키 필요)

- 안내: `https://www.mulmoa.go.kr/web/contents/29`, 인증키 신청 `/web/openapi/apply?pMENU_NO=187`, 관리 `/web/openapi/manage?pMENU_NO=188`
- Base `https://mulmoa.go.kr/api/v1/…` GET, 인증은 **쿼리 파라미터 `apikey`**, `output=json|xml`
- 응답 `{"result":{"code":"00","msg":…},"count":N,"list":[…]}`; 오류 10 파라미터 / 22 한도 초과 / 30 미등록 키 / **31 사용 불가(승인 대기·비활성)** / 99 시스템
- 제한: 1일 3,000건, 관리자 승인 후 사용. 시자료 1개월·일자료 3개월·월자료 1년 범위 조회
- 2026-10-20 발급 키 상태: `bo/stationData?bsncd=20` 호출 → HTTP 401, resultCode **31 "사용할 수 없는 API Key"** = 승인 대기. 승인되면 아래 명령으로 재검증.

| 서비스 | 엔드포인트 | 파라미터(필수*) | 주요 필드 |
|---|---|---|---|
| 보 목록 / 실시간 | `bo/stationData`, `bo/boData` | apikey*, bsncd(20 낙동강) / obscd*, type*(1 시간, 2 일), start, end(YYYYMMDD) | A_VAL 상류수위, B_VAL 하류수위, C_VAL 저수량, E_VAL 저수율, F_VAL 유입량, G_VAL 총방류량 |
| 댐 목록 / 실시간 | `dam/stationData`, `dam/damData` | 동일 | A_VAL 수위, B_VAL 저수량, D_VAL 저수율, E_VAL 유입량, F_VAL 방류량 |
| 수위 / 강수 | `waterLevel/{stationList,stationData,realtimeData}`, `precipitation/{…}` | bsncd / obscd*, type*, start, end | WTLV_DATA_VAL, AMRF |
| 수질측정망 | `waterQualityNetwork/riverSites`, `waterQualityNetwork/riverData` | type*(1 하천, 2 호소), basin(R02 낙동강, R03 금강) / stationCodes*, pDateGu*(1 일, 2 월, 3 년), pSDate, pEDate(YYYYMM) | IEM_1060 수온, 1054 DO, 1052 BOD, 1055 T-N, 1056 T-P, 1073 TOC, **1063 Chl-a** … (56개). **카탈로그 최신일 2026-08-01 → WQ-02 2026년분 보강 경로** |
| 자동측정망 | `autoNetworkConfirmed/autoMeasureSites`, `autoMeasureData` | basin / stationCodes*, pDateGun*(1 시간, 2 일), pSDay*, pEDay*(YYYYMMDD) | M02 수온, M03 pH, M05 DO, M27 T-N, M28 T-P, **M29 Chl-a** (최신 2026-10-19) |

조류경보제·조류예측 전용 Open API 서비스는 **없음**(메뉴 23개 확인).

```
curl -sk "https://mulmoa.go.kr/api/v1/bo/stationData?apikey=$MULMOA_API_KEY&bsncd=20&output=json"
curl -sk "https://mulmoa.go.kr/api/v1/waterQualityNetwork/riverData?apikey=$MULMOA_API_KEY&type=1&stationCodes=2011A20&pDateGu=2&pSDate=202601&pEDate=202608&output=json"
```

## 2. AI 녹조 정밀 예측 정보 (WQ-04 벤치마크) — 웹 내부 JSON, 인증 불필요

- 화면 `/web/algaeMap`(녹조지도), 데이터검색 `/web/totalSearch?bTopDataCode=1&bDataCode=16` (data_code 16, pDataGubun 58)
- 발표: 5~10월 월·목, 발표일 D+1~D+7 **단계** 예측(상수원 0단계 <1,000 / 1단계 1,000~10,000 / 2단계 10,000~100,000 / 3단계 100,000~1,000,000 / 4단계 ≥1,000,000 cells/mL). 관측 10,000 초과 시 매 근무일 추가 발표. **세포수 수치 예측은 제공하지 않는다.**
- 대상: 상수원 13 + 친수 5. 우리 5지점(2011G26, 2011G56, 2020G33, 2022G05, 3008G30) 모두 포함.
- **이력은 지점당 최근 3회분만 반환**(pSDate 를 바꿔도 무시) → `scripts/snapshot_mulmoa_forecast.py` 로 월·목(+매일) 스냅샷을 쌓아야 한다.

```
# A. 지점코드 지정, 최신 발표 7일 단계
curl -sk -A "Mozilla/5.0" -H "X-Requested-With: XMLHttpRequest" \
  --data-urlencode 'ATTR_1S=["2011G26","2011G56","2020G33","2022G05","3008G30"]' \
  https://www.mulmoa.go.kr/web/totalSearch/water/algaeMap/beforBlalMapDataCall
# → {"list":[{"SWMN_DTL_NM":"해평","SUMMARY_D2":"1단계",…,"SUMMARY_D8":"1단계","PRSNTN_NOW_YMD":"20261019"},…]}

# B. 전 지점 최근 3회 발표 + 최근 관측치(OLD_D 세포수, OLD_D_AG_ISSUE 경보)
curl -sk -A "Mozilla/5.0" -H "X-Requested-With: XMLHttpRequest" \
  -d 'data_code=16&tbmn_sn=19&pDataGubun=58&pLgubun=02' --data-urlencode 'ATTR_1S=["1","2","3","4"]' \
  -d 'pSDate=20261019&excel=N' https://www.mulmoa.go.kr/web/totalSearch/water/algaeBeforInfo/mesureDataCall
```

## 3. 조류경보제 측정자료(2026 포함) — 웹 JSON, 인증 불필요

- data_code 57, pDataGubun 169(상수원) / 170(친수) / 171(관찰) / 536 / 585. `pDateGun` 1 일·2 월(YYYYMM)·3 년(YYYY). STATION_CODES 최대 5개.
- 필드: IEM_1060 수온, 1039 pH, 1054 DO, 1062 투명도, 1045 탁도, 1063 Chl-a, **1166 유해남조류 세포수**, 1168 Microcystis, 1169 Anabaena, 1170 Oscillatoria, 1171 Aphanizomenon, 1087 지오스민, 1088 2-MIB, TOTAL_MICROS, 1091 MC-LR, 2295~2299 MC 변종
- 검증: 해평 2026-05~10 요청 → 29행. data.go.kr 조류경보제 API(WQ-01)와 같은 내용이며 교차검증용.

```
curl -sk -A "Mozilla/5.0" -H "X-Requested-With: XMLHttpRequest" \
  -d 'data_code=57&tbmn_sn=17&pDataGubun=169&pLgubun=02&pDateGun=1&pSDay=202605&pEDay=202610&excel=N' \
  --data-urlencode 'ATTR_1S=["2"]' --data-urlencode 'STATION_CODES=["2011G26"]' \
  https://www.mulmoa.go.kr/web/totalSearch/water/algaePreMeasure/mesureDataCall
```
- 보조: `POST /web/totalSearch/water/algaeMap/preMeasureMapDataCall`(지점별 최근 5회), `POST …/algaeMap/mapStatusCall`(62지점 현재 ISSUE_LVL A/B/C/D)

## 4. 주의

- 웹 XHR 은 비공식 내부 엔드포인트(POST form, `X-Requested-With` 헤더). 스키마 변경 가능 → 수집기에서 응답 키 검증 필수.
- 자료 재배포는 사이트 저작권 정책(`/web/contents/76`) 확인. 벤치마크 비교표에는 출처·발표일을 명기.
- 문의: 032-560-7494 / 070-4876-4226 (Open API), 국립환경과학원 한강통합물환경센터 032-560-7414 (조류예측).
