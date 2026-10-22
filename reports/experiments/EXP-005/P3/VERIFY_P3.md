# EXP-005 2차 P3 독립 검증 — 기상청 단기예보 격자 과거 발표분 피처

**종합 결론: 문제 없음.** 7개 항목이 모두 통과했다. 판정 'P3 미통과 → 최종 모델 C'를 캐시 재계산으로 그대로 확인했다. 중대한 문제는 0건이고, 판정에 영향 없는 경미한 문서 누락이 1건 있다.

- 검증 일시: 2026-10-22 (KST)
- 대상
  - 사전등록 [`PREREG_P3.md`](PREREG_P3.md)(커밋 f61eee7), 결과 [`RESULT.md`](RESULT.md)·`result.json`(미커밋)
  - 원자료 `data/raw/kma_fcst_grid/{calls.jsonl, fcst_long.parquet, plan.json, collect.log}`
  - 피처 캐시 `data/processed/exp/EXP-005b/p3_grid_features.parquet`
  - 예측 캐시 `data/processed/exp/EXP-005b/cache/{FINAL_C,P3F_T,P3F_T_K}_{1001..5005}`, `P3G_{T,TS,TSR}[_K]_{11..55}`, `C_{11..55}`
- 지킨 제약
  - 네트워크 호출과 모형 재학습을 하지 않았다. 판정은 캐시로만 다시 계산했다.
  - 2026 정답 파일(`test_targets_DO_NOT_USE.parquet`)은 열지 않았다.
  - git 추적 파일은 고치지 않았다. 이 파일만 새로 썼다.
- 독립성
  - 피처는 `r2nd_p3_kmafcst`를 쓰지 않고 `calls.jsonl`을 직접 읽어 다시 계산했다.
  - 지표는 `harness2.metric_row2`·`metrics.compute_all`을 쓰지 않고 numpy로 직접 계산했다.
  - 정답·행 순서는 `harness.load_base()`에서 가져왔다.

## 항목별 판정

