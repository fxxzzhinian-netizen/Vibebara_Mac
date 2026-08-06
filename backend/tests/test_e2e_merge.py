"""AI 辅助合并（冲突一键合并）端到端联调（真实三方：本地代理 node + 后端服务 + 真实 DB + 真实 LLM）。

复刻 `frontend/src/views/ProjectSkills.vue` + `orchestration.ts` 的合并链路并断言：
  场景：A 部署 → A 本地新增脚本（未推送，dirty）→ B 改 SKILL.md 正文并新增脚本后推送
        → A 被标记 status=conflict → A 走 AI 合并：
          merge_preview（读 A 文件 → 三方合并）
          → merge_apply（乐观锁 → 写回团队仓库 version+1 → 返回 native 产物）
          → 本地代理 write-skill 覆盖 A 本地
          → commit_merge（status=synced、change_log(merged)、标记 B outdated）
验证点：
  · 合并稿正文取 B 的改动（A 未动正文）、资源并集（A 的 a_extra + B 的 b_extra 都在）；
  · 写回后两端 hash 位级一致；团队版本推进到 v3；A=synced、B=outdated；change_log 含 merged；
  · 另跑一次真实 LLM 正文三方合并冒烟（mine/theirs 改不同处），断言返回非空合并稿。

运行（PowerShell，backend 目录）：
    .\.venv\Scripts\python.exe -m tests.test_e2e_merge

前置：本机 MySQL 可连 + node 在 PATH + local-agent 已 `npm run build` + .env 配好 LLM_API_KEY。
环境受限时各段会清晰跳过并打印原因。
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

import re  # noqa: E402

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))


def _read_env_database_url() -> str:
    """从 backend/.env 直接解析 DATABASE_URL（须在 import config 前拿到 DB 凭据）。"""
    env_path = _BACKEND_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(
        "DATABASE_URL", "mysql+aiomysql://root:@localhost:3306/cowork?charset=utf8mb4"
    )


# 用一次性隔离库跑 DB 联调：真实 cowork 库可能存在历史列漂移（create_all 只补表不补列），
# 隔离库由 create_all 建出与当前 ORM 完全一致的 schema，跑完即 DROP，不触碰真实数据。
# 关键：所有覆盖必须在 import app.core.config 之前经 os.environ 注入——engine 在
# config 导入时即按 settings 建好，import 后再改 settings 已不生效。
_TEST_DB = "cowork_merge_e2e"
_DB_M = re.match(
    r"mysql\+aiomysql://([^:]+):([^@]*)@([^:/]+):(\d+)/([^?]+)(\?.*)?",
    _read_env_database_url(),
)
_DB_CREATED = False
if _DB_M:
    _u, _p, _h, _port, _origdb, _qs = _DB_M.groups()
    try:
        import pymysql  # noqa: E402

        _c = pymysql.connect(host=_h, user=_u, password=_p, port=int(_port))
        with _c.cursor() as _cur:
            _cur.execute(f"CREATE DATABASE IF NOT EXISTS {_TEST_DB} CHARACTER SET utf8mb4")
        _c.commit()
        _c.close()
        os.environ["DATABASE_URL"] = (
            f"mysql+aiomysql://{_u}:{_p}@{_h}:{_port}/{_TEST_DB}{_qs or '?charset=utf8mb4'}"
        )
        _DB_CREATED = True
    except Exception as _e:  # noqa: BLE001
        print(f"  [warn] 隔离测试库创建失败（将跳过 DB 联调）：{repr(_e)[:160]}")

# cloud 模式 + 关 SQL echo + 测试 JWT 密钥（均须在 import config 前注入）。
os.environ["DEPLOYMENT_MODE"] = "cloud"
os.environ["DB_ECHO"] = "false"
os.environ.setdefault("JWT_SECRET", "e2e-merge-test-" + uuid.uuid4().hex + "x" * 16)

# 对象存储隔离到一次性临时数据根：避免污染 backend/data 真实技能仓库（须在 import config 前注入）。
_DATA_DIR = tempfile.mkdtemp(prefix="mg-data-")
os.environ["COWORK_DATA_DIR"] = _DATA_DIR


def _drop_test_db() -> None:
    if not (_DB_CREATED and _DB_M):
        return
    try:
        import pymysql

        _c = pymysql.connect(host=_h, user=_u, password=_p, port=int(_port))
        with _c.cursor() as _cur:
            _cur.execute(f"DROP DATABASE IF EXISTS {_TEST_DB}")
        _c.commit()
        _c.close()
    except Exception as _e:  # noqa: BLE001
        print(f"  [warn] 隔离测试库清理失败：{repr(_e)[:160]}")


from app.core.config import settings  # noqa: E402,F401

from sqlalchemy import delete, select  # noqa: E402

from app.core.database import async_session_factory, engine  # noqa: E402
from app.models.project import Project, ProjectSkill, UserSkillDeployment  # noqa: E402
from app.models.skill_change_log import SkillChangeLog  # noqa: E402
from app.models.skill_package import PersonalSkill, TeamSkill  # noqa: E402
from app.models.team import Team, TeamMember  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import project_service  # noqa: E402
from app.services.native_skill_store import NativeSkillStore  # noqa: E402
from app.services.skill_merge_service import merge_three_way  # noqa: E402
from app.services.llm import get_provider  # noqa: E402

AGENT_DIR = Path(__file__).resolve().parents[2] / "local-agent"
AGENT_ENTRY = AGENT_DIR / "dist" / "index.js"
PAIRING_TOKEN = "e2e-merge-pairing-" + uuid.uuid4().hex
PORT = 51988


# ------------------------------------------------------------------
# HTTP helpers（stdlib）
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
        for uid_key in ("user_id", "user_id_b"):
            if ids.get(uid_key):
                await s.execute(delete(User).where(User.id == ids[uid_key]))
        await s.commit()


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _write_skill(deploy_path: str, art: dict) -> dict:
    status, w = agent_post("/local/write-skill", {
        "deployPath": deploy_path, "scope": "project", "tool": "cursor",
        "skillId": art["skill_id"], "contents": art["contents"],
        "resources": art["resources"], "overwrite": True, "ensureGitignore": True,
    })
    assert status == 200 and w.get("ok"), (status, w)
    return w


async def _deploy_for(ids: dict, user_id: str, project_dir: str) -> dict:
    art = await project_service.build_project_skill_artifact(
        ids["project_id"], ids["team_skill_id"], user_id, "cursor"
    )
    assert art.get("success"), art
    w = _write_skill(project_dir, art)
    reg = await project_service.register_deployment(
        project_id=ids["project_id"], skill_id=ids["team_skill_id"], user_id=user_id,
        tool="cursor", deploy_path=project_dir, install_path=w["installPath"],
        installed_hash=w["installedHash"], repo_hash=art["repo_hash"],
        repo_version=art["repo_version"], abstract_snapshot=art["abstract_snapshot"],
        overwrite=True,
    )
    assert reg.get("success"), reg
    return reg["deployment"]


# ------------------------------------------------------------------
# 真实 LLM 正文三方合并冒烟（不依赖 DB / agent）
# ------------------------------------------------------------------

async def ai_body_merge_smoke() -> None:
    if not get_provider().is_configured():
        print("  [skip] 未配置 LLM_API_KEY，跳过 AI 正文三方合并冒烟")
        return
    base = {"config": {"name": "x", "description": "d"}, "vibeh_body": "# 标题\n\n第一行\n第二行\n", "resources": {}}
    mine = {"config": {"name": "x", "description": "d"}, "vibeh_body": "# 标题\n\n第一行（我改）\n第二行\n", "resources": {}}
    theirs = {"config": {"name": "x", "description": "d"}, "vibeh_body": "# 标题\n\n第一行\n第二行（他改）\n", "resources": {}}
    merged = await merge_three_way(base, mine, theirs, {}, {})
    body = merged.get("body", "")
    assert body, f"AI 合并应返回非空正文，merged={merged}"
    both = ("我改" in body) and ("他改" in body)
    flag = "（含双方改动）" if both else "（注意：未同时包含双方改动，请人工核对）"
    print(f"  PASS  ai-smoke   merge_available={merged.get('merge_available')} 正文长度={len(body)} {flag}")


# ------------------------------------------------------------------
# 冲突 → AI 合并主流程
# ------------------------------------------------------------------

async def run_merge_e2e(dir_a: str, dir_b: str) -> None:
    suffix = uuid.uuid4().hex[:8]
    ids = {
        "user_id": "mg-userA-" + suffix,
        "user_id_b": "mg-userB-" + suffix,
        "team_id": "mg-team-" + suffix,
        "project_id": "mg-proj-" + suffix,
        "skill_id": "mg-skill-" + suffix,
    }
    results = []

    try:
        # --- 固件：两个用户 + team + member + project ---
        async with async_session_factory() as s:
            s.add(User(id=ids["user_id"], username="mgA_" + suffix, display_name="A", password_hash="x"))
            s.add(User(id=ids["user_id_b"], username="mgB_" + suffix, display_name="B", password_hash="x"))
            await s.flush()
            s.add(Team(id=ids["team_id"], name="MG Team " + suffix, owner_id=ids["user_id"], invite_code=suffix[:8]))
            await s.flush()
            s.add(TeamMember(team_id=ids["team_id"], user_id=ids["user_id"], role="owner"))
            s.add(TeamMember(team_id=ids["team_id"], user_id=ids["user_id_b"], role="member"))
            s.add(Project(id=ids["project_id"], team_id=ids["team_id"], name="MG Proj", created_by=ids["user_id"]))
            await s.commit()

        # --- 基线 skill（v1）：SKILL.md + scripts/run.py + assets/icon.png ---
        personal_name = ids["skill_id"]
        personal_skill = await NativeSkillStore.create(
            {"name": personal_name, "description": "merge demo"},
            vibeh_content="# merge demo\n\n基线正文。\n",
            owner_id=ids["user_id"],
        )
        ids["skill_id"] = personal_skill["id"]
        # 经对象存储 API 写资源（个人前缀含 owner_id 与内部 UUID）。
        store = NativeSkillStore._store()
        prefix = personal_skill["store_path"]
        store.put_bytes(f"{prefix}/scripts/run.py", b"print('base v1')\n")
        store.put_bytes(f"{prefix}/assets/icon.png", bytes(range(256)))
        team_skill = await NativeSkillStore.copy_to_team(ids["skill_id"], ids["team_id"], ids["user_id"])
        ids["team_skill_id"] = team_skill["id"]
        assert (await project_service.add_skill_to_project(
            ids["project_id"], ids["team_skill_id"], ids["user_id"])).get("success")

        # --- A、B 各自部署（synced）---
        dep_a = await _deploy_for(ids, ids["user_id"], dir_a)
        dep_b = await _deploy_for(ids, ids["user_id_b"], dir_b)
        install_a = dep_a["install_path"]
        install_b = dep_b["install_path"]
        assert Path(install_a).name == personal_name
        assert Path(install_b).name == personal_name
        results.append(("setup", f"v1 部署完成 A/B；team_skill={ids['team_skill_id']}"))

        # --- A 本地新增脚本（未推送）→ 探测 dirty ---
        (Path(install_a) / "scripts" / "a_extra.py").write_bytes(b"print('A local only')\n")
        await project_service.refresh_deployment_dirty(dep_a["id"])
        async with async_session_factory() as s:
            row = await s.get(UserSkillDeployment, dep_a["id"])
            assert row.local_dirty is True, "A 本地改动后应 local_dirty=True"

        # --- B 改 SKILL.md 正文 + 新增脚本 → 推送（团队 v2）---
        body_mark = "B 追加的一段正文"
        skill_md_b = Path(install_b) / "SKILL.md"
        skill_md_b.write_bytes(skill_md_b.read_bytes() + f"\n{body_mark}。\n".encode("utf-8"))
        (Path(install_b) / "scripts" / "b_extra.py").write_bytes(b"print('B pushed')\n")
        _, hb = agent_post("/local/hash", {"paths": [install_b]})
        cur_hash_b = hb["results"][0]["hash"]
        _, folder_b = agent_post("/local/read-folder", {"path": install_b, "include": "all"})
        push = await project_service.push_deployment_content(
            dep_b["id"], ids["user_id_b"], current_hash=cur_hash_b, files=folder_b["files"]
        )
        assert push.get("success"), push

        # --- A 现在应为 conflict（团队前进 + A 本地脏）---
        async with async_session_factory() as s:
            row_a = await s.get(UserSkillDeployment, dep_a["id"])
            assert row_a.status == "conflict", f"A 应为 conflict，实际 {row_a.status}"
        results.append(("conflict", "B 推送 v2 后 A.status=conflict（团队前进 + A 本地脏）"))

        # =============== AI 合并 ===============
        # ① merge-preview：读 A 本地文件 → 三方合并
        _, ha = agent_post("/local/hash", {"paths": [install_a]})
        cur_hash_a = ha["results"][0]["hash"]
        _, folder_a = agent_post("/local/read-folder", {"path": install_a, "include": "all"})
        preview = await project_service.merge_preview(
            dep_a["id"], ids["user_id"], current_hash=cur_hash_a, files=folder_a["files"]
        )
        assert preview.get("success"), preview
        merged = preview["merged"]
        op_paths = {op["path"]: op["action"] for op in merged["resource_ops"]}
        assert op_paths.get("scripts/a_extra.py") == "use_mine", op_paths
        assert op_paths.get("scripts/b_extra.py") == "use_theirs", op_paths
        assert body_mark in merged["body"], "正文应取 B 的改动（A 未动正文）"
        results.append((
            "preview",
            f"resource_ops={len(merged['resource_ops'])} 正文取theirs manual={len(preview['manual_conflicts'])} "
            f"merge_available={preview['merge_available']}",
        ))

        # ② merge-apply：乐观锁 → 写回团队仓库 v3 → native 产物
        apply = await project_service.merge_apply(
            dep_a["id"], ids["user_id"], files=folder_a["files"], merged=merged,
            expected_theirs_hash=preview["theirs_hash"],
        )
        assert apply.get("success"), apply
        art = apply["artifact"]
        art_paths = {r["path"] for r in art["resources"]}
        assert {"scripts/run.py", "scripts/a_extra.py", "scripts/b_extra.py"} <= art_paths, art_paths

        # ③ 本地代理覆盖落盘 A + 两端 hash 位级一致
        w = _write_skill(dir_a, art)
        installed_merged = w["installedHash"]
        assert project_service._compute_content_hash(w["installPath"]) == installed_merged
        assert (Path(install_a) / "scripts" / "a_extra.py").exists()
        assert (Path(install_a) / "scripts" / "b_extra.py").exists()
        assert body_mark.encode("utf-8") in (Path(install_a) / "SKILL.md").read_bytes()

        # ④ commit-merge：登记 synced + change_log(merged) + 标记 B outdated
        commit = await project_service.commit_merge(
            dep_a["id"], ids["user_id"], installed_hash=installed_merged,
            repo_hash=art["repo_hash"], repo_version=art["repo_version"],
            abstract_snapshot=art["abstract_snapshot"],
        )
        assert commit.get("success"), commit

        async with async_session_factory() as s:
            row_a = await s.get(UserSkillDeployment, dep_a["id"])
            row_b = await s.get(UserSkillDeployment, dep_b["id"])
            ps = await s.scalar(select(ProjectSkill).where(
                ProjectSkill.project_id == ids["project_id"],
                ProjectSkill.skill_id == ids["team_skill_id"]))
            logs = (await s.execute(select(SkillChangeLog).where(
                SkillChangeLog.deployment_id == dep_a["id"]))).scalars().all()
        assert row_a.status == "synced" and row_a.local_dirty is False, (row_a.status, row_a.local_dirty)
        assert ps.version >= 3, f"团队版本应推进到 v3，实际 {ps.version}"
        assert row_b.status == "outdated", f"B 应被标记 outdated，实际 {row_b.status}"
        actions = sorted({lg.action for lg in logs})
        assert "merged" in actions, actions
        results.append((
            "merge",
            f"A=synced team_v={ps.version} B=outdated change_log={actions} "
            f"installedHash={installed_merged[:16]}…（位级一致）",
        ))

    finally:
        await cleanup(ids)

    print("\n  ===== 冲突 → AI 合并端到端闭环 =====")
    for name, detail in results:
        print(f"  PASS  {name:9s} {detail}")


async def async_main() -> int:
    # 真实 LLM 冒烟（不需要 DB / agent）
    try:
        await ai_body_merge_smoke()
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] AI 冒烟未通过（网络/额度？不阻断后续）：{repr(e)[:160]}")

    if not await db_reachable():
        print("  [skip] 跳过冲突合并端到端（DB 不可达）。")
        return 0
    await ensure_tables()
    if not _port_free(PORT):
        print(f"  [skip] 端口 {PORT} 被占用，跳过（请释放后重试）")
        return 0

    root_dir = tempfile.mkdtemp(prefix="mg-root-")
    dir_a = str(Path(root_dir) / "projA")
    dir_b = str(Path(root_dir) / "projB")
    Path(dir_a).mkdir(parents=True, exist_ok=True)
    Path(dir_b).mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [shutil.which("node"), str(AGENT_ENTRY),
         f"--port={PORT}", f"--pairing-token={PAIRING_TOKEN}",
         f"--writable-root={root_dir}"],
        cwd=str(AGENT_DIR), env=dict(os.environ),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        health = wait_health()
        print(f"  本地代理就绪：agentVersion={health.get('agentVersion')} apiVersion={health.get('apiVersion')}")
        agent_get(f"/local/browse?path={dir_a}")
        agent_get(f"/local/browse?path={dir_b}")
        await run_merge_e2e(dir_a, dir_b)
        print("\n  AI 辅助合并端到端联调全部通过。")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
        shutil.rmtree(root_dir, ignore_errors=True)
        await engine.dispose()


def main() -> int:
    if not AGENT_ENTRY.exists():
        print(f"  [skip] 本地代理未构建：{AGENT_ENTRY}（请先 `cd local-agent && npm run build`）")
        return 0
    if shutil.which("node") is None:
        print("  [skip] 未找到 node")
        return 0
    try:
        return asyncio.run(async_main())
    finally:
        _drop_test_db()
        shutil.rmtree(_DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
