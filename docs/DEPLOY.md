# 배포 (T7, 2026-10-21)

## 운영 URL
- 프로덕션: https://algaecast-7.vercel.app (Vercel 프로젝트 `algaecast-7`, 계정 jaehaeng2001-2614)
- Supabase: https://rjfjqquvzgvijvvvnrgf.supabase.co (anon 읽기 전용, RLS)

## 구성
- `web/` Next.js 15 App Router + TypeScript + Tailwind v4 + Recharts + Leaflet(OSM). Supabase 조회는 서버 컴포넌트/Route Handler 에서 anon 키로만.
- 페이지: `/`(헤드라인 KPI·지도·우선순위·지점 카드), `/sites/[id]`, `/performance`, `/insights`, `/about`
- API: `/api/sites`, `/api/sites/[id]/forecast`, `/api/overview`, `/api/metrics`, `POST /api/revalidate?secret=…`(ISR 재검증, 일일 파이프라인이 호출)
- ISR: 홈·지점 30분, 성능·인사이트 1시간. 보고서 표·그림은 `web/public/reports/`(reports/eval·eda 사본, `make deploy-assets` 로 갱신).

## 환경변수
| 이름 | 위치 | 설명 |
|---|---|---|
| NEXT_PUBLIC_SUPABASE_URL | Vercel env(plain), web/.env.local | Supabase URL |
| NEXT_PUBLIC_SUPABASE_ANON_KEY | Vercel env(plain), web/.env.local | anon 키(읽기 전용) |
| REVALIDATE_SECRET | Vercel env(encrypted), web/.env.local, .env | 재검증 엔드포인트 비밀 |
| VERCEL_TOKEN | .env 만 | CLI 배포 토큰 (커밋 금지) |

Vercel env 는 REST API(`POST /v10/projects/{id}/env?upsert=true`)로 등록했다(CLI `env add` 가 stdin 파이프에서 오동작).

## 절차 (재배포)
```bash
cd web
npm ci
npm run build                 # 경고 0 확인
npx vercel --prod --yes --token "$VERCEL_TOKEN"
```
- 프로젝트 링크 정보는 `web/.vercel/project.json`(gitignore). 새 환경에서는 `npx vercel link --yes --project algaecast-7` 먼저.
- 로컬 검증: `npm run start -- -p 3100` 후 `/`, `/sites/2022G05`, `/performance`, `/insights`, `/about`, `/api/overview` 200 확인.
- 재검증 호출: `curl -X POST "https://algaecast-7.vercel.app/api/revalidate?secret=$REVALIDATE_SECRET"` (T8 daily 워크플로 마지막 단계).

## 검증 기록 (2026-10-21)
- `npm run build` 경고 0, 라우트 11개 생성. 로컬·프로덕션 전 페이지 200.
- 스크린샷: `reports/screenshots/{home,site,performance,insights,about}.png` (headless Edge, 1400×1800).
