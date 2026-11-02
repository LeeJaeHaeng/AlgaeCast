# 제출 기록 — `submission-final-qa1030-r2`

- 작성: 2026-11-02(패키지 빌드 17:4x, zip 18:16 KST).
- 이 문서를 담은 커밋에 git 태그 `submission-final-qa1030-r2` 를 단다.
- **r2(같은 날 두 번째 판) 변경**: 첫 판 `submission-final-qa1030`(16:30) 뒤 사용자 요청으로 다시 검증했다 — 최종 zip 오프라인 재현(PASS), Linux 컨테이너 재현, 최종 zip 문서 독립 교차 검토(4관점). 그 결과 고친 것: (1) Linux 최소 이미지(`python:3.11-slim`)에는 LightGBM 의 OpenMP 런타임 `libgomp1` 이 없어 추론 단계에서 실패 → README 4절에 설치 안내, `libgomp1` 을 넣은 Debian 13 컨테이너(`--network none`)에서 추론 4줄·노트북 모두 바이트 동일 확인. Linux 노트북의 재학습 대조는 최대 절대차 1.0×10⁻¹⁰ — 직전 업로드본(T24v)의 '정확히 0.0' 검사였다면 멈췄을 차이로, 허용 오차 비교로 바꾼 것이 필요했음을 확인. (2) README 4절 경로 예시의 제어문자(빌더 이스케이프 실수, `C:c\`)·cmd.exe 에서 실패하는 명령 줄 끝 주석 제거, 빌더에 텍스트 제어문자 검사 추가. (3) 방법설명서 9.2절 설치 명령(PowerShell 5.1 에서 실패하는 `&&`·기본 python → `py -3.11` 3줄), 표 5-16 Brier 차이(+0.008→+0.007), 표지 개정일, 공지 ⑤ 둘째 문장과 5행의 관계 설명, ⑧ 간접 경로를 체크리스트에 명시, 사후 코드 목록 통일(headline.py), 패키지에서 이전 제출 기록(`src/docs/SUBMISSION_FINAL.md`) 제외, 체크리스트 12번(⑦), AI 도구 구분 예외 2건, MANIFEST 표기, verify_package 의 Linux 대응. 재현 코드·모델·데이터·`submission.csv` 는 첫 판과 같다.
- 왜 다시 만들었나: 운영사무국 공식 Q&A(2026-10-30, 출제기관 확인 — 원문 `docs/organizer_answers/2026-10-30.md`)에 맞춰 직전 업로드본(`submission-final-T24v`)을 고쳤다.
  - ⑥ **DataON 원값 제외.** 직전 업로드본의 모델자료 zip 2종에는 2026-10-28 이메일 답변('1. 가능합니다.')에 따라 DataON 연속 수위 원값 `data/raw/dataon/level_continuous_long.parquet`(DataON 128,279행 + WAMIS 15,789행)이 들어 있었다. 10-30 공지 ⑥('재배포 금지 — 원자료 대신 가공한 계수만 동봉')에 따라 뺐다. 수위 피처 2열은 가공 계수 `data/processed/level_cont_features_S1.parquet` 로 채운다(derived). 빌더는 패키지·zip 에 원값이나 원 배포 xlsx 가 있으면 멈춘다.
  - ② 문서·README·대시보드의 'R²' 표기를 공식 정의(원단위 피어슨 상관계수 제곱)로 바로잡았다. 예전 '원단위 R²' 값(r2_raw)은 NSE 다. 공식 4지표 표는 `reports/eval/tbl_official_metrics.md` 다(T24 2025 R² 0.204·NSE 0.175, 2026 사후 0.106·0.002).
  - ④ README 4-1절 '심사 재현(추론만)' 4줄과 난수 시드 42 를 적었다. 노트북 4단계 재학습 대조는 비트 일치 assert 에서 허용 오차(1e-6) 비교·경고로 바꿨다. requirements.txt 의 Windows 전용 `pywinpty` 에 환경 표시를 붙였다.
  - ⑧ 사후 분석 코드(`eval/posthoc*`·`eval/headline.py`·`eval/live.py`·`exp/confirm_2026.py`)를 패키지에서 뺐다.
  - 5행 이메일 답변('해당 5행은 학습에 사용해도 괜찮습니다')에 따라 T24 를 유지하고 엄격판 T24S 는 비상안에서 종료했다(2026 미채점).
  - 대시보드 캡처 6장을 T24·공식 지표 라벨 화면으로 다시 찍었다(2026-11-02 15:40, 웹 커밋 1a25661).
- **제출 모델 T24·`model/`·`submission.csv`(sha256 `057afeee93c7a4213bf9176d8696fd9255617641f5c0b0aa35427a8fc1cf3f73`)는 바꾸지 않았다.** 데모 영상도 v7 그대로다(자막의 '결정계수 0.18·0.00' 은 NSE — `demo/README_DEMO.md` 정정 절).
- 패키지는 커밋 `9033667`(빌드·zip 당시 작업 트리를 그대로 커밋) 의 작업 트리로 빌드했다(실행본 노트북·그림 2장은 18:14 패키지 폴더 검증 `--update-package` 결과). 빌드 뒤 바꾼 것은 `reports/eval/package_verify.*` 검증 기록과 이 문서뿐이다.
- **저장소 밖 보관본: `C:\Users\user\OneDrive\Desktop\경진대회\제출본\`** — zip 4종과 `SHA256SUMS.txt`. 첫 판 4종(`submission-final-qa1030`)은 `제출본\이전\submission-final-qa1030\`, 그 전 업로드본(`submission-final-T24v`)은 `제출본\이전\submission-final-T24v\` 에 있다.

## 제출 조합

| 안 | ① 문서자료 칸 | ② 모델자료 칸 | 쓰는 때 |
|---|---|---|---|
| **A안(기본)** | `AlgaeCast_문서자료_이재행.zip` | `AlgaeCast_모델자료_이재행.zip`(영상 포함) | 기본 |
| **B안** | `AlgaeCast_문서자료_영상포함_이재행.zip` | `AlgaeCast_모델자료_영상제외_이재행.zip` | 모델자료 업로드가 용량 때문에 실패할 때 |

- 각 문서자료 zip 의 `읽어보기.txt` 에는 짝이 되는 모델자료 zip 의 이름과 sha256 이 들어 있다(A안 ↔ 모델자료 영상 포함, B안 ↔ 모델자료 영상제외).

## zip 4종

| 파일 | 크기 | sha256 | 내용 |
|---|---|---|---|
| `AlgaeCast_문서자료_이재행.zip` | 2,563,521 B (2.6 MB) | `7d3d809ccceb1262196b85fa7273cc04d73505d23fbf0090ce3db967f723fe6a` | 폴더 `AlgaeCast_문서자료_이재행/`: `방법설명서.pdf`, `읽어보기.txt`(짝: 모델자료 영상 포함) |
| `AlgaeCast_문서자료_영상포함_이재행.zip` | 25,415,434 B (25.4 MB) | `f9adfb48a103f021670e00cf42f5463c0157da17856efb7e9444f92f0ec5b643` | A안 문서자료 + `demo/AlgaeCast_demo.mp4`·`demo/README_DEMO.md`(짝: 모델자료 영상제외) |
| `AlgaeCast_모델자료_이재행.zip` | 71,303,105 B (71.3 MB) | `30fdd809e596fff7bb758449025bb45902d8bccf2195e347152d18d8741d4577` | 폴더 `AlgaeCast_녹조7일예측_이재행/`: 제출 패키지 전체(영상 포함, **DataON 원값 없음**·가공 계수만, WAMIS 원값 없음) |
| `AlgaeCast_모델자료_영상제외_이재행.zip` | 48,462,609 B (48.5 MB) | `16ec33899f39341c1dffba62fe772168d2cf883f911bf7ce68ba4c9b405b8558` | 위와 같고 데모 영상만 뺌(`demo/영상_별도_안내.txt`) |

- `방법설명서.pdf`(62쪽) sha256 `83eb96d49f4ed9d79dcd4e6c060930a5bb3c5ace17cc0528bf9cf29cc5f73d6c`. 문서자료 zip 2종과 모델자료 zip 2종에 같은 파일이 들어 있다. 1쪽 요약이 한 쪽 안에 들고, 본문 줄 길이 분포가 직전 판과 같아 축소 인쇄가 없다.
- 데모 영상은 v7(sha256 `5c648ac0b38021a12a5c4cbd1b4db97becc6e750babf9e42249f6899cd4d56a1`) 그대로다.

## 제출 모델 T24 (바꾸지 않음)

- 동결 커밋 `a961caf`(2026-10-26 13:17:24 KST), 동결 문서 `models/FROZEN_T24.md`. 학습 = 대회 번들 `eval_pairs.csv` split=train 2,310행(기준일 ≤2024-12-30, 이 중 5행은 목표일 2025-01-06 — 운영사무국 허용).

| 이름 | 버전 | sha256(model.pkl) |
|---|---|---|
| regression | 20261026_131722 | `950dde7fbd1385019363af438a251fe49f901c09afbec7410032c033963b9152` |
| classifier | 20261026_131722 | `496a1a75dd505e2de170461963f8a82bd1b49a3b2a29e8dc6e399e4c68dec696` |
| quantile | 20261026_131722 | `9ebc0cef1c306bb5ad24eae06c643a0eb1cbb219289e023e7ebfe61e8a52defe` |

## 재현·구조 검증(2026-11-02, r2 최종본)

| 검증 | 결과 |
|---|---|
| 새 venv 재현 — 패키지 폴더(17:47~18:14, 26.6분) | 깨끗한 사본에서 추론 4줄 먼저 → `submission_reproduced.csv` 바이트 동일, 이어 노트북 `submission.csv` diff 0, 노트북 오류 0·경고 줄 0·절대경로 0, DataON·WAMIS 원값 없음(derived), 데모 영상 sha256 일치 |
| 새 venv 재현 — 모델자료 zip `30fdd809…`(18:17~18:47, 30.5분) | 위와 같음 — 추론 4줄·노트북 모두 바이트 동일, 오류 0 |
| 오프라인 재현 — 모델자료 zip(18:16~, 19.7분) | 설치 뒤 네트워크 차단(감사 훅·가짜 프록시·PIP_NO_INDEX)에서 노트북 rc 0·sha256 같음, 추론 CLI rc 0·sha256 같음, 차단 기록 0건, 대조 실험 통과 — PASS |
| Linux 재현 — 모델자료 zip(Docker Debian 13 `python:3.11-slim` + `libgomp1`, Python 3.11.18, `--network none`) | 통과 — 추론 4줄 11.5분·노트북 12.6분, 둘 다 sha256 `057afeee…`(124행 일치, 공지 ④ 불일치 0), 노트북 오류 0, 재학습 대조 최대 절대차 1.0×10⁻¹⁰(허용 오차 안, 경고 없음). `libgomp1` 없이는 추론 단계에서 LightGBM 로드 실패(첫 판 시험에서 발견 → README 안내) |
| 영상제외 zip | 모델자료 zip 과 454개 항목 중 데모 영상(→ `demo/영상_별도_안내.txt`) 1개만 다르고 나머지 CRC 모두 같음 |
| zip 구조 | 4종 모두 최상위 폴더 하나, CRC 정상, 텍스트 제어문자 0개, DataON 원값·원 배포 xlsx 0개(남은 xlsx 2개는 대회 번들), 사후 분석 코드 0개(headline 포함), `src/docs/SUBMISSION_FINAL.md` 없음 |
| 읽어보기 짝 sha256 | A안 = 모델자료 영상 포함(`30fdd809…`), B안 = 영상제외(`16ec3389…`), 두 문서자료 PDF = `reports/방법설명서.pdf`(`83eb96d4…`) |
| 패키지 README 7절 체크리스트 | 12개 모두 ✅(공지 #564 7개 + 공식 Q&A ④⑤⑥⑦⑧) |
| 첫 판 검증(참고) | 첫 판(16:30, 재현 코드 같음)도 새 venv 폴더·zip, 오프라인(폴더 15:43·zip 17:00) 모두 통과 |
| pytest | 548 passed |

## 다시 빌드할 때 주의

- 패키지를 다시 빌드하면 zip sha256 이 달라지고, 문서자료 `읽어보기.txt` 의 짝 sha256 도 따라 바뀐다. `submission.csv` 는 같다. 이유는 README 생성일과 일일 자동 커밋이 갱신하는 파일(`data/raw/kma_forecast/`, `reports/eval/live_benchmark.csv`)이다.
- `--zip-only` 는 패키지 `방법설명서.pdf` 가 `reports/방법설명서.pdf` 와 다르거나, `reports/방법설명서.md` 가 PDF 보다 새것이면 멈춘다.
- 빌드·zip 은 패키지에 DataON 원값(연속 수위 시계열·원 배포 xlsx)이 있으면 멈춘다(공지 ⑥).
- 1단계 빌드는 저장소의 실행 전 노트북을 복사한다. `verify_package.py --update-package` 로 실행본을 넣거나, 검증 뒤 다시 빌드했다면 검증 실행본 ipynb·그림 2장을 복사한 뒤 `--zip-only` 한다(이번 제출본은 후자).
- zip 은 짧은 경로에 푼다(Windows 260자).

## 이전 후보

| 태그 | 커밋 | 기본 zip sha256 | 비고 |
|---|---|---|---|
| `submission-final-qa1030` | e24b509 | 모델자료 `faab3d43…`·문서자료 `aa0903cd…` | 10-30 공지 대응 첫 판(DataON 원값 제외). 재검증에서 README 제어문자·Linux `libgomp1` 안내 누락 등을 찾아 r2 로 교체. `제출본\이전\submission-final-qa1030\` 에 보관 |
| `submission-final-T24v` | 263bf60 | 모델자료 `35531a6d…`·문서자료 `03695ea4…` | 제출 모델 T24(`057afeee…`, 같음), 데모 v7. 모델자료 zip 에 DataON 원값 포함(10-28 이메일 답변) — 10-30 공지 ⑥으로 교체. `제출본\이전\submission-final-T24v\` 에 보관 |
| `submission-final-T24` | 7b9f218 | 모델자료 `4da85a57…`·문서자료 `cec8009d…` | 제출 모델 T24(`057afeee…`, 같음). 데모 영상만 v6(T24 전환 전 v2.1 기준 녹화, `0907b110…`). `제출본\이전\submission-final-T24\` 에 보관 |
| `submission-final-upload` | 73f46ce | 모델자료 `37545b92…`·문서자료 `b2230314…` | 제출 모델 v2.1(`4741a3d3…`), DataON 원값 미포함(대체본 with_dataon 별도). `제출본\이전\submission-final-upload\` 에 보관 |
| `submission-final-1028` | bd6dc9f | `a4195fbf…`(`AlgaeCast_녹조7일예측_이재행.zip`) | 제출란 2칸 공지 전. `제출본\이전\submission-final-1028\` 에 보관 |
| `submission-candidate-final` | 34ebd01 | `28dc846c…` | `제출본\이전\submission-candidate-final\` 에 보관 |
| `submission-candidate-1026` | 45a4ef1 | `d6a0f33e…` | `dist/` 에서 덮어써짐(파일 없음) |
