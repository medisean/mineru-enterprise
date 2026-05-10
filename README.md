# MinerU Enterprise

企业级 MinerU 文档解析平台。在原版 MinerU 的解析内核基础上，补齐了企业化所需的全套能力：

- **官方输入格式对齐**：PDF / 图片（PNG / JPEG / JP2 / WebP / GIF / BMP / JPG / TIFF）/ DOCX / PPTX / XLSX
- **丰富解析参数**：OCR 开关、公式识别、表格识别、页码范围、10+ 语言、3 种解析引擎
- **多种输出格式**：Markdown / JSON / DOCX / HTML / LaTeX
- **在线预览**：Markdown 渲染预览 + 一键复制 + 文件下载
- **批量处理**：支持批量上传、批量创建任务（单次最多 100 个）
- **单点登录（SSO）**：OIDC / LDAP / 企业微信 / 钉钉
- **文件直传 S3**：AWS S3 / MinIO / 阿里云 OSS / 腾讯云 COS
- **异步任务队列**：Celery + Redis，WebSocket 实时进度推送
- **多用户 / 组织管理**：账号、角色、配额
- **一键 Docker 部署**：支持 CPU 和 GPU 两种模式

---

## 功能对比（vs MinerU 官方）

| 能力 | MinerU 官方 | MinerU Enterprise |
|------|:-----------:|:-----------------:|
| 文件格式 | PDF/图片/DOCX/PPTX/XLSX | 同官方，全部对齐 |
| 解析引擎 | pipeline / vlm / MinerU-HTML | 同官方 |
| 解析参数 | OCR / 公式 / 表格 / 页码范围 / 语言 | 同官方，全部对齐 |
| 输出格式 | Markdown / JSON / DOCX / HTML / LaTeX | 同官方 |
| 批量处理 | 最多 100 个 | 同官方 |
| 在线预览 | CDN Markdown | 自托管 Markdown/HTML/JSON 预览 |
| 认证方式 | Token | **OIDC / LDAP / 企微 / 钉钉 + 本地** |
| 文件存储 | 官方 CDN | **S3 / MinIO / OSS / COS 自托管** |
| 多用户 | 无 | **组织 + 角色 + 配额** |
| 部署方式 | 云端 | **Docker 自托管 + Nginx** |

---

## 架构

```
用户浏览器
    │
    ▼
Next.js 前端 (3000)
    │
    ▼
FastAPI 后端 (8000)
    │
    ├─→ PostgreSQL (元数据/用户/任务)
    ├─→ Redis (Celery 队列 + 缓存)
    ├─→ S3/MinIO (文件存储)
    └─→ Celery Worker
            ├─→ CPU Worker (MINERU_DEVICE=cpu)
            └─→ GPU Worker (MINERU_DEVICE=cuda, 可选)
                    └─→ MinerU 解析引擎
```

### 核心数据流

```
浏览器 → getUploadUrl(API) → 预签名 URL
浏览器 → PUT 直传 S3（绕过 API，减少服务器带宽）
浏览器 → createTask(API) → Celery 队列
Worker → 从 S3 下载 → mineru CLI（含全部参数）→ 结果上传 S3
浏览器 ← WebSocket 实时进度 ← Worker 更新 DB
浏览器 → getPreview(API) → 在线 Markdown/HTML 渲染
```

---

## 快速开始

### 1. 克隆并配置

```bash
git clone https://github.com/your-org/mineru-enterprise
cd mineru-enterprise
cp .env.example .env
# 编辑 .env 填入实际配置
```

### 2. 启动（本地开发，含 MinIO）

```bash
bash scripts/start.sh dev
```

访问：
- 前端：http://localhost:3000
- API 文档：http://localhost:8000/api/docs
- MinIO 控制台：http://localhost:9001

### 3. 生产部署（含 Nginx + HTTPS）

```bash
# 将 SSL 证书放到 docker/ssl/
bash scripts/start.sh prod
```

### 4. GPU 模式（远端部署）

