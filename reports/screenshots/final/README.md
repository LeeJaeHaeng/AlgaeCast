# T7-R 최종 화면 (프로덕션 https://algaecast-7.vercel.app, 2026-10-21 13:06 KST, 커밋 12c80aa)

| 파일 | 페이지 | 보기 |
|---|---|---|
| 01_main_1920x1080.png | 메인 상황판 | 쉽게 보기 |
| 02_site_2011G56_1920x1080.png | 지점 상세(강정·고령) | 쉽게 보기 |
| 03_performance_1920x1080.png | 얼마나 잘 맞혔나 | 쉽게 보기 |
| 04_insights_1920x1080.png | 녹조 이야기 | 쉽게 보기 |
| 05_about_1920x1080.png | 이 시스템은 | 쉽게 보기 |
| 06_performance_expert_1920x3600.png | 얼마나 잘 맞혔나 | 전문가 보기(전체 페이지) |

## Lighthouse (desktop preset, 프로덕션 주소)
| 페이지 | 성능 | 접근성 |
|---|---|---|
| / | 96 | 93 |
| /sites/2011G56 | 92 | 100 |
| /performance | 99 | 100 |
| /insights | 97 | 100 |
| /about | 100 | 100 |

- 금지어 검사(프로덕션 7개 경로): 0건 · 헤드라인 숫자 대조: 22/22
- POST /api/revalidate: 비밀 없이 401, 비밀 포함 {"ok":true} — board-data 캐시 태그 + /, /performance, /insights, /log, /sites/[id] 갱신. daily.yml 은 DASHBOARD_URL=https://algaecast-7.vercel.app 과 REVALIDATE_SECRET 으로 같은 엔드포인트를 호출한다.
