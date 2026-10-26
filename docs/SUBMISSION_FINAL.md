# 제출 후보 기록 — `submission-candidate-1026`

- 작성: 2026-10-26.
- 이 문서를 담은 커밋에 git 태그 `submission-candidate-1026` 을 단다.
- 패키지 빌드 기준 커밋: `56bd47bb2c0b0f5ceb966633972db7a63bf5731c`(코드·데이터·문서·대시보드).
  - 태그 커밋은 여기에 세 가지만 더한다: 방법설명서 9절 검증 시각과 PDF, `reports/eval/package_verify.*` 검증 기록, 이 문서와 보고서.
- zip 은 `dist/` 에 있다(git 추적 밖). 제출할 때는 아래 sha256 과 같은 파일을 쓴다.

## zip 3종

| 파일 | 크기 | sha256 | 용도 |
|---|---|---|---|
| `AlgaeCast_녹조7일예측_이재행.zip` | 62,923,648 B (62.9 MB) | `d6a0f33ee8dfc221bd4e0e98caeb92541757f80eaca72e594464fbefc23ba31c` | 기본 제출 zip(영상 포함, DataON·WAMIS 원값 없음) |
| `AlgaeCast_녹조7일예측_이재행_영상제외.zip` | 40,296,083 B (40.3 MB) | `1da213c9935cbf99b4295f5a06cffedf98fc354eaf0265aba0fd5a4bfcdbb80a` | 용량 제한 대비(영상 제외) |
| `AlgaeCast_녹조7일예측_이재행_with_dataon.zip` | 63,766,782 B (63.8 MB) | `9a2e751089053a0cbe117a70a023cd968c261838c273ee0a693222bf45509d42` | DataON 원값 포함 대체본 — 운영사무국이 허용할 때만 |

## 제출 모델 v2.1

- 동결 커밋: `217260e`(2026-10-23 12:08:19 KST).
- 동결 문서: `models/FROZEN_v2.1.md`.
- 레지스트리 current 와 같다. 패키지 `model/` 에는 이 3개 폴더만 들어 있다.

| 이름 | 버전 | sha256(model.pkl) |
|---|---|---|
| regression | 20261023_120818 | `d95e7a4e8dab50a59583dd8ecf8ab2482786ec05f7bfa1f256c657bec3a091f0` |
| classifier | 20261023_120255 | `cce848b6c1b5d1608d73403d5ef089bf8e4dc04bdc358eea8afd7fcb3ae1c77d` |
| quantile | 20261023_120257 | `9b52945aa53e2af2a0189eb8368389410eabd001a6336620684baaca07258bee` |

- `submission.csv`(124행) sha256: `4741a3d37ef3ae9f71b381e083028d93e83ec378ae5d5a65beba2ed48545a8e7`.

## 재현 결과(2026-10-26)

| 검증 | 결과 |
|---|---|
| 새 venv 재현 — 패키지 폴더(14:55) | `submission.csv` 바이트 동일(diff 0), 노트북 오류 0, 7.3분 |
| 새 venv 재현 — 기본 zip | diff 0, 노트북 오류 0, 7.3분 |
| 새 venv 재현 — with_dataon zip | diff 0, 노트북 오류 0, 수위 피처 raw, 7.6분 |
| 오프라인 재현(최종 기본 zip `d6a0f33e…`) | 통과 — 네트워크 차단(감사 훅) 상태에서 노트북·predict 모두 rc 0, sha256 `4741a3d3…` 같음, 외부 접속 시도 0건, 대조 실험 7종 차단 확인 |
| pytest(전체) | 532 통과 |
| 화면 숫자 대조(check_numbers) | 178/178 |
| 배포본 숫자(check_deployed_numbers, 56bd47b 배포본) | 63/63 |
| 쉽게 보기 금지어(11개 경로) | 0건 |
| 패키지 민감정보 검사 | 0건 |
| 방법설명서 PDF | 48쪽(1쪽 = 심사위원용 요약) |

## 다시 빌드할 때 주의

- 패키지를 다시 빌드하면 zip sha256 이 달라진다. `submission.csv` 는 같다. 이유는 두 가지다.
  1. README 에 생성일(`date.today()`)이 들어간다.
  2. 일일 자동 커밋이 패키지에 복사되는 파일을 갱신한다.
- 일일 자동 커밋(GitHub Actions)이 커밋하는 경로:
  - `daily.yml`: `reports/eval/live_benchmark.csv`
  - `mulmoa_snapshot.yml`: `data/raw/mulmoa/*.csv`, `data/raw/kma_forecast/*.csv`, `reports/eval/live_benchmark.csv`
- 이 중 패키지에 들어가는 것:
  - `data/raw/kma_forecast/` — 빌더가 폴더째 복사한다.
  - `reports/eval/live_benchmark.csv` — `figures/reports/eval/` 로 복사된다.
  - `data/raw/mulmoa/` 는 패키지에 들어가지 않는다.
- 이미 만든 `dist/` 의 zip 3종은 일일 커밋의 영향을 받지 않는다(git 추적 밖이고, 다시 빌드하지 않는 한 그대로).
- `models/`·`submission/`·`config/`·`src/` 는 일일 자동 커밋이 건드리지 않는다.
