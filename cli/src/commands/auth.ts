import { CloudClient } from "../cloud/client.js";
import type { UserResponse } from "../cloud/types.js";
import {
  clearCredential,
  loadConfig,
  requireCloudConfig,
  resolveConfig,
  saveConfig,
} from "../config.js";
import { CliError, EXIT } from "../errors.js";
import type { Output } from "../output.js";

export interface LoginOptions {
  apiKey?: string;
  cloud?: string;
}

export async function loginCommand(
  options: LoginOptions,
  output: Output,
): Promise<void> {
  const credentialSource = options.apiKey
    ? "argument"
    : process.env["VIBEBARA_API_KEY"]
      ? "environment"
      : "config";
  const resolved = resolveConfig({
    apiKey: options.apiKey,
    cloudApiBase: options.cloud,
  });
  if (!resolved.apiKey?.startsWith("vhk_")) {
    throw new CliError(
      "请通过 --api-key 或 VIBEBARA_API_KEY 提供 vhk_ PAT",
      EXIT.USAGE,
    );
  }
  if (!resolved.cloudApiBase) {
    throw new CliError(
      "请通过 --cloud 或 VIBEBARA_CLOUD_API_BASE 提供云端 API 地址",
      EXIT.USAGE,
    );
  }

  const client = new CloudClient(resolved.cloudApiBase, resolved.apiKey);
  const response = await client.get<UserResponse>("/auth/me");
  if (!response.success || !response.user) {
    throw new CliError(response.error || "凭据验证失败", EXIT.AUTH);
  }
  const stored = loadConfig();
  if (stored.userId && stored.userId !== response.user.id) {
    clearCredential();
  }
  saveConfig({
    apiKey: resolved.apiKey,
    cloudApiBase: resolved.cloudApiBase,
    userId: response.user.id,
    deviceId: response.credential?.device_id ?? undefined,
  });
  output.data({
    success: true,
    username: response.user.username,
    device_id: response.credential?.device_id,
    credential_source: credentialSource,
    cloud_api_base: resolved.cloudApiBase,
  });
}

export async function whoamiCommand(
  output: Output,
  cloudApiBase?: string,
): Promise<void> {
  const config = requireCloudConfig({ cloudApiBase });
  const response = await new CloudClient(
    config.cloudApiBase,
    config.apiKey,
  ).get<UserResponse>("/auth/me");
  if (!response.success || !response.user) {
    throw new CliError(response.error || "凭据验证失败", EXIT.AUTH);
  }
  output.data({
    success: true,
    user: response.user,
    api_key: `${config.apiKey.slice(0, 8)}…`,
    device_id: response.credential?.device_id,
    credential_source: process.env["VIBEBARA_API_KEY"]
      ? "environment"
      : "config",
    cloud_api_base: config.cloudApiBase,
  });
}

export function logoutCommand(output: Output): void {
  const hadCredential = Boolean(loadConfig().apiKey);
  clearCredential();
  output.data({ success: true, logged_out: hadCredential });
}
