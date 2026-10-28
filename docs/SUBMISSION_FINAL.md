# 제출 기록 — `submission-final-T24v`

- 작성: 2026-10-28(패키지 빌드 13:42, zip 14:08 KST).
- 공지(2026-10-27, 결과 제출 시작): 제출란은 두 칸이다. ① 문서자료(필수, "문제해결 방법에 대한 설명 문서: 개요, 활용 데이터, 모델 개발 방법, 실험 및 평가, 기대효과 등") ② 모델자료("모델 개발 결과(모델 실행 매뉴얼 포함)"). 둘 다 .zip 만 받고 자료는 한 개의 폴더로 압축한다.
- 이 문서를 담은 커밋에 git 태그 `submission-final-T24v` 를 단다.
- 직전 후보(`submission-final-T24`)와 다른 점: **데모 영상만 T24 기준으로 다시 만들었다(v7).** 제출 모델 T24·예측값·`submission.csv`(sha256 `057afeee93c7a4213bf9176d8696fd9255617641f5c0b0aa35427a8fc1cf3f73`)는 같다.
  - 영상 v7: sha256 `5c648ac0b38021a12a5c4cbd1b4db97becc6e750babf9e42249f6899cd4d56a1`. 노트북 실행 구간(T24 패키지, 출력 sha256 `057afeee…`)과 운영 화면 13장면(다시 보기 장면 ① 포함)을 다시 녹화했다. 자막 문구는 '2024년까지 자료로만 학습한 모델(T24, 대회 공식 학습 분할)'이다. 길이 2:28·자막 띠 규칙은 같다(방법설명서 9.4절, `demo/README_DEMO.md`).
  - 이에 따라 바뀐 것: 빌더·검증기의 `DEMO_SHA_PREFIX`, 패키지 README 데모 행, 문서자료 `읽어보기.txt` 의 데모 안내 줄, 방법설명서 9.1·9.3·9.4절과 9절 검증 시각, `demo/`(영상·자막·콘티·README_DEMO·캡처 7장).
  - 제출 모델 T24 와 DataON 원값 포함(운영사무국 답변 1-1)은 `submission-final-T24` 와 같다. 그 전 업로드본(`submission-final-upload`)은 제출 모델 v2.1 이다.
- 패키지는 커밋 `fea4295` 의 작업 트리로 빌드했다. 빌드 뒤에 바꾼 것은 다음뿐이다.
  - 방법설명서 9절 검증 시각(PDF 를 다시 렌더링해 zip 만들기 전에 패키지에 넣음)
  - `reports/eval/package_verify.*` 검증 기록
  - 이 문서와 `docs/handoff/`(패키지 제외)
