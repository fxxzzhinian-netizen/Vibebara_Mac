import type { RuntimeConfigPayload } from "../shared/types";
import type { CloudConfig } from "./userConfig";

/**
 * 组装注入渲染层的运行时配置（方案 B M5-a，任务项 4）。
 *
 * 字段与 frontend/src/runtime/config.ts 的 VibebaraRuntimeConfig 对齐：
 *   mode='desktop' → 前端 orchestration 推断为 true（此处显式置 true，双保险）；
 *   localAgentBase/Port = 主进程为本地代理分配的端口；
 *   pairingToken = 主进程生成的高熵令牌；
 *   cloudApiBase/cloudWsBase = 本机 cloud demo（可由配置/env 覆盖）。
 */
export function buildRuntimeConfig(opts: {
  port: number;
  pairingToken: string;
  cloud: CloudConfig;
  /** 有效设备标识 = registeredDeviceId ?? clientUuid（M5-b）。 */
  deviceId: string;
  /** 本机持久 uuid（M5-b 设备注册幂等键）。 */
  clientUuid: string;
}): RuntimeConfigPayload {
  return {
    mode: "desktop",
    platform:
      process.platform === "darwin"
        ? "darwin"
        : process.platform === "linux"
          ? "linux"
          : "win32",
    cloudApiBase: opts.cloud.cloudApiBase,
    cloudWsBase: opts.cloud.cloudWsBase,
    localAgentBase: `http://127.0.0.1:${opts.port}`,
    localAgentPort: opts.port,
    pairingToken: opts.pairingToken,
    orchestration: true,
    deviceId: opts.deviceId,
    clientUuid: opts.clientUuid,
  };
}
