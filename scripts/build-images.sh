#!/usr/bin/env bash
# Build one or more service images.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-mineru-enterprise}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PLATFORM="${PLATFORM:-}"
PUSH="${PUSH:-false}"
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-python:3.11-slim}"
NODE_BASE_IMAGE="${NODE_BASE_IMAGE:-node:20-alpine}"
CUDA_BASE_IMAGE="${CUDA_BASE_IMAGE:-nvidia/cuda:12.4.1-runtime-ubuntu22.04}"
NGINX_BASE_IMAGE="${NGINX_BASE_IMAGE:-nginx:1.27-alpine}"
APT_MIRROR="${APT_MIRROR:-}"
ALPINE_MIRROR="${ALPINE_MIRROR:-}"
PIP_INDEX_URL="${PIP_INDEX_URL:-}"
PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-}"
NPM_REGISTRY="${NPM_REGISTRY:-}"
TORCH_VERSION="${TORCH_VERSION:-2.7.0}"
CUDA_VERSION="${CUDA_VERSION:-cu124}"
NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
NEXT_PUBLIC_APP_NAME="${NEXT_PUBLIC_APP_NAME:-MinerU Enterprise}"

usage() {
  cat <<EOF
Usage:
  $0 [api|web|worker|worker-gpu|nginx|cpu|all]

Environment:
  IMAGE_REPOSITORY    Image repository/prefix. Default: mineru-enterprise
  IMAGE_TAG           Image tag. Default: latest
  PLATFORM            Optional docker platform, e.g. linux/amd64
  PUSH                Push after build when true. Default: false
  PYTHON_BASE_IMAGE   Python base image for api/worker.
  NODE_BASE_IMAGE     Node base image for web.
  CUDA_BASE_IMAGE     CUDA base image for GPU worker.
  NGINX_BASE_IMAGE    Nginx base image.
  APT_MIRROR          Debian/Ubuntu apt mirror, e.g. https://mirrors.aliyun.com/debian
  ALPINE_MIRROR       Alpine apk mirror, e.g. https://mirrors.aliyun.com/alpine
  PIP_INDEX_URL       Python package index mirror.
  PIP_EXTRA_INDEX_URL Extra Python package index.
  PYTORCH_INDEX_URL   PyTorch wheel index. Defaults per worker type.
  NPM_REGISTRY        npm registry mirror.
  TORCH_VERSION       Worker PyTorch version. Default: 2.7.0
  CUDA_VERSION        GPU worker CUDA wheel suffix. Default: cu124
  NEXT_PUBLIC_API_URL Frontend build-time API URL.
  NEXT_PUBLIC_APP_NAME Frontend build-time app name.

Examples:
  IMAGE_TAG=v1.0.0 $0 api
  IMAGE_REPOSITORY=registry.example.com/mineru IMAGE_TAG=v1.0.0 $0 all
  PUSH=true IMAGE_REPOSITORY=registry.example.com/mineru IMAGE_TAG=v1.0.0 $0 web
EOF
}

docker_cmd() {
  local args=(docker build)
  if [[ -n "$PLATFORM" ]]; then
    args+=(--platform "$PLATFORM")
  fi
  "${args[@]}" "$@"
}

push_image() {
  local image="$1"
  if [[ "$PUSH" == "true" || "$PUSH" == "1" || "$PUSH" == "yes" ]]; then
    docker push "$image"
  fi
}

check_mineru_model_bundle() {
  if [[ ! -d "$ROOT_DIR/backend/mineru-models" ]]; then
    echo "ERROR: backend/mineru-models/ is required for worker image builds." >&2
    echo "Place your pre-downloaded MinerU model files there before building worker images." >&2
    exit 1
  fi
  if ! find "$ROOT_DIR/backend/mineru-models" -mindepth 1 \
    ! -name ".gitkeep" ! -name "README.md" | grep -q .; then
    echo "ERROR: backend/mineru-models/ does not contain model files." >&2
    echo "Only placeholder files were found. Copy the real MinerU model files into this directory." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT_DIR/backend/mineru.json" ]]; then
    echo "ERROR: backend/mineru.json is required for worker image builds." >&2
    echo "It will be copied to /root/mineru.json inside the worker image." >&2
    exit 1
  fi
}

