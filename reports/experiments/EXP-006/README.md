# EXP-006 (R3) 속별 모델 합산

상태: **completed** · 착수 2026-10-21 17:53 · 마지막 실행 18:14~18:15 (KST) · 소요 0.36h / 상한 8h

## 1. 목적·설정

- 목적: 합계 세포수 대신 4속(Microcystis, Dolichospermum(Anabaena), Aphanizomenon, Oscillatoria)을 따로 log 회귀(C1 설정)한 뒤
  원단위로 합산하면 원단위 R²·NSE 가 오르는지, 또 속별 합산을 v1 앙상블(NNLS)의 4번째 구성원으로 넣으면 나아지는지 본다.
- 표본: `harness.load_base()` v1 학습·검증 2,566행(≤2025). CV = 2020~2024 연도 확장 OOF, 2025 = ≤2024 학습 → 2025.
- 하이퍼파라미터: v1 C1(`harness.v1_specs()['c1']`, log_w, α=0.0590) 그대로, 시드 42 하나. 분위(q90)는 v1 그대로 → 리드타임 동일.
- 속별 타깃 출처: 조류경보제 API 원자료 `data/raw/nier_algae/nier_algae_2012_2026.parquet`(v1 타깃과 같은 출처)에서
  v1 표본의 `target_date` 와 같은 날 측정의 `iem_bgalage_microsts`·`iem_bgalage_anba`·`iem_bgalage_apzo`·`iem_bgalage_osrtria`.
  2025-12-31 이후 측정은 읽은 즉시 버렸다.
- 출처 대조(대회 `algae_measure.csv`, 같은 열 이름): 아래 표처럼 2025-12-31 까지 공통 측정일의 총합·4속 값이 모두 일치 → API 원자료를 쓴다(내용 동일, v1 파이프라인과 같은 파일).

| 열 | 공통 측정일 | API에만 | 대회에만 | 둘 다 값 | 일치 | 한쪽만 결측 | 비고 |
|---|---|---|---|---|---|---|---|
| iem_bgalage_cell_co | 2718 | 0 | 0 | 2583 | 2583 | 0 |  |
| iem_bgalage_microsts | 2718 | 0 | 0 | 2478 | 2478 | 0 |  |
| iem_bgalage_anba | 2718 | 0 | 0 | 2478 | 2478 | 0 |  |
| iem_bgalage_apzo | 2718 | 0 | 0 | 2478 | 2478 | 0 |  |
| iem_bgalage_osrtria | 2718 | 0 | 0 | 2478 | 2478 | 0 |  |

- 합계 일치 점검(4속 합 = v1 타깃, |차| ≤ 0.5):

| 지점 | 표본 | 4속 있음 | 합계 일치 | 합계 불일치 | 4속 결측 | 결측 연도 | 총합=v1 타깃 |
|---|---|---|---|---|---|---|---|
| CS | 554 | 553 | 553 | 0 | 1 | 2025 | 553 |
| DCHN | 725 | 619 | 619 | 0 | 106 | 2012,2013,2014,2025 | 724 |
| GJGR | 513 | 513 | 513 | 0 | 0 | – | 513 |
| HP | 476 | 475 | 475 | 0 | 1 | 2025 | 475 |
| MGMR | 298 | 297 | 297 | 0 | 1 | 2025 | 297 |

  4속 결측 행은 회남 2012~2014(그 시기 원자료에 속별 값 없음)와 기준일 2025-12-29 의 정답 측정일이 2026-01-05 인 4행(2026 측정은 읽지 않음)이다.
  결측 행은 속별 모델 학습에서만 빠지고(2025 행은 어차피 학습에 쓰이지 않음) 예측·평가는 모든 행에 한다. 합계 불일치 행은 없다.
- 속별 비율(세포수 합 기준, 집계):

| 구간 | n | Microcystis | Dolichospermum(Anabaena) | Aphanizomenon | Oscillatoria |
|---|---|---|---|---|---|
| 2016~2024 학습 구간 | 2205 | 0.842 | 0.050 | 0.087 | 0.021 |
| 2025 | 252 | 0.947 | 0.016 | 0.025 | 0.012 |
| 표본 >10k(≤2024) | 202 | 0.875 | 0.044 | 0.066 | 0.015 |

