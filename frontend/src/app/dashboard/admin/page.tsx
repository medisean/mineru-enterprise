"use client";

import { useQuery } from "@tanstack/react-query";
import { Users, FileText, CheckCircle, HardDrive } from "lucide-react";
import { adminApi } from "@/lib/api";
import { useT } from "@/lib/i18n/use-translation";
import StatsCard from "@/components/admin/stats-card";

export default function AdminDashboardPage() {
  const t = useT();
  const { data: stats, isLoading } = useQuery({
    queryKey: ["admin-stats"],
    queryFn: async () => {
      const res = await adminApi.getStats();
      return res.data;
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-400" />
      </div>
    );
  }

  const successRate = stats?.total_tasks
    ? Math.round(
        (((stats.tasks_by_status?.success || 0) / stats.total_tasks) * 10000) / 100
      )
    : 0;

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">{t("admin.dashboard")}</h1>

      {/* Stats cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title={t("admin.totalUsers")}
          value={stats?.total_users ?? 0}
          icon={Users}
          color="blue"
        />
        <StatsCard
          title={t("admin.totalTasks")}
          value={stats?.total_tasks ?? 0}
          icon={FileText}
          color="purple"
        />
        <StatsCard
          title={t("admin.successRate")}
          value={`${successRate}%`}
          icon={CheckCircle}
          color="green"
        />
        <StatsCard
          title={t("admin.storageUsed")}
          value={`${stats?.total_storage_mb ?? 0} MB`}
          icon={HardDrive}
          color="amber"
        />
      </div>

      {/* Tasks by status */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-medium text-gray-700 mb-4">{t("admin.tasksByStatus")}</h2>
        <div className="space-y-3">
          {["pending", "processing", "success", "failed", "cancelled"].map((status) => {
            const count = stats?.tasks_by_status?.[status] || 0;
            const total = stats?.total_tasks || 1;
            const pct = Math.round((count / total) * 100);
            const colorMap: Record<string, string> = {
              pending: "bg-gray-400",
              processing: "bg-blue-500",
              success: "bg-emerald-500",
              failed: "bg-red-500",
              cancelled: "bg-amber-500",
            };
            return (
              <div key={status} className="flex items-center gap-3">
                <span className="text-xs text-gray-500 w-20 capitalize">{status}</span>
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${colorMap[status] || "bg-gray-400"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-xs text-gray-600 w-16 text-right">
                  {count} ({pct}%)
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Recent users */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-medium text-gray-700 mb-4">{t("admin.recentUsers")}</h2>
        {stats?.recent_users?.length ? (
          <div className="divide-y divide-gray-100">
            {stats.recent_users.map((u: { id: string; username: string; email: string; created_at: string }) => (
              <div key={u.id} className="flex items-center justify-between py-2.5">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-xs font-medium text-blue-700">
                    {u.username[0]?.toUpperCase()}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900">{u.username}</p>
                    <p className="text-xs text-gray-500">{u.email}</p>
                  </div>
                </div>
                <span className="text-xs text-gray-400">
                  {new Date(u.created_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400">{t("admin.noData")}</p>
        )}
      </div>
    </div>
  );
}
