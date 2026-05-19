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
            logger.warning(
                "OIDC token response missing access_token",
                token_keys=_safe_dict_keys(token),
                token_error=_token_error_summary(token),
            )
            return {}
        userinfo = await _fetch_userinfo(meta["userinfo_endpoint"], access_token, token, self.client_id)
        if _token_error_summary(userinfo):
            fallback_userinfo = _userinfo_from_token_response(token)
            if fallback_userinfo:
                return fallback_userinfo
            logger.warning(
                "OIDC userinfo endpoint returned no user info",
                userinfo_keys=_safe_dict_keys(userinfo),
                userinfo_error=_token_error_summary(userinfo),
            )
            return {}
        return userinfo


class OAuth2Provider:
    """Generic OAuth2 provider for Huawei IDaaS and similar corporate IdPs."""

    def __init__(self):
        self.authorization_url = settings.OAUTH2_AUTHORIZATION_URL
        self.token_url = settings.OAUTH2_TOKEN_URL
        self.userinfo_url = settings.OAUTH2_USERINFO_URL
        self.client_id = settings.OAUTH2_CLIENT_ID
        self.client_secret = settings.OAUTH2_CLIENT_SECRET

    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        logger.info(
            "OAuth2 authorization URL requested",
            authorization_url=self.authorization_url,
            redirect_uri=redirect_uri,
            scope=settings.OAUTH2_SCOPE,
            state_prefix=_state_prefix(state),
        )
        client = AsyncOAuth2Client(
            client_id=self.client_id,
            redirect_uri=redirect_uri,
            scope=settings.OAUTH2_SCOPE,
        )
        url, _ = client.create_authorization_url(self.authorization_url, state=state)
        logger.info("OAuth2 authorization URL generated", state_prefix=_state_prefix(state))
        _log_sso_secret_debug(
            "OAuth2 authorization URL generated with secrets",
            authorization_url=url,
            client_id=self.client_id,
            state=state,
            redirect_uri=redirect_uri,
            scope=settings.OAUTH2_SCOPE,
        )
        return url

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        logger.info(
            "OAuth2 code exchange started",
            token_url=self.token_url,
            userinfo_url=self.userinfo_url,
            redirect_uri=redirect_uri,
            token_auth_method=settings.OAUTH2_TOKEN_AUTH_METHOD,
            code_present=bool(code),
        )
        _log_sso_secret_debug(
            "OAuth2 code exchange started with secrets",
            code=code,
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=redirect_uri,
            token_url=self.token_url,
            userinfo_url=self.userinfo_url,
            token_auth_method=settings.OAUTH2_TOKEN_AUTH_METHOD,
        )
        token = await self._fetch_token(code, redirect_uri)

        access_token = _extract_access_token(token)
        logger.info(
            "OAuth2 token response parsed",
            token_keys=_safe_dict_keys(token),
            token_error=_token_error_summary(token),
            access_token_present=bool(access_token),
            token_type=_extract_token_type(token) or "",
            id_token_present=_has_id_token(token),
        )
        _log_sso_secret_debug("OAuth2 token response parsed with secrets", token_response=token)
        if not access_token:
            user_info = _userinfo_from_token_response(token)
            if user_info:
                logger.info(
                    "OAuth2 user info extracted from token response",
                    userinfo_keys=_safe_dict_keys(_unwrap_payload(user_info)),
                )
                return self._normalize_user_info(user_info)
            logger.warning(
                "OAuth2 token response missing access_token",
                token_keys=_safe_dict_keys(token),
                token_error=_token_error_summary(token),
            )
            return {}

        userinfo = await _fetch_userinfo(self.userinfo_url, access_token, token, self.client_id)
        logger.info(
            "OAuth2 userinfo response parsed",
            userinfo_keys=_safe_dict_keys(_unwrap_payload(userinfo)),
            userinfo_error=_token_error_summary(_unwrap_payload(userinfo)),
        )
        _log_sso_secret_debug("OAuth2 userinfo response parsed with secrets", userinfo_response=userinfo)
        return self._normalize_user_info(userinfo)

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
            logger.warning(
                "OAuth2 userinfo missing subject",
                userinfo_keys=_safe_dict_keys(data),
                userinfo_error=_token_error_summary(data),
            )
            return {}
        logger.info(
            "OAuth2 userinfo normalized",
            subject_present=True,
            email_present=bool(email),
            name_present=bool(name),
            avatar_present=bool(data.get(settings.OAUTH2_AVATAR_FIELD) or data.get("picture") or data.get("avatar_url") or data.get("avatarUrl")),
        )
        _log_sso_secret_debug(
            "OAuth2 userinfo normalized with secrets",
            normalized_subject=str(subject),
            normalized_email=email or f"{subject}@oauth2.local",
            normalized_name=name,
            raw_userinfo=data,
        )
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
    logger.info(
        "SSO token request sending",
        token_url=token_url,
        redirect_uri=redirect_uri,
        token_auth_method=token_auth_method,
        form_keys=sorted(key for key in form.keys() if key not in {"code", "client_secret"}),
        code_present=bool(code),
        client_secret_present=bool(client_secret),
    )
    _log_sso_secret_debug(
        "SSO token request sending with secrets",
        token_url=token_url,
        redirect_uri=redirect_uri,
        token_auth_method=token_auth_method,
        form=form,
        encoded_form=urlencode(form),
        headers=headers,
        basic_auth_client_id=client_id if auth else None,
        basic_auth_client_secret=client_secret if auth else None,
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            content=urlencode(form),
            headers=headers,
            auth=auth,
        )
        logger.info("SSO token response received", token_url=token_url, status_code=response.status_code)
        _log_sso_secret_debug(
            "SSO token response received with secrets",
            token_url=token_url,
            status_code=response.status_code,
            response_text=response.text,
            response_headers=dict(response.headers),
        )
        response.raise_for_status()
        token = response.json()
        logger.info(
            "SSO token response decoded",
            token_url=token_url,
            token_keys=_safe_dict_keys(token),
            token_error=_token_error_summary(token),
            access_token_present=bool(_extract_access_token(token)),
            token_type=_extract_token_type(token) or "",
            id_token_present=_has_id_token(token),
        )
        _log_sso_secret_debug("SSO token response decoded with secrets", token_response=token)
        if _token_error_summary(token):
            logger.warning(
                "SSO token endpoint returned error payload",
                token_keys=_safe_dict_keys(token),
                token_error=_token_error_summary(token),
                token_auth_method=token_auth_method,
            )
        return token


