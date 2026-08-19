#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cli_path="$script_dir/vibebara"
target="${1:-$HOME/.local/bin/vibebara}"

if [[ ! -x "$cli_path" ]]; then
  chmod +x "$cli_path"
fi

mkdir -p "$(dirname "$target")"
ln -sfn "$cli_path" "$target"

echo "Vibebara CLI linked: $target -> $cli_path"
if [[ ":${PATH}:" != *":$(dirname "$target"):"* ]]; then
  echo "Add this directory to PATH in ~/.zprofile:"
  echo "  export PATH=\"$(dirname "$target"):\$PATH\""
fi
echo "Open a new terminal, then run: vibebara --version"
