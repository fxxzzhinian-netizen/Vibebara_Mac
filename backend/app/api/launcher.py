import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import subprocess
import shutil
import shlex
import platform

from app.api.auth import get_current_user_id

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/launcher", tags=["launcher"])

# 注意（M2 多租户复核）：launcher 在「后端机器」上以子进程方式启动 Cursor/Codex，
# 属本地能力（迁移后归桌面壳/本地代理，M5）。在迁移完成前，云端形态下必须要求
# 登录鉴权，杜绝未授权用户触发服务器进程执行。前端经 apiClient 自动附带 Bearer。
# 进一步建议：cloud 模式应整体禁用本路由（见 M2 文档「残留风险」）。

SUPPORTED_TOOLS = (
    "cursor",
    "codex-cli",
    "codex-app",
    "windsurf",
    "claude-code",
    "claude-app",
    "kiro",
    "trae",
    "qoder",
    "workbuddy",
)
IS_WINDOWS = platform.system() == "Windows"

TOOL_LABELS = {
    "cursor": "Cursor",
    "codex-cli": "Codex CLI",
    "codex-app": "ChatGPT (Codex)",
    "windsurf": "Windsurf",
    "claude-code": "Claude Code",
    "claude-app": "Claude",
    "kiro": "Kiro",
    "trae": "Trae",
    "qoder": "Qoder",
    "workbuddy": "WorkBuddy",
}

# 交互式 CLI 工具（新终端窗口启动）；其余按 GUI 应用后台启动。
TERMINAL_TOOLS = ("codex-cli", "claude-code")

# 「以目标文件夹为工作区打开」的 IDE 工具：仅这些工具才把 project_path 作为命令行参数传入。
# Codex / Claude 桌面端是对话类应用，不接受工作区路径参数，传入反而会破坏启动。
WORKSPACE_TOOLS = ("cursor", "windsurf", "kiro", "trae", "qoder", "workbuddy")


class LaunchRequest(BaseModel):
    tool: str
    project_path: str = ""


class ToolInfo(BaseModel):
    id: str
    label: str
    available: bool
    mode: str
    description: str


def _find_executable(*candidates: str) -> Optional[str]:
    """Return the first candidate found in PATH, or None."""
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


_appx_cache: dict[str, Optional[str]] = {}


def _find_appx_app(package_pattern: str) -> Optional[str]:
    """在 Windows 上查找 MSIX/AppX 安装的应用，返回 shell:AppsFolder URI。"""
    if not IS_WINDOWS:
        return None
    if package_pattern in _appx_cache:
        return _appx_cache[package_pattern]
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-StartApps | Where-Object {{ $_.Name -like '{package_pattern}' }} "
             "| Select-Object -First 1 -ExpandProperty AppID"],
            capture_output=True, text=True, timeout=15,
        )
        app_id = result.stdout.strip()
        logger.info(f"[launcher] AppX 查询结果: rc={result.returncode}, id={app_id!r}")
        if app_id and result.returncode == 0:
            uri = f"shell:AppsFolder\\{app_id}"
            _appx_cache[package_pattern] = uri
            return uri
    except subprocess.TimeoutExpired:
        logger.warning(f"[launcher] 查找 AppX 应用超时: {package_pattern}")
    except Exception as e:
        logger.warning(f"[launcher] 查找 AppX 应用失败: {e}")
    _appx_cache[package_pattern] = None
    return None


