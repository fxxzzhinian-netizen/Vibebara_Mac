#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

DEPLOY_PATH="${1:?缺少部署目录}"
ARCHIVE_PATH="${2:?缺少发布包路径}"
RELEASE_SHA="${3:?缺少发布 Commit SHA}"
HEALTHCHECK_URL="${4:-http://127.0.0.1:8000/health}"

if [[ "$DEPLOY_PATH" == "/" || "$DEPLOY_PATH" != /* ]]; then
  echo "[deploy] DEPLOY_PATH 必须是非根目录的绝对路径" >&2
  exit 2
fi
if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{7,64}$ ]]; then
  echo "[deploy] RELEASE_SHA 格式无效" >&2
  exit 2
fi

for command_name in docker tar curl gzip; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "[deploy] 服务器缺少命令：$command_name" >&2
    exit 2
  fi
done
docker compose version >/dev/null

if [[ ! -f "$ARCHIVE_PATH" ]]; then
  echo "[deploy] 发布包不存在：$ARCHIVE_PATH" >&2
  exit 2
fi
if [[ ! -f "$DEPLOY_PATH/.env" ]]; then
  echo "[deploy] 缺少服务器配置：$DEPLOY_PATH/.env" >&2
  exit 2
fi
if [[ ! -d "$DEPLOY_PATH/backend" || ! -f "$DEPLOY_PATH/docker-compose.yml" ]]; then
  echo "[deploy] 部署目录尚未完成首次初始化" >&2
  exit 2
fi

STATE_DIR="$DEPLOY_PATH/.deploy"
BACKUP_DIR="$STATE_DIR/backups"
PREVIOUS_DIR="$STATE_DIR/previous"
WORK_ROOT="$STATE_DIR/work"
mkdir -p "$BACKUP_DIR" "$WORK_ROOT"

WORK_DIR="$(mktemp -d "$WORK_ROOT/${RELEASE_SHA}.XXXXXX")"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CURRENT_SHA="unknown"
if [[ -f "$STATE_DIR/current-sha" ]]; then
  CURRENT_SHA="$(tr -cd '0-9a-f' < "$STATE_DIR/current-sha" | cut -c1-64)"
elif git -C "$DEPLOY_PATH" rev-parse HEAD >/dev/null 2>&1; then
  CURRENT_SHA="$(git -C "$DEPLOY_PATH" rev-parse HEAD)"
fi

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

echo "[deploy] 校验发布包：$RELEASE_SHA"
tar -xzf "$ARCHIVE_PATH" -C "$WORK_DIR"
if [[ ! -d "$WORK_DIR/backend" || ! -f "$WORK_DIR/docker-compose.yml" ]]; then
  echo "[deploy] 发布包缺少 backend 或 docker-compose.yml" >&2
  exit 2
fi
if [[ "$(tr -d '\r\n' < "$WORK_DIR/RELEASE_SHA")" != "$RELEASE_SHA" ]]; then
  echo "[deploy] 发布包 Commit SHA 与流水线不一致" >&2
  exit 2
fi

(
  cd "$WORK_DIR"
  docker compose --env-file "$DEPLOY_PATH/.env" config -q
)

echo "[deploy] 备份数据库"
DB_BACKUP="$BACKUP_DIR/db-${TIMESTAMP}-${CURRENT_SHA:0:12}.sql.gz"
(
  cd "$DEPLOY_PATH"
  docker compose exec -T mysql sh -c \
    'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "${MYSQL_DATABASE:-cowork}"'
) | gzip -c > "$DB_BACKUP"
test -s "$DB_BACKUP"

echo "[deploy] 备份当前后端源码"
SOURCE_BACKUP="$BACKUP_DIR/source-${TIMESTAMP}-${CURRENT_SHA:0:12}.tgz"
tar \
  --exclude='backend/.env' \
  --exclude='backend/.env.*' \
  --exclude='backend/.venv' \
  --exclude='backend/data' \
  --exclude='backend/.skill-store' \
  --exclude='backend/skill-forge/node_modules' \
  --exclude='backend/skill-forge/dist' \
  -czf "$SOURCE_BACKUP" \
  -C "$DEPLOY_PATH" \
  backend docker-compose.yml

rollback() {
  local exit_code="$1"
  trap - ERR
  set +e
  echo "[deploy] 发布失败，开始恢复上一版后端" >&2
  if [[ -d "$PREVIOUS_DIR/backend" ]]; then
    rm -rf -- "$STATE_DIR/failed"
    mkdir -p "$STATE_DIR/failed"
    if [[ -d "$DEPLOY_PATH/backend" ]]; then
      mv "$DEPLOY_PATH/backend" "$STATE_DIR/failed/backend-$RELEASE_SHA"
    fi
    mv "$PREVIOUS_DIR/backend" "$DEPLOY_PATH/backend"
    cp "$PREVIOUS_DIR/docker-compose.yml" "$DEPLOY_PATH/docker-compose.yml"
    (
      cd "$DEPLOY_PATH"
      docker compose --env-file .env up -d --build --remove-orphans
    )
  else
    echo "[deploy] 尚未切换源码，服务器现有版本保持不变" >&2
  fi
  exit "$exit_code"
}

rm -rf -- "$PREVIOUS_DIR"
mkdir -p "$PREVIOUS_DIR"
trap 'rollback $?' ERR

mv "$DEPLOY_PATH/backend" "$PREVIOUS_DIR/backend"
cp "$DEPLOY_PATH/docker-compose.yml" "$PREVIOUS_DIR/docker-compose.yml"
mv "$WORK_DIR/backend" "$DEPLOY_PATH/backend"
cp "$WORK_DIR/docker-compose.yml" "$DEPLOY_PATH/docker-compose.yml"

echo "[deploy] 构建并启动后端"
(
  cd "$DEPLOY_PATH"
  docker compose --env-file .env build backend
  docker compose --env-file .env up -d --remove-orphans
)

echo "[deploy] 等待健康检查：$HEALTHCHECK_URL"
HEALTHY=0
for ((attempt = 1; attempt <= 30; attempt++)); do
  if curl --fail --silent --show-error --max-time 5 "$HEALTHCHECK_URL" >/dev/null; then
    HEALTHY=1
    break
  fi
  sleep 5
done
if [[ "$HEALTHY" != "1" ]]; then
  (
    cd "$DEPLOY_PATH"
    docker compose logs --tail=100 backend
  )
  false
fi

printf '%s\n' "$RELEASE_SHA" > "$STATE_DIR/current-sha"
printf '%s\n' "$TIMESTAMP" > "$STATE_DIR/deployed-at"
trap - ERR

echo "[deploy] 发布成功：$RELEASE_SHA"
echo "[deploy] 数据库备份：$DB_BACKUP"
echo "[deploy] 源码备份：$SOURCE_BACKUP"
