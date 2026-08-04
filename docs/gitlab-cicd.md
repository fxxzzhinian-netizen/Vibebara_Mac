# Vibebara GitLab CI/CD 运维手册

> 面向对象：负责 GitLab Runner、生产服务器和后端发布的运维人员。  
> GitLab 项目：`dailtech/vibebara/cowork-deploy`  
> 当前生产形态：仅后端与 MySQL 部署在 Linux 服务器；Windows 安装包由开发人员在自己的电脑打包，不属于本手册范围。

## 1. 运维需要交付什么

运维需要完成：

1. 为 GitLab 项目准备可运行 Linux Docker Job 的 Runner；
2. 配置生产服务器 SSH 免密部署账号；
3. 在 GitLab 配置生产部署变量；
4. 保证服务器部署目录和 `.env` 已初始化；
5. 在 `main` Pipeline 测试通过后，执行生产部署 Job；
6. 监控健康检查、备份和回滚结果。

运维不需要：

- 在服务器构建 Electron/Windows 安装包；
- 配置 Windows Runner、代码签名证书或 Electron 更新源；
- 将桌面端安装包上传到后端服务器；
- 在生产服务器执行前端或桌面端开发命令。

## 2. 已配置的 CI/CD 流程

仓库根目录 `.gitlab-ci.yml` 定义三个 Stage：

```text
test → package → deploy
```

执行规则：

- 功能分支和 Merge Request 执行 `test`；
- `main` 测试全部成功后，自动执行 `package-backend`；
- `package-backend` 生成与 Commit SHA 绑定的后端发布包，GitLab 保留 14 天；
- `deploy-backend-production` 只出现在 `main` Pipeline；
- 生产部署需要运维在 GitLab 手动点击执行；
- 同一时间只允许一个生产部署 Job 运行。

生产部署使用人工确认是为了防止代码合入后立即影响线上。点击部署以后，传输、备份、构建、启动、健康检查和失败回退均自动完成。

### 2.1 CI 检查范围

`test` Stage 会检查：

- Python 后端测试；
- frontend 构建；
- backend/skill-forge 构建；
- desktop TypeScript 构建；
- local-core 的 Lint、测试与构建；
- local-agent 的 Lint、测试与构建；
- CLI 的 Lint、测试、构建和分发验证。
- Linux 环境下部署脚本的 Bash 语法。

任意测试 Job 失败时，不会生成生产发布包，也不能执行 CD。

### 2.2 CD 实际动作

`deploy-backend-production` 会：

1. 校验 SSH 地址、端口、私钥、Host Key 和部署目录；
2. 把当前 Pipeline 的后端发布包传到服务器；
3. 校验发布包内 Commit SHA；
4. 校验 Docker Compose 配置；
5. 自动备份 MySQL；
6. 自动备份当前后端源码；
7. 替换 `backend/` 和 `docker-compose.yml`；
8. 在服务器执行 `docker compose build backend`；
9. 执行 `docker compose up -d --remove-orphans`；
10. 最多等待约 150 秒检查 `/health`；
11. 失败时恢复上一版后端并重新启动。

CD 不会覆盖：

- 服务器根目录 `.env`；
- MySQL Docker Volume；
- COS 中的 Skill 数据；
- 服务器 `.deploy/backups/` 中的备份。

## 3. 一次性配置 GitLab Runner

Runner 必须满足：

- Linux；
- Docker Executor，或其他能够运行 Docker Image 的 Executor；
- 可以拉取 `python:3.12`、`node:22`、`alpine:3.20`；
- 可以访问 `http://162.14.122.9`；
- 可以访问 npm、pip 和 Docker 镜像源；
- 可以通过 SSH 访问生产服务器；
- Runner 时间与 NTP 同步。

建议：

- Runner 使用专用机器或专用虚拟机；
- 不在生产后端服务器直接运行共享 Runner；
- 限制 Runner 仅供本项目使用；
- 国内网络配置 Docker Hub Mirror；
- 定期清理 Runner 的 Docker Cache 和磁盘。

注册完成后，在 GitLab 项目：

```text
Settings → CI/CD → Runners
```

确认 Runner 状态为 Online，并能够执行无 Tag Job。

## 4. 一次性初始化生产服务器

### 4.1 基础要求

生产服务器需要：

