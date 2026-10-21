# Lighthouse (desktop preset, Edge headless, 로컬 production 빌드) — 2026-10-21 T7-R

| 페이지 | 성능 | 접근성 | LCP | CLS |
|---|---|---|---|---|
| / 메인 상황판 | 96 | 93 | 1.3 s | 0.015 |
| /sites/2011G56 지점 상세 | 91 | 100 | 0.6 s | 0.192 |
| /performance 얼마나 잘 맞혔나 | 100 | 100 | 0.5 s | 0.019 |
| /insights 녹조 이야기 | 100 | 100 | 0.5 s | 0.004 |
| /about 이 시스템은 | 100 | 100 | 0.4 s | 0.011 |

- 명령: `npx lighthouse@12 <url> --preset=desktop --only-categories=performance,accessibility --chrome-flags="--headless=new"` (CHROME_PATH = Edge)
- 1차 측정에서 메인 접근성 86 → 링크의 aria-pressed 제거, 지도 마커 이름(title), 흐린 글자 대비, ⓘ 버튼 20px, 타일 aria-label 순서 수정 후 93.
- 지점 상세 성능 89 → Pretendard CSS 비차단 로드, 차트 높이 고정 후 91 (남은 CLS 0.19 는 Recharts 초기 렌더).
