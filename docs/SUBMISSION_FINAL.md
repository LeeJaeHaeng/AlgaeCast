# 제출 기록 — `submission-final-upload`

- 작성: 2026-10-27(패키지 빌드 17:50, zip 18:01 KST).
- 공지(2026-10-27, 결과 제출 시작): 제출란은 두 칸이다. ① 문서자료(필수, "문제해결 방법에 대한 설명 문서: 개요, 활용 데이터, 모델 개발 방법, 실험 및 평가, 기대효과 등") ② 모델자료("모델 개발 결과(모델 실행 매뉴얼 포함)"). 둘 다 .zip 만 받고 자료는 한 개의 폴더로 압축한다. 용량 제한은 공지에 없다.
- 이 문서를 담은 커밋에 git 태그 `submission-final-upload` 를 단다.
- 패키지는 커밋 `464ecd5` 의 작업 트리로 빌드했다. 빌드 뒤에 바꾼 것은 다음뿐이다.
  - 방법설명서 9절 검증 시각(PDF 를 다시 렌더링해 zip 만들기 전에 패키지에 넣음)
  - `reports/eval/package_verify.*` 검증 기록
  - 이 문서와 `docs/handoff/`(패키지 제외)
- 제출 모델·예측값·`submission.csv` 는 바꾸지 않았다.
- **저장소 밖 보관본: `C:\Users\user\OneDrive\Desktop\경진대회\제출본\`**
  - zip 5종과 `SHA256SUMS.txt`. `sha256sum -c` 로 대조했다.
  - 이전 후보는 후보별 하위 폴더로 옮겼다: `제출본\이전\submission-final-1028\`, `제출본\이전\submission-candidate-final\`.
  - 저장소에서 다시 빌드해도 이 사본은 건드리지 않는다. 제출에는 이 사본을 쓴다.

## 제출 조합

| 안 | ① 문서자료 칸 | ② 모델자료 칸 | 쓰는 때 |
|---|---|---|---|
| **A안(기본)** | `AlgaeCast_문서자료_이재행.zip` | `AlgaeCast_모델자료_이재행.zip`(영상 포함) | 기본 |
| **B안** | `AlgaeCast_문서자료_영상포함_이재행.zip` | `AlgaeCast_모델자료_영상제외_이재행.zip` | 모델자료 업로드가 용량 때문에 실패할 때 |

- 각 문서자료 zip 의 `읽어보기.txt` 에는 짝이 되는 모델자료 zip 의 이름과 sha256 이 들어 있다(A안 ↔ 모델자료 영상 포함, B안 ↔ 모델자료 영상제외).
- `AlgaeCast_녹조7일예측_이재행_with_dataon.zip` 은 이름을 그대로 두었다. 운영사무국이 DataON 원값 재배포를 허용할 때만 모델자료 칸에 쓰는 대체본이다.

## zip 5종

| 파일 | 크기 | sha256 | 내용 |
|---|---|---|---|
| `AlgaeCast_문서자료_이재행.zip` | 2,395,008 B (2.4 MB) | `b2230314bb33970b454f76c0187fda07c23634adede8d6b229ba5f12de32490e` | 폴더 `AlgaeCast_문서자료_이재행/`: `방법설명서.pdf`, `읽어보기.txt` |
| `AlgaeCast_문서자료_영상포함_이재행.zip` | 25,030,157 B (25.0 MB) | `3cd3de4c08fa37acb9d24849f1328572aee317eb557350d9720560806b7eecf4` | A안 + `demo/AlgaeCast_demo.mp4`·`demo/README_DEMO.md` |
| `AlgaeCast_모델자료_이재행.zip` | 62,975,053 B (63.0 MB) | `37545b92869a81d3f35fea49b3222375f2bfd4935c7fa796376b2791f2d13ad9` | 폴더 `AlgaeCast_녹조7일예측_이재행/`: 제출 패키지 전체(영상 포함, DataON·WAMIS 원값 없음) |
| `AlgaeCast_모델자료_영상제외_이재행.zip` | 40,347,520 B (40.3 MB) | `928a28e9784b84be39c1e0205788448fea4f7e53dff213cc4b348b20d7515656` | 위와 같고 데모 영상만 뺌(`demo/영상_별도_안내.txt`) |
| `AlgaeCast_녹조7일예측_이재행_with_dataon.zip` | 63,818,181 B (63.8 MB) | `5c1169b3f075c1aa19d2d312278f6ad6e256941ea8202c279bb687874b3332b6` | DataON 원값 포함 대체본 — 운영사무국 허용 시에만 |

- `방법설명서.pdf`(53쪽) sha256 `d4e5952f1a5ff08e7c2d35b854d8719dab56b1c85e9400c11c642f249af6d047`. 문서자료 zip 2종과 모델자료 zip 3종에 같은 파일이 들어 있다.
- 데모 영상은 v6 그대로다(sha256 `0907b1103c25371a…`).

## 제출 모델 v2.1

- 동결 커밋 `217260e`(2026-10-23 12:08:19 KST), 동결 문서 `models/FROZEN_v2.1.md`.
- 아래 3개 버전은 레지스트리 current 와 같고, 패키지 `model/` 에는 이 3개 폴더만 있다.

| 이름 | 버전 | sha256(model.pkl) |
|---|---|---|
| regression | 20261023_120818 | `d95e7a4e8dab50a59583dd8ecf8ab2482786ec05f7bfa1f256c657bec3a091f0` |
| classifier | 20261023_120255 | `cce848b6c1b5d1608d73403d5ef089bf8e4dc04bdc358eea8afd7fcb3ae1c77d` |
| quantile | 20261023_120257 | `9b52945aa53e2af2a0189eb8368389410eabd001a6336620684baaca07258bee` |

- `submission.csv`(124행) sha256: `4741a3d37ef3ae9f71b381e083028d93e83ec378ae5d5a65beba2ed48545a8e7`.

## 재현·구조 검증(2026-10-27)

| 검증 | 결과 |
|---|---|
| 새 venv 재현 — 패키지 폴더(18:00) | `submission.csv` 바이트 동일(diff 0), 노트북 오류 0, 9.5분 |
| 새 venv 재현 — 모델자료 기본 zip(18:13) | diff 0, 노트북 오류 0, 11.6분(오프라인 검증과 동시에 실행) |
| 새 venv 재현 — with_dataon zip(18:24) | diff 0, 노트북 오류 0, 수위 피처 raw, 9.8분 |
| 새 venv 재현 — 모델자료 영상제외 zip(18:33) | diff 0, 노트북 오류 0, 9.3분. 영상을 뺀 판이라 데모 영상 항목만 '없음'(검증 종료 코드 2 는 이 항목 때문) |
| 오프라인 재현 — 모델자료 기본 zip(18:05) | 네트워크를 막은 상태(감사 훅)에서 노트북·predict 모두 rc 0, sha256 `4741a3d3…` 같음, 외부 접속 시도 0건, 대조 실험 통과 — PASS(12분) |
| zip 구조(PowerShell `Expand-Archive`) | 5종 모두 최상위 폴더 하나, 한글 파일명 정상(비ASCII 이름 전 항목 UTF-8 플래그), CRC 정상, zip 안 가장 긴 경로 100자 |
| 읽어보기 짝 sha256 | A안 `37545b92…` = 모델자료, B안 `928a28e9…` = 모델자료 영상제외 |
| 대시보드·다시 보기 주소 4개 | 모두 HTTP 200, 장면 띠 '다시 보기 — 2026-07-27·08-03·07-06 기준' 확인 |
| pytest(전체) | 543 통과 |
| 패키지 민감정보 검사 | 0건 |
| 방법설명서 PDF | 53쪽: 1쪽 요약, 2쪽 제출 양식 항목 대응표, 3쪽 목차, 11장 기대효과, 부록 C AI 활용범위 |

## 다시 빌드할 때 주의

- 패키지를 다시 빌드하면 zip sha256 이 달라지고, 문서자료 `읽어보기.txt` 의 짝 sha256 도 따라 바뀐다. `submission.csv` 는 같다. 이유는 README 생성일(`date.today()`)과 일일 자동 커밋이 갱신하는 파일(`data/raw/kma_forecast/`, `reports/eval/live_benchmark.csv`)이다.
- `--zip-only` 는 패키지 `방법설명서.pdf` 가 `reports/방법설명서.pdf` 와 다르면 멈춘다. 9절을 고쳐 다시 렌더링했으면 PDF 를 패키지에 복사한 뒤 실행한다.
- zip 은 짧은 경로에 푼다. 깊은 폴더(예: 전체 경로 160자 이상)에 풀면 Windows 경로 길이 제한(260자)에 걸릴 수 있다(zip 안 가장 긴 경로 100자).
- 이미 만든 zip(`dist/`, git 추적 밖)과 `제출본` 보관본은 일일 커밋의 영향을 받지 않는다. 옛 이름 zip 은 `dist/이전_submission-final-1028/` 로 옮겼다.

## 이전 후보

| 태그 | 커밋 | 기본 zip sha256 | 비고 |
|---|---|---|---|
| `submission-final-1028` | bd6dc9f | `a4195fbf…`(`AlgaeCast_녹조7일예측_이재행.zip`) | 제출란 2칸 공지 전. `제출본\이전\submission-final-1028\` 에 보관 |
| `submission-candidate-final` | 34ebd01 | `28dc846c…` | `제출본\이전\submission-candidate-final\` 에 보관 |
| `submission-candidate-1026` | 45a4ef1 | `d6a0f33e…` | `dist/` 에서 덮어써짐(파일 없음) |
