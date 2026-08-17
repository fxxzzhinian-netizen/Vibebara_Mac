import { app } from "electron";
import { autoUpdater } from "electron-updater";
import type { DesktopUpdateState } from "../shared/types";

type UpdateStateListener = (state: DesktopUpdateState) => void;

let configured = false;
let state: DesktopUpdateState = {
  status: app.isPackaged ? "idle" : "disabled",
  currentVersion: app.getVersion(),
};
const listeners = new Set<UpdateStateListener>();

function publish(patch: Partial<DesktopUpdateState>): void {
  state = { ...state, ...patch };
  const snapshot = getUpdateState();
  for (const listener of listeners) listener(snapshot);
}

function publicError(error: unknown): string {
  console.error("[auto-update] 更新失败:", (error as Error)?.message ?? error);
  return "更新检查失败，请稍后重试";
}

export function getUpdateState(): DesktopUpdateState {
  return { ...state };
}

export function onUpdateStateChange(listener: UpdateStateListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function checkForDesktopUpdate(): Promise<DesktopUpdateState> {
  if (!configured) {
    return getUpdateState();
  }
  if (state.status === "downloaded") {
    return getUpdateState();
  }
  publish({
    status: "checking",
    message: undefined,
    percent: undefined,
    transferred: undefined,
    total: undefined,
    bytesPerSecond: undefined,
  });
  try {
    await autoUpdater.checkForUpdates();
  } catch (error) {
    publish({ status: "error", message: publicError(error) });
  }
  return getUpdateState();
}

export function installDesktopUpdate(): boolean {
  if (!configured || state.status !== "downloaded") {
    return false;
  }
  // 先让 IPC 响应返回渲染层，再退出并交给 NSIS 完成覆盖安装。
  setImmediate(() => autoUpdater.quitAndInstall(false, true));
  return true;
}

/**
 * 仅在打包应用中启用安全更新链路。
 * 正式包默认读取 electron-builder 内置的 app-update.yml；updateUrl 仅用于灰度覆盖。
 */
export function configureAutoUpdater(updateUrl = ""): void {
  if (!app.isPackaged) {
    publish({ status: "disabled", message: "开发模式不启用自动更新" });
    return;
  }
  if (configured) {
    return;
  }

  if (updateUrl) {
    try {
      const feed = new URL(updateUrl);
      if (feed.protocol !== "https:") {
        throw new Error("更新源必须使用 HTTPS");
      }
      autoUpdater.setFeedURL({ provider: "generic", url: feed.href });
      console.log(`[auto-update] 使用覆盖更新源 ${feed.origin}`);
    } catch (error) {
      publish({ status: "error", message: publicError(error) });
      return;
    }
  }

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  configured = true;
  publish({ status: "idle", message: undefined });

  autoUpdater.on("checking-for-update", () => {
    console.log("[auto-update] 正在检查更新");
    publish({ status: "checking", message: undefined });
  });
  autoUpdater.on("update-available", (info) => {
    console.log(`[auto-update] 发现新版本 ${info.version}，开始下载`);
    publish({
      status: "available",
      availableVersion: info.version,
      message: undefined,
    });
  });
  autoUpdater.on("update-not-available", (info) => {
    console.log(`[auto-update] 当前已是最新版本 ${info.version}`);
    publish({
      status: "idle",
      availableVersion: undefined,
      percent: undefined,
      transferred: undefined,
      total: undefined,
      bytesPerSecond: undefined,
      message: undefined,
    });
  });
  autoUpdater.on("download-progress", (progress) => {
    publish({
      status: "downloading",
      percent: Math.max(0, Math.min(100, progress.percent)),
      transferred: progress.transferred,
      total: progress.total,
      bytesPerSecond: progress.bytesPerSecond,
      message: undefined,
    });
  });
  autoUpdater.on("update-downloaded", (info) => {
    console.log(`[auto-update] ${info.version} 已下载，等待用户选择安装时机`);
    publish({
      status: "downloaded",
      availableVersion: info.version,
      percent: 100,
      message: undefined,
    });
  });
  autoUpdater.on("error", (error) => {
    publish({ status: "error", message: publicError(error) });
  });

  // 避免与首屏、本地代理启动争抢资源；失败仅记录，不阻断应用使用。
  setTimeout(() => {
    void checkForDesktopUpdate();
  }, 8_000);
}