- 변형
  - 부분 모델: 4속 각각(G4) 또는 Microcystis + 나머지 3속 합(G2). 방식 log(C1 회귀) 또는 hurdle(출현 P(y>0) 분류 × 양수 행 log 회귀, 0 이 많은 속 대비).
    '속별 선택' 은 부분마다 log/hurdle 중 CV(2020~2024) 원단위 MSE 가 작은 쪽.
  - 역변환: 속별 Duan smearing(smear) 또는 보정 없음(none). 원단위로 합산.
  - 속별 자기회귀 피처(+속별피처, as_of 규칙): 속별 최근 측정 log10(y+1), 최근 28일 최대 log, Microcystis 비율(최근 4속 측정). 속별 모델에만 추가.
  - 앙상블: `harness.ensemble_expanding(names=(c1, c3, c2, cg))`(4번째 구성원) 또는 c1 을 cg 로 대체(cg, c3, c2).
  - 참고 행(선택 대상 아님): C1 합계 단독, v1 3구성원에 속별 피처만 더한 구성(분해 없이 피처만의 효과).
- 속별 선택 결과(부분별 log/hurdle, CV 원단위 MSE):
- 피처 v1·smear: Microcystis=log, Dolichospermum(Anabaena)=hurdle, Aphanizomenon=hurdle, Oscillatoria=hurdle, 나머지 3속(Anabaena+Aphanizomenon+Oscillatoria)=log
- 피처 v1·none: Microcystis=log, Dolichospermum(Anabaena)=hurdle, Aphanizomenon=hurdle, Oscillatoria=hurdle, 나머지 3속(Anabaena+Aphanizomenon+Oscillatoria)=hurdle
- 피처 +속별·smear: Microcystis=log, Dolichospermum(Anabaena)=hurdle, Aphanizomenon=hurdle, Oscillatoria=hurdle, 나머지 3속(Anabaena+Aphanizomenon+Oscillatoria)=hurdle
- 피처 +속별·none: Microcystis=log, Dolichospermum(Anabaena)=hurdle, Aphanizomenon=hurdle, Oscillatoria=hurdle, 나머지 3속(Anabaena+Aphanizomenon+Oscillatoria)=hurdle

## 2. 표준 표

