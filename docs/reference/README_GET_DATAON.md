# DataON 원자료 받기 — 댐유역 하천 일평균수위 (선택)

이 제출 패키지의 **기본 zip 2종에는 DataON 원값이 들어 있지 않다.** 노트북과 `make reproduce` 는 DataON 원자료 없이
`data/processed/level_cont_features_S1.parquet`(수위 피처 2열, DataON 가공물)로 수위 피처를 채워 제출본과 같은
`submission.csv` 를 만든다. 2026-10-23 확인 결과, 원자료가 있든 없든 `features_S1` 은 완전히 같고 `submission.csv` 는 바이트까지 같다.
DataON 원자료부터 다시 만들고 싶을 때만 아래를 따른다.

## 1. 자료

| 항목 | 내용 |
|---|---|
| 자료명 | 댐유역 하천 일평균수위 (국가참조표준) |
| DOI | 10.20925/KSRD.74670854.v5 (https://doi.org/10.20925/KSRD.74670854.v5), 제·개정 2025-12-16 |
| 저작자 | 생산 한국수자원공사 오재우·이영창·이재용 / 발행 국가참조표준센터 / DataON(KISTI) 등재 |
| 라이선스 | **CC BY-NC-SA**(저작자표시-비영리-동일조건변경허락). DataON 유래 데이터와 그 가공물은 같은 조건으로만 재배포할 수 있다(`LICENSE_DataON.txt`) |
| 받는 곳 | DataON 상세 페이지 https://dataon.kisti.re.kr/search/view.do?mode=view&svcId=683386b621f469db2f44fb1ff25fe4ca 의 첨부파일 '전체' 내려받기 |

## 2. 기대 파일 (2026-10-20 내려받은 파일 기준)

| 파일 | 크기(바이트) | sha256 |
|---|---|---|
| `첨부파일_전체_DSDETL221128-012-5-DATA.zip` (내려받은 묶음) | 12,800,685 | `b6eb3e4ccd00faec9258049ade546f748401a0bbb8f1ca88ab1a1a9a0eeb43b8` |
| └ `댐유역 하천 일평균수위_DOI_v5.zip` (묶음 안) | 12,797,449 | `d9671e74619ef426e733408aa85e391c369e89b2cdfbf74481443f8fb90bc296` |
| └─ `댐유역 하천 일평균수위(2010-2014).xlsx` | 1,960,735 | `d81fd623b72968ac58a4a4c9e4ff6278006e0c9627edcdccc8e21b195f229538` |
| └─ `댐유역 하천 일평균수위(2015-2019).xlsx` | 2,006,359 | `c118e9cce40e0073d7b1048769cb360db7ac21f3252738bfc5c7e223b40bfa10` |
| └─ `댐유역 하천 일평균수위(2020).xlsx` | 7,630,992 | `a8a3d48d975ab47440229b837fcedbd517329feb352780850c5c8a07f828fc5d` |
| └─ `댐유역 하천 일평균수위(2021).xlsx` | 758,786 | `e592a8847f6bc422b3b12a199dde2c83237db9209805fe12652c011601d69a99` |
| └─ `댐유역 하천 일평균수위(2022).xlsx` | 408,295 | `fa54a5479966468ec4b7be4187094bbf76ce513611db867f15478460414c5f8d` |
| └─ `댐유역 하천 일평균수위(2023).xlsx` | 691,189 | `b950010dad6c6f82ff8a350c817427e0133a44dc0c73d70fd60061a508f9013c` |
| └─ `댐유역 하천 일평균수위(2024).xlsx` | 690,999 | `357002fd956d1d4ee6a7e37a58ede267d438da3a98e1252e407af121e08fe58b` |

DataON 이 자료를 다시 올리면 묶음 이름·해시가 달라질 수 있다. 그때는 xlsx 7개의 해시를 비교한다.
같은 DataON 의 「대청댐 유역 수위 관측국 시간수위」(DSDETL221128-011-1)는 모델에 쓰지 않으므로 받지 않아도 된다.

## 3. 배치 위치

xlsx 7개를 `data/raw/dataon/` 아래에 둔다. 하위 폴더도 괜찮다(예: `data/raw/dataon/DSDETL221128-012-5/`).
파서는 `댐유역 하천 일평균수위*.xlsx` 를 하위 폴더까지 찾는다.

## 4. 원자료부터 다시 만들기

```bash
python -m algaecast.collect.dataon_level --end 2026-10-20   # xlsx 파싱 + WAMIS 일수위로 2025년~ 연장(인증키 불필요, 인터넷 필요)
python -m algaecast.align.run --strategy S1                  # 원자료가 있으면 연속 수위 편차(level_cont_anom)를 원자료로 계산
python -m algaecast.features.run --strategy S1               # 원자료가 있으면 가공 피처 파일 대신 원자료로 수위 피처 계산
python -m algaecast.models.predict --out submission_from_dataon.csv
```

- 첫 줄이 만드는 파일: `data/raw/dataon/dataon_level_daily_long.parquet`(926,051행, 관측소 187곳, 2010~2024)과
  `data/raw/dataon/level_continuous_long.parquet`(5지점 관측소 24곳의 연속 시계열 = DataON 2010~2024 + WAMIS 2025~, 기준면 오프셋 보정).
- 재현 범위: **DataON 부분은 그대로 재현된다**(2026-10-23 확인: 926,051행 완전 일치). WAMIS 연장분은 다시 받아 오므로 제출 스냅샷과 다를 수 있다.
  - 스냅샷은 2026-10-21 00:05 에 받아 2026-10-20 일평균이 잠정값이었다. 2026-10-23 에 다시 받으니 그날 값 22행이 달랐다.
  - 스냅샷은 보현산댐 관측소(2012607)에 `wamis_ok: false` 표시를 하기 전에 만들어져, 이 관측소의 2025년~ WAMIS 값 658행(오프셋 226.89 m)이 들어 있다. 지금 코드는 이 값을 넣지 않는다.
  - v2 까지는 정렬 단계의 관측소 평균이 연속 시계열 전 기간 평균이어서 위 차이가 수위 편차 피처 값을 옮겼다.
    2026-10-23 그 규칙(v2)으로 다시 받은 시계열을 돌린 결과: `level_cont_t0` 2,979행 모두 조금씩 달라졌다(최대 차 1.21).
    `level_cont_diff7` 는 117행(대부분 칠서), `submission.csv` 는 124행 중 26행(최대 상대차 14.7%)이 달라졌다.
  - 제출본 v2.1 은 관측소별 직전 365일 평균(기준일 미포함)을 쓴다. 그래서 2026-10-20 잠정값 차이는 표본 행(기준일 ≤2026-10-15)의
    피처에 들어가지 않고, 보현산댐 2025년~ 값은 코드가 뺀다. 다만 WAMIS 가 과거 값을 고치면 달라질 수 있으므로 제출본 재현에는 아래 파일을 쓴다.
- **제출본과 같은 결과가 필요하면** 기본 패키지의 가공 피처 파일을 쓴다. 운영사무국이 허용한 경우에는 DataON 원값이 든 대체 zip(`AlgaeCast_녹조7일예측_이재행_with_dataon.zip`)에 있는 연속 시계열 스냅샷을 쓴다.
  - 파일: `data/raw/dataon/level_continuous_long.parquet`, 144,068행
  - sha256: `c37195353178e9d30fc0d6873a57a27379dd16558ae8a4f7016ccd8eaf981830`
  - 이 스냅샷으로 돌려도 결과는 같다(2026-10-26 대체 zip 재현 검증: DataON 원값으로 수위 피처를 계산해도 `submission.csv` 바이트 동일).

## 5. 기본 패키지에 든 DataON 유래 파일 (CC BY-NC-SA, 같은 폴더에 `LICENSE_DataON.txt`)

- `data/processed/level_cont_features_S1.parquet`
  - 2,979행 × 4열(`station_id`, `base_date`, `level_cont_t0`, `level_cont_diff7`)
  - 학습·검증·평가 샘플마다 수위 편차와 7일 변화를 담았다(원값이 아니라 관측소별 직전 365일 평균을 뺀 가공값).
  - sha256 `86243a68758a473a2ca6fc9cd3915b30f05ccdf916df12b33fe3c3ab4bed89f0`(v2.1 피처, 2026-10-23 12:10 생성).
  - 원자료가 있는 환경에서 `python -m algaecast.features.run --strategy S1 --export-level-cont` 로 다시 만들 수 있다.
- `src/config/level_cont_stats.json`: 관측소별 기준면 오프셋(2020~2024 겹침 구간 DataON − WAMIS 중앙값)·관측소 목록·본댐 대체 표.
  대시보드 일일 운영 전용이고 재현에는 쓰지 않는다(전 기간 평균 값은 v2.1 에서 폐기).
