import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

/** Where `npm run dev` should forward /api. */
const BACKEND = process.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8003"

/** The DAQ look's parts (neon_ui), source-aliased like lilak_ui. */
const NEON = new URL("../../neon_ui/src", import.meta.url).pathname
// neon.css takes its font files from the portal kit.
const FONTS = new URL("../../lilak_ui/src/fonts", import.meta.url).pathname

export default defineConfig({
  // Relative asset URLs. Behind the portal this app is served under `/p/<name>/`
  // and the proxy injects a `<base href>` -- which only steers RELATIVE urls, so
  // vite's default "/assets/index-*.js" would resolve against the portal root and
  // 404. Served directly, "./" resolves the same as before.
  base: "./",
  plugins: [react()],
  resolve: {
    alias: { "@neon": NEON, "@": new URL("./src", import.meta.url).pathname },
    // neon_ui's files would otherwise find React, Mantine and uPlot in its own
    // node_modules: a second React breaks every hook.
    dedupe: ["react", "react-dom", "@mantine/core", "@mantine/hooks", "@mantine/notifications", "uplot"],
  },
  server: {
    host: true,
    fs: { allow: [".", NEON, FONTS] },
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    // Served by the FastAPI app from backend/../frontend/dist.
    outDir: "dist",
    sourcemap: true,
  },
})
