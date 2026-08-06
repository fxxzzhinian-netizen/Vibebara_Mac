"""方案 B · M4 端到端编排联调（真实三方：本地代理 node + 后端服务 + 真实 DB）。

按 `frontend/src/api/orchestration.ts` 的步骤顺序，用**真实的本地代理（node 进程）**
+ **后端编排服务函数** + **真实 MySQL** 串通三条闭环并断言：
  - deploy：build-artifact → 本地代理 write-skill → register-deployment
  - push  ：本地代理 hash → read-folder → push（内容版，临时目录重建 diff）
  - pull  ：build-artifact（团队最新）→ 本地代理 write-skill(overwrite) → commit-pull
验证点：
  · 两端 hash **位级一致**（云端 `_compute_content_hash(installPath)` == 本地代理 write/hash 返回值）；
  · status / repo_version 推进、change_log 落库；
  · 路径白名单（installPath 在白名单外 → 403 WRITE_ROOT_FORBIDDEN）/ 鉴权（缺令牌 → 401）。

运行（PowerShell，backend 目录，venv 已激活或用 venv python）：
    .\.venv\Scripts\python.exe -m tests.test_e2e_orchestration

前置：本机 MySQL（root@localhost:3306/cowork）可连 + node 在 PATH + local-agent 已 `npm run build`。
环境受限（无 DB / 无 node）时脚本会清晰跳过并打印原因。
"""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# cloud 形态联调（同时验证 native_skill_store._upsert_db 在 cloud 下不探测后端盘 = 决定①）
from app.core.config import settings  # noqa: E402

settings.DEPLOYMENT_MODE = "cloud"
settings.DEBUG = False  # 关闭 SQL echo 噪声（须在 database engine 创建前设置）

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import async_session_factory, engine  # noqa: E402
from app.models.project import Project, ProjectSkill, UserSkillDeployment  # noqa: E402
from app.models.skill_change_log import SkillChangeLog  # noqa: E402
from app.models.skill_package import PersonalSkill, TeamSkill  # noqa: E402
from app.models.team import Team, TeamMember  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import project_service  # noqa: E402
from app.services.native_skill_store import NativeSkillStore  # noqa: E402

AGENT_DIR = Path(__file__).resolve().parents[2] / "local-agent"
AGENT_ENTRY = AGENT_DIR / "dist" / "index.js"
PAIRING_TOKEN = "e2e-pairing-" + uuid.uuid4().hex
PORT = 51987


# ------------------------------------------------------------------
# HTTP helpers（stdlib，避免额外依赖）
# ------------------------------------------------------------------

def _agent_url(path: str) -> str:
    return f"http://127.0.0.1:{PORT}{path}"


def agent_get(path: str, token: str | None = PAIRING_TOKEN):
    req = urllib.request.Request(_agent_url(path), method="GET")
    if token:
        req.add_header("X-Pairing-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def agent_post(path: str, body: dict, token: str | None = PAIRING_TOKEN):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(_agent_url(path), data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Pairing-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def wait_health(timeout_s: float = 15.0) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            status, body = agent_get("/local/health", token=None)
            if status == 200 and body.get("ok"):
                return body
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.3)
    raise RuntimeError(f"本地代理 health 未就绪：{last}")


# ------------------------------------------------------------------
# DB probe / cleanup
# ------------------------------------------------------------------

async def db_reachable() -> bool:
    try:
        from sqlalchemy import text

        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [skip] MySQL 不可达：{repr(e)[:160]}")
        return False