| 구성 | 구간 | n | r2_raw | r2_pearson_raw | nse_raw | rmse_log | r2_log | F1@10k | 리드타임 포착(q90≥10k) |
|---|---|---|---|---|---|---|---|---|---|
| v1 기준 | CV 2020~2024 | 1278 | 0.173 | 0.319 | 0.173 | 0.805 | 0.706 | 0.599 | 18/20 |
| v1 기준 | 2025 | 256 | 0.166 | 0.194 | 0.166 | 0.708 | 0.780 | 0.682 | 〃 |
| 참고: C1 합계 단독(smearing) | CV 2020~2024 | 1278 | 0.306 | 0.410 | 0.306 | 0.818 | 0.696 | 0.731 | 18/20 |
| 참고: C1 합계 단독(smearing) | 2025 | 256 | 0.109 | 0.191 | 0.109 | 0.713 | 0.777 | 0.682 | 〃 |
| G4 4속 log smear 단독 | CV 2020~2024 | 1278 | 0.299 | 0.380 | 0.299 | 0.811 | 0.701 | 0.712 | 18/20 |
| G4 4속 log smear 단독 | 2025 | 256 | 0.159 | 0.212 | 0.159 | 0.764 | 0.744 | 0.713 | 〃 |
| G4 4속 log none 단독 | CV 2020~2024 | 1278 | 0.202 | 0.382 | 0.202 | 0.836 | 0.683 | 0.633 | 18/20 |
| G4 4속 log none 단독 | 2025 | 256 | 0.171 | 0.212 | 0.171 | 0.803 | 0.717 | 0.597 | 〃 |
| G4 4속 hurdle smear 단독 | CV 2020~2024 | 1278 | 0.189 | 0.348 | 0.189 | 0.887 | 0.643 | 0.694 | 18/20 |
| G4 4속 hurdle smear 단독 | 2025 | 256 | 0.168 | 0.201 | 0.168 | 0.805 | 0.716 | 0.659 | 〃 |
| G4 4속 hurdle none 단독 | CV 2020~2024 | 1278 | 0.151 | 0.350 | 0.151 | 0.861 | 0.664 | 0.564 | 18/20 |
| G4 4속 hurdle none 단독 | 2025 | 256 | 0.166 | 0.201 | 0.166 | 0.797 | 0.721 | 0.608 | 〃 |
| G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear 단독 | CV 2020~2024 | 1278 | 0.302 | 0.382 | 0.302 | 0.865 | 0.661 | 0.717 | 18/20 |
| G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear 단독 | 2025 | 256 | 0.160 | 0.214 | 0.160 | 0.799 | 0.720 | 0.705 | 〃 |
| G2 Microcystis+나머지 log smear 단독 | CV 2020~2024 | 1278 | 0.303 | 0.381 | 0.303 | 0.810 | 0.702 | 0.723 | 18/20 |
| G2 Microcystis+나머지 log smear 단독 | 2025 | 256 | 0.161 | 0.215 | 0.161 | 0.731 | 0.765 | 0.705 | 〃 |
| G4 4속 log smear +속별피처 단독 | CV 2020~2024 | 1278 | 0.251 | 0.395 | 0.251 | 0.810 | 0.702 | 0.694 | 18/20 |
| G4 4속 log smear +속별피처 단독 | 2025 | 256 | 0.169 | 0.216 | 0.169 | 0.751 | 0.752 | 0.727 | 〃 |
| G2 Microcystis+나머지 log smear +속별피처 단독 | CV 2020~2024 | 1278 | 0.253 | 0.392 | 0.253 | 0.809 | 0.703 | 0.690 | 18/20 |
| G2 Microcystis+나머지 log smear +속별피처 단독 | 2025 | 256 | 0.167 | 0.216 | 0.167 | 0.723 | 0.771 | 0.727 | 〃 |
| G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear +속별피처 단독 | CV 2020~2024 | 1278 | 0.255 | 0.396 | 0.255 | 0.862 | 0.663 | 0.700 | 18/20 |
| G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear +속별피처 단독 | 2025 | 256 | 0.171 | 0.218 | 0.171 | 0.794 | 0.724 | 0.733 | 〃 |
| G2 Microcystis+나머지 속별 선택(micro=log·rest=hurdle) smear +속별피처 단독 | CV 2020~2024 | 1278 | 0.255 | 0.394 | 0.255 | 0.864 | 0.661 | 0.693 | 18/20 |
| G2 Microcystis+나머지 속별 선택(micro=log·rest=hurdle) smear +속별피처 단독 | 2025 | 256 | 0.172 | 0.218 | 0.172 | 0.774 | 0.737 | 0.742 | 〃 |
| 앙상블 c1·c3·c2 + [G4 4속 log smear] | CV 2020~2024 | 1278 | 0.202 | 0.363 | 0.202 | 0.798 | 0.711 | 0.631 | 18/20 |
| 앙상블 c1·c3·c2 + [G4 4속 log smear] | 2025 | 256 | 0.171 | 0.202 | 0.171 | 0.722 | 0.771 | 0.682 | 〃 |
| 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear] | CV 2020~2024 | 1278 | 0.198 | 0.348 | 0.198 | 0.804 | 0.707 | 0.631 | 18/20 |
| 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear] | 2025 | 256 | 0.165 | 0.194 | 0.165 | 0.712 | 0.778 | 0.690 | 〃 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear] | CV 2020~2024 | 1278 | 0.204 | 0.365 | 0.204 | 0.801 | 0.709 | 0.631 | 18/20 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear] | 2025 | 256 | 0.173 | 0.202 | 0.173 | 0.712 | 0.778 | 0.682 | 〃 |
| 앙상블 c1·c3·c2 + [G4 4속 log smear +속별피처] | CV 2020~2024 | 1278 | 0.191 | 0.364 | 0.191 | 0.796 | 0.712 | 0.627 | 18/20 |
| 앙상블 c1·c3·c2 + [G4 4속 log smear +속별피처] | 2025 | 256 | 0.177 | 0.205 | 0.177 | 0.717 | 0.775 | 0.690 | 〃 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear +속별피처] | CV 2020~2024 | 1278 | 0.196 | 0.371 | 0.196 | 0.798 | 0.711 | 0.627 | 18/20 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear +속별피처] | 2025 | 256 | 0.178 | 0.205 | 0.178 | 0.707 | 0.781 | 0.690 | 〃 |
| 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear +속별피처] | CV 2020~2024 | 1278 | 0.189 | 0.351 | 0.189 | 0.804 | 0.707 | 0.624 | 18/20 |
| 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear +속별피처] | 2025 | 256 | 0.167 | 0.196 | 0.167 | 0.711 | 0.778 | 0.690 | 〃 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 속별 선택(micro=log·rest=hurdle) smear +속별피처] | CV 2020~2024 | 1278 | 0.190 | 0.352 | 0.190 | 0.804 | 0.706 | 0.644 | 18/20 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 속별 선택(micro=log·rest=hurdle) smear +속별피처] | 2025 | 256 | 0.167 | 0.195 | 0.167 | 0.709 | 0.780 | 0.690 | 〃 |
| 앙상블 c1→[G4 4속 log smear]·c3·c2 | CV 2020~2024 | 1278 | 0.202 | 0.366 | 0.202 | 0.797 | 0.712 | 0.644 | 18/20 |
| 앙상블 c1→[G4 4속 log smear]·c3·c2 | 2025 | 256 | 0.171 | 0.202 | 0.171 | 0.722 | 0.771 | 0.682 | 〃 |
| 앙상블 c1→[G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear]·c3·c2 | CV 2020~2024 | 1278 | 0.196 | 0.349 | 0.196 | 0.803 | 0.708 | 0.637 | 18/20 |
| 앙상블 c1→[G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear]·c3·c2 | 2025 | 256 | 0.165 | 0.194 | 0.165 | 0.713 | 0.777 | 0.690 | 〃 |
| 앙상블 c1→[G2 Microcystis+나머지 log smear]·c3·c2 | CV 2020~2024 | 1278 | 0.204 | 0.367 | 0.204 | 0.800 | 0.709 | 0.638 | 18/20 |
| 앙상블 c1→[G2 Microcystis+나머지 log smear]·c3·c2 | 2025 | 256 | 0.173 | 0.202 | 0.173 | 0.712 | 0.778 | 0.682 | 〃 |
| 참고: v1 3구성원 + 속별피처(분해 없음) | CV 2020~2024 | 1278 | 0.156 | 0.301 | 0.156 | 0.805 | 0.706 | 0.552 | 18/20 |
| 참고: v1 3구성원 + 속별피처(분해 없음) | 2025 | 256 | 0.174 | 0.200 | 0.174 | 0.706 | 0.782 | 0.683 | 〃 |

