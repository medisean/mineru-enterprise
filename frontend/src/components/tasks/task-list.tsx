"use client";
/**
 * Task list component with real-time WebSocket progress updates,
 * pagination, and status filtering.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { tasksApi } from "@/lib/api";
import { apiClient } from "@/lib/api";
import {
  CheckCircle2, XCircle, Clock, Loader2, Download, FileText,
  ChevronLeft, ChevronRight, Filter, RotateCcw,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

interface Task {
  id: string;
  original_filename: string;
  file_size_bytes: number;
  status: string;
  progress: number;
  backend: string;
  output_format: string;
  language: string;
  is_ocr: boolean;
  enable_formula: boolean;
  enable_table: boolean;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  pending: { label: "等待中", color: "text-yellow-600 bg-yellow-50", icon: <Clock className="h-4 w-4" /> },
  processing: { label: "解析中", color: "text-blue-600 bg-blue-50", icon: <Loader2 className="h-4 w-4 animate-spin" /> },
  success: { label: "完成", color: "text-green-600 bg-green-50", icon: <CheckCircle2 className="h-4 w-4" /> },
  failed: { label: "失败", color: "text-red-600 bg-red-50", icon: <XCircle className="h-4 w-4" /> },
  cancelled: { label: "已取消", color: "text-gray-500 bg-gray-50", icon: <XCircle className="h-4 w-4" /> },
};

const STATUS_FILTERS = [
  { value: "", label: "全部" },
  { value: "pending", label: "等待中" },
  { value: "processing", label: "解析中" },
  { value: "success", label: "完成" },
  { value: "failed", label: "失败" },
];

const FILE_ICONS: Record<string, string> = {
  pdf: "text-red-400",
  doc: "text-blue-400",
  docx: "text-blue-400",
  ppt: "text-orange-400",
  pptx: "text-orange-400",
  xlsx: "text-green-400",
  png: "text-purple-400",
  jpg: "text-purple-400",
  jpeg: "text-purple-400",
  html: "text-cyan-400",
};

function getFileIconColor(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return FILE_ICONS[ext] || "text-gray-400";
}

function TaskRow({ task }: { task: Task }) {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (task.status !== "pending" && task.status !== "processing") return;

    const token = localStorage.getItem("access_token");
    const wsUrl = `${(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace("http", "ws")}/api/v1/ws/tasks/${task.id}?token=${token}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      const data = JSON.parse(evt.data);
      if (data.status === "success" || data.status === "failed" || data.status === "cancelled") {
        queryClient.invalidateQueries({ queryKey: ["tasks"] });
        ws.close();
      } else {
        queryClient.setQueryData(["tasks"], (old: { items: Task[] } | undefined) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((t) =>
              t.id === task.id ? { ...t, status: data.status, progress: data.progress } : t
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
      await apiClient.post(`/tasks/${task.id}/retry`);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    } catch {
      // silently fail — user can go to detail page for more info
    } finally {
      setRetrying(false);
    }
  };

  const statusCfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending;
  const fileSizeMB = (task.file_size_bytes / 1024 / 1024).toFixed(1);
  const iconColor = getFileIconColor(task.original_filename);

  return (
    <div className="flex items-center gap-4 p-4 bg-white border border-gray-100 rounded-xl hover:border-gray-200 transition-colors group">
      <FileText className={`h-8 w-8 flex-shrink-0 ${iconColor}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <p className="text-sm font-medium truncate">{task.original_filename}</p>
          <span className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${statusCfg.color}`}>
            {statusCfg.icon}
            {statusCfg.label}
          </span>
        </div>
        <p className="text-xs text-gray-400">
          {fileSizeMB} MB · {task.backend}
          {task.is_ocr && " · OCR"}
          {!task.enable_formula && " · 无公式"}
          {!task.enable_table && " · 无表格"}
          {" · "}
          {formatDistanceToNow(new Date(task.created_at), { addSuffix: true, locale: zhCN })}
        </p>
        {task.status === "processing" && (
          <div className="mt-1.5 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${task.progress}%` }}
            />
          </div>
        )}
        {task.error_message && (
          <p className="text-xs text-red-500 mt-0.5 truncate">{task.error_message}</p>
        )}
      </div>
      {task.status === "success" ? (
        <Link
          href={`/dashboard/tasks/${task.id}`}
          className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-lg transition-colors flex-shrink-0"
        >
          <Download className="h-3.5 w-3.5" />
          查看结果
        </Link>
      ) : task.status === "failed" ? (
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="flex items-center gap-1.5 text-xs text-orange-600 hover:text-orange-700 bg-orange-50 hover:bg-orange-100 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            {retrying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
            {retrying ? "重试中" : "重试"}
          </button>
          <Link
            href={`/dashboard/tasks/${task.id}`}
            className="flex items-center gap-1.5 text-xs text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors"
          >
            详情
          </Link>
        </div>
      ) : null}
    </div>
  );
}

export function TaskList() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const pageSize = 20;

  const { data, isLoading, isError } = useQuery({
    queryKey: ["tasks", page, statusFilter],
    queryFn: () =>
      tasksApi
        .list({ page, page_size: pageSize, status: statusFilter || undefined })
        .then((r: { data: { items: Task[]; total: number } }) => r.data),
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      const hasActive = items?.some(
        (t: Task) => t.status === "pending" || t.status === "processing"
      );
      return hasActive ? 5000 : false;
    },
  });

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="text-center py-12 text-sm text-red-500">加载失败，请刷新页面</div>
    );
  }

  if (!data?.items?.length) {
    return (
      <div className="text-center py-12">
        <FileText className="mx-auto h-10 w-10 text-gray-200 mb-3" />
        <p className="text-sm text-gray-400">暂无解析任务，上传文件开始解析</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex items-center gap-2">
        <Filter className="h-4 w-4 text-gray-400" />
        <div className="flex gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => { setStatusFilter(f.value); setPage(1); }}
              className={`text-xs px-2.5 py-1 rounded-full transition-colors ${
                statusFilter === f.value
                  ? "bg-blue-100 text-blue-700 font-medium"
                  : "text-gray-500 hover:bg-gray-100"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-400 ml-auto">
          共 {data.total} 条
        </span>
      </div>

      {/* Task list */}
      <div className="space-y-2">
        {data.items.map((task: Task) => (
          <TaskRow key={task.id} task={task} />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            上一页
          </button>
          <span className="text-xs text-gray-500">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
          >
            下一页
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
