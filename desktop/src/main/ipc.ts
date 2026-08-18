import {
  ipcMain,
  type IpcMainEvent,
  type IpcMainInvokeEvent,
} from "electron";
import {
  IPC,
  type CliAuthorizationRequest,
  type DesktopUpdateState,
  type LauncherLaunchRequest,
  type RuntimeConfigPayload,
} from "../shared/types";
import { bindCliIdentity, writeCliAuthorization } from "./cliConfig";
import * as launcher from "./launcher";
import * as tokenStore from "./tokenStore";

/**
 * 注册主进程 IPC 处理器（方案 B M5-a）。
 *
 *   · 同步：运行时配置、token 读取（preload sendSync，窗口加载前/拦截器同步取值）；
 *   · 异步：token 写/清、launcher 列举/启动（ipcRenderer.invoke）。
 */
export function registerIpc(deps: {
  getRuntimeConfig: () => RuntimeConfigPayload | null;
  /** 仅允许打包内页面或本机开发服务器调用高权限 IPC。 */
  isTrustedSender: (url: string) => boolean;
  /** 回写云端铸造的规范 device_id（M5-b 注册后）；返回回写后的有效 deviceId。 */
  persistDeviceId: (deviceId: string) => string;
  getUpdateState: () => DesktopUpdateState;
  checkForUpdate: () => Promise<DesktopUpdateState>;
  installUpdate: () => boolean;
}): void {
  const senderUrl = (event: IpcMainEvent | IpcMainInvokeEvent): string =>
    event.senderFrame?.url || event.sender.getURL();
  const isTrusted = (event: IpcMainEvent | IpcMainInvokeEvent): boolean =>
    deps.isTrustedSender(senderUrl(event));
  const assertTrusted = (event: IpcMainInvokeEvent): void => {
    if (!isTrusted(event)) {
      throw new Error("拒绝来自非受信任页面的 IPC 调用");
    }
  };

  // —— 运行时配置（同步）——
  ipcMain.on(IPC.RUNTIME_GET_SYNC, (event) => {
    event.returnValue = isTrusted(event) ? deps.getRuntimeConfig() : null;
  });

  // —— 设备身份回写（M5-b，异步）：登录注册后把规范 device_id 落 vibebara-device.json ——
  ipcMain.handle(IPC.DEVICE_PERSIST_ID, (event: IpcMainInvokeEvent, deviceId: unknown) => {
    assertTrusted(event);
    const id = typeof deviceId === "string" ? deviceId : "";
    return deps.persistDeviceId(id);
  });

  // —— 登录 token（同步读 / 异步写）——
  ipcMain.on(IPC.TOKEN_GET_SYNC, (event) => {
    event.returnValue = isTrusted(event) ? tokenStore.getToken() : "";
  });
  ipcMain.handle(IPC.TOKEN_SET, (event: IpcMainInvokeEvent, token: unknown) => {
    assertTrusted(event);
    tokenStore.setToken(typeof token === "string" ? token : "");
    return true;
  });
  ipcMain.handle(IPC.TOKEN_CLEAR, (event: IpcMainInvokeEvent) => {
    assertTrusted(event);
    tokenStore.clearToken();
    return true;
  });

  // —— C+：已登录桌面会话为 CLI 铸 PAT 后，一键写入用户级 CLI 配置 ——
  ipcMain.handle(
    IPC.CLI_AUTHORIZE,
    (event: IpcMainInvokeEvent, request: CliAuthorizationRequest) => {
      assertTrusted(event);
      return writeCliAuthorization(request);
    },
  );
  ipcMain.handle(
    IPC.CLI_BIND_IDENTITY,
    (
      event: IpcMainInvokeEvent,
      request: { userId: string; deviceId: string },
    ) => {
      assertTrusted(event);
      return bindCliIdentity(request);
    },
  );

  // —— launcher 一键启动（异步）——
  ipcMain.handle(IPC.LAUNCHER_LIST, (event: IpcMainInvokeEvent) => {
    assertTrusted(event);
    return launcher.listTools();
  });
  ipcMain.handle(
    IPC.LAUNCHER_LAUNCH,
    (event: IpcMainInvokeEvent, req: LauncherLaunchRequest) => {
      assertTrusted(event);
      try {
        return launcher.launchTool(req);
      } catch (e) {
        // 与后端 launcher 的 HTTPException 语义对齐：抛错，渲染层 catch 处理。
        throw new Error((e as Error)?.message ?? "启动失败");
      }
    },
  );

  // —— 桌面自动更新：状态可查询，事件另由主进程主动推送 ——
  ipcMain.handle(IPC.UPDATE_GET_STATE, (event: IpcMainInvokeEvent) => {
    assertTrusted(event);
    return deps.getUpdateState();
  });
  ipcMain.handle(IPC.UPDATE_CHECK, (event: IpcMainInvokeEvent) => {
    assertTrusted(event);
    return deps.checkForUpdate();
  });
  ipcMain.handle(IPC.UPDATE_INSTALL, (event: IpcMainInvokeEvent) => {
    assertTrusted(event);
    return deps.installUpdate();
  });
}