### 보조 표

| 구성 | CV 폴드평균 r2_raw | CV 폴드평균 nse_raw | CV 폴드평균 rmse_log | CV 폴드평균 F1@10k | 점예측≥10k 포착 | q90 중앙 리드(일) |
|---|---|---|---|---|---|---|
| v1 기준 | 0.168 | 0.168 | 0.805 | 0.512 | 1/20 | 14.0 |
| 참고: C1 합계 단독(smearing) | 0.229 | 0.229 | 0.819 | 0.496 | 4/20 | 14.0 |
| G4 4속 log smear 단독 | 0.173 | 0.173 | 0.812 | 0.475 | 7/20 | 14.0 |
| G4 4속 log none 단독 | 0.170 | 0.170 | 0.837 | 0.409 | 2/20 | 14.0 |
| G4 4속 hurdle smear 단독 | 0.164 | 0.164 | 0.886 | 0.576 | 2/20 | 14.0 |
| G4 4속 hurdle none 단독 | 0.148 | 0.148 | 0.860 | 0.392 | 1/20 | 14.0 |
| G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear 단독 | 0.178 | 0.178 | 0.865 | 0.478 | 7/20 | 14.0 |
| G2 Microcystis+나머지 log smear 단독 | 0.175 | 0.175 | 0.811 | 0.495 | 7/20 | 14.0 |
| G4 4속 log smear +속별피처 단독 | 0.180 | 0.180 | 0.811 | 0.483 | 4/20 | 14.0 |
| G2 Microcystis+나머지 log smear +속별피처 단독 | 0.178 | 0.178 | 0.810 | 0.494 | 5/20 | 14.0 |
| G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear +속별피처 단독 | 0.183 | 0.183 | 0.862 | 0.485 | 4/20 | 14.0 |
| G2 Microcystis+나머지 속별 선택(micro=log·rest=hurdle) smear +속별피처 단독 | 0.181 | 0.181 | 0.864 | 0.496 | 4/20 | 14.0 |
| 앙상블 c1·c3·c2 + [G4 4속 log smear] | 0.186 | 0.186 | 0.798 | 0.396 | 1/20 | 14.0 |
| 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear] | 0.183 | 0.183 | 0.804 | 0.412 | 1/20 | 14.0 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear] | 0.185 | 0.185 | 0.802 | 0.396 | 1/20 | 14.0 |
| 앙상블 c1·c3·c2 + [G4 4속 log smear +속별피처] | 0.173 | 0.173 | 0.797 | 0.397 | 1/20 | 14.0 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear +속별피처] | 0.175 | 0.175 | 0.799 | 0.397 | 1/20 | 14.0 |
| 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear +속별피처] | 0.173 | 0.173 | 0.804 | 0.394 | 1/20 | 14.0 |
| 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 속별 선택(micro=log·rest=hurdle) smear +속별피처] | 0.173 | 0.173 | 0.805 | 0.534 | 1/20 | 14.0 |
| 앙상블 c1→[G4 4속 log smear]·c3·c2 | 0.187 | 0.187 | 0.797 | 0.536 | 1/20 | 14.0 |
| 앙상블 c1→[G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear]·c3·c2 | 0.182 | 0.182 | 0.803 | 0.549 | 1/20 | 14.0 |
| 앙상블 c1→[G2 Microcystis+나머지 log smear]·c3·c2 | 0.186 | 0.186 | 0.801 | 0.529 | 1/20 | 14.0 |
| 참고: v1 3구성원 + 속별피처(분해 없음) | 0.141 | 0.141 | 0.806 | 0.475 | 1/20 | 13.5 |

