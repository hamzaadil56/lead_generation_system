import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The compose image copies `.next/standalone` and runs `node server.js`.
  // Without this the runtime stage has no server to start.
  output: "standalone",
};

export default nextConfig;