build_api() {
  local image="${IMAGE_REPOSITORY}/api:${IMAGE_TAG}"
  docker_cmd \
    --build-arg "PYTHON_BASE_IMAGE=${PYTHON_BASE_IMAGE}" \
    --build-arg "APT_MIRROR=${APT_MIRROR}" \
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
    --build-arg "PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}" \
    -t "$image" \
    -f "$ROOT_DIR/backend/Dockerfile" \
    "$ROOT_DIR/backend"
  push_image "$image"
}

build_web() {
  local image="${IMAGE_REPOSITORY}/web:${IMAGE_TAG}"
  docker_cmd \
    --build-arg "NODE_BASE_IMAGE=${NODE_BASE_IMAGE}" \
    --build-arg "ALPINE_MIRROR=${ALPINE_MIRROR}" \
    --build-arg "NPM_REGISTRY=${NPM_REGISTRY}" \
    --build-arg "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}" \
    --build-arg "NEXT_PUBLIC_APP_NAME=${NEXT_PUBLIC_APP_NAME}" \
    -t "$image" \
    -f "$ROOT_DIR/frontend/Dockerfile" \
    "$ROOT_DIR/frontend"
  push_image "$image"
}

build_worker() {
  local image="${IMAGE_REPOSITORY}/worker:${IMAGE_TAG}"
  local pytorch_index="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
  docker_cmd \
    --build-arg "PYTHON_BASE_IMAGE=${PYTHON_BASE_IMAGE}" \
    --build-arg "APT_MIRROR=${APT_MIRROR}" \
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
    --build-arg "PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}" \
    --build-arg "PYTORCH_INDEX_URL=${pytorch_index}" \
    --build-arg "TORCH_VERSION=${TORCH_VERSION}" \
    -t "$image" \
    -f "$ROOT_DIR/backend/Dockerfile.worker" \
    "$ROOT_DIR/backend"
  push_image "$image"
}

build_worker_gpu() {
  local image="${IMAGE_REPOSITORY}/worker-gpu:${IMAGE_TAG}"
  local pytorch_index="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/${CUDA_VERSION}}"
  check_mineru_model_bundle
  docker_cmd \
    --build-arg "CUDA_BASE_IMAGE=${CUDA_BASE_IMAGE}" \
    --build-arg "APT_MIRROR=${APT_MIRROR}" \
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
    --build-arg "PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}" \
    --build-arg "PYTORCH_INDEX_URL=${pytorch_index}" \
    --build-arg "TORCH_VERSION=${TORCH_VERSION}" \
    --build-arg "CUDA_VERSION=${CUDA_VERSION}" \
    -t "$image" \
    -f "$ROOT_DIR/backend/Dockerfile.worker.gpu" \
    "$ROOT_DIR/backend"
  push_image "$image"
}

build_nginx() {
  local image="${IMAGE_REPOSITORY}/nginx:${IMAGE_TAG}"
  docker_cmd \
    --build-arg "NGINX_BASE_IMAGE=${NGINX_BASE_IMAGE}" \
    --build-arg "ALPINE_MIRROR=${ALPINE_MIRROR}" \
    -t "$image" \
    -f "$ROOT_DIR/docker/Dockerfile.nginx" \
    "$ROOT_DIR/docker"
  push_image "$image"
}

target="${1:-all}"
case "$target" in
  api) build_api ;;
  web) build_web ;;
  worker) build_worker ;;
  worker-gpu) build_worker_gpu ;;
  nginx) build_nginx ;;
  cpu)
    build_api
    build_web
    build_worker
    build_nginx
    ;;
  all)
    build_api
    build_web
    build_worker
    build_worker_gpu
    build_nginx
    ;;
  *)
    usage
    exit 1
    ;;
esac
