# -*- coding: utf-8 -*-
"""Pytest compatibility hooks and runtime isolation for the test suite."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import tempfile
import time
import threading
from collections.abc import Awaitable, Callable
from contextvars import copy_context
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import patch
from warnings import warn

import anyio.to_thread
import fastapi.testclient
import httpx
import pytest
import requests.adapters
import starlette.testclient
from anyio._backends import _asyncio

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Runtime isolation
#
# The application resolves its SQLite database, credential files and logs from
# DATABASE_PATH / LOG_DIR at call time, defaulting to ./data and ./logs in the
# repository. Without an override, every test that touches DatabaseManager,
# LLM usage telemetry or admin auth writes into the developer's real
# data/stock_analysis.db. Point both at a per-session temporary directory before
# any application module is imported. `setdefault` keeps explicit overrides made
# by individual tests (they set DATABASE_PATH to their own tmp file); the
# autouse fixture below re-applies the default after tests that pop the variable.
# ---------------------------------------------------------------------------
_TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="dsa-pytest-"))
_TEST_DATA_DIR = _TEST_RUNTIME_DIR / "data"
_TEST_LOG_DIR = _TEST_RUNTIME_DIR / "logs"
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
_TEST_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _apply_isolated_runtime_env() -> None:
    os.environ.setdefault("DATABASE_PATH", str(_TEST_DATA_DIR / "stock_analysis.db"))
    os.environ.setdefault("LOG_DIR", str(_TEST_LOG_DIR))


_apply_isolated_runtime_env()

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver"})
_original_http_adapter_send = requests.adapters.HTTPAdapter.send


def _blocked_http_adapter_send(self, request, *args: Any, **kwargs: Any):
    """Refuse outbound HTTP from tests that are not marked ``network``.

    Tests that mock ``requests.get`` / ``Session.request`` never reach the
    adapter, so they are unaffected; only real connections are stopped.
    Loopback targets stay allowed for tests that spin up local servers.
    """
    host = (httpx.URL(request.url).host or "").lower() if request.url else ""
    if host in _LOOPBACK_HOSTS or host.endswith(".localhost"):
        return _original_http_adapter_send(self, request, *args, **kwargs)
    raise requests.exceptions.ConnectionError(
        f"Outbound HTTP to {host or request.url!r} is blocked in the offline test suite; "
        "mock the client or mark the test with @pytest.mark.network"
    )


@pytest.fixture(autouse=True)
def _isolated_runtime(request: pytest.FixtureRequest):
    """Keep tests off the real database/log directories and off the network."""
    _apply_isolated_runtime_env()
    if request.node.get_closest_marker("network") is not None:
        yield
        return
    with patch.object(requests.adapters.HTTPAdapter, "send", _blocked_http_adapter_send):
        yield


def set_zh_report_language_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the configured report language at ``zh`` until ``monkeypatch`` is undone."""
    from src.config import get_config

    # Load the singleton before changing the environment: if it does not exist
    # yet, get_config() would build it from REPORT_LANGUAGE=zh, monkeypatch
    # would record zh as the original value, and the singleton would keep zh
    # for every later test.
    config = get_config()
    monkeypatch.setattr(config, "report_language", "zh")
    monkeypatch.setenv("REPORT_LANGUAGE", "zh")


@pytest.fixture
def zh_report_language_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure ``REPORT_LANGUAGE=zh`` for tests that assert Chinese output.

    Report-language fallbacks follow the configured default
    (``src.report_language.get_default_report_language``), which is ``en``.
    Tests that exercise the Chinese rendering without passing a language opt
    in with ``@pytest.mark.usefixtures("zh_report_language_default")``.
    """
    set_zh_report_language_default(monkeypatch)


_original_call_soon_threadsafe = asyncio.BaseEventLoop.call_soon_threadsafe


async def _shutdown_default_executor_inline(
    self: asyncio.BaseEventLoop,
    timeout: float | None = None,
) -> None:
    """Avoid lost wakeups while asyncio.run() tears down test-only executors."""
    del timeout
    executor = getattr(self, "_default_executor", None)
    if executor is None:
        return
    self._executor_shutdown_called = True
    self._default_executor = None
    executor.shutdown(wait=True)


def _call_soon_threadsafe_with_extra_wakeup(
    self: asyncio.BaseEventLoop,
    callback,
    *args,
    context=None,
):
    """Wake the selector again for sandboxed test runs where the first wake is lost."""
    handle = _original_call_soon_threadsafe(self, callback, *args, context=context)
    write_to_self = getattr(self, "_write_to_self", None)
    if callable(write_to_self):
        write_to_self()
        threading.Timer(0.001, write_to_self).start()
    return handle


asyncio.BaseEventLoop.call_soon_threadsafe = _call_soon_threadsafe_with_extra_wakeup
asyncio.BaseEventLoop.shutdown_default_executor = _shutdown_default_executor_inline


async def _run_sync_via_asyncio_to_thread(
    func: Callable[..., T],
    *args: Any,
    abandon_on_cancel: bool = False,
    cancellable: bool | None = None,
    limiter: Any = None,
) -> T:
    """Use asyncio's executor path when AnyIO worker queues miss wakeups."""
    del abandon_on_cancel, limiter
    if cancellable is not None:
        warn(
            "The `cancellable=` keyword argument to `anyio.to_thread.run_sync` is "
            "deprecated since AnyIO 4.1.0; use `abandon_on_cancel=` instead",
            DeprecationWarning,
            stacklevel=2,
        )
    future: concurrent.futures.Future[T] = concurrent.futures.Future()
    context = copy_context()

    def runner() -> None:
        try:
            future.set_result(context.run(func, *args))
        except BaseException as exc:
            future.set_exception(exc)

    threading.Thread(target=runner, name="pytest-anyio-worker", daemon=True).start()
    while not future.done():
        await asyncio.sleep(0.001)
    return future.result()


