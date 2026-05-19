"use client";
/**
 * File upload component with drag-and-drop support.
 * Step 1: Get presigned URL from backend
 * Step 2: PUT file directly to S3
 * Step 3: Create parse task
 */
import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload, FileText, X, CheckCircle, Loader2,
  Settings2, ChevronDown, ChevronUp, Table,
  Calculator, ScanLine, Languages,
} from "lucide-react";
import axios from "axios";
import { tasksApi } from "@/lib/api";
import { useT } from "@/lib/i18n/use-translation";

interface UploadedFile {
  file: File;
  s3Key?: string;
  taskId?: string;
  status: "idle" | "uploading" | "creating_task" | "done" | "error";
  progress: number;
  error?: string;
}

export interface CreatedTask {
  id: string;
  original_filename: string;
  file_size_bytes: number;
  status: string;
  progress: number;
  is_favorite?: boolean;
  backend: string;
  output_format: string;
  created_at: string;
}

interface UploadPanelProps {
  onTaskCreated?: (task: CreatedTask) => void;
}

const ACCEPT_TYPES: Record<string, string[]> = {
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "image/png": [".png"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/jp2": [".jp2"],
  "image/jpeg2000": [".jp2"],
  "image/gif": [".gif"],
  "image/bmp": [".bmp"],
  "image/webp": [".webp"],
  "image/tiff": [".tiff"],
};

const MAX_FILES = 100;
const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_PAGES = 300;

export function UploadPanel({ onTaskCreated }: UploadPanelProps) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const t = useT();

  // Parse config — backend defaults to empty (MinerU v3 uses hybrid-auto-engine by default)
  const [backend, setBackend] = useState("");
  const [language, setLanguage] = useState("");  // empty = auto (MinerU defaults to 'ch')
  const [isOcr, setIsOcr] = useState<boolean | null>(null); // null = auto
  const [enableFormula, setEnableFormula] = useState(true);
  const [enableTable, setEnableTable] = useState(true);
  const [pageRanges, setPageRanges] = useState("");

  const onDrop = useCallback((accepted: File[]) => {
    setFiles((prev) => {
      const existingNames = new Set(prev.map((f) => f.file.name));
      const unique = accepted.filter((f) => !existingNames.has(f.name));
      const remaining = MAX_FILES - prev.length;
      const toAdd = remaining > 0 ? unique.slice(0, remaining) : [];
      return [
        ...prev,
        ...toAdd.map((f) => ({
          file: f,
          status: "idle" as const,
          progress: 0,
        })),
      ];
    });
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPT_TYPES,
    maxSize: MAX_FILE_SIZE_MB * 1024 * 1024,
    maxFiles: MAX_FILES,
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
        output_format: "markdown",
        language: language || undefined,
        is_ocr: isOcr,
        enable_formula: enableFormula,
        enable_table: enableTable,
        page_ranges: pageRanges || undefined,
      });

      updateFile({ status: "done", progress: 100, taskId: taskRes.data.id });
      onTaskCreated?.(taskRes.data);
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
        className={`min-h-[220px] border-2 border-dashed rounded-xl px-10 py-12 text-center cursor-pointer transition-colors flex flex-col items-center justify-center ${
          isDragActive
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 hover:border-gray-400 bg-gray-50"
        }`}
      >
        <input {...getInputProps()} />
        <Upload className="mx-auto h-10 w-10 text-gray-400 mb-3" />
        <p className="text-sm text-gray-600">
          {isDragActive ? t("upload.dragActive") : t("upload.dragIdle")}
        </p>
        <p className="text-xs text-gray-400 mt-1">
          {t("upload.supportFormats")}
        </p>
        <p className="text-xs text-gray-300 mt-0.5">
          {t("upload.maxFilesHint", { max: MAX_FILES, pages: MAX_FILE_PAGES })}
        </p>
      </div>

      {/* Engine & Language Config */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
            <Languages className="h-3.5 w-3.5" /> {t("upload.docLanguage")}
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2"
          >
            <option value="">{t("upload.autoDetect")}</option>
            <option value="ch">{t("upload.langZh")}</option>
            <option value="en">{t("upload.langEn")}</option>
            <option value="japan">{t("upload.langJapan")}</option>
            <option value="korean">{t("upload.langKorean")}</option>
            <option value="chinese_cht">{t("upload.langCht")}</option>
            <option value="latin">{t("upload.langLatin")}</option>
            <option value="cyrillic">{t("upload.langRussian")}</option>
          </select>
        </div>
        <div>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
            {t("upload.parseEngine")}
          </label>
          <select
            value={backend}
            onChange={(e) => setBackend(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2"
          >
            <option value="">{t("upload.engineAuto")}</option>
            <option value="pipeline">{t("upload.enginePipeline")}</option>
            <option value="hybrid-auto-engine">{t("upload.engineHybrid")}</option>
            <option value="vlm-auto-engine">{t("upload.engineVlm")}</option>
          </select>
        </div>
      </div>

      {/* Advanced Options Toggle */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors"
      >
        <Settings2 className="h-3.5 w-3.5" />
        {t("upload.advancedOptions")}
        {showAdvanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>

      {/* Advanced Options Panel */}
      {showAdvanced && (
        <div className="grid grid-cols-2 gap-4 p-4 bg-gray-50 border border-gray-100 rounded-xl">
          {/* OCR */}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <ScanLine className="h-3.5 w-3.5" /> {t("upload.ocrLabel")}
            </label>
            <select
              value={isOcr === null ? "auto" : isOcr ? "on" : "off"}
              onChange={(e) => {
                const v = e.target.value;
                setIsOcr(v === "auto" ? null : v === "on");
              }}
              className="text-xs border border-gray-200 rounded-md px-2 py-1"
            >
              <option value="auto">{t("upload.ocrAuto")}</option>
              <option value="on">{t("upload.ocrOn")}</option>
              <option value="off">{t("upload.ocrOff")}</option>
            </select>
          </div>

          {/* Formula */}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <Calculator className="h-3.5 w-3.5" /> {t("upload.formulaLabel")}
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
              <Table className="h-3.5 w-3.5" /> {t("upload.tableLabel")}
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
              <FileText className="h-3.5 w-3.5" /> {t("upload.pageRanges")}
            </label>
            <input
              type="text"
              value={pageRanges}
              onChange={(e) => setPageRanges(e.target.value)}
              placeholder={t("upload.pageRangesPlaceholder")}
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
          {t("upload.submitButton", { count: pendingCount })}
        </button>
      )}
    </div>
  );
}
