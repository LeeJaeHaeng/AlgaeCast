# 이력 모델 — 제출 패키지 미포함 목록

제출 패키지 `model/` 에는 submission.csv 재현과 노트북 실행에서 실제로 불러오는 모델만 넣는다.
제출·운영 모델 T24 의 회귀 `regression/20261026_131722`, 경보 분류기 `classifier/20261026_131722`,
분위 회귀 `quantile/20261026_131722` 세 폴더다(`FROZEN_T24.md` 표의 이름별 첫 행 = `registry.json` current).
T24 는 운영사무국 답변(2026-10-28, "학습은 24년까지의 데이터만 활용 가능")에 따라 사전등록 규칙대로 v2.1 에서 바꾼
제출 모델이다(`reports/experiments/PREREG_contingency.md` 8절). 구성은 v2.1 과 같고 학습은 대회 번들 split=train 2,310행이다.

- 근거(2026-10-23 추적, v2.1 때): 패키지 사본에서 `make_submission` 단독 실행과 노트북 전체 실행
  (`jupytext --to notebook --execute`, 커널 프로세스 포함)을 하면서, 파이썬 감사 훅(open 이벤트)과
  `pickle.load`·`joblib.load`·`lightgbm.Booster(model_file=...)`·`registry.load_current` 래퍼로 `model/` 아래에서
  열린 파일을 기록했다. 모델로 불러온 파일은 current 세 폴더의 `model.pkl` 뿐이었고, 이력 폴더는
  `scripts/verify_frozen.py` 의 sha256 읽기로만 열렸다. T24 는 코드 경로가 같고 current 만 바뀌었다. T24 회귀 객체의
  `aux`(v1 30열·범주)는 T24 학습 행에서 만들어 `model.pkl` 안에 들어 있다(이력 파일을 열지 않는다).
- 아래 여덟 폴더는 이력이다: 수정 전 v1 봉인본(3)·v2 회귀(1), 민감도 보고용 v1-fix 회귀(1), 그리고 2026-10-23~27 의
  제출·운영 모델 v2.1(3, 최종 학습 ≤2025). 동결 문서 `FROZEN.md`(v1)·`FROZEN_v2.md`(v2)·`FROZEN_v2.1.md`(v2.1·v1-fix)는
  기록으로 패키지에 남긴다. `registry.json` 도 저장소와 같은 항목(이력 포함)을 담으며 current 는 T24 다
  (패키지 사본에는 이력 항목에 `"package"` 표시만 더한다).
- 제공: **요청 시 제공(비공개 저장소 Release·로컬 보관)**. Release `model-frozen-v2.1-217260e`
  (자산 `models-frozen-v2.1-217260e.tar.gz`)에 v2.1 세 폴더와 v1·v2·v1-fix 다섯 폴더가 모두 있고, v1 세 폴더는
  `model-frozen-13ac483`, v1 세 폴더와 v2 회귀는 `model-frozen-v2-9dca86c` 에도 있다. T24 는 `contingency-T24-a961caf`.
  저장소 작업 폴더 `models/` 에도 보관한다.
- 검증: 패키지에서 `python scripts/verify_frozen.py` 는 이력 행의 파일이 없을 때 아래 표의 `model.pkl` sha256 이
  동결 문서 표와 같으면 '패키지 미포함(이력, model/HISTORY.md)'으로 표시하고 통과한다. 제출·운영 모델 세 폴더는
  파일이 있고 해시가 맞아야 통과한다. 저장소 `models/` 에서는 지금처럼 모든 파일을 검증한다.
- sha256 은 저장소 `models/` 의 실제 파일로 계산했다(`model.pkl` 값은 동결 문서 표와 같다).
- 재학습 명령은 해당 동결 커밋을 체크아웃한 저장소(원자료 `data/raw/` 포함)에서 정렬·피처
  (`python -m algaecast.align.run --strategy S1`, `python -m algaecast.features.run --strategy S1`) 다음에 실행한다.
  재학습으로 같은 파일이 다시 나온다고 보장하지 않으므로(아래 주의) 원본 대조는 Release 파일로 한다.

