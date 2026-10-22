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

## 일일 자동화 (T8, `.github/workflows/daily.yml`)
- 스케줄 cron `0 20 * * *`(UTC) = KST 05:00, `workflow_dispatch`(입력 dry_run). 물모아 스냅샷은 `mulmoa_snapshot.yml` 이 KST 06/09/18시에 별도 수행(단계 중복 없음).
- 단계: Release `model-frozen-v2-9dca86c`(2026-10-22 v2 동결 뒤; 그 전은 v1 `model-frozen-13ac483`, Release 유지) 다운로드 → `scripts/verify_frozen.py`(FROZEN.md·FROZEN_v2.md sha256 불일치 시 중단) → `scripts/daily_run.py`
  (공공 API 최근 120일 증분 수집 → S1 달력 → as-of 피처 → 동결 모델 예측 q50·CQR q10/q90·p_alert·tier → Supabase model_runs/predictions/shap/recommendations
  → 관측 증분 upsert → backfill_obs → live_benchmark.csv 에 pred_level·p_alert 결합 → `POST /api/revalidate`) → 로그 artifact(30일).
- as-of base_date = 오늘 이전 가장 최근 조류 측정일(지점별). 이미 predictions 에 있는 base_date 면 예측을 건너뛰고 backfill·revalidate 만 수행.
- 실패 시 `model_runs.status='failed'` 행이 기록되고 대시보드 홈 상단에 빨간 배너가 뜬다(마지막 성공 run 의 예측은 유지).
- 러너에는 대회 번들·모델 pickle 이 없다(대회 데이터는 저장소에 올리지 않음). as-of 피처 재현 검증: `reports/eval/tbl_asof_reproduction.md`
  (최근 12 base_date × 5지점 × 30피처 = 1,050값, 허용오차 |상대차| ≤1% 일치 94.6%, 완전 일치 81.9%; 불일치는 120일 창 밖 이력이 필요한 consecutive_over_1k·연속 수위 편차).
- 재학습 금지(제출 2026-11-06 전). 필요한 시크릿: DATA_GO_KR_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, REVALIDATE_SECRET (등록 완료).

### Supabase 무료 플랜 일시정지 방지
- 무료 프로젝트는 7일간 활동이 없으면 일시정지된다. 이 워크플로가 매일 REST(PostgREST) 로 읽기·쓰기(관측 upsert, model_runs insert, predictions upsert)를 수행하므로 **매일 활동이 발생해 조건을 충족**한다.
  단, 워크플로가 7일 이상 연속 실패하면 쓰기가 멈추므로 아래 알림 확인을 권장한다(실패 시에도 failed 행 insert 1건은 수행됨).

### 실패 알림 확인
- GitHub → Settings → Notifications → "Actions: Send notifications for failed workflows you didn't trigger" 가 켜져 있어야 이메일이 온다(기본 켜짐).
  확인 방법: `workflow_dispatch` 로 dry_run=true 를 한 번 실행한 뒤 Actions 탭 → 해당 run → "..." → 알림 설정에서 수신 이메일 확인. 저장소 Watch 가 "Participating and @mentions" 이상이어야 한다.
- Windows 작업 스케줄러 백업은 두지 않는다(PC 의존 불필요).

## 운영 모델 v2 동결(2026-10-22 완료)
- 최종 모델 C 를 v2 로 동결했다: 커밋 `9dca86c`, `models/FROZEN_v2.md`, Release `model-frozen-v2-9dca86c`(자산 `models-frozen-v2-9dca86c.tar.gz` — registry.json·FROZEN.md·FROZEN_v2.md, v1 회귀·v2 회귀·v1 분류기·v1 분위). `daily.yml` FROZEN_TAG 기본값을 같은 push 에서 교체했다. 절차·검증은 `reports/v2/BUILD.md`.
- 아래 절차는 제출 뒤 2026 자료까지 넣어 다시 학습하는 경우(v3)에 쓴다.

## 제출 후 재학습(v3) 절차 (실행은 2026-11-07 이후 지시로)
1. `git tag submission-2026-11-06` 로 제출 시점 고정, `models/FROZEN.md` 는 보존.
2. 데이터 갱신: `make collect align features` (2026 전 측정 포함; test 격리 로직은 그대로 두되 2026 행을 train 으로 쓰려면 `features/run.py` 의 분할 연도를 `splits.train_max_year=2026` 로 올리고 2027 을 valid 로 둠).
3. `make select` 재실행 여부 결정(피처 세트는 기본 유지), `python -m algaecast.models.tune --variant log_w --objective composite --trials 300` → `python -m algaecast.models.experiments` → `python -m algaecast.models.alert` (운영점·CQR 재산정, 조기 시즌 4~6월 가중치 실험 포함).
4. `models/registry.json` current 갱신 → `models/FROZEN_v3.md` 작성 → tarball 을 Release `model-frozen-v3-<commit>` 에 첨부 → `daily.yml` 의 `FROZEN_TAG` 변경(동결 커밋과 같은 push).
5. `scripts/verify_frozen.py` 에 FROZEN_v3.md 를 추가한 뒤 workflow_dispatch 로 검증.
6. 대시보드 소개·성능 페이지에 "v3(≤2026 학습)" 표기와 2025·2026 재평가 표 추가.

### 첫 실행 기록 (2026-10-21, run 39530775993)
- 전 단계 성공(모델 다운로드·sha256 검증 → 수집 → 예측 판단 → 관측 135행 upsert → backfill → revalidate 200). 최신 base_date(10/12~10/15)가 이미 predictions 에 있어 새 run 은 만들지 않음(설계대로 건너뜀).
- **알려진 제약**: GitHub 러너에서 WAMIS(wamis.go.kr:8080) 연결이 실패해 연속 수위(level_cont_*) 2개 피처가 결측으로 들어간다(시간 예산 240초 후 생략). 로컬 재현 검증(94.6%)과 달리 러너 예측은 이 두 피처가 NaN 인 상태의 LightGBM 예측이다. 대안: 자체 호스트 러너 또는 WAMIS 미러(차후).
- 첫 디스패치(39527640920)는 WAMIS 재시도 대기로 35분 이상 지연돼 취소 → 요청 20초·재시도 1회·예산 240초로 수정 후 재실행 성공(총 4분).

### 운영 보완 (2026-10-21, T8 승인 후)
- 연속 수위: 본댐 8개소(안동·임하·성덕·군위·김천부항·합천·밀양·대청)는 WAMIS 실패 시 K-water delist 댐수위(rwl)+오프셋으로 대체(`config/level_cont_stats.json dam_station_map`, `ASOF_LEVEL_SOURCE=auto|wamis|delist`). 최근 30 base_date 비교: 평균 |Δlog q50| 0.0004(최대 0.011), p_alert 차 0.0004, tier 일치 100%(`reports/eval/tbl_level_source_compare.md`). 방수로·조정지·하굿둑·대리는 WAMIS 전용(실패 시 결측).
- 수집 창: 올해 1/1 또는 ≥400일(`window_start`). 재검증 1,050값 일치 95.9%(≤1%), 완전 83.2%; consecutive_over_1k 100% 로 해결, 남은 불일치는 level_cont 2개(WAMIS 비본댐 관측소 수집 실패분).
- 현재 WAMIS(wamis.go.kr:8080)는 로컬에서도 연결 재설정이 잦아 delist 대체가 사실상 기본 경로다.
