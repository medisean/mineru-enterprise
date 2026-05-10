#!/usr/bin/env bash
# ─── Quick start script ────────────────────────────────────────────────────────
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🚀 MinerU Enterprise — 启动脚本${NC}"

if [ ! -f ".env" ]; then
  echo -e "${YELLOW}⚠  未找到 .env，正在从 .env.example 复制...${NC}"
  cp .env.example .env
  echo -e "${YELLOW}   请编辑 .env 填入实际配置后再运行${NC}"
  exit 1
fi

MODE=${1:-dev}

case $MODE in
  dev)
    echo "启动开发模式（含 MinIO）..."
    docker compose --profile minio up -d
    echo -e "${GREEN}✅ 服务已启动${NC}"
    echo "  前端:      http://localhost:3000"
    echo "  API:       http://localhost:8000/api/docs"
    echo "  MinIO:     http://localhost:9001"
    ;;
  prod)
    echo "启动生产模式（GPU only + Nginx）..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile gpu up -d
    echo -e "${GREEN}✅ 服务已启动（生产模式 — GPU only）${NC}"
    echo "  Nginx:     http://localhost:80"
    echo "  API:       http://localhost:8000/api/docs"
    echo "  GPU Worker: 已启用（CPU Worker 已禁用）"
    ;;
  gpu)
    echo "启动 GPU 模式（需要 nvidia-container-toolkit）..."
    docker compose --profile minio --profile gpu up -d
    echo -e "${GREEN}✅ 服务已启动（GPU 加速）${NC}"
    echo "  前端:      http://localhost:3000"
    echo "  API:       http://localhost:8000/api/docs"
    echo "  MinIO:     http://localhost:9001"
    echo "  GPU Worker: 已启用 (MINERU_DEVICE=cuda)"
    ;;
  monitor)
    echo "启动监控模式（含 Flower）..."
    docker compose --profile minio --profile monitoring up -d
    echo "  Flower:    http://localhost:5555"
    ;;
  down)
    docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile minio --profile monitoring --profile production --profile gpu down
    ;;
  *)
    echo "用法: ./scripts/start.sh [dev|prod|gpu|monitor|down]"
    ;;
esac
