# MinerU Enterprise — 打包部署 & API 调用指南

---

## 一、项目打包

### 1.1 镜像清单

| 镜像 | Dockerfile | 基础镜像 | 说明 |
|---|---|---|---|
| `mineru-enterprise/api` | `backend/Dockerfile` | `python:3.11-slim` | FastAPI 服务，含 LDAP 等系统依赖 |
| `mineru-enterprise/worker` | `backend/Dockerfile.worker` | `python:3.11-slim` | Celery CPU Worker，内置 PyTorch CPU + MinerU 模型 |
| `mineru-enterprise/worker-gpu` | `backend/Dockerfile.worker.gpu` | `nvidia/cuda:12.4.1-runtime-ubuntu22.04` | Celery GPU Worker，PyTorch CUDA 12.4 + MinerU 模型 |
| `mineru-enterprise/web` | `frontend/Dockerfile` | `node:20-alpine` | Next.js 14 前端，多阶段构建 standalone 输出 |
| `mineru-enterprise/nginx` | `docker/Dockerfile.nginx` | `nginx:1.27-alpine` | 反向代理，含 WebSocket 支持 |

### 1.2 构建命令

```bash
# 进入项目根目录
cd /path/to/mineru-web

# 构建单个镜像
./scripts/build-images.sh api
./scripts/build-images.sh web
./scripts/build-images.sh worker        # 需要 backend/mineru-models/ 和 backend/mineru.json
./scripts/build-images.sh worker-gpu    # 同上
./scripts/build-images.sh nginx

# 构建 CPU 全套（api + web + worker + nginx）
./scripts/build-images.sh cpu

# 构建全部（含 GPU worker）
./scripts/build-images.sh all
```

### 1.3 构建环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `IMAGE_REPOSITORY` | `mineru-enterprise` | 镜像仓库前缀 |
| `IMAGE_TAG` | `latest` | 镜像标签 |
| `PLATFORM` | (空) | 跨平台构建，如 `linux/amd64` |
| `PUSH` | `false` | 构建后推送 |
| `PYTHON_BASE_IMAGE` | `python:3.11-slim` | Python 基础镜像 |
| `NODE_BASE_IMAGE` | `node:20-alpine` | Node 基础镜像 |
| `CUDA_BASE_IMAGE` | `nvidia/cuda:12.4.1-runtime-ubuntu22.04` | CUDA 基础镜像 |
| `TORCH_VERSION` | `2.7.0` | PyTorch 版本 |
| `CUDA_VERSION` | `cu124` | CUDA wheel 后缀 |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | 前端构建时 API 地址 |
| `NEXT_PUBLIC_APP_NAME` | `MinerU Enterprise` | 前端构建时应用名 |
| `APT_MIRROR` | (空) | Debian apt 镜像 |
| `PIP_INDEX_URL` | (空) | pip 镜像 |
| `NPM_REGISTRY` | (空) | npm 镜像 |

**示例：带镜像加速 + 打标签 + 推送**

```bash
IMAGE_REPOSITORY=registry.example.com/mineru \
IMAGE_TAG=v1.2.0 \
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
NPM_REGISTRY=https://registry.npmmirror.com \
PUSH=true \
./scripts/build-images.sh all
```

### 1.4 Worker 镜像前置条件

构建 `worker` / `worker-gpu` 前，必须准备：

1. **`backend/mineru-models/`** — MinerU 模型文件目录（非空，不能只有 README.md）
2. **`backend/mineru.json`** — MinerU 模型配置文件（会被 COPY 到 `/root/mineru.json`）

缺少时会直接报错退出。

### 1.5 部署启动

```bash
# 首次运行需要 .env
cp .env.example .env
# 编辑 .env 填入实际配置（至少改 SECRET_KEY）

# 开发模式（含本地 MinIO）
./scripts/start.sh dev

# GPU 加速模式（需 nvidia-container-toolkit）
./scripts/start.sh gpu

# 生产模式（GPU only + Nginx 反代）
./scripts/start.sh prod

# 含 Flower 监控
./scripts/start.sh monitor

# 停止所有服务
./scripts/start.sh down
```

或直接 docker compose：

