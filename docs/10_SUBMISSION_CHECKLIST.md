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
- [ ] 코드 내 실측치 룩업·하드코딩 없음 (grep "sample_submission" 이외 정답 파일 참조 없음)
- [ ] 깨끗한 venv에서 `make reproduce` → `submission.csv` diff 0
- [ ] 시드 고정, requirements 버전 고정, Python 버전 명시
- [ ] 외부 데이터 전부 MANIFEST에 출처·라이선스·수집일시 기재, 공공누리/이용제한 없음만 사용
- [ ] 대회 제공 데이터는 저장소에 커밋하지 않음(규정: 대회 후 폐기, 제3자 제공 금지)

## C. 우수성 증빙 (방법 설명서에 포함)
- [ ] 베이스라인 B0~B4 비교표
- [ ] 2025 holdout 모든 지표 + 95% CI
- [ ] 결측 전략 3종 비교표
- [ ] 피처 그룹 ablation 표
- [ ] 지점별·월별 분해
- [ ] Diebold-Mariano·Wilcoxon 검정
- [ ] NIER 공식 예측 벤치마크 (동일 조합, n 명시)
- [ ] 잔차 진단 그림
- [ ] SHAP 전역·사례
- [ ] 통계분석 S1~S10 요약
- [ ] DataON 국가참조표준·AIDA 데이터 사용 명시 및 기여도

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