- Ubuntu 或兼容 Linux；
- Docker 20+；
- Docker Compose V2；
- `bash`、`tar`、`curl`、`gzip`；
- 能访问 Docker、npm 和 pip 所需下载源；
- 安全组按现有测试环境放行后端端口。

检查命令：

```bash
docker version
docker compose version
bash --version
tar --version
curl --version
gzip --version
```

### 4.2 创建部署账号

示例使用 `vibebara-deploy`：

```bash
sudo useradd --create-home --shell /bin/bash vibebara-deploy
sudo usermod -aG docker vibebara-deploy
sudo install -d -m 700 -o vibebara-deploy -g vibebara-deploy \
  /home/vibebara-deploy/.ssh
```

将 CI 部署私钥对应的公钥写入：

```text
/home/vibebara-deploy/.ssh/authorized_keys
```

设置权限：

```bash
sudo chown vibebara-deploy:vibebara-deploy \
  /home/vibebara-deploy/.ssh/authorized_keys
sudo chmod 600 /home/vibebara-deploy/.ssh/authorized_keys
```

部署账号需要：

- 能读写部署目录；
- 能执行 Docker；
- 不需要 root SSH 登录；
- 不需要把 sudo 密码交给 GitLab。

加入 Docker Group 后需要重新登录，再验证：

```bash
sudo -iu vibebara-deploy
docker ps
```

### 4.3 确认部署目录

CI 默认目录：

```text
/opt/vibebara/cowork-deploy
```

如果现有后端不在该目录，必须在 GitLab 设置实际 `DEPLOY_PATH`，不要为了匹配默认值移动正在运行的数据卷。

目录必须至少包含：

```text
/opt/vibebara/cowork-deploy/
├── .env
├── backend/
└── docker-compose.yml
```

授权示例：

```bash
sudo chown -R vibebara-deploy:vibebara-deploy \
  /opt/vibebara/cowork-deploy
sudo -u vibebara-deploy mkdir -p \
  /opt/vibebara/cowork-deploy/.deploy/incoming
sudo chmod 600 /opt/vibebara/cowork-deploy/.env
```

CD 启用后，不再在部署目录执行 `git pull`。服务器接收 GitLab Pipeline 生成的固定版本发布包，避免服务器保存 GitLab 账号密码。

### 4.4 检查服务器 `.env`

`.env` 由运维在服务器本地维护，不提交 GitLab。至少确认：

```dotenv
JWT_SECRET=<高熵随机值>
DB_USER=cowork
DB_PASSWORD=<数据库用户密码>
MYSQL_ROOT_PASSWORD=<MySQL root 密码>

STORAGE_BACKEND=cos
COS_SECRET_ID=<腾讯云 SecretId>
COS_SECRET_KEY=<腾讯云 SecretKey>
COS_BUCKET=vibebara-1327732770
COS_REGION=ap-chengdu

ALLOWED_ORIGINS=["null"]
ADMIN_USERNAMES=["管理员用户名"]
MARKET_SEED_REVIEWERS=[]
LLM_API_KEY=<按需配置>
```

安全要求：

- `JWT_SECRET` 使用随机生成的高熵值；
- 不使用 Compose 中的示例数据库默认密码；
- `SEED_USERS_ENABLED` 保持为 `false`；
- `ALLOW_ORIGIN_REGEX` 不设置为 `.*`；
- COS、LLM、数据库凭据只保存在服务器 `.env`；
- `.env` 权限为 `600`；
- 当前公网 HTTP/WS 仅适合受控测试，正式发布前应配置 HTTPS/WSS。

初始化检查：

