# Vibebara 使用手册

> 适用版本：Vibebara Desktop 1.4.0，Vibebara CLI 0.1.0  
> 更新日期：2026-08-17  
> 当前发布形态：Windows 桌面客户端

Vibebara 是面向 Cursor、Codex 等 Vibe Coding 工具的 Skill 协作平台。它可以统一管理个人和团队 Skill，把 Skill 部署到本机项目，在成员之间推送、拉取和合并改动。

## 1. 支持范围

当前支持以下工具：

- Cursor
- Codex
- Windsurf
- Claude Code
- Kiro
- Trae
- Qoder
- WorkBuddy

桌面安装包已内置本地代理和 `vibebara` CLI，普通用户不需要安装 Node.js 或 Python。

当前版本优先支持 Windows。macOS 和 Linux 桌面安装包尚未作为正式发布版本提供。

## 2. 下载与安装

### 2.1 下载安装包

Windows 当前版本：

- [VBB-Setup-1.4.0.exe](https://vibebara-exe-1327732770.cos.ap-chengdu.myqcloud.com/desktop/windows/VBB-Setup-1.4.0.exe)

当前安装包未进行 Windows 代码签名。如果 SmartScreen 显示“Windows 已保护你的电脑”，请确认文件来源后选择“更多信息”继续安装。

macOS Apple Silicon（M1/M2/M3/M4）版本使用
`VBB-mac-<version>-arm64.dmg`。正式发布包应具有 Developer ID 签名和 Apple 公证；
未签名内测包可能被 Gatekeeper 拦截。

### 2.2 完成安装

1. 运行 `VBB-Setup-1.4.0.exe`。
2. 按安装向导完成安装。
3. 启动 Vibebara。
4. 如果需要使用 CLI，请关闭并重新打开 PowerShell 或其他终端。

默认安装在当前 Windows 用户目录下，不需要管理员权限：

```text
%LOCALAPPDATA%\Programs\Vibebara
```

macOS 用户打开 DMG 后，将 Vibebara 拖入 Applications。应用内置独立 CLI，
无需安装 Node.js；首次使用 CLI 时执行：

```bash
/Applications/Vibebara.app/Contents/Resources/cli/install-cli.sh
```

### 2.3 验证 CLI

重新打开 PowerShell 或 macOS Terminal，执行：

```text
vibebara --version
```

当前 CLI 版本应显示：

```text
0.1.0
```

如果系统提示找不到命令，请参阅“常见问题”中的 CLI PATH 排查方法。

## 3. 第一次使用

### 3.1 登录或注册

启动 Vibebara 后进入登录页。

已有账号：

1. 输入用户名和密码。
2. 点击“登录”。
3. 按提示完成滑块安全验证。

注册新账号：

1. 点击“没有账号？使用邀请码注册”。
2. 输入用户名、密码、确认密码和邀请码。
3. 完成滑块安全验证。
4. 注册成功后继续首次引导。

同一账号同一时间只能在一台设备登录。在新电脑或新浏览器登录后，旧设备会自动退出，
旧设备签发的 CLI/CI API Key 也会失效。回到旧设备时需要重新输入密码登录，并重新生成 CLI Key。

当前测试版注册需要邀请码，邀请码示例格式为：

```text
VH-XXXX-XXXX
```

### 3.2 完成首次引导

首次登录后需要完成两项设置：

1. 选择主要使用场景：
   - 个人独立开发使用
   - 团队协同开发
2. 选择最常使用的 Vibe Coding 工具。

Vibebara 会检测本机已安装的工具。选择完成后点击“进入工作台”。

## 4. 界面与空间

Vibebara 分为个人空间和团队空间。

### 4.1 个人空间

个人空间包含：

- `SKILL 仓库`：创建、导入、编辑和部署个人 Skill。
- `SKILL 市场`：获取其他用户发布的 Skill，管理自己的市场发布。

### 4.2 团队空间

团队空间包含：

- `团队 SKILL`：团队共享 Skill 仓库。
- `团队项目`：管理项目、关联 Skill 和本地部署实例。
- `团队管理`：管理成员、邀请码、权限和自动热更新设置。
- `SKILL 市场`：从市场获取 Skill。

点击右上角头像，在“空间选择”中切换个人空间或团队。

头像菜单还提供：

- 管理个人资料
- 创建团队
- 加入团队
- 生成或轮换 CLI API Key
- 检查更新
- 退出登录

## 5. 管理个人 Skill

### 5.1 新建或导入 Skill

进入“个人空间 → SKILL 仓库”，点击“新增 Skill”。

支持以下方式：

- 手动新建
- 从链接导入
- 从本地文件夹导入
- 从本机 IDE 工具导入

手动新建时，Skill 名称建议只使用小写字母、数字和连字符，例如：

```text
develop-sop
```

从本地文件夹导入时，目录中必须包含：

```text
SKILL.md
```

### 5.2 编辑 Skill

点击个人 Skill 卡片进入编辑器。

编辑器提供：

- 介绍
- 基本信息
- Skill 指令
- 资源
- 元数据
- 平台结构

编辑后先点击“保存”。页面出现“未保存”时，不要直接关闭窗口。

### 5.3 部署个人 Skill

在 Skill 编辑页点击“部署”，选择目标工具和部署范围。

项目级 Skill 通常写入：

```text
<项目目录>\.<工具>\skills\<skill-name>\
```

例如 Cursor：

```text
E:\my-project\.cursor\skills\develop-sop\
```

全局 Skill 通常写入当前用户目录：

```text
~\.cursor\skills
~\.codex\skills
~\.claude\skills
```

不同工具的实际目录由 Vibebara 自动处理。

## 6. 使用 Skill 市场

进入“SKILL 市场”后，可以查看市场中已发布的 Skill。

### 6.1 获取市场 Skill

1. 打开 Skill 详情。
2. 点击“获取到个人仓库”。
3. 返回个人空间的“SKILL 仓库”查看。

从市场获取只会复制到个人仓库，不会自动加入团队或部署到本机项目。

### 6.2 发布自己的 Skill

1. 在个人 Skill 编辑器中完成编辑并保存。
2. 点击“发布到 SKILL 市场”。
3. 等待审核。

可以在市场的“我的 SKILL”中查看状态：

- 审核中
- 已通过
- 已拒绝

## 7. 团队与项目

### 7.1 创建或加入团队

点击右上角头像：

- 选择“创建团队”，填写团队名称和描述。
- 或选择“加入团队”，输入团队邀请码。

加入后，在“空间选择”中切换到对应团队。

### 7.2 向团队添加 Skill

进入“团队 SKILL”，点击“新增 Skill”。

支持：

- 从个人仓库导入
- 从本地文件夹导入
- 从链接导入

团队 Skill 是协作仓库中的共享版本。项目成员需要把它关联到项目并部署到本机后，才能参与推送、拉取和合并。

### 7.3 创建项目

进入“团队项目”，点击“新建项目”。

填写：

- 项目名称
- 项目描述（可选）

创建完成后点击项目卡片进入项目详情。

### 7.4 关联 Skill

在项目详情点击“关联 Skill”：

1. 从团队仓库选择 Skill。
2. 点击“添加”。

关联只会把 Skill 加入项目列表，不会自动写入本机目录。

### 7.5 部署到本机项目

在项目 Skill 列表中找到未部署的 Skill，点击“部署”：

1. 选择 Vibe Coding 工具。
2. 选择本机项目文件夹。
3. 按需选择“同时部署到全局”。
4. 目标目录已有同名 Skill 时，确认是否覆盖。
5. 点击“部署”。

部署完成后，Vibebara 开始跟踪这个本地 Skill 实例。

注意：

- “同时部署到全局”属于一次性复制，全局副本不参与项目协作跟踪。
- 协作跟踪的是项目部署目录，不是最初导入 Skill 的来源目录。
- 换电脑或更换项目路径后，需要在新电脑上重新部署。

## 8. 同步状态与协作

项目 Skill 可能显示以下状态：

- `未部署`：项目已关联，但尚未写入本机。
- `已同步`：本地内容与团队仓库一致。
- `待推送`：本地有未提交改动。
- `待更新`：团队仓库有新版本。
- `冲突`：本地和团队仓库都发生了改动。
- `路径缺失`：原部署目录不存在。
- `停止跟踪`：该部署实例暂不参与同步。

### 8.1 推送本地改动

本地编辑 Skill 后：

1. 返回项目 Skill 页面。
2. 找到“待推送”的 Skill。
3. 点击“推送”。
4. 确认将本地改动同步到团队仓库。

推送成功后，其他成员会看到“待更新”。

### 8.2 拉取团队更新

当 Skill 显示“待更新”时：

1. 点击“更新本地”。
2. 确认覆盖本地部署目录。

如果本地有未推送改动，直接拉取会被阻止。此时应先推送、合并，或在确认不保留本地改动后使用覆盖操作。

### 8.3 处理冲突

当本地和团队仓库都发生改动时，状态会变为“冲突”。

推荐流程：

1. 点击“AI 合并”查看合并结果。
2. 检查正文、配置和资源改动。
3. 如有人工冲突，先手动确认处理方式。
4. 确认后提交合并结果。

不要在没有检查预览的情况下强制覆盖重要本地改动。

### 8.4 实时同步状态

团队或项目页顶部会显示：

- `实时同步中`：WebSocket 连接正常。
- `同步断开`：实时连接中断。

断开后客户端会自动重连，并使用轮询作为兜底。长时间无法恢复时，请检查网络和云端服务状态。

## 9. Vibebara CLI

CLI 适合在终端、Coding Agent 或自动化脚本中检查和同步已部署的 Skill。

重要限制：CLI 只能操作已经通过 Vibebara Desktop 在当前电脑部署的 Skill。它不会自动把另一台电脑的绝对路径迁移到本机。

CLI API Key 绑定当前登录的桌面设备；在另一台设备登录账号后，旧 Key 会立即失效。
项目部署路径、安装路径和同步 hash 按设备分别保存，切回原设备后会恢复该设备自己的部署记录。

### 9.1 为 CLI 授权

推荐使用桌面端：

1. 登录 Vibebara Desktop。
2. 点击右上角头像。
3. 点击“生成 CLI API Key”。
4. 已有 Key 时可点击“轮换 CLI API Key”。
5. Windows 重新打开终端；macOS 首次使用先运行应用内的 `install-cli.sh`。
6. 执行：

```text
vibebara whoami
```

CLI 配置保存在：

```text
# Windows
%USERPROFILE%\.vibebara\config.json

# macOS
~/.vibebara/config.json
```

不要分享该文件或其中的 API Key。

### 9.2 查看部署状态

进入项目目录后执行：

```powershell
vibebara status
```

供 Agent 或脚本使用：

```powershell
vibebara status --json
```

只查看某个项目：

```powershell
vibebara status --project <project-id>
```

### 9.3 推送

```powershell
vibebara push <skill-name>
```

推送并创建版本：

```powershell
vibebara push <skill-name> `
  --create-version `
  --version-number 1.2 `
  --version-label "版本说明"
```

### 9.4 拉取

```powershell
vibebara pull <skill-name>
```

确认放弃本地未推送改动并覆盖：

```powershell
vibebara pull <skill-name> --overwrite
```

### 9.5 合并

先预览：

```powershell
vibebara merge <skill-name> --preview
```

确认后执行合并：

```powershell
vibebara merge <skill-name>
```

Agent 或无交互环境：

```powershell
vibebara --yes merge <skill-name> --json
```

### 9.6 精确选择部署

同一目录匹配到多个部署时，使用以下参数消歧：

```powershell
vibebara push --deployment <deployment-id>
vibebara pull --skill <skill-name> --project <project-id>
```

也可以指定解析部署时使用的工作目录：

```powershell
vibebara --cwd E:\my-project status
```

### 9.7 CLI 退出码

- `0`：成功
- `1`：一般错误或云端错误
- `2`：参数错误、找不到部署或匹配不唯一
- `3`：推送、拉取或乐观锁冲突
- `4`：合并需要人工处理
- `5`：未授权或凭据失效
- `6`：本地部署路径不存在或不匹配

自动化脚本应同时检查退出码和 `--json` 输出。

### 9.8 手动登录和退出

通常不需要手动登录。桌面端无法写入 CLI 配置时，可以执行：

```powershell
vibebara login `
  --api-key vhk_xxx `
  --cloud http://<server>:<port>/api/v1
```

退出 CLI 登录：

```powershell
vibebara logout
```

退出只会清除本机 API Key，不会退出桌面客户端。

## 10. 自动更新

正式安装的桌面客户端会在启动后自动检查更新。

检测到新版本后：

1. 客户端在后台下载。
2. 下载完成后显示“新版本已准备好”。
3. 可以选择“立即重启安装”或“稍后”。

选择“稍后”不会中断当前工作。正常退出客户端时，已下载的更新可能自动安装。

也可以点击右上角头像，选择“检查更新”。

## 11. 数据和安全

### 11.1 本地数据位置

桌面配置和登录数据位于：

```text
%APPDATA%\@vibebara\desktop
```

常见文件：

- `vibebara-desktop.config.json`：云端地址和本地写入范围配置。
- `vibebara-token.bin`：由 Windows 安全存储加密的登录 token。
- `vibebara-device.json`：当前设备标识。

CLI 配置位于：

```text
%USERPROFILE%\.vibebara\config.json
```

卸载桌面客户端不会自动删除这些用户数据。

### 11.2 本地代理

Vibebara 本地代理：

- 只监听 `127.0.0.1`。
- 使用随机配对令牌保护本地接口。
- 只允许在用户选择的项目目录和受支持的 Skill 目录中写文件。
- 会拒绝通过 `..` 等方式逃逸允许目录的路径。

### 11.3 安全提示

- 不要公开 CLI API Key。
- 不要把 `.vibebara\config.json` 提交到 Git。
- 推送、覆盖或合并前检查目标 Skill 和项目。
- 当前测试云端仍可能使用 HTTP/WS 明文连接，不应在不可信网络中传输敏感内容。
- 当前 Windows 安装包未签名，安装和升级时可能触发 SmartScreen。

## 12. 常见问题

### 12.1 终端找不到 `vibebara`

先关闭并重新打开终端，然后执行：

```powershell
Get-Command vibebara
```

如果仍找不到，检查以下目录是否存在：

```text
%LOCALAPPDATA%\Programs\Vibebara\resources\cli
```

可直接运行：

```powershell
& "$env:LOCALAPPDATA\Programs\Vibebara\resources\cli\vibebara.exe" --version
```

### 12.2 `vibebara whoami` 提示未授权

1. 确认桌面客户端已登录。
2. 在头像菜单点击“生成 CLI API Key”。
3. 重新打开终端。
4. 再执行 `vibebara whoami`。

已有 Key 仍失败时，可以轮换 Key 后重试。

### 12.3 CLI 提示“暂不支持跨机”

云端部署记录保存了部署时的绝对路径。出现此提示通常表示：

- 当前电脑不是最初部署的电脑。
- 项目被移动到新路径。
- Skill 目录被重命名或删除。

请在当前电脑使用桌面客户端重新部署该 Skill。

### 12.4 Skill 显示“路径缺失”

确认项目目录和 Skill 目录仍存在。如果项目已移动，使用“重新部署”，不要手动修改云端记录。

### 12.5 拉取被阻止

本地存在未推送改动。可以：

- 先推送本地改动。
- 使用合并处理双方改动。
- 确认不保留本地改动后使用覆盖拉取。

### 12.6 推送提示冲突

团队仓库已在本地编辑之后发生变化。先拉取或执行合并预览，再提交。

### 12.7 页面显示“同步断开”

1. 检查网络连接。
2. 等待客户端自动重连。
3. 刷新页面或重启客户端。
4. 如果持续断开，联系管理员检查云端 WebSocket 服务。

### 12.8 登录或滑块验证失败

- 检查网络和云端服务状态。
- 确认邀请码有效且未过期。
- 重新获取滑块挑战后再试。
- VPN 或代理异常时，尝试关闭后重新启动客户端。

### 12.9 本地代理不可用

正常情况下桌面客户端会自动启动并重启本地代理。持续失败时：

1. 退出 Vibebara。
2. 确认没有残留的 Vibebara 进程。
3. 重新启动客户端。
4. 仍失败时保留错误提示并联系管理员。

## 13. 当前限制

- 桌面客户端当前以 Windows 为主要支持平台。
- 安装包尚未完成代码签名。
- CLI 只支持同机部署，不支持跨机自动迁移路径。
- 项目“关联 Skill”不会自动部署，必须单独执行部署。
- 全局部署副本不参与项目同步跟踪。
- CLI 的 `--verbose` 参数当前不会输出额外调试信息。
- 当前测试云端可能仍使用 HTTP/WS，正式外部环境应使用 HTTPS/WSS。

## 14. 推荐协作流程

日常团队协作建议遵循：

1. 在团队仓库准备 Skill。
2. 在项目中关联 Skill。
3. 每位成员在自己的电脑部署 Skill。
4. 开始修改前先查看状态并拉取团队最新版本。
5. 本地修改完成后推送。
6. 出现双方改动时先预览合并。
7. 合并或覆盖前确认重要内容已备份。

CLI 快速流程：

```powershell
vibebara whoami
vibebara status --json
vibebara pull <skill-name>
# 本地编辑
vibebara push <skill-name>
```

冲突时：

```powershell
vibebara merge <skill-name> --preview --json
vibebara --yes merge <skill-name> --json
```

## 15. 获取帮助

遇到问题时，建议准备以下信息：

- Vibebara Desktop 版本
- `vibebara --version` 输出
- 操作系统版本
- 项目路径和目标工具
- Skill 名称
- 页面状态或 CLI 完整错误信息
- `vibebara status --json` 输出

提交日志或截图前，请删除 API Key、登录 token 和其他敏感信息。
