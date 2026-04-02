import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  // 构建到 ../static/（相对于 frontend/）
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
});
