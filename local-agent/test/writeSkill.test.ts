import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AgentConfig } from "../src/config";
import { createContext, type AgentContext } from "../src/context";
import { AgentError } from "../src/errors";
import { computeDirHash } from "../src/hash";
import { handleWriteSkill } from "../src/handlers/writeSkill";
import type { WriteSkillRequest } from "../src/types";

/**
 * write-skill 落盘 + 白名单 + 逃逸防护测试（契约 §6 / M0 §5.3）。
 */

let tmp: string;

beforeEach(() => {
  tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "la-write-")));
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

function makeCtx(writableRoots: string[]): AgentContext {
  const config: AgentConfig = {
    port: 0,
    pairingToken: "t",
    paired: true,
    writableRoots,
    maxBodyBytes: 256 * 1024 * 1024,
  };
  return createContext(config);
}

/** 断言抛出指定错误码的 AgentError。 */
function expectCode(fn: () => unknown, code: string): void {
  try {
    fn();
  } catch (err) {
    expect(err).toBeInstanceOf(AgentError);
    expect((err as AgentError).code).toBe(code);
    return;
  }
  throw new Error(`期望抛出 ${code}，但没有抛错`);
}

const PNG_BYTES = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x01]);

describe("handleWriteSkill", () => {
  it("项目部署：写 contents(utf8) + resources(base64/utf8)，字节忠实，installedHash 一致", () => {
    const deployPath = path.join(tmp, "project-a");
    fs.mkdirSync(deployPath, { recursive: true });
    const ctx = makeCtx([deployPath]);

    const req: WriteSkillRequest = {
      deployPath,
      scope: "project",
      tool: "cursor",
      skillId: "my-skill",
      contents: {
        "SKILL.md": "---\nname: my-skill\n---\nhello\n",
        "agents/openai.yaml": "interface:\n  display_name: My Skill\n",
      },
      resources: [
        { path: "scripts/run.py", transfer: "inline", encoding: "utf8", content: "print('hi')\n" },
        { path: "assets/icon.png", transfer: "inline", encoding: "base64", content: PNG_BYTES.toString("base64") },
      ],
      overwrite: true,
      ensureGitignore: true,
    };

    const res = handleWriteSkill(req, ctx);
    const installPath = path.join(deployPath, ".cursor", "skills", "my-skill");
    expect(res.installPath).toBe(installPath);
    expect(res.written.sort()).toEqual(
      ["SKILL.md", "agents/openai.yaml", "scripts/run.py", "assets/icon.png"].sort(),
    );

    // 文本忠实
    expect(fs.readFileSync(path.join(installPath, "SKILL.md"), "utf8")).toBe(
      "---\nname: my-skill\n---\nhello\n",
    );
    // 二进制忠实（base64 解码逐字节）
    expect(fs.readFileSync(path.join(installPath, "assets", "icon.png"))).toEqual(PNG_BYTES);

    // installedHash == 重新计算
    expect(res.installedHash).toBe(computeDirHash(installPath));
    expect(res.installedHash).toHaveLength(64);
  });

  it("ensureGitignore 在 deployPath 写入 Vibebara 块", () => {
    const deployPath = path.join(tmp, "proj-gi");
    fs.mkdirSync(deployPath, { recursive: true });
    const ctx = makeCtx([deployPath]);
    handleWriteSkill(
      {
        deployPath,
        scope: "project",
        tool: "codex",
        skillId: "s",
        contents: { "SKILL.md": "x" },
        resources: [],
        overwrite: true,
        ensureGitignore: true,
      },
      ctx,
    );
    const gi = fs.readFileSync(path.join(deployPath, ".gitignore"), "utf8");
    expect(gi).toContain("# Vibebara local skill deployments");
    expect(gi).toContain(".cursor/skills/");
    expect(gi).toContain(".codex/skills/");
    expect(gi).toContain(".windsurf/skills/");
    const guide = fs.readFileSync(path.join(deployPath, "vibebara.md"), "utf8");
    expect(guide).toContain("vibebara status");
    expect(guide).toContain("vibebara pull <skill-name>");
    expect(guide).toContain("vibebara push <skill-name>");
    expect(guide).toContain("vibebara merge <skill-name> --preview");
  });

  it("Windsurf 项目部署：落盘到 .windsurf/skills/{id}", () => {
    const deployPath = path.join(tmp, "project-ws");
    fs.mkdirSync(deployPath, { recursive: true });
    const ctx = makeCtx([deployPath]);

    const res = handleWriteSkill(
      {
        deployPath,
        scope: "project",
        tool: "windsurf",
        skillId: "ws-skill",
        contents: { "SKILL.md": "---\nname: ws-skill\ndescription: d\n---\nbody\n" },
        resources: [],
        overwrite: true,
      },
      ctx,
    );
    const installPath = path.join(deployPath, ".windsurf", "skills", "ws-skill");
    expect(res.installPath).toBe(installPath);
    expect(fs.existsSync(path.join(installPath, "SKILL.md"))).toBe(true);
  });

  it("目录已存在且未 overwrite → INSTALL_EXISTS", () => {
    const deployPath = path.join(tmp, "proj-exists");
    fs.mkdirSync(deployPath, { recursive: true });
    const ctx = makeCtx([deployPath]);
    const base: WriteSkillRequest = {
      deployPath,
      scope: "project",
      tool: "cursor",
      skillId: "dup",
      contents: { "SKILL.md": "v1" },
      resources: [],
      overwrite: true,
    };
    handleWriteSkill(base, ctx);
    expectCode(() => handleWriteSkill({ ...base, overwrite: false }, ctx), "INSTALL_EXISTS");
    // overwrite=true 覆盖成功
    const res = handleWriteSkill({ ...base, contents: { "SKILL.md": "v2" }, overwrite: true }, ctx);
    expect(fs.readFileSync(path.join(res.installPath, "SKILL.md"), "utf8")).toBe("v2");
  });

  it("【任务③】部署到用户确认选定的 deployPath：无需 browse / 无需预注入即放行（绑定授权来源）", () => {
    // 不预注入任何可写根（ctx 仅含平台目录）；deployPath 为已存在真实目录。
    const deployPath = path.join(tmp, "confirmed-target");
    fs.mkdirSync(deployPath, { recursive: true });
    const ctx = makeCtx([]); // 不预注入 deployPath
    const res = handleWriteSkill(
      {
        deployPath,
        scope: "project",
        tool: "cursor",
        skillId: "s",
        contents: { "SKILL.md": "x" },
        resources: [],
        overwrite: true,
      },
      ctx,
    );
    expect(res.installPath).toBe(
      path.join(deployPath, ".cursor", "skills", "s"),
    );
    // 登记副作用：确认选定的 deployPath 被登记为可写根（供后续复用）。
    expect(ctx.writableRoots.isAllowed(path.join(deployPath, "anything"))).toBe(true);
  });

  it("【任务③】deployPath 不存在（凭空路径）→ WRITE_ROOT_FORBIDDEN", () => {
    const ghost = path.join(tmp, "does-not-exist");
    const ctx = makeCtx([]);
    expectCode(
      () =>
        handleWriteSkill(
          {
            deployPath: ghost,
            scope: "project",
            tool: "cursor",
            skillId: "s",
            contents: { "SKILL.md": "x" },
            resources: [],
            overwrite: true,
          },
          ctx,
        ),
      "WRITE_ROOT_FORBIDDEN",
    );
  });

  it("【任务③】deployPath 是文件而非目录 → NOT_A_DIRECTORY", () => {
    const f = path.join(tmp, "a-file.txt");
    fs.writeFileSync(f, "x");
    const ctx = makeCtx([]);
    expectCode(
      () =>
        handleWriteSkill(
          {
            deployPath: f,
            scope: "project",
            tool: "cursor",
            skillId: "s",
            contents: { "SKILL.md": "x" },
            resources: [],
            overwrite: true,
          },
          ctx,
        ),
      "NOT_A_DIRECTORY",
    );
  });

  it("非法 tool → UNSUPPORTED_TOOL", () => {
    const ctx = makeCtx([tmp]);
    expectCode(
      () =>
        handleWriteSkill(
          {
            deployPath: tmp,
            scope: "project",
            // @ts-expect-error 故意传非法 tool
            tool: "vim",
            skillId: "s",
            contents: {},
            resources: [],
          },
          ctx,
        ),
      "UNSUPPORTED_TOOL",
    );
  });

  it("contents 路径含 `..` 逃逸 → BAD_REQUEST", () => {
    const deployPath = path.join(tmp, "proj-escape");
    fs.mkdirSync(deployPath, { recursive: true });
    const ctx = makeCtx([deployPath]);
    expectCode(
      () =>
        handleWriteSkill(
          {
            deployPath,
            scope: "project",
            tool: "cursor",
            skillId: "s",
            contents: { "../../evil.txt": "pwned" },
            resources: [],
            overwrite: true,
          },
          ctx,
        ),
      "BAD_REQUEST",
    );
  });

  it("scope=project 缺 deployPath → BAD_REQUEST", () => {
    const ctx = makeCtx([tmp]);
    expectCode(
      () =>
        handleWriteSkill(
          {
            scope: "project",
            tool: "cursor",
            skillId: "s",
            contents: {},
            resources: [],
          },
          ctx,
        ),
      "BAD_REQUEST",
    );
  });

  it("transfer=url 在 M3 暂不支持 → BAD_REQUEST", () => {
    const deployPath = path.join(tmp, "proj-url");
    fs.mkdirSync(deployPath, { recursive: true });
    const ctx = makeCtx([deployPath]);
    expectCode(
      () =>
        handleWriteSkill(
          {
            deployPath,
            scope: "project",
            tool: "cursor",
            skillId: "s",
            contents: { "SKILL.md": "x" },
            resources: [{ path: "assets/big.bin", transfer: "url", url: "https://x/y", sha256: "z" }],
            overwrite: true,
          },
          ctx,
        ),
      "BAD_REQUEST",
    );
  });
});