async def ensure_tables() -> None:
    """确保 schema 存在（真实 cowork 库通常已建；幂等）。"""
    from app.core.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def cleanup(ids: dict) -> None:
    async with async_session_factory() as s:
        tsid = ids.get("team_skill_id")
        if tsid:
            await s.execute(delete(SkillChangeLog).where(SkillChangeLog.skill_id == tsid))
            await s.execute(delete(UserSkillDeployment).where(UserSkillDeployment.team_skill_id == tsid))
            await s.execute(delete(ProjectSkill).where(ProjectSkill.skill_id == tsid))
        if ids.get("project_id"):
            await s.execute(delete(UserSkillDeployment).where(UserSkillDeployment.project_id == ids["project_id"]))
            await s.execute(delete(ProjectSkill).where(ProjectSkill.project_id == ids["project_id"]))
            await s.execute(delete(SkillChangeLog).where(SkillChangeLog.project_id == ids["project_id"]))
        if tsid:
            await s.execute(delete(TeamSkill).where(TeamSkill.id == tsid))
        if ids.get("skill_id"):
            await s.execute(delete(PersonalSkill).where(PersonalSkill.id == ids["skill_id"]))
        if ids.get("project_id"):
            await s.execute(delete(Project).where(Project.id == ids["project_id"]))
        if ids.get("team_id"):
            await s.execute(delete(TeamMember).where(TeamMember.team_id == ids["team_id"]))
            await s.execute(delete(Team).where(Team.id == ids["team_id"]))
        if ids.get("user_id"):
            await s.execute(delete(User).where(User.id == ids["user_id"]))
        await s.commit()


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def _cloud_hash(path: str) -> str:
    """云端权威 hash（M1 收敛算法），读用户本地盘核对本地代理上报值是否位级一致。"""
    return project_service._compute_content_hash(path)


