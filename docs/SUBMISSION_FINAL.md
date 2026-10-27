# 제출 후보 기록 — `submission-final-1028`

- 작성: 2026-10-27(패키지 빌드 2026-10-27 10:34, zip 10:44 KST).
- 이 문서를 담은 커밋에 git 태그 `submission-final-1028` 을 단다.
- 패키지는 이 태그 커밋과 같은 작업 트리로 빌드했다. 빌드 뒤에 바꾼 것은 `reports/eval/package_verify.*` 검증 기록, 방법설명서 9절 검증 시각(PDF 를 다시 렌더링해 zip 만들기 전에 패키지에 넣음), 이 문서, `docs/handoff/`(패키지 제외)뿐이다.
- **저장소 밖 보관본: `C:\Users\user\OneDrive\Desktop\경진대회\제출본\`**
  - zip 3종과 `SHA256SUMS.txt`. `sha256sum -c` 로 대조했다.
  - 이전 후보(`submission-candidate-final`)의 사본은 `제출본\이전\` 으로 옮겼다.
  - 저장소에서 다시 빌드해도 이 사본은 건드리지 않는다. 제출에는 이 사본을 쓴다.
- 이전 후보 `submission-candidate-final`(zip 기본 `28dc846c…`)과 비교한 변경 사항:
  - 대시보드 문구 '공식 발령 발령 없음' → '공식 발령 없음'(웹, 패키지 밖)과 다시 보기 근거·날씨 실측 칸 — 방법설명서 8.4절에 반영
  - `docs/PROGRESS.md` 기록, 방법설명서 9절 검증 시각
  - 일일 자동 커밋이 갱신한 `data/raw/kma_forecast/`·`reports/eval/live_benchmark.csv`
  - `submission.csv`·모델·데모 영상(v6 `0907b110…`)·스크린샷은 같다.

## zip 3종

| 파일 | 크기 | sha256 | 용도 |
|---|---|---|---|
| `AlgaeCast_녹조7일예측_이재행.zip` | 62,928,919 B (62.9 MB) | `a4195fbf72ad67c6ba872492325fe34765e0571d43b4f24bd24d487a3f2027fa` | 기본 제출 zip(영상 포함, DataON·WAMIS 원값 없음) |
| `AlgaeCast_녹조7일예측_이재행_영상제외.zip` | 40,301,354 B (40.3 MB) | `19c66310dea026b4d9ae593b49c0c301dfd8f4451311e6e36310df03a274a479` | 용량 제한 대비(영상 제외) |
| `AlgaeCast_녹조7일예측_이재행_with_dataon.zip` | 63,772,053 B (63.8 MB) | `6c7e4754a52ade64ca22299cb3d27ae6343f3854a88fa76e3385a9023bdf996a` | DataON 원값 포함 대체본 — 운영사무국이 허용할 때만 |

## 제출 모델 v2.1

- 동결 커밋 `217260e`(2026-10-23 12:08:19 KST), 동결 문서 `models/FROZEN_v2.1.md`.
- 아래 3개 버전은 레지스트리 current 와 같고, 패키지 `model/` 에는 이 3개 폴더만 있다.

| 이름 | 버전 | sha256(model.pkl) |
|---|---|---|
| regression | 20261023_120818 | `d95e7a4e8dab50a59583dd8ecf8ab2482786ec05f7bfa1f256c657bec3a091f0` |
| classifier | 20261023_120255 | `cce848b6c1b5d1608d73403d5ef089bf8e4dc04bdc358eea8afd7fcb3ae1c77d` |
| quantile | 20261023_120257 | `9b52945aa53e2af2a0189eb8368389410eabd001a6336620684baaca07258bee` |

- `submission.csv`(124행) sha256: `4741a3d37ef3ae9f71b381e083028d93e83ec378ae5d5a65beba2ed48545a8e7`.

## 재현 결과(2026-10-27)

| 검증 | 결과 |
|---|---|
| 새 venv 재현 — 패키지 폴더(2026-10-27 10:44) | `submission.csv` 바이트 동일(diff 0), 노트북 오류 0, 9.2분 |
| 새 venv 재현 — 기본 zip | diff 0, 노트북 오류 0, 8.5분 |
| 새 venv 재현 — with_dataon zip | diff 0, 노트북 오류 0, 수위 피처 raw, 8.6분 |
| 오프라인 재현(최종 기본 zip `a4195fbf…`) | 네트워크를 막은 상태(감사 훅)에서 노트북·predict 모두 rc 0, sha256 `4741a3d3…` 같음, 외부 접속 시도 0건 |
| pytest(전체) | 540 통과 |
| 화면 숫자 대조(check_numbers) | 178/178 |
| 배포본 숫자(check_deployed_numbers, 4db74cf 배포본) | 63/63 |
| 다시 보기 미래 관측 누수(check_asof, 프로덕션) | 장면 3개 × 9쪽 × 토글 끔·켬 = 54쪽 실패 0 |
| 단어 중복(check_dup_words, 프로덕션) | copy.ts 0건 + 화면 0건 |
| 쉽게 보기 금지어(기본 11 + 다시 보기 8 URL, 프로덕션) | 0건 |
| 패키지 민감정보 검사 | 0건 |
| 방법설명서 PDF | 1쪽 = 심사위원용 요약 |

## 다시 빌드할 때 주의

- 패키지를 다시 빌드하면 zip sha256 이 달라진다. `submission.csv` 는 같다. 이유는 README 생성일(`date.today()`)과 일일 자동 커밋이 갱신하는 파일(`data/raw/kma_forecast/`, `reports/eval/live_benchmark.csv`)이다.
- `models/`·`submission/`·`config/`·`src/` 는 일일 자동 커밋이 건드리지 않는다.
- 이미 만든 zip(`dist/`, git 추적 밖)과 `제출본` 보관본은 일일 커밋의 영향을 받지 않는다.

## 이전 후보

| 태그 | 커밋 | 기본 zip sha256 | 비고 |
|---|---|---|---|
| `submission-candidate-final` | 34ebd01 | `28dc846c…` | `제출본\이전\` 에 보관 |
| `submission-candidate-1026` | 45a4ef1 | `d6a0f33e…` | `dist/` 에서 덮어써짐(파일 없음) |
