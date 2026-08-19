# Vibebara macOS arm64 构建与发布

macOS 与 Windows 共用同一套业务源码。首个 macOS 版本仅支持 Apple Silicon
（M1/M2/M3/M4，`arm64`），必须在 Apple Silicon Mac 上构建。

## 内部测试包

```bash
git checkout <release-tag>
chmod +x build-desktop-mac.sh
./build-desktop-mac.sh --unsigned-dist
```

产物位于 `desktop/release-mac/`：

- `VBB-mac-<version>-arm64.dmg`：首次安装；
- `VBB-mac-<version>-arm64.zip`：自动更新；
- `latest-mac.yml`：自动更新元数据（仅 update/release 配置生成）；
- `mac-arm64/Vibebara.app`：解包冒烟测试。

未签名、未公证的内测包会触发 Gatekeeper，不得作为正式版本分发。

## GitHub Runner 未签名内测发布

仓库内的 `.github/workflows/desktop-mac.yml` 使用 GitHub 托管的 Apple Silicon
`macos-15` Runner，在手动输入版本号后构建 arm64 DMG/ZIP、更新元数据和
blockmap，并保留 14 天 GitHub Artifact。该工作流不连接 COS，避免海外 Runner
上传中国大陆存储桶时发生跨境网络停滞。

在 GitHub 仓库 `Settings -> Environments` 创建 `macos-cos-release` Environment。
用 Deployment branches 限制为实际发布分支。该 Environment 不需要 COS Secret，
仅需添加以下 Variable：

```text
VIBEBARA_UPDATE_URL                # 公开 HTTPS 地址，末尾建议带 /
```

原先为 GitHub workflow 配置的 `COS_SECRET_ID`、`COS_SECRET_KEY` 和
`COS_SESSION_TOKEN` 可以从 GitHub Environment 删除，凭据只保存在国内发布机。

触发步骤：

1. 打开 GitHub 仓库的 `Actions -> macOS Desktop Release`。
2. 点击 `Run workflow`，选择待发布分支并输入 `major.minor.patch` 版本号。
3. 如 Environment 配置了审批，批准 `macos-cos-release` deployment。
4. Job 完成后下载并解压 `VBB-mac-<version>-arm64` Artifact。

工作流固定使用 Node.js 22.12.0。Artifact 只包含 DMG、ZIP、两个 blockmap 和
`latest-mac.yml`，不包含解包后的 `.app` 目录。

## 从国内 Windows 发布 GitHub Artifact

国内 Windows 发布机安装 COSCLI 1.0.8 或更高版本，将下载的 GitHub Artifact
解压到单独目录，然后在 PowerShell 中设置：

```powershell
$env:COS_BUCKET = "vibebara-exe-1327732770"
$env:COS_REGION = "ap-chengdu"
$env:COS_SECRET_ID = "..."
$env:COS_SECRET_KEY = "..."

# 可先仅校验文件和更新元数据
powershell -ExecutionPolicy Bypass -File `
  .\desktop\scripts\publish-mac-update-cos.ps1 `
  -ReleaseDir "C:\Downloads\VBB-mac-1.4.3-arm64" `
  -Prefix "desktop/macos" `
  -UpdateUrl "https://vibebara-exe-1327732770.cos.ap-chengdu.myqcloud.com/desktop/macos/" `
  -DryRun

# 确认后正式上传
powershell -ExecutionPolicy Bypass -File `
  .\desktop\scripts\publish-mac-update-cos.ps1 `
  -ReleaseDir "C:\Downloads\VBB-mac-1.4.3-arm64" `
  -Prefix "desktop/macos" `
  -UpdateUrl "https://vibebara-exe-1327732770.cos.ap-chengdu.myqcloud.com/desktop/macos/"
```

如使用临时密钥，还需设置 `COS_SESSION_TOKEN`。脚本校验 ZIP SHA-512，先上传
DMG、ZIP 和 blockmap，最后上传 `latest-mac.yml`，并通过公开 HTTPS 地址回读
所有文件。COS 凭据应限制为目标桶/前缀，并允许上传对象和设置 `public-read`
ACL。脚本默认前缀固定为 `desktop/macos`，不会读取 Windows 发布使用的
`VIBEBARA_COS_UPDATE_PREFIX`。

## 正式签名与公证

需要 Developer ID Application 证书，并配置以下任一公证方式：

```bash
export MAC_CSC_LINK="/secure/path/developer-id-application.p12"
export MAC_CSC_KEY_PASSWORD="certificate-password"

# 方式一：App Store Connect API Key
export APPLE_API_KEY="/secure/path/AuthKey_XXXXXXXXXX.p8"
export APPLE_API_KEY_ID="XXXXXXXXXX"
export APPLE_API_ISSUER="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# 也可以使用 APPLE_ID 组合或 APPLE_KEYCHAIN profile 组合。
export VIBEBARA_UPDATE_URL="https://你的更新域名/desktop/macos/"

./build-desktop-mac.sh --dist
```

## 发布到腾讯云 COS

本地发布使用与 Windows 相同的 COS 凭据：

```bash
export COS_BUCKET="your-bucket"
export COS_REGION="ap-chengdu"
export COS_SECRET_ID="..."
export COS_SECRET_KEY="..."
export VIBEBARA_COS_UPDATE_PREFIX="desktop/macos"
export VIBEBARA_UPDATE_URL="https://你的更新域名/desktop/macos/"

# 未签名内测更新
./build-desktop-mac.sh --unsigned-dist --publish

# 已签名并公证的正式更新
./build-desktop-mac.sh --dist --publish
```

发布脚本先上传 DMG、ZIP 和 blockmap，最后上传 `latest-mac.yml`，然后通过
HTTPS 回读验证。Windows 继续使用 `desktop/windows/`，两套更新元数据互不覆盖。
本地执行前需自行安装 `coscli`。

## 安装内置 CLI

应用内置独立 SEA CLI，用户不需要安装 Node.js。DMG 拖拽安装不会自动修改 PATH，
首次使用时执行：

```bash
/Applications/Vibebara.app/Contents/Resources/cli/install-cli.sh
```

脚本默认创建 `~/.local/bin/vibebara`。如该目录不在 PATH，按脚本提示将其加入
`~/.zprofile`，重新打开终端后验证：

```bash
vibebara --version
vibebara whoami
```

## 发布前验收

1. `./build-desktop-mac.sh --unsigned-dist` 能生成 arm64 DMG/ZIP。
2. `.app` 内 local-agent 可启动，CLI 在无 Node PATH 下可运行。
3. Cursor 等 GUI 工具可通过 `open -a` 打开指定项目。
4. 正式包通过 `codesign --verify`、Gatekeeper 与 Apple Notarization。
5. `latest-mac.yml`、ZIP 和 DMG 在 `desktop/macos/` 可匿名读取。
6. 从旧版本自动更新到新版本后，登录态和 CLI 配置保持正常。

未签名版本即使上传和下载成功，也可能在首次启动或自动更新安装阶段被
Gatekeeper 拦截。内部测试可右键应用选择“打开”，或在确认文件来源可信后执行
`xattr -cr /Applications/Vibebara.app`。正式对外分发必须改用签名与公证流程。
