"use client";
/**
 * Root page — redirects based on auth status.
 * Logged in → /dashboard; not logged in → configured SSO or /login.
 */
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { authApi } from "@/lib/api";
import { startSSOLogin } from "@/lib/sso";

export default function HomePage() {
  const router = useRouter();
  const { accessToken, hasHydrated } = useAuthStore();
  const startedRef = useRef(false);

  useEffect(() => {
    if (!hasHydrated || startedRef.current) return;
    startedRef.current = true;

    if (accessToken) {
      router.replace("/dashboard");
      return;
    }

    (async () => {
      try {
        const res = await authApi.getSSOConfig();
        const provider = res.data.default_provider;
        if (res.data.auto_login_enabled && provider) {
          await startSSOLogin(provider);
          return;
        }
      } catch {
        // Fall through to local login when SSO config is unavailable.
      }
      router.replace("/login");
    })();
  }, [accessToken, hasHydrated, router]);

  return null;
}
