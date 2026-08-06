import fs from "node:fs";
import path from "node:path";

export const VIBEBARA_GUIDE_FILENAME = "vibebara.md";
export const VIBEBARA_GUIDE_START = "<!-- vibebara:commands:start -->";
export const VIBEBARA_GUIDE_END = "<!-- vibebara:commands:end -->";

export const VIBEBARA_GUIDE_BLOCK = `${VIBEBARA_GUIDE_START}
# Vibebara Skill 协作指南

此项目的 Skill 由 Vibebara 管理。请在项目根目录打开终端并执行以下命令。

## 查看部署状态

\`\`\`bash
vibebara status
\`\`\`

## 拉取团队最新 Skill

\`\`\`bash
vibebara pull <skill-name>
\`\`\`

如果需要覆盖尚未推送的本地改动：

\`\`\`bash
vibebara pull <skill-name> --overwrite
\`\`\`

## 推送本地改动

\`\`\`bash
vibebara push <skill-name>
\`\`\`

创建版本时可使用：

\`\`\`bash
vibebara push <skill-name> --create-version --version-number 1.2 --version-label "版本说明"
\`\`\`

## 合并冲突

先预览 AI 三方合并结果：

\`\`\`bash
vibebara merge <skill-name> --preview
\`\`\`

确认后执行合并：

\`\`\`bash
vibebara merge <skill-name>
\`\`\`

当项目中存在多个同名部署时，可增加 \`--project <project-id>\` 或
\`--deployment <deployment-id>\` 精确指定。使用 \`vibebara <command> --help\`
查看完整参数。

${VIBEBARA_GUIDE_END}
`;

export function ensureVibebaraGuide(projectRoot: string): void {
  fs.mkdirSync(projectRoot, { recursive: true });
  const guidePath = path.join(projectRoot, VIBEBARA_GUIDE_FILENAME);
  const existing = fs.existsSync(guidePath)
    ? fs.readFileSync(guidePath, "utf8")
    : "";

  const start = existing.indexOf(VIBEBARA_GUIDE_START);
  const end = existing.indexOf(VIBEBARA_GUIDE_END, start);
  let updated: string;

  if (start >= 0 && end >= start) {
    const suffixStart = end + VIBEBARA_GUIDE_END.length;
    updated =
      existing.slice(0, start) +
      VIBEBARA_GUIDE_BLOCK.trimEnd() +
      existing.slice(suffixStart);
    if (!updated.endsWith("\n")) updated += "\n";
  } else {
    const separator =
      existing === "" ? "" : existing.endsWith("\n\n") ? "" : existing.endsWith("\n") ? "\n" : "\n\n";
    updated = `${existing}${separator}${VIBEBARA_GUIDE_BLOCK}`;
  }

  if (updated !== existing) {
    fs.writeFileSync(guidePath, updated, "utf8");
  }
}
