import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 분석 API(FastAPI, :8000)로 프록시한다. 분석은 LLM 호출 때문에 수십 초가 걸릴 수 있다.
    proxy: { "/api": { target: "http://localhost:8000", timeout: 300_000, proxyTimeout: 300_000 } },
  },
});