| # | 항목 | 판정 | 근거 수치 |
|---|---|---|---|
| 1 | 누수(사용 발표시각) | 통과 | **사용 발표시각 = 기준일 05:00 − `p3_fc_issue_lag_h`**<br>• 대상: `available=1`인 2,337행<br>• 기준일 05:00보다 늦음(issued_at > 05:00): **0행**<br>• 24시간보다 오래됨: **0행**<br>• 지연: 0h 2,332행, 6h 5행(기준일 2021-02-22, 전날 23시 발표 × 5지점). 최대 6h<br><br>**`fcst_long` 대조**<br>• 사용 발표시각 ≠ 해당 지점 `fcst_long`에서 cutoff 이하 가장 늦은 발표: **0행**<br>• 사용 발표시각이 `fcst_long`에 없음: 0행<br>• `plan.json` 선택 발표시각(634개 기준일, 05:00보다 늦은 것 0)과 다름: 0행<br><br>**`available=0`인 225행**<br>• 구성: 2012~2015년 194행 + PROBE의 8개 기준일 31행<br>• 24시간 안 발표분이 `fcst_long`에 있는데도 결측 처리된 행: 0행<br>• `fcst_long`에서 fcst_at < issued_at인 행: 0행 |
| 2 | 피처 재계산 | 통과 | **표본 200행**(`default_rng(7)`로 비복원 추출) × 15열 = 3,000셀, 값 있는 셀 1,755개<br>• NaN 위치 불일치 0<br>• \|차\| > 1e-9 0, 최대 \|차\| 0<br><br>**전 2,562행**(38,430셀, 값 21,699개)<br>• 불일치 0<br>• `issue_lag_h`·`available` 불일치 0<br><br>**직접 구현한 규칙**<br>• 상태는 레코드의 `land_valid`·`land_zero`로 다시 판정했다. 저장된 status와 불일치 0<br>• TMX·TMN·SKY는 ok만 쓴다. POP·PCP는 같은 (발표, 발효)의 SKY가 ok일 때만 쓴다<br>• R06은 전국 0을 허용하고, fcst_at = 끝 − 6h로 둔다<br>• 값 ≤ −90은 결측<br>• 구형 R06 4구간은 하나라도 없으면 결측, 신형 PCP 3시각 평균×24도 하나라도 없으면 결측<br>• 버린 레코드: TMX 0채움 3, TMX·TMN 결측 각 94, POP·SKY·PCP 0채움 각 561 |
| 3 | 0채움 처리 | 통과 | **2021-06-30 이전 발표분**<br>• 이 발표분을 쓴 1,160행 중 POP·SKY 값이 들어간 행: **0**<br>• 원자료에 그 시기 POP·SKY 레코드 자체가 0건이다<br><br>**신형 발표분의 +3일 SKY**<br>• 0채움(3시각 모두): 792행(기준일 2021-11-29~2024-11-25), 미수집(d3 시작 전): 108행<br>• 이 900행에서 `pop_max_d3`·`sky_mean_d3` 값이 있는 행: **0**<br>• +3일 SKY 정상은 기준일 2024-12-02부터 277행이고, 이 중 결측 행은 0<br><br>**+1·+2일**<br>• SKY 정상 시각이 하나도 없는데 POP·SKY 값이 있는 경우: 0<br>• 3시각 중 일부만 있는 경우: 0 |
| 4 | 판정 수치 재계산 | 통과 | **시드별 지표**(FINAL_C·P3F_T·P3F_T_K × 5시드 = 15개)<br>• 대상: CV r2_raw·2025 r2_raw·rmse_log·F1@10k·9~10월 rmse_log<br>• result.json `rows`와 최대 \|차\| **0.0**<br>• 행 수: CV 1,278, 2025 252, 9~10월 61<br>• 캐시 키·정답과 `load_base()`의 불일치 파일: 0<br><br>**rmse_log 정의**: log10(x+1)(`metrics.LOG_OFFSET = 1.0`, `log10p`)<br><br>**기준별 재계산**(문턱, 판정)<br>• a1: **−0.002285**(≥ +0.08, 미충족)<br>• a2: 하한 **−0.011174**, 구간 [−0.011174, +0.003911], 중앙 −0.002354. 블록 25개, 2,000회, `default_rng(20261022)`로 직접 구현(미충족)<br>• a3: **+0.005971**(≥ +0.04, 미충족)<br>• b1: **0.144671**(< 0.147381 = C 0.167381 − 0.02, 미충족)<br>• b2: 0.701553(≤ 0.721703, 충족)<br>• b3: 0.738839(≥ 0.674184, 충족)<br>• c: 0.369375(≤ 0.372585, 충족)<br>• 모두 result.json과 차 0이고 충족 여부도 같다<br>• b4: 15개 캐시의 q90이 전부 NaN이다. 따라서 세 구성 모두 같은 v1 동결 q90을 쓰고, 값은 18이다<br><br>**탐색**(시드 11~55)<br>• ΔCV: T −0.004814, TSR −0.021072, TS −0.026644(json과 같음)<br>• 대조군 대비: T +0.002503, TS +0.009877, TSR +0.019569<br>• 최대는 T다. 2위와 차가 0.0163(≥ 0.002)이라 동률 규칙이 적용되지 않는다 → **T 선택이 맞다**<br><br>**대조군 K**<br>• 10개 시드(판정 5 + 탐색 5) 모두에서 `harness2.noise_like(T 6열, s)`가 직접 생성한 `default_rng([20261022, s, 6]).standard_normal` + T 결측 위치와 완전히 같다<br>• 결측 위치는 T와 같다(결측 비율 0.2528)<br>• `judge()`는 `builders → H2.noise_like(frame, s)`를 판정 시드 s로 호출한다 |
| 5 | 2026 미사용 | 통과 | **파일별 2026 행**<br>• `p3_grid_features.parquet`: base_date ≥ 2026 0행(최대 2025-12-22)<br>• P3G·P3F·FINAL_C·C 캐시 50개: base_date ≥ 2026 0행, target_date ≥ 2026 0행(최대 base 2025-12-22, target 2025-12-29)<br>• `fcst_long`: 2026 발표분 0, fcst_at ≥ 2026 0(최대 issued 2025-12-22 05시)<br>• `calls.jsonl`: tmfc·tmef ≥ 2026 0건<br>• `plan.json`: 2026 기준일 0<br><br>**테스트**: `pytest tests/test_no_2026_targets_outside_live.py` **5 passed**(종료 코드 0) |
| 6 | 순서 | 통과 | **시각 순서**(모두 2026-10-22 KST)<br>• PREREG 커밋 f61eee7: `git log -1 --format=%ci` = **15:58:34 +0900**<br>• P3G_·P3F_ 캐시 40개 수정 시각: **16:08:01 ~ 16:22:05**(모두 커밋 이후)<br>• 피처 캐시: 16:07:41<br>• `fcst_long`: 16:06:59(수집은 PREREG가 허용한 '같은 날 진행 중')<br>• RESULT·result.json: 16:22:05<br><br>**코드·문서 변경 여부**<br>• f61eee7 이후 PREREG_P3.md·`r2nd_p3_kmafcst.py`·`r2nd_p3_run.py`·`kma_fcst_grid_hist.py`·`harness2.py`를 바꾼 커밋이 없다<br>• 작업 트리 diff도 없다 |
| 7 | 키 비노출 | 통과 | `.env`의 `KMA_APIHUB_KEY`(22자, 값은 출력하지 않음)를 셌다. 원문과 URL 인코딩이 같아 한 형태만 센다<br><br>**발견 0건인 곳**<br>• `calls.jsonl`·`collect.log`·`plan.json`·`fcst_long.parquet`(피처 캐시 포함)<br>• `reports/experiments/EXP-005/P3/` 아래 11개 파일 전부(미커밋 RESULT·result.json 포함)<br>• git 추적 파일 전체: `git grep -F` 작업 트리·`--cached`<br>• git 전체 이력 79개 커밋<br>• 이 검증 작업 폴더<br><br>**잘린 노출 탐지**: 앞 12자로도 다시 셌다. 위 대상 모두 0건<br><br>`.env`는 git이 추적하지 않는다 |
| (d) | P3 누수 테스트·전체 pytest | 통과 | `tests/test_exp_r2nd_p3_kmafcst.py` **33 passed**. 전체 pytest는 아래 '참고 4' |