async def run_e2e(store_dir: str, project_dir: str) -> None:
    suffix = uuid.uuid4().hex[:8]
    ids = {
        "user_id": "e2e-user-" + suffix,
        "team_id": "e2e-team-" + suffix,
        "project_id": "e2e-proj-" + suffix,
        "skill_id": "e2e-skill-" + suffix,
    }
    # 仅设置 store 目录指针，**不调用 NativeSkillStore.init**：init 会触发
    # _sync_from_filesystem（对空 store 目录会 DELETE 全部 skill_packages 行），
    # 会破坏真实 DB。这里直接设类属性 + 建目录即可（NativeSkillStore.create 只 upsert 单条）。
    NativeSkillStore._store_dir = store_dir
    Path(store_dir).mkdir(parents=True, exist_ok=True)
    results = []

    try:
        # --- 0. 固件：user / team / member / project（直插模型，唯一前缀，便于清理）---
        # FK 顺序：先建 user（teams.owner_id / projects.created_by / team_members.user_id 均引用），
        # 显式 flush 后再建依赖行，避免无 ORM 关系时插入顺序导致 FK 失败。
        async with async_session_factory() as s:
            s.add(User(id=ids["user_id"], username="e2e_" + suffix, display_name="E2E", password_hash="x"))
            await s.flush()
            s.add(Team(id=ids["team_id"], name="E2E Team " + suffix, owner_id=ids["user_id"], invite_code=suffix[:8]))
            await s.flush()
            s.add(TeamMember(team_id=ids["team_id"], user_id=ids["user_id"], role="owner"))
            s.add(Project(id=ids["project_id"], team_id=ids["team_id"], name="E2E Proj", created_by=ids["user_id"]))
            await s.commit()

        # --- 0b. 创建个人 skill（personal_skills），补资源后复制到团队仓库（team_skills），
        # 再把团队 skill 关联到项目（拆表后项目仅能关联团队仓库 Skill）---
        personal_name = ids["skill_id"]
        personal_skill = await NativeSkillStore.create(
            {"name": personal_name, "description": "e2e demo skill"},
            vibeh_content="# e2e\n\n演示技能正文。\n",
            owner_id=ids["user_id"],
        )
        ids["skill_id"] = personal_skill["id"]
        store = NativeSkillStore._store()
        prefix = personal_skill["store_path"]
        store.put_bytes(prefix + "/scripts/run.py", b"print('e2e v1')\n")
        # 二进制资源：验证 base64 inline 忠实落盘
        store.put_bytes(prefix + "/assets/icon.png", bytes(range(256)) * 2)
        team_skill = await NativeSkillStore.copy_to_team(
            ids["skill_id"], ids["team_id"], ids["user_id"]
        )
        ids["team_skill_id"] = team_skill["id"]
        res = await project_service.add_skill_to_project(
            ids["project_id"], ids["team_skill_id"], ids["user_id"]
        )
        assert res.get("success"), res

        # =============== ① deploy ===============
        art = await project_service.build_project_skill_artifact(
            ids["project_id"], ids["team_skill_id"], ids["user_id"], "cursor"
        )
        assert art.get("success"), art
        assert "SKILL.md" in art["contents"], art["contents"].keys()
        res_paths = {r["path"] for r in art["resources"]}
        assert {"scripts/run.py", "assets/icon.png"} <= res_paths, res_paths
        repo_hash_1 = art["repo_hash"]
        assert len(repo_hash_1) == 64

        status, w = agent_post("/local/write-skill", {
            "deployPath": project_dir, "scope": "project", "tool": "cursor",
            "skillId": art["skill_id"], "contents": art["contents"],
            "resources": art["resources"], "overwrite": True, "ensureGitignore": True,
        })
        assert status == 200 and w.get("ok"), (status, w)
        install_path = w["installPath"]
        assert Path(install_path).name == personal_name
        installed_hash_1 = w["installedHash"]

        # 位级一致：云端读盘算 hash == 本地代理 write-skill 返回值
        cloud_h = _cloud_hash(install_path)
        assert cloud_h == installed_hash_1, f"deploy hash 不一致: cloud={cloud_h} agent={installed_hash_1}"
        # /local/hash 独立再算也一致
        _, h = agent_post("/local/hash", {"paths": [install_path]})
        assert h["results"][0]["hash"] == installed_hash_1
        # 二进制资源忠实还原
        assert (Path(install_path) / "assets" / "icon.png").read_bytes() == bytes(range(256)) * 2
        # .gitignore 块写入
        assert ".cursor/skills/" in (Path(project_dir) / ".gitignore").read_text(encoding="utf-8")

        reg = await project_service.register_deployment(
            project_id=ids["project_id"], skill_id=ids["team_skill_id"], user_id=ids["user_id"],
            tool="cursor", deploy_path=project_dir, install_path=install_path,
            installed_hash=installed_hash_1, repo_hash=repo_hash_1, repo_version=art["repo_version"],
            abstract_snapshot=art["abstract_snapshot"], overwrite=True,
        )
        assert reg.get("success"), reg
        dep = reg["deployment"]
        deployment_id = dep["id"]
        assert dep["status"] == "synced"
        assert dep["installed_hash"] == installed_hash_1
        results.append(("deploy", f"installedHash={installed_hash_1[:16]}… (云端/本地代理位级一致), status=synced"))

        # =============== ② push（本地改动 → 团队仓库）===============
        # 模拟本地编辑：新增一个脚本资源（必产生抽象包 diff + hash 变化）
        (Path(install_path) / "scripts" / "extra.py").write_bytes(b"print('local edit')\n")
        _, h2 = agent_post("/local/hash", {"paths": [install_path]})
        current_hash = h2["results"][0]["hash"]
        assert current_hash != installed_hash_1, "本地改动后 hash 应变化"

        _, folder = agent_post("/local/read-folder", {"path": install_path, "include": "all"})
        assert folder.get("ok") and folder["dirHash"] == current_hash, (folder.get("dirHash"), current_hash)
        files = folder["files"]

        push = await project_service.push_deployment_content(
            deployment_id, ids["user_id"], current_hash=current_hash, files=files
        )
        assert push.get("success"), push
        assert not push.get("no_change"), "应检测到改动"
        assert push.get("change_items"), push
        # 团队仓库版本应推进
        async with async_session_factory() as s:
            ps = await s.scalar(select(ProjectSkill).where(
                ProjectSkill.project_id == ids["project_id"],
                ProjectSkill.skill_id == ids["team_skill_id"]))
            new_version = ps.version
        assert new_version >= 2, f"push 后 ProjectSkill.version 应推进, got {new_version}"
        results.append(("push", f"change_items={len(push['change_items'])}, repo_version→{new_version}, broadcast skill.pushed"))

        # =============== ③ pull（团队仓库 → 覆盖本地）===============
        art2 = await project_service.build_deployment_artifact(deployment_id, ids["user_id"])
        assert art2.get("success"), art2
        team_hash = art2["repo_hash"]

        status, w2 = agent_post("/local/write-skill", {
            "deployPath": project_dir, "scope": "project", "tool": "cursor",
            "skillId": art2["skill_id"], "contents": art2["contents"],
            "resources": art2["resources"], "overwrite": True, "ensureGitignore": True,
        })
        assert status == 200 and w2.get("ok"), (status, w2)
        installed_hash_2 = w2["installedHash"]
        # 覆盖写后两端再次位级一致
        assert _cloud_hash(w2["installPath"]) == installed_hash_2

        commit = await project_service.commit_pull(
            deployment_id, ids["user_id"], installed_hash=installed_hash_2,
            repo_hash=team_hash, repo_version=art2["repo_version"], abstract_snapshot=art2["abstract_snapshot"],
        )
        assert commit.get("success"), commit
        async with async_session_factory() as s:
            dep_row = await s.get(UserSkillDeployment, deployment_id)
            assert dep_row.status == "synced"
            assert dep_row.installed_hash == installed_hash_2
            assert dep_row.local_dirty is False
            logs = (await s.execute(
                select(SkillChangeLog).where(SkillChangeLog.deployment_id == deployment_id)
            )).scalars().all()
        actions = sorted({lg.action for lg in logs})
        assert "deployed" in actions and "pulled" in actions, actions
        results.append(("pull", f"installedHash={installed_hash_2[:16]}… (位级一致), status=synced, change_log actions={actions}"))

        # =============== 安全：鉴权 + 路径白名单 ===============
        status_noauth, b_noauth = agent_post("/local/write-skill", {
            "deployPath": project_dir, "scope": "project", "tool": "cursor",
            "skillId": ids["team_skill_id"], "contents": {"SKILL.md": "x"}, "resources": [], "overwrite": True,
        }, token=None)
        assert status_noauth == 401 and b_noauth["error"]["code"] == "UNAUTHORIZED", (status_noauth, b_noauth)

        outside = str(Path(tempfile.gettempdir()) / ("e2e-outside-" + suffix))
        status_forbid, b_forbid = agent_post("/local/write-skill", {
            "deployPath": outside, "scope": "project", "tool": "cursor",
            "skillId": ids["team_skill_id"], "contents": {"SKILL.md": "x"}, "resources": [], "overwrite": True,
        })
        assert status_forbid == 403 and b_forbid["error"]["code"] == "WRITE_ROOT_FORBIDDEN", (status_forbid, b_forbid)
        results.append(("security", "缺令牌→401 UNAUTHORIZED；白名单外路径→403 WRITE_ROOT_FORBIDDEN"))

    finally:
        await cleanup(ids)

    print("\n  ===== 端到端编排闭环（真实三方）=====")
    for name, detail in results:
        print(f"  PASS  {name:9s} {detail}")


