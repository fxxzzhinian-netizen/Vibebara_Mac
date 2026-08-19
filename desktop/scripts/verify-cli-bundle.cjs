"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const args = process.argv.slice(2);
const requireSignature = args.includes("--require-signature");
const outputArg = args.find((arg) => !arg.startsWith("--"));
const defaultRoot =
  process.platform === "darwin"
    ? path.join(__dirname, "..", "release-mac", "mac-arm64", "Vibebara.app")
    : path.join(__dirname, "..", "release", "win-unpacked");
const packageRoot = path.resolve(outputArg || defaultRoot);
const resourceDir = packageRoot.endsWith(".app")
  ? path.join(packageRoot, "Contents", "Resources")
  : path.join(packageRoot, "resources");
const cliDir = path.join(resourceDir, "cli");
const executableName = process.platform === "win32" ? "vibebara.exe" : "vibebara";
const executable = path.join(cliDir, executableName);
const pathHelper = path.join(
  cliDir,
  process.platform === "win32" ? "update-cli-path.ps1" : "install-cli.sh",
);

function fail(message) {
  throw new Error(`[desktop-cli] ${message}`);
}

function run(command, commandArgs, env = process.env) {
  const result = spawnSync(command, commandArgs, {
    encoding: "utf8",
    windowsHide: true,
    env,
  });
  if (result.error || result.status !== 0) {
    fail(
      `${path.basename(command)} ${commandArgs.join(" ")} 失败\n` +
        `${result.error?.message || ""}\n${result.stdout || ""}${result.stderr || ""}`,
    );
  }
  return `${result.stdout || ""}${result.stderr || ""}`;
}

if (!fs.existsSync(executable)) fail(`安装包缺少 ${executable}`);
if (!fs.existsSync(pathHelper)) fail(`安装包缺少 ${pathHelper}`);
if (process.platform !== "win32") {
  fs.chmodSync(executable, 0o755);
  fs.chmodSync(pathHelper, 0o755);
}

const restrictedEnv =
  process.platform === "win32"
    ? {
        ...process.env,
        PATH: path.join(process.env.SystemRoot || "C:\\Windows", "System32"),
      }
    : { ...process.env, PATH: "/usr/bin:/bin:/usr/sbin:/sbin" };
if (!run(executable, ["--version"], restrictedEnv).includes("0.1.0")) {
  fail("打包后的独立 CLI 版本输出异常");
}
if (!run(executable, ["--help"], restrictedEnv).includes("Usage: vibebara")) {
  fail("打包后的独立 CLI help 输出异常");
}

if (requireSignature && process.platform === "win32") {
  const escaped = executable.replace(/'/g, "''");
  const signature = run("powershell.exe", [
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    `$s=Get-AuthenticodeSignature -LiteralPath '${escaped}'; ` +
      "Write-Output $s.Status; if ($s.Status -ne 'Valid') { exit 1 }",
  ]);
  if (!signature.includes("Valid")) fail("CLI Authenticode 签名无效");
}
if (requireSignature && process.platform === "darwin") {
  run("codesign", ["--verify", "--strict", "--verbose=2", executable]);
}

console.log(`[desktop-cli] bundled CLI verified: ${executable}`);