## 발견한 문제

### 중대 — 없음

### 경미 1 — +3일 POP·SKY·강수량 결측 구조가 문서에 없음(판정 영향 없음)

**내용**
- 05시 발표분의 +3일 SKY는 기준일 2021-11-29~2024-11-25 동안 전국 0채움이다. 같은 시기 +3일 기온(TMX·TMN)은 값이 있다.
- 규칙대로 같은 시각의 POP·PCP도 버려진다. 그래서 `pop_max_d3`·`sky_mean_d3`·`rn_day_d3`는 기준일 2024-12-02부터만 값이 있다.
- 값 비율은 학습 구간(≤ 2024) 1.1%, CV 2020~2024 `rn_day_d3` 2.0%, 2025 100%다.
- 처리 자체는 사전등록 규칙(0채움 SKY 버림, POP·PCP는 SKY 정상일 때만)과 맞다. 다만 PREREG 2절·PROBE_GRID·RESULT 어디에도 이 구조가 적혀 있지 않다. 문서에는 "+3일은 2021-11-29부터"(TMX 기준)만 있다.

**영향**
- 선택·판정 묶음 T(기온 6열)에는 영향이 없다.
- TS·TSR 탐색 결과는 학습과 2025의 d3 결측 분포가 다른 상태에서 나온 값이다. 이 점을 함께 적어 두는 편이 좋다.

