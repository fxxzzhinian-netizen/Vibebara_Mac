import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { computeDirHash, hashPath } from "../src/hash";

/**
 * hash 一致性测试 —— 核心验收点：本地代理 hash 与云端 §7 规范**位级一致**。
 *
 * 三重保障：
 *  1. 与 M0 §7.3 冻结伪代码的**独立内联参考实现**一致（不复用生产代码）。
 *  2. 与**云端 Python 实现实测 hex 一致**（CLOUD_PARITY_HEX 由 backend 参考算法在
 *     同一目录树上实测，见 M3 实施记录"hash 一致性验证"）。
 *  3. 边界：空目录/不存在 → ""；不同根路径下同内容 hash 稳定；分隔符排序陷阱
 *     （ref/z vs refA.md 按 POSIX 字节序）。
 */

// 与 backend/tests/test_hash_convergence._build_tree 等价的确定性目录树在 Python
// 参考算法下的实测 hash（已交叉校验 TS == PY）。
const CLOUD_PARITY_HEX =
  "37b702e386cff1ded780b07b2c679aabdfadf83a93e2d5fbc8dc931268cf394a";

let tmp: string;

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "la-hash-"));
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

/** 构造覆盖边界场景的目录树（与 backend _build_tree 字节一致）。 */
function buildTree(base: string): void {
  fs.mkdirSync(base, { recursive: true });
  fs.writeFileSync(path.join(base, "SKILL.md"), "---\nname: demo\n---\nbody\n");
  fs.writeFileSync(path.join(base, "refA.md"), "refA-content");
  fs.mkdirSync(path.join(base, "ref"), { recursive: true });
  fs.writeFileSync(path.join(base, "ref", "z"), "z-content");
  fs.mkdirSync(path.join(base, "资料"), { recursive: true });
  fs.writeFileSync(path.join(base, "资料", "说明.md"), "中文内容\n");
  fs.writeFileSync(path.join(base, "Aa.txt"), "Aa");
  fs.writeFileSync(path.join(base, "aB.txt"), "aB");
  fs.mkdirSync(path.join(base, "assets"), { recursive: true });
  const block = Buffer.from(Array.from({ length: 256 }, (_, i) => i));
  fs.writeFileSync(
    path.join(base, "assets", "icon.png"),
    Buffer.concat([block, block, block, block]),
  );
}

/** M0 §7.3 冻结伪代码的独立参考实现（不复用 src/hash.ts）。 */
function referenceHash(root: string): string {
  if (!fs.existsSync(root)) return "";
  const files: { rel: string; abs: string }[] = [];
  const recurse = (dir: string): void => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const abs = path.join(dir, e.name);
      if (e.isDirectory()) recurse(abs);
      else if (e.isFile())
        files.push({ rel: path.relative(root, abs).split(path.sep).join("/"), abs });
    }
  };
  const st = fs.statSync(root);
  if (!st.isDirectory()) return "";
  recurse(root);
  if (files.length === 0) return "";
  files.sort((a, b) =>
    Buffer.compare(Buffer.from(a.rel, "utf8"), Buffer.from(b.rel, "utf8")),
  );
  const h = createHash("sha256");
  for (const f of files) {
    h.update(Buffer.from(f.rel, "utf8"));
    h.update(Buffer.from([0]));
    h.update(fs.readFileSync(f.abs));
    h.update(Buffer.from([0]));
  }
  return h.digest("hex");
}

describe("computeDirHash", () => {
  it("与 M0 §7.3 冻结伪代码独立参考实现一致", () => {
    const root = path.join(tmp, "skill");
    buildTree(root);
    expect(computeDirHash(root)).toBe(referenceHash(root));
    expect(computeDirHash(root)).toHaveLength(64);
  });

  it("与云端 Python 实现实测 hex 位级一致（cloud parity）", () => {
    const root = path.join(tmp, "skill");
    buildTree(root);
    expect(computeDirHash(root)).toBe(CLOUD_PARITY_HEX);
  });

  it("空目录 → ''，不存在路径 → ''", () => {
    const empty = path.join(tmp, "empty");
    fs.mkdirSync(empty);
    expect(computeDirHash(empty)).toBe("");
    expect(computeDirHash(path.join(tmp, "nope"))).toBe("");
  });

  it("同内容在不同根路径下 hash 稳定（去平台/分隔符相关性）", () => {
    const r1 = path.join(tmp, "a", "deep", "skill");
    const r2 = path.join(tmp, "x", "skill");
    buildTree(r1);
    buildTree(r2);
    expect(computeDirHash(r1)).toBe(computeDirHash(r2));
  });

  it("分隔符排序陷阱：ref/z 与 refA.md 按 POSIX 字节序", () => {
    const root = path.join(tmp, "edge");
    fs.mkdirSync(root, { recursive: true });
    fs.writeFileSync(path.join(root, "refA.md"), "A");
    fs.mkdirSync(path.join(root, "ref"));
    fs.writeFileSync(path.join(root, "ref", "z"), "Z");
    expect(computeDirHash(root)).toBe(referenceHash(root));
  });
});

describe("hashPath", () => {
  it("exists 反映真实存在性，与 hash 是否为空解耦", () => {
    const empty = path.join(tmp, "empty");
    fs.mkdirSync(empty);
    expect(hashPath(empty)).toEqual({ hash: "", exists: true });
    expect(hashPath(path.join(tmp, "nope"))).toEqual({ hash: "", exists: false });
  });
});
