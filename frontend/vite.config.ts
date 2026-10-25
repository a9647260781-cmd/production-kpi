import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const runtimeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const devPort = Number(runtimeEnv.KPD_E2E_PORT ?? "5173");
const apiTarget = runtimeEnv.KPD_E2E_API_TARGET ?? "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: devPort,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
});

