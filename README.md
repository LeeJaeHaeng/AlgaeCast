# AlgaeCast-7

수질·수문·기상 공개 데이터를 융합해 조류경보제 5개 지점의 유해남조류 세포수를 **7일 선행 예측**하고,
경계(10,000 cells/mL) 초과 확률과 녹조제거설비 배치 우선순위를 대시보드로 제공한다.
2026 DATA·AI 분석 경진대회(KISTI) 문제해결 부문 제출작.

- 작업 규칙·실격 조건: [`CLAUDE.md`](CLAUDE.md)
- 문서 지도: [`docs/00_README.md`](docs/00_README.md)
- 태스크 지시서: [`docs/09_DEV_GUIDE_CLAUDE_CODE.md`](docs/09_DEV_GUIDE_CLAUDE_CODE.md)
- 진행 기록: [`docs/PROGRESS.md`](docs/PROGRESS.md)

## 빠른 시작 (Python 3.11, GNU make)
```bash
cp .env.example .env      # data.go.kr 인증키 입력
make setup                # .venv 생성 + 의존성 + pre-commit
make test                 # pytest (누수 테스트 포함)
```
Windows: `winget install ezwinports.make Python.Python.3.11` 후 새 터미널에서 실행.

## 핵심 결과
제출·운영 모델은 **T24**([`models/FROZEN_T24.md`](models/FROZEN_T24.md))다. v2.1(데이터 유래 상수 누수 수정판)과 구성이 같고, 학습은 대회 번들 `eval_pairs.csv` 의 split=train 정의 그대로(2,310행, 기준일 ≤2024-12-30, 이 중 5행은 목표일 2025-01-06)다.
2024년까지 자료로만 학습한 모델(T24, 대회 공식 학습 분할)로 2026년 경계 사건 8건 중 7건을 중앙 21일 앞서 감시 단계로 포착했다(지속성 2건).
2020~2026년 합계로는 28건 중 24건(86%)을 첫 경계 초과 측정 기준 중앙 14일 앞서 포착했다(지속성 3건).
T24 의 2026 결과는 동결 뒤 한 번 계산한 사후 계산이며 블라인드가 아니다(팀은 v2.1 의 2026 결과를 본 뒤 T24 를 사전등록·동결).

2026-10-28 운영사무국 답변("학습은 24년까지의 데이터만 활용 가능합니다", [`docs/organizer_answers/2026-10-28.md`](docs/organizer_answers/2026-10-28.md))에 따라, 답변 전에 등록한 규칙([`reports/experiments/PREREG_contingency.md`](reports/experiments/PREREG_contingency.md) 2·7·8절, 사전등록 960d76f·동결 a961caf)대로 제출 모델을 v2.1(최종 적합 ≤2025)에서 T24 로 바꿨다. 목표일 2025-01-06 인 5행까지 뺀 엄격판 T24S 는 비상안으로 동결했다(2026 미채점).

2026-10-23 참가자 지시로 데이터로 계산한 상수를 전수 점검했다. 그 결과 v1(2026-10-21 봉인)·v2(2026-10-22 동결)의 일부 상수(지점별 수온 임계, 수위 기준 평균, ASOS 관측소 선정)가 2026년 자료를 포함한 전 기간으로 계산돼 있었음을 발견했다.
사전등록한 규칙([`reports/experiments/FIX-v2.1/PREREG.md`](reports/experiments/FIX-v2.1/PREREG.md))대로 고쳐 v2.1 을 결과와 무관하게 채택했다(T24 는 이 v2.1 구성을 그대로 쓴다). 영향과 재발 방지는 [`RESULT.md`](reports/experiments/FIX-v2.1/RESULT.md) 에 있다.
v1 의 2026년 8건 중 7건은 이력으로만 남긴다. 같은 규칙으로 고친 v1-fix 도 8건 중 7건이다.

상세와 한계(2026 사후 성능 저하 등)는 `reports/방법설명서.pdf` 1·5(5.11 결정별 사용 자료·5.12 전환)·6·10장.

## 재현
저장소에서 동결 모델로 제출 파일을 다시 만들어 제출본과 비교한다(재학습 없음).
```bash
make reproduce    # 동결 모델 해시 확인 → 정렬 → 피처 → 예측 → submission/submission.csv 와 바이트 비교
```

## 제출 패키지 (공지 #564 구조)
```bash
python scripts/render_method_doc.py                       # reports/방법설명서.md → .pdf (헤드리스 Edge)
python scripts/build_submission_package.py                # submission_package/ 생성(데모 영상 sha256 확인)
python scripts/verify_package.py --update-package         # 새 venv 재현 검증(diff 0·노트북 오류 0)
python scripts/build_submission_package.py --zip-only     # dist/ 에 모델자료 zip 2종(AlgaeCast_모델자료_이재행·_영상제외, 둘 다 DataON 원값 포함) + 문서자료 zip 2종(A안 AlgaeCast_문서자료_이재행, B안 _영상포함)
```
패키지 안에서는 `jupyter lab notebooks/01_train_eval.ipynb` 로 노트북을 열어 셀 단위로 실행할 수 있다.
