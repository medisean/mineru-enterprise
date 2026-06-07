#!/usr/bin/env sh
set -eu

loglevel="${CELERY_LOGLEVEL:-info}"
concurrency="${GPU_WORKER_CONCURRENCY:-1}"

case "$concurrency" in
  ''|*[!0-9]*|0)
    echo "GPU_WORKER_CONCURRENCY must be a positive integer, got: ${concurrency}" >&2
    exit 1
    ;;
esac

gpu_ids_from_var() {
  value="$1"
  if [ -z "$value" ] || [ "$value" = "all" ]; then
    return 0
  fi
  printf '%s' "$value" | tr ',' '\n' | sed '/^[[:space:]]*$/d'
}

normalize_gpu_ids() {
  printf '%s\n' "$1" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | sed '/^$/d'
}

detect_gpu_ids() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null || true
    return 0
  fi
  gpu_ids_from_var "${CUDA_VISIBLE_DEVICES:-}"
  gpu_ids_from_var "${NVIDIA_VISIBLE_DEVICES:-}"
}

start_worker_for_gpu() {
  gpu_id="$1"
  echo "Starting GPU worker for GPU ${gpu_id} with concurrency=${concurrency}"
  CUDA_VISIBLE_DEVICES="$gpu_id" celery \
    -A app.workers.parse_worker.celery_app \
    worker \
    -Q parse_gpu \
    -c "$concurrency" \
    -n "gpu-${gpu_id}@%h" \
    --loglevel="$loglevel" &
}

if [ -n "${GPU_WORKER_DEVICES:-}" ]; then
  gpu_ids="$(normalize_gpu_ids "$GPU_WORKER_DEVICES")"
elif [ -n "${CUDA_VISIBLE_DEVICES:-}" ] && [ "$CUDA_VISIBLE_DEVICES" != "all" ]; then
  gpu_ids="$(normalize_gpu_ids "$CUDA_VISIBLE_DEVICES")"
elif [ -n "${NVIDIA_VISIBLE_DEVICES:-}" ] && [ "$NVIDIA_VISIBLE_DEVICES" != "all" ]; then
  gpu_ids="$(normalize_gpu_ids "$NVIDIA_VISIBLE_DEVICES")"
else
  gpu_ids="$(detect_gpu_ids | sed '/^[[:space:]]*$/d')"
fi

if [ -z "$gpu_ids" ]; then
  gpu_ids="0"
fi

worker_pids=""
for gpu_id in $gpu_ids; do
  start_worker_for_gpu "$gpu_id"
  worker_pids="$worker_pids $!"
done

trap 'kill $worker_pids 2>/dev/null || true; wait $worker_pids 2>/dev/null || true' INT TERM
wait $worker_pids
