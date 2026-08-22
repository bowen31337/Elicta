import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

const host = process.env.TAURI_DEV_HOST;

// Where the service tier is listening, for the proxy below. `start.sh` sets
// it; under `tauri dev` it is unset and the proxy simply goes unused.
const serviceUrl = process.env.ELICTA_SERVICE_URL || "http://127.0.0.1:8000";

// Serving the panel in a browser puts the page on a different origin from the
// service, and two parts of the UI ask for `/api/...` relative to the page
// (the session stream and the debrief chat) while the generated client uses an
// absolute base URL. Proxying the prefix makes the whole app same-origin, so
// both styles resolve and the service needs no CORS headers. Declared for the
// preview server too, so the production bundle can be exercised the same way.
const apiProxy = {
  "/api": {
    target: serviceUrl,
    changeOrigin: true,
  },
};

// Serving over TLS, when `start.sh --https` has generated a certificate and
// pointed us at it. This is not about eavesdropping on a LAN: browsers hand
// out `navigator.mediaDevices` only in a *secure context*, so on a plain-HTTP
// address that is not `localhost` the microphone API is not merely blocked,
// it is absent — there is nothing to grant. A self-signed certificate is
// enough to make the context secure, which is what the capture screen needs.
const certFile = process.env.ELICTA_HTTPS_CERT;
const keyFile = process.env.ELICTA_HTTPS_KEY;
const https =
  certFile && keyFile
    ? { cert: readFileSync(certFile), key: readFileSync(keyFile) }
    : undefined;

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  // The version shown in About comes from the package manifest at build time,
  // so it cannot drift from what was actually shipped.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },

  // Tauri expects a fixed port, fails if that port is not available.
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    proxy: apiProxy,
    https,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  preview: {
    proxy: apiProxy,
    https,
  },
});
