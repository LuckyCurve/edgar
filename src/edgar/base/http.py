from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from edgar.base.env import get_cache_dir, get_rate_limit, get_timeout, get_user_agent
from edgar.base.errors import BlockedError, NetworkError, NotFoundError, ParseError

TTL_TICKERS = 24 * 60 * 60
TTL_SUBMISSIONS = 30 * 60
TTL_FACTS = 6 * 60 * 60
TTL_INDEX = 60 * 60
TTL_DOCUMENT = 7 * 24 * 60 * 60
TTL_SEARCH = 60

_BLOCK_MARKERS = (
    b"undeclared automated tool",
    b"your request originates",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Response:
    url: str
    content: bytes
    status: int
    fetched_at: str
    cache: str = "miss"
    stale: bool = False
    content_type: str = ""
    headers: dict | None = None

    @property
    def text(self) -> str:
        charset = "utf-8"
        if self.content_type and "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            return self.content.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        try:
            return json.loads(self.content)
        except ValueError as exc:
            raise ParseError(
                f"SEC returned data that is not JSON for {self.url}",
                "The endpoint may be temporarily unavailable; retry with --refresh.",
            ) from exc


class HttpClient:
    """Rate-limited, retrying, cached HTTP access to SEC.

    Every fetch is recorded in ``sources`` so callers can show provenance.
    """

    def __init__(
        self,
        user_agent: str | None = None,
        rate_limit: float | None = None,
        cache_dir: str | Path | None = None,
        timeout: float | None = None,
        use_cache: bool = True,
    ):
        self.user_agent = user_agent or get_user_agent()
        self.rate_limit = get_rate_limit() if rate_limit is None else max(0.1, min(float(rate_limit), 10.0))
        self.timeout = get_timeout() if timeout is None else float(timeout)
        self.cache_dir = Path(cache_dir) if cache_dir else get_cache_dir()
        self.use_cache = use_cache
        self.sources: dict[str, dict] = {}
        self.refresh = False
        self._min_interval = 1.0 / self.rate_limit
        self._last_request = 0.0

    # -- provenance -------------------------------------------------------

    def _record(self, url: str, fetched_at: str, cache: str, status: int, stale: bool = False):
        self.sources[url] = {
            "url": url,
            "fetched_at": fetched_at,
            "cache": cache,
            "status": status,
            **({"stale": True} if stale else {}),
        }

    def source_list(self) -> list[dict]:
        return list(self.sources.values())

    # -- cache ------------------------------------------------------------

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        root = self.cache_dir / "http"
        return root / "body" / key, root / "meta" / f"{key}.json"

    def _read_cache(self, url: str) -> tuple[bytes | None, dict]:
        body_path, meta_path = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, {}
        try:
            body = body_path.read_bytes()
        except OSError:
            return None, {}
        return body, meta if isinstance(meta, dict) else {}

    def _write_cache(self, url: str, body: bytes, meta: dict):
        body_path, meta_path = self._paths(url)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = body_path.with_suffix(".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, body_path)
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, meta_path)

    # -- network ----------------------------------------------------------

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def _requires_contact(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "www.sec.gov" or host == "efts.sec.gov"

    def _request_once(self, url: str, headers: dict) -> tuple[int, Any, bytes]:
        self._throttle()
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                status = resp.status
                resp_headers = resp.headers
        except HTTPError as exc:
            body = exc.read() if exc.fp is not None else b""
            status = exc.code
            resp_headers = exc.headers
            try:
                exc.close()
            except Exception:
                pass
        encoding = (resp_headers.get("Content-Encoding") or "").lower() if resp_headers else ""
        if encoding == "gzip" or body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except OSError:
                pass
        elif encoding == "deflate":
            try:
                body = zlib.decompress(body)
            except zlib.error:
                try:
                    body = zlib.decompress(body, -zlib.MAX_WBITS)
                except zlib.error:
                    pass
        return status, resp_headers, body

    def get(
        self,
        url: str,
        ttl: int = 0,
        refresh: bool | None = None,
        headers: dict | None = None,
    ) -> Response:
        if refresh is None:
            refresh = self.refresh
        body, meta = self._read_cache(url) if (self.use_cache and ttl > 0) else (None, {})
        now = time.time()
        if body is not None and not refresh and now - float(meta.get("fetched_at", 0)) < ttl:
            fetched_at = datetime.fromtimestamp(
                float(meta.get("fetched_at", now)), timezone.utc
            ).isoformat(timespec="seconds").replace("+00:00", "Z")
            self._record(url, fetched_at, "hit", int(meta.get("status", 200)))
            return Response(
                url=url,
                content=body,
                status=int(meta.get("status", 200)),
                fetched_at=fetched_at,
                cache="hit",
                content_type=str(meta.get("content_type", "")),
                headers=meta.get("headers") if isinstance(meta.get("headers"), dict) else None,
            )

        if self._requires_contact(url) and "@" not in self.user_agent:
            raise BlockedError(
                "SEC blocks archive requests without a contact email in the User-Agent.",
                'Run: edgar config set user_agent "Your Name you@example.com"',
            )

        request_headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/html, application/xhtml+xml, text/plain, */*",
        }
        if headers:
            request_headers.update(headers)
        if body is not None:
            if meta.get("etag"):
                request_headers["If-None-Match"] = str(meta["etag"])
            if meta.get("last_modified"):
                request_headers["If-Modified-Since"] = str(meta["last_modified"])

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                status, resp_headers, content = self._request_once(url, request_headers)
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                time.sleep(0.5 * (2**attempt))
                continue

            content_type = (resp_headers.get("Content-Type") or "") if resp_headers else ""
            etag = (resp_headers.get("ETag") or "") if resp_headers else ""
            last_modified = (resp_headers.get("Last-Modified") or "") if resp_headers else ""

            if status == 304 and body is not None:
                meta["fetched_at"] = now
                if self.use_cache and ttl > 0:
                    self._write_cache(url, body, meta)
                fetched_at = utc_now()
                self._record(url, fetched_at, "revalidated", 304)
                return Response(
                    url=url,
                    content=body,
                    status=int(meta.get("status", 200)),
                    fetched_at=fetched_at,
                    cache="revalidated",
                    content_type=str(meta.get("content_type", "")),
                    headers=meta.get("headers") if isinstance(meta.get("headers"), dict) else None,
                )

            if status == 200:
                fetched_at = utc_now()
                if self.use_cache and ttl > 0:
                    self._write_cache(
                        url,
                        content,
                        {
                            "url": url,
                            "fetched_at": now,
                            "status": status,
                            "etag": etag,
                            "last_modified": last_modified,
                            "content_type": content_type,
                        },
                    )
                self._record(url, fetched_at, "miss", status)
                return Response(
                    url=url,
                    content=content,
                    status=status,
                    fetched_at=fetched_at,
                    cache="miss",
                    content_type=content_type,
                    headers=dict(resp_headers.items()) if resp_headers else None,
                )

            lowered = content.lower()
            if status == 403 or any(marker in lowered for marker in _BLOCK_MARKERS):
                raise BlockedError(
                    "SEC rejected the request as an undeclared automated tool.",
                    'Run: edgar config set user_agent "Your Name you@example.com"',
                )
            if status == 404:
                raise NotFoundError(f"SEC has no document at {url}")
            if status == 429 or 500 <= status < 600:
                last_error = NetworkError(f"SEC returned HTTP {status} for {url}")
                time.sleep(0.5 * (2**attempt))
                continue
            raise NetworkError(f"SEC returned HTTP {status} for {url}")

        if body is not None:
            fetched_at = datetime.fromtimestamp(
                float(meta.get("fetched_at", now)), timezone.utc
            ).isoformat(timespec="seconds").replace("+00:00", "Z")
            self._record(url, fetched_at, "stale", int(meta.get("status", 200)), stale=True)
            return Response(
                url=url,
                content=body,
                status=int(meta.get("status", 200)),
                fetched_at=fetched_at,
                cache="stale",
                stale=True,
                content_type=str(meta.get("content_type", "")),
                headers=meta.get("headers") if isinstance(meta.get("headers"), dict) else None,
            )
        raise NetworkError(
            f"Could not reach SEC for {url}",
            str(last_error) if last_error else "Check your network connection and retry.",
        )

    def get_json(self, url: str, ttl: int = 0, refresh: bool | None = None) -> Any:
        return self.get(url, ttl=ttl, refresh=refresh).json()