### 부분 모델 진단(CV 2020~2024, 부분 타깃 기준, smearing)

| 부분 | CV n | 0 비율 | log rmse_log | log r2_raw | hurdle rmse_log | hurdle r2_raw | log+F rmse_log | log+F r2_raw | hurdle+F rmse_log | hurdle+F r2_raw |
|---|---|---|---|---|---|---|---|---|---|---|
| Microcystis | 1278 | 0.514 | 0.804 | 0.307 | 0.964 | 0.189 | 0.779 | 0.261 | 0.923 | 0.158 |
| Dolichospermum(Anabaena) | 1278 | 0.656 | 0.925 | -0.011 | 0.99 | -0.0 | 0.875 | -0.01 | 0.948 | 0.004 |
| Aphanizomenon | 1278 | 0.402 | 1.012 | 0.009 | 1.122 | 0.045 | 0.956 | 0.071 | 1.08 | 0.093 |
| Oscillatoria | 1278 | 0.842 | 0.858 | -0.01 | 1.099 | 0.03 | 0.753 | 0.035 | 0.957 | 0.075 |
| 나머지 3속(Anabaena+Aphanizomenon+Oscillatoria) | 1278 | 0.306 | 0.961 | 0.057 | 1.041 | 0.051 | 0.936 | 0.042 | 1.01 | 0.066 |

### 앙상블 가중치(2025 적용분, 2020~2024 OOF 로 적합)

