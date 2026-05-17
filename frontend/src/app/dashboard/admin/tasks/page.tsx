"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FileText, Clock, CheckCircle2, XCircle, AlertCircle, Loader2, Search, X,
  ChevronLeft, ChevronRight, FileSpreadsheet, FileImage, File,
} from "lucide-react";
import { adminApi } from "@/lib/api";
import { useT } from "@/lib/i18n/use-translation";

type QuickRange = "24h" | "7d" | "30d" | "all" | "";

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode }> = {
  pending: { color: "text-yellow-500", icon: <Clock className="h-4 w-4" /> },
  processing: { color: "text-blue-500", icon: <Loader2 className="h-4 w-4 animate-spin" /> },
  success: { color: "text-green-500", icon: <CheckCircle2 className="h-4 w-4" /> },
  failed: { color: "text-red-500", icon: <XCircle className="h-4 w-4" /> },
  cancelled: { color: "text-gray-400", icon: <AlertCircle className="h-4 w-4" /> },
};

const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
const PAGE_SIZE_STORAGE_KEY = "mineru.admin.tasks.pageSize";

const FILE_TYPE_MAP: Record<string, { icon: React.ElementType; color: string }> = {
  pdf:  { icon: FileText, color: "text-red-500" },
  docx: { icon: FileText, color: "text-blue-500" },
  pptx: { icon: File, color: "text-orange-500" },
  xlsx: { icon: FileSpreadsheet, color: "text-green-600" },
  png:  { icon: FileImage, color: "text-purple-500" },
  jpg:  { icon: FileImage, color: "text-purple-500" },
  jpeg: { icon: FileImage, color: "text-purple-500" },
  jp2:  { icon: FileImage, color: "text-purple-500" },
  gif:  { icon: FileImage, color: "text-purple-500" },
  bmp:  { icon: FileImage, color: "text-purple-500" },
  tiff: { icon: FileImage, color: "text-purple-500" },
  webp: { icon: FileImage, color: "text-purple-500" },
};

function getFileTypeInfo(filename: string): { icon: React.ElementType; color: string } {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return FILE_TYPE_MAP[ext] || { icon: FileText, color: "text-gray-400" };
}

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

function toDatetimeLocal(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("-") + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function minutesAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toDatetimeLocal(d);
}

function nowMinute(): string {
  return toDatetimeLocal(new Date());
}

function buildPageNumbers(current: number, total: number): (number | "...")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | "...")[] = [1];
  const left = Math.max(2, current - 1);
  const right = Math.min(total - 1, current + 1);
  if (left > 2) pages.push("...");
  for (let i = left; i <= right; i++) pages.push(i);
  if (right < total - 1) pages.push("...");
  pages.push(total);
  return pages;
}

