import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AgentConfig } from "../src/config";
import { createContext, type AgentContext } from "../src/context";
import { AgentError } from "../src/errors";
import { handleBrowse } from "../src/handlers/browse";

/**
 * browse 目录浏览测试 —— 过滤规则与 backend browse_directory 对齐。
 */

let tmp: string;
let ctx: AgentContext;

beforeEach(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "la-browse-")));
  const config: AgentConfig = {
    port: 0,
    pairingToken: "t",
    paired: true,
    writableRoots: [],
    maxBodyBytes: 1024,
  };
  ctx = createContext(config);
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe("handleBrowse", () => {
  it("过滤普通隐藏/噪声目录，但保留受支持 IDE 的点号目录", () => {
    for (const d of [
      "alpha",
      "beta",
      ".cursor",
      ".codex",
      ".hidden",
      "node_modules",
      "__pycache__",
      ".git",
      "dist",
      "build",
    ]) {
      fs.mkdirSync(path.join(tmp, d));
    }
    fs.writeFileSync(path.join(tmp, "afile.txt"), "x"); // 非目录

    const res = handleBrowse(tmp, ctx);
    expect(res.ok).toBe(true);
    const names = res.dirs.map((d) => d.name).sort();
    expect(names).toEqual([".codex", ".cursor", "alpha", "beta"]);
    expect(res.dirs.every((d) => d.isDrive === false)).toBe(true);
    expect(res.current).toBe(tmp);
    expect(res.parent).toBe(path.dirname(tmp));
  });

  it("【任务③】浏览目录不再登记可写根（纯只读浏览，消除看一眼就扩大白名单）", () => {
    const child = path.join(tmp, "proj");
    fs.mkdirSync(child);
    handleBrowse(tmp, ctx);
    // browse 后既不授权 current 也不授权子目录——授权改由 write-skill 的 deployPath 绑定。
    expect(ctx.writableRoots.isAllowed(path.join(tmp, "x"))).toBe(false);
    expect(ctx.writableRoots.isAllowed(path.join(child, "y"))).toBe(false);
  });

  it("路径不存在 → PATH_NOT_FOUND", () => {
    try {
      handleBrowse(path.join(tmp, "nope"), ctx);
      throw new Error("应抛错");
    } catch (err) {
      expect(err).toBeInstanceOf(AgentError);
      expect((err as AgentError).code).toBe("PATH_NOT_FOUND");
    }
  });

  it("目标是文件 → NOT_A_DIRECTORY", () => {
    const f = path.join(tmp, "file.txt");
    fs.writeFileSync(f, "x");
    try {
      handleBrowse(f, ctx);
      throw new Error("应抛错");
    } catch (err) {
      expect(err).toBeInstanceOf(AgentError);
      expect((err as AgentError).code).toBe("NOT_A_DIRECTORY");
    }
  });
});
