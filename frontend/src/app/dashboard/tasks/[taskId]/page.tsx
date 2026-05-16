"use client";
/**
 * Task detail page — left-right split layout with scroll sync.
 * Left: source file preview (PDF pages via react-pdf, or image embed).
 * Right: parse result (Markdown + copy).
 * Scrolling one panel proportionally scrolls the other.
 */
import { useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import DOMPurify from "dompurify";
import { apiClient, tasksApi } from "@/lib/api";
import {
  ArrowLeft, Download, FileText, Loader2, Copy, Check,
  AlertCircle, RotateCcw, ZoomIn, ZoomOut,
  FileSpreadsheet, Square, Star,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { zhCN, enUS } from "date-fns/locale";
import { useT } from "@/lib/i18n/use-translation";
import { useI18nStore } from "@/lib/i18n-store";

// Dynamic import PDF viewer to avoid SSR issues (pdfjs-dist uses browser APIs)
const PdfViewer = dynamic(() => import("@/components/pdf-viewer"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
    </div>
  ),
});

interface TaskDetail {
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
  page_ranges: string | null;
  error_message?: string;
  queued_ahead?: number | null;
  is_stalled?: boolean;
  last_heartbeat_at?: string | null;
  run_attempt?: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  input_s3_key?: string;
}

interface PreviewData {
  format: string;
  content: string;
  markdown_content: string | null;
  json_content: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "text-yellow-600 bg-yellow-50",
  processing: "text-blue-600 bg-blue-50",
  success: "text-green-600 bg-green-50",
  failed: "text-red-600 bg-red-50",
  cancelled: "text-gray-500 bg-gray-100",
};

const PDF_EXTENSIONS = ["pdf"];
const IMAGE_EXTENSIONS = ["png", "jpeg", "jp2", "webp", "gif", "bmp", "jpg", "tiff"];
const OFFICE_EXTENSIONS = ["pptx", "docx", "xlsx"];

function isPdfFile(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return PDF_EXTENSIONS.includes(ext);
}

function isImageFile(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return IMAGE_EXTENSIONS.includes(ext);
}

function isOfficeFile(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  return OFFICE_EXTENSIONS.includes(ext);
}

function getOfficeFileType(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (ext === "pptx") return "PowerPoint";
  if (ext === "docx") return "Word";
  if (ext === "xlsx") return "Excel";
  return "Office";
}

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const t = useT();
  const dateLocale = useI18nStore((s) => s.locale) === "zh" ? zhCN : enUS;

  const STATUS_MAP: Record<string, { label: string; color: string }> = {
    pending: { label: t("status.pending"), color: STATUS_COLORS.pending },
    processing: { label: t("status.processing"), color: STATUS_COLORS.processing },
    success: { label: t("status.success"), color: STATUS_COLORS.success },
    failed: { label: t("status.failed"), color: STATUS_COLORS.failed },
    cancelled: { label: t("status.cancelled"), color: STATUS_COLORS.cancelled },
  };

  const [copied, setCopied] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [favoriting, setFavoriting] = useState(false);
  const [zoom, setZoom] = useState(100);

  // Scroll sync refs
  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);

  const { data: task, isLoading, isError, refetch } = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => apiClient.get(`/tasks/${taskId}`).then((r) => r.data),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 3000 : false;
    },
  });

  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ["task-preview", taskId],
    queryFn: () => apiClient.get(`/tasks/${taskId}/preview`).then((r) => r.data as PreviewData),
    enabled: task?.status === "success",
  });

  const { data: results } = useQuery({
    queryKey: ["task-results", taskId],
    queryFn: () => apiClient.get(`/tasks/${taskId}/results`).then((r) => r.data),
    enabled: task?.status === "success",
  });

  // Get source file presigned URL for left panel preview
  const { data: sourceUrlData } = useQuery({
    queryKey: ["source-url", taskId],
    queryFn: () => apiClient.get(`/tasks/${taskId}/source-url`).then((r) => r.data),
    enabled: task?.status === "success",
  });
  const sourceFileUrl = sourceUrlData?.download_url;
  const previewType = sourceUrlData?.preview_type;

  const handleDownloadAll = () => {
    if (!results?.files?.length) return;
    for (const file of results.files) {
      const a = document.createElement("a");
      a.href = file.download_url;
      a.download = file.filename;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  };

  const copyContent = async () => {
    const text = preview?.markdown_content || preview?.content;
    if (text) {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleRetry = async () => {
    if (retrying) return;
    setRetrying(true);
    try {
      await apiClient.post(`/tasks/${taskId}/retry`);
      refetch();
    } catch (err: any) {
      alert(err?.response?.data?.detail || t("taskDetail.retryFailed"));
    } finally {
      setRetrying(false);
    }
  };

  const handleStop = async () => {
    if (stopping) return;
    setStopping(true);
    try {
      await apiClient.post(`/tasks/${taskId}/cancel`);
      refetch();
    } catch (err: any) {
      alert(err?.response?.data?.detail || t("taskDetail.stopFailed"));
    } finally {
      setStopping(false);
    }
  };

  const handleFavorite = async () => {
    if (!task || favoriting) return;
    setFavoriting(true);
    try {
      await tasksApi.setFavorite(taskId, !task.is_favorite);
      await refetch();
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      queryClient.invalidateQueries({ queryKey: ["recent-tasks"] });
    } catch {
      alert(t("tasks.favoriteFailed"));
    } finally {
      setFavoriting(false);
    }
  };

  // ── Scroll sync (one-way: left → right only) ──────────────────────────
  const handleLeftScroll = useCallback(() => {
    const srcEl = leftScrollRef.current;
    const dstEl = rightScrollRef.current;
    if (!srcEl || !dstEl) return;

    const srcMax = srcEl.scrollHeight - srcEl.clientHeight;
    if (srcMax <= 0) return;
    const ratio = srcEl.scrollTop / srcMax;
    const dstMax = dstEl.scrollHeight - dstEl.clientHeight;
    dstEl.scrollTop = ratio * dstMax;
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh)] bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !task) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh)] bg-gray-50">
        <div className="text-center">
          <AlertCircle className="mx-auto h-8 w-8 text-red-400 mb-3" />
          <p className="text-sm text-red-500">{t("taskDetail.notFound")}</p>
          <button onClick={() => router.push("/dashboard")} className="text-sm text-blue-600 mt-2 hover:underline">
            {t("taskDetail.backToConsole")}
          </button>
        </div>
      </div>
    );
  }

  const statusCfg = STATUS_MAP[task.status] || STATUS_MAP.pending;

  // Non-success states: compact card view
  if (task.status !== "success") {
    return (
      <div className="h-screen bg-gray-50">
        <main className="max-w-3xl mx-auto p-8">
          <button
            onClick={() => router.push("/dashboard/tasks")}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("taskDetail.backToTaskList")}
          </button>

          <div className="bg-white rounded-xl border border-gray-100 p-6">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <FileText className="h-8 w-8 text-gray-300 flex-shrink-0" />
                <div className="min-w-0 overflow-hidden">
                  <h1 className="text-base font-medium text-gray-900 truncate" title={task.original_filename}>{task.original_filename}</h1>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {(task.file_size_bytes / 1024 / 1024).toFixed(1)} MB
                    {task.completed_at && ` · ${t("taskDetail.elapsed")} ${formatDistanceToNow(new Date(task.started_at || task.created_at), { locale: dateLocale })}`}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={handleFavorite}
                  disabled={favoriting}
                  className={`inline-flex items-center justify-center h-8 w-8 rounded-lg transition-colors disabled:opacity-50 ${
                    task.is_favorite
                      ? "text-amber-500 bg-amber-50 hover:bg-amber-100"
                      : "text-gray-300 bg-gray-50 hover:text-amber-500 hover:bg-amber-50"
                  }`}
                  title={task.is_favorite ? t("tasks.unfavorite") : t("tasks.favorite")}
                >
                  {favoriting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Star className={`h-4 w-4 ${task.is_favorite ? "fill-amber-400" : ""}`} />
                  )}
                </button>
                <span className={`text-xs px-2.5 py-1 rounded-full whitespace-nowrap ${statusCfg.color}`}>
                  {task.status === "processing" && <Loader2 className="h-3 w-3 animate-spin inline mr-1" />}
                  {statusCfg.label}
                </span>
              </div>
            </div>

            {task.status === "processing" && (
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden mb-4">
                <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${task.progress}%` }} />
              </div>
            )}

            {task.status === "pending" && typeof task.queued_ahead === "number" && task.queued_ahead > 0 && (
              <p className="text-sm text-gray-500 mb-4">
                {t("tasks.queuedAhead", { count: task.queued_ahead })}
              </p>
            )}

            {task.status === "pending" && task.queued_ahead === 0 && (
              <p className="text-sm text-gray-500 mb-4">
                {t("tasks.queueHead")}
              </p>
            )}

            {task.status === "processing" && task.is_stalled && (
              <div className="mt-4 p-3 bg-amber-50 border border-amber-100 rounded-lg">
                <p className="text-xs text-amber-700 font-medium mb-1">{t("taskDetail.possiblyStalledTitle")}</p>
                <p className="text-xs text-amber-600">{t("taskDetail.possiblyStalledDesc")}</p>
              </div>
            )}

            {task.error_message && (
              <div className="mt-4 p-3 bg-red-50 border border-red-100 rounded-lg">
                <p className="text-xs text-red-600 font-medium mb-1">{t("taskDetail.parseFailedTitle")}</p>
                <p className="text-xs text-red-500">{task.error_message}</p>
              </div>
            )}

            {(task.status === "pending" || task.status === "processing" || task.status === "failed" || task.status === "cancelled" || task.is_stalled) && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                {(task.status === "pending" || task.status === "processing") && (
                  <button
                    onClick={handleStop}
                    disabled={stopping}
                    className="group flex items-center gap-2 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 px-4 py-2 rounded-lg transition-colors"
                  >
                    {stopping ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4 fill-current text-gray-400 group-hover:text-gray-500" />}
                    {stopping ? t("taskDetail.stopping") : t("taskDetail.stop")}
                  </button>
                )}
                <button
                  onClick={handleRetry}
                  disabled={retrying}
                  className={`${(task.status === "failed" || task.status === "cancelled" || task.is_stalled) ? "flex" : "hidden"} items-center gap-2 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded-lg transition-colors`}
                >
                  {retrying ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                  {retrying ? t("taskDetail.retrying") : t("taskDetail.reparse")}
                </button>
              </div>
            )}
          </div>
        </main>
      </div>
    );
  }

  // ── Success: left-right split layout ──────────────────────────────────────
  const sourceIsPdf = isPdfFile(task.original_filename);
  const sourceIsImage = isImageFile(task.original_filename);
  const sourceIsOffice = isOfficeFile(task.original_filename);
  const officeType = getOfficeFileType(task.original_filename);

  // Determine if we should use react-pdf (for actual PDFs and Office files with PDF preview)
  const usePdfRenderer = (sourceIsPdf || (sourceIsOffice && previewType === "pdf")) && sourceFileUrl;

  const originFileUrl = sourceFileUrl;

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-3 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <button
            onClick={() => router.push("/dashboard/tasks")}
            className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors flex-shrink-0"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("taskDetail.taskList")}
          </button>
          <div className="w-px h-4 bg-gray-200 flex-shrink-0" />
          <FileText className="h-4 w-4 text-gray-400 flex-shrink-0" />
          <span className="text-sm font-medium text-gray-900 truncate" title={task.original_filename}>{task.original_filename}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap flex-shrink-0 ${statusCfg.color}`}>{statusCfg.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleFavorite}
            disabled={favoriting}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50 ${
              task.is_favorite
                ? "text-amber-600 bg-amber-50 hover:bg-amber-100"
                : "text-gray-500 bg-gray-50 hover:text-amber-600 hover:bg-amber-50"
            }`}
            title={task.is_favorite ? t("tasks.unfavorite") : t("tasks.favorite")}
          >
            {favoriting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Star className={`h-3.5 w-3.5 ${task.is_favorite ? "fill-amber-400" : ""}`} />
            )}
            {task.is_favorite ? t("tasks.unfavorite") : t("tasks.favorite")}
          </button>
          {results?.files?.length > 0 && (
            <button
              onClick={handleDownloadAll}
              className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-800 bg-gray-50 hover:bg-gray-100 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              {t("taskDetail.downloadResults")}
            </button>
          )}
        </div>
      </div>

      {/* Split content */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: Source file preview */}
        <div className="w-1/2 border-r border-gray-200 flex flex-col bg-gray-100">
          <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-100 flex-shrink-0">
            <span className="text-xs font-medium text-gray-600">{t("taskDetail.sourcePreview")}</span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setZoom((z) => Math.max(50, z - 10))}
                className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
                title={t("taskDetail.zoomOut")}
              >
                <ZoomOut className="h-3.5 w-3.5" />
              </button>
              <span className="text-xs text-gray-500 w-10 text-center">{zoom}%</span>
              <button
                onClick={() => setZoom((z) => Math.min(200, z + 10))}
                className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
                title={t("taskDetail.zoomIn")}
              >
                <ZoomIn className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div
            ref={leftScrollRef}
            onScroll={handleLeftScroll}
            className="flex-1 overflow-auto p-4"
          >
            {usePdfRenderer ? (
              <PdfViewer url={originFileUrl} zoom={zoom} />
            ) : sourceIsImage && originFileUrl ? (
              <div className="flex justify-center">
                <img
                  src={originFileUrl}
                  alt={t("taskDetail.sourcePreviewAlt")}
                  className="bg-white shadow-lg rounded max-w-none"
                  style={{ width: `${zoom}%` }}
                />
              </div>
            ) : sourceIsOffice && originFileUrl && previewType !== "pdf" ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-20 w-full">
                <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 max-w-sm w-full overflow-hidden">
                  <div className="w-16 h-16 bg-blue-50 rounded-xl flex items-center justify-center mx-auto mb-4">
                    <FileSpreadsheet className="h-8 w-8 text-blue-500" />
                  </div>
                  <p className="text-sm font-medium text-gray-700 mb-1 truncate" title={task.original_filename}>{task.original_filename}</p>
                  <p className="text-xs text-gray-400 mb-4">
                    {t("taskDetail.fileType", { type: officeType })} · {(task.file_size_bytes / 1024 / 1024).toFixed(1)} MB
                  </p>
                  <p className="text-xs text-gray-400 mb-4">{t("taskDetail.noPreview")}</p>
                  <a
                    href={originFileUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-xs text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors"
                  >
                    <Download className="h-3.5 w-3.5" />
                    {t("taskDetail.downloadOriginal")}
                  </a>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center py-20 px-8 overflow-hidden">
                <FileText className="h-16 w-16 text-gray-200 mb-4" />
                <p className="text-sm text-gray-400 mb-1 truncate w-full" title={task.original_filename}>{task.original_filename}</p>
                <p className="text-xs text-gray-300">
                  {(task.file_size_bytes / 1024 / 1024).toFixed(1)} MB · {task.backend} · {task.language}
                </p>
                <p className="text-xs text-gray-300 mt-4">{t("taskDetail.noPreviewGeneric")}</p>
              </div>
            )}
          </div>
        </div>

        {/* Right panel: Markdown result */}
        <div className="w-1/2 flex flex-col bg-white">
          {/* Header bar */}
          <div className="flex items-center justify-between px-4 border-b border-gray-100 flex-shrink-0">
            <span className="px-4 py-2.5 text-xs font-medium border-b-2 border-blue-500 text-blue-600">
              Markdown
            </span>
            <button
              onClick={copyContent}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 bg-gray-50 hover:bg-gray-100 px-2.5 py-1 rounded transition-colors"
            >
              {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
              {copied ? t("taskDetail.copied") : t("taskDetail.copy")}
            </button>
          </div>

          {/* Markdown content */}
          <div
            ref={rightScrollRef}
            className="flex-1 overflow-auto p-6"
          >
            {previewLoading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
              </div>
            ) : (
              <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-table:text-sm prose-code:text-blue-600 prose-code:bg-blue-50 prose-code:px-1 prose-code:rounded">
                {preview?.markdown_content ? (
                  preview.format === "html" && !preview.markdown_content.includes("#") ? (
                    <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(preview.markdown_content, { USE_PROFILES: { html: true } }) }} />
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {preview.markdown_content}
                    </ReactMarkdown>
                  )
                ) : (
                  <pre className="bg-gray-50 rounded-lg p-4 text-xs text-gray-700 whitespace-pre-wrap">
                    {preview?.content || t("taskDetail.noPreviewContent")}
                  </pre>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
