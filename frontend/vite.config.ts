/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Конфиг исполняется в Node, но типы Node в проект не подключены — описываем
// ровно то, что используем, вместо лишней зависимости.
declare const process: { env: Record<string, string | undefined> };

// Адрес бэкенда для сервера разработки. По умолчанию — стандартный порт
// uvicorn; если он занят на машине разработчика, задать ORBITLINK_API.
const apiTarget = process.env.ORBITLINK_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