GPU 模式需要服务器已安装 [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)。

```bash
bash scripts/start.sh gpu
```

GPU 模式会同时启动 CPU Worker 和 GPU Worker，共享同一个任务队列。GPU Worker 优先消费任务，CPU Worker 作为兜底。

#### 工作原理

| 组件 | CPU 模式 (`dev`) | GPU 模式 (`gpu`) |
|------|:---:|:---:|
| Worker 镜像 | `Dockerfile.worker` (python:3.11-slim) | `Dockerfile.worker.gpu` (nvidia/cuda:12.4) |
| PyTorch | CPU-only wheel | CUDA 12.4 wheel |
| `MINERU_DEVICE` | `cpu` | `cuda` |
| GPU 设备 | 无 | nvidia GPU passthrough |

#### 配置项

```env
MINERU_DEVICE=cpu           # cpu | cuda | mps（默认 cpu，GPU 模式自动设为 cuda）
NVIDIA_VISIBLE_DEVICES=all  # 指定可见 GPU，如 "0" 或 "0,1"
GPU_WORKER_DEVICES=         # 可选：指定 GPU worker 使用哪些卡，如 "0,1"；为空则使用所有可见卡
```

GPU worker 启动时会按 GPU 卡号启动多个 Celery worker：每张卡 1 个 worker，每个 worker 并发固定为 1。

> 本地开发默认使用 CPU 模式，无需 GPU 驱动。

### 5. 单独构建服务镜像

项目内置 `scripts/build-images.sh`，可以按服务独立打镜像，也可以一次构建全部业务镜像。

```bash
# 默认镜像名：
# mineru-enterprise/api:latest
# mineru-enterprise/web:latest
# mineru-enterprise/worker:latest
# mineru-enterprise/worker-gpu:latest
# mineru-enterprise/nginx:latest

bash scripts/build-images.sh api
bash scripts/build-images.sh web
bash scripts/build-images.sh worker
bash scripts/build-images.sh worker-gpu
bash scripts/build-images.sh nginx
bash scripts/build-images.sh cpu     # api + web + CPU worker + nginx
bash scripts/build-images.sh all     # api + web + CPU worker + GPU worker + nginx
```

自定义仓库、版本号、平台和推送：

```bash
IMAGE_REPOSITORY=registry.example.com/mineru \
IMAGE_TAG=v1.0.0 \
PLATFORM=linux/amd64 \
PUSH=true \
bash scripts/build-images.sh all
```

构建时可以按服务切换基础镜像和依赖源：

```bash
# API / CPU Worker: Python 基础镜像、Debian apt 源、pip 源
PYTHON_BASE_IMAGE=registry.example.com/library/python:3.11-slim \
DEBIAN_APT_MIRROR=https://mirrors.aliyun.com/debian \
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
bash scripts/build-images.sh api

# Web: Node 基础镜像、Alpine 源、npm 源
NODE_BASE_IMAGE=registry.example.com/library/node:20-alpine \
ALPINE_MIRROR=https://mirrors.aliyun.com/alpine \
NPM_REGISTRY=https://registry.npmmirror.com \
bash scripts/build-images.sh web

# CPU Worker: 默认只走 pip 源；如需单独 PyTorch wheel 源可设置 PYTORCH_INDEX_URL
DEBIAN_APT_MIRROR=https://mirrors.aliyun.com/debian \
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
bash scripts/build-images.sh worker

# GPU Worker: CUDA 基础镜像、Ubuntu apt 源；默认只走 pip 源
CUDA_BASE_IMAGE=registry.example.com/nvidia/cuda:12.4.1-runtime-ubuntu22.04 \
UBUNTU_APT_MIRROR=https://mirrors.aliyun.com/ubuntu \
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
bash scripts/build-images.sh worker-gpu

# Nginx: Nginx 基础镜像、Alpine 源
NGINX_BASE_IMAGE=registry.example.com/library/nginx:1.27-alpine \
ALPINE_MIRROR=https://mirrors.aliyun.com/alpine \
bash scripts/build-images.sh nginx
```