- 앙상블 c1·c3·c2 + [G4 4속 log smear]: 2025 가중 c1 0.000, c3 0.247, c2 0.355, cg 0.398
- 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear]: 2025 가중 c1 0.063, c3 0.290, c2 0.514, cg 0.134
- 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear]: 2025 가중 c1 0.000, c3 0.262, c2 0.371, cg 0.367
- 앙상블 c1·c3·c2 + [G4 4속 log smear +속별피처]: 2025 가중 c1 0.000, c3 0.246, c2 0.337, cg 0.416
- 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 log smear +속별피처]: 2025 가중 c1 0.000, c3 0.265, c2 0.332, cg 0.402
- 앙상블 c1·c3·c2 + [G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear +속별피처]: 2025 가중 c1 0.060, c3 0.296, c2 0.508, cg 0.135
- 앙상블 c1·c3·c2 + [G2 Microcystis+나머지 속별 선택(micro=log·rest=hurdle) smear +속별피처]: 2025 가중 c1 0.079, c3 0.332, c2 0.496, cg 0.093
- 앙상블 c1→[G4 4속 log smear]·c3·c2: 2025 가중 cg 0.398, c3 0.247, c2 0.355
- 앙상블 c1→[G4 4속 속별 선택(micro=log·anba=hurdle·apzo=hurdle·osc=hurdle) smear]·c3·c2: 2025 가중 cg 0.145, c3 0.307, c2 0.548
- 앙상블 c1→[G2 Microcystis+나머지 log smear]·c3·c2: 2025 가중 cg 0.367, c3 0.262, c2 0.371

## 3. 선택과 채택 판정

- 선택 규칙(EXP-PLAN 4절, CV 만): 채택 기준을 만족하는 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대 변형을 '기준 미달'로 표시.
- 선택: **G2 Microcystis+나머지 log smear 단독** — CV r2_raw 0.303, CV rmse_log 0.810, 리드타임 18/20
  (2025 확인: r2_raw 0.161, rmse_log 0.731).
- 판정(`harness.adoption`, v1 기준 대비): ΔCV r2_raw +0.131, ΔCV rmse_log +0.006, 리드타임 유지 True → **채택 기준 만족**.
- rmse_log 악화 0.01 이내 변형 중 CV r2_raw 최대는 'G2 Microcystis+나머지 log smear 단독'(CV r2_raw 0.303, rmse_log 0.810).
- 선택 변형의 연도별 NNLS 가중치: (앙상블 아님)
- 행 단위 OOF: `data/processed/exp/EXP-006/chosen_oof.parquet`(c1·c3·c2·cg·cg_<부분>·q10·q50·q90·pred). 부분 OOF 전체: `components.parquet`, 속별 피처: `features.parquet`.
- 중복으로 합친 변형(속별 선택 결과가 기존 변형과 같음): G2 Microcystis+나머지 속별 선택(micro=log·rest=log) smear = G2 Microcystis+나머지 log smear 단독

### 연도별 r2_raw / rmse_log

| 구성 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|
| v1 기준 | 0.086 / 0.865 | 0.328 / 0.777 | 0.073 / 0.834 | 0.091 / 0.777 | 0.261 / 0.772 | 0.166 / 0.708 |
| C1 합계 단독 | 0.050 / 0.884 | 0.367 / 0.793 | 0.225 / 0.825 | 0.093 / 0.808 | 0.410 / 0.786 | 0.109 / 0.713 |
| 선택: G2 Microcystis+나머지 log smear 단독 | 0.058 / 0.886 | 0.102 / 0.776 | 0.244 / 0.827 | 0.098 / 0.805 | 0.374 / 0.762 | 0.161 / 0.731 |
| 최고 앙상블: 앙상블 c1→[G2 Microcystis+나머지 log smear]·c3·c2 | 0.090 / 0.864 | 0.345 / 0.773 | 0.115 / 0.826 | 0.102 / 0.778 | 0.278 / 0.765 | 0.173 / 0.712 |

### (지점·연도) 블록 부트스트랩(CV 2020~2024, 2,000회, 시드 42)

- 선택 − v1 기준: Δr2_raw +0.131 [95% -0.005, +0.168], P(Δ>0) 0.97; Δrmse_log +0.006 [95% -0.011, +0.021] (25블록)
- 선택 − C1 합계 단독: Δr2_raw -0.003 [95% -0.073, +0.022], P(Δ>0) 0.39; Δrmse_log -0.008 [95% -0.024, +0.006] (25블록)
- 최고 앙상블 − v1 기준: Δr2_raw +0.031 [95% +0.005, +0.040], P(Δ>0) 0.99; Δrmse_log -0.004 [95% -0.009, +0.001] (25블록)

### 해석

