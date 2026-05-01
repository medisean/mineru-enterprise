"use client";
/**
 * File upload component with drag-and-drop support.
 * Step 1: Get presigned URL from backend
 * Step 2: PUT file directly to S3
 * Step 3: Create parse task
 *
 * Enhanced: supports all MinerU formats, full parse options, advanced config
 */
import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload, FileText, X, CheckCircle, Loader2,
  Settings2, ChevronDown, ChevronUp, Languages, Table,
  Calculator, ScanLine, FileOutput,
} from "lucide-react";
import axios from "axios";
import { tasksApi } from "@/lib/api";

interface UploadedFile {
  file: File;
  s3Key?: string;
  taskId?: string;
  status: "idle" | "uploading" | "creating_task" | "done" | "error";
  progress: number;
  error?: string;
}

interface UploadPanelProps {
  onTaskCreated?: (taskId: string) => void;
}

const ACCEPT_TYPES: Record<string, string[]> = {
  "application/pdf": [".pdf"],
  "application/msword": [".doc"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "application/vnd.ms-powerpoint": [".ppt"],
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "image/png": [".png"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/gif": [".gif"],
  "image/bmp": [".bmp"],
  "image/webp": [".webp"],
  "image/jp2": [".jp2"],
  "text/html": [".html"],
};

const LANGUAGE_OPTIONS = [
  { value: "ch", label: "中文 (简体)" },
  { value: "ch_server", label: "中文 (繁体/手写)" },
  { value: "en", label: "英文" },
  { value: "japan", label: "日文" },
  { value: "korean", label: "韩文" },
  { value: "chinese_cht", label: "繁体中文" },
  { value: "latin", label: "拉丁语系 (法/德/西/葡)" },
  { value: "arabic", label: "阿拉伯语系" },
  { value: "cyrillic", label: "西里尔语系 (俄/乌)" },
  { value: "devanagari", label: "天城文语系 (印地语)" },
];

const OUTPUT_FORMAT_OPTIONS = [
  { value: "markdown", label: "Markdown", desc: "通用格式，适合 RAG/LLM" },
  { value: "json", label: "JSON", desc: "结构化数据，方便程序处理" },
  { value: "both", label: "Markdown + JSON", desc: "同时输出两种格式" },
  { value: "docx", label: "DOCX", desc: "Word 文档格式" },
  { value: "html", label: "HTML", desc: "网页格式，可预览" },
  { value: "latex", label: "LaTeX", desc: "学术论文排版" },
];

export function UploadPanel({ onTaskCreated }: UploadPanelProps) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Parse config — backend defaults to empty (MinerU v3 uses hybrid-auto-engine by default)
  const [backend, setBackend] = useState("");
  const [outputFormat, setOutputFormat] = useState("markdown");
  const [language, setLanguage] = useState("ch");
  const [isOcr, setIsOcr] = useState<boolean | null>(null); // null = auto
  const [enableFormula, setEnableFormula] = useState(true);
  const [enableTable, setEnableTable] = useState(true);
  const [pageRanges, setPageRanges] = useState("");

  const onDrop = useCallback((accepted: File[]) => {
    setFiles((prev) => [
      ...prev,
      ...accepted.map((f) => ({
        file: f,
        status: "idle" as const,
        progress: 0,
      })),
    ]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPT_TYPES,
    maxSize: 200 * 1024 * 1024,
  });

  const uploadFile = async (index: number) => {
    const item = files[index];
    if (!item) return;

    const updateFile = (updates: Partial<UploadedFile>) => {
      setFiles((prev) => prev.map((f, i) => (i === index ? { ...f, ...updates } : f)));
    };

    try {
      updateFile({ status: "uploading", progress: 5 });
      const urlRes = await tasksApi.getUploadUrl(
        item.file.name,
        item.file.type || "application/octet-stream",
        item.file.size
      );
      const { upload_url, s3_key } = urlRes.data;

      await axios.put(upload_url, item.file, {
        headers: { "Content-Type": item.file.type || "application/octet-stream" },
        onUploadProgress: (e) => {
          const pct = Math.round((e.loaded / (e.total || 1)) * 75) + 5;
          updateFile({ progress: pct });
        },
      });

      updateFile({ status: "creating_task", progress: 85, s3Key: s3_key });
      const taskRes = await tasksApi.createTask({
        s3_key,
        original_filename: item.file.name,
        file_size_bytes: item.file.size,
        backend: backend || undefined,
        output_format: outputFormat,
        language,
        is_ocr: isOcr,
        enable_formula: enableFormula,
        enable_table: enableTable,
        page_ranges: pageRanges || undefined,
      });

      updateFile({ status: "done", progress: 100, taskId: taskRes.data.id });
      onTaskCreated?.(taskRes.data.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      updateFile({ status: "error", error: msg });
    }
  };

  const uploadAll = () => {
    files.forEach((f, i) => {
      if (f.status === "idle") uploadFile(i);
    });
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const pendingCount = files.filter((f) => f.status === "idle").length;

  return (
    <div className="space-y-4">
      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
          isDragActive
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 hover:border-gray-400 bg-gray-50"
        }`}
      >
        <input {...getInputProps()} />
        <Upload className="mx-auto h-10 w-10 text-gray-400 mb-3" />
        <p className="text-sm text-gray-600">
          {isDragActive ? "松开以上传文件" : "拖拽文件到此处，或点击选择"}
        </p>
        <p className="text-xs text-gray-400 mt-1">
          支持 PDF/DOC/DOCX/PPT/PPTX/XLSX/PNG/JPG/GIF/BMP/WebP/HTML，最大 200 MB
        </p>
      </div>

      {/* Basic Config Row */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
            <FileOutput className="h-3.5 w-3.5" /> 输出格式
          </label>
          <select
            value={outputFormat}
            onChange={(e) => setOutputFormat(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2"
          >
            {OUTPUT_FORMAT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
            <Languages className="h-3.5 w-3.5" /> 文档语言
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2"
          >
            {LANGUAGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
            解析引擎
          </label>
          <select
            value={backend}
            onChange={(e) => setBackend(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2"
          >
            <option value="">自动（推荐）</option>
            <option value="pipeline">Pipeline（传统管道）</option>
            <option value="hybrid-auto-engine">Hybrid（混合引擎）</option>
            <option value="vlm-auto-engine">VLM（视觉语言模型）</option>
          </select>
        </div>
      </div>

      {/* Advanced Options Toggle */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors"
      >
        <Settings2 className="h-3.5 w-3.5" />
        高级解析选项
        {showAdvanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>

      {/* Advanced Options Panel */}
      {showAdvanced && (
        <div className="grid grid-cols-2 gap-4 p-4 bg-gray-50 border border-gray-100 rounded-xl">
          {/* OCR */}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <ScanLine className="h-3.5 w-3.5" /> OCR 文字识别
            </label>
            <select
              value={isOcr === null ? "auto" : isOcr ? "on" : "off"}
              onChange={(e) => {
                const v = e.target.value;
                setIsOcr(v === "auto" ? null : v === "on");
              }}
              className="text-xs border border-gray-200 rounded-md px-2 py-1"
            >
              <option value="auto">自动检测</option>
              <option value="on">强制开启</option>
              <option value="off">关闭</option>
            </select>
          </div>

          {/* Formula */}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <Calculator className="h-3.5 w-3.5" /> 公式识别
            </label>
            <button
              onClick={() => setEnableFormula(!enableFormula)}
              className={`relative w-9 h-5 rounded-full transition-colors ${enableFormula ? "bg-blue-500" : "bg-gray-300"}`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                  enableFormula ? "translate-x-4" : ""
                }`}
              />
            </button>
          </div>

          {/* Table */}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <Table className="h-3.5 w-3.5" /> 表格识别
            </label>
            <button
              onClick={() => setEnableTable(!enableTable)}
              className={`relative w-9 h-5 rounded-full transition-colors ${enableTable ? "bg-blue-500" : "bg-gray-300"}`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                  enableTable ? "translate-x-4" : ""
                }`}
              />
            </button>
          </div>

          {/* Page Ranges */}
          <div>
            <label className="flex items-center gap-1.5 text-xs text-gray-600 mb-1">
              <FileText className="h-3.5 w-3.5" /> 页码范围
            </label>
            <input
              type="text"
              value={pageRanges}
              onChange={(e) => setPageRanges(e.target.value)}
              placeholder="例: 1-10 或 2,4-6"
              className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 placeholder:text-gray-300"
            />
          </div>
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((item, i) => (
            <div key={i} className="flex items-center gap-3 p-3 bg-white border border-gray-100 rounded-lg">
              <FileText className="h-5 w-5 text-gray-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{item.file.name}</p>
                <p className="text-xs text-gray-400">{(item.file.size / 1024 / 1024).toFixed(1)} MB</p>
                {item.status !== "idle" && (
                  <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${
                        item.status === "done"
                          ? "bg-green-500"
                          : item.status === "error"
                          ? "bg-red-500"
                          : "bg-blue-500"
                      }`}
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                )}
                {item.error && <p className="text-xs text-red-500 mt-0.5">{item.error}</p>}
              </div>
              {item.status === "done" ? (
                <CheckCircle className="h-5 w-5 text-green-500 flex-shrink-0" />
              ) : item.status === "uploading" || item.status === "creating_task" ? (
                <Loader2 className="h-5 w-5 text-blue-500 animate-spin flex-shrink-0" />
              ) : (
                <button onClick={() => removeFile(i)} className="text-gray-400 hover:text-gray-600">
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {pendingCount > 0 && (
        <button
          onClick={uploadAll}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
        >
          上传并解析 {pendingCount} 个文件
        </button>
      )}
    </div>
  );
}
