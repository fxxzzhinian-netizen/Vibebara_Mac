#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Vibebara Desktop macOS arm64 build

Usage:
  ./build-desktop-mac.sh
  ./build-desktop-mac.sh --quick
  ./build-desktop-mac.sh --build-only
  ./build-desktop-mac.sh --no-be
  ./build-desktop-mac.sh --dev
  ./build-desktop-mac.sh --pack
  ./build-desktop-mac.sh --unsigned-dist [--prepare-update | --publish]
  ./build-desktop-mac.sh --dist [--publish]
  ./build-desktop-mac.sh --unsigned-dist --prepare-update --version 1.5.0
  ./build-desktop-mac.sh --force-install
EOF
}

quick=0
build_only=0
no_be=0
dev=0
pack=0
unsigned_dist=0
dist=0
publish=0
prepare_update=0
force_install=0
build_version=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) quick=1 ;;
    --build-only) build_only=1 ;;
    --no-be) no_be=1 ;;
    --dev) dev=1 ;;
    --pack) pack=1 ;;
    --unsigned-dist) unsigned_dist=1 ;;
    --dist) dist=1 ;;
    --publish) publish=1 ;;
    --prepare-update) prepare_update=1 ;;
    --force-install) force_install=1 ;;
    --version)
      [[ $# -ge 2 ]] || {
        echo "--version requires major.minor.patch." >&2
        exit 2
      }
      build_version="$2"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

package_modes=$((pack + unsigned_dist + dist))
if [[ "$package_modes" -gt 1 ]]; then
  echo "Choose only one packaging mode: --pack, --unsigned-dist, or --dist." >&2
  exit 2
fi
if [[ "$publish" -eq 1 && "$dist" -eq 0 && "$unsigned_dist" -eq 0 ]]; then
  echo "--publish requires --dist or --unsigned-dist." >&2
  exit 2
fi
if [[ "$prepare_update" -eq 1 && "$unsigned_dist" -eq 0 ]]; then
  echo "--prepare-update requires --unsigned-dist." >&2
  exit 2
fi
if [[ "$prepare_update" -eq 1 && "$publish" -eq 1 ]]; then
  echo "Choose only one: --prepare-update or --publish." >&2
  exit 2
fi
if [[ -n "$build_version" && "$package_modes" -eq 0 ]]; then
  echo "--version requires --pack, --unsigned-dist, or --dist." >&2
  exit 2
fi
if [[ -n "$build_version" && ! "$build_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "--version must use major.minor.patch, for example 1.5.0." >&2
  exit 2
fi
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS packages must be built on macOS." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "The first macOS release supports Apple Silicon arm64 only." >&2
  exit 1
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_dir="$root/backend"
frontend_dir="$root/frontend"
local_core_dir="$root/local-core"
cli_dir="$root/cli"
agent_dir="$root/local-agent"
desktop_dir="$root/desktop"
release_dir="$desktop_dir/release-mac"
venv_python="$backend_dir/.venv/bin/python"

default_cloud_api_base="http://162.14.106.190:8000/api/v1"
default_cloud_ws_base="ws://162.14.106.190:8000"

section() {
  printf '\n========================================================\n'
  printf '  %s\n' "$1"
  printf '========================================================\n'
}

run_in() {
  local dir="$1"
  shift
  (cd "$dir" && "$@")
}

node_version_ok() {
  node -e "const [a,b]=process.versions.node.split('.').map(Number); process.exit(a>22 || (a===22 && b>=12) ? 0 : 1)"
}

build_node() {
  local dir="$1"
  local name="$2"
  printf '  [%s] ' "$name"
  if [[ "$force_install" -eq 1 || ! -d "$dir/node_modules" ]]; then
    printf 'install -> '
    run_in "$dir" npm install --loglevel=error
  fi
  printf 'build -> '
  run_in "$dir" npm run build
  printf 'OK\n'
}

build_cli() {
  build_node "$cli_dir" "cli"
  printf '  [cli-sea] bundle + darwin-arm64 SEA -> '
  run_in "$cli_dir" npm run sea:mac
  printf 'OK\n'
}

ensure_mac_icon() {
  local source_png="$frontend_dir/src/img/logo_icon.png"
  local target_icns="$desktop_dir/build/icon.icns"
  [[ -f "$target_icns" ]] && return
  [[ -f "$source_png" ]] || {
    echo "Missing icon source: $source_png" >&2
    exit 1
  }
  local iconset="$desktop_dir/build/icon.iconset"
  local scaled_png="$desktop_dir/build/.icon-scaled.png"
  local square_png="$desktop_dir/build/.icon-square.png"
  rm -rf "$iconset"
  mkdir -p "$iconset"
  # 先按比例缩小，再补成透明方形画布，避免直接拉伸现有长方形 logo。
  sips -Z 900 "$source_png" --out "$scaled_png" >/dev/null
  sips --padToHeightWidth 1024 1024 "$scaled_png" --out "$square_png" >/dev/null
  sips -z 16 16 "$square_png" --out "$iconset/icon_16x16.png" >/dev/null
  sips -z 32 32 "$square_png" --out "$iconset/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$square_png" --out "$iconset/icon_32x32.png" >/dev/null
  sips -z 64 64 "$square_png" --out "$iconset/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$square_png" --out "$iconset/icon_128x128.png" >/dev/null
  sips -z 256 256 "$square_png" --out "$iconset/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$square_png" --out "$iconset/icon_256x256.png" >/dev/null
  sips -z 512 512 "$square_png" --out "$iconset/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$square_png" --out "$iconset/icon_512x512.png" >/dev/null
  cp "$square_png" "$iconset/icon_512x512@2x.png"
  iconutil -c icns "$iconset" -o "$target_icns"
  rm -rf "$iconset" "$scaled_png" "$square_png"
  echo "  [icon] generated $target_icns"
}

set_desktop_build_version() {
  local pkg_path="$desktop_dir/package.json"
  local lock_path="$desktop_dir/package-lock.json"
  local current suggested input version
  current="$(node -e "console.log(require(process.argv[1]).version)" "$pkg_path")"
  suggested="$current"
  if [[ "$current" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    suggested="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.$((BASH_REMATCH[3] + 1))"
  fi
  version="$build_version"
  if [[ -z "$version" ]]; then
    while [[ -z "$version" ]]; do
      read -r -p "  Package version (current $current, Enter for $suggested): " input
      input="${input:-$suggested}"
      if [[ "$input" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        version="$input"
      else
        echo "Use major.minor.patch, for example 1.5.0" >&2
      fi
    done
  fi
  node - "$pkg_path" "$lock_path" "$version" <<'NODE'
const fs = require("node:fs");
const [pkgPath, lockPath, version] = process.argv.slice(2);
for (const file of [pkgPath, lockPath]) {
  if (!fs.existsSync(file)) continue;
  const json = JSON.parse(fs.readFileSync(file, "utf8"));
  json.version = version;
  if (json.packages?.[""]) json.packages[""].version = version;
  fs.writeFileSync(file, `${JSON.stringify(json, null, 2)}\n`);
}
NODE
  echo "  [package] version -> $version"
}

ensure_backend_venv() {
  if [[ ! -x "$venv_python" ]]; then
    local py="python3"
    command -v python3 >/dev/null 2>&1 || py="python"
    "$py" -m venv "$backend_dir/.venv"
    "$venv_python" -m pip install -r "$backend_dir/requirements.txt" -q
  fi
}

start_backend() {
  ensure_backend_venv
  (
    cd "$backend_dir"
    export DEPLOYMENT_MODE=cloud
    export ALLOW_ORIGIN_REGEX='^null$'
    export SEED_USERS_ENABLED=false
    export INVITE_CODE_REQUIRED=false
    export ADMIN_USERNAMES='[]'
    export MARKET_SEED_REVIEWERS='[]'
    "$venv_python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ) &
  echo "  [backend] started on :8000, pid=$!"
  sleep 2
}

start_frontend_dev() {
  (cd "$frontend_dir" && npm run dev) &
  echo "  [frontend] Vite started on :5173, pid=$!"
  sleep 3
}

smoke_packaged_cli() {
  local app_path
  app_path="$(find "$release_dir" -maxdepth 3 -type d -name "Vibebara.app" -print -quit)"
  [[ -n "$app_path" ]] || {
    echo "Packaged Vibebara.app not found under $release_dir" >&2
    exit 1
  }
  run_in "$desktop_dir" npm run smoke:cli -- "$app_path"
}

publish_update() {
  local args=("--release-dir" "$release_dir")
  [[ "$unsigned_dist" -eq 0 ]] || args+=("--allow-unsigned")
  "$desktop_dir/scripts/publish-update-cos.sh" "${args[@]}"
}

section "Vibebara Desktop macOS arm64"
command -v node >/dev/null 2>&1 || {
  echo "Node.js 22.12 or newer is required on the release Mac." >&2
  exit 1
}
node_version_ok || {
  echo "Node.js 22.12 or newer is required; current $(node --version)." >&2
  exit 1
}
echo "  Node $(node --version) | npm $(npm --version)"

if [[ "$quick" -eq 0 ]]; then
  section "Build desktop components"
  build_node "$local_core_dir" "local-core"
  build_cli
  build_node "$agent_dir" "local-agent"
  if [[ "$dev" -eq 0 ]]; then
    build_node "$frontend_dir" "frontend"
  fi
  build_node "$desktop_dir" "desktop"
else
  missing=()
  [[ -f "$local_core_dir/dist/index.js" ]] || missing+=("local-core")
  [[ -f "$cli_dir/release/vibebara" ]] || missing+=("cli")
  [[ -f "$agent_dir/dist/index.js" ]] || missing+=("local-agent")
  [[ "$dev" -eq 1 || -f "$frontend_dir/dist/index.html" ]] || missing+=("frontend")
  [[ -f "$desktop_dir/dist-electron/main/index.js" ]] || missing+=("desktop")
  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "  [quick] missing artifacts: ${missing[*]}; rebuilding all"
    build_node "$local_core_dir" "local-core"
    build_cli
    build_node "$agent_dir" "local-agent"
    [[ "$dev" -eq 1 ]] || build_node "$frontend_dir" "frontend"
    build_node "$desktop_dir" "desktop"
  fi
fi

if [[ "$package_modes" -gt 0 ]]; then
  if [[ -z "${CI:-}" && -z "${ELECTRON_BUILDER_BINARIES_MIRROR:-}" ]]; then
    export ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"
  fi
  chmod +x "$desktop_dir/scripts/install-cli.sh" \
    "$desktop_dir/scripts/publish-update-cos.sh"
  ensure_mac_icon
  set_desktop_build_version
fi

if [[ "$dist" -eq 1 ]]; then
  section "Package signed and notarized macOS arm64 release"
  export CSC_LINK="${CSC_LINK:-${MAC_CSC_LINK:-}}"
  export CSC_KEY_PASSWORD="${CSC_KEY_PASSWORD:-${MAC_CSC_KEY_PASSWORD:-}}"
  run_in "$desktop_dir" npm run dist:mac
  smoke_packaged_cli
  [[ "$publish" -eq 0 ]] || publish_update
  echo "  [OK] Output: $release_dir"
  exit 0
fi

if [[ "$unsigned_dist" -eq 1 ]]; then
  section "Package unsigned macOS arm64 DMG/ZIP"
  export CSC_IDENTITY_AUTO_DISCOVERY=false
  if [[ "$publish" -eq 1 || "$prepare_update" -eq 1 ]]; then
    run_in "$desktop_dir" npm run dist:mac:update-unsigned
  else
    run_in "$desktop_dir" npm run dist:mac:unsigned
  fi
  smoke_packaged_cli
  [[ "$publish" -eq 0 ]] || publish_update
  echo "  [OK] Output: $release_dir"
  exit 0
fi

if [[ "$pack" -eq 1 ]]; then
  section "Package unpacked macOS arm64 app"
  run_in "$desktop_dir" npm run pack:mac
  smoke_packaged_cli
  echo "  [OK] Output: $release_dir"
  exit 0
fi

if [[ "$build_only" -eq 1 ]]; then
  echo "  [OK] Build complete"
  exit 0
fi

section "Start services"
if [[ "$no_be" -eq 0 ]]; then
  start_backend
else
  export VIBEBARA_CLOUD_API_BASE="${VIBEBARA_CLOUD_API_BASE:-$default_cloud_api_base}"
  export VIBEBARA_CLOUD_WS_BASE="${VIBEBARA_CLOUD_WS_BASE:-$default_cloud_ws_base}"
fi
if [[ "$dev" -eq 1 ]]; then
  export VIBEBARA_DEV_SERVER_URL="http://localhost:5173"
  start_frontend_dev
fi
run_in "$desktop_dir" npm start
