"""모델 레지스트리 (docs/08 §93).

models/registry.json 의 ``current`` 에 회귀(제출용)·분류기(확률용)·분위 모델을 분리 등록.

버전 디렉터리: models/<name>/<version>/ (pickle + meta.json). predict 는 current 만 사용.

회귀 항목의 종류(meta.kind, pickle 객체의 "kind")
- ``ensemble``    : v1 로그 앙상블(C1·C3·C2, 피처 30) — models/FROZEN.md
- ``ensemble_v2`` : v2 운영 모델(v1 앙상블 + 상류 피처 5 + 속별 cg,
  models.v2.V2Model.to_registry) — models/FROZEN_v2.md
- ``log_w``       : 단일 C1(앙상블 미채택 시)
v2 에서도 분류기·분위는 v1 버전을 그대로 current 로 둔다.

reg_dir 인자: 기본(None)은 저장소 models/(패키지: model/).
freeze_v2 --dry-run·테스트는 임시 디렉터리를 넘긴다.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from algaecast.config import MODELS_DIR, ROOT

REG_DIR = MODELS_DIR
REG_FILE = REG_DIR / "registry.json"


def _paths(reg_dir: Path | None) -> tuple[Path, Path]:
    """(레지스트리 디렉터리, registry.json).

    None 이면 모듈 기본값(테스트에서 바꿀 수 있게 호출 시점에 읽는다).
    """
    if reg_dir is None:
        return REG_DIR, REG_FILE
    d = Path(reg_dir)
    return d, d / "registry.json"


def _load(reg_dir: Path | None = None) -> dict:
    _, f = _paths(reg_dir)
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"current": {}, "versions": []}


def _save(reg: dict, reg_dir: Path | None = None) -> None:
    d, f = _paths(reg_dir)
    d.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


def features_hash(cols: list[str]) -> str:
    return hashlib.sha1("|".join(cols).encode()).hexdigest()[:12]


def file_sha256(path: Path) -> str:
    """파일 sha256(16진수 64자)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return p.resolve().as_posix()


def _new_version(d: Path, name: str) -> str:
    """초 단위 버전(YYYYMMDD_HHMMSS). 같은 초에 이미 있으면 다음 초까지 기다린다."""
    while True:
        v = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not (d / name / v).exists():
            return v
        time.sleep(0.2)


def register(
    name: str,
    obj: Any,
    *,
    features: list[str],
    metrics_holdout: dict,
    meta: dict | None = None,
    set_current: bool = True,
    reg_dir: Path | None = None,
    version: str | None = None,
) -> dict:
    """obj 를 <reg_dir>/<name>/<version>/model.pkl 로 저장하고 registry.json 에 항목을 더한다."""
    base, _ = _paths(reg_dir)
    version = version or _new_version(base, name)
    d = base / name / version
    if (d / "model.pkl").exists():
        raise FileExistsError(f"이미 있는 버전: {d}")
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
        "path": _rel(d / "model.pkl"),
    }
    (d / "meta.json").write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    reg = _load(reg_dir)
    reg["versions"].append(entry)
    if set_current:
        reg["current"][name] = version
    _save(reg, reg_dir)
    return entry


def entry_for(name: str, version: str, reg_dir: Path | None = None) -> dict:
    """registry.json 의 (name, version) 항목."""
    reg = _load(reg_dir)
    for e in reg["versions"]:
        if e["name"] == name and e["version"] == version:
            return e
    raise KeyError(f"registry 에 {name}/{version} 없음")


def current_entry(name: str, reg_dir: Path | None = None) -> dict:
    """current 항목(pickle 을 열지 않는다)."""
    version = _load(reg_dir)["current"].get(name)
    if version is None:
        raise KeyError(f"registry current 에 {name} 없음")
    return entry_for(name, version, reg_dir)


def current_kind(name: str = "regression", reg_dir: Path | None = None) -> str | None:
    """current 항목의 종류(meta.kind: ensemble·ensemble_v2·log_w). 없으면 None."""
    try:
        return current_entry(name, reg_dir).get("meta", {}).get("kind")
    except KeyError:
        return None


def model_path(name: str, version: str, reg_dir: Path | None = None) -> Path:
    base, _ = _paths(reg_dir)
    return base / name / version / "model.pkl"


def load_current(name: str, reg_dir: Path | None = None) -> tuple[Any, dict]:
    entry = current_entry(name, reg_dir)
    # registry.json 의 경로는 저장소 기준(models/...)
    # 실제 위치는 MODELS_DIR(또는 reg_dir) 기준으로 푼다(패키지: model/)
    with model_path(name, entry["version"], reg_dir).open("rb") as f:
        return pickle.load(f), entry


def set_current(name: str, version: str, reg_dir: Path | None = None) -> None:
    reg = _load(reg_dir)
    entry_for(name, version, reg_dir)
    reg["current"][name] = version
    _save(reg, reg_dir)


def copy_version(name: str, version: str, dst_dir: Path, src_dir: Path | None = None) -> dict:
    """src 레지스트리의 (name, version) 파일·항목을 dst 레지스트리로 복사.

    dry-run·테스트용. current 는 바꾸지 않는다.
    """
    src_base, _ = _paths(src_dir)
    entry = entry_for(name, version, src_dir)
    dst = Path(dst_dir) / name / version
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("model.pkl", "meta.json"):
        if (src_base / name / version / f).exists():
            shutil.copy2(src_base / name / version / f, dst / f)
    reg = _load(dst_dir)
    if not any(e["name"] == name and e["version"] == version for e in reg["versions"]):
        reg["versions"].append(entry)
    _save(reg, dst_dir)
    return entry


LN10 = 2.302585092994046  # ln(10): 자연로그 공간 SHAP → log10 공간


def explain_member(reg: dict) -> dict:
    """SHAP 설명용 단일 LightGBM 구성원 — model·cols·cats·categories(+member·shap_scale)를 담은 dict.

    - v1 ensemble: '회귀 C1(smearing)'(log10 공간).
    - ensemble_v2: 결합 가중치가 가장 큰 단일 모델 구성원(c1 log 회귀 또는 c2 tweedie). c3 hurdle·cg 속별은
      모델이 둘 이상이라 제외한다. v2 동결 가중치는 c1 0 · c2 0.373 이라 c2 를 설명한다.
      tweedie 의 SHAP 은 자연로그(링크) 공간이므로 shap_scale = 1/ln(10) 을 곱해 log10 공간으로 맞춘다.
    - 단일 모델: 객체 자체.
    """
    kind = reg.get("kind")
    if kind == "ensemble":
        return reg["members"]["회귀 C1(smearing)"]
    if kind == "ensemble_v2":
        w = reg.get("weights", {})
        single = [k for k, m in reg["members"].items() if isinstance(m, dict) and "model" in m]
        name = max(single, key=lambda k: (float(w.get(k, 0.0)), k == "c1"))
        m = reg["members"][name]
        scale = 1.0 / LN10 if m.get("kind") == "tweedie" else 1.0
        return {
            **m,
            "cols": reg["cols"],
            "cats": m.get("cats", reg["cats"]),
            "member": name,
            "shap_scale": scale,
        }
    return reg


def current_versions(reg_dir: Path | None = None) -> dict[str, str]:
    return dict(_load(reg_dir)["current"])


def registry_path(reg_dir: Path | None = None) -> Path:
    return _paths(reg_dir)[1]
