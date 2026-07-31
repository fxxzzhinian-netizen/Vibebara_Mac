"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { build } = require("esbuild");
const { inject } = require("postject");

const SEA_FUSE = "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2";
const root = path.resolve(__dirname, "..");
const coreEntry = path.resolve(root, "..", "local-core", "dist", "index.js");
const releaseDir = path.join(root, "release");
const buildDir = path.join(releaseDir, ".sea-build");
const bundlePath = path.join(releaseDir, "vibebara.cjs");
const blobPath = path.join(buildDir, "vibebara.blob");
const configPath = path.join(buildDir, "sea-config.json");
const executablePath = path.join(releaseDir, "vibebara.exe");
const bundleOnly = process.argv.includes("--bundle-only");

function fail(message) {
  throw new Error(`[cli-sea] ${message}`);
}

function assertNodeVersion() {
  const [major, minor] = process.versions.node
    .split(".")
    .slice(0, 2)
    .map(Number);
  if (major < 22 || (major === 22 && minor < 12)) {
    fail(`需要 Node.js >=22.12.0，当前为 ${process.versions.node}`);
  }
}

function runSmoke(command, args) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
    env: process.env,
  });
  if (result.error) {
    fail(`${path.basename(command)} ${args.join(" ")} 启动失败: ${result.error.message}`);
  }
  if (result.status !== 0) {
    fail(
      `${path.basename(command)} ${args.join(" ")} 退出码 ${result.status}\n` +
        `${result.stdout || ""}${result.stderr || ""}`,
    );
  }
}

async function main() {
  assertNodeVersion();
  if (!fs.existsSync(coreEntry)) {
    fail("缺少 local-core/dist/index.js；请先在 local-core 执行 npm run build");
  }
  if (!bundleOnly && process.platform !== "win32") {
    fail("Windows SEA 必须在 Windows 发布机上生成；其他平台请使用 --bundle-only");
  }

  fs.mkdirSync(releaseDir, { recursive: true });
  fs.rmSync(buildDir, { recursive: true, force: true });
  fs.mkdirSync(buildDir, { recursive: true });

  await build({
    entryPoints: [path.join(root, "src", "program.ts")],
    outfile: bundlePath,
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node22",
    sourcemap: false,
    minify: false,
    footer: { js: "void module.exports.run();" },
  });
  runSmoke(process.execPath, [bundlePath, "--version"]);
  runSmoke(process.execPath, [bundlePath, "--help"]);
  console.log(`[cli-sea] CJS bundle ready: ${bundlePath}`);

  if (bundleOnly) {
    fs.rmSync(buildDir, { recursive: true, force: true });
    return;
  }

  fs.writeFileSync(
    configPath,
    JSON.stringify(
      {
        main: bundlePath,
        output: blobPath,
        disableExperimentalSEAWarning: true,
        useSnapshot: false,
        useCodeCache: false,
      },
      null,
      2,
    ),
  );

  const blob = spawnSync(
    process.execPath,
    ["--experimental-sea-config", configPath],
    { encoding: "utf8", windowsHide: true },
  );
  if (blob.error || blob.status !== 0 || !fs.existsSync(blobPath)) {
    fail(
      `SEA blob 生成失败\n${blob.error?.message || ""}\n` +
        `${blob.stdout || ""}${blob.stderr || ""}`,
    );
  }

  fs.copyFileSync(process.execPath, executablePath);
  await inject(executablePath, "NODE_SEA_BLOB", fs.readFileSync(blobPath), {
    sentinelFuse: SEA_FUSE,
  });

  runSmoke(executablePath, ["--version"]);
  runSmoke(executablePath, ["--help"]);
  fs.rmSync(bundlePath, { force: true });
  fs.rmSync(buildDir, { recursive: true, force: true });
  console.log(
    `[cli-sea] Windows executable ready: ${executablePath} ` +
      `(${Math.ceil(fs.statSync(executablePath).size / 1024 / 1024)} MiB)`,
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
