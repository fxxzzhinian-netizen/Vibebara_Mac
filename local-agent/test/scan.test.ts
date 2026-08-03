import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { scanAndPackage } from "../src/scan/scan";
import { detectOrigin } from "../src/scan/detect";

/**
 * scan 来源识别移植测试（R1）—— 验证 detectOrigin 评分与 scanAndPackage 归一化输出
 * 与云端 bridge scan-and-package 口径一致。
 */

let tmp: string;

beforeEach(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "la-scan-")));
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

function mkSkill(name: string, files: Record<string, string>): string {
  const dir = path.join(tmp, name);
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return dir;
}

describe("detectOrigin", () => {
  it("cursor：frontmatter 含 disable-model-invocation → cursor/high", () => {
    const dir = mkSkill("cur", {
      "SKILL.md": "---\nname: cur\ndescription: d\ndisable-model-invocation: true\n---\nbody\n",
    });
    const r = detectOrigin(dir);
    expect(r.origin).toBe("cursor");
    expect(r.confidence).toBe("high");
    expect(r.signals).toContain("frontmatter has disable-model-invocation");
  });

  it("codex：存在 agents/openai.yaml → codex/high", () => {
    const dir = mkSkill("cdx", {
      "SKILL.md": "---\nname: cdx\ndescription: d\n---\nbody\n",
      "agents/openai.yaml": "interface:\n  display_name: Codex Skill\n",
    });
    const r = detectOrigin(dir);
    expect(r.origin).toBe("codex");
    expect(r.confidence).toBe("high");
    expect(r.signals).toContain("agents/openai.yaml present");
  });

  it("无信号 → unknown/low", () => {
    const dir = mkSkill("unk", {
      "SKILL.md": "---\nname: unk\ndescription: d\n---\nplain body without markers\n",
    });
    const r = detectOrigin(dir);
    expect(r.origin).toBe("unknown");
    expect(r.confidence).toBe("low");
  });
});

describe("scanAndPackage", () => {
  it("只收含 SKILL.md 的一级子目录，跳过无 SKILL.md / 点开头目录", () => {
    mkSkill("cursor-skill", {
      "SKILL.md": "---\nname: cursor-skill\ndescription: Cursor one\ndisable-model-invocation: false\n---\nbody\n",
      "scripts/run.py": "print(1)",
    });
    mkSkill("codex-skill", {
      "SKILL.md": "---\nname: codex-skill\ndescription: Codex one\n---\nbody\n",
      "agents/openai.yaml": "interface:\n  display_name: Codex One\n  short_description: short\n",
      "assets/icon.png": "binary-ish",
    });
    // 无 SKILL.md → 跳过
    mkSkill("not-a-skill", { "README.md": "nope" });
    // 点开头 → 跳过
    mkSkill(".hidden-skill", { "SKILL.md": "---\nname: h\n---\n" });

    const pkgs = scanAndPackage(tmp);
    const byId = Object.fromEntries(pkgs.map((p) => [p.id, p]));
    expect(Object.keys(byId).sort()).toEqual(["codex-skill", "cursor-skill"]);

    const cursor = byId["cursor-skill"]!;
    expect(cursor.origin).toBe("cursor");
    expect(cursor.name).toBe("cursor-skill");
    expect(cursor.description).toBe("Cursor one");
    expect(cursor.hasScripts).toBe(true);
    expect(cursor.hasAssets).toBe(false);
    // cursor 导入不含 displayName
    expect(cursor.displayName).toBe("");

    const codex = byId["codex-skill"]!;
    expect(codex.origin).toBe("codex");
    expect(codex.displayName).toBe("Codex One");
    expect(codex.shortDescription).toBe("short");
    expect(codex.hasAssets).toBe(true);
    expect(codex.hasScripts).toBe(false);
    // installedAt 形状存在
    expect(codex.installedAt).toHaveProperty("cursor");
    expect(codex.installedAt).toHaveProperty("codex");
    expect(codex.installedAt).toHaveProperty("windsurf");
  });

  it("rootDir 自身含 SKILL.md（用户直接选中 skill 文件夹）→ 收 rootDir 本身", () => {
    const dir = mkSkill("bare-skill", {
      "SKILL.md": "---\nname: bare-skill\ndescription: Bare one\n---\nbody\n",
    });
    const pkgs = scanAndPackage(dir);
    expect(pkgs.map((p) => p.id)).toEqual(["bare-skill"]);
    expect(pkgs[0]!.name).toBe("bare-skill");
    expect(pkgs[0]!.description).toBe("Bare one");
    expect(pkgs[0]!.sourcePath).toBe(dir);
  });

  it("rootDir 自身含 SKILL.md 且一级子目录也含 SKILL.md → 两者并收", () => {
    const root = mkSkill("mixed-skill", {
      "SKILL.md": "---\nname: mixed-skill\ndescription: Root one\n---\nbody\n",
    });
    // 子目录也是一个独立 skill
    const childMd = path.join(root, "child-skill", "SKILL.md");
    fs.mkdirSync(path.dirname(childMd), { recursive: true });
    fs.writeFileSync(
      childMd,
      "---\nname: child-skill\ndescription: Child one\n---\nbody\n",
    );

    const pkgs = scanAndPackage(root);
    expect(pkgs.map((p) => p.id).sort()).toEqual(["child-skill", "mixed-skill"]);
  });

  it("项目根目录下的 .cursor/.codex Skill 容器不会被点号规则忽略", () => {
    const cursorSkill = mkSkill(path.join(".cursor", "skills", "cursor-dot-skill"), {
      "SKILL.md": "---\nname: cursor-dot-skill\ndescription: Cursor dot dir\n---\nbody\n",
    });
    const codexSkill = mkSkill(path.join(".codex", "skills", "codex-dot-skill"), {
      "SKILL.md": "---\nname: codex-dot-skill\ndescription: Codex dot dir\n---\nbody\n",
      "agents/openai.yaml": "interface:\n  display_name: Codex Dot Skill\n",
    });
    mkSkill(".unrelated-hidden", {
      "SKILL.md": "---\nname: unrelated-hidden\n---\nbody\n",
    });

    const pkgs = scanAndPackage(tmp);
    expect(pkgs.map((p) => p.id).sort()).toEqual([
      "codex-dot-skill",
      "cursor-dot-skill",
    ]);
    expect(pkgs.map((p) => p.sourcePath).sort()).toEqual(
      [codexSkill, cursorSkill].sort(),
    );
  });

  it("空目录 / 不存在目录 → 空数组", () => {
    expect(scanAndPackage(tmp)).toEqual([]);
    expect(scanAndPackage(path.join(tmp, "nope"))).toEqual([]);
  });
});
