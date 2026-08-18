"""方案 B · M4 云端编排端点单测。

覆盖：
1. content_transfer 纯工具：write_files 逐字节忠实落盘 + 与 M1 收敛 hash 位级一致、
   路径逃逸拦截、base64/utf8 往返；collect_store_resources 结构正确。
2. build-artifact 产物组装（_assemble_artifact）：contents 透传、资源 inline 编码、
   repo_hash/repo_version、abstract_snapshot 由产物直接生成。
3. 编排 push 的 diff 语义：上传内容重建 + parse + diff 产出正确改动点。
4. 服务层越权拦截：build-artifact(deployment) / push-content / commit-pull 拒绝他人部署。
5. 路由鉴权与多租户：build-artifact / register-deployment 缺 token→401、非成员→403、
   成员放行（TestClient + 打桩服务/鉴权，不连 DB、不调 Node）。

可直接运行：`python -m tests.test_m4_orchestration`（无需 pytest，亦兼容 pytest）。
"""

import asyncio
import base64
import hashlib
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import project_permission_service, project_service, team_service
from app.services import auth_service
from app.services.content_transfer import (
    collect_store_resources,
    write_files,
)
from app.services.project_service import _assemble_artifact, _compute_content_hash
from app.services.skill_diff_service import diff_abstract_packages, parse_native_skill
from app.services import object_store as object_store_module
from app.services.object_store import LocalObjectStore


# ------------------------------------------------------------------
# M0 §7.3 冻结伪代码的独立参考实现（用于验证写盘后 hash 与本地代理一致）
# ------------------------------------------------------------------

