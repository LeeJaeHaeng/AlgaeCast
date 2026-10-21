# T7-R DoD 점검 (docs/12 §10) — 2026-10-21, 브랜치 ui-control-room

| 항목 | 결과 | 근거 |
|---|---|---|
| 메인 상황판 1920×1080 스크롤 없음 | 통과 | `main_1920x1080.png` (board = 100dvh 고정, ≥1600×900 에서만) |
| 쉽게 보기 금지어 0개 | 통과 | `web/scripts/check_copy.mjs` 7개 경로(/, 지점 2, 성능, 이야기, 시스템, /log) 합계 0건 → `banned_words_check.md` |
| 모든 수치에 단위·기준 | 통과 | 개/mL·%·℃·mm·일, 기준일/측정일/목표일 규칙(targetLabel), 출처 줄 |
| 공식 발령 vs AI 예상 구분 | 통과 | 타일 칩·지점 상세 머리·지도 테두리·상황 기록 "공식 발령 ○○" + 조합 라벨(docs/12 §8.4) |
| 순환·전체화면·자동 갱신·발표 모드 | 통과 | TopBar: ?kiosk=1 30초 순환(GIF), requestFullscreen, 5분 router.refresh + 60초 데이터 캐시, data-theme=light 기억 |
| 비전문가 Q1~Q5 | 1차 통과(사용자 확인 대기) | `plain_language_check.md` |
| 스크린샷 3해상도 × 5페이지 + 순환 GIF | 통과 | `{main,site,performance,insights,about}_{1920x1080,1366x768,390x844}.png`, `performance_expert_1920x1080.png`, `kiosk_rotation.gif` |
| Lighthouse 성능·접근성 ≥ 90 | 통과 | `lighthouse.md` (최저: 메인 접근성 93, 지점 상세 성능 91) |
| 헤드라인 숫자 대조 | 통과 | `web/scripts/check_numbers.mjs` 22/22 일치 (prebuild) |
| npm run build 경고 0 | 통과 | `✓ Compiled successfully`, 경고 없음 |
| Vercel 프로덕션 반영 | 대기 | main 머지 승인 후 배포 |