1. **분해보다 '단독 점예측'의 효과가 크다.** 선택 변형은 v1 기준 대비 CV r2_raw +0.131, rmse_log +0.006 로 채택 기준을 만족한다. 그러나 같은 C1 설정의 합계 모델을 단독으로 쓴 참고 행도 CV r2_raw 0.306(rmse_log 0.818, 악화 +0.013 로 rmse_log 기준만 미달)이다. v1 대비 원단위 R² 이득의 대부분은 속별 분해가 아니라 'log 공간 NNLS 앙상블 대신 smearing 보정 log 회귀를 그대로 점예측으로 쓰는 것'에서 온다.
2. **속별 분해 자체의 기여(선택 − C1 합계 단독)**: CV r2_raw -0.003, rmse_log -0.008. 원단위 R² 는 그대로이고 log 오차를 조금 줄여 C1 단독이 넘지 못한 rmse_log 기준(0.01)을 넘게 한 것이 분해의 실질 효과다. 4속(G4) 합산도 CV r2_raw 0.299·rmse_log 0.811 로 비슷하고, G2 가 2025 rmse_log 에서 더 낫다(0.731 vs 0.764).
3. **2025 확인(선택에 쓰지 않음)**: 선택 변형 r2_raw 0.161·rmse_log 0.731 vs v1 0.166·0.708. CV 의 원단위 R² 이득이 2025 에는 재현되지 않았고 rmse_log 는 나빠졌다(C1 합계 단독 2025 r2_raw 0.109 보다는 높음). 블록 부트스트랩 구간도 넓어(위 표), CV 이득은 소수 고농도 사건에 크게 좌우된다.
3-1. **통합 CV 와 폴드 평균의 차이**: 표준 지표(2020~2024 통합) Δr2_raw +0.131 와 달리 CV 폴드 평균 r2_raw 는 선택 0.175 vs v1 0.168(+0.008), C1 합계 단독 0.229. 통합 R² 는 분산이 큰 2022·2024 의 첨두 몇 행이 좌우하고(연도별 원단위 SSE 의 약 30~70% 가 상위 3행), 2021 은 물금·매리 고농도 1~2행을 과대예측(관측의 약 1.8·4.7배)해 선택 변형이 v1·C1 보다 크게 낮다(연도별 표). 즉 채택 기준은 통합 지표로 만족하지만 연도 간 일관성은 약하다.
4. **NNLS 4번째 구성원**: 최고 앙상블 '앙상블 c1→[G2 Microcystis+나머지 log smear]·c3·c2' 은 CV r2_raw 0.204(+0.031), rmse_log 0.800(-0.004) 로 log 오차는 줄지만 R² 이득이 +0.10 에 못 미친다. 2025 적용 가중은 cg 0.37, c3 0.26, c2 0.37 — NNLS 는 c1 대신 속별 합산을 고른다(속별 합산이 c1 보다 나은 log 구성원). log 공간 NNLS 는 원단위 첨두를 눌러 단독 점예측의 R² 이득을 대부분 잃는다.
5. **hurdle**: 4속 hurdle 합산 CV rmse_log 0.887, r2_raw 0.189 로 log 보다 나쁘다. 부분 원단위 MSE 로는 소수 3속에서 hurdle 이 조금 낫게 나와 '속별 선택'에 뽑혔지만 소수 3속은 세포수 합의 약 16%(2025 약 5%)라 합산 R² 에는 영향이 작고 rmse_log 는 나빠진다.
6. **smearing**: 보정 없는 4속 합산은 CV r2_raw 0.202 — 속별 smearing 이 원단위 합산에 필수다.
7. **속별 자기회귀 피처**: Microcystis 부분 rmse_log 는 좋아지지만(부분 진단 표) 원단위 R² 는 낮아진다. 합산 단독(G2 log +속별피처 CV r2_raw 0.253)·앙상블 모두 피처 없는 쪽보다 R² 가 낮고, v1 3구성원에 피처만 더한 참고 행도 CV r2_raw 0.156(rmse_log 0.805) 로 이득이 없다 → 피처는 채택하지 않는다.

## 4. 누수·2026 점검

