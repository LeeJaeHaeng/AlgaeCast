# Lighthouse (desktop preset, Edge headless, 프로덕션 https://algaecast-7.vercel.app) — 2026-10-23 18:37 KST, v2.1 화면

페이지마다 3회 측정한 중앙값(괄호는 3회 값). 요약 원자료: `lighthouse_20261023_1837.json`. 측정 대상은 커밋 05543c9(지점 상세 글꼴 폴백 크기 보정) 배포본이다.

| 페이지 | 성능 | 접근성 | LCP | CLS |
|---|---|---|---|---|
| / 메인 상황판 | 96 (94·96·96) | 93 | 1.3 s | 0.027 |
| /sites/2011G56 지점 상세 | 98 (95·98·98) | 100 | 0.8 s | 0.000 |
| /sites/2011G56?kiosk=1 지점 상세 발표모드 | 97 (97·98·97) | 100 | 0.7 s | 0.000 |
| /sites/2011G56?view=expert 지점 상세 전문가 보기 | 98 | 96 | 0.7 s | 0.001 |
| /performance 얼마나 잘 맞혔나 | 100 | 100 | 0.5 s | 0.010 |
| /insights 녹조 이야기 | 100 (100·98·100) | 100 | 0.6 s | 0.004 |
| /about 이 시스템은 | 100 | 100 | 0.5 s | 0.013 |

- 명령: `npx lighthouse@12 <url> --preset=desktop --only-categories=performance,accessibility --chrome-flags="--headless=new"` (CHROME_PATH = Edge, Lighthouse 12.8.2)
- 지점 상세 레이아웃 이동의 원인은 글꼴 교체였다. 본문 글꼴 Pretendard(CDN 동적 서브셋, `font-display: swap`)가 첫 그리기 뒤에 도착하면 폴백(맑은 고딕)과 글자 폭이 달라 줄바꿈이 바뀌었다. 그래서 큰 차트 머리 범례가 2줄에서 1줄로 줄고, '왜 이렇게 예상했나' 묶음이 위로 당겨졌다(Lighthouse 원인 'Web font loaded').
- 수정은 자리 미리 잡기만 했다(문구·숫자·배치·색 변경 없음). 지점 상세에만 'Pretendard Fallback' 글꼴(local 맑은 고딕)을 두고, 굵기·글자 묶음별 `size-adjust`·`ascent/descent-override`로 Pretendard 지표에 맞췄다(next/font `adjustFontFallback` 과 같은 방식, `web/src/app/globals.css` `.fit-fallback-font`).
- 수정 전후 로컬 프로덕션 빌드에서 지점 5곳과 2011G56 전문가 보기·발표모드를 1920×1080·390×844 전체 페이지로 찍어 비교했다. 14장 모두 픽셀 차이가 0이었다.
- 맑은 고딕이 없는 환경(macOS 등)에서는 이 폴백 글꼴이 무시되어 수정 전과 같이 동작한다.
- 다른 페이지 점수는 떨어지지 않았다. 메인은 이번 수정의 적용 범위 밖이며 CLS 는 회차별 0.005~0.027(이전 측정 중앙값 0.018)이고, 전문가 보기 접근성 96 은 수정 전 배포본에서도 같은 값이다(보조 표기 대비).
- 메인 접근성 93 은 2026-10-21 과 같다(링크 aria-pressed 제거·지도 마커 이름·대비·ⓘ 버튼 크기 수정 뒤 값).
- 이력: 2026-10-23 14:50 수정 전 프로덕션은 지점 상세 성능 87(86·92·87)·CLS 0.225, 메인 96/93, 성능 100/100, 녹조 이야기 99/100, 이 시스템은 100/100 이었다(`lighthouse_20261023.json`). 2026-10-21 로컬 production 빌드는 메인 96/93, 지점 상세 91/100, 나머지 100/100 이었다.
