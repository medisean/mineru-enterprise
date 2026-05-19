import sys
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qs


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config_module = types.ModuleType("app.core.config")
config_module.settings = types.SimpleNamespace(
    SSO_DEBUG_LOG_SECRETS=False,
    OIDC_ENABLED=False,
    OAUTH2_ENABLED=False,
    LDAP_ENABLED=False,
    WECHAT_WORK_ENABLED=False,
    DINGTALK_ENABLED=False,
)
sys.modules["app.core.config"] = config_module

structlog_module = types.ModuleType("structlog")
structlog_module.get_logger = lambda *args, **kwargs: types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
sys.modules["structlog"] = structlog_module

authlib_module = types.ModuleType("authlib")
integrations_module = types.ModuleType("authlib.integrations")
httpx_client_module = types.ModuleType("authlib.integrations.httpx_client")
httpx_client_module.AsyncOAuth2Client = object
sys.modules["authlib"] = authlib_module
sys.modules["authlib.integrations"] = integrations_module
sys.modules["authlib.integrations.httpx_client"] = httpx_client_module

from app.services import sso  # noqa: E402


class _FakeResponse:
    status_code = 200
    text = '{"sub":"user-1"}'
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {"sub": "user-1"}


class _FakeAsyncClient:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, content=None, headers=None, params=None):
        self.calls.append({
            "method": "POST",
            "url": url,
            "content": content,
            "headers": headers or {},
            "params": params or {},
        })
        return _FakeResponse()

    async def get(self, url, headers=None, params=None):
        self.calls.append({
            "method": "GET",
            "url": url,
            "headers": headers or {},
            "params": params or {},
        })
        return _FakeResponse()


class UserinfoRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_oauth2_userinfo_posts_required_form_body_first(self):
        original_client = sso.httpx.AsyncClient
        _FakeAsyncClient.calls = []
        sso.httpx.AsyncClient = _FakeAsyncClient
        try:
            await sso._fetch_userinfo(
                "https://idp.example.com/userinfo",
                "token-value",
                {"access_token": "token-value"},
                "client-id",
                "base.profile",
            )
        finally:
            sso.httpx.AsyncClient = original_client

        self.assertEqual(_FakeAsyncClient.calls[0]["method"], "POST")
        self.assertEqual(
            _FakeAsyncClient.calls[0]["headers"],
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = parse_qs(_FakeAsyncClient.calls[0]["content"])
        self.assertEqual(body["client_id"], ["client-id"])
        self.assertEqual(body["access_token"], ["token-value"])
        self.assertEqual(body["scope"], ["base.profile"])


if __name__ == "__main__":
    unittest.main()
