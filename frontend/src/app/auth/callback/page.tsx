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

function CallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setTokens, fetchMe } = useAuthStore();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const provider = searchParams.get("provider") || state?.split(":")[0];

    if (!code || !state) {
      setStatus("error");
      setErrorMsg("缺少授权参数，请重新登录");
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
        setErrorMsg(err instanceof Error ? err.message : "SSO 登录失败，请联系管理员");
      }
    })();
  }, [searchParams, setTokens, fetchMe, router]);

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        {status === "loading" && (
          <>
            <Loader2 className="h-8 w-8 animate-spin text-blue-500 mx-auto mb-4" />
            <p className="text-sm text-gray-600">正在验证登录信息...</p>
          </>
        )}
        {status === "success" && (
          <>
            <CheckCircle className="h-8 w-8 text-green-500 mx-auto mb-4" />
            <p className="text-sm text-green-600">登录成功，正在跳转...</p>
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
              返回登录页
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
          <div className="text-center">
            <Loader2 className="h-8 w-8 animate-spin text-blue-500 mx-auto mb-4" />
            <p className="text-sm text-gray-600">正在验证登录信息...</p>
          </div>
        </div>
      }
    >
      <CallbackContent />
    </Suspense>
  );
}