## regression/20261021_091108 — v1 봉인본 회귀

- 역할: v1 제출 모델(2026-10-21 봉인) 회귀 = 로그 앙상블(C1 smearing·C3 hurdle·C2 tweedie, NNLS, 피처 30). 수정 전 이력
- 동결 문서: `FROZEN.md` (표 첫 행)
- 동결 커밋: `13ac4832f5ff641c42c766da20c2f983b3c7915c` (2026-10-21 09:43:57 KST). FROZEN.md 기록 커밋 `9c7a353` (2026-10-21 09:57:41 KST)
- 동결 시각: FROZEN.md 에 동결 시각 항목 없음 — 위 동결 커밋 시각. 파일 생성 2026-10-21 09:11:09 (meta.json `created`)
- 재학습 명령: `python -m algaecast.models.alert --trials 150` (`make alert`; T4-c 러너가 회귀 앙상블·분류기·분위를 한 번에
  학습·등록 — `src/algaecast/models/alert.py`, reports/experiments/EXP-002.md 2026-10-21판)
- 주의: 2026-10-22 2026 타깃 격리 뒤 코드에서는 학습 행 차이로 같은 파일이 나오지 않는다(docs/PROGRESS.md 2026-10-22 'v2 운영 이식').
  봉인 당시 일부 데이터 유래 상수가 2026 자료를 포함해 계산됐다(reports/experiments/FIX-v2.1/RESULT.md).
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-13ac483`·`model-frozen-v2-9dca86c`·`model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `regression/20261021_091108/model.pkl` | `dc45d72bb878e863d0680a750859956e12d3a161978087d7d74bcbb9f32d9403` | 15,402,662 |
| `regression/20261021_091108/meta.json` | `f1d6909511f8b3f0f8d67adf9fa63bf27599bc54d75b1635bc8010d33fb64a56` | 1,273 |

## classifier/20261021_091109 — v1 봉인본 경보 분류기(v1·v2 공통)

- 역할: 경계 분류기 b(+4~+10일 창 ≥10,000). v1 과 v2 가 함께 썼다(v2.1 은 `classifier/20261023_120255` 로 재적합). 수정 전 이력
- 동결 문서: `FROZEN.md`·`FROZEN_v2.md`
- 동결 커밋: `13ac4832f5ff641c42c766da20c2f983b3c7915c` (2026-10-21 09:43:57 KST)
- 동결 시각: 동결 커밋 시각(FROZEN.md 에 별도 항목 없음). 파일 생성 2026-10-21 09:11:09
- 재학습 명령: `python -m algaecast.models.alert --trials 150` (위 회귀와 같은 실행)
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-13ac483`·`model-frozen-v2-9dca86c`·`model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `classifier/20261021_091109/model.pkl` | `81e913ad85a2ec586738c33c1f2d24ecc45d92993e1f4f567d96b27ba46f5c63` | 1,658,726 |
| `classifier/20261021_091109/meta.json` | `b71166d9ced99b33d294230aa97210b124db9f326839cec69a668bdc81cee5cb` | 1,033 |

## quantile/20261021_091110 — v1 봉인본 분위 회귀(v1·v2 공통)

- 역할: 분위 회귀 q10·q50·q90. v1 과 v2 가 함께 썼다(v2.1 은 `quantile/20261023_120257` 로 재적합). 수정 전 이력
- 동결 문서: `FROZEN.md`·`FROZEN_v2.md`
- 동결 커밋: `13ac4832f5ff641c42c766da20c2f983b3c7915c` (2026-10-21 09:43:57 KST)
- 동결 시각: 동결 커밋 시각(FROZEN.md 에 별도 항목 없음). 파일 생성 2026-10-21 09:11:10
- 재학습 명령: `python -m algaecast.models.alert --trials 150` (위 회귀와 같은 실행)
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-13ac483`·`model-frozen-v2-9dca86c`·`model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `quantile/20261021_091110/model.pkl` | `3b26c445d5b728233e94015d58b52ef32f7f8a811777f015d6f37cb013f48478` | 7,947,776 |
| `quantile/20261021_091110/meta.json` | `dc28502f3f4f87c2b149e8a248d7f6f7076d0888c7455e4cdd55b84ffe6d1aea` | 962 |

