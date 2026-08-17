import fs from "node:fs";
import path from "node:path";
import { isInside, realResolve } from "@vibebara/local-core";
import type { UserSkillDeploymentInfo } from "./cloud/types.js";
import { CliError, EXIT } from "./errors.js";

const TOOL_MARKERS = [
  ".cursor",
  ".codex",
  ".windsurf",
  ".claude",
  ".kiro",
  ".trae",
  ".qoder",
  ".workbuddy",
];

const TEAM_SKILL_SUFFIX = /-team-[0-9a-z]{1,12}$/i;

export interface DeploymentSelector {
  deployment?: string;
  skill?: string;
  project?: string;
  cwd?: string;
}

function samePath(a: string, b: string): boolean {
  const left = realResolve(a);
  const right = realResolve(b);
  return process.platform === "win32"
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}

export function detectRepositoryRoot(start: string): string | null {
  let current = path.resolve(start);
  while (true) {
    for (const marker of TOOL_MARKERS) {
      const skills = path.join(current, marker, "skills");
      if (fs.existsSync(skills) && fs.statSync(skills).isDirectory()) {
        return current;
      }
    }
    for (const marker of TOOL_MARKERS) {
      if (fs.existsSync(path.join(current, marker))) return current;
    }
    if (fs.existsSync(path.join(current, ".git"))) return current;
    const parent = path.dirname(current);
    if (parent === current) return null;
    current = parent;
  }
}

export function resolveDeployment(
  deployments: UserSkillDeploymentInfo[],
  selector: DeploymentSelector,
): UserSkillDeploymentInfo {
  let candidates = deployments;
  if (selector.deployment) {
    candidates = candidates.filter((item) => item.id === selector.deployment);
  }
  if (selector.skill) {
    const skill = selector.skill.toLowerCase();
    candidates = candidates.filter(
      (item) =>
        item.team_skill_id.toLowerCase() === skill ||
        item.skill_name.toLowerCase() === skill,
    );
  }
  if (selector.project) {
    candidates = candidates.filter(
      (item) => item.project_id === selector.project,
    );
  }

  if (!selector.deployment && !selector.skill) {
    const root = detectRepositoryRoot(selector.cwd ?? process.cwd());
    if (!root) {
      throw new CliError(
        "无法从当前目录定位仓库根；请使用 --deployment 或 --skill",
        EXIT.USAGE,
      );
    }
    candidates = candidates.filter(
      (item) =>
        samePath(item.deploy_path, root) ||
        isInside(realResolve(item.install_path), realResolve(root)),
    );
  }

  if (candidates.length === 0) {
    throw new CliError("未找到匹配的部署实例", EXIT.USAGE);
  }
  if (candidates.length > 1) {
    throw new CliError(
      `匹配到 ${candidates.length} 个部署实例，请用 --deployment/--skill/--project 消歧`,
      EXIT.USAGE,
      candidates.map((item) => ({
        id: item.id,
        skill: item.team_skill_id,
        project: item.project_id,
        install_path: item.install_path,
      })),
    );
  }
  return candidates[0]!;
}

export function assertSameMachine(
  deployment: UserSkillDeploymentInfo,
): void {
  const installPath = deployment.install_path;
  const naturalSkillId =
    deployment.team_skill_id.replace(TEAM_SKILL_SUFFIX, "") ||
    deployment.team_skill_id;
  const expectedSkillIds = new Set([
    deployment.team_skill_id,
    naturalSkillId,
  ]);
  let stat: fs.Stats;
  try {
    stat = fs.statSync(installPath);
  } catch {
    throw new CliError(
      `该部署登记在 ${installPath}，本机不存在该路径。请在本机用桌面客户端重新部署，或回原机器操作；CLI 暂不支持跨机。`,
      EXIT.LOCAL_DISK,
    );
  }
  if (
    !stat.isDirectory() ||
    !fs.existsSync(path.join(installPath, "SKILL.md")) ||
    !expectedSkillIds.has(path.basename(installPath))
  ) {
    throw new CliError(
      `该部署登记在 ${installPath}，但目录不是与 ${deployment.team_skill_id} 对应的本地 Skill。请在本机重新部署；CLI 暂不支持跨机。`,
      EXIT.LOCAL_DISK,
    );
  }
}
