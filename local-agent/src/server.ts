import http from "node:http";
import { URL } from "node:url";
import { WebSocketServer, type WebSocket } from "ws";
import { verifyPairingToken } from "./auth";
import { API_VERSION, PAIRING_TOKEN_HEADER } from "./constants";
import type { AgentContext } from "./context";
import { AgentError } from "./errors";
import { handleBrowse } from "./handlers/browse";
import { handleHash } from "./handlers/hash";
import { handleHealth } from "./handlers/health";
import { handleReadFolder } from "./handlers/readFolder";
import { handleScan } from "./handlers/scan";
import { WatchSession } from "./handlers/watch";
import { handleWriteSkill } from "./handlers/writeSkill";
import type { WatchServerMessage } from "./types";

const HOST = "127.0.0.1"; // M0 §5.4：仅监听本机回环，杜绝局域网访问

/** 仅放行桌面渲染层/本地来源的 CORS，拒绝任意网页跨站调用（M0 §5.4）。 */
export function isAllowedOrigin(origin: string | undefined): boolean {
  if (!origin || origin === "null") return true; // 非浏览器(curl)/file:// 等
  try {
    const u = new URL(origin);
    if (u.protocol === "file:" || u.protocol === "app:") return true;
    // 打包桌面端通过自定义协议 vibebara://app 加载渲染层。
    // 同时限制 host，避免其他自定义协议页面获得本地代理跨域访问权。
    if (u.protocol === "vibebara:" && u.hostname === "app") return true;
    if (
      (u.protocol === "http:" || u.protocol === "https:") &&
      (u.hostname === "127.0.0.1" || u.hostname === "localhost")
    ) {
      return true;
    }
    if (u.protocol.startsWith("vscode-webview")) return true;
  } catch {
    return false;
  }
  return false;
}

function applyCors(req: http.IncomingMessage, res: http.ServerResponse): void {
  const origin = req.headers.origin;
  if (isAllowedOrigin(origin) && origin) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type, X-Pairing-Token",
  );
}

function sendJson(res: http.ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(body);
}

function sendError(res: http.ServerResponse, err: AgentError): void {
  sendJson(res, err.httpStatus, err.toFailure());
}

async function readJsonBody(
  req: http.IncomingMessage,
  maxBytes: number,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    req.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > maxBytes) {
        reject(new AgentError("BAD_REQUEST", "请求体过大"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (chunks.length === 0) {
        resolve({});
        return;
      }
      try {
        // 去除可能的 UTF-8 BOM（部分客户端/代理会注入），否则 JSON.parse 失败
        const text = Buffer.concat(chunks).toString("utf-8").replace(/^\uFEFF/, "");
        resolve(JSON.parse(text));
      } catch {
        reject(new AgentError("BAD_REQUEST", "请求体不是合法 JSON"));
      }
    });
    req.on("error", (e) => reject(new AgentError("IO_ERROR", e.message)));
  });
}

function getPairingToken(req: http.IncomingMessage): string | undefined {
  const v = req.headers[PAIRING_TOKEN_HEADER];
  if (Array.isArray(v)) return v[0];
  return v;
}

function requireAuth(req: http.IncomingMessage, ctx: AgentContext): void {
  const token = getPairingToken(req);
  if (!verifyPairingToken(token, ctx.config.pairingToken)) {
    throw new AgentError("UNAUTHORIZED", "缺失或无效的配对令牌");
  }
}

async function route(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  ctx: AgentContext,
): Promise<void> {
  const method = (req.method ?? "GET").toUpperCase();
  const url = new URL(req.url ?? "/", `http://${HOST}`);
  const pathname = url.pathname;

  if (method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }

  // 唯一免配对令牌端点
  if (pathname === "/local/health" && method === "GET") {
    sendJson(res, 200, handleHealth(ctx));
    return;
  }

  // 其余端点强制配对令牌
  requireAuth(req, ctx);

  if (pathname === "/local/browse" && method === "GET") {
    const p = url.searchParams.get("path") ?? undefined;
    sendJson(res, 200, handleBrowse(p, ctx));
    return;
  }
  if (pathname === "/local/scan" && method === "POST") {
    const body = (await readJsonBody(req, ctx.config.maxBodyBytes)) as never;
    sendJson(res, 200, handleScan(body));
    return;
  }
  if (pathname === "/local/read-folder" && method === "POST") {
    const body = (await readJsonBody(req, ctx.config.maxBodyBytes)) as never;
    sendJson(res, 200, handleReadFolder(body));
    return;
  }
  if (pathname === "/local/write-skill" && method === "POST") {
    const body = (await readJsonBody(req, ctx.config.maxBodyBytes)) as never;
    sendJson(res, 200, handleWriteSkill(body, ctx));
    return;
  }
  if (pathname === "/local/hash" && method === "POST") {
    const body = (await readJsonBody(req, ctx.config.maxBodyBytes)) as never;
    sendJson(res, 200, handleHash(body));
    return;
  }

  throw new AgentError("BAD_REQUEST", `未知端点: ${method} ${pathname}`);
}

export interface RunningServer {
  server: http.Server;
  close(): Promise<void>;
}

/** 构造（未监听的）HTTP+WS 服务器实例。 */
export function createServer(ctx: AgentContext): http.Server {
  const server = http.createServer((req, res) => {
    applyCors(req, res);
    route(req, res, ctx).catch((err) => {
      if (err instanceof AgentError) {
        sendError(res, err);
      } else {
        sendError(
          res,
          new AgentError("IO_ERROR", "内部错误", (err as Error)?.message),
        );
      }
    });
  });

  // WS /local/watch（noServer：手动鉴权后再 handleUpgrade）
  const wss = new WebSocketServer({ noServer: true });

  server.on("upgrade", (req, socket, head) => {
    const url = new URL(req.url ?? "/", `http://${HOST}`);
    if (url.pathname !== "/local/watch") {
      socket.destroy();
      return;
    }
    const token =
      getPairingToken(req) ?? url.searchParams.get("pairingToken") ?? undefined;
    if (!verifyPairingToken(token, ctx.config.pairingToken)) {
      socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit("connection", ws, req);
    });
  });

  wss.on("connection", (ws: WebSocket) => {
    const send = (msg: WatchServerMessage): void => {
      if (ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify(msg));
      }
    };
    const session = new WatchSession(send);
    ws.on("message", (data) => session.handleMessage(data.toString()));
    ws.on("close", () => session.close());
    ws.on("error", () => session.close());
  });

  return server;
}

/** 启动服务器并监听；端口被占用且未显式指定时自动顺延（最多 +20）。 */
export function startServer(ctx: AgentContext): Promise<RunningServer> {
  const server = createServer(ctx);
  const startPort = ctx.config.port;
  const maxAttempts = 20;

  return new Promise((resolve, reject) => {
    let attempt = 0;
    const tryListen = (port: number): void => {
      server.once("error", (err: NodeJS.ErrnoException) => {
        if (err.code === "EADDRINUSE" && attempt < maxAttempts) {
          attempt += 1;
          tryListen(port + 1);
        } else {
          reject(err);
        }
      });
      server.listen(port, HOST, () => {
        const addr = server.address();
        const actualPort =
          typeof addr === "object" && addr ? addr.port : port;
        ctx.config.port = actualPort;
        // eslint-disable-next-line no-console
        console.log(
          `[local-agent] ${API_VERSION} 监听 http://${HOST}:${actualPort}` +
            ` (paired=${ctx.config.paired})`,
        );
        resolve({
          server,
          close: () =>
            new Promise<void>((r) => server.close(() => r())),
        });
      });
    };
    tryListen(startPort);
  });
}
