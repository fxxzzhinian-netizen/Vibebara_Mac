import type {
  SkillVersionItem,
  SkillVersionDetail,
  VersionResourceFileResponse,
} from '@/api/skillStore'
import type { ChangeItem } from '@/api/projects'

/**
 * 「版本历史」模拟数据。
 *
 * 两种触发方式：
 *  1) 显式强制（dev / 生产均可，默认关闭、纯属 opt-in）——用于在打包后的桌面端也能临时看模拟数据：
 *     - 地址栏带 ?mock=1（hash 路由下放 # 前后均可，会写入 localStorage 持久化）
 *     - 控制台执行：localStorage.setItem('vibebara_dev_mock', '1')
 *     关闭：地址带 ?mock=0，或 localStorage.removeItem('vibebara_dev_mock')
 *  2) 自动回退（仅 import.meta.env.DEV 开发构建，见 SkillDetail.loadVersions）——
 *     真实版本为空或接口报错时自动填充模拟数据，生产构建不受影响。
 */
const MOCK_KEY = 'vibebara_dev_mock'

/** 是否被显式强制开启模拟数据（dev / 生产都可，opt-in）。 */
export function isMockForced(): boolean {
  try {
    const href = window.location.href
    if (/[?&]mock=1\b/.test(href)) {
      localStorage.setItem(MOCK_KEY, '1')
      return true
    }
    if (/[?&]mock=0\b/.test(href)) {
      localStorage.removeItem(MOCK_KEY)
      return false
    }
    return localStorage.getItem(MOCK_KEY) === '1'
  } catch {
    return false
  }
}

function isoMinutesAgo(min: number): string {
  return new Date(Date.now() - min * 60_000).toISOString()
}

const BODY_DIFF_SMALL = `@@ -8,7 +8,8 @@ ## 使用说明
 1. 准备输入文件，放到 input/ 目录。
 2. 运行构建脚本：
-运行 build.sh 生成产物。
+运行 build.ps1 生成产物（Windows 友好）。
 3. 产物输出到 dist/ 目录。
-注意：需要 Node 16 及以上版本。
+注意：需要 Node 18 及以上版本。
+提示：可用环境变量 OUTPUT_DIR 自定义输出目录。`

const BODY_DIFF_LARGE = `@@ -1,4 +1,6 @@ # 角色设定
-你是一个通用助手。
+你是一名资深前端工程师，精通 Vue3 与 TypeScript。
+回答需简洁、给出可运行示例。
 始终使用中文回复。
@@ -20,6 +22,9 @@ ## 输出规范
 - 代码块标注语言。
-- 不要附带多余解释。
+- 关键步骤附一句话说明。
+- 涉及命令时优先给 PowerShell 版本。
+- 大段改动给出 diff 而非整文件。
 - 保持风格统一。`

/** 模拟版本列表（倒序：seq 大在前），覆盖 field / body / resource 各类改动与多种来源。 */
export function mockVersions(): SkillVersionItem[] {
  return [
    {
      id: 'mock-v5',
      skill_id: 'mock-skill',
      team_id: 'mock-team',
      seq: 5,
      version_number: '1.5',
      label: '调整提示词',
      content_hash: 'a1b2c3d4',
      change_summary: '修改描述 + 正文(+5/-3)，新增 1 个资源',
      resource_count: 4,
      source: 'web_edit',
      created_by: 'u-amy',
      created_by_name: 'Amy',
      created_at: isoMinutesAgo(8),
      change_items: [
        {
          kind: 'field',
          path: 'description',
          label: '描述 (description)',
          old: '一个用于整理文件的技能。',
          new: '一个用于整理输入文件并生成结构化报告的技能。',
        },
        {
          kind: 'body',
          path: 'SKILL.md',
          label: '正文',
          added_lines: 5,
          removed_lines: 3,
          diff: BODY_DIFF_SMALL,
        },
        {
          kind: 'resource',
          path: 'scripts/build.ps1',
          label: 'scripts/build.ps1',
          change: 'added',
        },
      ],
    },
    {
      id: 'mock-v4',
      skill_id: 'mock-skill',
      team_id: 'mock-team',
      seq: 4,
      version_number: '1.4',
      label: '',
      content_hash: 'e5f6a7b8',
      change_summary: '资源调整：新增/删除/修改各 1 个文件',
      resource_count: 3,
      source: 'push',
      created_by: 'u-bob',
      created_by_name: 'Bob',
      created_at: isoMinutesAgo(95),
      change_items: [
        {
          kind: 'resource',
          path: 'references/api.md',
          label: 'references/api.md',
          change: 'added',
        },
        {
          kind: 'resource',
          path: 'scripts/build.sh',
          label: 'scripts/build.sh',
          change: 'removed',
        },
        {
          kind: 'resource',
          path: 'assets/logo.png',
          label: 'assets/logo.png',
          change: 'modified',
        },
      ],
    },
    {
      id: 'mock-v3',
      skill_id: 'mock-skill',
      team_id: 'mock-team',
      seq: 3,
      version_number: '1.3',
      label: '回滚到 v1',
      content_hash: 'c9d0e1f2',
      change_summary: '回滚：还原为 v1 内容',
      resource_count: 2,
      source: 'restore',
      created_by: 'u-amy',
      created_by_name: 'Amy',
      created_at: isoMinutesAgo(60 * 5),
      change_items: [],
    },
    {
      id: 'mock-v2',
      skill_id: 'mock-skill',
      team_id: 'mock-team',
      seq: 2,
      version_number: '1.2',
      label: '重写角色设定',
      content_hash: '3a4b5c6d',
      change_summary: '正文大幅修改(+5/-3)',
      resource_count: 2,
      source: 'push',
      created_by: 'u-bob',
      created_by_name: 'Bob',
      created_at: isoMinutesAgo(60 * 26),
      change_items: [
        {
          kind: 'body',
          path: 'SKILL.md',
          label: '正文',
          added_lines: 5,
          removed_lines: 3,
          diff: BODY_DIFF_LARGE,
          diff_truncated: true,
        },
      ],
    },
    {
      id: 'mock-v1',
      skill_id: 'mock-skill',
      team_id: 'mock-team',
      seq: 1,
      version_number: '1.1',
      label: '初始版本',
      content_hash: '7e8f9a0b',
      change_summary: '创建技能',
      resource_count: 1,
      source: 'web_edit',
      created_by: 'u-amy',
      created_by_name: 'Amy',
      created_at: isoMinutesAgo(60 * 24 * 3),
      change_items: [],
    },
  ]
}

