import type { NextConfig } from "next";

/**
 * `npm run build` writes to `.next-build`, not `.next`.
 *
 * A production build and a running dev server share `.next` by default, and the
 * build rewrites the chunk files the dev server is still serving from memory.
 * The dev server then asks for a chunk id that no longer exists and the page
 * dies with `Cannot find module './960.js'`. Separating the directories means a
 * build can run at any time — including in CI or a parallel terminal — without
 * taking the running dev server down.
 */
const isProductionBuild = process.env.NEXT_BUILD_TARGET === "production";

const config: NextConfig = {
  reactStrictMode: true,
  distDir: isProductionBuild ? ".next-build" : ".next",
  env: {
    NEXT_PUBLIC_API_BASE:
      process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8010/api/v1",
  },
};

export default config;