```bash
cd /opt/vibebara/cowork-deploy
docker compose --env-file .env config -q
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

如果使用了其他部署目录，将命令中的路径替换为实际值。

## 5. 一次性配置 GitLab CD 变量

进入：

```text
GitLab 项目 → Settings → CI/CD → Variables
```

新增以下变量。

### 5.1 必填变量

`DEPLOY_HOST`

- 值：生产服务器 IP 或域名；
- 当前生产服务器填写 `162.14.106.190`；
- 设置为 Protected；
- Environment scope 设置为 `production` 或 All。

`DEPLOY_USER`

- 值：部署账号，例如 `vibebara-deploy`；
- 设置为 Protected。

`DEPLOY_SSH_PRIVATE_KEY`

- 类型：File；
- 值：部署专用 SSH 私钥完整内容；
- 设置为 Protected；
- 不使用个人 SSH 私钥；
- 公钥只授予该生产服务器部署账号。

`DEPLOY_KNOWN_HOSTS`

- 类型：File；
- 值：生产服务器 SSH Host Key；
- 设置为 Protected；
- 必须先核对服务器指纹，不能关闭 Host Key 校验。

从可信运维终端获取候选内容：

```bash
ssh-keyscan -p 22 -H 162.14.106.190
```

必须与服务器本机显示的指纹进行核对：

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

### 5.2 可选覆盖变量

`DEPLOY_PORT`

- 默认：`22`；
- SSH 使用其他端口时设置。

`DEPLOY_PATH`

- 默认：`/opt/vibebara/cowork-deploy`；
- 必须填写现有后端的真实绝对路径；
- 路径不能包含空格和单引号。

`DEPLOY_HEALTHCHECK_URL`

- 默认：`http://127.0.0.1:8000/health`；
- 必须是服务器本机可访问的 HTTP/HTTPS 地址；
- 不要填写只能从公网访问、服务器本机无法访问的地址。

所有生产变量都应设为 Protected。SSH 私钥和 Host Key 推荐使用 File 类型，避免多行内容被 Shell 错误解析。

## 6. 配置 GitLab 生产保护

运维或 GitLab 管理员需要确认：

### 6.1 保护 main

```text
Settings → Repository → Protected branches
```

- `main` 禁止普通开发者直接 Push；
- 仅允许 Maintainer 合并；
- 不允许 Force Push；
- Merge Request 必须 Pipeline 成功。

### 6.2 保护 production

如果当前 GitLab 版本支持 Protected Environments：

```text
Settings → CI/CD → Protected environments
```

将 `production` 设置为仅 Maintainer 或指定运维人员可以部署。

如果版本不支持，至少保证：

- `main` 为受保护分支；
- 部署变量全部为 Protected；
- 只有运维或 Maintainer 能点击生产部署 Job。

## 7. 首次验证 CI/CD

`.gitlab-ci.yml`、`ops/deploy-backend.sh` 和本手册合入 `main` 后执行。

### 7.1 验证 CI

打开：

```text
GitLab 项目 → Build → Pipelines
```

确认 `main` Pipeline：

- Backend 测试成功；
- Node Matrix 全部成功；
- local-core/local-agent/CLI 测试成功；
- `package-backend` 成功；
- Artifact 中存在 `backend-<完整 Commit SHA>.tgz`；
- `deploy-backend-production` 显示为等待手动执行。

### 7.2 首次执行 CD

执行前确认：

```bash
cd /opt/vibebara/cowork-deploy
docker compose ps
curl --fail http://127.0.0.1:8000/health
df -h
```

然后在 GitLab `main` Pipeline 中点击：

```text
deploy-backend-production → Run
```

成功日志应包含：

```text
[deploy] 校验发布包
[deploy] 备份数据库
[deploy] 备份当前后端源码
[deploy] 构建并启动后端
[deploy] 发布成功
```

发布后服务器检查：

```bash
cd /opt/vibebara/cowork-deploy
docker compose ps
docker compose logs --tail=100 backend
curl --fail http://127.0.0.1:8000/health
cat .deploy/current-sha
cat .deploy/deployed-at
```

`.deploy/current-sha` 必须与 GitLab 部署 Job 对应的 Commit SHA 一致。

## 8. 日常发布操作

每次后端发布只执行以下步骤：

1. 打开 GitLab `main` 最新 Pipeline；
2. 确认所有测试 Job 为绿色；
3. 确认 `package-backend` 成功；
4. 核对 Pipeline Commit SHA 是计划发布的版本；
5. 点击 `deploy-backend-production`；
6. 等待 Job 显示 Passed；
7. 检查 `/health`、后端日志和核心接口；
8. 在发布记录中登记 Commit SHA、操作人和结果。

禁止：

- 在测试失败时绕过 Pipeline 手工部署；
- 在服务器部署目录继续执行 `git pull`；
- 手工删除 `.deploy/backups` 中的最新备份；
- 执行 `docker compose down -v`；
- 把 `.env`、SSH 私钥或数据库备份上传为 GitLab 普通 Artifact。

## 9. 备份与回滚

### 9.1 自动备份位置

每次 CD 在替换后端前自动生成：

```text
<DEPLOY_PATH>/.deploy/backups/db-<时间>-<上一版本>.sql.gz
<DEPLOY_PATH>/.deploy/backups/source-<时间>-<上一版本>.tgz
```

