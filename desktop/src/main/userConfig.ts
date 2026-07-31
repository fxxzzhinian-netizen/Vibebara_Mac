import { app } from "electron";
import fs from "node:fs";
import path from "node:path";

/**
 * 云端地址等可覆盖配置（方案 B M5-a / 决策 C）。
 *
 * 策略：**内置默认 + 可由本机配置文件覆盖**。
 *   · 内置默认按是否打包区分：dev（未打包）指向本机 cloud demo，
 *     打包安装包指向云端服务器（测试者无 env，必须 bake 真实地址）；
 *   · 用户可在 `<userData>/vibebara-desktop.config.json` 覆盖 cloudApiBase /
 *     cloudWsBase / writableRoots，从本地 demo 平滑切到真实云端无需改壳代码。
 *   · 也支持环境变量覆盖（便于联调）：VIBEBARA_CLOUD_API_BASE / VIBEBARA_CLOUD_WS_BASE /
 *     VIBEBARA_UPDATE_URL / VIBEBARA_WRITABLE_ROOTS（; 分隔）。
 */

export interface CloudConfig {
  /** 云端 REST 基址（含 /api/v1）。 */
  cloudApiBase: string;
  /** 云端 WS 基址（不含路径）。 */
  cloudWsBase: string;
  /** electron-updater generic provider 的 HTTPS 基址；空表示暂不检查更新。 */
  updateUrl: string;
  /** 启动注入本地代理的可写根（可空）。 */
  writableRoots: string[];
}

// 本机 dev（未打包）默认：连本地 cloud demo 后端（零参数 build-desktop.ps1 起的 :8000）。
const DEV_DEFAULTS: CloudConfig = {
  cloudApiBase: "http://127.0.0.1:8000/api/v1",
  cloudWsBase: "ws://127.0.0.1:8000",
  updateUrl: "",
  writableRoots: [],
};

// 安装包不再内置明文 HTTP 地址。发布时必须经环境变量或用户配置提供 HTTPS/WSS，
// 未配置会在启动阶段明确失败，避免 token 静默发送到不安全链路。
const PACKAGED_DEFAULTS: CloudConfig = {
  cloudApiBase: "",
  cloudWsBase: "",
  updateUrl: "",
  writableRoots: [],
};

function builtinDefaults(): CloudConfig {
  return app.isPackaged ? { ...PACKAGED_DEFAULTS } : { ...DEV_DEFAULTS };
}

function configFile(): string {
  return path.join(app.getPath("userData"), "vibebara-desktop.config.json");
}

function splitRoots(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function validateEndpoint(
  raw: string,
  label: string,
  secureProtocol: "https:" | "wss:",
  localProtocol: "http:" | "ws:",
): string {
  if (!raw) {
    throw new Error(`${label} 未配置`);
  }
  const url = new URL(raw);
  const isLoopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    url.protocol !== secureProtocol &&
    !(url.protocol === localProtocol && isLoopback && !app.isPackaged)
  ) {
    throw new Error(
      `${label} 必须使用 ${secureProtocol}//；仅未打包开发态允许本机 ${localProtocol}//`,
    );
  }
  return url.href.replace(/\/$/, "");
}

export function loadCloudConfig(): CloudConfig {
  let merged: CloudConfig = builtinDefaults();

  // 1) 配置文件覆盖
  try {
    const f = configFile();
    if (fs.existsSync(f)) {
      const j = JSON.parse(fs.readFileSync(f, "utf-8")) as Partial<CloudConfig>;
      if (typeof j.cloudApiBase === "string" && j.cloudApiBase) {
        merged.cloudApiBase = j.cloudApiBase;
      }
      if (typeof j.cloudWsBase === "string" && j.cloudWsBase) {
        merged.cloudWsBase = j.cloudWsBase;
      }
      if (typeof j.updateUrl === "string") {
        merged.updateUrl = j.updateUrl;
      }
      if (Array.isArray(j.writableRoots)) {
        merged.writableRoots = j.writableRoots.filter(
          (r) => typeof r === "string" && r.trim(),
        );
      }
    }
  } catch (e) {
    console.warn("[user-config] 读取配置文件失败，用内置默认:", (e as Error)?.message);
  }

  // 2) 环境变量覆盖（联调优先级最高）
  if (process.env.VIBEBARA_CLOUD_API_BASE) {
    merged.cloudApiBase = process.env.VIBEBARA_CLOUD_API_BASE;
  }
  if (process.env.VIBEBARA_CLOUD_WS_BASE) {
    merged.cloudWsBase = process.env.VIBEBARA_CLOUD_WS_BASE;
  }
  if (process.env.VIBEBARA_UPDATE_URL) {
    merged.updateUrl = process.env.VIBEBARA_UPDATE_URL;
  }
  if (process.env.VIBEBARA_WRITABLE_ROOTS) {
    merged.writableRoots = splitRoots(process.env.VIBEBARA_WRITABLE_ROOTS);
  }

  merged.cloudApiBase = validateEndpoint(
    merged.cloudApiBase,
    "cloudApiBase",
    "https:",
    "http:",
  );
  merged.cloudWsBase = validateEndpoint(
    merged.cloudWsBase,
    "cloudWsBase",
    "wss:",
    "ws:",
  );
  if (merged.updateUrl) {
    merged.updateUrl = validateEndpoint(
      merged.updateUrl,
      "updateUrl",
      "https:",
      "http:",
    );
  }
  return merged;
}