## regression/20261022_162747 — v2 회귀

- 역할: v2 제출 모델(2026-10-22 동결) 회귀 = ensemble_v2(c1·c3·c2 + 속별 cg, 피처 35 = v1 30 + 상류 5). 수정 전 이력
- 동결 문서: `FROZEN_v2.md` (표 첫 행)
- 동결 커밋: `9dca86ccb236625e3decba6fcf49442c071d51d1` (2026-10-22 16:33:26 KST)
- 동결 시각: 2026-10-22 16:27:48 KST (FROZEN_v2.md). 파일 생성 2026-10-22 16:27:47
- 재학습 명령: `python scripts/freeze_v2.py --freeze` (FROZEN_v2.md·reports/v2/BUILD.md; 이미 동결 문서가 있으면 `--force`.
  `--dry-run` 은 data/processed/exp/v2_dryrun/ 에만 쓴다)
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-v2-9dca86c`·`model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `regression/20261022_162747/model.pkl` | `d696f6933eff04130f722a52cda614f1f0cf091a06cf518b67acd18b2b1f34e2` | 20,430,437 |
| `regression/20261022_162747/meta.json` | `3061f6d10d28452c133e694471bd567aedf366a121216568669fe4f5f39eac33` | 3,297 |

## regression/20261023_120255 — v1-fix 회귀(민감도용)

- 역할: v1 구성(c1·c3·c2, 피처 30, NNLS)을 누수 수정 피처로 다시 적합한 회귀. 민감도 보고용이며 current 가 아니다.
  v2.1 회귀의 `aux`(v1 30열·범주)를 이 객체에서 복사했다(v2.1 `model.pkl` 안에 들어 있어 이 파일은 실행에 필요 없다)
- 동결 문서: `FROZEN_v2.1.md` (표 넷째 행, '민감도 보고용, current 아님')
- 동결 커밋: `217260ee42e26519a52b187cca7149162046e222` (2026-10-23 12:14:45 KST)
- 동결 시각: 2026-10-23 12:08:19 KST (FROZEN_v2.1.md, v2.1 과 같은 동결). 파일 생성 2026-10-23 12:02:55
- 재학습 명령: `python -m algaecast.models.alert --skip-tune` (같은 실행이 v2.1 분류기 `classifier/20261023_120255`·분위
  `quantile/20261023_120257` 도 등록한다 — scripts/freeze_v21.py 설명, reports/experiments/FIX-v2.1/PREREG.md R6).
  그 뒤 `python scripts/freeze_v21.py --oof` → `--freeze` 가 v2.1 회귀를 만든다
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `regression/20261023_120255/model.pkl` | `4e341732fe4d9ba48be768a570dd9836b0050d9233a29d5cc924dbe87d4dfed7` | 15,371,621 |
| `regression/20261023_120255/meta.json` | `ef23538a7c1737d50e9b2a5e8a3c354004026c246a346f6ff5707c713c42ea4e` | 1,273 |

## regression/20261023_120818 — v2.1 회귀(2026-10-23~27 제출·운영)

- 역할: v2.1 제출·운영 모델(2026-10-23 동결 ~ 2026-10-28 T24 전환) 회귀 = ensemble_v2(c1·c3·c2·cg, 피처 35, 가중치 c1 0.055·c3 0.280·c2 0.267·cg 0.398). 최종 적합 ≤2025(2,562행), 수온 임계 ≤2025
- 동결 문서: `FROZEN_v2.1.md` (표 첫 행)
- 동결 커밋: `217260ee42e26519a52b187cca7149162046e222` (2026-10-23 12:14:45 KST)
- 동결 시각: 2026-10-23 12:08:19 KST (FROZEN_v2.1.md). 파일 생성 2026-10-23 12:08:18
- 재학습 명령: `python -m algaecast.models.alert --skip-tune`(분류기·분위) → `python scripts/freeze_v21.py --oof` → `--freeze`(회귀)
- 주의: v2.1 제출본(`4741a3d3…`)은 test 수온 임계 ≤2025 로 만든 것이다. 2026-10-28 부터 코드 기본값이
  `FINAL_THRESHOLD_YEAR = 2024`(T24)이므로, v2.1 재현 경로(`scripts/freeze_v21.py`·`models/alert.py` 최종 적합·
  `eval/posthoc_v21.py`)는 `V21_THRESHOLD_YEAR = 2025` 를 명시해 쓴다. 원본 대조는 동결 커밋 217260e 와 Release 로 한다
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `regression/20261023_120818/model.pkl` | `d95e7a4e8dab50a59583dd8ecf8ab2482786ec05f7bfa1f256c657bec3a091f0` | 20,414,068 |
| `regression/20261023_120818/meta.json` | `059772416e24bd2723cf4483612c9873d5d6afe441c308f1dd92d233861bcf9f` | 3,558 |

