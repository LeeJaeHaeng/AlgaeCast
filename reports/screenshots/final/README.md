# 최종 화면 (프로덕션 https://algaecast-7.vercel.app, 2026-10-23 12:42 KST, 웹 커밋 387acfa)

2026-10-23 12시: 제출·운영 모델을 v2.1(데이터 유래 상수 누수 수정판, models/FROZEN_v2.1.md)로 바꾼 화면으로 다시 찍었다. 헤드라인은 28건 중 24건·2026년 8건 중 7건(2025년까지 자료로만 만든 v2.1, 블라인드 아님), 운영점 46%, 녹조 이야기 수온 기준은 ≤2025 측정 값이다. 이전 판: 2026-10-23 10:08(커밋 0f48ec8, v2 예상값 하나로 통일), 처음 판 2026-10-21 13:06(커밋 12c80aa).

| 파일 | 페이지 | 보기 |
|---|---|---|
| 01_main_1920x1080.png | 메인 상황판 | 쉽게 보기 |
| 02_site_2011G56_1920x1080.png | 지점 상세(강정·고령) | 쉽게 보기 |
| 03_performance_1920x1080.png | 얼마나 잘 맞혔나 | 쉽게 보기 |
| 04_insights_1920x1080.png | 녹조 이야기 | 쉽게 보기 |
| 05_about_1920x1080.png | 이 시스템은 | 쉽게 보기 |
| 06_performance_expert_1920x3600.png | 얼마나 잘 맞혔나 | 전문가 보기(전체 페이지) |

## Lighthouse (desktop preset, 프로덕션 주소 — 2026-10-21 측정)
| 페이지 | 성능 | 접근성 |
|---|---|---|
| / | 96 | 93 |
| /sites/2011G56 | 92 | 100 |
| /performance | 99 | 100 |
| /insights | 97 | 100 |
| /about | 100 | 100 |

- 금지어 검사(프로덕션 10개 경로, 2026-10-23 12:42): 0건 · 배포 숫자 대조(check_deployed_numbers): 63/63 · 빌드 전 숫자 대조(check_numbers): 178/178
- POST /api/revalidate: 비밀 없이 401, 비밀 포함 {"ok":true} — board-data 캐시 태그 + /, /performance, /insights, /log, /sites/[id] 갱신. daily.yml 은 DASHBOARD_URL=https://algaecast-7.vercel.app 과 REVALIDATE_SECRET 으로 같은 엔드포인트를 호출한다.
