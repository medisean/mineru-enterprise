"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Clock, CheckCircle2, XCircle, AlertCircle, Loader2 } from "lucide-react";
import { adminApi } from "@/lib/api";
import { useT } from "@/lib/i18n/use-translation";

type QuickRange = "24h" | "7d" | "30d" | "all" | "";

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode }> = {
  pending: { color: "bg-yellow-100 text-yellow-700", icon: <Clock className="w-3 h-3" /> },
  processing: { color: "bg-blue-100 text-blue-700", icon: <Loader2 className="w-3 h-3 animate-spin" /> },
  success: { color: "bg-emerald-100 text-emerald-700", icon: <CheckCircle2 className="w-3 h-3" /> },
  failed: { color: "bg-red-100 text-red-700", icon: <XCircle className="w-3 h-3" /> },
  cancelled: { color: "bg-gray-100 text-gray-600", icon: <AlertCircle className="w-3 h-3" /> },
};

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "-";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${rm}m`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function AdminTasksPage() {
  const t = useT();
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [activeRange, setActiveRange] = useState<QuickRange>("all");
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const { data, isLoading } = useQuery({
    queryKey: ["admin-tasks", page, statusFilter, dateFrom, dateTo],
    queryFn: async () => {
      const res = await adminApi.listTasks({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      return res.data;
    },
  });

  const totalPages = data ? Math.ceil(data.total / pageSize) : 1;

  const applyQuickRange = (range: QuickRange) => {
    setActiveRange(range);
    setPage(1);
    switch (range) {
      case "24h": setDateFrom(daysAgo(1)); setDateTo(today()); break;
      case "7d": setDateFrom(daysAgo(7)); setDateTo(today()); break;
      case "30d": setDateFrom(daysAgo(30)); setDateTo(today()); break;
      case "all": setDateFrom(""); setDateTo(""); break;
    }
  };

  const handleDateFromChange = (val: string) => {
    setDateFrom(val);
    setActiveRange("");
    setPage(1);
  };

  const handleDateToChange = (val: string) => {
    setDateTo(val);
    setActiveRange("");
    setPage(1);
  };

  const quickBtnClass = (range: QuickRange) =>
    `px-3 py-1 text-xs font-medium rounded-full transition-all ${
      activeRange === range
        ? "bg-blue-100 text-blue-700 ring-1 ring-blue-500/30"
        : "bg-gray-50 text-gray-600 hover:bg-gray-100 border border-gray-200"
    }`;

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">
          {t("admin.taskHistory")}
          <span className="ml-2 text-sm font-normal text-gray-400">{t("admin.total")}: {data?.total ?? 0}</span>
        </h1>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        {/* Row 1: Date range + Status */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Date from */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-gray-500">{t("admin.dateFrom")}</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => handleDateFromChange(e.target.value)}
              className="w-[140px] px-3 py-1.5 text-sm bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 hover:bg-white transition-colors"
            />
          </div>
          <span className="text-gray-300">—</span>
          {/* Date to */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-gray-500">{t("admin.dateTo")}</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => handleDateToChange(e.target.value)}
              className="w-[140px] px-3 py-1.5 text-sm bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 hover:bg-white transition-colors"
            />
          </div>
          {/* Status */}
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="px-3 py-1.5 text-sm bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 hover:bg-white transition-colors"
          >
            <option value="">{t("admin.allStatus")}</option>
            <option value="pending">{t("status.pending")}</option>
            <option value="processing">{t("status.processing")}</option>
            <option value="success">{t("status.success")}</option>
            <option value="failed">{t("status.failed")}</option>
            <option value="cancelled">{t("status.cancelled")}</option>
          </select>
        </div>
        {/* Row 2: Quick range buttons */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 mr-1">{t("admin.quickFilter")}:</span>
          <button onClick={() => applyQuickRange("all")} className={quickBtnClass("all")}>
            {t("admin.allTime")}
          </button>
          <button onClick={() => applyQuickRange("24h")} className={quickBtnClass("24h")}>
            {t("admin.last24h")}
          </button>
          <button onClick={() => applyQuickRange("7d")} className={quickBtnClass("7d")}>
            {t("admin.last7d")}
          </button>
          <button onClick={() => applyQuickRange("30d")} className={quickBtnClass("30d")}>
            {t("admin.last30d")}
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.taskName")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.status")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.username")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.fileSize")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.duration")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.engine")}</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">{t("admin.created")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">{t("admin.loading")}</td></tr>
              ) : !data?.items?.length ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">{t("admin.noTasks")}</td></tr>
              ) : (
                data.items.map((task: {
                  id: string;
                  original_filename: string;
                  status: string;
                  username?: string;
                  file_size_bytes: number;
                  duration_s?: number | null;
                  backend: string;
                  created_at: string;
                  error_message?: string;
                }) => {
                  const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
                  return (
                    <tr key={task.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                          <div className="min-w-0">
                            <p className="font-medium text-gray-900 truncate max-w-[280px]">{task.original_filename}</p>
                            {task.status === "failed" && task.error_message && (
                              <p className="text-xs text-red-500 truncate max-w-[280px]" title={task.error_message}>{task.error_message}</p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${cfg.color}`}>
                          {cfg.icon}
                          {t(`status.${task.status}`)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{task.username || "-"}</td>
                      <td className="px-4 py-3 text-gray-600">{formatFileSize(task.file_size_bytes)}</td>
                      <td className="px-4 py-3 text-gray-600 font-mono text-xs">{formatDuration(task.duration_s)}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{task.backend || "auto"}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {new Date(task.created_at).toLocaleString()}
                      </td>
                    </tr>
                  );
                })
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
    </div>
  );
}
