import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// API paths served by FastAPI. `npm run dev` forwards them to the server on port 8000.
const API = ["/upload", "/documents", "/ask", "/answer", "/session", "/stats", "/health"];

// The build goes straight into app/static, which FastAPI serves: the server (and Render) needs
// no Node.js, only these built files.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../app/static", emptyOutDir: true },
  server: { proxy: Object.fromEntries(API.map((path) => [path, "http://127.0.0.1:8000"])) },
});
