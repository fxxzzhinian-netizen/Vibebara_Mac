import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { CliError, EXIT } from "./errors.js";

export interface CliConfig {
  apiKey?: string;
  cloudApiBase?: string;
  userId?: string;
  deviceId?: string;
}

export interface ConfigOverrides {
  apiKey?: string;
  cloudApiBase?: string;
}

export function configPath(): string {
  return path.join(os.homedir(), ".vibebara", "config.json");
}

function normalizeCloudApiBase(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new CliError("cloud API 地址无效", EXIT.USAGE);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new CliError("cloud API 地址必须使用 http 或 https", EXIT.USAGE);
  }
  return normalized;
}

export function loadConfig(): CliConfig {
  const file = configPath();
  if (!fs.existsSync(file)) return {};
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8")) as CliConfig;
    return {
      apiKey: typeof value.apiKey === "string" ? value.apiKey : undefined,
      cloudApiBase:
        typeof value.cloudApiBase === "string"
          ? value.cloudApiBase
          : undefined,
      userId: typeof value.userId === "string" ? value.userId : undefined,
      deviceId: typeof value.deviceId === "string" ? value.deviceId : undefined,
    };
  } catch (error) {
    throw new CliError(
      `CLI 配置读取失败: ${(error as Error).message}`,
      EXIT.GENERAL,
    );
  }
}

function writeConfig(next: CliConfig): CliConfig {
  if (next.apiKey !== undefined) next.apiKey = next.apiKey.trim();
  if (next.cloudApiBase !== undefined) {
    next.cloudApiBase = normalizeCloudApiBase(next.cloudApiBase);
  }

  const target = configPath();
  const directory = path.dirname(target);
  const temporary = `${target}.${process.pid}.tmp`;
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  fs.writeFileSync(temporary, `${JSON.stringify(next, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  fs.renameSync(temporary, target);
  try {
    fs.chmodSync(target, 0o600);
  } catch {
    // Windows relies on the user's profile ACL.
  }
  return next;
}

export function saveConfig(update: CliConfig): CliConfig {
  return writeConfig({ ...loadConfig(), ...update });
}

export function clearCredential(): void {
  const current = loadConfig();
  delete current.apiKey;
  writeConfig(current);
}

export function resolveConfig(overrides: ConfigOverrides = {}): CliConfig {
  const stored = loadConfig();
  const apiKey =
    overrides.apiKey ??
    process.env["VIBEBARA_API_KEY"]?.trim() ??
    stored.apiKey;
  const rawBase =
    overrides.cloudApiBase ??
    process.env["VIBEBARA_CLOUD_API_BASE"]?.trim() ??
    stored.cloudApiBase;
  return {
    apiKey,
    cloudApiBase: rawBase ? normalizeCloudApiBase(rawBase) : undefined,
  };
}

export function requireCloudConfig(
  overrides: ConfigOverrides = {},
): CliConfig & Required<Pick<CliConfig, "apiKey" | "cloudApiBase">> {
  const resolved = resolveConfig(overrides);
  if (!resolved.cloudApiBase) {
    throw new CliError(
      "未配置云端地址；请运行 vibebara login --cloud <url> 或设置 VIBEBARA_CLOUD_API_BASE",
      EXIT.USAGE,
    );
  }
  if (!resolved.apiKey) {
    throw new CliError(
      "未登录；请先在桌面执行“为 CLI 授权”，或运行 vibebara login --api-key <key>",
      EXIT.AUTH,
    );
  }
  return {
    apiKey: resolved.apiKey,
    cloudApiBase: resolved.cloudApiBase,
  };
}
