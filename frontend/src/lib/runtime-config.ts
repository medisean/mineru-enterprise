type RuntimeConfig = {
  NEXT_PUBLIC_API_URL?: string;
  NEXT_PUBLIC_APP_NAME?: string;
  NEXT_PUBLIC_OIDC_ENABLED?: string;
  NEXT_PUBLIC_OAUTH2_ENABLED?: string;
  NEXT_PUBLIC_WECHAT_WORK_ENABLED?: string;
  NEXT_PUBLIC_DINGTALK_ENABLED?: string;
  NEXT_PUBLIC_LOCAL_LOGIN_ENABLED?: string;
  NEXT_PUBLIC_USER_INFO_VISIBLE?: string;
};

declare global {
  interface Window {
    __MINERU_RUNTIME_CONFIG__?: RuntimeConfig;
  }
}

function getRuntimeConfig(): RuntimeConfig {
  if (typeof window !== "undefined") {
    return window.__MINERU_RUNTIME_CONFIG__ ?? {};
  }
  return {};
}

export function getRuntimeEnv(key: keyof RuntimeConfig, fallback = ""): string {
  const runtimeValue = getRuntimeConfig()[key];
  if (runtimeValue !== undefined) return runtimeValue;
  return fallback;
}

export function getApiOrigin(): string {
  const configuredOrigin = getRuntimeEnv("NEXT_PUBLIC_API_URL", "").replace(/\/+$/, "");
  if (configuredOrigin) return configuredOrigin;
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

export function getApiBaseUrl(): string {
  const origin = getApiOrigin();
  return `${origin}/api/v1`;
}

export function getWebSocketBaseUrl(): string {
  const origin = getApiOrigin();
  if (origin) return origin.replace(/^http/, "ws");
  return "";
}

export function isRuntimeEnabled(key: keyof RuntimeConfig): boolean {
  return getRuntimeEnv(key, "false") === "true";
}
