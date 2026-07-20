import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 프록시는 쓰지 않는다 — CORS는 백엔드 CORSMiddleware가 담당(AGENT_GUIDE §3 블록).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
