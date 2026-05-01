"use client";
/**
 * Login page — supports local login and SSO buttons.
 * Enhanced with registration toggle and improved UX.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import { authApi } from "@/lib/api";
import { Loader2, FileText } from "lucide-react";

const SSO_PROVIDERS = [
  { id: "oidc", label: "企业 SSO 登录", enabled: process.env.NEXT_PUBLIC_OIDC_ENABLED === "true" },
  { id: "wechat_work", label: "企业微信登录", enabled: process.env.NEXT_PUBLIC_WECHAT_WORK_ENABLED === "true" },
  { id: "dingtalk", label: "钉钉登录", enabled: process.env.NEXT_PUBLIC_DINGTALK_ENABLED === "true" },
];

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuthStore();
  const [isRegister, setIsRegister] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  // Login form
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Register form
  const [regEmail, setRegEmail] = useState("");
  const [regUsername, setRegUsername] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regFullName, setRegFullName] = useState("");

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await login(username, password);
      router.push("/dashboard");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (detail) {
        setError(detail);
      } else if (err?.response?.status === 0 || !err?.response) {
        setError("网络连接失败，请检查后端服务是否启动");
      } else {
        setError("登录失败，请稍后重试");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await authApi.register({
        email: regEmail,
        username: regUsername,
        password: regPassword,
        full_name: regFullName || undefined,
      });
      // Auto-login after registration
      await login(regUsername, regPassword);
      router.push("/dashboard");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (detail) {
        setError(detail);
      } else if (err?.response?.status === 0 || !err?.response) {
        setError("网络连接失败，请检查后端服务是否启动");
      } else {
        setError("注册失败，请稍后重试");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleSSO = async (provider: string) => {
    try {
      const res = await authApi.getSSOAuthUrl(provider);
      // Redirect to SSO provider with callback URL
      const callbackUrl = `${window.location.origin}/auth/callback?provider=${provider}`;
      const authUrl = res.data.authorization_url
        .replace(/redirect_uri=[^&]+/, `redirect_uri=${encodeURIComponent(callbackUrl)}`);
      window.location.href = authUrl;
    } catch {
      setError("SSO 跳转失败，请联系管理员");
    }
  };

  const enabledSSOProviders = SSO_PROVIDERS.filter((p) => p.enabled);

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="mx-auto w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center mb-4">
            <FileText className="h-6 w-6 text-white" />
          </div>
          <h1 className="text-2xl font-semibold text-gray-900">MinerU Enterprise</h1>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 space-y-4">
          {/* Tab switch */}
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            <button
              onClick={() => { setIsRegister(false); setError(""); }}
              className={`flex-1 text-sm font-medium py-2 rounded-md transition-colors ${
                !isRegister ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"
              }`}
            >
              登录
            </button>
            <button
              onClick={() => { setIsRegister(true); setError(""); }}
              className={`flex-1 text-sm font-medium py-2 rounded-md transition-colors ${
                isRegister ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"
              }`}
            >
              注册
            </button>
          </div>

          {!isRegister ? (
            /* Login form */
            <form onSubmit={handleLogin} className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">用户名 / 邮箱</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  placeholder="请输入用户名或邮箱"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">密码</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  placeholder="请输入密码"
                />
              </div>
              {error && <p className="text-xs text-red-500">{error}</p>}
              <button
                type="submit"
                disabled={isLoading}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                登录
              </button>
            </form>
          ) : (
            /* Register form */
            <form onSubmit={handleRegister} className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">邮箱</label>
                <input
                  type="email"
                  value={regEmail}
                  onChange={(e) => setRegEmail(e.target.value)}
                  required
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  placeholder="your@email.com"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">用户名</label>
                <input
                  type="text"
                  value={regUsername}
                  onChange={(e) => setRegUsername(e.target.value)}
                  required
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  placeholder="3-32 字符"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">密码</label>
                <input
                  type="password"
                  value={regPassword}
                  onChange={(e) => setRegPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  placeholder="至少 6 位"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">姓名（可选）</label>
                <input
                  type="text"
                  value={regFullName}
                  onChange={(e) => setRegFullName(e.target.value)}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  placeholder="真实姓名"
                />
              </div>
              {error && <p className="text-xs text-red-500">{error}</p>}
              <button
                type="submit"
                disabled={isLoading}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                注册并登录
              </button>
            </form>
          )}

          {/* SSO section */}
          {enabledSSOProviders.length > 0 && (
            <>
              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-gray-100" />
                </div>
                <div className="relative flex justify-center">
                  <span className="bg-white px-3 text-xs text-gray-400">或使用企业账号登录</span>
                </div>
              </div>
              <div className="space-y-2">
                {enabledSSOProviders.map((provider) => (
                  <button
                    key={provider.id}
                    onClick={() => handleSSO(provider.id)}
                    className="w-full border border-gray-200 hover:border-gray-300 hover:bg-gray-50 text-sm text-gray-700 py-2.5 rounded-lg transition-colors"
                  >
                    {provider.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

      </div>
    </div>
  );
}
