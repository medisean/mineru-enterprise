export function normalizeTaskBackend(backend?: string | null): string {
  const value = (backend ?? "").trim();
  return value || "auto";
}

export function getTaskBackendLabel(
  backend: string | null | undefined,
  t: (key: string) => string
): string {
  switch (normalizeTaskBackend(backend)) {
    case "auto":
      return t("upload.engineAuto");
    case "pipeline":
      return t("upload.enginePipeline");
    case "hybrid-auto-engine":
    case "hybrid-http-client":
      return t("upload.engineHybrid");
    case "vlm":
    case "vlm-auto-engine":
    case "vlm-http-client":
      return t("upload.engineVlm");
    default:
      return (backend ?? "").trim() || "auto";
  }
}
