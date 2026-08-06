import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  computeDirHash,
  ensureVibebaraGuide,
  LocalCoreError,
  readFolder,
  VIBEBARA_GUIDE_START,
  writeSkill,
} from "../src";

const CLOUD_PARITY_HEX =
  "37b702e386cff1ded780b07b2c679aabdfadf83a93e2d5fbc8dc931268cf394a";

let tempRoot: string;

beforeEach(() => {
  tempRoot = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "vibebara-core-")),
  );
});

afterEach(() => {
  fs.rmSync(tempRoot, { recursive: true, force: true });
});

function buildFixture(root: string): void {
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, "SKILL.md"), "---\nname: demo\n---\nbody\n");
  fs.writeFileSync(path.join(root, "refA.md"), "refA-content");
  fs.mkdirSync(path.join(root, "ref"));
  fs.writeFileSync(path.join(root, "ref", "z"), "z-content");
  fs.mkdirSync(path.join(root, "资料"));
  fs.writeFileSync(path.join(root, "资料", "说明.md"), "中文内容\n");
  fs.writeFileSync(path.join(root, "Aa.txt"), "Aa");
  fs.writeFileSync(path.join(root, "aB.txt"), "aB");
  fs.mkdirSync(path.join(root, "assets"));
  const block = Buffer.from(Array.from({ length: 256 }, (_, index) => index));
  fs.writeFileSync(
    path.join(root, "assets", "icon.png"),
    Buffer.concat([block, block, block, block]),
  );
}

function referenceHash(root: string): string {
  const files: string[] = [];
  const visit = (directory: string): void => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(absolute);
      else if (entry.isFile()) {
        files.push(path.relative(root, absolute).split(path.sep).join("/"));
      }
    }
  };
  visit(root);
  files.sort((a, b) =>
    Buffer.compare(Buffer.from(a, "utf8"), Buffer.from(b, "utf8")),
  );
  const digest = createHash("sha256");
  for (const relative of files) {
    digest.update(Buffer.from(relative, "utf8"));
    digest.update(Buffer.from([0]));
    digest.update(fs.readFileSync(path.join(root, relative)));
    digest.update(Buffer.from([0]));
  }
  return digest.digest("hex");
}

describe("shared hash semantics", () => {
  it("matches the independent reference and backend fixture", () => {
    const root = path.join(tempRoot, "skill");
    buildFixture(root);
    expect(computeDirHash(root)).toBe(referenceHash(root));
    expect(computeDirHash(root)).toBe(CLOUD_PARITY_HEX);
  });
});

describe("shared read/write semantics", () => {
  it("writes byte-faithful resources and reads the same tree once", () => {
    const project = path.join(tempRoot, "project");
    fs.mkdirSync(project);
    const binary = Buffer.from([0, 1, 2, 255]);
    const result = writeSkill({
      deployPath: project,
      scope: "project",
      tool: "cursor",
      skillId: "demo",
      contents: { "SKILL.md": "---\nname: demo\n---\nbody\n" },
      resources: [
        {
          path: "assets/icon.bin",
          transfer: "inline",
          encoding: "base64",
          content: binary.toString("base64"),
        },
      ],
      overwrite: true,
      ensureGitignore: true,
    });

    const folder = readFolder({ path: result.installPath });
    expect(folder.dirHash).toBe(result.installedHash);
    expect(folder.files.map((file) => file.path).sort()).toEqual([
      "SKILL.md",
      "assets/icon.bin",
    ]);
    expect(
      fs.readFileSync(path.join(result.installPath, "assets", "icon.bin")),
    ).toEqual(binary);
    expect(
      fs.readFileSync(path.join(project, "vibebara.md"), "utf8"),
    ).toContain("vibebara merge <skill-name> --preview");
  });

  it("preserves existing vibebara.md content and maintains one command block", () => {
    const project = path.join(tempRoot, "project-guide");
    fs.mkdirSync(project);
    fs.writeFileSync(path.join(project, "vibebara.md"), "# 团队说明\n", "utf8");

    ensureVibebaraGuide(project);
    ensureVibebaraGuide(project);

    const guide = fs.readFileSync(path.join(project, "vibebara.md"), "utf8");
    expect(guide.startsWith("# 团队说明\n")).toBe(true);
    expect(guide).toContain("vibebara pull <skill-name>");
    expect(guide.match(new RegExp(VIBEBARA_GUIDE_START, "g"))).toHaveLength(1);
  });

  it("rejects path traversal", () => {
    const project = path.join(tempRoot, "project");
    fs.mkdirSync(project);
    expect(() =>
      writeSkill({
        deployPath: project,
        scope: "project",
        tool: "cursor",
        skillId: "demo",
        contents: { "../../escape": "no" },
        resources: [],
        overwrite: true,
      }),
    ).toThrowError(LocalCoreError);
  });
});
