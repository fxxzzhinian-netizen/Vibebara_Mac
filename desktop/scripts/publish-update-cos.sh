#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release_dir="$script_dir/../release-mac"
prefix="${VIBEBARA_COS_UPDATE_PREFIX:-desktop/macos}"
allow_unsigned=0
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-dir) release_dir="$2"; shift ;;
    --prefix) prefix="$2"; shift ;;
    --allow-unsigned) allow_unsigned=1 ;;
    --dry-run) dry_run=1 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

require_value() {
  local value="$1"
  local name="$2"
  if [[ -z "$value" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
}

release_dir="$(cd "$release_dir" && pwd)"
latest="$release_dir/latest-mac.yml"
[[ -f "$latest" ]] || { echo "Missing $latest" >&2; exit 1; }

zip_name="$(awk '/^path:[[:space:]]*/ { sub(/^path:[[:space:]]*/, ""); gsub(/^["'\'']|["'\'']$/, ""); print; exit }' "$latest")"
if [[ ! "$zip_name" =~ ^VBB-mac-([0-9]+\.[0-9]+\.[0-9]+)-arm64\.zip$ ]]; then
  echo "Unexpected arm64 update path in latest-mac.yml: $zip_name" >&2
  exit 1
fi
version="${BASH_REMATCH[1]}"
dmg_name="VBB-mac-${version}-arm64.dmg"
zip_path="$release_dir/$zip_name"
dmg_path="$release_dir/$dmg_name"
[[ -f "$zip_path" ]] || { echo "Missing $zip_path" >&2; exit 1; }
[[ -f "$dmg_path" ]] || { echo "Missing $dmg_path" >&2; exit 1; }

expected_sha="$(awk '/^sha512:[[:space:]]*/ { sub(/^sha512:[[:space:]]*/, ""); gsub(/^["'\'']|["'\'']$/, ""); print; exit }' "$latest")"
if [[ -n "$expected_sha" ]]; then
  actual_sha="$(openssl dgst -sha512 -binary "$zip_path" | openssl base64 -A)"
  [[ "$actual_sha" == "$expected_sha" ]] || {
    echo "ZIP SHA-512 does not match latest-mac.yml" >&2
    exit 1
  }
fi

app_path="$release_dir/mac-arm64/Vibebara.app"
if [[ "$allow_unsigned" -eq 0 ]]; then
  [[ -d "$app_path" ]] || { echo "Missing signed app: $app_path" >&2; exit 1; }
  codesign --verify --deep --strict --verbose=2 "$app_path"
  xcrun stapler validate "$app_path"
  spctl --assess --type execute --verbose=2 "$app_path"
  spctl --assess --type open --context context:primary-signature \
    --verbose=2 "$dmg_path"
else
  echo "[signature] WARNING: publishing unsigned macOS artifacts" >&2
fi

update_url="${VIBEBARA_UPDATE_URL:-}"
require_value "$update_url" "VIBEBARA_UPDATE_URL"
[[ "$update_url" == https://* ]] || {
  echo "VIBEBARA_UPDATE_URL must use HTTPS" >&2
  exit 1
}

artifacts=("$dmg_path" "$zip_path")
for blockmap in "$dmg_path.blockmap" "$zip_path.blockmap"; do
  [[ -f "$blockmap" ]] && artifacts+=("$blockmap")
done

if [[ "$dry_run" -eq 1 ]]; then
  echo "[dry-run] macOS arm64 release validation completed; no files uploaded."
  exit 0
fi

bucket="${COS_BUCKET:-}"
region="${COS_REGION:-}"
require_value "$bucket" "COS_BUCKET"
require_value "$region" "COS_REGION"
require_value "${COS_SECRET_ID:-}" "COS_SECRET_ID"
require_value "${COS_SECRET_KEY:-}" "COS_SECRET_KEY"
command -v coscli >/dev/null 2>&1 || {
  echo "coscli was not found in PATH" >&2
  exit 1
}

config_path="$(mktemp "${TMPDIR:-/tmp}/vibebara-cos.XXXXXX.yaml")"
remote_latest="$(mktemp "${TMPDIR:-/tmp}/vibebara-latest.XXXXXX.yml")"
cleanup() {
  rm -f "$config_path" "$remote_latest"
}
trap cleanup EXIT

node - "$config_path" <<'NODE'
const fs = require("node:fs");
const out = process.argv[2];
const q = (value) => JSON.stringify(value || "");
fs.writeFileSync(out, [
  "cos:",
  "  base:",
  `    secretid: ${q(process.env.COS_SECRET_ID)}`,
  `    secretkey: ${q(process.env.COS_SECRET_KEY)}`,
  `    sessiontoken: ${q(process.env.COS_SESSION_TOKEN)}`,
  '    protocol: "https"',
  '    disableencryption: "true"',
  "  buckets:",
  `    - name: ${q(process.env.COS_BUCKET)}`,
  '      alias: "vibebara-update"',
  `      region: ${q(process.env.COS_REGION)}`,
  `      endpoint: ${q(`cos.${process.env.COS_REGION}.myqcloud.com`)}`,
  "      ofs: false",
  "",
].join("\n"));
NODE

prefix="${prefix#/}"
prefix="${prefix%/}"
upload() {
  local source="$1"
  local name
  name="$(basename "$source")"
  echo "[upload] $name -> cos://$bucket/$prefix/$name"
  coscli cp "$source" "cos://$bucket/$prefix/$name" \
    --acl public-read --disable-log=true -c "$config_path"
}

# 版本产物全部成功后，最后更新 latest-mac.yml 指针。
for artifact in "${artifacts[@]}"; do upload "$artifact"; done
upload "$latest"

for artifact in "${artifacts[@]}" "$latest"; do
  name="$(basename "$artifact")"
  curl --fail --silent --show-error --head \
    "${update_url%/}/$name" >/dev/null
done
curl --fail --silent --show-error "${update_url%/}/latest-mac.yml" \
  --output "$remote_latest"
[[ "$(shasum -a 256 "$latest" | awk '{print $1}')" == \
   "$(shasum -a 256 "$remote_latest" | awk '{print $1}')" ]] || {
  echo "Remote latest-mac.yml differs from local metadata" >&2
  exit 1
}

echo "[OK] macOS arm64 update published to COS."
