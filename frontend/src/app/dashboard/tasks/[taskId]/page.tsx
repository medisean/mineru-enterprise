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
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiClient } from "@/lib/api";
import {
  ArrowLeft, Download, FileText, Loader2, Copy, Check,
  AlertCircle, RotateCcw, ZoomIn, ZoomOut,
  FileSpreadsheet,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

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
  input_s3_key?: string;
}

interface PreviewData {
  format: string;
  content: string;
  markdown_content: string | null;
  json_content: string | null;
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: "等待中", color: "text-yellow-600 bg-yellow-50" },
  processing: { label: "解析中", color: "text-blue-600 bg-blue-50" },
  success: { label: "完成", color: "text-green-600 bg-green-50" },
  failed: { label: "失败", color: "text-red-600 bg-red-50" },
  cancelled: { label: "已取消", color: "text-gray-500 bg-gray-100" },
};

const PDF_EXTENSIONS = ["pdf"];
const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "bmp", "webp", "gif"];
const OFFICE_EXTENSIONS = ["pptx", "ppt", "docx", "doc", "xlsx", "xls"];

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
  if (["pptx", "ppt"].includes(ext)) return "PowerPoint";
  if (["docx", "doc"].includes(ext)) return "Word";
  if (["xlsx", "xls"].includes(ext)) return "Excel";
  return "Office";
}

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [zoom, setZoom] = useState(100);

  // Scroll sync refs
  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  const isSyncingScroll = useRef(false);

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
      alert(err?.response?.data?.detail || "重试失败，请稍后再试");
    } finally {
      setRetrying(false);
    }
  };

  // ── Scroll sync ──────────────────────────────────────────────────────
  const handleScroll = useCallback((source: "left" | "right") => {
    if (isSyncingScroll.current) return;
    isSyncingScroll.current = true;

    const srcEl = source === "left" ? leftScrollRef.current : rightScrollRef.current;
    const dstEl = source === "left" ? rightScrollRef.current : leftScrollRef.current;
    if (!srcEl || !dstEl) {
      isSyncingScroll.current = false;
      return;
    }

    const srcMax = srcEl.scrollHeight - srcEl.clientHeight;
    if (srcMax <= 0) {
      isSyncingScroll.current = false;
      return;
    }
    const ratio = srcEl.scrollTop / srcMax;
    const dstMax = dstEl.scrollHeight - dstEl.clientHeight;
    dstEl.scrollTop = ratio * dstMax;

    // Use requestAnimationFrame to avoid jank
    requestAnimationFrame(() => {
      isSyncingScroll.current = false;
    });
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !task) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <AlertCircle className="mx-auto h-8 w-8 text-red-400 mb-3" />
          <p className="text-sm text-red-500">任务不存在或加载失败</p>
          <button onClick={() => router.push("/dashboard")} className="text-sm text-blue-600 mt-2 hover:underline">
            返回控制台
          </button>
        </div>
      </div>
    );
  }

  const statusCfg = STATUS_MAP[task.status] || STATUS_MAP.pending;

  // Non-success states: compact card view
  if (task.status !== "success") {
    return (
      <div className="min-h-screen bg-gray-50">
        <main className="max-w-3xl mx-auto p-8">
          <button
            onClick={() => router.push("/dashboard?tab=tasks")}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            返回任务列表
          </button>

          <div className="bg-white rounded-xl border border-gray-100 p-6">
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
              <span className={`text-xs px-2.5 py-1 rounded-full ${statusCfg.color}`}>
                {task.status === "processing" && <Loader2 className="h-3 w-3 animate-spin inline mr-1" />}
                {statusCfg.label}
              </span>
            </div>

            {task.status === "processing" && (
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden mb-4">
                <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${task.progress}%` }} />
              </div>
            )}

            {task.error_message && (
              <div className="mt-4 p-3 bg-red-50 border border-red-100 rounded-lg">
                <p className="text-xs text-red-600 font-medium mb-1">解析失败</p>
                <p className="text-xs text-red-500">{task.error_message}</p>
              </div>
            )}

            {(task.status === "failed" || task.status === "cancelled") && (
              <div className="mt-4">
                <button
                  onClick={handleRetry}
                  disabled={retrying}
                  className="flex items-center gap-2 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded-lg transition-colors"
                >
                  {retrying ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                  {retrying ? "重新提交中..." : "重新解析"}
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
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/dashboard?tab=tasks")}
            className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            返回
          </button>
          <div className="w-px h-4 bg-gray-200" />
          <FileText className="h-4 w-4 text-gray-400" />
          <span className="text-sm font-medium text-gray-900 truncate max-w-[300px]">{task.original_filename}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${statusCfg.color}`}>{statusCfg.label}</span>
        </div>
        <div className="flex items-center gap-2">
          {results?.files?.length > 0 && (
            <a
              href={results.files[0].download_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-800 bg-gray-50 hover:bg-gray-100 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              下载全部
            </a>
          )}
        </div>
      </div>

      {/* Split content */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: Source file preview */}
        <div className="w-1/2 border-r border-gray-200 flex flex-col bg-gray-100">
          <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-100 flex-shrink-0">
            <span className="text-xs font-medium text-gray-600">原文预览</span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setZoom((z) => Math.max(50, z - 10))}
                className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
                title="缩小"
              >
                <ZoomOut className="h-3.5 w-3.5" />
              </button>
              <span className="text-xs text-gray-500 w-10 text-center">{zoom}%</span>
              <button
                onClick={() => setZoom((z) => Math.min(200, z + 10))}
                className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
                title="放大"
              >
                <ZoomIn className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div
            ref={leftScrollRef}
            onScroll={() => handleScroll("left")}
            className="flex-1 overflow-auto p-4"
          >
            {usePdfRenderer ? (
              <PdfViewer url={originFileUrl} zoom={zoom} />
            ) : sourceIsImage && originFileUrl ? (
              <div className="flex justify-center">
                <img
                  src={originFileUrl}
                  alt="源文件预览"
                  className="bg-white shadow-lg rounded max-w-none"
                  style={{ width: `${zoom}%` }}
                />
              </div>
            ) : sourceIsOffice && originFileUrl && previewType !== "pdf" ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-20 w-full">
                <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 max-w-sm w-full">
                  <div className="w-16 h-16 bg-blue-50 rounded-xl flex items-center justify-center mx-auto mb-4">
                    <FileSpreadsheet className="h-8 w-8 text-blue-500" />
                  </div>
                  <p className="text-sm font-medium text-gray-700 mb-1">{task.original_filename}</p>
                  <p className="text-xs text-gray-400 mb-4">
                    {officeType} 文件 · {(task.file_size_bytes / 1024 / 1024).toFixed(1)} MB
                  </p>
                  <p className="text-xs text-gray-400 mb-4">该文件类型暂不支持在线预览，请下载后查看</p>
                  <a
                    href={originFileUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-xs text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors"
                  >
                    <Download className="h-3.5 w-3.5" />
                    下载原文件
                  </a>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center py-20">
                <FileText className="h-16 w-16 text-gray-200 mb-4" />
                <p className="text-sm text-gray-400 mb-1">{task.original_filename}</p>
                <p className="text-xs text-gray-300">
                  {(task.file_size_bytes / 1024 / 1024).toFixed(1)} MB · {task.backend} · {task.language}
                </p>
                <p className="text-xs text-gray-300 mt-4">该文件类型暂不支持在线预览</p>
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
              {copied ? "已复制" : "复制"}
            </button>
          </div>

          {/* Markdown content */}
          <div
            ref={rightScrollRef}
            onScroll={() => handleScroll("right")}
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
                    <div dangerouslySetInnerHTML={{ __html: preview.markdown_content }} />
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {preview.markdown_content}
                    </ReactMarkdown>
                  )
                ) : (
                  <pre className="bg-gray-50 rounded-lg p-4 text-xs text-gray-700 whitespace-pre-wrap">
                    {preview?.content || "暂无预览内容"}
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
