# 모델 동결 T24 (FROZEN_T24) — 제출·운영 모델(2026-10-28 전환): v2.1 구성, 학습 = 대회 번들 split=train

- 동결 커밋: `a961cafc236791ea5d1c31a5ea0eba2dec0b3ddb` (2026-10-26 13:17:24 KST 동결, 이 커밋 이후 T24 모델·가중치·피처·임계·운영점을 바꾸지 않는다). Release `contingency-T24-a961caf`.
- **전환 근거:** 운영사무국 답변(2026-10-28 이메일, 원문 `docs/organizer_answers/2026-10-28.md`)의 "학습은 24년까지의 데이터만 활용 가능합니다".
  - 답변 전에 등록한 전환 규칙(`reports/experiments/PREREG_contingency.md` 2절·7절, 사전등록 960d76f·동결 a961caf)대로 제출 모델을 v2.1 에서 T24 로 바꿨다.
  - 전환 기록은 같은 문서 8절에 있다.
- **학습 행:** 대회 번들 `eval_pairs.csv` 의 split=train 정의를 그대로 따른다.
  - 2,310행, 기준일 2012-04-02~2024-12-30, 지점별 CS 503·DCHN 668·GJGR 458·HP 431·MGMR 250
  - 2025 홀드아웃 검증에 쓴 Final 폴드 학습 행과 같다.
  - **이 중 5행은 목표일이 2025-01-06(기준일 2024-12-30)이다.** 그 측정(HP 0·GJGR 0·CS 1,602·MGMR 626·DCHN 97 cells/mL)이 학습 타깃과, 결합 가중치·CQR 을 정한 2024 폴드 OOF 에 들어 있다.
  - 이 5행까지 뺀 엄격판 T24S 는 비상안으로 따로 동결했다(`reports/experiments/contingency_T24S/FROZEN_T24S.md`, 동결 db2b3f2). 운영사무국이 '5행도 학습 불가'라고 답할 때만 교체한다.
- **v2.1 과 같은 것:**
  - 피처 35개(선별 30 + 상류 5), 구성원 c1·c3·c2·cg, 하이퍼파라미터, 시드 42
  - 결합 가중치 c1 0.055309·c3 0.279862·c2 0.266994·cg 0.397835
  - 분류기 임계 a 0.58·b 0.87, 운영점 0.46(r=3), CQR q̂ 0.1646(2023~2024 OOF, n=531)
- **수온 임계(측정 ≤2024):** HP 26.0·GJGR 24.2·CS 23.6·MGMR 23.4·DCHN 20.8 ℃. 학습 행·2025 확인·2026 test 피처 모두 같다(코드 기본값 `FINAL_THRESHOLD_YEAR = 2024`).
- **2025·2026 측정의 쓰임:** 예측 시점의 입력(as-of 피처)으로만 쓴다. 이것은 학습이 아니다.
- **제출 파일:** `submission/submission.csv`(124행) sha256 `057afeee93c7a4213bf9176d8696fd9255617641f5c0b0aa35427a8fc1cf3f73`. v2.1 제출본(`4741a3d3…`)은 이력이다(태그 `submission-final-upload`).
- 원 동결 기록(2025 확인표·정의 정정·2026 사후 1회 결과): `reports/experiments/contingency_T24/FROZEN_T24.md`.

## 동결 파일

| name | version | sha256(model.pkl) | bytes | sha256(meta.json) | 비고 |
|---|---|---|---|---|---|
| regression | 20261026_131722 | `950dde7fbd1385019363af438a251fe49f901c09afbec7410032c033963b9152` | 19,820,569 | `b795363da2abbce48b8711d92c4492202560a7360ded24ac318f82d166e4083d` | T24-fold 회귀(c1·c3·c2·cg, 피처 35, v2.1 가중치) |
| classifier | 20261026_131722 | `496a1a75dd505e2de170461963f8a82bd1b49a3b2a29e8dc6e399e4c68dec696` | 1,584,262 | `8c2960cc8b144bdab0bd9b6bbdb69fdcf75fbf36b7cc4579ed6b1db9e5391c41` | T24-fold 분류기 b(피처 30) |
| quantile | 20261026_131722 | `9ebc0cef1c306bb5ad24eae06c643a0eb1cbb219289e023e7ebfe61e8a52defe` | 7,721,406 | `39d80086b0e15b0df6aae175b60e4b76917bf22bfab79e4a0e4ea2d37393ff2e` | T24-fold 분위 q10·q50·q90(피처 30) |

- 위 표의 meta.json 해시는 동결 당시 작업 트리 바이트(CRLF) 기준이다. 저장소 커밋에는 LF 로 들어가 다시 체크아웃하면 meta.json 해시가 달라질 수 있다. 검증(`scripts/verify_frozen.py`)은 model.pkl 해시로 한다.
- 저장소 `models/` 사본(2026-10-28 커밋 시 줄바꿈 정규화: LF·파일 끝 줄바꿈, 내용 같음)의 meta.json sha256: regression `59c9b57b3dbf35770a63a9f35949a03ffe139593a64aa1b5cbc9cd74282dba54`, classifier `b07c6b6778f18624cc14b6cfac6c608be4745a40ede71f99ced2ed0ac3b10449`, quantile `c1cc8e5485d126e0a15050d40c04484cfa6c76ba8894f1ae87d297566ef0eac7`. 운영용 Release `model-frozen-T24-a961caf`·제출 패키지 `model/` 은 이 사본을 담는다.
