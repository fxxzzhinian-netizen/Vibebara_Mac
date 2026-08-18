import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.services import project_service, team_service
from app.services.auth_service import verify_credential
from app.services.skill_sync_service import SkillSyncService
from app.services.team_sync_service import TeamSyncService
from app.websocket.hub import project_ws_manager, team_ws_manager

ws_router = APIRouter()


@ws_router.websocket("/ws/project/{project_id}")
async def project_websocket_endpoint(
    websocket: WebSocket,
    project_id: str,
    user_id: str = Query(...),
    token: str = Query(default=""),
):
    """
    项目级 WebSocket 通道（Skill 实时同步）。

    连接后自动订阅 SkillSyncService 的事件广播，
    该项目下任何 Skill 变更都会推送到此连接。

    鉴权策略（M2，强制）：
      1. token 缺失或无效 → 一律拒绝（close 4001）；
      2. token 解析出的 user_id 必须与连接 user_id 一致（防伪冒），否则拒绝；
      3. 以 token 解析出的 user_id 为**权威身份**参与连接与广播；
      4. 防御性多租户校验：该用户必须是项目所属团队成员，否则拒绝（close 4003），
         避免非成员仅凭 project_id 订阅他人项目的 Skill 动态。
    """
    token_user_id = (await verify_credential(token)) if token else None
    if not token_user_id or token_user_id != user_id:
        await websocket.close(code=4001, reason="invalid token")
        return

    team_id = await project_service.get_project_team_id(project_id)
    if not team_id or not await team_service.is_team_member(team_id, token_user_id):
        await websocket.close(code=4003, reason="forbidden")
        return

    await project_ws_manager.connect(websocket, project_id, token_user_id)

    SkillSyncService.subscribe(project_id, project_ws_manager.on_skill_event)

    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                if await verify_credential(token) != token_user_id:
                    await websocket.close(code=4001, reason="signed in elsewhere")
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await project_ws_manager.disconnect(project_id, token_user_id, websocket)
        if not project_ws_manager.get_online_users(project_id):
            SkillSyncService.unsubscribe(
                project_id, project_ws_manager.on_skill_event
            )


@ws_router.websocket("/ws/team/{team_id}")
async def team_websocket_endpoint(
    websocket: WebSocket,
    team_id: str,
    user_id: str = Query(...),
    token: str = Query(default=""),
):
    """
    团队级 WebSocket 通道（结构变更实时同步）。

    连接后自动订阅 TeamSyncService 的事件广播，该团队下的项目增删、
    团队 Skill 仓库增减、成员加入都会推送到此连接，前端据此刷新对应区块。

    鉴权策略（与项目级通道一致，强制）：
      1. token 缺失或无效 → 拒绝（close 4001）；
      2. token 解析出的 user_id 必须与连接 user_id 一致（防伪冒）；
      3. 必须是该团队成员，否则拒绝（close 4003），避免非成员订阅他人团队动态。
    """
    token_user_id = (await verify_credential(token)) if token else None
    if not token_user_id or token_user_id != user_id:
        await websocket.close(code=4001, reason="invalid token")
        return

    if not await team_service.is_team_member(team_id, token_user_id):
        await websocket.close(code=4003, reason="forbidden")
        return

    await team_ws_manager.connect(websocket, team_id, token_user_id)

    TeamSyncService.subscribe(team_id, team_ws_manager.on_team_event)

    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                if await verify_credential(token) != token_user_id:
                    await websocket.close(code=4001, reason="signed in elsewhere")
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await team_ws_manager.disconnect(team_id, token_user_id, websocket)
        if not team_ws_manager.get_online_users(team_id):
            TeamSyncService.unsubscribe(
                team_id, team_ws_manager.on_team_event
            )
