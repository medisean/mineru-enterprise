/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME || "MinerU Enterprise",
    NEXT_PUBLIC_OIDC_ENABLED: process.env.NEXT_PUBLIC_OIDC_ENABLED || "false",
    NEXT_PUBLIC_OAUTH2_ENABLED: process.env.NEXT_PUBLIC_OAUTH2_ENABLED || "false",
    NEXT_PUBLIC_WECHAT_WORK_ENABLED: process.env.NEXT_PUBLIC_WECHAT_WORK_ENABLED || "false",
    NEXT_PUBLIC_DINGTALK_ENABLED: process.env.NEXT_PUBLIC_DINGTALK_ENABLED || "false",
  },
  images: {
    domains: ["localhost"],
  },
  // Fix: pdfjs-dist@5.x ESM + webpack __webpack_require__.r incompatibility
  // causes "Object.defineProperty called on non-object" in dev mode.
  // transpilePackages forces SWC to re-compile pdfjs-dist ESM correctly.
  transpilePackages: ["pdfjs-dist", "react-pdf"],
  webpack: (config, { dev, isServer }) => {
    // Prevent canvas native module from being bundled (server-side only)
    if (isServer) {
      config.resolve.alias.canvas = false;
    }

    if (dev && !isServer) {
      // Next.js 14 forces eval-source-map in dev and silently reverts any override.
      // The eval environment breaks pdfjs-dist's ESM module initialization
      // (__webpack_require__.r calls Object.defineProperty on a non-object).
      // Use Object.defineProperty getter to prevent Next.js from reverting our devtool.
      // Ref: https://github.com/vercel/next.js/discussions/21425
      Object.defineProperty(config, "devtool", {
        get() {
          return "cheap-module-source-map";
        },
        set() {
          // no-op: prevent Next.js from reverting to eval-source-map
        },
      });
    }

    return config;
  },
};

export default nextConfig;