async def async_main() -> int:
    """全部 DB / 编排逻辑在**单一事件循环**内完成（异步引擎的连接池绑定单循环，
    多次 asyncio.run 会触发 'Event loop is closed'）。node 子进程用同步 subprocess。"""
    if not await db_reachable():
        print("  [skip] 跳过端到端（DB 不可达）；本地代理 ↔ hash 位级一致仍由 local-agent 单测保证。")
        return 0
    await ensure_tables()

    if not _port_free(PORT):
        print(f"  [skip] 端口 {PORT} 被占用，跳过（请释放后重试）")
        return 0

    store_dir = tempfile.mkdtemp(prefix="e2e-store-")
    project_dir = tempfile.mkdtemp(prefix="e2e-project-")
    proc = subprocess.Popen(
        [shutil.which("node"), str(AGENT_ENTRY),
         f"--port={PORT}", f"--pairing-token={PAIRING_TOKEN}",
         f"--writable-root={project_dir}"],
        cwd=str(AGENT_DIR), env=dict(os.environ),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        health = wait_health()
        print(f"  本地代理就绪：agentVersion={health.get('agentVersion')} apiVersion={health.get('apiVersion')} "
              f"platform={health.get('platform')} paired={health.get('paired')}")
        # 让本地代理把 project_dir 登记为可写根（M3「browse 即登记」；--writable-root 已注入，双保险）
        agent_get(f"/local/browse?path={project_dir}")
        await run_e2e(store_dir, project_dir)
        print("\n  端到端编排联调全部通过。")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
        shutil.rmtree(store_dir, ignore_errors=True)
        shutil.rmtree(project_dir, ignore_errors=True)
        await engine.dispose()


def main() -> int:
    if not AGENT_ENTRY.exists():
        print(f"  [skip] 本地代理未构建：{AGENT_ENTRY}（请先 `cd local-agent && npm run build`）")
        return 0
    if shutil.which("node") is None:
        print("  [skip] 未找到 node")
        return 0
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
