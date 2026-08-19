import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export interface CliAuthorizationConfig {
  apiKey: string;
  cloudApiBase: string;
  userId: string;
  deviceId: string;
}

export interface CliAuthorizationResult {
  success: true;
  configPath: string;
  cliBundled: boolean;
  terminalRestartRequired: boolean;
  cliPath?: string;
}

function configDirectory(): string {
  return path.join(os.homedir(), ".vibebara");
}

export function cliConfigPath(): string {
  return path.join(configDirectory(), "config.json");
}

function bundledCliPath(): string | undefined {
  if (!process.resourcesPath) return undefined;
  if (process.platform !== "win32" && process.platform !== "darwin") {
    return undefined;
  }
  const executable = process.platform === "win32" ? "vibebara.exe" : "vibebara";
  const candidate = path.join(process.resourcesPath, "cli", executable);
  return fs.existsSync(candidate) ? candidate : undefined;
}

function validateCloudBase(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  const parsed = new URL(trimmed);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("cloudApiBase 必须使用 http 或 https");
  }
  return trimmed;
}

/** Atomically persist the CLI bootstrap config with owner-only permissions. */
export function writeCliAuthorization(
  input: CliAuthorizationConfig,
): CliAuthorizationResult {
  const apiKey = input.apiKey?.trim();
  if (!apiKey.startsWith("vhk_")) {
    throw new Error("无效的 CLI API Key");
  }
  if (!input.userId || !input.deviceId) {
    throw new Error("CLI 授权缺少账号或设备身份");
  }
  const cloudApiBase = validateCloudBase(input.cloudApiBase ?? "");
  const directory = configDirectory();
  const target = cliConfigPath();
  const temporary = `${target}.${process.pid}.tmp`;

  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  fs.writeFileSync(
    temporary,
    `${JSON.stringify({
      apiKey,
      cloudApiBase,
      userId: input.userId,
      deviceId: input.deviceId,
    }, null, 2)}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
  fs.renameSync(temporary, target);
  try {
    fs.chmodSync(target, 0o600);
  } catch {
    // Windows enforces access through the user's profile ACL.
  }
  const cliPath = bundledCliPath();
  return {
    success: true,
    configPath: target,
    cliBundled: Boolean(cliPath),
    terminalRestartRequired: Boolean(cliPath),
    cliPath,
  };
}

/** 登录身份变化时立即清掉上一账号/设备遗留的 CLI PAT。 */
export function bindCliIdentity(input: {
  userId: string;
  deviceId: string;
}): { success: true; cleared: boolean } {
  if (!input.userId || !input.deviceId) {
    throw new Error("缺少账号或设备身份");
  }
  const target = cliConfigPath();
  if (!fs.existsSync(target)) return { success: true, cleared: false };
  let current: Record<string, unknown> = {};
  try {
    current = JSON.parse(fs.readFileSync(target, "utf8")) as Record<string, unknown>;
  } catch {
    current = {};
  }
  const sameIdentity =
    current.userId === input.userId && current.deviceId === input.deviceId;
  if (sameIdentity) return { success: true, cleared: false };

  delete current.apiKey;
  current.userId = input.userId;
  current.deviceId = input.deviceId;
  const temporary = `${target}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(current, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  fs.renameSync(temporary, target);
  return { success: true, cleared: true };
}
