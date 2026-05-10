import { authApi } from "@/lib/api";

export async function startSSOLogin(provider: string) {
  const res = await authApi.getSSOAuthUrl(provider);
  window.location.href = res.data.authorization_url;
}
