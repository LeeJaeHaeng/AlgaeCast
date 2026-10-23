# 모델 동결 S (FROZEN_S) — 비상용: 기준일 전날까지 자료만(as_of = base_date − 1일)

- 근거: `reports/experiments/PREREG_contingency.md`(사전등록 커밋 4b48e51, 학습 전 push). S 모델은 **제출 패키지에 넣지 않는다.** 2절 전환 규칙(운영사무국이 '기준일 당일 측정값 사용 불가'로 답한 경우)에서만 제출 모델로 교체한다.
- 동결 시각(KST): 2026-10-23 16:51:27. 이 문서를 담은 커밋이 S 동결 커밋이다. 2026 사후 계산은 이 커밋 뒤에만 1회 한다.
- 정의: v2.1 과 학습 표본(2,562행)·피처 35개·하이퍼파라미터·구성원(c1·c3·c2·cg)·결합(log10 NNLS)·최종 학습 범위(≤2025)·시드 42·분류기·분위 재적합·임계(CV OOF F1 최대)·운영점(r=3)·CQR(2023~2024 OOF)·폴드별 수온 임계가 모두 같다. 바꾼 것은 `config/features.yaml` 의 `as_of_offset_days: 1` 하나다(자료 피처·상류 피처의 as_of = 기준일 전날, 달력·지점 피처는 기준일). 피처 파일 `features_S1_asofm1.parquet`.
- 실행: 저장소 사본(로컬 작업 폴더)에서 오프셋 1 로 `features.run --strategy S1` → `models.alert --skip-tune` → `scripts/freeze_v21.py --oof` → `eval.transitions` → `scripts/freeze_v21.py --freeze --force`(사본 안). 운영점·CQR·분류기 임계는 분류기·분위 OOF 로만 정해지므로 `--oof` 와 `transitions` 의 순서와 무관하다. 저장소의 v2.1 모델·레지스트리·피처·OOF 캐시·config 는 건드리지 않았다.
- 오프셋 0 확인: 같은 코드에서 `as_of_offset_days: 0` 이면 `features_S1.parquet`(2,979행×109열)와 `submission.csv`(sha256 `4741a3d3…`)가 v2.1 과 바이트 단위로 같다(2026-10-23 16:44).

## 동결 파일 (사본 `models/`, sha256 of model.pkl)

| name | version | sha256 | bytes | 비고 |
|---|---|---|---|---|
| regression | 20261023_165126 | `bcca5bcd35dcab7397bcea1e1fb0b5e4fafb5c95376d213c8f99b97c230ec86d` | 20,510,446 | S(c1·c3·c2·cg, 피처 35) — current |
| classifier | 20261023_165046 | `f4930e23496447b5aebbc6b640215906de371cb4b4ec5589792fddda6f0a867c` | 1,699,522 | 분류기 b(S 피처) |
| quantile | 20261023_165048 | `1ccbe932efeda4072639b432f7fef64c5ceffbfc1dc2c26330d92788183f16cf` | 7,990,681 | q10·q50·q90(S 피처) |
| regression | 20261023_165046 | `7f7fcc0dac74cb319d5d22814bc148d4451fb7d013829ee14aa11b91bba80e4d` | 2,576,887 | v1 구성(S 피처) — 참고, current 아님. 앙상블 채택 규칙(CV rmse_log 0.002 이상 개선)을 넘지 못해 단일 C1 |

- 결합 가중치(2020~2024 연도 확장 CV OOF, 시드 42): c1 0.2573 · c3 0.1992 · c2 0.1445 · cg 0.3990 (v2.1: 0.0553 · 0.2799 · 0.2670 · 0.3978)
- 분류기 임계(CV OOF F1 최대): a 0.60 · b 0.58 (v2.1: 0.58 · 0.87). 운영점(r=3): 0.58 (v2.1 0.46). CQR q̂(2023~2024, n=531): 0.198 (v2.1 0.165)
- submission_S.csv(124행) sha256 `e4a2375e688714ecb11be4fbad9025f3b188758506ee2692489ca48695b9663b`(v2.1 대비 |Δlog10| 중앙 0.168·최대 1.416)
- 보관: 사본 작업 폴더(로컬)와 비공개 저장소 GitHub Release `contingency-S-<동결 커밋>`(모델 묶음·submission_S.csv). 제출 패키지에는 넣지 않는다.

## 동결 전 지표(CV·2025, 2026 미사용)

| 지표 | S | v2.1 |
|---|---|---|
| 2025 같은 252행 rmse_log | 0.7573 | 0.7120 |
| 2025 r2_log | 0.7492 | 0.7783 |
| 2025 r2_raw | 0.1047 | 0.1754 |
| 2025 F1@10k | 0.5316 | 0.7045 |
| CV 2020~2024 폴드 평균 rmse_log | 0.8512 | 0.7917 |
| CV r2_log | 0.6395 | 0.6888 |
| CV r2_raw | 0.1413 | 0.2486 |
| CV F1@10k | 0.3549 | 0.5977 |
| 2020~2025 경계 사건 20건 감시(q90 ≥ 1만) 포착·중앙 리드(E) | 16건·14일 | 17건·14일 |
