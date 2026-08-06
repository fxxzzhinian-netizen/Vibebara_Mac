import { confirmDialog } from '@/composables/useConfirmDialog'
import { choiceDialog } from '@/composables/useChoiceDialog'
import { toast } from '@/composables/useToast'
import { launchTool, type ToolId } from '@/api/launcher'
import { TOOL_LABELS, type ToolType } from '@/constants/platforms'

/** 部署目标（个人 / 团队部署弹窗中的工具选项）= 受支持工具的单一事实来源。 */
export type DeployTool = ToolType

/** 部署目标的展示名（复用单一来源 TOOL_LABELS）。 */
export const DEPLOY_TOOL_LABELS: Record<DeployTool, string> = TOOL_LABELS

/**
 * 单一启动形态的部署目标 → 启动器工具 id（IDE 类以部署目录为工作区打开）。
 * Codex / Claude Code 因同时存在 CLI 与桌面端两种形态，不在此表，见 DUAL_FORM_TOOLS。
 */
const SIMPLE_DEPLOY_TOOL_TO_LAUNCHER: Partial<Record<DeployTool, ToolId>> = {
  cursor: 'cursor',
  windsurf: 'windsurf',
  kiro: 'kiro',
  trae: 'trae',
  qoder: 'qoder',
  workbuddy: 'workbuddy',
}

/** CLI / 桌面端两种打开形态的描述。 */
interface ToolForm {
  tool: ToolId
  label: string
  description: string
}

/**
 * 同时存在「命令行 CLI」与「桌面端 App」两种形态的工具：
 * 打开前需让用户二次选择以何种形态打开。
 *   · CLI（codex-cli / claude-code）：打开新终端并锁定到部署目录；
 *   · 桌面端（codex-app / claude-app）：后台启动对应桌面应用。
 */
const DUAL_FORM_TOOLS: Partial<Record<DeployTool, { cli: ToolForm; app: ToolForm }>> = {
  codex: {
    cli: { tool: 'codex-cli', label: '命令行 (CLI)', description: '打开新终端并定位到部署目录' },
    app: { tool: 'codex-app', label: 'ChatGPT 客户端', description: '启动内含 Codex 的 ChatGPT 桌面应用' },
  },
  claude: {
    cli: { tool: 'claude-code', label: '命令行 (CLI)', description: '打开新终端并定位到部署目录' },
    app: { tool: 'claude-app', label: '桌面端 App', description: '启动 Claude 桌面应用' },
  },
}

/**
 * 部署成功后统一调用：弹窗询问是否打开 {工具}。
 *   · Codex / Claude Code：弹「命令行 (CLI) / 桌面端 App」二次选择，按所选形态打开；
 *   · 其余工具：弹「是否打开」二元确认，确认后以部署目录为工作区打开。
 *
 * 个人仓库与团队项目部署共用此逻辑。
 *
 * @param tool        部署所选工具
 * @param projectPath 部署目标文件夹（终端将锁定 / IDE 将打开此目录）
 */
export async function promptOpenAfterDeploy(
  tool: DeployTool,
  projectPath: string,
): Promise<void> {
  const path = (projectPath || '').trim()
  if (!path) return
  const label = DEPLOY_TOOL_LABELS[tool]

  let launcherTool: ToolId | null = null
  const dual = DUAL_FORM_TOOLS[tool]
  if (dual) {
    // Codex / Claude Code：让用户二次选择以 CLI 还是桌面端打开。
    const choice = await choiceDialog({
      title: '部署成功',
      message: `以何种方式打开 ${label}？\n将定位到部署目录：${path}`,
      options: [
        { id: 'cli', label: dual.cli.label, description: dual.cli.description },
        { id: 'app', label: dual.app.label, description: dual.app.description, primary: true },
      ],
      cancelText: '暂不',
    })
    if (!choice) return
    launcherTool = choice === 'app' ? dual.app.tool : dual.cli.tool
  } else {
    const simple = SIMPLE_DEPLOY_TOOL_TO_LAUNCHER[tool]
    if (!simple) return
    const ok = await confirmDialog({
      title: '部署成功',
      message: `是否打开 ${label}？\n将定位到部署目录：${path}`,
      confirmText: `打开 ${label}`,
      cancelText: '暂不',
    })
    if (!ok) return
    launcherTool = simple
  }

  try {
    await launchTool({ tool: launcherTool, project_path: path })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : ''
    toast.warning(`打开 ${label} 失败，请手动打开${msg ? `：${msg}` : ''}`)
  }
}