```bash
# 开发
docker compose --profile minio up -d

# 生产
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 1.6 服务端口

| 服务 | 端口 | 访问 |
|---|---|---|
| 前端 (web) | 3000 | `http://localhost:3000` |
| API | 8000 | `http://localhost:8000/api/docs` (DEBUG=true 时) |
| MinIO API | 9000 | `http://localhost:9000` |
| MinIO Console | 9001 | `http://localhost:9001` |
| Nginx (生产) | 80/443 | `http://localhost` |
| Flower (监控) | 5555 | `http://localhost:5555` |

---

## 二、API 调用

### 2.1 认证方式

所有企业 API（`/api/v1/*`）需要 JWT 认证，在请求头携带：

```
Authorization: Bearer <access_token>
```

获取 token 方式：
1. **本地登录** `POST /api/v1/auth/login`
2. **SSO 登录** `GET /api/v1/auth/sso/{provider}/authorize` → 回调
3. **刷新** `POST /api/v1/auth/refresh`

MinerU 官方 API（`/tasks`、`/file_parse`）**不需要**认证。
Agent API（`/api/v1/agent/*`）**不需要**认证，但有 IP 限速（30次/分钟）。
Precision API（`/api/v4/*`）**需要**认证。

---

### 2.2 企业 API（`/api/v1`）

#### 2.2.1 认证 — `/api/v1/auth`

**登录**
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "yourpassword"}'
```
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**注册**
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "username": "newuser",
    "password": "SecurePass1",
    "full_name": "New User"
  }'
```

**刷新 Token**
```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJ..."}'
```

**SSO 授权（OIDC/企微/钉钉）**
```bash
# 获取授权跳转 URL
curl http://localhost:8000/api/v1/auth/sso/oidc/authorize
# 返回 {"authorize_url": "https://keycloak.example.com/..."}

# SSO 回调
curl -X POST http://localhost:8000/api/v1/auth/sso/callback \
  -H "Content-Type: application/json" \
  -d '{"code": "xxx", "state": "xxx", "provider": "oidc"}'
```

---

#### 2.2.2 任务 — `/api/v1/tasks`

核心流程：**获取上传 URL → 直传 S3 → 创建任务 → 轮询/WebSocket → 获取结果**

**Step 1: 获取预签名上传 URL**
```bash
curl -X POST http://localhost:8000/api/v1/tasks/upload-url \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "report.pdf",
    "content_type": "application/pdf",
    "file_size_bytes": 1048576
  }'
```
```json
{
  "upload_url": "https://minio:9000/mineru-enterprise/uploads/...?X-Amz-...",
  "s3_key": "uploads/<user_id>/<uuid>/report.pdf",
  "expires_in": 3600
}
```

**Step 2: 直传文件到 S3**
```bash
curl -X PUT "<upload_url>" \
  -H "Content-Type: application/pdf" \
  --data-binary @report.pdf
```

**Step 3: 创建解析任务**
```bash
curl -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "s3_key": "uploads/<user_id>/<uuid>/report.pdf",
    "original_filename": "report.pdf",
    "file_size_bytes": 1048576,
    "backend": "",
    "language": "ch",
    "enable_formula": true,
    "enable_table": true,
    "data_id": "my-doc-001",
    "callback_url": "https://your-server.com/webhook",
    "callback_seed": "your-hmac-seed"
  }'
```
```json
{
  "id": "task-uuid",
  "original_filename": "report.pdf",
  "status": "pending",
  "progress": 0,
  ...
}
```

**Step 4: 查询任务状态**
```bash
curl http://localhost:8000/api/v1/tasks/<task_id> \
  -H "Authorization: Bearer <token>"
```

**Step 5: 获取结果**
```bash
curl http://localhost:8000/api/v1/tasks/<task_id>/results \
  -H "Authorization: Bearer <token>"
```
```json
{
  "task_id": "task-uuid",
  "status": "success",
  "files": [
    {"filename": "report.md", "s3_key": "...", "download_url": "https://...", "size": 12345},
    {"filename": "report.json", "s3_key": "...", "download_url": "https://...", "size": 67890}
  ]
}
```

**预览 Markdown 内容**
```bash
curl "http://localhost:8000/api/v1/tasks/<task_id>/preview?format=markdown" \
  -H "Authorization: Bearer <token>"
```

**批量上传 URL**
```bash
curl -X POST http://localhost:8000/api/v1/tasks/batch/upload-urls \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      {"filename": "a.pdf", "content_type": "application/pdf", "file_size_bytes": 100000},
      {"filename": "b.docx", "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "file_size_bytes": 200000}
    ]
  }'
```

