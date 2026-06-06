"use client";
/**
 * Task list — table layout with selection, search, status filter, batch download, pagination.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { tasksApi } from "@/lib/api";
import { apiClient } from "@/lib/api";
import { getWebSocketBaseUrl } from "@/lib/runtime-config";
import { refetchTaskCollections, syncTaskCaches } from "@/lib/task-cache";
import {
  CheckCircle2, XCircle, Clock, Loader2, FileText,
  FileSpreadsheet, FileImage, File,
  ChevronLeft, ChevronRight, ChevronDown, Search, RotateCcw, Trash2,
  Download, X, AlertTriangle, Square, Star,
} from "lucide-react";
import { format } from "date-fns";
import { useT } from "@/lib/i18n/use-translation";
import { getTaskBackendLabel } from "@/lib/task-backend";

interface Task {
  id: string;
  original_filename: string;
  file_size_bytes: number;
  status: string;
  progress: number;
  is_favorite?: boolean;
  backend: string;
  output_format: string;
  language: string;
  is_ocr: boolean;
  enable_formula: boolean;
  enable_table: boolean;
  error_message?: string;
  queued_ahead?: number | null;
  is_stalled?: boolean;
  last_heartbeat_at?: string | null;
  created_at: string;
  completed_at?: string;
}

interface TaskListCache {
  items: Task[];
  total: number;
  page?: number;
  page_size?: number;
}

const STATUS_CONFIG: Record<string, { labelKey: string; color: string; icon: React.ReactNode }> = {
  pending: { labelKey: "status.pending", color: "text-yellow-500", icon: <Clock className="h-4 w-4" /> },
  processing: { labelKey: "status.processing", color: "text-blue-500", icon: <Loader2 className="h-4 w-4 animate-spin" /> },
  success: { labelKey: "status.parseSuccess", color: "text-green-500", icon: <CheckCircle2 className="h-4 w-4" /> },
  failed: { labelKey: "status.parseFailed", color: "text-red-500", icon: <XCircle className="h-4 w-4" /> },
  cancelled: { labelKey: "status.cancelled", color: "text-gray-400", icon: <XCircle className="h-4 w-4" /> },
};

const STATUS_FILTERS = [
  { value: "", labelKey: "status.all" },
  { value: "pending", labelKey: "status.pending" },
  { value: "processing", labelKey: "status.processing" },
  { value: "success", labelKey: "status.success" },
  { value: "failed", labelKey: "status.failed" },
  { value: "cancelled", labelKey: "status.cancelled" },
];

const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
const PAGE_SIZE_STORAGE_KEY = "mineru.tasks.pageSize";

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

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

function getExt(filename: string): string {
  return filename.split(".").pop()?.toUpperCase() || "";
}

function taskMatchesListFilters(task: Task, statusFilter: unknown, searchQuery: unknown): boolean {
  if (statusFilter && statusFilter !== task.status) return false;
  if (!searchQuery) return true;
  return task.original_filename.toLowerCase().includes(String(searchQuery).toLowerCase());
}

function syncFavoriteInTaskCache(cache: TaskListCache | undefined, task: Task, queryKey: readonly unknown[]): TaskListCache | undefined {
  if (!cache) return cache;

  const [, page, , statusFilter, searchQuery, favoriteOnly] = queryKey;
  const existingIndex = cache.items.findIndex((item) => item.id === task.id);

  if (!favoriteOnly) {
    if (existingIndex === -1) return cache;
    return {
      ...cache,
      items: cache.items.map((item) => (item.id === task.id ? task : item)),
    };
  }

  if (!task.is_favorite) {
    if (existingIndex === -1) return cache;
    return {
      ...cache,
      items: cache.items.filter((item) => item.id !== task.id),
      total: Math.max(0, cache.total - 1),
    };
  }

  if (existingIndex !== -1) {
    return {
      ...cache,
      items: cache.items.map((item) => (item.id === task.id ? task : item)),
    };
  }

  if (page !== 1 || !taskMatchesListFilters(task, statusFilter, searchQuery)) return cache;

  return {
    ...cache,
    items: [task, ...cache.items].slice(0, cache.page_size ?? cache.items.length + 1),
    total: cache.total + 1,
  };
}

function updateFavoriteInCachedTaskLists(queryClient: ReturnType<typeof useQueryClient>, task: Task) {
  const taskQueries = queryClient.getQueryCache().findAll({ queryKey: ["tasks"] });
  for (const query of taskQueries) {
    queryClient.setQueryData<TaskListCache>(query.queryKey, (cache) =>
      syncFavoriteInTaskCache(cache, task, query.queryKey)
    );
  }

  queryClient.setQueriesData<TaskListCache>({ queryKey: ["recent-tasks"] }, (cache) => {
    if (!cache) return cache;
    const hasTask = cache.items.some((item) => item.id === task.id);
    return {
      ...cache,
      items: hasTask
        ? cache.items.map((item) => (item.id === task.id ? task : item))
        : cache.items,
    };
  });
}

/** Build page number array with ellipsis */
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

