# MinerU Enterprise

基于 [MinerU](https://github.com/opendatalab/MinerU) 解析内核的自托管文档处理平台。项目将解析能力接入账号、任务队列、对象存储和管理界面，适合需要多人使用、留存结果并自行管理文件的场景。本项目由社区独立维护，不属于 MinerU 官方仓库。

![上传、解析和预览流程示意](docs/assets/workflow.gif)

> GIF 为根据当前界面绘制的流程示意，使用虚构文件；实际运行画面与任务耗时取决于部署环境。

## 当前能力

- **解析任务**：PDF、常见图片和 Office 文件上传，Celery + Redis 异步处理，支持批量创建、状态查询、取消、重试和结果下载。
- **解析内核**：CPU 与 GPU Worker 均固定依赖 MinerU **4.0.10**。后端接受 `flash`、`basic`、`standard`、`advanced`，并映射旧名称 `pipeline`、`hybrid`、`vlm`。
- **结果查看**：任务详情提供源文件与 Markdown 对照预览、复制和下载；后台还提供任务记录与统计。
- **身份与存储**：本地账号、OIDC、LDAP、企业微信、钉钉；预签名 URL 直传 S3 兼容存储，可使用 MinIO。
- **部署**：Docker Compose 编排 Next.js、FastAPI、PostgreSQL、Redis、MinIO、Nginx 和 Worker；可选 NVIDIA GPU 服务。

## 与官方 MinerU 4.0.10 对比

这里的“官方”指 [opendatalab/MinerU 4.0.10 开源版](https://github.com/opendatalab/MinerU/tree/mineru-4.0.10-released)，不是 MinerU 云服务。官方 4.0 本身已有 WebUI、自托管 V1 API、批量解析和 Docker 部署；本项目侧重多人任务管理与对象存储集成。对比依据：[官方 4.0.10 README](https://github.com/opendatalab/MinerU/blob/mineru-4.0.10-released/README.md)、[4.0.10 发布说明](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.10-released)。

4.0.10 的新增修复针对官方 WebUI 在非安全 HTTP 环境下无法使用 `crypto.randomUUID` 的情况；本项目使用独立的 Next.js 前端，因此该 WebUI 修复不直接改变本项目界面。

| 能力 | 官方 MinerU 4.0.10 | 本项目 |
|---|---|---|
| 解析内核 | 官方 4.0.10 | Worker 使用同版本的 `mineru-kit parse` |
| 输入 | PDF、图片、Office、OpenDocument、RTF、EPUB、OFD、HTML/MHTML、CSV/TSV 等 | Web 上传：PDF、图片、DOCX、PPTX、XLSX；后端还接受旧 Office 格式和 HTML。MHTML、EPUB、OFD、CSV/TSV 等尚未接入上传入口 |
| 解析档位 | `flash` / `basic` / `standard` / `advanced` | 后端接受四档；当前 Web 界面提供 Pipeline（映射 `basic`）和 VLM（映射 `advanced`）。Office/HTML 在 Worker 中使用 `flash` |
| 输出 | 统一文档模型，按接口导出 Markdown、HTML、LaTeX、DOCX、EPUB、PDF、结构化内容等 | 任务保存 MinerU 解析结果并提供 Markdown/JSON；可从 Markdown 生成简易 HTML、DOCX、LaTeX，保真度不等同于官方对应渲染器 |
| WebUI | 官方 Gradio WebUI | Next.js 上传、任务列表、源文件与结果对照预览、管理页面 |
| API | 官方 `/v1/*` 解析服务、SDK、Router | 自有 `/api/v1/*`、`/api/v4/extract/*` 和旧式 `/tasks`、`/file_parse` 兼容入口；**尚不实现官方 4.0 的 `/v1/*` 协议** |
| 本地文档库 | 搜索、缓存、页/块定位与继续阅读 | 尚未接入官方 doclib；以任务和结果文件为中心 |
| 多人协作 | 官方开源 CLI、服务和 WebUI | 账号、角色、管理后台、API Token、可选 SSO 与组织数据模型 |
| 任务与存储 | 官方无状态批处理、V1 作业与本地文档库 | Celery 队列、任务历史、WebSocket 进度、S3 兼容对象存储 |
| 部署 | 官方提供本地运行与 Docker 方案 | Compose 部署完整应用栈，可选 CPU/GPU Worker |

**参数边界**：当前 Worker 会将档位、OCR 模式、PDF 页码范围和图像分析选项传给 MinerU 4.0 CLI。前端和 API 仍接收语言、公式、表格开关，但这些字段目前没有映射到 4.0 CLI 的独立参数；请勿将它们视为已生效的解析控制项。

## 快速开始

### 1. 克隆并配置

```bash
git clone https://github.com/medisean/mineru-enterprise.git
cd mineru-enterprise
cp .env.example .env
```

编辑 `.env`，至少更换 `SECRET_KEY`、PostgreSQL 和 MinIO 的默认口令，并按部署环境配置对外地址。模型文件不打入镜像；设置 `MINERU_MODELS_HOST_PATH` 指向主机上的持久目录，例如：

```env
MINERU_MODELS_HOST_PATH=/data/mineru-models
```

该目录会挂载为容器内的 `/opt/mineru-models`。在外接硬盘部署时，可填入外接盘上的**绝对路径**。模型下载和校验均在这个挂载目录进行。

### 2. 构建并启动

```bash
docker compose --profile minio --profile proxy up -d --build
```

访问 `http://localhost`。前端直连端口为 `3000`，API 直连端口为 `8000`，MinIO 控制台为 `9001`。本地开发如需 FastAPI 文档，可在 `.env` 中设 `DEBUG=true` 后重启 API，再访问 `http://localhost/api/docs`。

也可使用 `bash scripts/start.sh dev`；GPU 服务器使用 `bash scripts/start.sh gpu`，需 NVIDIA 驱动和 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)。

### 3. 准备本地模型

Worker 默认从挂载目录读取模型（`MINERU_MODEL_SOURCE=local`）。首次解析前，下载适合所选档位的模型：

```bash
# CPU Basic：ONNX 小模型
docker compose --profile minio --profile proxy run --rm worker \
  mineru-kit models download --tier basic --small-backend onnx --source modelscope

# 本地 llama.cpp VLM：供 Standard / Advanced 使用
docker compose --profile minio --profile proxy run --rm worker \
  mineru-kit models download MinerU2.5-Pro-2605-1.2B-GGUF --source modelscope
```

模型来源也可按官方 [模型配置文档](https://github.com/opendatalab/MinerU/blob/mineru-4.0.10-released/docs/en/usage/model_source.md) 选择 Hugging Face。GPU 部署需要按所用推理引擎准备对应权重；以上 GGUF 示例针对本地 llama.cpp。

### 4. 使用

在网页注册或登录，上传文件并选择解析引擎；任务完成后进入详情页查看原文、Markdown 和下载结果。Web 界面单次最多选择 100 个文件，单文件上传上限默认 50 MB；实际解析还受页数、模型、硬件和服务配置限制。

## 架构

```text
浏览器 ──> Next.js / Nginx ──> FastAPI ──> PostgreSQL
   │                           │
   └── 预签名 URL 直传 ────────> S3 / MinIO
                               │
                               └── Redis / Celery ──> MinerU Worker
                                                      └── 挂载的本地模型目录
```

API 创建任务后，Worker 从对象存储读取源文件，调用 MinerU 4.0.10 CLI，并将结果写回对象存储。WebSocket 提供任务进度；任务详情页读取预览内容与结果下载地址。

## API 入口

| 路径 | 用途 |
|---|---|
| `POST /api/v1/auth/login` | 本地登录 |
| `POST /api/v1/tasks/upload-url` | 申请预签名上传 URL |
| `POST /api/v1/tasks/`、`GET /api/v1/tasks/` | 创建与查询任务 |
| `GET /api/v1/tasks/{id}/preview` | 读取解析预览 |
| `GET /api/v1/tasks/{id}/results` | 获取结果文件 |
| `POST /api/v1/tasks/batch/upload-urls`、`POST /api/v1/tasks/batch/tasks` | 批量上传准备与任务创建 |
| `POST /file_parse`、`POST /tasks` | 项目保留的旧式兼容入口 |

兼容入口服务于已有调用方，接口形状与官方 MinerU 4.0 的 V1 API 不相同。完整配置项见 [`.env.example`](.env.example)，镜像构建脚本见 [`scripts/build-images.sh`](scripts/build-images.sh)。

## 运行记录

本地 ARM64 CPU 环境已用 MinerU 4.0.10 验证：ONNX Basic 模型校验通过；GGUF VLM 模型校验通过，并完成一页 PDF 的 Advanced 解析。该环境没有 CUDA，VLM 单页示例耗时约 48 秒。此记录仅说明本地路径可运行，不代表其他硬件的吞吐量或 GPU 镜像已验证。