**批量创建任务**
```bash
curl -X POST http://localhost:8000/api/v1/tasks/batch/tasks \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "tasks": [
      {"s3_key": "...", "original_filename": "a.pdf", "file_size_bytes": 100000},
      {"s3_key": "...", "original_filename": "b.docx", "file_size_bytes": 200000}
    ]
  }'
```

**其他端点**

| 操作 | 方法 | 路径 |
|---|---|---|
| 任务列表 | GET | `/api/v1/tasks/?page=1&page_size=20&status=success&keyword=report` |
| 源文件预览 URL | GET | `/api/v1/tasks/<task_id>/source-url` |
| 重试失败任务 | POST | `/api/v1/tasks/<task_id>/retry` |
| 删除/取消任务 | DELETE | `/api/v1/tasks/<task_id>` |
| 批量下载 ZIP | POST | `/api/v1/tasks/batch/download` (body: `{"task_ids": [...]}`) |

**WebSocket 实时进度**
```javascript
const ws = new WebSocket(
  'ws://localhost:8000/api/v1/ws/tasks/<task_id>?token=<access_token>'
);
ws.onmessage = (e) => console.log(JSON.parse(e.data));
// 每 2 秒推送: {"task_id": "...", "status": "processing", "progress": 45}
```

---

#### 2.2.3 用户 — `/api/v1/users`

```bash
# 获取当前用户
curl http://localhost:8000/api/v1/users/me -H "Authorization: Bearer <token>"

# 更新资料
curl -X PATCH http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"full_name": "New Name", "avatar_url": "https://..."}'
```

---

#### 2.2.4 管理后台 — `/api/v1/admin`

所有管理端点需要 `admin` 角色用户。

```bash
# 仪表盘统计
curl http://localhost:8000/api/v1/admin/stats -H "Authorization: Bearer <admin_token>"

# 用户列表
curl "http://localhost:8000/api/v1/admin/users?page=1&page_size=20&role=member&search=john" \
  -H "Authorization: Bearer <admin_token>"

# 更新用户角色/状态
curl -X PATCH http://localhost:8000/api/v1/admin/users/<user_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin", "is_active": true}'

# 删除用户
curl -X DELETE http://localhost:8000/api/v1/admin/users/<user_id> \
  -H "Authorization: Bearer <admin_token>"

# 全局任务列表
curl "http://localhost:8000/api/v1/admin/tasks?page=1&page_size=20&status=failed" \
  -H "Authorization: Bearer <admin_token>"
```

---

### 2.3 MinerU 官方兼容 API

兼容开源 MinerU FastAPI 格式，**不需要认证**。

**异步提交**
```bash
curl -X POST http://localhost:8000/tasks \
  -F "file=@report.pdf"
```
```json
{"id": "task-uuid", "status": "pending"}
```

**查询状态**
```bash
curl http://localhost:8000/tasks/<task_id>
```
```json
{"id": "task-uuid", "status": "processing", "progress": 50}
```

**获取结果**
```bash
curl http://localhost:8000/tasks/<task_id>/result
```

**同步解析（阻塞等待，最长 3600s）**
```bash
curl -X POST http://localhost:8000/file_parse \
  -F "file=@report.pdf"
```

---

### 2.4 MinerU Precision API v4（`/api/v4`）

兼容 MinerU 官方云 API 格式，**需要 Bearer 认证**。

**单文件 URL 解析**
```bash
curl -X POST http://localhost:8000/api/v4/extract/task \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/doc.pdf",
    "language": "ch",
    "enable_formula": true,
    "enable_table": true,
    "data_id": "doc-001",
    "callback": "https://your-server.com/webhook",
    "seed": "hmac-seed"
  }'
```
```json
{"code": 0, "msg": "ok", "data": {"task_id": "task-uuid"}}
```

**查询解析结果**
```bash
curl http://localhost:8000/api/v4/extract/task/<task_id> \
  -H "Authorization: Bearer <token>"
```
```json
{
  "code": 0,
  "data": {
    "task_id": "task-uuid",
    "state": "done",
    "full_zip_url": "https://s3.../results.zip",
    "extract_progress": {"extracted_pages": 10, "total_pages": 10}
  }
}
```

**批量获取上传 URL**
```bash
curl -X POST http://localhost:8000/api/v4/file-urls/batch \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      {"name": "a.pdf"},
      {"name": "b.docx", "data_id": "doc-b"}
    ],
    "language": "ch",
    "callback": "https://your-server.com/webhook",
    "seed": "hmac-seed"
  }'
```
```json
{"code": 0, "data": {"batch_id": "batch-uuid", "file_urls": ["https://presigned-url-1", "https://presigned-url-2"]}}
```

