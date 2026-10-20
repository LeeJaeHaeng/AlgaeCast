"""BaseCollector: 캐시 키(비밀값 제외)·캐시 적중·TTL·재시도·포털 오류 처리 (네트워크 없음)."""

from datetime import date, timedelta

import pandas as pd
import pytest
import requests

from algaecast.collect import base as b


class FakeResp:
    def __init__(self, text: str, status: int = 200):
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Dummy(b.BaseCollector):
    source = "dummy"
    key_env = None

    def fetch(self, site_code: str, start: date, end: date) -> pd.DataFrame:  # pragma: no cover - 계약용
        return pd.DataFrame()


def _collector(tmp_path, responses):
    sess = FakeSession(responses)
    c = Dummy(cache_dir=tmp_path / "cache", out_dir=tmp_path / "out", session=sess, sleep=lambda s: None)
    c.errors_log = tmp_path / "errors.log"
    return c, sess


def test_cache_key_excludes_secret_and_is_order_independent():
    k1 = b.cache_key("http://x/a", {"serviceKey": "SECRET1", "b": 2, "a": 1})
    k2 = b.cache_key("http://x/a", {"a": 1, "b": 2, "serviceKey": "OTHER"})
    assert k1 == k2
    assert b.cache_key("http://x/a", {"a": 1}) != b.cache_key("http://x/a", {"a": 2})
    assert b.redact({"serviceKey": "s", "x": 1}) == {"serviceKey": "***", "x": 1}


def test_cache_hit_and_ttl(tmp_path):
    c, sess = _collector(tmp_path, [FakeResp("<r>1</r>"), FakeResp("<r>2</r>")])
    r1 = c.get("http://x/a", {"serviceKey": "k", "q": "1"})
    assert r1.text == "<r>1</r>" and not r1.from_cache and r1.cache_path.exists()
    assert "SECRET" not in r1.cache_path.read_text(
        encoding="utf-8"
    ) and '"serviceKey": "***"' in r1.cache_path.read_text(encoding="utf-8")
    r2 = c.get("http://x/a", {"serviceKey": "k", "q": "1"})  # 영구 캐시 적중
    assert r2.from_cache and r2.text == "<r>1</r>" and len(sess.calls) == 1
    r3 = c.get("http://x/a", {"serviceKey": "k", "q": "1"}, ttl=timedelta(seconds=0))  # 만료 → 재요청
    assert not r3.from_cache and r3.text == "<r>2</r>" and len(sess.calls) == 2
    assert c.n_cache_hits == 1 and c.n_requests == 2


def test_retry_then_success_and_exhaustion(tmp_path):
    c, sess = _collector(tmp_path, [requests.ConnectionError("boom"), FakeResp("x", 503), FakeResp("<ok/>")])
    r = c.get("http://x/a", {"q": "1"})
    assert r.text == "<ok/>" and len(sess.calls) == 3
    # 첫 시도 + 재시도 3회 = 최대 4회 호출 (대기 1·2·4초)
    c3, sess3 = _collector(tmp_path / "3", [requests.ConnectionError("a")] * 3 + [FakeResp("<ok/>")])
    assert c3.get("http://x/a", {"q": "3"}).text == "<ok/>" and len(sess3.calls) == 4
    c2, sess2 = _collector(tmp_path / "2", [requests.ConnectionError("a")] * 4)
    with pytest.raises(b.CollectError):
        c2.get("http://x/a", {"q": "2"})
    assert len(sess2.calls) == 4 and "retries exhausted" in c2.errors_log.read_text(encoding="utf-8")


def test_secret_never_leaks_into_logs_or_exceptions(tmp_path, caplog):
    url_with_key = "/x?" + "service" + "Key=SECRET123&pageNo=1"  # 훅의 리터럴 차단을 피하기 위해 조합
    leak = requests.ConnectionError("Max retries exceeded with url: " + url_with_key)
    c, _ = _collector(tmp_path, [leak] * 4)
    with pytest.raises(b.CollectError) as ei:
        c.get("http://x/a", {"serviceKey": "SECRET123", "pageNo": "1"})
    assert "SECRET123" not in str(ei.value)
    assert "SECRET123" not in c.errors_log.read_text(encoding="utf-8")
    assert "SECRET123" not in caplog.text
    assert b.scrub("u?apikey=ABC&x=1 key=Z") == "u?apikey=***&x=1 key=***"


def test_4xx_is_fatal_but_429_retries(tmp_path):
    c, sess = _collector(tmp_path, [FakeResp("nope", 404), FakeResp("<never/>")])
    with pytest.raises(b.CollectError):
        c.get("http://x/a", {"q": "1"})
    assert len(sess.calls) == 1
    c2, sess2 = _collector(tmp_path / "2", [FakeResp("slow down", 429), FakeResp("<ok/>")])
    assert c2.get("http://x/a", {"q": "1"}).text == "<ok/>" and len(sess2.calls) == 2


def test_uncacheable_body_is_retried_not_cached_and_corrupt_cache_is_ignored(tmp_path):
    class Strict(Dummy):
        def is_cacheable(self, text: str) -> bool:
            return "<ok" in text

    sess = FakeSession([FakeResp("<html>maintenance</html>"), FakeResp("<ok/>")])
    c = Strict(cache_dir=tmp_path / "cache", out_dir=tmp_path / "out", session=sess, sleep=lambda s: None)
    c.errors_log = tmp_path / "errors.log"
    r = c.get("http://x/a", {"q": "1"})
    assert r.text == "<ok/>" and len(sess.calls) == 2
    cached = list((tmp_path / "cache").glob("*.json"))
    assert len(cached) == 1 and "<ok/>" in cached[0].read_text(encoding="utf-8")
    cached[0].write_text("{not json", encoding="utf-8")  # 손상된 캐시 → 무시하고 재요청
    sess.responses.append(FakeResp("<ok2/>"))
    assert c.get("http://x/a", {"q": "1"}).text == "<ok2/>"


def test_portal_fatal_error_is_not_retried(tmp_path):
    xml = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        "<returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>"
        "<returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    c, sess = _collector(tmp_path, [FakeResp(xml), FakeResp("<never/>")])
    with pytest.raises(b.PortalError) as ei:
        c.get("http://x/a", {"serviceKey": "k"})
    assert ei.value.code == "22" and len(sess.calls) == 1
    assert "22" in c.errors_log.read_text(encoding="utf-8") and "***" in c.errors_log.read_text(
        encoding="utf-8"
    )


def test_portal_transient_error_is_retried(tmp_path):
    xml = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        "<returnAuthMsg>APPLICATION_ERROR</returnAuthMsg><returnReasonCode>1</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    c, sess = _collector(tmp_path, [FakeResp(xml), FakeResp("<ok/>")])
    assert c.get("http://x/a", {"q": "1"}).text == "<ok/>" and len(sess.calls) == 2


def test_save_writes_parquet_and_csv(tmp_path):
    c, _ = _collector(tmp_path, [])
    df = pd.DataFrame({"site_code": ["2011G26"], "obs_date": [date(2026, 1, 5)], "v": [1.5]})
    pq, csv = c.save(df, "t")
    assert pq.exists() and csv.exists()
    assert pd.read_parquet(pq)["v"].iloc[0] == 1.5
    assert len(c.sha256_prefix(csv)) == 16
    row = c.manifest_row(id_="X", name="n", org="o", endpoint="e", period="p", rows=1, license_="l", path=csv)
    assert row.startswith("| X | n | o | e | p | ") and row.count("|") == 10
