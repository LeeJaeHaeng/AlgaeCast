"""수집기 공통 기반 — 캐시·재시도·pandera 스키마 검증·저장·MANIFEST (docs/02 9절, docs/08 4절).

- 캐시: 요청 URL + 파라미터(serviceKey 제외)의 sha1 → ``data/raw/cache/<sha1>.json`` (원문·메타).
  ``ttl`` 로 만료 제어.
- 재시도: 네트워크 오류·5xx·포털 일시 오류에 3회(1·2·4초). 트래픽 초과(22)·키 오류(30/31/32)는 즉시 중단.
- 검증: 하위 클래스의 ``schema``(pandera) 로 ``validate()``. 실패는 예외 — 조용히 넘어가지 않는다.
- 저장: ``data/raw/<source>/<name>.parquet`` + 동일 내용 ``.csv``(utf-8-sig).
  ``manifest_row()`` 로 MANIFEST 행 생성.
- 실패 로그: ``data/raw/collect_errors.log``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pandera.pandas as pa
import requests

from algaecast.config import RAW_DIR, get_env

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger(__name__)

PORTAL_FATAL = {
    "22": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS",
    "30": "SERVICE_KEY_IS_NOT_REGISTERED",
    "31": "DEADLINE_HAS_EXPIRED",
    "32": "UNREGISTERED_IP",
}
SECRET_PARAMS = {"servicekey", "apikey", "key"}


class CollectError(RuntimeError):
    """재시도로 해결되지 않는 수집 오류 (키·트래픽·스키마)."""


class PortalError(CollectError):
    """공공데이터포털 게이트웨이 오류 (OpenAPI_ServiceResponse)."""

    def __init__(self, code: str, msg: str) -> None:
        super().__init__(f"data.go.kr 오류 {code} {msg}")
        self.code, self.msg = code, msg


@dataclass
class FetchResult:
    text: str
    from_cache: bool
    fetched_at: datetime
    url: str
    cache_path: Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def redact(params: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k.lower() in SECRET_PARAMS else v) for k, v in params.items()}


_SECRET_RE = re.compile(r"(?i)(servicekey|apikey|key)=[^&\s'\")]+")


def scrub(text: str) -> str:
    """URL 쿼리 안의 인증키를 가린다 (requests 예외 메시지에는 전체 URL 이 들어간다)."""
    return _SECRET_RE.sub(r"\1=***", text)


def cache_key(url: str, params: dict[str, Any]) -> str:
    """serviceKey 등 비밀값을 뺀 (url, 정렬된 파라미터) 의 sha1."""
    clean = {k: str(v) for k, v in params.items() if k.lower() not in SECRET_PARAMS}
    payload = url + "?" + "&".join(f"{k}={clean[k]}" for k in sorted(clean))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def portal_error(text: str) -> PortalError | None:
    """포털 레벨 오류 XML(OpenAPI_ServiceResponse)이면 PortalError, 아니면 None."""
    head = text.lstrip()[:200]
    if "OpenAPI_ServiceResponse" not in head and "cmmMsgHeader" not in text[:500]:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return PortalError("?", head[:120])
    code = root.findtext(".//returnReasonCode") or "?"
    msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or ""
    return PortalError(code, msg)


class BaseCollector(ABC):
    """공공 데이터 수집기 기반 클래스. 하위 클래스는 ``source``·``schema``·``fetch()`` 를 정의한다."""

    source: str = "base"
    schema: pa.DataFrameSchema | None = None
    timeout: int = 60
    retries: int = 3
    backoff: tuple[float, ...] = (1.0, 2.0, 4.0)
    key_env: str | None = "DATA_GO_KR_KEY"  # 인증키 환경변수 (None 이면 키 없이)

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        out_dir: Path | None = None,
        use_cache: bool = True,
        session: requests.Session | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.cache_dir = (RAW_DIR / "cache") if cache_dir is None else cache_dir
        self.out_dir = (RAW_DIR / self.source) if out_dir is None else out_dir
        self.use_cache = use_cache
        self.session = session or requests.Session()
        self._sleep = sleep
        self.errors_log = RAW_DIR / "collect_errors.log"
        self.n_requests = 0
        self.n_cache_hits = 0

    # ------------------------------------------------------------------ HTTP
    def service_key(self) -> str | None:
        return get_env(self.key_env, required=True) if self.key_env else None

    def is_cacheable(self, text: str) -> bool:
        """캐시해도 되는 정상 응답인지 판정. 하위 클래스가 응답 헤더 검사로 덮어쓴다(오류 본문 캐시 방지)."""
        return bool(text.strip())

    def _read_cache(self, path: Path, ttl: timedelta | None) -> FetchResult | None:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(meta["fetched_at"])
            text = meta["text"]
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("손상된 캐시 무시: %s", path.name)
            return None
        if ttl is not None and datetime.now(KST) - fetched > ttl:
            return None
        return FetchResult(text, True, fetched, meta.get("url", ""), path, meta)

    def get(self, url: str, params: dict[str, Any], *, ttl: timedelta | None = None) -> FetchResult:
        """GET + 캐시 + 재시도 (첫 시도 + ``retries`` 회, 대기 1·2·4초).

        ``ttl=None`` 이면 캐시를 영구 사용, 주면 그 시간 안의 캐시만 사용. 4xx(429 제외)·포털 치명 오류는
        재시도하지 않고 즉시 CollectError. ``is_cacheable()`` 을 통과한 본문만 캐시한다.
        """
        path = self.cache_dir / f"{cache_key(url, params)}.json"
        if self.use_cache and path.exists():
            hit = self._read_cache(path, ttl)
            if hit is not None:
                self.n_cache_hits += 1
                return hit
        last: str = ""
        attempts = self.retries + 1
        for attempt in range(attempts):
            try:
                self.n_requests += 1
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code >= 500 or r.status_code == 429:
                    raise requests.RequestException(f"HTTP {r.status_code}")  # 일시 오류 → 재시도
                if r.status_code >= 400:
                    self._log_error(url, params, f"fatal HTTP {r.status_code}")
                    raise CollectError(f"{self.source}: HTTP {r.status_code} (재시도 안 함)")
                text = r.content.decode(r.encoding or "utf-8", errors="replace") if r.content else ""
                err = portal_error(text)
                if err is not None:
                    if err.code in PORTAL_FATAL:
                        self._log_error(url, params, f"fatal {err}")
                        raise err
                    raise requests.RequestException(str(err))  # 일시 오류 → 재시도
                if not self.is_cacheable(text):
                    raise requests.RequestException(f"응답 검증 실패 (캐시 안 함): {text.lstrip()[:80]!r}")
                fetched = datetime.now(KST)
                meta = {
                    "url": url,
                    "params": redact(params),
                    "fetched_at": fetched.isoformat(),
                    "status": r.status_code,
                    "text": text,
                }
                if self.use_cache:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                return FetchResult(text, False, fetched, url, path if self.use_cache else None, meta)
            except CollectError:
                raise
            except (requests.RequestException, OSError) as exc:
                last = scrub(str(exc))
                log.warning("%s 요청 실패 (%d/%d): %s", self.source, attempt + 1, attempts, last)
                if attempt < attempts - 1:
                    self._sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        self._log_error(url, params, f"retries exhausted: {last}")
        raise CollectError(f"{self.source}: {self.retries}회 재시도 실패 - {last}")

    def _log_error(self, url: str, params: dict[str, Any], msg: str) -> None:
        self.errors_log.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            datetime.now(KST).isoformat(),
            self.source,
            url,
            json.dumps(redact(params), ensure_ascii=False),
            msg,
        ]
        with self.errors_log.open("a", encoding="utf-8") as f:
            f.write("\t".join(fields) + "\n")

    # ------------------------------------------------------------------ 계약
    @abstractmethod
    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:
        """02 문서 9절 규약(site_code, obs_date, <vars>, source, fetched_at)의 DataFrame 을 반환한다."""

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.schema is None:
            return df
        return self.schema.validate(df, lazy=True)

    # ------------------------------------------------------------------ 저장
    def save(self, df: pd.DataFrame, name: str) -> tuple[Path, Path]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        pq, csv = self.out_dir / f"{name}.parquet", self.out_dir / f"{name}.csv"
        df.to_parquet(pq, index=False)
        df.to_csv(csv, index=False, encoding="utf-8-sig", lineterminator="\n")
        return pq, csv

    @staticmethod
    def sha256_prefix(path: Path, n: int = 16) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:n]

    def manifest_row(
        self,
        *,
        id_: str,
        name: str,
        org: str,
        endpoint: str,
        period: str,
        rows: int,
        license_: str,
        path: Path,
    ) -> str:
        fetched = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        cells = [id_, name, org, endpoint, period, fetched, f"{rows:,}", license_, self.sha256_prefix(path)]
        return "| " + " | ".join(cells) + " |"
