# EXP-005(2차) P3 MANIFEST 조각 — 메인 세션이 data/raw/MANIFEST.md 에 통합

수집 결과는 0건이다(API허브 활용신청 미승인). MT-06(중기예보, 서비스 미승인 0건) 행과 같은 방식으로 시도 기록만 남긴다.

| id | 데이터명 | 기관 | 엔드포인트/URL | 기간 | 수집일시 | 행수 | 라이선스 | sha256 |
|----|---------|------|---------------|------|---------|------|---------|--------|
| MT-05b | 기상청 단기예보 과거 발표분(격자) — 5지점 격자(HP 85,97 · GJGR 86,90 · CS 87,80 · MGMR 96,79 · DCHN 71,102), 기준일 05시 발표분 +1~+3일 계획 (`collect/kma_apihub_fcst.py` 점검만, 저장 위치 계획 `data/raw/kma_fcst_hist/`) | 기상청 | apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_shrt_grd (tmfc, tmef, vars, authKey=`KMA_APIHUB_KEY`) | (계획) 2016-01~2025-12 발표분 | 2026-10-22 12:19 KST 점검 — **HTTP 403 "활용신청이 필요한 API 입니다"** | 0 | 공공누리 1유형(기상청) | - |

비고
- 같은 키로 예보구역 조회(`typ01/url/fct_shrt_reg.php`, `fct_medm_reg.php`)는 HTTP 200이다. 잘못된 키를 넣으면 HTTP 401 "유효한 인증키가 아닙니다."가 나온다. 따라서 키는 유효하고, 자료 API를 활용신청하지 않은 상태다.
- 아래 API도 같은 403이었다.
  - 동네예보 격자: `nph-dfs_vsrt_grd`, `nph-dfs_odam_grd`, `nph-dfs_xy_lonlat`
  - `typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst`
  - 단기 육상예보 `fct_afs_dl.php`·`fct_afs_dl2.php`, 단기 개황 `fct_afs_ds.php`
- 공공데이터포털 `VilageFcstInfoService_2.0/getVilageFcst`(MT-05)는 과거 발표일 요청에 resultCode 10 "최근 3일 간의 자료만 제공합니다."를 돌려준다.
- 점검 원본: `reports/experiments/EXP-005/P3/probe.json`(키 값 없음). 다시 점검하려면 `python -m algaecast.collect.kma_apihub_fcst`를 실행한다.
- MT-04(API허브) 행의 "계정 발급" 표기에 "단기예보 격자자료 등 자료 API 는 개별 활용신청 필요(2026-10-22 기준 미신청)"를 덧붙이는 것을 제안한다.