const MOCK_RES_OLD = `#!/usr/bin/env bash
# 构建脚本（旧）
set -e
echo "building..."
node build.js
echo "done"`

const MOCK_RES_NEW = `#!/usr/bin/env pwsh
# 构建脚本（新，Windows 友好）
$ErrorActionPreference = "Stop"
Write-Host "building..."
node build.js --mode production
Write-Host "done"`

/** 模拟「改动明细」里点击资源文件后的内容/diff（开发者模式用）。 */
export function mockResourceFile(item: ChangeItem): VersionResourceFileResponse {
  const change = (item.change || 'modified') as 'added' | 'removed' | 'modified'
  const textSide = (content: string) => ({
    exists: true,
    encoding: 'utf8' as const,
    content,
    size: content.length,
    is_binary: false,
    too_large: false,
  })
  if (change === 'added') {
    return {
      success: true,
      path: item.path,
      change,
      seq: 5,
      version_number: '1.5',
      prev_version_id: 'mock-v4',
      prev_seq: 4,
      prev_version_number: '1.4',
      new: textSide(MOCK_RES_NEW),
      old: null,
      diff: '',
      diff_truncated: false,
    }
  }
  if (change === 'removed') {
    return {
      success: true,
      path: item.path,
      change,
      seq: 4,
      version_number: '1.4',
      prev_version_id: 'mock-v3',
      prev_seq: 3,
      prev_version_number: '1.3',
      new: null,
      old: textSide(MOCK_RES_OLD),
      diff: '',
      diff_truncated: false,
    }
  }
  // modified：构造一段 unified diff（仅 hunk + 增删行）
  const diff = `@@ -1,6 +1,6 @@
-#!/usr/bin/env bash
-# 构建脚本（旧）
-set -e
+#!/usr/bin/env pwsh
+# 构建脚本（新，Windows 友好）
+$ErrorActionPreference = "Stop"
-echo "building..."
-node build.js
+Write-Host "building..."
+node build.js --mode production`
  return {
    success: true,
    path: item.path,
    change,
    seq: 5,
    version_number: '1.5',
    prev_version_id: 'mock-v4',
    prev_seq: 4,
    prev_version_number: '1.4',
    new: textSide(MOCK_RES_NEW),
    old: textSide(MOCK_RES_OLD),
    diff,
    diff_truncated: false,
  }
}

/** 模拟单个版本详情（查看弹窗用）。 */
export function mockVersionDetail(v: SkillVersionItem): SkillVersionDetail {
  return {
    ...v,
    config: {
      name: 'mock-skill',
      description: '一个用于整理输入文件并生成结构化报告的技能。',
      metadata: { author: v.created_by_name, version: `1.0.${v.seq}` },
      policy: { auto_invoke: true },
    },
    vibeh_content: `# 使用说明\n\n本技能用于自动整理输入文件并生成报告。\n\n## 步骤\n\n1. 准备输入文件，放到 input/ 目录。\n2. 运行 build.ps1 生成产物（Windows 友好）。\n3. 产物输出到 dist/ 目录。\n\n> 这是版本 v${v.version_number} 的模拟正文内容。`,
    resources: ['scripts/build.ps1', 'references/api.md', 'assets/logo.png'].slice(
      0,
      v.resource_count,
    ),
  }
}
