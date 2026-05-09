"""
SSO Authentication Service.
Supports: Local, OIDC, LDAP, WeChat Work, DingTalk.
"""
import httpx
import structlog
from typing import Optional

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
        async with AsyncOAuth2Client(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=redirect_uri,
        ) as client:
            token = await client.fetch_token(meta["token_endpoint"], code=code)
            userinfo = await client.get(meta["userinfo_endpoint"])
            return userinfo.json()


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
ldap_service = LDAPAuthService()
wechat_work_oauth = WeChatWorkOAuth() if settings.WECHAT_WORK_ENABLED else None
dingtalk_oauth = DingTalkOAuth() if settings.DINGTALK_ENABLED else None
