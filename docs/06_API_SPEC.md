# 06. API 명세 (Next.js Route Handlers + Supabase)

## 1. 아키텍처
```
[GitHub Actions 일일 파이프라인] --service_role--> [Supabase Postgres]
                                                        ▲ anon (RLS SELECT)
[Vercel: Next.js App Router] ── Server Components / Route Handlers ──┘
        │
        └── 브라우저: Recharts, Leaflet
```
- 서버 컴포넌트에서 `@supabase/ssr` 클라이언트로 직접 조회 (anon key). Route Handler는 외부 공개 JSON API 겸 캐시 계층.
- 캐시: Route Handler `revalidate = 3600`, 파이프라인 완료 시 `/api/revalidate?secret=` 호출로 무효화.
- 환경 변수(web): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `REVALIDATE_SECRET`, `NEXT_PUBLIC_MAP_TILE_URL`

## 2. 엔드포인트

### GET /api/sites
지점 목록 + 최신 예측 요약 (지도 마커용)
```json
[{"site_id":"2022G05","name":"물금·매리","basin":"낙동강","lat":35.31,"lon":128.98,
  "latest":{"base_date":"2026-10-19","target_date":"2026-10-26","q50":8200,"p_over_10k":0.41,"pred_alert_level":1,"obs_alert_level":1}}]
```
SQL: `sites` ⨝ `v_latest_predictions`(지점별 최신 base_date 1행) ⨝ `observations`(최신 alert_level)

### GET /api/sites/{site_id}/forecast?base_date=YYYY-MM-DD
지점 상세 차트용
```json
{"site":{...},
 "base_date":"2026-10-19",
 "history":[{"obs_date":"2026-08-01","cell_count":48000,"water_temp":28.1,"alert_level":2}, ...],   // 최근 180일 관측
 "forecast":{"target_date":"2026-10-26","q10":3100,"q50":8200,"q90":21000,"p_over_1k":0.93,"p_over_10k":0.41,"p_over_1m":0.0},
 "past_forecasts":[{"base_date":"2026-10-12","target_date":"2026-10-19","q50":9100,"obs_cell_count":7600}, ...], // 사후검증 20건
 "drivers":[{"feature_group":"수온","label":"수온 상승","share":0.58,"direction":"+"}, ...],   // SHAP 상위 5
 "recommendation":{"action":"deploy_remover","priority_rank":1,"rationale_ko":"..."}}
```
- `base_date` 생략 시 최신. 존재하지 않으면 404.

### GET /api/overview
대시보드 홈 KPI
```json
{"run_at":"2026-10-20T03:05:00+09:00","model_version":"lgbm-ens-v1.3",
 "sites_total":5,"sites_alert_now":2,"sites_p10k_over_50":1,
 "ranking":[{"site_id":"2022G05","name":"물금·매리","priority_score":0.41,"priority_rank":1,"action":"deploy_remover"}, ...],
 "metrics":{"holdout2025":{"R2_raw":0.63,"NSE_raw":0.55,"RMSE_log":0.49,"F1_10k":0.71}}}
```

### GET /api/metrics?split=holdout2025|cv|benchmark
`model_metrics` 테이블 그대로 (성능 페이지)

### GET /api/hydro-weather/{site_id}?days=90
수문·기상 보조 차트 (강우·유입·방류·수온)

### POST /api/revalidate?secret=
파이프라인 완료 후 호출. `revalidatePath('/')`, `revalidatePath('/sites/[id]')`

## 3. 서버 쿼리 함수 (`web/lib/queries.ts`)
| 함수 | 반환 | 비고 |
|---|---|---|
| `getSitesWithLatest()` | Site[] | 1쿼리 + 1쿼리 (predictions distinct on site_id) |
| `getSiteForecast(siteId, baseDate?)` | ForecastPayload | 4쿼리 병렬 Promise.all |
| `getOverview()` | Overview | v_latest_recommendations + model_metrics |
| `getMetrics(split)` | Metric[] | |

Supabase `distinct on` 예시:
```sql
select distinct on (site_id) * from v_latest_predictions order by site_id, base_date desc;
```

## 4. 타입 (`web/types/index.ts`)
```ts
export type AlertLevel = 0|1|2|3;
export interface Site { site_id:string; name:string; basin:string; facility_type:'weir'|'dam'; lat:number; lon:number; intake_weight:number; }
export interface Observation { obs_date:string; cell_count:number|null; water_temp:number|null; chla:number|null; alert_level:AlertLevel|null; }
export interface Forecast { base_date:string; target_date:string; q10:number; q50:number; q90:number; p_over_1k:number; p_over_10k:number; p_over_1m:number; pred_alert_level:AlertLevel; obs_cell_count?:number|null; }
export interface Driver { feature_group:string; label:string; share:number; direction:'+'|'-'; }
export interface Recommendation { site_id:string; action:string; priority_rank:number; priority_score:number; rationale_ko:string; }
```

## 5. 오류·빈 데이터 처리
- 예측이 없는 지점: `latest: null`, 지도 마커 회색
- 파이프라인 실패(최신 run status=failed): 홈 상단 배너 "최근 갱신 실패 — 마지막 성공 {run_at}"
- 모든 Route Handler는 `{error:string}` + 적절한 status

## 6. 보안
- anon key만 클라이언트 노출. service_role은 GitHub Secrets에만.
- RLS로 모든 테이블 SELECT만 허용.
- `/api/revalidate` 는 secret 비교 후 실행.
