"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Trash2, Shield, UserCheck, UserX } from "lucide-react";
import { adminApi } from "@/lib/api";
import { useT } from "@/lib/i18n/use-translation";

const ROLE_OPTIONS = ["admin", "member"] as const;

export default function AdminUsersPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; username: string } | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-users", page, search, roleFilter],
    queryFn: async () => {
      const res = await adminApi.listUsers({ page, page_size: pageSize, search: search || undefined, role: roleFilter || undefined });
      return res.data;
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: { role?: string; is_active?: boolean; organization_id?: string } }) =>
      adminApi.updateUser(userId, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (userId: string) => adminApi.deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setDeleteTarget(null);
    },
  });

  const roleColor: Record<string, string> = {
    super_admin: "bg-amber-100 text-amber-700",
    admin: "bg-red-100 text-red-700",
    member: "bg-blue-100 text-blue-700",
  };

  const totalPages = data ? Math.ceil(data.total / pageSize) : 1;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">{t("admin.userManagement")}</h1>
        <span className="text-sm text-gray-500">{t("admin.total")}: {data?.total ?? 0}</span>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder={t("admin.searchUsers")}
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <select
          value={roleFilter}
          onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}
          className="px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="">{t("admin.allRoles")}</option>
          <option value="super_admin">{t("role.superAdmin")}</option>
          {ROLE_OPTIONS.map((role) => (
            <option key={role} value={role}>{t(`role.${role}`)}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.username")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.email")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.role")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.status")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.tasks")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.joinedAt")}</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">{t("admin.actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">{t("admin.loading")}</td></tr>
              ) : !data?.items?.length ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">{t("admin.noUsers")}</td></tr>
              ) : (
                data.items.map((u: {
                  id: string; username: string; email: string; role: string;
                  is_active: boolean; task_count: number;
                  created_at: string; is_superuser?: boolean;
                }) => (
                  <tr key={u.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-gray-900">{u.username}</span>
                        {u.is_superuser && <Shield className="w-3.5 h-3.5 text-amber-500" />}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{u.email}</td>
                    <td className="px-4 py-3">
                      {u.is_superuser ? (
                        <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full ${roleColor.super_admin}`}>
                          <Shield className="w-3 h-3" />
                          {t("role.superAdmin")}
                        </span>
                      ) : (
                        <select
                          value={u.role === "viewer" ? "member" : u.role}
                          onChange={(e) => updateMutation.mutate({ userId: u.id, data: { role: e.target.value } })}
                          className={`text-xs font-medium px-2 py-1 rounded-full border-0 cursor-pointer ${roleColor[u.role] || roleColor.member}`}
                        >
                          {ROLE_OPTIONS.map((role) => (
                            <option key={role} value={role}>{t(`role.${role}`)}</option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => updateMutation.mutate({ userId: u.id, data: { is_active: !u.is_active } })}
                        className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full cursor-pointer ${
                          u.is_active ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
                        }`}
                      >
                        {u.is_active ? <UserCheck className="w-3 h-3" /> : <UserX className="w-3 h-3" />}
                        {u.is_active ? t("admin.active") : t("admin.disabled")}
                      </button>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{u.task_count}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => setDeleteTarget({ id: u.id, username: u.username })}
                        disabled={u.is_superuser}
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition disabled:opacity-30 disabled:cursor-not-allowed"
                        title={t("admin.deleteUser")}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
          >
            {t("admin.prev")}
          </button>
          <span className="text-sm text-gray-500">{page} / {totalPages}</span>
          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
          >
            {t("admin.next")}
          </button>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-sm w-full mx-4 shadow-xl">
            <h3 className="text-base font-semibold text-gray-900 mb-2">{t("admin.confirmDelete")}</h3>
            <p className="text-sm text-gray-600 mb-5">
              {t("admin.deleteUserConfirm", { username: deleteTarget.username })}
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