def _resolve_command(tool: str) -> tuple[list[str], bool]:
    """解析工具启动命令，返回 (命令数组, via_appx)。

    via_appx=True 表示经 explorer + shell:AppsFolder 协议激活（MSIX/AppX 应用），
    此时命令不可附带任何路径参数，否则 explorer 会去打开该文件夹而非激活应用。
    """

    if tool == "cursor":
        candidates = ("cursor.cmd", "cursor") if IS_WINDOWS else ("cursor",)
        exe = _find_executable(*candidates)
        if exe:
            return [exe], False
        raise FileNotFoundError(
            "cursor 命令未找到，请确认 Cursor 已安装且在 PATH 中"
        )

    if tool == "codex-cli":
        exe = _find_executable("codex.cmd", "codex") if IS_WINDOWS else _find_executable("codex")
        if exe:
            return [exe], False
        raise FileNotFoundError(
            "codex 命令未找到，请确认 Codex CLI 已安装 (npm i -g @openai/codex)"
        )

    if tool == "codex-app":
        if IS_WINDOWS:
            # 新版 Codex 已合并进 ChatGPT 客户端；优先识别 ChatGPT，同时兼容旧 Codex App。
            exe = _find_executable(
                "ChatGPT.exe",
                "chatgpt.exe",
                "codex-app.cmd",
                "codex-app",
                "Codex.exe",
            )
            if exe:
                return [exe], False
            appx_uri = _find_appx_app("*ChatGPT*") or _find_appx_app("*Codex*")
            if appx_uri:
                return ["explorer.exe", appx_uri], True
        else:
            exe = _find_executable("chatgpt", "ChatGPT", "codex-app", "Codex")
            if exe:
                return [exe], False
        raise FileNotFoundError(
            "ChatGPT 客户端未找到，请确认已安装包含 Codex 的新版 ChatGPT 客户端"
        )

    if tool == "windsurf":
        if IS_WINDOWS:
            exe = _find_executable("windsurf.cmd", "windsurf", "Windsurf.exe")
            if exe:
                return [exe], False
            appx_uri = _find_appx_app("Windsurf")
            if appx_uri:
                return ["explorer.exe", appx_uri], True
        else:
            exe = _find_executable("windsurf", "Windsurf")
            if exe:
                return [exe], False
        raise FileNotFoundError(
            "windsurf 命令未找到，请确认 Windsurf 已安装且在 PATH 中"
        )

    if tool == "claude-code":
        exe = _find_executable("claude.cmd", "claude") if IS_WINDOWS else _find_executable("claude")
        if exe:
            return [exe], False
        raise FileNotFoundError(
            "claude 命令未找到，请确认 Claude Code 已安装 (npm i -g @anthropic-ai/claude-code)"
        )

    if tool == "claude-app":
        if IS_WINDOWS:
            exe = _find_executable("claude-app.cmd", "claude-app", "Claude.exe")
            if exe:
                return [exe], False
            appx_uri = _find_appx_app("Claude")
            if appx_uri:
                return ["explorer.exe", appx_uri], True
        else:
            exe = _find_executable("claude-app", "Claude")
            if exe:
                return [exe], False
        raise FileNotFoundError(
            "Claude App 未找到，请确认 Claude 桌面应用已安装"
        )

    if tool == "kiro":
        if IS_WINDOWS:
            exe = _find_executable("kiro.cmd", "kiro", "Kiro.exe")
            if exe:
                return [exe], False
            appx_uri = _find_appx_app("Kiro")
            if appx_uri:
                return ["explorer.exe", appx_uri], True
        else:
            exe = _find_executable("kiro", "Kiro")
            if exe:
                return [exe], False
        raise FileNotFoundError(
            "kiro 命令未找到，请确认 Kiro 已安装且在 PATH 中"
        )

    if tool == "trae":
        if IS_WINDOWS:
            exe = _find_executable("trae.cmd", "trae", "Trae.exe")
            if exe:
                return [exe], False
            # Trae 在开始菜单注册名形态多样（如 "Trae" / "Trae CN" / "TRAE SOLO CN"），用通配匹配
            appx_uri = _find_appx_app("*Trae*")
            if appx_uri:
                return ["explorer.exe", appx_uri], True
        else:
            exe = _find_executable("trae", "Trae")
            if exe:
                return [exe], False
        raise FileNotFoundError(
            "trae 命令未找到，请确认 Trae 已安装且在 PATH 中"
        )

    if tool == "qoder":
        if IS_WINDOWS:
            exe = _find_executable("qoder.cmd", "qoder", "qodercli.cmd", "qodercli", "Qoder.exe")
            if exe:
                return [exe], False
            appx_uri = _find_appx_app("Qoder")
            if appx_uri:
                return ["explorer.exe", appx_uri], True
        else:
            exe = _find_executable("qoder", "qodercli", "Qoder")
            if exe:
                return [exe], False
        raise FileNotFoundError(
            "qoder 命令未找到，请确认 Qoder 已安装且在 PATH 中"
        )

    if tool == "workbuddy":
        if IS_WINDOWS:
            exe = _find_executable("workbuddy.cmd", "workbuddy", "WorkBuddy.exe")
            if exe:
                return [exe], False
            # WorkBuddy（腾讯 CodeBuddy 生态）开始菜单注册名形态多样，用通配匹配
            appx_uri = _find_appx_app("*WorkBuddy*")
            if appx_uri:
                return ["explorer.exe", appx_uri], True
        else:
            exe = _find_executable("workbuddy", "WorkBuddy")
            if exe:
                return [exe], False
        raise FileNotFoundError(
            "workbuddy 命令未找到，请确认 WorkBuddy 已安装且在 PATH 中"
        )

    raise ValueError(f"不支持的工具: {tool}")


def _launch_background(cmd: list[str]) -> None:
    """以后台静默方式启动（用于桌面 GUI 应用）"""
    kwargs: dict = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if IS_WINDOWS:
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        )
        kwargs["shell"] = True
    subprocess.Popen(cmd, **kwargs)