function TaskRow({
  task,
  selected,
  onToggleSelect,
  anySelected,
  onDeleteRequest,
}: {
  task: Task;
  selected: boolean;
  onToggleSelect: () => void;
  anySelected: boolean;
  onDeleteRequest: (id: string, label: string) => void;
}) {
  const queryClient = useQueryClient();
  const t = useT();
  const wsRef = useRef<WebSocket | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [favoriting, setFavoriting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (task.status !== "pending" && task.status !== "processing") return;

    const token = localStorage.getItem("access_token");
    const wsUrl = `${getWebSocketBaseUrl()}/api/v1/ws/tasks/${task.id}?token=${token}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      const data = JSON.parse(evt.data);
      if (data.status === "success" || data.status === "failed" || data.status === "cancelled") {
        queryClient.invalidateQueries({ queryKey: ["tasks"] });
        ws.close();
      } else {
        queryClient.setQueriesData({ queryKey: ["tasks"] }, (old: { items: Task[] } | undefined) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((t) =>
              t.id === task.id ? { ...t, status: data.status, progress: data.progress, queued_ahead: data.queued_ahead, is_stalled: data.is_stalled } : t
            ),
          };
        });
      }
    };

    return () => ws.close();
  }, [task.id, task.status, queryClient]);

  const handleRetry = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (retrying) return;
    setRetrying(true);
    try {
      const res = await apiClient.post(`/tasks/${task.id}/retry`);
      syncTaskCaches(queryClient, res.data as Task);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["recent-tasks"] });
      refetchTaskCollections(queryClient);
    } catch {
      // silent
    } finally {
      setRetrying(false);
    }
  };

  const handleStop = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (stopping) return;
    setStopping(true);
    try {
      await apiClient.post(`/tasks/${task.id}/cancel`);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["recent-tasks"] });
    } catch {
      // silent
    } finally {
      setStopping(false);
    }
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (deleting) return;
    onDeleteRequest(task.id, task.original_filename);
  };

  const handleFavorite = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (favoriting) return;
    setFavoriting(true);
    try {
      const res = await tasksApi.setFavorite(task.id, !task.is_favorite);
      const updatedTask = res.data as Task;
      updateFavoriteInCachedTaskLists(queryClient, updatedTask);
      queryClient.invalidateQueries({ queryKey: ["task", task.id] });
      queryClient.invalidateQueries({ queryKey: ["recent-tasks"] });
      void queryClient.refetchQueries({ queryKey: ["tasks"], type: "all" });
    } catch {
      alert(t("tasks.favoriteFailed"));
    } finally {
      setFavoriting(false);
    }
  };

  const statusCfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
  const { icon: FileIcon, color: iconColor } = getFileTypeInfo(task.original_filename);

  return (
    <tr
      className={`group border-b border-gray-50 transition-colors cursor-pointer ${
        selected ? "bg-blue-50/60" : "hover:bg-gray-50/50"
      }`}
      onClick={() => { window.location.href = `/dashboard/tasks/${task.id}`; }}
    >
      {/* Checkbox — hidden by default, shown when any selected or on hover */}
      <td className="py-4 pl-5 pr-3 w-10" onClick={(e) => e.stopPropagation()}>
        <div className={`flex items-center justify-center transition-opacity ${anySelected || selected ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-0 focus:ring-offset-0 cursor-pointer accent-blue-600"
          />
        </div>
      </td>
      {/* Name + size */}
      <td className="py-4 pr-5 max-w-md">
        <div className="flex items-center gap-3 min-w-0">
          <FileIcon className={`h-5 w-5 flex-shrink-0 ${iconColor}`} />
          <div className="min-w-0 flex-1 overflow-hidden">
            <p className="text-sm text-gray-800 truncate" title={task.original_filename}>{task.original_filename}</p>
            <p className="text-xs text-gray-400">{formatFileSize(task.file_size_bytes)}</p>
          </div>
        </div>
      </td>
      {/* Status */}
      <td className="py-4 pr-5">
        <span className="inline-flex items-center gap-1.5 text-sm text-gray-600">
          <span className={statusCfg.color}>{statusCfg.icon}</span>
          {t(statusCfg.labelKey)}
        </span>
        {task.status === "processing" && (
          <div className="mt-1.5 h-1 bg-gray-100 rounded-full overflow-hidden w-20">
            <div
              className="h-full bg-blue-400 rounded-full transition-all duration-500"
              style={{ width: `${task.progress}%` }}
            />
          </div>
        )}
        {task.status === "pending" && typeof task.queued_ahead === "number" && task.queued_ahead > 0 && (
          <p className="mt-1 text-xs text-gray-400 whitespace-nowrap">
            {t("tasks.queuedAhead", { count: task.queued_ahead })}
          </p>
        )}
        {task.status === "pending" && task.queued_ahead === 0 && (
          <p className="mt-1 text-xs text-gray-400 whitespace-nowrap">
            {t("tasks.queueHead")}
          </p>
        )}
        {task.status === "processing" && task.is_stalled && (
          <p className="mt-1 text-xs text-amber-600 whitespace-nowrap">
            {t("tasks.possiblyStalled")}
          </p>
        )}
      </td>
      {/* Type */}
      <td className="py-4 pr-5">
        <span className="text-sm text-gray-500">{getExt(task.original_filename)}</span>
      </td>
      {/* Model */}
      <td className="py-4 pr-5">
        <span className="text-sm text-gray-500">{getTaskBackendLabel(task.backend, t)}</span>
      </td>
      {/* Created */}
      <td className="py-4 pr-5">
        <span className="text-sm text-gray-400 whitespace-nowrap">
          {format(new Date(task.created_at), "yyyy-MM-dd HH:mm")}
        </span>
      </td>
      {/* Actions */}
      <td className="py-4 pr-5 w-[180px]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-1 flex-wrap">
          <button
            onClick={handleFavorite}
            disabled={favoriting}
            className={`inline-flex items-center text-xs p-1 rounded transition-colors disabled:opacity-50 ${
              task.is_favorite
                ? "text-amber-500 hover:text-amber-600 hover:bg-amber-50"
                : "text-gray-300 hover:text-amber-500 hover:bg-amber-50"
            }`}
            title={task.is_favorite ? t("tasks.unfavorite") : t("tasks.favorite")}
          >
            {favoriting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Star className={`h-3.5 w-3.5 ${task.is_favorite ? "fill-amber-400" : ""}`} />
            )}
          </button>
          {(task.status === "pending" || task.status === "processing") && (
            <button
              onClick={handleStop}
              disabled={stopping}
              className="group inline-flex items-center gap-1 text-xs text-gray-500 hover:text-amber-700 hover:bg-amber-50 px-2 py-1 rounded transition-colors disabled:opacity-50"
            >
              {stopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5 fill-current text-gray-400 group-hover:text-amber-500" />}
              {t("tasks.stop")}
            </button>
          )}
          {(task.status === "failed" || task.status === "cancelled" || task.is_stalled) && (
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="inline-flex items-center gap-1 text-xs text-orange-600 hover:text-orange-700 hover:bg-orange-50 px-2 py-1 rounded transition-colors disabled:opacity-50"
            >
              {retrying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
              {t("tasks.retry")}
            </button>
          )}
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="inline-flex items-center text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 p-1 rounded transition-colors disabled:opacity-50"
            title={t("tasks.delete")}
          >
            {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </td>
    </tr>
  );
}

export function TaskList({
  favoriteOnly = false,
  titleKey = "tasks.allTasks",
}: {
  favoriteOnly?: boolean;
  titleKey?: string;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState<{ url: string; count: number } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{ ids: string[]; label: string } | null>(null);
  const [pageSize, setPageSize] = useState(() => {
    if (typeof window === "undefined") return 20;
    const saved = Number(window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY));
    return PAGE_SIZE_OPTIONS.includes(saved as (typeof PAGE_SIZE_OPTIONS)[number]) ? saved : 20;
  });

  // Debounce search: 500ms after user stops typing, apply the search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
      setPage(1);
    }, 500);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["tasks", page, pageSize, statusFilter, debouncedSearch, favoriteOnly],
    queryFn: () =>
      tasksApi
        .list({
          page,
          page_size: pageSize,
          status: statusFilter || undefined,
          keyword: debouncedSearch || undefined,
          favorite: favoriteOnly || undefined,
        })
        .then((r: { data: { items: Task[]; total: number } }) => r.data),
    refetchInterval: (query) => {
      if (statusFilter === "pending" || statusFilter === "processing") {
        return 5000;
      }
      const items = query.state.data?.items;
      const hasActive = items?.some(
        (t: Task) => t.status === "pending" || t.status === "processing"
      );
      return hasActive ? 5000 : false;
    },
    refetchOnMount: favoriteOnly ? "always" : undefined,
  });

  // Clear selection when page/filter changes
  useEffect(() => {
    setSelectedIds(new Set());
  }, [page, statusFilter, debouncedSearch, favoriteOnly]);

  const items = data?.items ?? [];
  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;
  const isEmpty = !items.length;

  const currentStatusLabel = STATUS_FILTERS.find(f => f.value === statusFilter)?.labelKey ? t(STATUS_FILTERS.find(f => f.value === statusFilter)!.labelKey) : t("status.all");

  // Selection helpers
  const allSelected = items.length > 0 && items.every((t: Task) => selectedIds.has(t.id));
  const someSelected = items.some((t: Task) => selectedIds.has(t.id)) && !allSelected;
  const selectedCount = selectedIds.size;

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((t: Task) => t.id)));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  // Batch download markdown
  const handleBatchDownload = async () => {
    const successTasks = items.filter((t: Task) => t.status === "success" && selectedIds.has(t.id));
    if (!successTasks.length) {
      alert(t("tasks.selectCompleted"));
      return;
    }
    setDownloading(true);
    try {
      if (successTasks.length === 1) {
        // Single file: download .md directly
        const res = await apiClient.get(`/tasks/${successTasks[0].id}/results`);
        const files = res.data?.files ?? [];
        const mdFile = files.find((f: { filename: string }) => f.filename.endsWith(".md"));
        const targetFile = mdFile || files[0];
        if (targetFile?.download_url) {
          const a = document.createElement("a");
          a.href = targetFile.download_url;
          a.download = targetFile.filename;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        }
      } else {
        // Multiple files: ZIP via batch download API
        const res = await apiClient.post("/tasks/batch/download", {
          task_ids: successTasks.map((t: Task) => t.id),
        });
        const { download_url, task_count } = res.data;
        setDownloadNotice({ url: download_url, count: task_count });
        setTimeout(() => setDownloadNotice(null), 15000);
      }
    } catch {
      alert(t("tasks.downloadFailed"));
    } finally {
      setDownloading(false);
    }
  };

  // Request batch delete (show confirm modal)
  const requestBatchDelete = () => {
    setDeleteConfirm({
      ids: Array.from(selectedIds),
      label: t("tasks.selectedBatch", { count: selectedCount }),
    });
  };

  // Execute delete after confirm
  const confirmDelete = async () => {
    if (!deleteConfirm) return;
    const ids = deleteConfirm.ids;
    setDeleteConfirm(null);
    setDownloading(true);
    try {
      for (const id of ids) {
        await apiClient.delete(`/tasks/${id}`);
      }
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["recent-tasks"] });
    } catch {
      alert(t("tasks.deleteFailed"));
    } finally {
      setDownloading(false);
    }
  };

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="text-center py-12 text-sm text-red-500">{t("tasks.loadFailed")}</div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Title + Search & Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-900 whitespace-nowrap">{t(titleKey)}</h2>

        {/* Search input */}
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder={t("tasks.searchPlaceholder")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-9 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-colors bg-white"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              aria-label={t("tasks.clearSearch")}
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Status dropdown */}
        <div className="relative">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="inline-flex items-center gap-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors bg-white"
          >
            {currentStatusLabel}
            <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
          </button>
          {dropdownOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
              <div className="absolute right-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[120px]">
                {STATUS_FILTERS.map((f) => (
                  <button
                    key={f.value}
                    onClick={() => { setStatusFilter(f.value); setPage(1); setDropdownOpen(false); }}
                    className={`w-full text-left text-sm px-3 py-1.5 hover:bg-gray-50 transition-colors ${
                      statusFilter === f.value ? "text-blue-600 font-medium bg-blue-50" : "text-gray-600"
                    }`}
                  >
                    {t(f.labelKey)}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <span className="text-xs text-gray-400 whitespace-nowrap">
          {t("tasks.totalCount", { count: data?.total ?? 0 })}
        </span>
      </div>

      {/* Table */}
      {isEmpty ? (
        <div className="text-center py-12">
          <FileText className="mx-auto h-10 w-10 text-gray-200 mb-3" />
          <p className="text-sm text-gray-400">
            {favoriteOnly && !debouncedSearch && !statusFilter
              ? t("tasks.noFavorites")
              : debouncedSearch
              ? t("tasks.noTasksMatched")
              : statusFilter
                ? t("tasks.noTasksFiltered", { status: t(STATUS_FILTERS.find(f => f.value === statusFilter)!.labelKey) })
                : t("tasks.noTasksEmpty")}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-3 pl-5 pr-3 w-10">
                  <div className={`flex items-center justify-center transition-opacity ${selectedCount > 0 ? "opacity-100" : "opacity-0"}`}>
                    <input
                      type="checkbox"
                      ref={(el) => {
                        if (el) el.indeterminate = someSelected;
                      }}
                      checked={allSelected}
                      onChange={toggleSelectAll}
                      className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                    />
                  </div>
                </th>
                <th className="text-left text-xs font-medium text-gray-500 py-3 pr-5 max-w-md">{t("tasks.colName")}</th>
                <th className="text-left text-xs font-medium text-gray-500 py-3 pr-5">{t("tasks.colStatus")}</th>
                <th className="text-left text-xs font-medium text-gray-500 py-3 pr-5">{t("tasks.colType")}</th>
                <th className="text-left text-xs font-medium text-gray-500 py-3 pr-5">{t("tasks.colModel")}</th>
                <th className="text-left text-xs font-medium text-gray-500 py-3 pr-5">{t("tasks.colCreated")}</th>
                <th className="text-left text-xs font-medium text-gray-500 py-3 pr-5 w-[180px] whitespace-nowrap">{t("tasks.colActions")}</th>
              </tr>
            </thead>
            <tbody className="px-4">
              {items.map((task: Task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  selected={selectedIds.has(task.id)}
                  onToggleSelect={() => toggleSelect(task.id)}
                  anySelected={selectedCount > 0}
                  onDeleteRequest={(id, label) => setDeleteConfirm({ ids: [id], label })}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Selection toolbar — fixed at bottom */}
      {selectedCount > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-3 bg-white border border-gray-200 shadow-xl rounded-xl px-5 py-3">
          <span className="text-sm text-gray-700 font-medium">{t("tasks.selected", { count: selectedCount })}</span>
          <div className="w-px h-5 bg-gray-200" />
          <button
            onClick={handleBatchDownload}
            disabled={downloading}
            className="inline-flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-700 hover:bg-blue-50 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {t("tasks.downloadMarkdown")}
          </button>
          <button
            onClick={requestBatchDelete}
            disabled={downloading}
            className="inline-flex items-center gap-1.5 text-sm text-red-500 hover:text-red-600 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            {t("tasks.delete")}
          </button>
          <div className="w-px h-5 bg-gray-200" />
          <button
            onClick={clearSelection}
            className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 px-2 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <X className="h-4 w-4" />
            {t("tasks.cancel")}
          </button>
        </div>
      )}

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

      {/* Download complete notice — bottom right, auto-dismiss 15s */}
      {downloadNotice && (
        <div className="fixed bottom-6 right-6 z-40 bg-white border border-gray-200 shadow-xl rounded-xl px-5 py-4 max-w-xs animate-in slide-in-from-right">
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-8 h-8 bg-green-50 rounded-full flex items-center justify-center">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900">{t("tasks.exportSuccess")}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {t("tasks.exportDesc", { count: downloadNotice.count })}
              </p>
              <a
                href={downloadNotice.url}
                download="export.zip"
                className="inline-flex items-center gap-1 mt-2.5 text-sm text-blue-600 hover:text-blue-700 font-medium transition-colors"
              >
                <Download className="h-4 w-4" />
                {t("tasks.downloadNow")}
              </a>
            </div>
            <button
              onClick={() => setDownloadNotice(null)}
              className="flex-shrink-0 text-gray-400 hover:text-gray-600 p-0.5 transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/30" onClick={() => setDeleteConfirm(null)} />
          <div className="relative bg-white rounded-xl shadow-xl px-6 py-5 max-w-lg w-full mx-4 overflow-hidden">
            <div className="flex flex-col items-center text-center">
              <div className="w-10 h-10 bg-amber-50 rounded-full flex items-center justify-center mb-3">
                <AlertTriangle className="h-5 w-5 text-amber-500" />
              </div>
              <h3 className="text-base font-medium text-gray-900 mb-1">{t("tasks.deleteTitle")}</h3>
              {deleteConfirm.ids.length === 1 ? (
                <div className="w-full space-y-2">
                  <p className="text-sm text-gray-500">{t("tasks.deleteSingleHint")}</p>
                  <div
                    className="w-full max-h-32 overflow-y-auto rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2 text-sm text-gray-700 break-all text-left"
                    title={deleteConfirm.label}
                  >
                    {deleteConfirm.label}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-gray-500 w-full break-words">
                  {t("tasks.deleteMultiple", { label: deleteConfirm.label })}
                </p>
              )}
            </div>
            <div className="flex items-center gap-3 mt-5">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="flex-1 text-sm text-gray-600 bg-gray-100 hover:bg-gray-200 px-4 py-2 rounded-lg transition-colors font-medium"
              >
                {t("tasks.cancel")}
              </button>
              <button
                onClick={confirmDelete}
                className="flex-1 text-sm text-white bg-red-500 hover:bg-red-600 px-4 py-2 rounded-lg transition-colors font-medium"
              >
                {t("tasks.confirm")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
