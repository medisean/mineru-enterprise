"""
SSO Authentication Service.
Supports: Local, OIDC, LDAP, WeChat Work, DingTalk.
"""
import httpx
import structlog
from typing import Optional
import base64
import json
from urllib.parse import urlencode

from authlib.integrations.httpx_client import AsyncOAuth2Client
from app.core.config import settings

logger = structlog.get_logger(__name__)


class OIDCProvider:
    """Generic OIDC provider (Keycloak, Azure AD, Okta, etc.)"""

    def __init__(self):
        self.issuer = settings.OIDC_ISSUER
        self.client_id = settings.OIDC_CLIENT_ID
        self.client_secret = settings.OIDC_CLIENT_SECRET
        self._metadata: Optional[dict] = None

    async def get_metadata(self) -> dict:
        if self._metadata:
            return self._metadata
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.issuer}/.well-known/openid-configuration")
            self._metadata = resp.json()
            return self._metadata

    async def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        meta = await self.get_metadata()
        client = AsyncOAuth2Client(
            client_id=self.client_id,
            redirect_uri=redirect_uri,
            scope=settings.OIDC_SCOPE,
        )
        url, _ = client.create_authorization_url(meta["authorization_endpoint"], state=state)
        return url

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        meta = await self.get_metadata()
        token = await _fetch_authorization_code_token(
            meta["token_endpoint"],
            self.client_id,
            self.client_secret,
            code,
            redirect_uri,
            _oidc_token_auth_method(meta),
        )
        access_token = _extract_access_token(token)
        if not access_token:
            user_info = _userinfo_from_token_response(token)
            if user_info:
                return user_info
            logger.warning("OIDC token response missing access_token", token_keys=_safe_dict_keys(token))
            return {}
        async with httpx.AsyncClient() as client:
            userinfo = await client.get(
                meta["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo.raise_for_status()
            return userinfo.json()


class OAuth2Provider:
    """Generic OAuth2 provider for Huawei IDaaS and similar corporate IdPs."""

    def __init__(self):
        self.authorization_url = settings.OAUTH2_AUTHORIZATION_URL
        self.token_url = settings.OAUTH2_TOKEN_URL
        self.userinfo_url = settings.OAUTH2_USERINFO_URL
        self.client_id = settings.OAUTH2_CLIENT_ID
        self.client_secret = settings.OAUTH2_CLIENT_SECRET

    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        client = AsyncOAuth2Client(
            client_id=self.client_id,
            redirect_uri=redirect_uri,
            scope=settings.OAUTH2_SCOPE,
        )
        url, _ = client.create_authorization_url(self.authorization_url, state=state)
        return url

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        token = await self._fetch_token(code, redirect_uri)

        access_token = _extract_access_token(token)
        if not access_token:
            user_info = _userinfo_from_token_response(token)
            if user_info:
                return self._normalize_user_info(user_info)
            logger.warning("OAuth2 token response missing access_token", token_keys=_safe_dict_keys(token))
            return {}

        # Some corporate IdPs return non-standard token_type values such as
        # "access_token". Use a plain HTTP client for userinfo so Authlib does
        # not reject the already-issued access token while attaching auth.
        async with httpx.AsyncClient() as client:
            userinfo = await client.get(
                self.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo.raise_for_status()
            return self._normalize_user_info(userinfo.json())

    def _normalize_user_info(self, raw: dict) -> dict:
        data = _unwrap_payload(raw)
        subject = (
            data.get(settings.OAUTH2_USER_ID_FIELD)
            or data.get("sub")
            or data.get("id")
            or data.get("user_id")
            or data.get("userid")
            or data.get("userId")
            or data.get("uid")
            or data.get("unionId")
            or data.get("unionid")
            or data.get("account")
            or data.get("username")
        )
        email = data.get(settings.OAUTH2_EMAIL_FIELD) or data.get("email") or ""
        name = (
            data.get(settings.OAUTH2_NAME_FIELD)
            or data.get("name")
            or data.get("displayName")
            or data.get("nick")
            or data.get("nickname")
            or email
            or str(subject or "")
        )
        if not subject:
            logger.warning("OAuth2 userinfo missing subject", userinfo_keys=_safe_dict_keys(data))
            return {}
        return {
            "sso_subject": str(subject),
            "email": email or f"{subject}@oauth2.local",
            "full_name": name,
            "avatar_url": data.get(settings.OAUTH2_AVATAR_FIELD) or data.get("picture") or data.get("avatar_url") or data.get("avatarUrl"),
        }

    async def _fetch_token(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code without Authlib token_type validation.

        Some corporate OAuth2 providers return non-standard token_type values
        such as "access_token". Authlib rejects those while parsing the token
        response, even though the access_token itself is usable.
        """
        return await _fetch_authorization_code_token(
            self.token_url,
            self.client_id,
            self.client_secret,
            code,
            redirect_uri,
            settings.OAUTH2_TOKEN_AUTH_METHOD,
        )


def _oidc_token_auth_method(metadata: dict) -> str:
    supported = metadata.get("token_endpoint_auth_methods_supported") or []
    if "client_secret_post" in supported:
        return "client_secret_post"
    return "client_secret_basic"


async def _fetch_authorization_code_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    token_auth_method: str,
) -> dict:
    """Exchange authorization code without Authlib token_type validation."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    auth = None
    if token_auth_method == "client_secret_basic":
        auth = (client_id, client_secret)
    else:
        form["client_id"] = client_id
        form["client_secret"] = client_secret

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            content=urlencode(form),
            headers=headers,
            auth=auth,
        )
        response.raise_for_status()
        return response.json()


def _safe_dict_keys(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value.keys())


def _unwrap_payload(value: dict) -> dict:
    data = value
    for key in ("data", "result", "user", "userinfo", "profile"):
        nested = data.get(key)
        if isinstance(nested, dict):
            data = nested
    return data


def _extract_access_token(token: dict) -> str:
    for data in (token, _unwrap_payload(token)):
        for key in ("access_token", "accessToken", "access-token", "token"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _userinfo_from_token_response(token: dict) -> dict:
    unwrapped = _unwrap_payload(token)
    for key in ("id_token", "idToken"):
        value = token.get(key) or unwrapped.get(key)
        if isinstance(value, str) and value:
            return _decode_jwt_payload(value)
    user_info_keys = {"sub", "id", "user_id", "userid", "userId", "uid", "unionId", "unionid", "account", "username", "email"}
    if any(key in unwrapped for key in user_info_keys):
        return unwrapped
    return {}


def _decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception as exc:
        logger.warning("Failed to decode id_token payload", error=str(exc))
        return {}


class LDAPAuthService:
    """LDAP / Active Directory authentication."""

    @staticmethod
    def _escape_ldap_filter(value: str) -> str:
        """Escape special characters in LDAP filter values to prevent injection.

        Per RFC 4515, the following characters must be escaped:
        * \\  -> \\5c
        * (  -> \\28
        * )  -> \\29
        * *  -> \\2a
        * \\x00 (NUL) -> \\00
        """
        return (
            value
            .replace("\\", "\\5c")
            .replace("(", "\\28")
            .replace(")", "\\29")
            .replace("*", "\\2a")
            .replace("\x00", "\\00")
        )

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        if not settings.LDAP_ENABLED:
            return None
        try:
            import ldap
            conn = ldap.initialize(settings.LDAP_SERVER)
            conn.simple_bind_s(settings.LDAP_BIND_DN, settings.LDAP_BIND_PASSWORD)

            safe_username = self._escape_ldap_filter(username)
            search_filter = settings.LDAP_USER_SEARCH_FILTER.format(username=safe_username)
            results = conn.search_s(
                settings.LDAP_BASE_DN,
                ldap.SCOPE_SUBTREE,
                search_filter,
                [settings.LDAP_ATTR_EMAIL, settings.LDAP_ATTR_NAME, "dn"],
            )
            if not results:
                return None

            user_dn, attrs = results[0]
            conn.simple_bind_s(user_dn, password)

            return {
                "email": attrs.get(settings.LDAP_ATTR_EMAIL, [b""])[0].decode(),
                "full_name": attrs.get(settings.LDAP_ATTR_NAME, [b""])[0].decode(),
                "sso_subject": user_dn,
            }
        except Exception as e:
            logger.warning("LDAP auth failed", username=username, error=str(e))
            return None


class WeChatWorkOAuth:
    """企业微信 OAuth login."""

    BASE = "https://qyapi.weixin.qq.com/cgi-bin"

    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        return (
            f"https://open.weixin.qq.com/connect/oauth2/authorize"
            f"?appid={settings.WECHAT_WORK_CORP_ID}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code&scope=snsapi_base&state={state}#wechat_redirect"
        )

    async def get_user_info(self, code: str) -> Optional[dict]:
        async with httpx.AsyncClient() as client:
            # Get access token
            token_resp = await client.get(
                f"{self.BASE}/gettoken",
                params={"corpid": settings.WECHAT_WORK_CORP_ID, "corpsecret": settings.WECHAT_WORK_SECRET},
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return None

            # Get user ID
            user_resp = await client.get(
                f"{self.BASE}/user/getuserinfo",
                params={"access_token": access_token, "code": code},
            )
            user_data = user_resp.json()
            userid = user_data.get("UserId")
            if not userid:
                return None

            # Get user detail
            detail_resp = await client.get(
                f"{self.BASE}/user/get",
                params={"access_token": access_token, "userid": userid},
            )
            detail = detail_resp.json()
            return {
                "sso_subject": userid,
                "email": detail.get("email", f"{userid}@wechat.work"),
                "full_name": detail.get("name", userid),
                "avatar_url": detail.get("avatar"),
            }


class DingTalkOAuth:
    """钉钉 OAuth login."""

    async def get_access_token(self) -> Optional[str]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oapi.dingtalk.com/gettoken",
                params={"appkey": settings.DINGTALK_APP_KEY, "appsecret": settings.DINGTALK_APP_SECRET},
            )
            data = resp.json()
            return data.get("access_token")

    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        return (
            f"https://login.dingtalk.com/oauth2/auth"
            f"?client_id={settings.DINGTALK_APP_KEY}"
            f"&response_type=code&scope=openid"
            f"&redirect_uri={redirect_uri}&state={state}&prompt=consent"
        )

    async def get_user_info(self, code: str) -> Optional[dict]:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
                json={
                    "clientId": settings.DINGTALK_APP_KEY,
                    "clientSecret": settings.DINGTALK_APP_SECRET,
                    "code": code,
                    "grantType": "authorization_code",
                },
            )
            token_data = token_resp.json()
            access_token = token_data.get("accessToken")
            if not access_token:
                return None

            me_resp = await client.get(
                "https://api.dingtalk.com/v1.0/contact/users/me",
                headers={"x-acs-dingtalk-access-token": access_token},
            )
            me = me_resp.json()
            return {
                "sso_subject": me.get("unionId"),
                "email": me.get("email", f"{me.get('unionId')}@dingtalk"),
                "full_name": me.get("nick", ""),
                "avatar_url": me.get("avatarUrl"),
            }


# Singleton instances
oidc_provider = OIDCProvider() if settings.OIDC_ENABLED else None
oauth2_provider = OAuth2Provider() if settings.OAUTH2_ENABLED else None
ldap_service = LDAPAuthService()
wechat_work_oauth = WeChatWorkOAuth() if settings.WECHAT_WORK_ENABLED else None
dingtalk_oauth = DingTalkOAuth() if settings.DINGTALK_ENABLED else None
