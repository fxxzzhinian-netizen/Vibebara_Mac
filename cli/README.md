# Vibebara CLI

Headless Skill collaboration commands for merge, push, pull, and deployment
status.

## Installation

The Windows desktop installer includes a signed `vibebara.exe`, registers its
directory in the current user's PATH, and does not require Node.js on the user
machine. Open a **new terminal** after installation or upgrade:

```powershell
vibebara --version
```

Repository development and the optional npm package require Node.js 22.12 or
newer. From a checkout, build `local-core` before the CLI:

```powershell
cd local-core
npm install
npm run build
cd ..\cli
npm install
npm run build
npm link
```

## Authorization

Preferred desktop flow:

1. Sign in to Vibebara Desktop.
2. Open the user menu and choose **为 CLI 授权**.
3. The desktop app writes `~/.vibebara/config.json`.
4. Open a new terminal and run `vibebara whoami`.

Manual/web/CI flow:

```bash
vibebara login --api-key vhk_xxx --cloud http://<ip>:<port>/api/v1
```

CI may set `VIBEBARA_API_KEY` and `VIBEBARA_CLOUD_API_BASE` instead of writing
the config file.

## Commands

```bash
vibebara whoami
vibebara status [--project <id>] [--json]

vibebara merge [skill] [--deployment <id>] [--project <id>] [--preview]
vibebara --yes merge [skill]
vibebara push [skill] [--create-version] [--version-label <label>]
vibebara pull [skill] [--overwrite]
```

When no deployment or skill is supplied, the CLI walks upward from `cwd` and
uses the nearest tool marker (`.{tool}/skills` → `.{tool}` → `.git`) to locate
the deployment. The MVP is same-machine only: the stored install path must
exist locally and contain the expected `SKILL.md`.

## Exit codes

- `0`: success
- `1`: general/cloud error
- `2`: invalid usage or ambiguous deployment
- `3`: optimistic-lock/push/pull conflict
- `4`: merge requires manual handling
- `5`: missing or invalid credentials
- `6`: missing/invalid local deployment path

Use `--json` for Agent and CI integration. Secrets are never included in normal
output; `whoami` only returns a masked key prefix.
