"use client";
/**
 * SSO callback page — handles OAuth code exchange.
 * URL pattern: /auth/callback?code=xxx&state=yyy&provider=zzz
 */
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { authApi } from "@/lib/api";
import { Loader2, CheckCircle, XCircle } from "lucide-react";
import { useT } from "@/lib/i18n/use-translation";
import { t as _t } from "@/lib/i18n";
import { useI18nStore } from "@/lib/i18n-store";

function CallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setTokens, fetchMe } = useAuthStore();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const t = useT();
  const locale = useI18nStore((s) => s.locale);

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const provider = searchParams.get("provider") || state?.split(":")[0];

    if (!code || !state) {
      setStatus("error");
      setErrorMsg(t("callback.missingParams"));
      return;
    }

    (async () => {
      try {
        const providerName = provider || "oidc";
        const res = await authApi.ssoCallback(providerName, code, state);
        setTokens(res.data.access_token, res.data.refresh_token);
        await fetchMe();
        setStatus("success");
        setTimeout(() => router.push("/dashboard"), 800);
      } catch (err: unknown) {
        setStatus("error");
        setErrorMsg(err instanceof Error ? err.message : t("callback.ssoFailed"));
      }
    })();
  }, [searchParams, setTokens, fetchMe, router, t]);

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        {status === "loading" && (
          <>
            <Loader2 className="h-8 w-8 animate-spin text-blue-500 mx-auto mb-4" />
            <p className="text-sm text-gray-600">{t("callback.verifying")}</p>
          </>
        )}
        {status === "success" && (
          <>
            <CheckCircle className="h-8 w-8 text-green-500 mx-auto mb-4" />
            <p className="text-sm text-green-600">{t("callback.success")}</p>
          </>
        )}
        {status === "error" && (
          <>
            <XCircle className="h-8 w-8 text-red-400 mx-auto mb-4" />
            <p className="text-sm text-red-500 mb-3">{errorMsg}</p>
            <button
              onClick={() => router.push("/login")}
              className="text-sm text-blue-600 hover:underline"
            >
              {t("callback.backToLogin")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  const locale = useI18nStore((s) => s.locale);
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
          <div className="text-center">
            <Loader2 className="h-8 w-8 animate-spin text-blue-500 mx-auto mb-4" />
            <p className="text-sm text-gray-600">{_t(locale, "callback.verifying")}</p>
          </div>
        </div>
      }
    >
      <CallbackContent />
    </Suspense>
  );
}
