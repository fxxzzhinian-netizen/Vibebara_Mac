import { app } from "electron";
import { autoUpdater } from "electron-updater";

/** 仅在签名后的安装包中启用静默下载、退出时安装的安全更新链路。 */
export function configureAutoUpdater(updateUrl: string): void {
  if (!app.isPackaged) {
    return;
  }
  if (!updateUrl) {
    console.warn("[auto-update] 未配置 HTTPS 更新源，本次启动跳过自动更新");
    return;
  }

  const feed = new URL(updateUrl);
  if (feed.protocol !== "https:") {
    console.error("[auto-update] 更新源必须使用 HTTPS，已拒绝检查更新");
    return;
  }
  autoUpdater.setFeedURL({ provider: "generic", url: feed.href });

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on("checking-for-update", () => {
    console.log("[auto-update] 正在检查更新");
  });
  autoUpdater.on("update-available", (info) => {
    console.log(`[auto-update] 发现新版本 ${info.version}，开始下载`);
  });
  autoUpdater.on("update-not-available", (info) => {
    console.log(`[auto-update] 当前已是最新版本 ${info.version}`);
  });
  autoUpdater.on("update-downloaded", (info) => {
    console.log(`[auto-update] ${info.version} 已下载，将在退出应用后安装`);
  });
  autoUpdater.on("error", (error) => {
    console.error("[auto-update] 更新失败:", error.message);
  });

  // 避免与首屏、本地代理启动争抢资源；失败仅记录，不阻断应用使用。
  setTimeout(() => {
    void autoUpdater.checkForUpdatesAndNotify().catch((error: unknown) => {
      console.error("[auto-update] 检查更新失败:", (error as Error)?.message);
    });
  }, 8_000);
}
