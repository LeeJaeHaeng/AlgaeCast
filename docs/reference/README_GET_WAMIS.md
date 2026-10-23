# WAMIS 원값 받기 — 국가수자원관리종합정보시스템 댐·보 일자료·수위 (선택)

이 제출 패키지의 **기본 zip 2종에는 WAMIS 원값을 넣지 않았다.** 빠진 파일은 다음과 같다.
- `data/raw/wamis_dam/wamis_dam_daily.parquet`
- `data/raw/hydro/hydro_daily_long.parquet` 의 `wamis_mn_dtdata`·`wamis_wl_dtdata` 행

노트북과 `make reproduce` 는 WAMIS 원자료 없이 수문 피처 33열을 `data/processed/wamis_hydro_features_S1.parquet`(가공물)로 채운다. 그래서 제출본과 같은 `submission.csv` 를 만든다.

## 1. 원값을 빼는 이유

- 수집은 WAMIS 개방 API(`www.wamis.go.kr:8080/wamis/openapi`)의 인증키 없는 엔드포인트로 했다.
  - 쓴 엔드포인트: `wkd/mn_dtdata` 댐·보 일자료, `wkw/wl_dtdata` 수위관측소 일수위
  - 회원 가입·활용 신청을 하지 않았다.
  - 저장소의 `WAMIS_KEY` 는 실제로는 한강홍수통제소 OpenAPI 키이며 수집 코드에서 쓰지 않았다.
- WAMIS OPEN API 포털 회원약관 제15조④는 "회원은 서비스를 이용하여 얻는 정보를 사전 승낙 없이 복제·제공할 수 없다"고 정한다.
  - 이 조항이 회원이 아닌 이용자에게도 적용되는지는 약관만으로 분명하지 않다.
  - 그래서 원값은 다시 배포하지 않고 가공 피처만 넣는다.

## 2. 같은 값을 받는 공식 경로와 라이선스

| 경로 | 라이선스 | 비고 |
|---|---|---|
| 공공데이터포털 #3068550 「기후에너지환경부 한강홍수통제소_수자원 정보」 | 이용허락범위 제한 없음 | WAMIS 수위·댐 일자료 등록분(제공 URL wamis.go.kr/wkw/wl_dubwlobs.do) |
| 공공데이터포털 #3040409 「한강홍수통제소_표준수문DB」 | 이용허락범위 제한 없음. 오픈 API 이용약관 제10조 "저작자 및 출처 표시 조건으로 자유이용" | 한강홍수통제소 OpenAPI(api.hrfco.go.kr). 인증키가 필요하다 |
| 공공데이터포털 #15099110 「K-water 수문 운영 정보」 | 이용허락범위 제한 없음 | 보·댐 유입·방류·수위(이미 기본 패키지에 포함) |

- 표본 대조 결과(2026-10-23): 유입·방류는 일치했고, 수위는 반올림 차 0.005 m 이하였다.
- 출처 표시: 한강홍수통제소 국가수자원관리종합정보시스템(WAMIS).

## 3. 기본 패키지에 남긴 수문 자료

- K-water delist(#15099110, 이용허락범위 제한 없음)
- K-water 다목적댐 운영 정보(#15099049, 이용허락범위 제한 없음)
- 대회 번들 `dam_daily`(출처 표기 `bundle_wamis`, 대회 제공 자료 — 심사용)

## 4. 원자료부터 다시 만들기

```bash
python -m algaecast.collect.kwater_dam --start 2012-01-01 --end 2026-10-20
python -m algaecast.align.run --strategy S1
python -m algaecast.features.run --strategy S1      # WAMIS 원자료가 있으면 가공 파일 대신 원자료로 수문 피처 계산
python -m algaecast.models.predict --out submission_from_wamis.csv
```

- 첫 줄의 수집 조건: WAMIS 개방 API 는 키가 필요 없다. K-water delist 는 `.env` 의 `DATA_GO_KR_KEY` 가 필요하다.
- 첫 줄이 만드는 파일:
  - `data/raw/wamis_dam/wamis_dam_daily.parquet`
  - `data/raw/hydro/hydro_daily_long.parquet`(K-water·번들 행 포함 전체)
- 제출 스냅샷의 sha256(2026-10-20 수집):

  | 파일 | sha256 |
  |---|---|
  | `wamis_dam_daily.parquet` | `1044c8256afe7de8e191ae1d4e0fd3a8fbf4e98ae0c2dee6e244599aef5fd2a2` |
  | `hydro_daily_long.parquet`(전체) | `9f6edb82b14d2f00fde259232127da569100e4fa5618c97c21ee7a1e07caf085` |

- 다시 받으면 최근 값(잠정값)이 바뀌어 결과가 조금 달라질 수 있다. 제출본과 같은 결과가 필요하면 기본 패키지의 가공 피처 파일을 쓴다.
- 가공 파일은 원자료가 있는 환경에서 다시 만들 수 있다: `python -m algaecast.features.run --strategy S1 --export-wamis`
