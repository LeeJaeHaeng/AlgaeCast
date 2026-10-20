# AlgaeCast-7

수질·수문·기상 공개 데이터를 융합해 조류경보제 5개 지점의 유해남조류 세포수를 **7일 선행 예측**하고,
경계(10,000 cells/mL) 초과 확률과 녹조제거설비 배치 우선순위를 대시보드로 제공한다.
2026 DATA·AI 분석 경진대회(KISTI) 문제해결 부문 제출작.

- 작업 규칙·실격 조건: [`CLAUDE.md`](CLAUDE.md)
- 문서 지도: [`docs/00_README.md`](docs/00_README.md)
- 태스크 지시서: [`docs/09_DEV_GUIDE_CLAUDE_CODE.md`](docs/09_DEV_GUIDE_CLAUDE_CODE.md)
- 진행 기록: [`docs/PROGRESS.md`](docs/PROGRESS.md)

## 빠른 시작 (Python 3.11, GNU make)
```bash
cp .env.example .env      # data.go.kr 인증키 입력
make setup                # .venv 생성 + 의존성 + pre-commit
make test                 # pytest (누수 테스트 포함)
```
Windows: `winget install ezwinports.make Python.Python.3.11` 후 새 터미널에서 실행.

## 재현 (T9-b 에서 확정)
```bash
make features train submission
```
