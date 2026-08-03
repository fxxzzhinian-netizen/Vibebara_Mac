"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const args = process.argv.slice(2);
const requireSignature = args.includes("--require-signature");
const outputArg = args.find((arg) => !arg.startsWith("--"));
const unpackedDir = path.resolve(
  outputArg || path.join(__dirname, "..", "release", "win-unpacked"),
);
const cliDir = path.join(unpackedDir, "resources", "cli");
const executable = path.join(cliDir, "vibebara.exe");
const pathHelper = path.join(cliDir, "update-cli-path.ps1");

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

const restrictedEnv = {
  ...process.env,
  PATH: path.join(process.env.SystemRoot || "C:\\Windows", "System32"),
};
if (!run(executable, ["--version"], restrictedEnv).includes("0.1.0")) {
  fail("打包后的独立 CLI 版本输出异常");
}
if (!run(executable, ["--help"], restrictedEnv).includes("Usage: vibebara")) {
  fail("打包后的独立 CLI help 输出异常");
}

if (requireSignature) {
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

console.log(`[desktop-cli] bundled CLI verified: ${executable}`);
