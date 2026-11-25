import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Same editable components as Sites; this target runs on any static web server.
const releaseId = process.env.EASYREP_BUILD_ID?.replace(/[^a-zA-Z0-9_-]/g, "") || "local";

export default defineConfig({
  root: fileURLToPath(new URL("./standalone", import.meta.url)),
  publicDir: fileURLToPath(new URL("./public", import.meta.url)),
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  build: {
    outDir: fileURLToPath(new URL("./dist-static", import.meta.url)),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      output: {
        entryFileNames: `assets/[name]-[hash]-${releaseId}.js`,
        chunkFileNames: `assets/[name]-[hash]-${releaseId}.js`,
        assetFileNames: asset => asset.name?.endsWith(".css")
          ? `assets/[name]-[hash]-${releaseId}[extname]`
          : "assets/[name]-[hash][extname]",
      },
      input: {
        app: fileURLToPath(new URL("./standalone/index.html", import.meta.url)),
        demo: fileURLToPath(new URL("./standalone/demo.html", import.meta.url)),
        materials: fileURLToPath(new URL("./standalone/materials.html", import.meta.url)),
      },
    },
  },
});