**재현**
```python
import pandas as pd
F = pd.read_parquet("data/processed/exp/EXP-005b/p3_grid_features.parquet")
a = F[(F.p3_fc_available == 1) & (F.base_date >= "2021-06-30")]
z = a[a.p3_fc_ta_max_d3.notna() & a.p3_fc_sky_mean_d3.isna()]
print(z.base_date.min(), z.base_date.max(), len(z))            # 2021-11-29 2024-11-25 792
print(a.loc[a.p3_fc_sky_mean_d3.notna(), "base_date"].min())    # 2024-12-02
```
원자료 쪽 근거: `calls.jsonl`에서 (사용 발표분, 기준일+3일 09·15·21시, SKY) 레코드의 `land_zero == 1.0`이다(792행 모두 3시각 0채움).

## 참고(문제 아님)

1. **24시간 경계**
   - 코드(`forecast_features`)는 `issued ≥ cutoff − 24h`, 즉 경계를 포함한다. 전날 05시 발표분도 허용된다.
   - PREREG 본문은 그 예로 02·23·20·17시만 든다.
   - 실제 사용 지연은 최대 6h라 결과에 영향이 없다.
2. **K 예측 캐시와 난수의 연결**
   - K 예측 캐시가 이 난수로 학습된 것인지는 재학습 금지라 직접 재현할 수 없다.
   - 코드 경로와 난수 생성 재현(10개 시드 완전 일치)으로 확인했다.
3. **기준 모델 캐시**
   - FINAL_C·C 캐시(수정 14:07, PREREG 이전)는 P3와 무관한 기준 모델 C를 재사용한 것이다.
   - 이전 최종 판정 `reports/experiments/EXP-005/FINAL/results.json`의 C 시드 행과 지표 차가 0이다.
4. **전체 pytest**: 메인 세션이 PREREG 커밋(f61eee7) 코드로 실행한 전체 pytest 는 456 passed(종료 코드 0, 16:03)다. 검증 시점 작업 트리에는 P3와 무관한 미커밋 변경이 함께 있었다(v2 동결 관련 `posthoc.py`·`freeze_v2.py`·`registry.json` 등).
5. **원자료 정리 상태**
   - `calls.jsonl`의 오류 1건(2022091905→2022092215 PCP, HTTP 없음)은 같은 키로 다시 호출해 받은 레코드로 대체됐다.
   - 내용이 다른 중복 키는 0이다.
6. **R06 '전국 0 허용' 규칙의 타당성**
   - 월별 전국 0 비율은 7월 0.19 ~ 10월 0.61이다.
   - 8구간이 모두 전국 0인 발표분은 21/346이고, 7·8월에는 0건이다.
   - 따라서 실제 무강수로 보는 것이 타당하다.

## 재현 방법

검증 스크립트는 세션 임시 폴더(`scratchpad/verify_p3/`)에 있다. 저장소 루트에서 아래처럼 실행한다.
```
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 .venv/Scripts/python.exe <스크립트> < /dev/null
```

| 스크립트 | 항목 | 하는 일 |
|---|---|---|
| `v1_leak.py` | 1 | 사용 발표시각과 `fcst_long` 지점별 최신 발표·`plan.json`을 대조한다 |
| `v2_recompute.py` | 2·3 | `calls.jsonl`을 직접 해석해 15열을 다시 계산한다(표본 시드 7·전체). 0채움 위반을 센다 |
| `v4_metrics.py` | 4 | 캐시 예측과 `load_base()`로 지표·기준·부트스트랩·탐색 선택·대조군 난수를 확인한다 |
| `v4b_cref.py` | 4 | C 행을 이전 최종 판정과 대조한다 |
| `v5_no2026.py` + `pytest tests/test_no_2026_targets_outside_live.py` | 5 | 2026 행이 없는지 확인한다 |
| `git log -1 --format=%ci f61eee7`, `ls --time-style=full-iso …/cache/P3*` | 6 | 커밋 시각과 캐시 수정 시각을 비교한다 |
| `v7_keys.py` | 7 | 키 등장 개수만 센다. 값은 출력하지 않는다 |
| `pytest tests/test_exp_r2nd_p3_kmafcst.py` | (d) | P3 누수 테스트를 실행한다 |
