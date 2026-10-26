import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const runtimeProcess = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> };
  }
).process;
const apiProxyTarget =
  runtimeProcess?.env?.VITE_API_PROXY_TARGET ?? "http://localhost:8000";
const apiProxy = {
  "/api": apiProxyTarget,
  "/health": apiProxyTarget,
};

function vendorChunk(id: string): string | undefined {
  if (!id.includes("node_modules")) return undefined;
  if (/\/(react|react-dom|scheduler)\//.test(id)) return "vendor-react";
  if (id.includes("/@tanstack/react-query/")) return "vendor-query";
  if (id.includes("/oidc-client-ts/")) return "vendor-oidc";
  return undefined;
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    proxy: apiProxy,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: vendorChunk,
      },
    },
  },
});

