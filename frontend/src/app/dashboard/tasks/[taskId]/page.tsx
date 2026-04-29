"use client";
/**
 * Task detail page with Markdown/HTML preview and file downloads.
 */
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiClient } from "@/lib/api";
import {
  ArrowLeft, Download, FileText, Loader2, Copy, Check,
  RefreshCw, Clock, AlertCircle, ExternalLink, RotateCcw,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

interface TaskDetail {
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
  page_ranges: string | null;
  error_message?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

interface ResultFile {
  filename: string;
  s3_key: string;
  download_url: string;
  size: number;
}

interface PreviewData {
  format: string;
  content: string;
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: "等待中", color: "text-yellow-600 bg-yellow-50" },
  processing: { label: "解析中", color: "text-blue-600 bg-blue-50" },
  success: { label: "完成", color: "text-green-600 bg-green-50" },
  failed: { label: "失败", color: "text-red-600 bg-red-50" },
  cancelled: { label: "已取消", color: "text-gray-500 bg-gray-100" },
};

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [activeTab, setActiveTab] = useState<"preview" | "files">("preview");

  const { data: task, isLoading, isError, refetch } = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => apiClient.get(`/api/v1/tasks/${taskId}`).then((r) => r.data),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 3000 : false;
    },
  });

  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ["task-preview", taskId],
    queryFn: () => apiClient.get(`/api/v1/tasks/${taskId}/preview`).then((r) => r.data as PreviewData),
    enabled: task?.status === "success",
  });

  const { data: results } = useQuery({
    queryKey: ["task-results", taskId],
    queryFn: () => apiClient.get(`/api/v1/tasks/${taskId}/results`).then((r) => r.data),
    enabled: task?.status === "success",
  });

  const copyContent = async () => {
    if (preview?.content) {
      await navigator.clipboard.writeText(preview.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleRetry = async () => {
    if (retrying) return;
    setRetrying(true);
    try {
      await apiClient.post(`/api/v1/tasks/${taskId}/retry`);
      refetch();
    } catch (err: any) {
      alert(err?.response?.data?.detail || "重试失败，请稍后再试");
    } finally {
      setRetrying(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !task) {
    return (
      <div className="text-center py-12">
        <AlertCircle className="mx-auto h-8 w-8 text-red-400 mb-3" />
        <p className="text-sm text-red-500">任务不存在或加载失败</p>
        <button onClick={() => router.push("/dashboard")} className="text-sm text-blue-600 mt-2 hover:underline">
          返回控制台
        </button>
      </div>
    );
  }

  const statusCfg = STATUS_MAP[task.status] || STATUS_MAP.pending;

  return (
    <div className="min-h-screen bg-gray-50">
      <main className="max-w-5xl mx-auto p-8">
        {/* Back button + header */}
        <button
          onClick={() => router.push("/dashboard?tab=tasks")}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          返回任务列表
        </button>

        {/* Task info card */}
        <div className="bg-white rounded-xl border border-gray-100 p-6 mb-6">
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center gap-3">
              <FileText className="h-8 w-8 text-gray-300" />
              <div>
                <h1 className="text-base font-medium text-gray-900">{task.original_filename}</h1>
                <p className="text-xs text-gray-400 mt-0.5">
                  {(task.file_size_bytes / 1024 / 1024).toFixed(1)} MB
                  {task.completed_at && ` · 耗时 ${formatDistanceToNow(new Date(task.started_at || task.created_at), { locale: zhCN })}`}
                </p>
              </div>
            </div>
            <span className={`text-xs px-2.5 py-1 rounded-full ${statusCfg.color} flex items-center gap-1`}>
              {task.status === "processing" && <Loader2 className="h-3 w-3 animate-spin" />}
              {statusCfg.label}
            </span>
          </div>

          {/* Progress bar for in-progress tasks */}
          {task.status === "processing" && (
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden mb-4">
              <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${task.progress}%` }} />
            </div>
          )}

          {/* Metadata grid */}
          <div className="grid grid-cols-4 gap-4 text-xs">
            <div>
              <span className="text-gray-400">引擎</span>
              <p className="text-gray-700 font-medium mt-0.5">{task.backend}</p>
            </div>
            <div>
              <span className="text-gray-400">输出格式</span>
              <p className="text-gray-700 font-medium mt-0.5">{task.output_format}</p>
            </div>
            <div>
              <span className="text-gray-400">语言</span>
              <p className="text-gray-700 font-medium mt-0.5">{task.language}</p>
            </div>
            <div>
              <span className="text-gray-400">创建时间</span>
              <p className="text-gray-700 font-medium mt-0.5">
                {formatDistanceToNow(new Date(task.created_at), { addSuffix: true, locale: zhCN })}
              </p>
            </div>
          </div>

          {/* Parse options badges */}
          <div className="flex gap-2 mt-3 flex-wrap">
            {task.is_ocr && (
              <span className="text-xs bg-purple-50 text-purple-600 px-2 py-0.5 rounded-full">OCR</span>
            )}
            {task.enable_formula && (
              <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full">公式识别</span>
            )}
            {task.enable_table && (
              <span className="text-xs bg-green-50 text-green-600 px-2 py-0.5 rounded-full">表格识别</span>
            )}
            {task.page_ranges && (
              <span className="text-xs bg-orange-50 text-orange-600 px-2 py-0.5 rounded-full">
                页码: {task.page_ranges}
              </span>
            )}
          </div>

          {/* Error message */}
          {task.error_message && (
            <div className="mt-4 p-3 bg-red-50 border border-red-100 rounded-lg">
              <p className="text-xs text-red-600 font-medium mb-1">解析失败</p>
              <p className="text-xs text-red-500">{task.error_message}</p>
            </div>
          )}

          {/* Retry button for failed/cancelled tasks */}
          {(task.status === "failed" || task.status === "cancelled") && (
            <div className="mt-4">
              <button
                onClick={handleRetry}
                disabled={retrying}
                className="flex items-center gap-2 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 rounded-lg transition-colors"
              >
                {retrying ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RotateCcw className="h-4 w-4" />
                )}
                {retrying ? "重新提交中..." : "重新解析"}
              </button>
            </div>
          )}
        </div>

        {/* Success: show preview + downloads */}
        {task.status === "success" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            {/* Tab bar */}
            <div className="flex border-b border-gray-100">
              <button
                onClick={() => setActiveTab("preview")}
                className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === "preview"
                    ? "border-blue-500 text-blue-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                内容预览
              </button>
              <button
                onClick={() => setActiveTab("files")}
                className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === "files"
                    ? "border-blue-500 text-blue-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                下载文件
                {results?.files?.length && (
                  <span className="ml-1.5 text-xs text-gray-400">({results.files.length})</span>
                )}
              </button>
            </div>

            <div className="p-6">
              {activeTab === "preview" ? (
                <div>
                  {/* Toolbar */}
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400">
                        {preview?.format === "markdown" ? "Markdown" : preview?.format === "html" ? "HTML" : "JSON"} 格式
                      </span>
                      {task.status === "processing" && (
                        <button
                          onClick={() => refetch()}
                          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
                        >
                          <RefreshCw className="h-3 w-3" />
                          刷新
                        </button>
                      )}
                    </div>
                    {preview?.content && (
                      <button
                        onClick={copyContent}
                        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 bg-gray-50 px-3 py-1.5 rounded-md transition-colors"
                      >
                        {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
                        {copied ? "已复制" : "复制内容"}
                      </button>
                    )}
                  </div>

                  {previewLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                    </div>
                  ) : preview?.format === "markdown" ? (
                    <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-table:text-sm prose-code:text-blue-600 prose-code:bg-blue-50 prose-code:px-1 prose-code:rounded">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {preview.content}
                      </ReactMarkdown>
                    </div>
                  ) : preview?.format === "html" ? (
                    <div
                      className="prose prose-sm max-w-none"
                      dangerouslySetInnerHTML={{ __html: preview.content }}
                    />
                  ) : preview?.format === "json" ? (
                    <pre className="bg-gray-50 rounded-lg p-4 text-xs text-gray-700 overflow-auto max-h-[600px] whitespace-pre-wrap">
                      {JSON.stringify(JSON.parse(preview.content), null, 2)}
                    </pre>
                  ) : (
                    <pre className="bg-gray-50 rounded-lg p-4 text-xs text-gray-700 overflow-auto max-h-[600px] whitespace-pre-wrap">
                      {preview?.content || "暂无预览内容"}
                    </pre>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {results?.files?.map((file: ResultFile) => (
                    <a
                      key={file.s3_key}
                      href={file.download_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-3 p-3 border border-gray-100 rounded-lg hover:border-gray-200 hover:bg-gray-50 transition-colors group"
                    >
                      <FileText className="h-5 w-5 text-gray-400 group-hover:text-blue-500 transition-colors" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-700 truncate group-hover:text-blue-600 transition-colors">
                          {file.filename}
                        </p>
                        <p className="text-xs text-gray-400">{(file.size / 1024).toFixed(1)} KB</p>
                      </div>
                      <Download className="h-4 w-4 text-gray-400 group-hover:text-blue-500 transition-colors" />
                    </a>
                  ))}
                  {(!results?.files?.length) && (
                    <p className="text-sm text-gray-400 text-center py-8">暂无文件</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
