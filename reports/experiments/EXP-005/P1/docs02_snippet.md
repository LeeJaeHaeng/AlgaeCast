# docs/02_DATA_SPEC.md 조각 — EXP-005 2차 P1 파생 피처(통합은 메인 세션)

새 원자료 수집은 없다(MANIFEST 추가 항목 없음). 아래는 기존 일 단위 달력(`data/interim/daily_<지점>_S1.parquet`)에서 as_of 규칙으로 만든 파생 피처와 문헌 상수다. P1 선택 설정에는 쓰이지 않았다(효과 없음). 기록용이다.

| 피처 | 원자료 열 | 정의(창 = base_date 포함 7일) | 단위 |
|---|---|---|---|
| mu_micro7 / mu_dolicho7 / mu_dom7 | wtemp, genus_obs | 속별 수온 성장률 μ(T) = 0.92·2.35^((T−T_opt)/10)(T ≤ T_opt), 최적 위는 2차 감소(35℃ 에서 0)의 7일 평균. 우점 속은 마지막 측정 | d⁻¹ |
| dil_rate7 | fac_outflow, fac_storage | 7일 평균 방류량 × 86400 / (저수량 × 10⁶) | d⁻¹ |
| net_growth7 | 위 둘 | 일별 (μ_dom − 희석률) 7일 평균 | d⁻¹ |
| si_mean7 / ss_mean7 | si, ss | 일사량·일조시간 7일 평균 | MJ m⁻² d⁻¹ / h d⁻¹ |
| wtemp_x_res | wtemp, 희석률 | 수온 7일 평균 × log10(1/희석률) | ℃·log10(일) |
| growth_pot_h | μ_dom7, 희석률, horizon_days | μ_dom7 × min(1/희석률, horizon) / ln10 | log10 |

문헌 상수(출처는 `reports/experiments/EXP-005/P1/README.md` 1절):
- T_opt: Microcystis 27.5℃(You 외 2018), Dolichospermum 25℃(Robarts·Zohary 1987; Shang 외 2025), Aphanizomenon 28℃(Mehnert 외 2010), Oscillatoria 24℃(Savadova 외 2018), 그 밖 29.2℃(Lürling 외 2013).
- Q10 2.35, μ_opt 0.92 d⁻¹: Lürling 외(2013) 남조류 평균값에서 유도.
- T_max 35℃.
