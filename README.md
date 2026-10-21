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

## 핵심 결과
2020~2026년 경계 사건 28건 중 25건(89%)을 첫 경계 초과 측정 기준 중앙 14일 앞서 감시 단계로 포착했다(지속성 3건).
모델 동결 후 처음 보는 2026년 경계 사건 8건 중 7건을 중앙 21일 앞서 포착했다(지속성 2건).
상세와 한계(2026 사후 성능 저하 등)는 `reports/방법설명서.pdf` 1·6·10장.

## 재현
저장소에서 동결 모델로 제출 파일을 다시 만들어 제출본과 비교한다(재학습 없음).
```bash
make reproduce    # 동결 모델 해시 확인 → 정렬 → 피처 → 예측 → submission/submission.csv 와 바이트 비교
```

## 제출 패키지 (공지 #564 구조)
```bash
python scripts/render_method_doc.py                       # reports/방법설명서.md → .pdf (헤드리스 Edge)
python scripts/build_submission_package.py                # submission_package/ 생성(데모 영상 sha256 확인)
python scripts/verify_package.py --update-package         # 새 venv 재현 검증(diff 0·노트북 오류 0)
python scripts/build_submission_package.py --zip-only     # dist/ 에 zip 2종(영상 포함·영상 제외)
```
패키지 안에서는 `jupyter lab notebooks/01_train_eval.ipynb` 로 노트북을 열어 셀 단위로 실행할 수 있다.