- **저장소 밖 보관본: `C:\Users\user\OneDrive\Desktop\경진대회\제출본\`**
  - zip 4종과 `SHA256SUMS.txt`. `sha256sum -c` 로 대조했다.
  - 직전 후보 5종(`submission-final-T24`)은 `제출본\이전\submission-final-T24\` 로 옮겼다.

## 제출 조합

| 안 | ① 문서자료 칸 | ② 모델자료 칸 | 쓰는 때 |
|---|---|---|---|
| **A안(기본)** | `AlgaeCast_문서자료_이재행.zip` | `AlgaeCast_모델자료_이재행.zip`(영상 포함) | 기본 |
| **B안** | `AlgaeCast_문서자료_영상포함_이재행.zip` | `AlgaeCast_모델자료_영상제외_이재행.zip` | 모델자료 업로드가 용량 때문에 실패할 때 |

- 각 문서자료 zip 의 `읽어보기.txt` 에는 짝이 되는 모델자료 zip 의 이름과 sha256 이 들어 있다(A안 ↔ 모델자료 영상 포함, B안 ↔ 모델자료 영상제외).

## zip 4종

| 파일 | 크기 | sha256 | 내용 |
|---|---|---|---|
| `AlgaeCast_문서자료_이재행.zip` | 2,469,417 B (2.5 MB) | `03695ea44772f6b6a576bb348a8eaaa24602b8009fae1627336cb6f42313ba95` | 폴더 `AlgaeCast_문서자료_이재행/`: `방법설명서.pdf`, `읽어보기.txt`(짝: 모델자료 영상 포함) |
| `AlgaeCast_문서자료_영상포함_이재행.zip` | 25,319,702 B (25.3 MB) | `608d0adc9bb4d9e04df1bdadb4e0446cbd0231e0bfd2c48439c20ae1b157be67` | A안 문서자료 + `demo/AlgaeCast_demo.mp4`·`demo/README_DEMO.md`(짝: 모델자료 영상제외) |
| `AlgaeCast_모델자료_이재행.zip` | 64,927,990 B (64.9 MB) | `35531a6d4bd5273f5615da9b60edca6d073917355cb42bca40782c052e0dad3f` | 폴더 `AlgaeCast_녹조7일예측_이재행/`: 제출 패키지 전체(영상 포함, DataON 연속 수위 원값 포함, WAMIS 원값 없음) |
| `AlgaeCast_모델자료_영상제외_이재행.zip` | 42,087,494 B (42.1 MB) | `f3d1ae49a5c26799f697589f129c4d24fd309e427b6cbca7e9856fb49445e4ac` | 위와 같고 데모 영상만 뺌(`demo/영상_별도_안내.txt`) |

- `방법설명서.pdf`(58쪽) sha256 `8f27b749fca31836a76250929f9cfbb36dfa5eb2c4a1149835efce4202491d8f`. 문서자료 zip 2종과 모델자료 zip 2종에 같은 파일이 들어 있다.
- 데모 영상은 v7(sha256 `5c648ac0b38021a12a5c4cbd1b4db97becc6e750babf9e42249f6899cd4d56a1`, 2026-10-28 제출 모델 T24 기준 재녹화)이다. 모델자료(영상 포함) zip 과 문서자료 영상포함 zip 에 같은 파일이 들어 있다.

## 제출 모델 T24

- 동결 커밋 `a961caf`(2026-10-26 13:17:24 KST), 동결 문서 `models/FROZEN_T24.md`. 학습 = 대회 번들 `eval_pairs.csv` split=train 2,310행(기준일 ≤2024-12-30, 이 중 5행은 목표일 2025-01-06).
- 아래 3개 버전은 레지스트리 current 와 같고, 패키지 `model/` 에는 이 3개 폴더만 있다(이력 8폴더는 `model/HISTORY.md`).

| 이름 | 버전 | sha256(model.pkl) |
|---|---|---|
| regression | 20261026_131722 | `950dde7fbd1385019363af438a251fe49f901c09afbec7410032c033963b9152` |
| classifier | 20261026_131722 | `496a1a75dd505e2de170461963f8a82bd1b49a3b2a29e8dc6e399e4c68dec696` |
| quantile | 20261026_131722 | `9ebc0cef1c306bb5ad24eae06c643a0eb1cbb219289e023e7ebfe61e8a52defe` |

- 엄격판 T24S(목표일 2025 5행 제외)는 비상안으로 동결만 했다(db2b3f2, 2026 미채점, 패키지 미포함).

## 재현·구조 검증(2026-10-28)

| 검증 | 결과 |
|---|---|
| 새 venv 재현 — 패키지 폴더(13:43~13:55) | `submission.csv` 바이트 동일(diff 0), 노트북 오류 0·경고 줄 0·절대경로 0, 데모 영상 sha256 일치(`5c648ac0…`), DataON 원자료로 수위 피처 계산(raw), WAMIS 원값 없음(derived), `model/` T24 3폴더만, 11.5분 |
| 오프라인 재현 — 패키지 폴더(13:55~14:07) | 네트워크를 막은 상태(감사 훅·가짜 프록시·PIP_NO_INDEX)에서 노트북·predict 모두 rc 0, sha256 `057afeee…` 같음, 차단 기록 0건, 대조 실험 통과 — PASS(11.8분). zip 은 이 폴더에 README 체크리스트·PDF 9절 시각만 더한 것 |
| 새 venv 재현 — 모델자료 zip(14:08~14:20, 기록 보존용 재실행 14:36~14:53) | 두 번 모두 diff 0, 노트북 오류 0, 데모 영상 sha256 일치, raw·derived, 11.3분·17.5분 |
| 새 venv 재현 — 모델자료 영상제외 zip(14:20~14:35) | diff 0, 노트북 오류 0, 14.7분. 영상을 뺀 판이라 데모 영상 항목만 '없음'(검증 종료 코드 2 는 이 항목 때문) |
| zip 구조(PowerShell `Expand-Archive`, 짧은 경로) | 4종 모두 최상위 폴더 하나, 한글 파일명 정상(비ASCII 이름 전 항목 UTF-8 플래그), CRC 정상, zip 안 가장 긴 경로 103자 |
| 읽어보기 짝 sha256 | A안 = 모델자료 영상 포함, B안 = 모델자료 영상제외, 두 문서자료 PDF = `reports/방법설명서.pdf`, 데모 안내 줄 = 'T24 기준으로 다시 녹화' |
| 모델자료 내용 | `model/` = T24 3폴더(`*/20261026_131722`), DataON 연속 수위 원값 있음, T24S 제출본 없음, `submission.csv` = `057afeee…`, `demo/AlgaeCast_demo.mp4` = `5c648ac0…`(영상제외판은 없음) |
| 데모 영상 v7 | 148.000초·4,440프레임, 자동 점검 296프레임 이상 0건, 옛 문구('발령 발령'·'2025년까지 자료로' 등) — 화면 글자·노트북·자막 0건, 프레임 OCR 정확 일치 0건(v6 양성 대조로 검출력 확인) |
| 대시보드·다시 보기 주소 4개 | 모두 HTTP 200, 장면 띠 '다시 보기 — 2026-07-27·08-03·07-06 기준. 동결 모델(T24)' 확인. 웹은 이번에 바꾸지 않았다(프로덕션 화면 검사 68/68·check-asof 54쪽 0 등은 `submission-final-T24` 기록 그대로) |
| 패키지 민감정보 검사 | 0건 |
| 방법설명서 PDF | 58쪽(이전과 같음), 축소 인쇄 없음(글자 상자 높이가 이전 판과 같음) |
| pytest | 546 passed |

## 다시 빌드할 때 주의

- 패키지를 다시 빌드하면 zip sha256 이 달라지고, 문서자료 `읽어보기.txt` 의 짝 sha256 도 따라 바뀐다. `submission.csv` 는 같다. 이유는 README 생성일(`date.today()`)과 일일 자동 커밋이 갱신하는 파일(`data/raw/kma_forecast/`, `reports/eval/live_benchmark.csv`)이다.
- `--zip-only` 는 패키지 `방법설명서.pdf` 가 `reports/방법설명서.pdf` 와 다르면 멈춘다. 9절을 고쳐 다시 렌더링했으면 PDF 를 패키지에 복사한 뒤 실행한다.
- 빌드·zip 은 `demo/AlgaeCast_demo.mp4` 의 sha256 이 `DEMO_SHA_PREFIX`(v7 `5c648ac0`)로 시작하지 않으면 멈춘다.
- zip 은 짧은 경로에 푼다. 깊은 폴더에 풀면 Windows 경로 길이 제한(260자)에 걸릴 수 있다.
- 이미 만든 zip(`dist/`, git 추적 밖)과 `제출본` 보관본은 일일 커밋의 영향을 받지 않는다.

## 이전 후보

| 태그 | 커밋 | 기본 zip sha256 | 비고 |
|---|---|---|---|
| `submission-final-T24` | 7b9f218 | 모델자료 `4da85a57…`·문서자료 `cec8009d…` | 제출 모델 T24(`057afeee…`, 같음). 데모 영상만 v6(T24 전환 전 v2.1 기준 녹화, `0907b110…`). `제출본\이전\submission-final-T24\` 에 보관 |
| `submission-final-upload` | 73f46ce | 모델자료 `37545b92…`·문서자료 `b2230314…` | 제출 모델 v2.1(`4741a3d3…`), DataON 원값 미포함(대체본 with_dataon 별도). `제출본\이전\submission-final-upload\` 에 보관 |
| `submission-final-1028` | bd6dc9f | `a4195fbf…`(`AlgaeCast_녹조7일예측_이재행.zip`) | 제출란 2칸 공지 전. `제출본\이전\submission-final-1028\` 에 보관 |
| `submission-candidate-final` | 34ebd01 | `28dc846c…` | `제출본\이전\submission-candidate-final\` 에 보관 |
| `submission-candidate-1026` | 45a4ef1 | `d6a0f33e…` | `dist/` 에서 덮어써짐(파일 없음) |
