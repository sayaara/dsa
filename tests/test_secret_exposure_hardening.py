# -*- coding: utf-8 -*-
"""Regression tests for the secret-exposure hardening:

1. every schema-sensitive config field is masked on read,
2. saved channel secrets can be reused for test / discovery only when the endpoint is unchanged,
3. private-network LLM base URLs are blocked unless LLM_ALLOW_PRIVATE_BASE_URLS=true,
4. /docs, /redoc and /openapi.json require an admin session when auth is enabled.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    sys.modules["litellm"] = MagicMock()

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.auth as auth
from api.middlewares.auth import add_auth_middleware
from src.config import Config
from src.core.config_manager import ConfigManager
from src.services.system_config_service import SystemConfigService


class _EnvBackedServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self._write_env(
            "STOCK_LIST=600519",
            "GEMINI_API_KEY=gemini-secret",
            "TUSHARE_TOKEN=tushare-secret",
            "WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wechat-secret",
            "LLM_CHANNELS=proxy,multi",
            "LLM_PROXY_PROTOCOL=openai",
            "LLM_PROXY_BASE_URL=https://proxy.example.com/v1",
            "LLM_PROXY_API_KEY=sk-proxy-secret",
            "LLM_PROXY_MODELS=gpt-4o-mini",
            "LLM_MULTI_PROTOCOL=openai",
            "LLM_MULTI_BASE_URL=https://multi.example.com/v1",
            "LLM_MULTI_API_KEYS=sk-multi-1,sk-multi-2",
            "LLM_MULTI_MODELS=gpt-4o-mini",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        Config.reset_instance()
        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    def tearDown(self) -> None:
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def _write_env(self, *lines: str) -> None:
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class SensitiveFieldMaskingTests(_EnvBackedServiceTestCase):
    def test_every_sensitive_field_is_masked_on_read(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}
        serialized = repr(payload)

        for key in ("GEMINI_API_KEY", "TUSHARE_TOKEN", "WECHAT_WEBHOOK_URL", "LLM_PROXY_API_KEY", "LLM_MULTI_API_KEYS"):
            with self.subTest(key=key):
                self.assertEqual(items[key]["value"], payload["mask_token"])
                self.assertTrue(items[key]["is_masked"])
                self.assertTrue(items[key]["raw_value_exists"])

        for secret in ("gemini-secret", "tushare-secret", "wechat-secret", "sk-proxy-secret", "sk-multi-1"):
            self.assertNotIn(secret, serialized)

        self.assertEqual(items["LLM_PROXY_BASE_URL"]["value"], "https://proxy.example.com/v1")
        self.assertFalse(items["LLM_PROXY_BASE_URL"]["is_masked"])

    def test_saving_mask_token_keeps_stored_secret(self) -> None:
        payload = self.service.get_config(include_schema=True)
        mask = payload["mask_token"]
        self.service.update(
            items=[
                {"key": "GEMINI_API_KEY", "value": mask},
                {"key": "LLM_MULTI_API_KEYS", "value": mask},
                {"key": "STOCK_LIST", "value": "600519,000001"},
            ],
            config_version=payload["config_version"],
            mask_token=mask,
            reload_now=False,
        )
        saved = self.manager.read_config_map()
        self.assertEqual(saved["GEMINI_API_KEY"], "gemini-secret")
        self.assertEqual(saved["LLM_MULTI_API_KEYS"], "sk-multi-1,sk-multi-2")
        self.assertEqual(saved["STOCK_LIST"], "600519,000001")


class SavedChannelSecretReuseTests(_EnvBackedServiceTestCase):
    def _resolve(self, *, name: str, base_url: str, protocol: str = "openai"):
        return self.service._resolve_hermes_saved_secret(
            channel_name=name,
            protocol=protocol,
            base_url=base_url,
            submitted_api_key="******",
            use_saved_secret=True,
            stage="chat_completion",
        )

    def test_reuses_saved_single_key_when_endpoint_unchanged(self) -> None:
        secret, error, redaction = self._resolve(name="proxy", base_url="https://proxy.example.com/v1/")
        self.assertEqual(secret, "sk-proxy-secret")
        self.assertEqual(error, {})
        self.assertIn("sk-proxy-secret", redaction)

    def test_reuses_saved_multi_key_when_endpoint_unchanged(self) -> None:
        secret, _error, _ = self._resolve(name="multi", base_url="https://multi.example.com/v1")
        self.assertEqual(secret, "sk-multi-1,sk-multi-2")

    def test_rejects_reuse_when_base_url_changed(self) -> None:
        secret, error, _ = self._resolve(name="proxy", base_url="https://attacker.example.net/v1")
        self.assertIsNone(secret)
        self.assertFalse(error["success"])
        self.assertEqual(error["error_code"], "saved_secret_scope_mismatch")
        self.assertNotIn("sk-proxy-secret", repr(error))

    def test_rejects_reuse_when_protocol_changed(self) -> None:
        secret, error, _ = self._resolve(name="proxy", base_url="https://proxy.example.com/v1", protocol="anthropic")
        self.assertIsNone(secret)
        self.assertEqual(error["error_code"], "saved_secret_scope_mismatch")

    def test_missing_saved_secret_is_reported(self) -> None:
        secret, error, _ = self._resolve(name="unknown", base_url="https://proxy.example.com/v1")
        self.assertIsNone(secret)
        self.assertEqual(error["error_code"], "missing_saved_secret")

    def test_submitted_key_wins_when_reuse_not_requested(self) -> None:
        secret, error, _ = self.service._resolve_hermes_saved_secret(
            channel_name="proxy",
            protocol="openai",
            base_url="https://elsewhere.example.com/v1",
            submitted_api_key="sk-typed",
            use_saved_secret=False,
            stage="chat_completion",
        )
        self.assertEqual(secret, "sk-typed")
        self.assertEqual(error, {})


class PrivateNetworkBaseUrlTests(unittest.TestCase):
    PRIVATE_URLS = (
        "http://192.168.1.20:11434/v1",
        "http://10.0.0.5:8000/v1",
        "http://172.16.4.4/v1",
        "http://100.64.0.9/v1",
        "http://[fd00::1]/v1",
        "http://[::ffff:192.168.1.20]/v1",
        "http://host.docker.internal:11434/v1",
        "http://ollama.local:11434/v1",
        "http://gpu-box.lan:8080/v1",
    )
    ALWAYS_BLOCKED = (
        "http://169.254.169.254/latest/meta-data/",
        "http://[fe80::1]/v1",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://100.100.100.200/v1",
        "http://0.0.0.0:11434/v1",
    )
    ALWAYS_ALLOWED = (
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434",
        "http://[::1]:11434/v1",
        "http://ollama.localhost:11434/v1",
        "https://api.openai.com/v1",
        "https://api.deepseek.com/v1",
    )

    def setUp(self) -> None:
        self._saved = os.environ.pop("LLM_ALLOW_PRIVATE_BASE_URLS", None)

    def tearDown(self) -> None:
        os.environ.pop("LLM_ALLOW_PRIVATE_BASE_URLS", None)
        if self._saved is not None:
            os.environ["LLM_ALLOW_PRIVATE_BASE_URLS"] = self._saved

    def test_private_ranges_blocked_by_default(self) -> None:
        for url in self.PRIVATE_URLS:
            with self.subTest(url=url):
                self.assertFalse(SystemConfigService._is_safe_base_url(url))

    def test_private_ranges_allowed_with_flag(self) -> None:
        for url in self.PRIVATE_URLS:
            with self.subTest(url=url, mode="argument"):
                self.assertTrue(SystemConfigService._is_safe_base_url(url, allow_private=True))
        os.environ["LLM_ALLOW_PRIVATE_BASE_URLS"] = "true"
        for url in self.PRIVATE_URLS:
            with self.subTest(url=url, mode="env"):
                self.assertTrue(SystemConfigService._is_safe_base_url(url))

    def test_metadata_and_link_local_blocked_even_with_flag(self) -> None:
        for url in self.ALWAYS_BLOCKED:
            with self.subTest(url=url):
                self.assertFalse(SystemConfigService._is_safe_base_url(url, allow_private=True))
                self.assertFalse(SystemConfigService._is_safe_base_url(url, allow_private=False))

    def test_loopback_and_public_hosts_allowed_by_default(self) -> None:
        for url in self.ALWAYS_ALLOWED:
            with self.subTest(url=url):
                self.assertTrue(SystemConfigService._is_safe_base_url(url))

    def test_flag_parser_accepts_only_explicit_truthy_tokens(self) -> None:
        for raw in ("true", "TRUE", "1", "yes", "on"):
            self.assertTrue(SystemConfigService._parse_allow_private_base_urls(raw))
        for raw in ("", None, "false", "0", "maybe", "off"):
            self.assertFalse(SystemConfigService._parse_allow_private_base_urls(raw))


class PrivateNetworkValidationFlagTests(_EnvBackedServiceTestCase):
    def _channel_items(self, base_url: str, *extra):
        return [
            {"key": "LLM_CHANNELS", "value": "lan"},
            {"key": "LLM_LAN_PROTOCOL", "value": "openai"},
            {"key": "LLM_LAN_BASE_URL", "value": base_url},
            {"key": "LLM_LAN_API_KEY", "value": "sk-lan"},
            {"key": "LLM_LAN_MODELS", "value": "qwen3:8b"},
            *extra,
        ]

    def test_validate_blocks_private_lan_host_by_default(self) -> None:
        os.environ.pop("LLM_ALLOW_PRIVATE_BASE_URLS", None)
        validation = self.service.validate(items=self._channel_items("http://192.168.1.20:11434/v1"))
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "ssrf_blocked" for issue in validation["issues"]))

    def test_validate_accepts_private_lan_host_when_flag_submitted_in_same_draft(self) -> None:
        os.environ.pop("LLM_ALLOW_PRIVATE_BASE_URLS", None)
        validation = self.service.validate(
            items=self._channel_items(
                "http://192.168.1.20:11434/v1",
                {"key": "LLM_ALLOW_PRIVATE_BASE_URLS", "value": "true"},
            )
        )
        self.assertFalse(
            any(issue["code"] == "ssrf_blocked" for issue in validation["issues"]),
            validation["issues"],
        )

    def test_validate_still_blocks_metadata_with_flag(self) -> None:
        validation = self.service.validate(
            items=self._channel_items(
                "http://169.254.169.254/latest/meta-data/",
                {"key": "LLM_ALLOW_PRIVATE_BASE_URLS", "value": "true"},
            )
        )
        self.assertTrue(any(issue["code"] == "ssrf_blocked" for issue in validation["issues"]))


class DocsAuthGateTests(unittest.TestCase):
    def setUp(self) -> None:
        auth._auth_enabled = None
        auth._session_secret = None
        auth._rate_limit = {}
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.auth_patcher = patch.object(auth, "_is_auth_enabled_from_env", return_value=True)
        self.data_dir_patcher = patch.object(auth, "_get_data_dir", return_value=self.data_dir)
        self.auth_patcher.start()
        self.data_dir_patcher.start()

        app = FastAPI(docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")

        @app.get("/api/v1/ping")
        async def ping():
            return {"ok": True}

        @app.get("/health")
        async def health():
            return {"ok": True}

        add_auth_middleware(app)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_patcher.stop()
        self.data_dir_patcher.stop()
        auth._auth_enabled = None
        auth._session_secret = None
        self.temp_dir.cleanup()

    def test_docs_pages_redirect_to_login_without_session(self) -> None:
        for path in ("/docs", "/redoc"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], f"/login?redirect={path}")

    def test_openapi_schema_requires_session(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "unauthorized")

    def test_docs_reachable_with_valid_session(self) -> None:
        token = auth.create_session()
        cookies = {auth.COOKIE_NAME: token}
        self.assertEqual(self.client.get("/openapi.json", cookies=cookies).status_code, 200)
        self.assertEqual(self.client.get("/docs", cookies=cookies).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/ping", cookies=cookies).status_code, 200)

    def test_health_stays_public(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_docs_public_when_auth_disabled(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", return_value=False):
            auth._auth_enabled = None
            self.assertEqual(self.client.get("/openapi.json").status_code, 200)
            self.assertEqual(self.client.get("/docs").status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
