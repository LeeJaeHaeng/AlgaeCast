# 10. 제출 체크리스트 (마감 2026-11-06)

## A. 대회 필수 제출물
- [ ] **학습 모델(재현 코드)**: `submission/code.zip` — src, config, Makefile, requirements(고정 버전), models/*.pkl, registry.json, 데이터 다운로드 스크립트, README_REPRODUCE.md
- [ ] **평가 대상 예측 결과 파일**: `submission/submission.csv` — sample_submission.csv와 동일 행·순서·컬럼, 예측값 원단위 cells/mL (음수·NaN 없음)
- [ ] **방법 설명서**: `submission/방법설명서.pdf`
- [ ] 참가신청서 PDF (자필 서명 스캔) — 접수 시 업로드
- [ ] 데모 영상 (Q&A에 데모영상 문의가 있었음 → 공지/FAQ에서 형식·길이 확인 후 준비)

## B. 실격 방지 (전부 통과해야 제출)
- [ ] `tests/test_no_leakage.py` 통과 로그 첨부
- [ ] 2026 평가 조합 전체에 대해 피처 계산에 사용된 최대 obs_date ≤ base_date 임을 출력하는 스크립트 실행, 로그 첨부 (`reports/eval/leakage_audit.md`)
- [ ] 원자료부터 다시 계산하는 누수 감사(`scripts/leakage_audit.py --raw-sample 60`: 원천을 기준일로 잘라 정렬·피처를 다시 만들어 대조) 불일치 0, 음성 대조(전 기간 평균으로 되돌리면 검출) 통과
- [ ] 데이터로 계산한 상수는 as-of 또는 학습기간 자료로만: `config/derived_constants.json` 계산 자료 메타데이터 + `tests/test_derived_constants.py` 통과(FIX-v2.1, 2026-10-23)
- [ ] 제출 모델 학습은 2024년까지(대회 공식 학습 분할 split=train — 목표일 2025-01-06 인 5행 포함, 운영사무국 허용). 근거: 운영사무국 답변 2026-10-28, 10-30 공지 ⑤('eval_pairs.csv split=train 조합만'). registry current = T24(`models/FROZEN_T24.md`), `FINAL_THRESHOLD_YEAR = 2024`, 노트북의 split=train 2,310행 일치 assert 통과
- [ ] 5행(split=train 중 기준일 2024-12-30·목표일 2025-01-06) 학습 사용 — 운영사무국 이메일 답변(10-28 문의에 대한 회신) '해당 5행은 학습에 사용해도 괜찮습니다' → `PREREG_contingency.md` 8절 규칙대로 T24 유지, 엄격판 T24S 는 비상안 종료(2026 미채점). 답변 원문을 `docs/organizer_answers/` 에 기록하고, 문서의 '재확인·운영사무국 확인 중·답할 때만 교체' 문구를 이 결과로 정리. 사전등록·동결 문서는 원문을 두고 '덧붙임(2026-11-02)'만 더함
- [ ] 코드 내 실측치 룩업·하드코딩 없음 (grep "sample_submission" 이외 정답 파일 참조 없음)
- [ ] 깨끗한 venv에서 `make reproduce` → `submission.csv` diff 0
- [ ] 시드 고정, requirements 버전 고정, Python 버전 명시
- [ ] 10-30 공지 ④ — 패키지 README 4절에 실행 명령 기재: 심사 재현(추론만, 재학습 없음) 4줄을 첫 경로로(`.venv/Scripts/python scripts/verify_frozen.py` → `-m algaecast.align.run --strategy S1` → `-m algaecast.features.run --strategy S1` → `-m algaecast.models.predict --out submission_reproduced.csv`, Linux/macOS 는 `.venv/bin/python`), 노트북 전체 실행은 둘째 경로. 패키지에는 `Makefile` 이 없으므로 패키지 문서는 `make reproduce` 대신 이 4줄을 가리킴
- [ ] 공지 ④ — 추론만 4줄의 결과 `submission_reproduced.csv` 가 루트 `submission.csv` 와 바이트 동일(sha256 057afeee…), 새 venv 에서 확인
- [ ] 공지 ④ — README 에 난수 시드 42 명시: `src/config/seed.yaml`(seed: 42 — LightGBM `random_state` 는 `models.train.SEED`, 부트스트랩 등은 `algaecast.config.load_seed()`). 추론은 저장 모델·고정 가중치만 써서 난수를 쓰지 않음
- [ ] 공지 ④ — 오프라인: 설치 명령(첫 2줄)만 네트워크 사용, 추론 4줄은 네트워크 없이 실행해 바이트 동일
- [ ] 공지 ④ — 허용 오차(124행 행 단위, log10(세포수+1) 차 ≤0.05 또는 절대 차 ≤100 cells/mL, 불일치 ≤6행·2배 초과 0행) 대비: 노트북 4단계 '재학습 = 동결' 대조는 허용 오차 비교(상대·절대 1e-6, 넘으면 경고 줄만 출력), `requirements.txt` 의 `pywinpty` 에 `; sys_platform == "win32"` 표시(Linux/macOS 설치 자동 제외)
- [ ] 외부 데이터 전부 MANIFEST에 출처·라이선스·수집일시 기재(공공데이터포털 자료는 공공누리/이용허락범위 제한 없음, WAMIS 는 같은 값의 포털 #3068550·#3040409 등록분 기준(수집은 키 없는 개방 API, 회원약관 제15조④ 비회원 적용 불분명), DataON 수위 자료는 CC BY-NC-SA — 패키지의 DataON 유래 파일에 LICENSE_DataON.txt)
- [ ] DataON 원값 미포함(10-30 공지 ⑥ — 「댐유역 하천 일평균수위」 재배포 금지, 원자료 대신 가공한 계수만 동봉): 모델자료 zip 에 `data/raw/dataon/level_continuous_long.parquet`·원 배포 xlsx 가 없음(verify_package `dataon_raw_present false`), 노트북이 가공 파일(`data/processed/level_cont_features_S1.parquet`, `level_cont_mode = derived`)로 수위 피처 2열을 채워 submission.csv diff 0(sha256 057afeee…). 가공 계수 정의·기준면 오프셋·출처는 `LICENSE_DataON.txt`·`data/raw/dataon/README_GET_DATAON.md`·MANIFEST 에 기재, README_GET_WAMIS 의 예외 문구(연속 시계열의 WAMIS 연장분) 삭제. 2026-10-28 업로드본(`submission-final-T24`·`submission-final-T24v`)은 이메일 답변(2026-10-28 '결과물 data/ 포함 가능')으로 원값을 넣었으나, 10-28 답변과 10-30 공지가 달라 나중에 나온 출제기관 확인 공지를 따랐다
- [ ] WAMIS 원값도 모델자료 zip 에 넣지 않음: 수문 피처 33열 가공 파일(`data/processed/wamis_hydro_features_S1.parquet`)로 원자료 없이 submission.csv diff 0, 받는 법은 `data/raw/hydro/README_GET_WAMIS.md`(#3068550·#3040409)
- [ ] 대회 제공 데이터는 저장소에 커밋하지 않음(참가신청서 규정 3항: 승인 목적 외 이용 금지, 제3자 열람·제공·대여·판매 금지, 대회 완료 후 폐기, 성과물 출처 명시). 패키지에는 심사용으로만(`data/raw/competition/README_심사용_공개시제외.txt`) — 운영사무국 답변(2026-10-28): 결과물 data/ 에 포함 가능, 별도 컴퓨터에서 재현이 원활하도록 구성
- [ ] 10-30 공지 ⑧ — 사후 분석 코드(`eval/posthoc*.py`·`eval/live.py`·`exp/confirm_2026.py`)가 패키지 `src/` 에 없음(빌더 `SRC_SKIP_FILES`, 남은 `exp/` 는 재현(노트북·추론 4줄)에 쓰지 않는 실험 코드), 2026 사후 수치는 '블라인드 아님' 표기 유지, 2026 실측을 모델 튜닝·제출 결과 수정에 쓰지 않음

## C. 우수성 증빙 (방법 설명서에 포함)
- [ ] 베이스라인 B0~B4 비교표
- [ ] 2025 holdout 모든 지표 + 95% CI
- [ ] 10-30 공지 ①② — 공식 R² 표기: 'R²' 는 원단위 관측·예측의 피어슨 상관계수 제곱(`r2_official`·`r2_pearson_raw`)만 가리키고, 1−SSE/SST(`r2_raw`)는 'NSE' 로 표기('원단위 R²'·'결정계수'로 부르지 않음). 방법설명서·README·대시보드·발표 자료에 공식 4지표(RMSE(log)·MAE(log)·R²·NSE, 124건 통합 계산) 병기 — T24 2025 검증 0.712·0.537·0.204·0.175, 2026 사후(블라인드 아님) 0.731·0.566·0.106·0.002(`reports/eval/tbl_official_metrics.md`). 목표 R² 0.6·NSE 0.5 는 공지 ③에 따라 2026 평가 구간 124건 기준·순위 미반영으로 서술. F1 은 10,000 초과 기준 참고지표(순위 미반영)
- [ ] 결측 전략 3종 비교표
- [ ] 피처 그룹 ablation 표
- [ ] 지점별·월별 분해
- [ ] Diebold-Mariano·Wilcoxon 검정
- [ ] NIER 공식 예측 벤치마크 (동일 조합, n 명시)
- [ ] 잔차 진단 그림
- [ ] SHAP 전역·사례
- [ ] 통계분석 S1~S10 요약
- [ ] DataON 국가참조표준 데이터 사용 명시 및 기여도 · AIDA 정규격자는 계획했으나 미사용(기상은 ASOS 관측소로 대체) 명시

## D. 효과성 증빙
- [ ] 대시보드 Vercel URL (심사 기간 내 가동, Supabase 무료 티어 일시정지 방지: 주 1회 쿼리 cron)
- [ ] GitHub Actions 일일 실행 성공 기록 스크린샷
- [ ] 정책 브리프 PDF
- [ ] 데모 영상 (90~120초)

## E. 창의성 증빙
- [ ] 예보 피처 ablation (있을 때/없을 때)
- [ ] 확률 경보·설비 배치 우선순위 결과 예시
- [ ] SHAP 담당자 문장 예시

## F. 제출 직전
- [ ] 방법 설명서 수치 ↔ reports 파일 대조
- [ ] 파일명에 팀명 포함, 한글 깨짐 확인
- [ ] 제출 플랫폼 용량 제한 확인 (모델 파일 크면 다운로드 링크 + 해시)
- [ ] 11/6 18:00 이전 제출 완료, 확인 메일 저장

## G. 발표평가(11/25) 준비 — 서류 통과 시
- [ ] 발표자료 (11 문서)
- [ ] 라이브 데모 백업: 녹화 영상 + 로컬 실행본
- [ ] 예상 질문 10개 답변 (누수 검증, 결측, 벤치마크 공정성, 현업 적용 비용, 확장 로드맵)