前端镜像会在构建时固化 `NEXT_PUBLIC_API_URL`：

```bash
NEXT_PUBLIC_API_URL=https://api.example.com \
IMAGE_REPOSITORY=registry.example.com/mineru \
IMAGE_TAG=v1.0.0 \
bash scripts/build-images.sh web
```

Worker 镜像支持构建参数：

```bash
TORCH_VERSION=2.7.0 bash scripts/build-images.sh worker
CUDA_VERSION=cu124 bash scripts/build-images.sh worker-gpu
```

`worker` 和 `worker-gpu` 不在构建阶段下载 MinerU 模型。构建前需要准备本地模型包：

```text
backend/mineru-models/   # 已下载好的 MinerU 模型文件
backend/mineru.json      # MinerU 本地模型配置
```

构建时会把 `backend/mineru-models/` 复制到镜像内 `/opt/mineru-models/`，并把 `backend/mineru.json` 复制到镜像内 `/root/mineru.json`。运行时默认设置 `MINERU_MODEL_SOURCE=local`、`HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1`，不会尝试联网下载模型。

`docker-compose.yml` 也已绑定同一套镜像变量。构建或部署指定版本：

```bash
IMAGE_REPOSITORY=registry.example.com/mineru IMAGE_TAG=v1.0.0 docker compose build api web
IMAGE_REPOSITORY=registry.example.com/mineru IMAGE_TAG=v1.0.0 docker compose up -d
```

---

## 目录结构

```
mineru-enterprise/
├── backend/                    # FastAPI 后端
│   ├── main.py                 # 应用入口
│   ├── alembic/                # 数据库迁移
│   │   ├── versions/           # 迁移脚本
│   │   └── env.py              # Alembic 配置
│   ├── alembic.ini             # Alembic 入口
│   ├── app/
│   │   ├── api/v1/endpoints/   # API 路由
│   │   │   ├── auth.py         # 认证（本地 + SSO）
│   │   │   ├── tasks.py        # 文件上传 + 任务管理 + 批量 + 预览
│   │   │   ├── users.py        # 用户信息
│   │   │   └── ws.py           # WebSocket 进度推送
│   │   ├── core/
│   │   │   ├── config.py       # 所有配置项（从环境变量读取）
│   │   │   ├── database.py     # 数据库连接
│   │   │   ├── security.py     # JWT / 密码哈希
│   │   │   └── deps.py         # FastAPI 依赖注入
│   │   ├── models/models.py    # SQLAlchemy ORM 模型
│   │   ├── schemas/schemas.py  # Pydantic 请求/响应模型
│   │   ├── services/
│   │   │   ├── storage.py      # S3 通用存储服务
│   │   │   └── sso.py          # SSO 适配器（OIDC/LDAP/企微/钉钉）
│   │   └── workers/
│   │       └── parse_worker.py # Celery 任务（调用 MinerU，全参数支持）
│   ├── Dockerfile              # API 服务镜像
│   ├── Dockerfile.worker       # Worker 镜像（CPU，含 MinerU）
│   └── Dockerfile.worker.gpu   # Worker 镜像（GPU，CUDA + MinerU）
│
├── frontend/                   # Next.js 14 前端
│   └── src/
│       ├── app/
│       │   ├── login/page.tsx  # 登录页（本地 + SSO 按钮）
│       │   └── dashboard/
│       │       ├── page.tsx    # 主控制台
│       │       └── tasks/[taskId]/page.tsx  # 任务详情 + 在线预览
│       ├── components/
│       │   ├── upload/         # 文件拖拽上传（全格式 + 高级解析选项）
│       │   └── tasks/          # 任务列表（WebSocket 实时进度）
│       └── lib/
│           ├── api.ts          # API 客户端（axios + 自动刷新 token + 批量 API）
│           └── auth-store.ts   # 认证状态管理（Zustand）
│
├── docker/
│   └── nginx.conf              # Nginx 反向代理配置
├── docker-compose.yml          # 完整编排文件
├── .env.example                # 配置模板
└── scripts/start.sh            # 一键启动脚本
```

