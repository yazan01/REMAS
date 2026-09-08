import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_BASE:
      process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8010/api/v1",
  },
};

export default config;
