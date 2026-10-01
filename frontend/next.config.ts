import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (deploy/), no node_modules needed at runtime.
  output: "standalone",
};

export default nextConfig;