export default function AdminTasksPage() {
  const t = useT();
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [activeRange, setActiveRange] = useState<QuickRange>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => {
    if (typeof window === "undefined") return 20;
    const saved = Number(window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY));
    return PAGE_SIZE_OPTIONS.includes(saved as (typeof PAGE_SIZE_OPTIONS)[number]) ? saved : 20;
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
      setPage(1);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-tasks", page, statusFilter, dateFrom, dateTo, debouncedSearch],
    queryFn: async () => {
      const res = await adminApi.listTasks({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        search: debouncedSearch || undefined,
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
      case "24h": setDateFrom(minutesAgo(1)); setDateTo(nowMinute()); break;
      case "7d": setDateFrom(minutesAgo(7)); setDateTo(nowMinute()); break;
      case "30d": setDateFrom(minutesAgo(30)); setDateTo(nowMinute()); break;
      case "all": setDateFrom(""); setDateTo(""); break;
    }
  };

  const hasFilters = Boolean(statusFilter || dateFrom || dateTo || debouncedSearch);

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
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-gray-900 whitespace-nowrap">
          {t("admin.taskHistory")}
        </h1>
      </div>

      {/* Filters */}
      <div className="flex flex-col gap-3 rounded-xl border border-gray-100 bg-white px-4 py-3">
        {/* Row 1: Search + Date range + Status */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[260px] flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("admin.searchTasks")}
              className="w-full pl-9 pr-9 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-colors bg-white"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                aria-label={t("admin.clearSearch")}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          {/* Date from */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">{t("admin.dateFrom")}</label>
            <input
              type="datetime-local"
              value={dateFrom}
              onChange={(e) => handleDateFromChange(e.target.value)}
              className="h-9 w-[185px] px-3 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 bg-white transition-colors"
            />
          </div>
          <span className="text-gray-300">—</span>
          {/* Date to */}
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">{t("admin.dateTo")}</label>
            <input
              type="datetime-local"
              value={dateTo}
              onChange={(e) => handleDateToChange(e.target.value)}
              className="h-9 w-[185px] px-3 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 bg-white transition-colors"
            />
          </div>
          {/* Status */}
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="h-9 px-3 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 bg-white transition-colors"
          >
            <option value="">{t("admin.allStatus")}</option>
            <option value="pending">{t("status.pending")}</option>
            <option value="processing">{t("status.processing")}</option>
            <option value="success">{t("status.success")}</option>
            <option value="failed">{t("status.failed")}</option>
            <option value="cancelled">{t("status.cancelled")}</option>
          </select>
          <span className="text-xs text-gray-400 whitespace-nowrap">
            {t("tasks.totalCount", { count: data?.total ?? 0 })}
          </span>
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
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t("admin.taskName")}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t("admin.status")}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t("admin.username")}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t("admin.fileSize")}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t("admin.duration")}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t("admin.engine")}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t("admin.created")}</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-gray-400">{t("admin.loading")}</td></tr>
              ) : !data?.items?.length ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-gray-400">{hasFilters ? t("admin.noTasksMatched") : t("admin.noTasks")}</td></tr>
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
                  const { icon: FileIcon, color: iconColor } = getFileTypeInfo(task.original_filename);
                  return (
                    <tr key={task.id} className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          <FileIcon className={`w-4 h-4 flex-shrink-0 ${iconColor}`} />
                          <div className="min-w-0">
                            <p className="text-sm text-gray-800 truncate max-w-[280px]">{task.original_filename}</p>
                            {task.status === "failed" && task.error_message && (
                              <p className="text-xs text-red-500 truncate max-w-[280px]" title={task.error_message}>{task.error_message}</p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <span className="inline-flex items-center gap-1.5 text-sm text-gray-600">
                          <span className={cfg.color}>{cfg.icon}</span>
                          {t(`status.${task.status}`)}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-sm text-gray-500">{task.username || "-"}</td>
                      <td className="px-4 py-4 text-sm text-gray-500">{formatFileSize(task.file_size_bytes)}</td>
                      <td className="px-4 py-4 text-sm text-gray-500">{formatDuration(task.duration_s)}</td>
                      <td className="px-4 py-4 text-sm text-gray-500">{task.backend || "auto"}</td>
                      <td className="px-4 py-4 text-sm text-gray-400 whitespace-nowrap">
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
      {(totalPages > 1 || (data?.total ?? 0) > 20) && (
        <div className="flex items-center justify-end gap-3 pt-1">
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed px-2.5 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              {buildPageNumbers(page, totalPages).map((p, i) =>
                p === "..." ? (
                  <span key={`ellipsis-${i}`} className="text-xs text-gray-400 px-1">…</span>
                ) : (
                  <button
                    key={p}
                    onClick={() => setPage(p as number)}
                    className={`min-w-[28px] h-7 text-xs rounded-lg transition-colors ${
                      page === p
                        ? "bg-blue-600 text-white font-medium"
                        : "text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    {p}
                  </button>
                )
              )}
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed px-2.5 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          <label className="inline-flex items-center gap-1.5 text-xs text-gray-500 whitespace-nowrap">
            {t("tasks.pageSize")}
            <select
              value={pageSize}
              onChange={(e) => {
                const nextPageSize = Number(e.target.value);
                setPageSize(nextPageSize);
                window.localStorage.setItem(PAGE_SIZE_STORAGE_KEY, String(nextPageSize));
                setPage(1);
              }}
              className="h-8 rounded-lg border border-gray-200 bg-white px-2 text-xs text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
          </label>
        </div>
      )}
    </div>
  );
}
