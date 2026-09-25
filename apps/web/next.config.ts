import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    resolveAlias: { "pino-pretty": { browser: "./src/lib/empty.ts" }, lokijs: { browser: "./src/lib/empty.ts" }, encoding: { browser: "./src/lib/empty.ts" } },
  },
};

export default nextConfig;
