"""사후 검증 전용 — test 타깃(2026)을 **명시적으로** 읽는 유일한 통로.

학습·튜닝·앙상블 코드에서 import 금지.
"""

from __future__ import annotations

import pandas as pd

from algaecast.config import DATA_DIR

TEST_TARGETS_PATH = DATA_DIR / "processed" / "test_targets_DO_NOT_USE.parquet"


def load_test_targets(*, i_know_this_is_for_post_hoc_only: bool = False) -> pd.DataFrame:
    """2026 평가 조합의 실측 타깃. 제출 후 사후 검증(reports/eval/live_*)에서만 호출한다."""
    if not i_know_this_is_for_post_hoc_only:
        raise PermissionError(
            "test 타깃은 사후 검증 전용 — i_know_this_is_for_post_hoc_only=True 로 명시하라"
        )
    df = pd.read_parquet(TEST_TARGETS_PATH)
    df["base_date"] = pd.to_datetime(df["base_date"]).dt.date
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    return df