def _wait_for_cross_thread_result(loop: asyncio.AbstractEventLoop, future: concurrent.futures.Future[T]) -> T:
    write_to_self = getattr(loop, "_write_to_self", None)
    while not future.done():
        if callable(write_to_self):
            write_to_self()
        time.sleep(0.001)
    return future.result()


def _run_sync_from_thread_with_wakeup(
    cls,
    func: Callable[..., T],
    args: tuple[Any, ...],
    token: object,
) -> T:
    @wraps(func)
    def wrapper() -> None:
        try:
            _asyncio.set_current_async_library("asyncio")
            future.set_result(func(*args))
        except BaseException as exc:
            future.set_exception(exc)
            if not isinstance(exc, Exception):
                raise

    loop = token or _asyncio.threadlocals.current_token.native_token
    if loop.is_closed():
        raise _asyncio.RunFinishedError
    future: concurrent.futures.Future[T] = concurrent.futures.Future()
    loop.call_soon_threadsafe(wrapper)
    return _wait_for_cross_thread_result(loop, future)


def _run_async_from_thread_with_wakeup(
    cls,
    func: Callable[..., Awaitable[T]],
    args: tuple[Any, ...],
    token: object,
) -> T:
    loop = token or _asyncio.threadlocals.current_token.native_token
    if loop.is_closed():
        raise _asyncio.RunFinishedError
    context = copy_context()
    context.run(_asyncio.set_current_async_library, "asyncio")
    future = context.run(asyncio.run_coroutine_threadsafe, func(*args), loop=loop)
    return _wait_for_cross_thread_result(loop, future)


anyio.to_thread.run_sync = _run_sync_via_asyncio_to_thread
_asyncio.AsyncIOBackend.run_sync_from_thread = classmethod(_run_sync_from_thread_with_wakeup)
_asyncio.AsyncIOBackend.run_async_from_thread = classmethod(_run_async_from_thread_with_wakeup)


class _ThreadlessTestClient:
    """Small TestClient replacement that avoids AnyIO's cross-thread portal."""

    def __init__(
        self,
        app,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        follow_redirects: bool = True,
        **_: Any,
    ) -> None:
        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self.follow_redirects = follow_redirects
        self.cookies = httpx.Cookies()
        self._lifespan_ctx = None
        self._lifespan_enter_count = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_client: httpx.AsyncClient | None = None

    def _get_lifespan_context(self):
        return getattr(getattr(self.app, "router", None), "lifespan_context", None)

    def _build_async_client(self, follow_redirects: bool) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(
            app=self.app,
            raise_app_exceptions=self.raise_server_exceptions,
        )
        return httpx.AsyncClient(
            transport=transport,
            base_url=self.base_url,
            follow_redirects=follow_redirects,
            cookies=self.cookies,
        )

    def __enter__(self):
        if self._lifespan_enter_count == 0:
            self._loop = asyncio.new_event_loop()
            lifespan_context = self._get_lifespan_context()
            if callable(lifespan_context):
                self._lifespan_ctx = lifespan_context(self.app)
                self._loop.run_until_complete(self._lifespan_ctx.__aenter__())
            self._async_client = self._build_async_client(self.follow_redirects)
        self._lifespan_enter_count += 1
        return self

    def __exit__(self, *args: Any) -> None:
        if self._lifespan_enter_count == 0:
            return None

        self._lifespan_enter_count -= 1
        if self._lifespan_enter_count == 0 and self._loop is not None:
            try:
                async def _close() -> None:
                    if self._async_client is not None:
                        await self._async_client.aclose()
                    if self._lifespan_ctx is not None:
                        await self._lifespan_ctx.__aexit__(*args)

                self._loop.run_until_complete(_close())
            finally:
                self._lifespan_ctx = None
                self._async_client = None
                self._loop.close()
                self._loop = None
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        follow_redirects = kwargs.pop("follow_redirects", self.follow_redirects)
        kwargs.pop("allow_redirects", None)

        if self._lifespan_enter_count > 0 and self._loop is not None and self._async_client is not None:
            response = self._loop.run_until_complete(
                self._async_client.request(method, url, follow_redirects=follow_redirects, **kwargs)
            )
            self.cookies = httpx.Cookies(self._async_client.cookies)
            return response

        async def _send() -> httpx.Response:
            async with self._build_async_client(follow_redirects) as client:
                response = await client.request(method, url, **kwargs)
                self.cookies = httpx.Cookies(client.cookies)
                return response

        return asyncio.run(_send())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)


fastapi.testclient.TestClient = _ThreadlessTestClient
starlette.testclient.TestClient = _ThreadlessTestClient
