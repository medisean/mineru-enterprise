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
    echo "启动生产模式（含 Nginx）..."
    docker compose --profile production up -d
    ;;
  gpu)
    echo "启动 GPU 模式..."
    docker compose --profile minio up -d
    # Uncomment GPU deploy config in docker-compose.yml first
    ;;
  monitor)
    echo "启动监控模式（含 Flower）..."
    docker compose --profile minio --profile monitoring up -d
    echo "  Flower:    http://localhost:5555"
    ;;
  down)
    docker compose --profile minio --profile monitoring --profile production down
    ;;
  *)
    echo "用法: ./scripts/start.sh [dev|prod|gpu|monitor|down]"
    ;;
esac
