import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, ".") } },
  // globals: true lets @testing-library/react's own `afterEach(cleanup)`
  // auto-register (it checks `typeof afterEach === "function"`). It's a
  // no-op for files that never call render(), so the node-environment
  // tests in lib/__tests__/ are unaffected.
  test: { environment: "node", globals: true, setupFiles: ["./vitest.setup.ts"] },
});
