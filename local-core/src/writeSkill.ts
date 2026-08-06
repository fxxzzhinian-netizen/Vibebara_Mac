import fs from "node:fs";
import path from "node:path";
import { LocalCoreError } from "./errors";
import { writeContent } from "./fileio";
import { ensureGitignore } from "./gitignore";
import { computeDirHash } from "./hash";
import { platformSkillsDir } from "./platform";
import { ensureVibebaraGuide } from "./projectGuide";
import { isInside, safeJoinUnder, WritableRoots } from "./security";
import type { ToolType, WriteSkillOptions, WriteSkillResult } from "./types";

const SUPPORTED_TOOLS = new Set<ToolType>([
  "cursor",
  "codex",
  "windsurf",
  "claude",
  "kiro",
  "trae",
  "qoder",
  "workbuddy",
]);

export interface WriteSkillRuntime {
  writableRoots?: WritableRoots;
}

function safeTarget(installPath: string, relativePath: string): string {
  try {
    const target = safeJoinUnder(installPath, relativePath);
    if (!isInside(target, installPath)) {
      throw new Error(`写入路径逃逸: ${relativePath}`);
    }
    return target;
  } catch (error) {
    throw new LocalCoreError("BAD_REQUEST", (error as Error).message);
  }
}

export function writeSkill(
  input: WriteSkillOptions,
  runtime: WriteSkillRuntime = {},
): WriteSkillResult {
  if (!SUPPORTED_TOOLS.has(input?.tool)) {
    throw new LocalCoreError("UNSUPPORTED_TOOL", `不支持的 tool: ${input?.tool}`);
  }
  if (input.scope !== "project" && input.scope !== "platform") {
    throw new LocalCoreError("BAD_REQUEST", "scope 必须为 project 或 platform");
  }
  const skillId = input.skillId;
  if (!skillId?.trim()) {
    throw new LocalCoreError("BAD_REQUEST", "缺少 skillId");
  }
  if (skillId.includes("/") || skillId.includes("\\") || skillId.includes("..")) {
    throw new LocalCoreError("BAD_REQUEST", `非法 skillId: ${skillId}`);
  }
  if (
    typeof input.contents !== "object" ||
    input.contents === null ||
    Array.isArray(input.contents)
  ) {
    throw new LocalCoreError("BAD_REQUEST", "contents 必须为对象");
  }
  if (!Array.isArray(input.resources)) {
    throw new LocalCoreError("BAD_REQUEST", "resources 必须为数组");
  }

  const writableRoots = runtime.writableRoots ?? new WritableRoots();
  let installRoot: string;
  if (input.scope === "project") {
    const deployPath = input.deployPath;
    if (!deployPath?.trim()) {
      throw new LocalCoreError(
        "BAD_REQUEST",
        "scope=project 时 deployPath 必填",
      );
    }
    let stat: fs.Stats;
    try {
      stat = fs.statSync(deployPath);
    } catch {
      throw new LocalCoreError(
        "WRITE_ROOT_FORBIDDEN",
        "deployPath 不是已确认的有效目标目录（不存在）",
        `deployPath=${deployPath}`,
      );
    }
    if (!stat.isDirectory()) {
      throw new LocalCoreError(
        "NOT_A_DIRECTORY",
        `deployPath 不是目录: ${deployPath}`,
      );
    }
    writableRoots.register(deployPath);
    installRoot = path.join(deployPath, `.${input.tool}`, "skills");
  } else {
    installRoot = platformSkillsDir(input.tool);
    writableRoots.register(installRoot);
  }

  const installPath = path.join(installRoot, skillId);
  if (!writableRoots.isAllowed(installPath)) {
    throw new LocalCoreError(
      "WRITE_ROOT_FORBIDDEN",
      "目标路径不在可写根白名单内",
      `installPath=${installPath}`,
    );
  }

  const exists = fs.existsSync(installPath);
  if (exists && !input.overwrite) {
    throw new LocalCoreError(
      "INSTALL_EXISTS",
      `install 目录已存在: ${installPath}`,
    );
  }

  const written: string[] = [];
  try {
    if (exists) fs.rmSync(installPath, { recursive: true, force: true });
    fs.mkdirSync(installPath, { recursive: true });

    for (const [relativePath, text] of Object.entries(input.contents)) {
      writeContent(
        safeTarget(installPath, relativePath),
        "utf8",
        typeof text === "string" ? text : String(text),
      );
      written.push(relativePath);
    }

    for (const resource of input.resources) {
      if (!resource || typeof resource.path !== "string") {
        throw new LocalCoreError("BAD_REQUEST", "resource 缺少 path");
      }
      if (resource.transfer === "url") {
        throw new LocalCoreError(
          "BAD_REQUEST",
          `transfer="url" 暂未实现（仅支持 inline）: ${resource.path}`,
        );
      }
      writeContent(
        safeTarget(installPath, resource.path),
        resource.encoding === "base64" ? "base64" : "utf8",
        resource.content ?? "",
      );
      written.push(resource.path);
    }

    if (input.scope === "project" && input.ensureGitignore && input.deployPath) {
      ensureGitignore(input.deployPath);
      ensureVibebaraGuide(input.deployPath);
    }
  } catch (error) {
    if (error instanceof LocalCoreError) throw error;
    throw new LocalCoreError(
      "IO_ERROR",
      `落盘失败: ${(error as Error).message}`,
    );
  }

  return {
    installPath,
    written,
    installedHash: computeDirHash(installPath),
  };
}
