#!/usr/bin/env node
/**
 * Runs `next` with NEXT_BUILD_TARGET=production set, cross-platform.
 *
 * `FOO=bar next build` is shell syntax that Windows cmd does not understand, and
 * pulling in `cross-env` for one variable is a dependency the project does not
 * need. Six lines of Node does the same job everywhere.
 *
 *   node scripts/next.mjs build
 *   node scripts/next.mjs start -p 3000
 */
import { spawn } from "node:child_process";

const args = process.argv.slice(2);
const next = spawn("next", args, {
  stdio: "inherit",
  shell: true,
  env: { ...process.env, NEXT_BUILD_TARGET: "production" },
});

next.on("exit", (code) => process.exit(code ?? 0));