async def _fetch_userinfo(userinfo_url: str, access_token: str, token_response: dict, client_id: str = "") -> dict:
    token_type = _extract_token_type(token_response)
    attempts: list[tuple[str, dict, dict]] = [
        ("bearer_authorization", {"Authorization": f"Bearer {access_token}"}, {}),
    ]
    if token_type and token_type.lower() != "bearer":
        attempts.append((f"{token_type}_authorization", {"Authorization": f"{token_type} {access_token}"}, {}))
    attempts.extend([
        ("access_token_header", {"access_token": access_token}, {}),
        ("access_token_query", {}, {"access_token": access_token}),
    ])
    if client_id:
        attempts.extend([
            ("bearer_authorization_client_id_query", {"Authorization": f"Bearer {access_token}"}, {"client_id": client_id}),
            ("access_token_header_client_id_header", {"access_token": access_token, "client_id": client_id}, {}),
            ("access_token_query_client_id_query", {}, {"access_token": access_token, "client_id": client_id}),
        ])
        if token_type and token_type.lower() != "bearer":
            attempts.append((
                f"{token_type}_authorization_client_id_query",
                {"Authorization": f"{token_type} {access_token}"},
                {"client_id": client_id},
            ))

    last_payload: dict = {}
    logger.info(
        "SSO userinfo request sequence started",
        userinfo_url=userinfo_url,
        token_type=token_type or "",
        client_id_present=bool(client_id),
        attempt_methods=[attempt[0] for attempt in attempts],
    )
    async with httpx.AsyncClient() as client:
        for auth_method, headers, params in attempts:
            logger.info(
                "SSO userinfo request sending",
                userinfo_url=userinfo_url,
                userinfo_auth_method=auth_method,
                header_keys=sorted(headers.keys()),
                param_keys=sorted(params.keys()),
            )
            _log_sso_secret_debug(
                "SSO userinfo request sending with secrets",
                userinfo_url=userinfo_url,
                userinfo_auth_method=auth_method,
                headers=headers,
                params=params,
                access_token=access_token,
            )
            try:
                response = await client.get(userinfo_url, headers=headers, params=params)
                logger.info(
                    "SSO userinfo response received",
                    userinfo_url=userinfo_url,
                    userinfo_auth_method=auth_method,
                    status_code=response.status_code,
                )
                _log_sso_secret_debug(
                    "SSO userinfo response received with secrets",
                    userinfo_url=userinfo_url,
                    userinfo_auth_method=auth_method,
                    status_code=response.status_code,
                    response_text=response.text,
                    response_headers=dict(response.headers),
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                logger.warning("SSO userinfo request failed", userinfo_auth_method=auth_method, error=str(exc))
                continue

            last_payload = payload
            error_summary = _token_error_summary(payload)
            if not error_summary:
                logger.info(
                    "SSO userinfo request succeeded",
                    userinfo_auth_method=auth_method,
                    userinfo_keys=_safe_dict_keys(_unwrap_payload(payload)),
                    used_fallback=auth_method != "bearer_authorization",
                )
                _log_sso_secret_debug(
                    "SSO userinfo request succeeded with secrets",
                    userinfo_auth_method=auth_method,
                    userinfo_payload=payload,
                )
                return payload
            logger.warning(
                "SSO userinfo endpoint returned error payload",
                userinfo_auth_method=auth_method,
                userinfo_keys=_safe_dict_keys(payload),
                userinfo_error=error_summary,
            )

    return last_payload


def _safe_dict_keys(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value.keys())


def _log_sso_secret_debug(event: str, **fields) -> None:
    if settings.SSO_DEBUG_LOG_SECRETS:
        logger.warning(event, **fields)


def _token_error_summary(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    summary = {}
    for key in ("error", "error_description", "errorCode", "errorDesc", "message", "msg"):
        error_value = value.get(key)
        if isinstance(error_value, (str, int, float, bool)) and error_value != "":
            summary[key] = str(error_value)[:500]
    return summary


def _state_prefix(state: str) -> str:
    return state.split(":", 1)[0] if ":" in state else ""


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


def _extract_token_type(token: dict) -> str:
    for data in (token, _unwrap_payload(token)):
        for key in ("token_type", "tokenType"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _has_id_token(token: dict) -> bool:
    unwrapped = _unwrap_payload(token)
    return bool(token.get("id_token") or token.get("idToken") or unwrapped.get("id_token") or unwrapped.get("idToken"))


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