def _launch_terminal(cmd: list[str], cwd: Optional[str] = None) -> None:
    """在新终端窗口中启动（用于 CLI 交互式工具）。

    传入 cwd 时，新终端的工作目录会锁定到该目录（部署后「打开终端并定位到部署目录」）。
    """
    workdir = cwd if (cwd and cwd.strip()) else None
    if IS_WINDOWS:
        # start /d 指定新窗口的工作目录；cmd /k 保留窗口。
        if workdir:
            start_args = ["start", "", "/d", workdir, "cmd", "/k"] + cmd
        else:
            start_args = ["start", "cmd", "/k"] + cmd
        subprocess.Popen(
            start_args,
            shell=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    elif platform.system() == "Darwin":
        joined = " ".join(cmd)
        script = f"cd {shlex.quote(workdir)}; {joined}" if workdir else joined
        script = script.replace('"', '\\"')
        subprocess.Popen(
            ["osascript", "-e", f'tell app "Terminal" to do script "{script}"']
        )
    else:
        for term in ("x-terminal-emulator", "gnome-terminal", "xterm"):
            if shutil.which(term):
                subprocess.Popen([term, "-e"] + cmd, cwd=workdir)
                return
        subprocess.Popen(cmd, cwd=workdir)


@api_router.get("/tools")
async def list_tools(user_id: str = Depends(get_current_user_id)):
    """返回所有支持的工具及其可用状态"""
    tools = []
    for tool_id in SUPPORTED_TOOLS:
        try:
            _resolve_command(tool_id)
            available = True
        except FileNotFoundError:
            available = False

        if tool_id == "codex-cli":
            mode, desc = "terminal", "在终端中启动 Codex CLI 交互式对话"
        elif tool_id == "codex-app":
            mode, desc = "app", "启动包含 Codex 的 ChatGPT 桌面应用"
        elif tool_id == "windsurf":
            mode, desc = "app", "启动 Windsurf IDE"
        elif tool_id == "claude-code":
            mode, desc = "terminal", "在终端中启动 Claude Code 交互式对话"
        elif tool_id == "claude-app":
            mode, desc = "app", "启动 Claude 桌面应用"
        elif tool_id == "kiro":
            mode, desc = "app", "启动 Kiro IDE"
        elif tool_id == "trae":
            mode, desc = "app", "启动 Trae IDE"
        elif tool_id == "qoder":
            mode, desc = "app", "启动 Qoder IDE"
        elif tool_id == "workbuddy":
            mode, desc = "app", "启动 WorkBuddy IDE"
        else:
            mode, desc = "app", "启动 Cursor IDE"

        tools.append(ToolInfo(
            id=tool_id,
            label=TOOL_LABELS[tool_id],
            available=available,
            mode=mode,
            description=desc,
        ))
    return {"tools": tools}


@api_router.post("/launch")
async def launch_tool(
    data: LaunchRequest, user_id: str = Depends(get_current_user_id)
):
    """启动工具 (Cursor / Codex CLI / Codex App / Windsurf)"""
    if data.tool not in SUPPORTED_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的工具: {data.tool}，可选: {', '.join(SUPPORTED_TOOLS)}",
        )

    try:
        cmd, via_appx = _resolve_command(data.tool)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    label = TOOL_LABELS[data.tool]
    is_terminal = data.tool in TERMINAL_TOOLS
    path = (data.project_path or "").strip()

    # 路径处理策略（按工具形态）：
    #   · 终端类（codex-cli / claude-code）：路径仅作为新终端的工作目录（cwd），不作为命令行参数；
    #   · IDE 工作区类（cursor / windsurf）：把路径作为参数传入以该目录为工作区打开；
    #     但经 AppsFolder 激活（via_appx）时不能附带任何参数，否则 explorer 会去打开该文件夹而非激活应用；
    #   · 桌面对话类（codex-app / claude-app）：不接受工作区路径，仅启动应用本身。
    # —— 这是「Codex/Claude 桌面端无报错也不启动」的根因：旧逻辑对所有工具都把路径追加到 explorer 命令。
    append_path = (
        not is_terminal and data.tool in WORKSPACE_TOOLS and not via_appx and bool(path)
    )
    if append_path:
        cmd.append(path)

    try:
        if is_terminal:
            _launch_terminal(cmd, path or None)
        else:
            _launch_background(cmd)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"启动 {label} 失败: {exc}",
        )

    used_path = bool(path) if is_terminal else append_path
    suffix = f"，项目路径: {path}" if used_path else ""
    return {
        "status": "launched",
        "tool": data.tool,
        "mode": "terminal" if is_terminal else "app",
        "message": f"{label} 已成功启动{suffix}",
    }