**批量 URL 解析**
```bash
curl -X POST http://localhost:8000/api/v4/extract/task/batch \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [{"url": "https://example.com/a.pdf"}, {"url": "https://example.com/b.docx"}],
    "language": "ch"
  }'
```

**批量结果查询**
```bash
curl http://localhost:8000/api/v4/extract-results/batch/<batch_id> \
  -H "Authorization: Bearer <token>"
```

---

### 2.5 Agent API（`/api/v1/agent`）

轻量级解析接口，**无需认证**，IP 限速 30次/分钟。

**URL 解析**
```bash
curl -X POST http://localhost:8000/api/v1/agent/parse/url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/doc.pdf", "language": "ch"}'
```

**文件上传解析**
```bash
# Step 1: 获取上传信息
curl -X POST http://localhost:8000/api/v1/agent/parse/file \
  -H "Content-Type: application/json" \
  -d '{"file_name": "report.pdf"}'
# 返回: {"task_id": "...", "file_url": "https://presigned-upload-url"}

# Step 2: 上传文件
curl -X PUT "<file_url>" -H "Content-Type: application/pdf" --data-binary @report.pdf

# Step 3: 查询结果
curl http://localhost:8000/api/v1/agent/parse/<task_id>
```

---

### 2.6 CreateTaskRequest 字段说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `s3_key` | string | ✅ | — | 上传后返回的 S3 key |
| `original_filename` | string | ✅ | — | 原始文件名 |
| `file_size_bytes` | int | ✅ | — | 文件大小（字节） |
| `backend` | string | ❌ | `""` | 解析引擎：`pipeline` / `hybrid-auto-engine` / `vlm-auto-engine` / 空=默认 |
| `output_format` | string | ❌ | `"markdown"` | 输出格式：`markdown` / `json` / `both` / `docx` / `html` / `latex` |
| `language` | string | ❌ | `""` | 文档语言：空=自动检测 / `ch` / `en` / `japan` / `korean` 等 |
| `is_ocr` | bool/null | ❌ | `null` | OCR：`null`=自动检测 / `true`=强制 / `false`=禁用 |
| `enable_formula` | bool | ❌ | `true` | 启用公式识别 |
| `enable_table` | bool | ❌ | `true` | 启用表格识别 |
| `page_ranges` | string | ❌ | `null` | 页码范围：`"1-10"` / `"2,4-6"` |
| `data_id` | string | ❌ | `null` | 业务自定义 ID，≤128 字符 |
| `parse_options` | dict | ❌ | `null` | 额外 MinerU CLI 选项（白名单校验） |
| `callback_url` | string | ❌ | `null` | Webhook 回调 URL |
| `callback_seed` | string | ❌ | `null` | Webhook HMAC 签名种子 |

---

### 2.7 支持的文件格式

`.pdf`, `.png`, `.jpeg`, `.jpg`, `.jp2`, `.webp`, `.gif`, `.bmp`, `.tiff`, `.docx`, `.pptx`, `.xlsx`

---

### 2.8 健康检查

```bash
curl http://localhost:8000/health
# {"status": "ok", "version": "1.0.0"}
```

---

## 三、核心数据流

```
浏览器 → POST /upload-url → 获取 S3 预签名 URL
浏览器 → PUT 预签名 URL → 直传文件到 S3
浏览器 → POST /tasks/ → 创建解析任务
API → dispatch_parse_task() → 投递到 Celery 队列（parse_cpu / parse_gpu）
Worker → 下载源文件 → MinerU CLI 解析 → 上传结果到 S3 → 更新 DB
浏览器 ← WebSocket / GET /tasks/{id} ← 实时进度 + 结果
浏览器 → GET /tasks/{id}/results → 下载解析结果文件
```

---

## 四、Webhook 回调

任务创建时可指定 `callback_url` + `callback_seed`，任务完成/失败时 Worker 会 POST 回调：

```
POST <callback_url>
Headers:
  X-MinerU-Signature: hmac-sha256 签名
  Content-Type: application/json
Body:
  {"task_id": "...", "status": "success|failed", "data_id": "...", ...}
```

验证签名：
```python
import hmac, hashlib
signature = hmac.new(seed.encode(), body.encode(), hashlib.sha256).hexdigest()
```
