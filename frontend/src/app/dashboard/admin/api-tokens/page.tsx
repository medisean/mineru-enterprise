"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clipboard, KeyRound, Loader2, Plus, Power, Trash2, X } from "lucide-react";
import { adminApi } from "@/lib/api";
import { useT } from "@/lib/i18n/use-translation";

interface ApiTokenItem {
  id: string;
  name: string;
  prefix: string;
  suffix: string;
  is_active: boolean;
  created_by_username?: string | null;
  created_at: string;
  last_used_at?: string | null;
}

export default function AdminApiTokensPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [createdToken, setCreatedToken] = useState<string | null>(null);
  const [createdName, setCreatedName] = useState("");
  const [copied, setCopied] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ApiTokenItem | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-api-tokens"],
    queryFn: async () => {
      const res = await adminApi.listApiTokens();
      return res.data as ApiTokenItem[];
    },
  });

  const createMutation = useMutation({
    mutationFn: (payload: { name: string }) => adminApi.createApiToken(payload),
    onSuccess: (res) => {
      setCreatedToken(res.data.token);
      setCreatedName(res.data.item.name);
      setName("");
      setCopied(false);
      queryClient.invalidateQueries({ queryKey: ["admin-api-tokens"] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ tokenId, isActive }: { tokenId: string; isActive: boolean }) =>
      adminApi.updateApiToken(tokenId, { is_active: isActive }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-api-tokens"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (tokenId: string) => adminApi.deleteApiToken(tokenId),
    onSuccess: () => {
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["admin-api-tokens"] });
    },
  });

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    createMutation.mutate({ name: trimmed });
  };

  const copyToken = async () => {
    if (!createdToken) return;
    await navigator.clipboard.writeText(createdToken);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const tokens = data ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">{t("admin.apiTokens")}</h1>
          <p className="mt-1 text-sm text-gray-500">{t("admin.difyBaseUrl")}: <code className="text-gray-700">http://host.docker.internal:8000</code></p>
        </div>
      </div>

      <form onSubmit={handleCreate} className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="flex flex-col sm:flex-row sm:items-end gap-3">
          <label className="flex-1 min-w-0">
            <span className="block text-sm font-medium text-gray-700 mb-1">{t("admin.tokenName")}</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={128}
              placeholder={t("admin.tokenNamePlaceholder")}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </label>
          <button
            type="submit"
            disabled={!name.trim() || createMutation.isPending}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {createMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            {t("admin.createApiToken")}
          </button>
        </div>
      </form>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.tokenName")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.tokenPreview")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.status")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.createdBy")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.created")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.lastUsed")}</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">{t("admin.actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">{t("admin.loading")}</td></tr>
              ) : tokens.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">{t("admin.noApiTokens")}</td></tr>
              ) : (
                tokens.map((token) => (
                  <tr key={token.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <KeyRound className="w-4 h-4 text-gray-400" />
                        <span className="font-medium text-gray-900">{token.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <code className="text-xs text-gray-600 bg-gray-100 px-2 py-1 rounded">{token.prefix}...{token.suffix}</code>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full ${
                        token.is_active ? "bg-emerald-100 text-emerald-700" : "bg-gray-100 text-gray-500"
                      }`}>
                        {token.is_active ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
                        {token.is_active ? t("admin.active") : t("admin.disabled")}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{token.created_by_username || "-"}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{formatDate(token.created_at)}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {token.last_used_at ? formatDate(token.last_used_at) : t("admin.neverUsed")}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex items-center justify-end gap-1">
                        <button
                          onClick={() => updateMutation.mutate({ tokenId: token.id, isActive: !token.is_active })}
                          disabled={updateMutation.isPending}
                          className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition disabled:opacity-40"
                          title={token.is_active ? t("admin.disable") : t("admin.enable")}
                        >
                          <Power className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setDeleteTarget(token)}
                          className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition"
                          title={t("admin.deleteApiToken")}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {createdToken && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-xl w-full mx-4 shadow-xl">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <h3 className="text-base font-semibold text-gray-900">{t("admin.tokenCreated")}</h3>
                <p className="text-sm text-gray-500 mt-1">{createdName}</p>
              </div>
              <button onClick={() => setCreatedToken(null)} className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg">
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-sm text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 mb-3">
              {t("admin.tokenCreatedHint")}
            </p>
            <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg p-2">
              <code className="flex-1 min-w-0 text-xs text-gray-700 break-all">{createdToken}</code>
              <button
                onClick={copyToken}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-800"
              >
                {copied ? <Check className="w-4 h-4" /> : <Clipboard className="w-4 h-4" />}
                {copied ? t("admin.copied") : t("admin.copy")}
              </button>
            </div>
            <div className="mt-4 text-sm text-gray-600 space-y-1">
              <p>{t("admin.authHeader")}: <code>Authorization: Bearer {createdToken}</code></p>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-sm w-full mx-4 shadow-xl">
            <h3 className="text-base font-semibold text-gray-900 mb-2">{t("admin.confirmDelete")}</h3>
            <p className="text-sm text-gray-600 mb-5">
              {t("admin.deleteApiTokenConfirm", { name: deleteTarget.name })}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleteTarget(null)}
                className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
              >
                {t("admin.cancel")}
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteTarget.id)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {t("admin.delete")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function formatDate(value: string) {
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
