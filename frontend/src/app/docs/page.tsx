"use client";

import Link from "next/link";
import {
  ArrowLeft, BookOpen, CheckCircle2, Code2, KeyRound, Link2, RefreshCw,
  ShieldCheck, UploadCloud, Webhook,
} from "lucide-react";
import { getApiOrigin } from "@/lib/runtime-config";

const API_ORIGIN = getApiOrigin() || "http://localhost:8000";
const API_BASE = `${API_ORIGIN}/api/v1`;
const PRECISION_BASE = `${API_ORIGIN}/api/v4`;
const AGENT_BASE = `${API_ORIGIN}/api/v1/agent`;

const codeBlocks = {
  token: `curl -X POST ${API_BASE}/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"service-account","password":"your-password"}'`,
  uploadUrl: `curl -X POST ${API_BASE}/tasks/upload-url \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"filename":"demo.pdf","content_type":"application/pdf","file_size_bytes":1048576}'`,
  createTask: `curl -X POST ${API_BASE}/tasks/ \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "s3_key":"uploads/user/demo.pdf",
    "original_filename":"demo.pdf",
    "file_size_bytes":1048576,
    "backend":"",
    "output_format":"markdown",
    "callback_url":"https://internal.example.com/mineru/callback",
    "callback_seed":"your-sign-secret"
  }'`,
  batchTasks: `curl -X POST ${API_BASE}/tasks/batch/tasks \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '[{
    "s3_key":"uploads/user/a.pdf",
    "original_filename":"a.pdf",
    "file_size_bytes":1048576,
    "output_format":"markdown"
  }]'`,
  result: `curl -H "Authorization: Bearer $TOKEN" \\
  ${API_BASE}/tasks/$TASK_ID/results`,
  officialTask: `curl -X POST ${PRECISION_BASE}/extract/task \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "url":"https://internal.example.com/files/demo.pdf",
    "is_ocr":false,
    "enable_formula":true,
    "enable_table":true,
    "callback":"https://internal.example.com/mineru/callback",
    "seed":"your-sign-secret"
  }'`,
  officialBatch: `curl -X POST ${PRECISION_BASE}/extract/task/batch \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"files":[{"url":"https://internal.example.com/files/a.pdf","data_id":"a"}]}'`,
  agent: `curl -X POST ${AGENT_BASE}/parse/url \\
  -H "Content-Type: application/json" \\
  -d '{"url":"https://internal.example.com/files/demo.pdf","page_range":"1-5"}'`,
  webhook: `{
  "task_id": "3f8c...",
  "status": "success",
  "timestamp": "2026-05-10T12:00:00+00:00",
  "data_id": "business-id-001",
  "progress": 100,
  "error_message": null,
  "output_s3_prefix": "results/user/...",
  "created_at": "2026-05-10T11:59:00+00:00",
  "completed_at": "2026-05-10T12:00:00+00:00"
}`,
};