---

## API 概览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/login` | 本地登录 |
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/refresh` | 刷新 Token |
| GET | `/api/v1/auth/sso/{provider}/authorize` | SSO 授权跳转 |
| POST | `/api/v1/auth/sso/callback` | SSO 回调 |

### 文件上传 & 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/tasks/upload-url` | 获取单个预签名上传 URL |
| POST | `/api/v1/tasks/` | 创建解析任务 |
| GET | `/api/v1/tasks/` | 任务列表 |
| GET | `/api/v1/tasks/{id}` | 任务详情 |
| GET | `/api/v1/tasks/{id}/results` | 获取下载链接 |
| GET | `/api/v1/tasks/{id}/preview` | **在线预览内容** |
| DELETE | `/api/v1/tasks/{id}` | 取消任务 |
| POST | `/api/v1/tasks/batch/upload-urls` | **批量预签名 URL（≤100）** |
| POST | `/api/v1/tasks/batch/tasks` | **批量创建任务（≤100）** |

### MinerU 官方兼容 API

输入格式与官方 FastAPI 对齐：PDF、图片（PNG / JPEG / JP2 / WebP / GIF / BMP / JPG / TIFF）、DOCX、PPTX、XLSX。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/file_parse` | 同步解析，表单参数对齐官方 MinerU FastAPI |
| POST | `/tasks` | 异步提交解析任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |
| GET | `/tasks/{task_id}/result` | 获取任务结果 |

### 任务创建参数

```json
{
  "s3_key": "uploads/xxx/file.pdf",
  "original_filename": "report.pdf",
  "file_size_bytes": 5242880,
  "backend": "pipeline",         // pipeline | vlm | MinerU-HTML
  "output_format": "markdown",    // markdown | json | both | docx | html | latex
  "language": "ch",               // ch | en | japan | korean | latin | arabic | ...
  "is_ocr": null,                 // null=自动, true=强制, false=关闭
  "enable_formula": true,
  "enable_table": true,
  "page_ranges": "1-10"           // 可选，如 "2,4-6"
}
```

---

## SSO 配置

### OIDC（Keycloak / Azure AD / Okta）

```env
OIDC_ENABLED=true
OIDC_ISSUER=https://keycloak.example.com/realms/company
OIDC_CLIENT_ID=mineru-enterprise
OIDC_CLIENT_SECRET=your-secret
```

### LDAP / Active Directory

```env
LDAP_ENABLED=true
LDAP_SERVER=ldap://ldap.example.com:389
LDAP_BIND_DN=cn=admin,dc=example,dc=com
LDAP_BIND_PASSWORD=password
LDAP_BASE_DN=dc=example,dc=com
```

### 企业微信

```env
WECHAT_WORK_ENABLED=true
WECHAT_WORK_CORP_ID=ww_xxx
WECHAT_WORK_AGENT_ID=1000001
WECHAT_WORK_SECRET=your-secret
```

### 钉钉

```env
DINGTALK_ENABLED=true
DINGTALK_APP_KEY=your-app-key
DINGTALK_APP_SECRET=your-app-secret
```

---

## S3 存储配置

### MinIO（自托管，推荐内网）

```env
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_BUCKET_NAME=mineru-enterprise
```

### AWS S3

```env
# S3_ENDPOINT_URL 留空
S3_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
S3_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG
S3_REGION_NAME=ap-southeast-1
```

### 阿里云 OSS

```env
S3_ENDPOINT_URL=https://oss-cn-hangzhou.aliyuncs.com
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
S3_REGION_NAME=cn-hangzhou
```

---

## 环境要求

- Docker 24+，Docker Compose v2+
- GPU 支持（可选）：NVIDIA Docker runtime（`nvidia-container-toolkit`）
- 内存：>= 8 GB（CPU 模式），>= 16 GB（GPU 模式）

---

## License

MIT
