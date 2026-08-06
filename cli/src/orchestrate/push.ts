import { readFolder } from "@vibebara/local-core";
import type { PushDeploymentResponse } from "../cloud/types.js";
import { CliError, EXIT } from "../errors.js";
import type { DeploymentSelector } from "../resolve.js";
import { collaborationContext } from "./context.js";

export interface PushOptions extends DeploymentSelector {
  cloudApiBase?: string;
  createVersion?: boolean;
  versionNumber?: string;
  versionLabel?: string;
}

export async function pushSkill(
  options: PushOptions,
): Promise<PushDeploymentResponse> {
  const { client, deployment } = await collaborationContext(options);
  const folder = readFolder({ path: deployment.install_path, include: "all" });
  if (folder.dirHash === deployment.installed_hash) {
    return {
      success: true,
      no_change: true,
      change_items: [],
      diff_summary: "",
    };
  }

  const response = await client.post<PushDeploymentResponse>(
    `/skill-deployments/${deployment.id}/push`,
    {
      currentHash: folder.dirHash,
      files: folder.files,
      createVersion: options.createVersion ?? false,
      versionNumber: options.versionNumber ?? "",
      versionLabel: options.versionLabel ?? "",
    },
  );
  if (!response.success) {
    throw new CliError(
      response.error || "推送失败",
      response.conflict ? EXIT.CONFLICT : EXIT.GENERAL,
      response,
    );
  }
  return response;
}