数据库备份失败时，部署立即停止。

运维需要：

- 监控部署磁盘空间；
- 将备份同步到受控备份存储；
- 按公司保留策略清理历史文件；
- 定期抽样验证 SQL 备份可恢复。

### 9.2 自动回滚

以下情况会触发脚本自动恢复上一版后端：

- Docker Image 构建失败；
- Docker Compose 启动失败；
- 150 秒内健康检查未通过。

自动回滚只恢复后端源码和 Compose 文件，不自动恢复数据库。数据库恢复属于高风险操作，必须经过人工确认。

### 9.3 推荐的人工回滚

优先在 GitLab 找到目标旧版本的 `main` Pipeline，重新执行该 Pipeline 的 `deploy-backend-production`。Artifact 默认保留 14 天。

如果旧 Artifact 已过期，使用服务器源码备份：

```bash
cd /opt/vibebara/cowork-deploy
docker compose ps
ls -lt .deploy/backups/source-*.tgz

mkdir -p /tmp/vibebara-rollback
tar -xzf .deploy/backups/source-<目标备份>.tgz \
  -C /tmp/vibebara-rollback

mv backend ".deploy/failed/backend-$(date +%Y%m%d-%H%M%S)"
mv /tmp/vibebara-rollback/backend ./backend
cp /tmp/vibebara-rollback/docker-compose.yml ./docker-compose.yml

docker compose --env-file .env up -d --build --remove-orphans
curl --fail http://127.0.0.1:8000/health
```

数据库仅在确认新版本已写入不兼容数据、且业务负责人批准后恢复。恢复前先额外备份当前数据库。

## 10. 常见故障

### Pipeline Pending

- 检查 Runner 是否 Online；
- 检查 Runner 是否允许无 Tag Job；
- 检查 Runner 能否拉取基础镜像；
- 检查 Runner 磁盘空间。

### `package-backend` 没有出现

- 该 Job 仅在默认分支执行；
- 确认 Pipeline 分支为 `main`；
- 确认 Test Stage 已成功。

### 部署提示缺少 GitLab 变量

- 检查变量名拼写；
- 检查变量是否 Protected；
- 检查 Pipeline 是否来自受保护的 `main`；
- 检查 Environment Scope 是否覆盖 `production`。

### SSH Permission denied

- 检查私钥是否为 File 类型且内容完整；
- 检查公钥是否写入部署账号 `authorized_keys`；
- 检查 `.ssh` 为 `700`、`authorized_keys` 为 `600`；
- 检查 `DEPLOY_USER` 和 `DEPLOY_PORT`；
- 不要改成密码登录。

### Host key verification failed

- 服务器重装或 SSH Host Key 变更后重新核对指纹；
- 更新 `DEPLOY_KNOWN_HOSTS`；
- 不设置 `StrictHostKeyChecking=no`。

### 提示缺少 `.env`

- 检查 `DEPLOY_PATH` 是否为现有部署目录；
- 检查 `.env` 是否位于 `docker-compose.yml` 同级；
- 不把 `.env` 放入 GitLab Artifact。

### Docker Permission denied

```bash
sudo usermod -aG docker vibebara-deploy
```

重新登录部署账号后执行：

```bash
docker ps
```

### 健康检查失败

```bash
cd /opt/vibebara/cowork-deploy
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=100 mysql
curl -v http://127.0.0.1:8000/health
```

重点检查：

- MySQL 是否 healthy；
- `.env` 中数据库和 COS 配置；
- Docker Build 下载源；
- 8000 端口是否被占用；
- 服务器内存和磁盘是否充足。

## 11. 运维验收清单

一次性验收：

- Linux Runner Online；
- `main` 已保护；
- `production` 部署权限已限制；
- 生产变量全部配置；
- SSH Host Key 已核验；
- 部署账号可以执行 Docker；
- 部署目录和 `.env` 权限正确；
- 首次 CI 全绿；
- 首次 CD 成功；
- MySQL 备份文件已生成；
- Commit SHA 与 GitLab 一致；
- 自动回滚已在测试环境演练。

每次发布验收：

- 发布的是 `main` 目标 Commit；
- Pipeline 全绿；
- CD Job Passed；
- `/health` 成功；
- Backend/MySQL 容器正常；
- 后端日志无持续异常；
- 数据库和源码备份存在；
- 发布记录已登记。
