import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as outputStream } from "node:process";
import { CliError, EXIT } from "../errors.js";
import type { Output } from "../output.js";
import type { DeploymentSelector } from "../resolve.js";
import { applyMerge, prepareMerge } from "../orchestrate/merge.js";
import { pullSkill } from "../orchestrate/pull.js";
import { pushSkill } from "../orchestrate/push.js";

interface CommonOptions extends DeploymentSelector {
  cloudApiBase?: string;
}

export interface MergeCommandOptions extends CommonOptions {
  preview?: boolean;
  yes?: boolean;
  forceManual?: boolean;
}

export interface PushCommandOptions extends CommonOptions {
  createVersion?: boolean;
  versionNumber?: string;
  versionLabel?: string;
}

export interface PullCommandOptions extends CommonOptions {
  overwrite?: boolean;
}

async function confirmCommit(): Promise<boolean> {
  if (!input.isTTY) {
    throw new CliError(
      "非交互环境必须显式传 --yes",
      EXIT.USAGE,
    );
  }
  const prompt = createInterface({ input, output: outputStream });
  try {
    const answer = await prompt.question("提交合并并覆盖本地文件？[y/N] ");
    return ["y", "yes"].includes(answer.trim().toLowerCase());
  } finally {
    prompt.close();
  }
}

export async function mergeCommand(
  options: MergeCommandOptions,
  output: Output,
): Promise<void> {
  const prepared = await prepareMerge(options);
  const previewPayload = {
    success: true,
    deployment_id: prepared.deployment.id,
    skill: prepared.deployment.team_skill_id,
    merged: prepared.preview.merged,
    preview_change_items: prepared.preview.preview_change_items,
    manual_conflicts: prepared.preview.manual_conflicts,
    notes: prepared.preview.notes,
    merge_available: prepared.preview.merge_available,
    theirs_hash: prepared.preview.theirs_hash,
  };
  const needsManual =
    prepared.preview.manual_conflicts.length > 0 ||
    !prepared.preview.merge_available;
  if (options.preview) {
    if (needsManual) {
      throw new CliError(
        "合并预览需要人工处理，未提交",
        EXIT.MANUAL_CONFLICT,
        previewPayload,
      );
    }
    output.data(previewPayload);
    return;
  }
  if (needsManual && !options.forceManual) {
    throw new CliError(
      "存在人工冲突或 AI 合并不可用；核对后使用 --force-manual 提交",
      EXIT.MANUAL_CONFLICT,
      previewPayload,
    );
  }
  if (!output.json) output.data(previewPayload);
  if (!options.yes && !(await confirmCommit())) {
    output.data({ success: true, cancelled: true });
    return;
  }

  const result = await applyMerge(prepared);
  output.data({ ...result, preview: previewPayload });
}

export async function pushCommand(
  options: PushCommandOptions,
  output: Output,
): Promise<void> {
  const result = await pushSkill(options);
  output.data(result);
}

export async function pullCommand(
  options: PullCommandOptions,
  output: Output,
): Promise<void> {
  const result = await pullSkill(options);
  output.data(result);
}
