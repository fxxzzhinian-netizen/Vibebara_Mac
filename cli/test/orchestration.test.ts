import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { computeDirHash } from "@vibebara/local-core";
import type { UserSkillDeploymentInfo } from "../src/cloud/types.js";
import { applyMerge, prepareMerge } from "../src/orchestrate/merge.js";
import { pullSkill } from "../src/orchestrate/pull.js";
import { pushSkill } from "../src/orchestrate/push.js";

let projectRoot: string;
let installPath: string;
let originalFetch: typeof globalThis.fetch;

beforeEach(() => {
  projectRoot = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "vibe-orchestrate-")),
  );
  installPath = path.join(projectRoot, ".cursor", "skills", "demo");
  fs.mkdirSync(installPath, { recursive: true });
  fs.writeFileSync(path.join(installPath, "SKILL.md"), "mine-v1");
  process.env["VIBEBARA_API_KEY"] = "vhk_test";
  process.env["VIBEBARA_CLOUD_API_BASE"] = "http://cloud.test/api/v1";
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete process.env["VIBEBARA_API_KEY"];
  delete process.env["VIBEBARA_CLOUD_API_BASE"];
  fs.rmSync(projectRoot, { recursive: true, force: true });
});

function deployment(overrides: Partial<UserSkillDeploymentInfo> = {}) {
  return {
    id: "dep-1",
    user_id: "user-1",
    project_id: "project-1",
    team_skill_id: "demo-team-deadbeef",
    skill_name: "demo-team-deadbeef",
    tool_type: "cursor",
    deploy_path: projectRoot,
    install_path: installPath,
    repo_version: 1,
    repo_hash: "repo-old",
    installed_hash: "installed-old",
    status: "synced",
    tracking_enabled: true,
    local_dirty: false,
    last_seen_at: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  } satisfies UserSkillDeploymentInfo;
}

function json(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("push/pull orchestration", () => {
  it("uploads the local byte tree for push", async () => {
    let pushedBody: Record<string, unknown> | undefined;
    globalThis.fetch = async (input, init) => {
      const url = String(input);
      if (url.endsWith("/skill-deployments/mine")) {
        return json({ success: true, deployments: [deployment()] });
      }
      if (url.endsWith("/skill-deployments/dep-1/push")) {
        pushedBody = JSON.parse(String(init?.body));
        return json({
          success: true,
          change_items: [],
          diff_summary: "pushed",
        });
      }
      throw new Error(`unexpected URL ${url}`);
    };

    const result = await pushSkill({ deployment: "dep-1" });
    expect(result.success).toBe(true);
    expect(pushedBody?.["currentHash"]).toBe(computeDirHash(installPath));
    expect(
      (pushedBody?.["files"] as Array<{ path: string }>)[0]?.path,
    ).toBe("SKILL.md");
  });

  it("writes a pull artifact then commits its installed hash", async () => {
    const baseline = computeDirHash(installPath);
    let commitBody: Record<string, unknown> | undefined;
    globalThis.fetch = async (input, init) => {
      const url = String(input);
      if (url.endsWith("/skill-deployments/mine")) {
        return json({
          success: true,
          deployments: [deployment({ installed_hash: baseline })],
        });
      }
      if (url.endsWith("/build-artifact")) {
        return json({
          success: true,
          skill_id: "demo",
          tool: "cursor",
          contents: { "SKILL.md": "theirs-v2" },
          resources: [],
          repo_hash: "repo-v2",
          repo_version: 2,
          abstract_snapshot: {},
        });
      }
      if (url.endsWith("/commit-pull")) {
        commitBody = JSON.parse(String(init?.body));
        return json({ success: true });
      }
      throw new Error(`unexpected URL ${url}`);
    };

    await pullSkill({ deployment: "dep-1" });
    expect(fs.readFileSync(path.join(installPath, "SKILL.md"), "utf8")).toBe(
      "theirs-v2",
    );
    expect(commitBody?.["repoHash"]).toBe("repo-v2");
    expect(commitBody?.["installedHash"]).toBe(computeDirHash(installPath));
  });
});

describe("merge orchestration", () => {
  it("reuses preview files for apply and commits the merged artifact", async () => {
    let applyBody: Record<string, unknown> | undefined;
    globalThis.fetch = async (input, init) => {
      const url = String(input);
      if (url.endsWith("/skill-deployments/mine")) {
        return json({
          success: true,
          deployments: [deployment({ status: "conflict" })],
        });
      }
      if (url.endsWith("/merge-preview")) {
        return json({
          success: true,
          merged: { body: "merged", config: {}, resource_ops: [] },
          preview_change_items: [],
          manual_conflicts: [],
          notes: [],
          merge_available: true,
          theirs_hash: "theirs-v2",
        });
      }
      if (url.endsWith("/merge-apply")) {
        applyBody = JSON.parse(String(init?.body));
        return json({
          success: true,
          artifact: {
            success: true,
            skill_id: "demo",
            tool: "cursor",
            contents: { "SKILL.md": "merged-output" },
            resources: [],
            repo_hash: "repo-merged",
            repo_version: 3,
            abstract_snapshot: {},
          },
        });
      }
      if (url.endsWith("/commit-merge")) {
        return json({ success: true });
      }
      throw new Error(`unexpected URL ${url}`);
    };

    const prepared = await prepareMerge({ deployment: "dep-1" });
    fs.writeFileSync(path.join(installPath, "SKILL.md"), "changed-after-preview");
    await applyMerge(prepared);

    const sentFile = (
      applyBody?.["files"] as Array<{ path: string; content: string }>
    )[0];
    expect(sentFile?.content).toBe("mine-v1");
    expect(fs.readFileSync(path.join(installPath, "SKILL.md"), "utf8")).toBe(
      "merged-output",
    );
  });
});
