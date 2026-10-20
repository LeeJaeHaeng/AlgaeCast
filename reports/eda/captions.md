# 그림 캡션 (T2)

- **fig_target_dist.png** — 세포수 원단위(로그 y축)·log10(x+1) 히스토그램과 지점별 상자그림. 0값과 우측 긴 꼬리 → log 변환 근거.
- **fig_seasonal_month.png** — 지점별 월 상자그림. 6~10월 집중, 물금·매리는 11월까지 지속, 회남은 8~9월 단봉.
- **fig_seasonal_HP.png** — 해평 주 단위 log 세포수 STL 분해(주기 52주, robust). 계절 성분이 분산의 84.2%.
- **fig_seasonal_GJGR.png** — 강정·고령 주 단위 log 세포수 STL 분해(주기 52주, robust). 계절 성분이 분산의 83.6%.
- **fig_seasonal_CS.png** — 칠서 주 단위 log 세포수 STL 분해(주기 52주, robust). 계절 성분이 분산의 83.8%.
- **fig_seasonal_MGMR.png** — 물금·매리 주 단위 log 세포수 STL 분해(주기 52주, robust). 계절 성분이 분산의 85.5%.
- **fig_seasonal_DCHN.png** — 회남 주 단위 log 세포수 STL 분해(주기 52주, robust). 계절 성분이 분산의 84.3%.
- **fig_lag_corr.png** — log 세포수와 설명변수(0~30일 lag) Spearman 히트맵, 전체 및 지점별. 창 길이 7/14/30일 선정 근거.
- **fig_site_response.png** — 지점별 세포수–수온 LOESS. 같은 수온에서도 지점별 반응이 다름(물금·매리 > 강정고령 > 칠서 > 해평 > 회남). 지점 범주형 피처 근거.
- **fig_onset_trend.png** — 연도·지점별 첫 관심/경계 발령일(DOY). 추세 검정 결과는 tbl_onset_trend.md.
- **fig_missing.png** — 수질 변수×월 결측률과 주간 미채수 비율. 겨울(12~3월) 비채수가 대부분, 하절기에는 세포수 결측이 거의 없음.
- **fig_corr_matrix.png** — 측정일 기준 변수 간 Spearman 상관행렬. 기온–수온, 유입–방류 강한 공선성 → T3-c VIF 로 정리.