def _reference_hash(root_path: str) -> str:
    root = Path(root_path)
    if not root.exists():
        return ""
    rels = sorted(
        (p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()),
        key=lambda s: s.encode("utf-8"),
    )
    if not rels:
        return ""
    h = hashlib.sha256()
    for rel in rels:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update((root / rel).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# ------------------------------------------------------------------
# 1. content_transfer 纯工具
# ------------------------------------------------------------------

def test_write_files_faithful_and_hash_consistent():
    """write_files 落盘后，用 M1 收敛算法算 hash 必须与 §7.3 参考实现位级一致。

    这是 M4 hash 一致性的核心：云端把内容交本地代理落盘后，两端对同一字节树
    必算出相同 hash（dirty/冲突判定不误判）。"""
    png_bytes = bytes(range(256)) * 3
    files = [
        {"path": "SKILL.md", "encoding": "utf8", "content": "---\nname: demo\n---\n正文\r\nL2\n"},
        {"path": "scripts/run.py", "encoding": "utf8", "content": "print('hi')\n"},
        {"path": "assets/icon.png", "encoding": "base64", "content": base64.b64encode(png_bytes).decode()},
        {"path": "资料/说明.md", "encoding": "utf8", "content": "中文\n"},
    ]
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "install"
        written = write_files(root, files)
        assert set(written) == {"SKILL.md", "scripts/run.py", "assets/icon.png", "资料/说明.md"}
        # 二进制忠实还原
        assert (root / "assets/icon.png").read_bytes() == png_bytes
        # utf8 保留原始换行（不做 CRLF->LF 归一）
        assert (root / "SKILL.md").read_bytes() == "---\nname: demo\n---\n正文\r\nL2\n".encode("utf-8")
        # 收敛算法 hash == 参考实现（本地代理 TS 同算法 → 位级一致）
        assert _compute_content_hash(str(root)) == _reference_hash(str(root))
        assert len(_compute_content_hash(str(root))) == 64


def test_write_files_rejects_path_escape():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "install"
        for bad in ("../evil.txt", "a/../../evil.txt"):
            try:
                write_files(root, [{"path": bad, "encoding": "utf8", "content": "x"}])
                raise AssertionError(f"应拒绝逃逸路径: {bad}")
            except ValueError:
                pass


@contextmanager
def _isolated_object_store(root: Path):
    previous = object_store_module._store
    store = LocalObjectStore(str(root))
    object_store_module._store = store
    try:
        yield store
    finally:
        object_store_module._store = previous


def test_collect_store_resources_structure():
    with tempfile.TemporaryDirectory() as d, _isolated_object_store(
        Path(d) / "object-store"
    ) as store:
        prefix = "skills/team/demo-team-12345678"
        # 用 put_bytes 精确控制内容（避免 Windows write_text 把 \n 翻译成 \r\n）
        store.put_bytes(prefix + "/scripts/run.py", b"print(1)\n")
        store.put_bytes(prefix + "/references/doc.md", b"doc\n")
        png = bytes([0x89, 0x50, 0x4E, 0x47, 0x00, 0xFF, 0xFE])
        store.put_bytes(prefix + "/assets/icon.png", png)
        # 这些 root 文件不应被纳入资源
        store.put_bytes(prefix + "/skill.config.yaml", b"name: x\n")
        store.put_bytes(prefix + "/SKILL.md", b"body\n")
        store.put_bytes(prefix + "/LICENSE", b"MIT\n")

        res = collect_store_resources(prefix)
        by_path = {r["path"]: r for r in res}
        assert set(by_path) == {"scripts/run.py", "references/doc.md", "assets/icon.png"}
        assert by_path["scripts/run.py"]["encoding"] == "utf8"
        # 文本资源 utf8 往返必须字节忠实
        assert by_path["scripts/run.py"]["content"].encode("utf-8") == b"print(1)\n"
        assert by_path["assets/icon.png"]["encoding"] == "base64"
        assert base64.b64decode(by_path["assets/icon.png"]["content"]) == png
        assert all(r["transfer"] == "inline" for r in res)


# ------------------------------------------------------------------
# 2. build-artifact 产物组装
# ------------------------------------------------------------------

def _make_store(store: LocalObjectStore) -> str:
    prefix = "skills/team/demo-team-12345678"
    store.put_text(prefix + "/scripts/run.py", "print('go')\n")
    store.put_bytes(prefix + "/assets/icon.png", bytes(range(64)))
    store.put_text(prefix + "/skill.config.yaml", "name: demo\n")
    store.put_text(prefix + "/SKILL.md", "body\n")
    return prefix


def test_assemble_artifact_structure():
    with tempfile.TemporaryDirectory() as d, _isolated_object_store(
        Path(d) / "object-store"
    ) as object_store:
        store_prefix = _make_store(object_store)
        build_outputs = [
            {
                "target": "cursor",
                "contents": {
                    "SKILL.md": "---\nname: demo\ndescription: a demo skill\n---\nHello\n"
                },
            }
        ]
        out = _assemble_artifact("demo", "cursor", 7, store_prefix, build_outputs)
        assert out["success"] is True
        assert out["skill_id"] == "demo"
        assert out["tool"] == "cursor"
        assert out["repo_version"] == 7
        assert out["contents"]["SKILL.md"].startswith("---")
        # 资源随产物（含二进制 base64 inline）
        rpaths = {r["path"] for r in out["resources"]}
        assert rpaths == {"scripts/run.py", "assets/icon.png"}
        # repo_hash == Store 收敛 hash
        assert out["repo_hash"] == object_store.compute_prefix_hash(store_prefix)
        # abstract_snapshot 由产物直接生成（云端，无需本地回传）
        snap = out["abstract_snapshot"]
        assert snap.get("config", {}).get("name") == "demo"
        assert snap.get("config", {}).get("description") == "a demo skill"
        # 资源 hash 进入抽象快照（供后续 diff）
        assert "scripts/run.py" in snap.get("resources", {})


def test_assemble_artifact_picks_matching_tool():
    with tempfile.TemporaryDirectory() as d, _isolated_object_store(
        Path(d) / "object-store"
    ) as object_store:
        store_prefix = _make_store(object_store)
        build_outputs = [
            {"target": "cursor", "contents": {"SKILL.md": "---\nname: demo\n---\nC\n"}},
            {"target": "codex", "contents": {"SKILL.md": "---\nname: demo\n---\nX\n", "agents/openai.yaml": "interface: {}\n"}},
        ]
        out = _assemble_artifact("demo", "codex", 1, store_prefix, build_outputs)
        assert "agents/openai.yaml" in out["contents"]


# ------------------------------------------------------------------
# 3. 编排 push 的 diff 语义（上传内容重建 + parse + diff）
# ------------------------------------------------------------------

def test_push_content_diff_semantics():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "install"
        (base / "scripts").mkdir(parents=True)
        (base / "SKILL.md").write_text(
            "---\nname: demo\ndescription: old\n---\nbody\n", encoding="utf-8"
        )
        (base / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
        base_pkg = parse_native_skill(str(base), "cursor")

        # 模拟前端经 read-folder 上传的 install 内容（描述改了 + 脚本改了）
        upload_files = [
            {"path": "SKILL.md", "encoding": "utf8", "content": "---\nname: demo\ndescription: new\n---\nbody\n"},
            {"path": "scripts/run.py", "encoding": "utf8", "content": "print(2)\n"},
        ]
        upload = Path(d) / "upload"
        write_files(upload, upload_files)
        cur_pkg = parse_native_skill(str(upload), "cursor")

        items = diff_abstract_packages(base_pkg, cur_pkg)
        kinds = {(i["kind"], i.get("path")) for i in items}
        assert ("field", "description") in kinds
        assert ("resource", "scripts/run.py") in kinds
        res_item = next(i for i in items if i["kind"] == "resource")
        assert res_item["change"] == "modified"


# ------------------------------------------------------------------
# 4. 服务层越权拦截（FakeSession，不连 DB）
# ------------------------------------------------------------------

class _FakeDeployment:
    def __init__(self, user_id):
        self.id = "dep1"
        self.user_id = user_id
        self.team_skill_id = "skill1"
        self.project_id = "proj1"
        self.tool_type = "cursor"
        self.tracking_enabled = True
        self.status = "synced"
        self.repo_version = 1


class _FakeSession:
    def __init__(self, deployment):
        self._dep = deployment

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, model, ident):
        return self._dep if ident == "dep1" else None


def _patch_session(deployment):
    project_service.async_session_factory = lambda: _FakeSession(deployment)


def test_service_ownership_interception():
    owner_dep = _FakeDeployment(user_id="owner")
    orig = project_service.async_session_factory
    try:
        _patch_session(owner_dep)

        r1 = asyncio.run(project_service.build_deployment_artifact("dep1", "intruder"))
        assert r1["success"] is False and "another user" in r1["error"]

        r2 = asyncio.run(
            project_service.commit_pull("dep1", "intruder", installed_hash="x")
        )
        assert r2["success"] is False and "another user" in r2["error"]

        r3 = asyncio.run(
            project_service.push_deployment_content(
                "dep1", "intruder", current_hash="h", files=[{"path": "SKILL.md", "encoding": "utf8", "content": "x"}]
            )
        )
        assert r3["success"] is False and "another user" in r3["error"]

        # 不存在的部署
        r4 = asyncio.run(project_service.build_deployment_artifact("missing", "owner"))
        assert r4["success"] is False and "not found" in r4["error"].lower()
    finally:
        project_service.async_session_factory = orig


# ------------------------------------------------------------------
# 5. 路由鉴权与多租户（TestClient + 打桩，不连 DB / Node）
# ------------------------------------------------------------------

def test_list_user_deployments_filters_owner():
    """mine 服务查询必须在数据库层按当前 user_id 隔离。"""
    captured = {}

    class FakeResult:
        class Scalars:
            @staticmethod
            def all():
                return []

        def scalars(self):
            return self.Scalars()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            captured["statement"] = statement
            return FakeResult()

        async def scalar(self, _statement):
            return "device-owner"

    saved_factory = project_service.async_session_factory
    project_service.async_session_factory = FakeSession
    try:
        assert asyncio.run(project_service.list_user_deployments("u-owner")) == []
        statement = captured["statement"]
        assert "user_skill_deployments.user_id" in str(statement)
        assert "ORDER BY" in str(statement)
        assert "u-owner" in statement.compile().params.values()
    finally:
        project_service.async_session_factory = saved_factory


def _build_client():
    from fastapi.testclient import TestClient
    import app.main as m

    m.settings.DEPLOYMENT_MODE = "local"
    app = m.create_app()
    return TestClient(app)


def _install_router_stubs():
    """打桩 token 校验 / 团队成员 / 项目归属 / 编排服务，绕开 DB 与 Node。"""
    token_user = {"tok-member": "u-member", "tok-other": "u-other"}

    async def fake_verify(token):
        user_id = token_user.get(token)
        if not user_id:
            return None
        return auth_service.AuthCredential(
            f"token-{user_id}", user_id, "session", f"device-{user_id}"
        )

    async def fake_reason(_token):
        return ""

    async def fake_get_team_id(project_id):
        return "team-1"

    async def fake_is_member(team_id, user_id):
        return user_id == "u-member"

    async def fake_require_project_permission(project_id, user_id, permission):
        if user_id != "u-member":
            raise project_permission_service.ProjectAccessDeniedError(
                "无权访问该项目"
            )
        return project_permission_service.ProjectPermissionContext(
            project_id=project_id,
            team_id="team-1",
            user_id=user_id,
            role="member",
            member_permissions=(
                project_permission_service.DEFAULT_MEMBER_PERMISSIONS.copy()
            ),
            effective_permissions=(
                project_permission_service.DEFAULT_MEMBER_PERMISSIONS.copy()
            ),
            can_manage=False,
        )

    async def fake_build(project_id, skill_id, user_id, tool):
        return {
            "success": True,
            "skill_id": skill_id,
            "tool": tool,
            "contents": {"SKILL.md": "x"},
            "resources": [],
            "repo_hash": "h",
            "repo_version": 1,
            "abstract_snapshot": {},
        }

    async def fake_register(**kwargs):
        return {"success": True, "deployment": None}

    async def fake_list_user_deployments(user_id):
        assert user_id == "u-member"
        return [
            {
                "id": "dep-1",
                "user_id": user_id,
                "project_id": "proj1",
                "team_skill_id": "skill1",
                "skill_name": "Demo",
                "tool_type": "cursor",
                "deploy_path": "C:/proj",
                "install_path": "C:/proj/.cursor/skills/skill1",
            }
        ]

    saved = {
        "verify": auth_service.verify_credential_info,
        "reason": auth_service.credential_failure_reason,
        "team_id": project_service.get_project_team_id,
        "is_member": team_service.is_team_member,
        "require_project_permission": (
            project_permission_service.require_project_permission
        ),
        "build": project_service.build_project_skill_artifact,
        "register": project_service.register_deployment,
        "list_user_deployments": project_service.list_user_deployments,
    }
    auth_service.verify_credential_info = fake_verify
    auth_service.credential_failure_reason = fake_reason
    project_service.get_project_team_id = fake_get_team_id
    team_service.is_team_member = fake_is_member
    project_permission_service.require_project_permission = (
        fake_require_project_permission
    )
    project_service.build_project_skill_artifact = fake_build
    project_service.register_deployment = lambda **kw: fake_register(**kw)
    project_service.list_user_deployments = fake_list_user_deployments
    return saved


def _restore_router_stubs(saved):
    auth_service.verify_credential_info = saved["verify"]
    auth_service.credential_failure_reason = saved["reason"]
    project_service.get_project_team_id = saved["team_id"]
    team_service.is_team_member = saved["is_member"]
    project_permission_service.require_project_permission = saved[
        "require_project_permission"
    ]
    project_service.build_project_skill_artifact = saved["build"]
    project_service.register_deployment = saved["register"]
    project_service.list_user_deployments = saved["list_user_deployments"]


def test_router_auth_and_tenancy():
    client = _build_client()
    saved = _install_router_stubs()
    base = "/api/v1/projects/proj1/skills/skill1"
    try:
        # 缺 token → 401
        r = client.post(f"{base}/build-artifact", json={"tool": "cursor"})
        assert r.status_code == 401, r.text

        # 合法 token 但非团队成员 → 403
        r = client.post(
            f"{base}/build-artifact",
            json={"tool": "cursor"},
            headers={"Authorization": "Bearer tok-other"},
        )
        assert r.status_code == 403, r.text

        # 团队成员 → 放行，返回 snake_case 产物（R-A 统一口径）
        r = client.post(
            f"{base}/build-artifact",
            json={"tool": "cursor"},
            headers={"Authorization": "Bearer tok-member"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["skill_id"] == "skill1"
        assert body["repo_hash"] == "h"
        assert "abstract_snapshot" in body

        # register-deployment：非成员 → 403
        reg_body = {
            "tool": "cursor",
            "deployPath": "C:/proj",
            "installPath": "C:/proj/.cursor/skills/skill1",
            "installedHash": "abc",
            "repoHash": "h",
            "repoVersion": 1,
            "abstractSnapshot": {},
        }
        r = client.post(
            f"{base}/register-deployment",
            json=reg_body,
            headers={"Authorization": "Bearer tok-other"},
        )
        assert r.status_code == 403, r.text

        # register-deployment：成员 → 放行（camelCase 入参被正确解析）
        r = client.post(
            f"{base}/register-deployment",
            json=reg_body,
            headers={"Authorization": "Bearer tok-member"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        # mine：仅依赖当前登录用户，跨项目返回自己的 deployment。
        r = client.get(
            "/api/v1/skill-deployments/mine",
            headers={"Authorization": "Bearer tok-member"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["deployments"][0]["id"] == "dep-1"

        r = client.get("/api/v1/skill-deployments/mine")
        assert r.status_code == 401, r.text
    finally:
        _restore_router_stubs(saved)


def test_store_build_artifact_route():
    """store 级 build-artifact（个人/团队仓库部署）路由 + 归属守卫对齐前端调用。"""
    from fastapi.testclient import TestClient
    import app.main as m
    import app.api.skill_store as ss

    m.settings.DEPLOYMENT_MODE = "local"
    client = TestClient(m.create_app())

    token_user = {"tok-a": "u-a"}

    async def fake_verify(token):
        user_id = token_user.get(token)
        if not user_id:
            return None
        return auth_service.AuthCredential(
            f"token-{user_id}", user_id, "session", f"device-{user_id}"
        )

    async def fake_reason(_token):
        return ""

    async def fake_assert_ok(skill_id, user_id):
        return None  # 有权

    async def fake_assert_denied(skill_id, user_id):
        raise PermissionError(f"Skill '{skill_id}' not found or access denied")

    async def fake_build(skill_id, user_id, tool):
        return {
            "success": True,
            "skill_id": skill_id,
            "tool": tool,
            "contents": {"SKILL.md": "x"},
            "resources": [],
            "repo_hash": "h",
            "repo_version": 0,
            "abstract_snapshot": {},
        }

    saved_verify = auth_service.verify_credential_info
    saved_reason = auth_service.credential_failure_reason
    saved_assert = ss._assert_skill_accessible
    saved_build = ss.project_service.build_store_skill_artifact
    auth_service.verify_credential_info = fake_verify
    auth_service.credential_failure_reason = fake_reason
    ss.project_service.build_store_skill_artifact = lambda sid, uid, tool: fake_build(sid, uid, tool)
    path = "/api/v1/skill-forge/store/my-skill/build-artifact"
    try:
        # 缺 token → 401
        r = client.post(path, json={"tool": "cursor"})
        assert r.status_code == 401, r.text

        # 无权（归属守卫拒绝）→ 200 success False（与 store build/deploy 口径一致）
        ss._assert_skill_accessible = fake_assert_denied
        r = client.post(path, json={"tool": "cursor"}, headers={"Authorization": "Bearer tok-a"})
        assert r.status_code == 200, r.text
        assert r.json()["success"] is False

        # 有权 → 放行，返回 snake_case 产物（R-A 统一口径）
        ss._assert_skill_accessible = fake_assert_ok
        r = client.post(path, json={"tool": "cursor"}, headers={"Authorization": "Bearer tok-a"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["skill_id"] == "my-skill"
        assert body["repo_hash"] == "h"
    finally:
        auth_service.verify_credential_info = saved_verify
        auth_service.credential_failure_reason = saved_reason
        ss._assert_skill_accessible = saved_assert
        ss.project_service.build_store_skill_artifact = saved_build


def _run_all():
    tests = [
        test_write_files_faithful_and_hash_consistent,
        test_write_files_rejects_path_escape,
        test_collect_store_resources_structure,
        test_assemble_artifact_structure,
        test_assemble_artifact_picks_matching_tool,
        test_push_content_diff_semantics,
        test_service_ownership_interception,
        test_router_auth_and_tenancy,
        test_store_build_artifact_route,
    ]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\nAll {len(tests)} M4 orchestration tests passed.")


if __name__ == "__main__":
    _run_all()