- 테스트 `tests/test_exp_r3_genus.py` 11건 통과(pytest): `test_genus_ar_features_ignore_rows_after_as_of`(as_of 이후 행 난수 교체·삭제·추가해도 속별 피처 동일, 3개 as_of), `test_genus_ar_features_values_and_other_station`, `test_build_features_same_index_new_columns_only`(2026 기준일 거부 포함), `test_genus_targets_alignment_and_consistency`(target_date 정렬·합계 불일치 행 비움), `test_compare_sources_counts_matches`, `test_fit_component_uses_only_prior_year_labels[log|hurdle]`(2023 이후 라벨을 교란해도 ≤2023 검증 OOF 동일 — 속별 라벨은 학습 연도 < 검증 연도에서만 쓰임), `test_members_rejects_2026_rows`, `test_load_algae_cuts_after_2025`. 기존 `tests/test_exp_harness.py` 도 함께 통과.
- 속별 타깃은 피처가 아니라 라벨이다(합계 타깃과 같은 측정일·같은 출처). 폴드마다 기준일 연도 < 검증 연도 행만 학습에 쓴다(`year_folds`).
- 속별 자기회귀 피처는 `genus_ar_features(algae, as_of, station_id)` 진입 직후 `features.base.cut_as_of` 로 as_of 이후 측정을 버린다(위 누수 테스트).
- 2026: `harness.load_base()`(≤2025)만 사용, 모델 입력 프레임 `guard_no_2026` 통과. 조류 원자료·대회 번들은 2025-12-31 이후 측정을 읽은 즉시 버렸다 (그래서 정답 측정일이 2026-01-05 인 2025 검증 4행은 속별 타깃 없음 — 이 행들은 학습에 쓰이지 않는다). test 행 예측·2026 지표 없음. 리드타임은 `harness.leadtime`(2025 까지).
- 보호 파일: `python scripts/exp_check_protected.py` 와 같은 대조 결과 변경 0개.
- 공개 함수 `members(df, cols)` 재현: 선택 변형 cg 와 log10 최대 절대차 0.00e+00, 모듈 상수 CHOSEN 일치 True.
- 하이퍼파라미터 v1 그대로(C1), 시드 42 하나. 새 패키지·새 원자료 수집 없음(MANIFEST 조각 불필요).

## 5. 소요 시간·한계·다음 단계

- 소요 0.36h / 상한 8h (착수 2026-10-21 17:53, 마지막 실행 종료 18:15 KST). 전체 실행 1회(부분 OOF 20종 + 참고 구성 + 지표) 약 1.5~3분(동시 실행 부하에 따라).

- 한계: (1) 선택 변형의 v1 대비 이득은 주로 '앙상블 → 단독 smearing 점예측' 전환에서 오며 R1(분산 반영 원단위 복원)과 겹친다. (2) 2025 에서 원단위 R² 이득이 재현되지 않았고, CV 폴드 평균 r2_raw 이득도 작다(3-1). (3) 원단위 R² 는 소수 고농도 표본에 좌우되어 블록 부트스트랩 구간이 넓다. (4) 시드 하나(42), 하이퍼파라미터는 합계 타깃 기준 튜닝값을 속별 타깃에 그대로 썼다(속별 재튜닝 안 함). (5) 회남 2012~2014 는 속별 값이 없어 속별 모델 학습에서 빠졌다(105행). (6) 분위(q90)는 v1 그대로라 리드타임 변화 없음.
- 다음 단계(종합 EXP-011): ① 속별 합산 cg(G2 log smear)를 '단독 점예측' 후보와 'NNLS 구성원' 후보 둘 다로 넘긴다(`members(df, cols)`). 구성원으로 쓰면(c1 을 cg 로 대체) 이득은 작지만(+0.03) 부트스트랩 구간이 0 을 넘고 2025 에서도 v1 보다 조금 나아 더 안정적이다. ② R1 의 원단위 복원(분위 기반 σ·폭 보정)을 C1 합계 단독·cg 에 같이 적용해 비교하면 분해 효과와 역변환 효과를 가를 수 있다. ③ 앙상블은 log 공간 NNLS 대신 원단위 손실로 가중을 적합하는 쪽(또는 cg 단독)을 CV 로 비교할 가치가 있다. ④ 속별 피처는 R² 를 낮춰 넘기지 않는다.