const apiGroups = [
  {
    title: "认证",
    rows: [
      ["POST", "/api/v1/auth/login", "账号密码登录，返回 access_token / refresh_token"],
      ["POST", "/api/v1/auth/refresh", "刷新访问令牌"],
      ["GET", "/api/v1/auth/sso/config", "读取 SSO 自动登录配置"],
    ],
  },
  {
    title: "任务 API",
    rows: [
      ["POST", "/api/v1/tasks/upload-url", "获取单文件预签名上传地址"],
      ["POST", "/api/v1/tasks/", "创建单个解析任务"],
      ["GET", "/api/v1/tasks/", "分页查询当前用户任务"],
      ["GET", "/api/v1/tasks/{task_id}", "查询任务状态和基础信息"],
      ["POST", "/api/v1/tasks/{task_id}/favorite", "收藏或取消收藏任务"],
      ["GET", "/api/v1/tasks/{task_id}/results", "获取解析结果下载链接"],
      ["GET", "/api/v1/tasks/{task_id}/preview", "获取页面预览数据"],
      ["POST", "/api/v1/tasks/{task_id}/retry", "重新解析失败或已停止任务"],
      ["POST", "/api/v1/tasks/{task_id}/cancel", "停止等待中或解析中的任务"],
      ["DELETE", "/api/v1/tasks/{task_id}", "删除任务记录"],
      ["POST", "/api/v1/tasks/batch/upload-urls", "批量获取上传地址，单次最多 100 个文件"],
      ["POST", "/api/v1/tasks/batch/tasks", "批量创建解析任务，单次最多 100 个文件"],
      ["POST", "/api/v1/tasks/batch/download", "批量导出结果 ZIP"],
    ],
  },
  {
    title: "官方兼容 API",
    rows: [
      ["POST", "/api/v4/extract/task", "按 URL 创建单文件解析任务"],
      ["GET", "/api/v4/extract/task/{task_id}", "查询官方兼容任务结果"],
      ["POST", "/api/v4/file-urls/batch", "批量获取官方兼容上传地址，单次最多 100 个文件"],
      ["POST", "/api/v4/extract/task/batch", "批量 URL 解析，单次最多 100 个文件"],
      ["GET", "/api/v4/extract-results/batch/{batch_id}", "查询批量解析结果"],
      ["POST", "/tasks", "简化官方兼容任务提交"],
      ["GET", "/tasks/{task_id}", "简化官方兼容任务状态"],
      ["GET", "/tasks/{task_id}/result", "简化官方兼容任务结果"],
      ["POST", "/file_parse", "同步风格文件解析接口"],
    ],
  },
  {
    title: "Agent 轻量 API",
    rows: [
      ["POST", "/api/v1/agent/parse/url", "无需登录，按 URL 创建轻量解析任务"],
      ["POST", "/api/v1/agent/parse/file", "无需登录，获取轻量文件上传解析任务"],
      ["GET", "/api/v1/agent/parse/{task_id}", "查询轻量解析结果"],
    ],
  },
];

const flow = [
  { title: "获取访问令牌", icon: KeyRound, body: "任务 API 和官方兼容 v4 API 使用 Bearer Token。Agent 轻量 API 是受控内网入口，不要求登录。" },
  { title: "上传或提供 URL", icon: UploadCloud, body: "内网系统可使用预签名上传地址，也可以直接让官方兼容接口从 URL 拉取文件。" },
  { title: "创建解析任务", icon: Code2, body: "支持 PDF、图片、DOCX、PPTX、XLSX，可设置 OCR、公式、表格、页码范围和回调。" },
  { title: "查询或接收结果", icon: RefreshCw, body: "可轮询任务状态和结果，也可通过 webhook 在成功或失败时通知下游系统。" },
];

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-lg bg-gray-950 px-4 py-3 text-xs leading-relaxed text-gray-100">
      <code>{children}</code>
    </pre>
  );
}

