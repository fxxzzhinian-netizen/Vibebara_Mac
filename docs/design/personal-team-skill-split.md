# 个人 / 团队 Skill 拆表（数据层隔离）— 设计与实现

## 1. 背景

原先个人与团队 Skill 共用单表 `skill_packages`，靠 `scope` 字段（`personal` / `team`）区分；磁盘也共用一个扁平目录 `{SKILL_STORE_DIR}/{id}/`，以 `id`（全局唯一主键）定位。该设计是演进式产物（团队能力后来加列贴上），带来一个根本约束：`id` 全局唯一 → 个人与团队不能同名（曾导致从 IDE 全局目录导入个人仓库撞团队记录报错）。

本次将其拆为两张物理表，实现数据层隔离。

## 2. 目标架构

- 表 `personal_skills`：PK `id` = 内部 UUID，`name` = 自然名，`owner_id` 为必填 FK；以 `UniqueConstraint(owner_id, name)` 保证用户内名称唯一。对象前缀为 `skills/personal/{owner_id}/{id}/`。
- 表 `team_skills`：PK `id` = 单列代理键 `{自然名}-team-{team_id[:8]}`，附 `name`（自然名）、`team_id`(FK teams)、`source_skill_id`（软引用个人 id），`UniqueConstraint(team_id, name)`；磁盘 `{SKILL_STORE_DIR}/team/{id}/`。
- 公共列由 mixin `_SkillColumnsMixin` 复用：display_name/description/short_description/version/tags/imported_from/store_path/content_hash/deployed_*7/created_at/updated_at。
- 外键改指：`project_skills.skill_id` 与 `user_skill_deployments.team_skill_id` 均 `ForeignKey("team_skills.id")`（项目 Skill 必为团队 Skill）。
- 软引用：`skill_versions.skill_id`、`skill_change_log.skill_id` 存团队 `id`（版本/变更日志只针对团队）。

`scope` 不再是列，由「所在表」隐含；`NativeSkillStore._row_to_dict` 按行类型计算 `scope` 字段对外兼容（前端无需改）。

### 关于团队代理主键的实现取舍

计划中曾提出团队表用纯 uuid 代理主键。实现时改用既有的 `{自然名}-team-{team_id[:8]}` 作为单列代理键，原因：`id` 在系统中深度耦合「磁盘目录名 + 部署落地的 IDE 目录名 + 编排/本地代理传参」。纯 uuid 会让 uuid 泄漏到部署目录名（跨后端+前端+local-agent）。沿用 `-team-<hash>` 方案：

- 同样满足「(team_id, 自然名) 唯一 + 单列代理键 + 外键指代理键」；
- 个人 id（自然名）与团队 id（带后缀）天然不冲突 → 个人/团队可同名，且 `get_by_id` 仍可「先个人后团队」单 id 解析，API 无需携带 scope；
- 对部署目录命名零行为变更（与拆表前一致），风险最小。

## 3. 关键路由（NativeSkillStore）

- `_personal_dir/_team_dir/_resolve_dir`：磁盘按仓库分目录 + 解析。
- `_get_row(session, id)`：先查 `PersonalSkill` 再查 `TeamSkill`。
- `_upsert_db(..., scope, team_id, source_skill_id, name)`：按 scope 写对应表。
- `list_all(scope, owner_id, team_ids)`：personal 表按 owner 过滤，team 表按 team_id 过滤。
- 个人导入（`import_from_external` allow_team_update=False）：只在当前用户的 `(owner_id, name)` 命名空间内判重；同名时覆盖本人的既有 UUID，不同用户同名互不冲突。
- 团队回写（promote/push，allow_team_update=True + target_skill_id）：写团队表。
- `copy_to_team` / `import_external_to_team`：读个人 / 落团队表 + 团队目录，config 写入 `team_id` / `source_skill_id` 供 `_sync_from_filesystem` 重建识别。
- `_sync_from_filesystem`：按 `personal/{owner_id}/{uuid}` 与 `team/{id}` 扫描；仅在对象目录完整列举成功后裁剪 DB，COS 瞬时列举失败时保留数据库索引。

## 4. 受影响文件

- 模型：`backend/app/models/skill_package.py`（PersonalSkill/TeamSkill + mixin）、`models/project.py`（2 处 FK 改指）、`models/__init__.py`。
- 服务：`native_skill_store.py`（全量按两表路由）、`project_service.py`（所有 `SkillPackage`→`TeamSkill`，删 3 处 `pkg.scope="team"`，`add_skill_to_project` 改为要求团队表已有该 Skill）、`team_service.py`（删团队级联删 `team_skills`）、`skill_sync_service.py`（双表查）、`skill_version_service.py`（团队表）、`file_watcher_service.py`（按 `personal/`、`team/` 分流 upsert）。
- API/Schema：`api/skill_store.py`（团队鉴权改「命中团队表」）、`schemas/skill_forge.py`（`NativeSkillItem` 增 `name`）。
- DB 引导：`core/database.py`（`_migrate_add_columns` 去掉 `skill_packages` 段；新表由 `create_all` 直接建出）。
- 前端：`api/skillStore.ts` 的 `NativeSkillItem.name` 为必填自然名；卡片展示、同名判定和本机安装状态按 `name`，API 操作与路由仍按内部 `id`。

## 5. 部署（老数据一键丢弃）

本次为破坏性 schema 变更，且约定丢弃旧数据，无数据迁移脚本。Docker 经 `create_all`（`DB_AUTO_CREATE=true`）建新表：

```bash
git pull
docker compose down -v          # 丢弃 mysql-data + skill-store 卷（清空全部旧数据）
docker compose up -d --build    # 重建空库（create_all 建 personal_skills/team_skills）+ 空 store；种子用户 DAIL/DAIL2 自动重建
```

前端：`cd frontend && npm run build` 重建 dist 后重启桌面壳。

> Alembic 基线仍含旧 `skill_packages`，但 Docker 部署走 `create_all` 而非 `alembic upgrade`，且本次丢弃旧库，故未改 Alembic（后续如启用 Alembic 管理需补一版新基线）。

## 6. 验证

- 后端回归测试覆盖：跨用户同名创建得到不同 UUID/对象前缀、同用户重名拒绝、`(owner_id, name)` 唯一约束、个人权限隔离、COS 列举失败不裁剪 DB。
- `python -m compileall app` 与前端 `npm run build` 通过。
- 上线后仍需真实服务器 + 本地代理烟测：两个账号创建同名 Skill、导入覆盖、复制到团队、按自然名部署、推送/拉取和版本回滚。
