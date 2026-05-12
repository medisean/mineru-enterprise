#!/bin/sh
set -eu

node <<'NODE'
const fs = require("fs");

const config = {
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "",
  NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME || "MinerU Enterprise",
  NEXT_PUBLIC_OIDC_ENABLED: process.env.NEXT_PUBLIC_OIDC_ENABLED || "false",
  NEXT_PUBLIC_OAUTH2_ENABLED: process.env.NEXT_PUBLIC_OAUTH2_ENABLED || "false",
  NEXT_PUBLIC_WECHAT_WORK_ENABLED: process.env.NEXT_PUBLIC_WECHAT_WORK_ENABLED || "false",
  NEXT_PUBLIC_DINGTALK_ENABLED: process.env.NEXT_PUBLIC_DINGTALK_ENABLED || "false",
};

fs.writeFileSync(
  "/app/public/runtime-config.js",
  `window.__MINERU_RUNTIME_CONFIG__ = ${JSON.stringify(config)};\n`,
  "utf8"
);
NODE

exec "$@"