function EndpointTable({ title, rows }: { title: string; rows: string[][] }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-gray-100">
            {rows.map(([method, path, desc]) => (
              <tr key={`${method}-${path}`}>
                <td className="whitespace-nowrap px-4 py-3 text-xs font-semibold text-blue-600">{method}</td>
                <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-gray-700">{path}</td>
                <td className="min-w-[220px] px-4 py-3 text-xs leading-5 text-gray-500">{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function DocsPage() {
  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
              <BookOpen className="h-3.5 w-3.5" />
              API Integration Guide
            </div>
            <h1 className="text-2xl font-semibold text-gray-900">MinerU 企业 API 接入指南</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">
              面向内部业务系统、知识库、数据中台和自动化 Agent 的接入说明，聚焦推荐调用链路和企业内集成注意事项。
            </p>
          </div>
          <Link
            href="/"
            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 transition hover:bg-gray-50 hover:text-gray-900"
          >
            <ArrowLeft className="h-4 w-4" />
            返回首页
          </Link>
        </div>

        <section className="grid grid-cols-1 gap-3 md:grid-cols-4">
          {[
            ["Web 控制台", "人工上传、查看进度和预览结果，适合日常使用。"],
            ["任务 API", "业务系统先拿上传地址，再创建任务，适合内网系统集成。"],
            ["官方兼容 API", "对齐 MinerU 常用输入输出形态，便于迁移已有调用方。"],
            ["Agent 轻量 API", "无需登录的受控内网入口，适合自动化 Agent 调用。"],
          ].map(([title, desc]) => (
            <div key={title} className="rounded-lg border border-gray-200 bg-white p-4">
              <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
              <p className="mt-2 text-xs leading-5 text-gray-500">{desc}</p>
            </div>
          ))}
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-base font-semibold text-gray-900">推荐接入流程</h2>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            {flow.map((step) => {
              const Icon = step.icon;
              return (
                <div key={step.title} className="rounded-lg bg-gray-50 p-4">
                  <Icon className="h-4 w-4 text-blue-600" />
                  <h3 className="mt-3 text-sm font-medium text-gray-900">{step.title}</h3>
                  <p className="mt-2 text-xs leading-5 text-gray-500">{step.body}</p>
                </div>
              );
            })}
          </div>
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-blue-600" />
              <h2 className="text-base font-semibold text-gray-900">鉴权</h2>
            </div>
            <p className="text-sm leading-6 text-gray-500">
              任务 API 使用 Bearer Token。调用方建议使用内部服务账号，避免复用个人管理员账号。
            </p>
            <CodeBlock>{codeBlocks.token}</CodeBlock>
          </div>

          <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              <h2 className="text-base font-semibold text-gray-900">支持范围</h2>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm text-gray-600">
              {["PDF", "PNG/JPG/WebP/TIFF", "DOCX", "PPTX", "XLSX", "Markdown/JSON/ZIP 结果"].map((item) => (
                <div key={item} className="rounded-lg bg-gray-50 px-3 py-2">{item}</div>
              ))}
            </div>
            <p className="text-xs leading-5 text-gray-400">
              单次最多 100 个文件，单文件最大 300 页。Office 文件会先转换后解析；生产 GPU 模式建议只启用 GPU worker。
            </p>
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-base font-semibold text-gray-900">暴露的 API</h2>
          <div className="grid grid-cols-1 gap-4">
            {apiGroups.map((group) => (
              <EndpointTable key={group.title} title={group.title} rows={group.rows} />
            ))}
          </div>
        </section>

        <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-base font-semibold text-gray-900">任务 API 示例</h2>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">1. 获取上传地址</h3>
              <CodeBlock>{codeBlocks.uploadUrl}</CodeBlock>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">2. 创建解析任务</h3>
              <CodeBlock>{codeBlocks.createTask}</CodeBlock>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">3. 批量创建任务</h3>
              <CodeBlock>{codeBlocks.batchTasks}</CodeBlock>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-gray-700">4. 查询结果</h3>
              <CodeBlock>{codeBlocks.result}</CodeBlock>
            </div>
          </div>
        </section>

        <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-base font-semibold text-gray-900">官方兼容 API 示例</h2>
          <p className="text-sm leading-6 text-gray-500">
            已有 MinerU 调用方可以优先接入 `/api/v4/extract/task` 和批量接口。参数里的 `callback` 和 `seed` 会映射到企业版任务的 webhook 配置。
          </p>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <CodeBlock>{codeBlocks.officialTask}</CodeBlock>
            <CodeBlock>{codeBlocks.officialBatch}</CodeBlock>
          </div>
        </section>

        <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-base font-semibold text-gray-900">Agent 轻量 API 示例</h2>
          <p className="text-sm leading-6 text-gray-500">
            该入口不要求登录，适合放在受控内网里给 Agent 或自动化任务调用。生产环境建议在网关层增加 IP 白名单或访问控制。
          </p>
          <CodeBlock>{codeBlocks.agent}</CodeBlock>
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-2">
              <Webhook className="h-4 w-4 text-blue-600" />
              <h2 className="text-base font-semibold text-gray-900">Webhook 回调</h2>
            </div>
            <p className="text-sm leading-6 text-gray-500">
              任务成功或失败时会 POST 到 `callback_url`。若提供 `seed`，请求头包含 `X-MinerU-Signature`。
            </p>
            <CodeBlock>{codeBlocks.webhook}</CodeBlock>
          </div>

          <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 text-amber-600" />
              <div>
                <h2 className="text-base font-semibold text-amber-900">生产环境建议</h2>
                <div className="mt-3 space-y-2 text-sm leading-6 text-amber-800">
                  <p>Token、webhook seed 放入企业密钥管理系统。</p>
                  <p>生产 GPU 模式设置 `FORCE_GPU_QUEUE=true`，只启 `worker-gpu`。</p>
                  <p>无外网环境需要提前把 MinerU 模型放入 `backend/mineru-models/` 并打入 worker 镜像。</p>
                  <p>Webhook 接收方应校验 HMAC 签名，并对重复回调做幂等处理。</p>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