## classifier/20261023_120255 — v2.1 경보 분류기 b

- 역할: v2.1 경보 분류기 b(+4~+10일 창 ≥1만, 피처 30). 최종 적합 ≤2025
- 동결 문서: `FROZEN_v2.1.md` (표 둘째 행)
- 동결 커밋: `217260ee42e26519a52b187cca7149162046e222` (2026-10-23 12:14:45 KST)
- 동결 시각: 2026-10-23 12:08:19 KST (FROZEN_v2.1.md). 파일 생성 2026-10-23 12:02:55
- 재학습 명령: `python -m algaecast.models.alert --skip-tune`
- 주의: v2.1 제출본(`4741a3d3…`)은 test 수온 임계 ≤2025 로 만든 것이다. 2026-10-28 부터 코드 기본값이
  `FINAL_THRESHOLD_YEAR = 2024`(T24)이므로, v2.1 재현 경로(`scripts/freeze_v21.py`·`models/alert.py` 최종 적합·
  `eval/posthoc_v21.py`)는 `V21_THRESHOLD_YEAR = 2025` 를 명시해 쓴다. 원본 대조는 동결 커밋 217260e 와 Release 로 한다
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `classifier/20261023_120255/model.pkl` | `cce848b6c1b5d1608d73403d5ef089bf8e4dc04bdc358eea8afd7fcb3ae1c77d` | 1,653,681 |
| `classifier/20261023_120255/meta.json` | `8427c45acb1e243389efd8cd8ebc2b9ab96e55087e9f1c6c56604a23fe85c4a1` | 1,033 |

## quantile/20261023_120257 — v2.1 분위 회귀

- 역할: v2.1 분위 회귀 q10·q50·q90(피처 30). 최종 적합 ≤2025
- 동결 문서: `FROZEN_v2.1.md` (표 셋째 행)
- 동결 커밋: `217260ee42e26519a52b187cca7149162046e222` (2026-10-23 12:14:45 KST)
- 동결 시각: 2026-10-23 12:08:19 KST (FROZEN_v2.1.md). 파일 생성 2026-10-23 12:02:57
- 재학습 명령: `python -m algaecast.models.alert --skip-tune`
- 주의: v2.1 제출본(`4741a3d3…`)은 test 수온 임계 ≤2025 로 만든 것이다. 2026-10-28 부터 코드 기본값이
  `FINAL_THRESHOLD_YEAR = 2024`(T24)이므로, v2.1 재현 경로(`scripts/freeze_v21.py`·`models/alert.py` 최종 적합·
  `eval/posthoc_v21.py`)는 `V21_THRESHOLD_YEAR = 2025` 를 명시해 쓴다. 원본 대조는 동결 커밋 217260e 와 Release 로 한다
- 제공: 요청 시 제공(비공개 저장소 Release·로컬 보관) — Release `model-frozen-v2.1-217260e`

| 파일 | sha256 | bytes |
|---|---|---|
| `quantile/20261023_120257/model.pkl` | `9b52945aa53e2af2a0189eb8368389410eabd001a6336620684baaca07258bee` | 7,926,563 |
| `quantile/20261023_120257/meta.json` | `7b75f8078b9ce065acc7b2389f0f1bf4e1b331bc0208e96d7c666ff51353a272` | 962 |
