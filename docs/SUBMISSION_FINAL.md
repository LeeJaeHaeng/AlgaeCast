# 제출 후보 기록 — `submission-candidate-final`

- 작성: 2026-10-27(패키지 빌드 2026-10-26 23:5x KST).
- 이 문서를 담은 커밋에 git 태그 `submission-candidate-final` 을 단다.
- 패키지는 이 태그 커밋과 같은 작업 트리로 빌드했다. 빌드 뒤에 더한 것은 세 가지뿐이다.
  - `reports/eval/package_verify.*` 검증 기록
  - 이 문서
  - `docs/handoff/` 보고서·캡처 — 패키지에는 넣지 않는다.
- **저장소 밖 보관본: `C:\Users\user\OneDrive\Desktop\경진대회\제출본\`**
  - zip 3종과 `SHA256SUMS.txt` 가 들어 있다. `sha256sum -c` 로 대조했다.
  - 저장소에서 다시 빌드해도 이 사본은 건드리지 않는다. 제출에는 이 사본을 쓴다.
- 이전 후보 `submission-candidate-1026`(zip 기본 `d6a0f33e…`)과 비교한 변경 사항:
  - 다시 보기 문구(README §0·방법설명서)
  - T24 공식 분할 기록
  - DataON 문장
  - `docs/handoff/` 제외
  - `submission.csv`·모델은 같다.

## zip 3종

| 파일 | 크기 | sha256 | 용도 |
|---|---|---|---|
| `AlgaeCast_녹조7일예측_이재행.zip` | 62,924,210 B (62.9 MB) | `28dc846c830990902f1dbe6975a820d0c731b36d8b1035653f35bde5b74e4f31` | 기본 제출 zip(영상 포함, DataON·WAMIS 원값 없음) |
| `AlgaeCast_녹조7일예측_이재행_영상제외.zip` | 40,296,645 B (40.3 MB) | `0895e12328e7b924b0da104b03a38e6fca5674947b6f4ff9f0ce678d4c2af7f9` | 용량 제한 대비(영상 제외) |
| `AlgaeCast_녹조7일예측_이재행_with_dataon.zip` | 63,767,344 B (63.8 MB) | `97197dea3ec16f7301658093493a9bcf2154a02c3826c97c18f699e51f5cb36a` | DataON 원값 포함 대체본 — 운영사무국이 허용할 때만 |

## 제출 모델 v2.1

- 동결 커밋 `217260e`(2026-10-23 12:08:19 KST), 동결 문서 `models/FROZEN_v2.1.md`.
- 아래 3개 버전은 레지스트리 current 와 같고, 패키지 `model/` 에는 이 3개 폴더만 있다.

| 이름 | 버전 | sha256(model.pkl) |
|---|---|---|
| regression | 20261023_120818 | `d95e7a4e8dab50a59583dd8ecf8ab2482786ec05f7bfa1f256c657bec3a091f0` |
| classifier | 20261023_120255 | `cce848b6c1b5d1608d73403d5ef089bf8e4dc04bdc358eea8afd7fcb3ae1c77d` |
| quantile | 20261023_120257 | `9b52945aa53e2af2a0189eb8368389410eabd001a6336620684baaca07258bee` |

- `submission.csv`(124행) sha256: `4741a3d37ef3ae9f71b381e083028d93e83ec378ae5d5a65beba2ed48545a8e7`.

## 재현 결과(2026-10-26~27)

| 검증 | 결과 |
|---|---|
| 새 venv 재현 — 패키지 폴더(23:51) | `submission.csv` 바이트 동일(diff 0), 노트북 오류 0, 7.1분 |
| 새 venv 재현 — 기본 zip | diff 0, 노트북 오류 0, 7.2분 |
| 새 venv 재현 — with_dataon zip | diff 0, 노트북 오류 0, 수위 피처 raw, 7.0분 |
| 오프라인 재현(최종 기본 zip `28dc846c…`) | 네트워크를 막은 상태(감사 훅)에서 노트북·predict 모두 rc 0, sha256 `4741a3d3…` 같음, 외부 접속 시도 0건 |
| pytest(전체) | 533 통과 |
| 화면 숫자 대조(check_numbers) | 178/178 |
| 배포본 숫자(check_deployed_numbers, 0224285 배포본) | 63/63 |
| 다시 보기 미래 관측 누수(check_asof, 프로덕션) | 54쪽 실패 0 |
| 쉽게 보기 금지어(기본 10 + 다시 보기 7 URL, 프로덕션) | 0건 |
| 패키지 민감정보 검사 | 0건 |
| 방법설명서 PDF | 1쪽 = 심사위원용 요약 |

## 다시 빌드할 때 주의

- 패키지를 다시 빌드하면 zip sha256 이 달라진다. `submission.csv` 는 같다. 이유는 두 가지다.
  - README 에 생성일(`date.today()`)이 들어간다.
  - 일일 자동 커밋이 패키지에 복사되는 파일을 갱신한다.
- 일일 자동 커밋(GitHub Actions)이 커밋하는 경로:
  - `daily.yml`: `reports/eval/live_benchmark.csv`
  - `mulmoa_snapshot.yml`: `data/raw/mulmoa/*.csv`, `data/raw/kma_forecast/*.csv`, `reports/eval/live_benchmark.csv`
- 이 중 패키지에 들어가는 것:
  - `data/raw/kma_forecast/`(폴더째 복사)
  - `reports/eval/live_benchmark.csv`(`figures/reports/eval/` 로 복사)
  - `data/raw/mulmoa/` 는 들어가지 않는다.
- `models/`·`submission/`·`config/`·`src/` 는 일일 자동 커밋이 건드리지 않는다.
- 이미 만든 zip(`dist/`, git 추적 밖)과 `제출본` 보관본은 일일 커밋의 영향을 받지 않는다.

## 이전 후보

- `submission-candidate-1026`(커밋 45a4ef1)의 zip sha256 은 다음과 같다(`dist/` 에서는 이미 덮어써짐).
  - 기본 `d6a0f33e…`
  - 영상제외 `1da213c9…`
  - with_dataon `9a2e7510…`
