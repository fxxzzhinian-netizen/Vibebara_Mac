"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const distEntry = path.join(root, "dist", "index.js");
const bundleEntry = path.join(root, "release", "vibebara.cjs");
const executable = path.join(root, "release", "vibebara.exe");

function assert(condition, message) {
  if (!condition) throw new Error(`[cli-distribution] ${message}`);
}

function run(command, args, env = process.env) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
    env,
  });
  assert(!result.error, `${path.basename(command)} 无法启动: ${result.error?.message}`);
  assert(
    result.status === 0,
    `${path.basename(command)} ${args.join(" ")} 退出码 ${result.status}\n` +
      `${result.stdout || ""}${result.stderr || ""}`,
  );
  return `${result.stdout || ""}${result.stderr || ""}`;
}

assert(fs.existsSync(distEntry), "缺少 dist/index.js；请先运行 npm run build");
const hasBundle = fs.existsSync(bundleEntry);
const hasExecutable = fs.existsSync(executable);
assert(hasBundle || hasExecutable, "缺少 bundle/SEA 分发产物");

assert(run(process.execPath, [distEntry, "--version"]).includes("0.1.0"), "npm bin 版本异常");
if (hasBundle) {
  assert(run(process.execPath, [bundleEntry, "--help"]).includes("Usage: vibebara"), "CJS bundle help 异常");
}

if (process.platform === "win32") {
  assert(hasExecutable, "Windows 缺少 release/vibebara.exe");
  const restrictedEnv = {
    ...process.env,
    PATH: path.join(process.env.SystemRoot || "C:\\Windows", "System32"),
  };
  assert(
    run(executable, ["--version"], restrictedEnv).includes("0.1.0"),
    "SEA 在无 Node PATH 环境下无法执行",
  );
}

console.log("[cli-distribution] npm bin and bundle/standalone executable verified");
