import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { isInside, safeJoinUnder, WritableRoots } from "../src/security";
import { isAllowedOrigin } from "../src/server";

/**
 * 可写根白名单 + 路径逃逸防护测试（M0 §5.3 / §5.4）。
 */

let tmp: string;

beforeEach(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "la-sec-")));
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe("WritableRoots.isAllowed", () => {
  it("根内路径放行，根外路径拒绝", () => {
    const root = path.join(tmp, "project");
    fs.mkdirSync(root, { recursive: true });
    const roots = new WritableRoots([root]);

    expect(roots.isAllowed(path.join(root, ".cursor", "skills", "s1"))).toBe(true);
    expect(roots.isAllowed(root)).toBe(true);
    expect(roots.isAllowed(path.join(tmp, "other", "x"))).toBe(false);
  });

  it("`..` 逃逸在 realResolve 后被拒绝", () => {
    const root = path.join(tmp, "project");
    fs.mkdirSync(root, { recursive: true });
    const roots = new WritableRoots([root]);

    // project/../secret 解析到 tmp/secret，不在白名单
    const escape = path.join(root, "..", "secret", "evil");
    expect(roots.isAllowed(escape)).toBe(false);
  });

  it("未登记任何根 → 全部拒绝", () => {
    const roots = new WritableRoots([]);
    expect(roots.isAllowed(path.join(tmp, "anything"))).toBe(false);
  });

  it("运行期 register 后放行（任务③：模拟 write-skill 登记确认选定的 deployPath）", () => {
    const roots = new WritableRoots([]);
    const dir = path.join(tmp, "picked");
    fs.mkdirSync(dir, { recursive: true });
    expect(roots.isAllowed(path.join(dir, "x"))).toBe(false);
    roots.register(dir);
    expect(roots.isAllowed(path.join(dir, "x"))).toBe(true);
  });
});

describe("isInside", () => {
  it("自身/子路径 true，外部 false", () => {
    expect(isInside("/a/b/c", "/a/b")).toBe(true);
    expect(isInside("/a/b", "/a/b")).toBe(true);
    expect(isInside("/a/x", "/a/b")).toBe(false);
    expect(isInside("/a/bc", "/a/b")).toBe(false); // 前缀但非子目录
  });
});

describe("safeJoinUnder", () => {
  const install = path.join(path.sep, "install", "root");

  it("正常相对 POSIX 路径拼接到 install 根下", () => {
    expect(safeJoinUnder(install, "assets/icon.png")).toBe(
      path.join(install, "assets", "icon.png"),
    );
    expect(safeJoinUnder(install, "SKILL.md")).toBe(
      path.join(install, "SKILL.md"),
    );
  });

  it("含 `..` 的相对路径抛错", () => {
    expect(() => safeJoinUnder(install, "../evil")).toThrow();
    expect(() => safeJoinUnder(install, "a/../../evil")).toThrow();
  });

  it("绝对路径 / 盘符路径抛错", () => {
    expect(() => safeJoinUnder(install, "/etc/passwd")).toThrow();
    expect(() => safeJoinUnder(install, "C:\\Windows\\x")).toThrow();
  });
});

describe("isAllowedOrigin", () => {
  it("仅放行正式桌面渲染层的 vibebara://app origin", () => {
    expect(isAllowedOrigin("vibebara://app")).toBe(true);
    expect(isAllowedOrigin("vibebara://evil")).toBe(false);
  });
});
