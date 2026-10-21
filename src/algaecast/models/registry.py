"""모델 레지스트리 (docs/08 §93).

models/registry.json 의 ``current`` 에 회귀(제출용)·분류기(확률용)·분위 모델을 분리 등록.

버전 디렉터리: models/<name>/<version>/ (pickle + meta.json). predict 는 current 만 사용.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

from algaecast.config import MODELS_DIR, ROOT

REG_DIR = MODELS_DIR
REG_FILE = REG_DIR / "registry.json"


def _load() -> dict:
    if REG_FILE.exists():
        return json.loads(REG_FILE.read_text(encoding="utf-8"))
    return {"current": {}, "versions": []}


def features_hash(cols: list[str]) -> str:
    return hashlib.sha1("|".join(cols).encode()).hexdigest()[:12]


def register(
    name: str,
    obj: Any,
    *,
    features: list[str],
    metrics_holdout: dict,
    meta: dict | None = None,
    set_current: bool = True,
) -> dict:
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = REG_DIR / name / version
    d.mkdir(parents=True, exist_ok=True)
    with (d / "model.pkl").open("wb") as f:
        pickle.dump(obj, f)
    entry = {
        "name": name,
        "version": version,
        "created": datetime.now().isoformat(timespec="seconds"),
        "features": features,
        "features_hash": features_hash(features),
        "metrics_holdout": {
            k: (round(float(v), 4) if isinstance(v, (int, float)) else v) for k, v in metrics_holdout.items()
        },
        "meta": meta or {},
        "path": str((d / "model.pkl").relative_to(ROOT)).replace("\\", "/"),
    }
    (d / "meta.json").write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    reg = _load()
    reg["versions"].append(entry)
    if set_current:
        reg["current"][name] = version
    REG_FILE.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return entry


def load_current(name: str) -> tuple[Any, dict]:
    reg = _load()
    version = reg["current"].get(name)
    if version is None:
        raise KeyError(f"registry current 에 {name} 없음")
    entry = next(e for e in reg["versions"] if e["name"] == name and e["version"] == version)
    # registry.json 의 경로는 저장소 기준(models/...) — 실제 위치는 MODELS_DIR 기준으로 푼다(패키지: model/)
    with (REG_DIR / name / version / "model.pkl").open("rb") as f:
        return pickle.load(f), entry


def current_versions() -> dict[str, str]:
    return dict(_load()["current"])


def registry_path() -> Path:
    return REG_FILE
