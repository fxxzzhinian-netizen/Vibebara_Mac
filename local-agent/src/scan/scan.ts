import fs from "node:fs";
import path from "node:path";
import { cursorSkillsDir, codexSkillsDir, windsurfSkillsDir, claudeSkillsDir, kiroSkillsDir, traeSkillsDir, qoderSkillsDir, workbuddySkillsDir } from "../platform";
import type { UnifiedSkillPackage } from "../types";
import { detectOrigin } from "./detect";
import { parseFrontmatter, parseYaml } from "./frontmatter";

/**
 * scan 来源识别移植（R1）—— 纯 TS 复刻 skill-forge bridge `scan-and-package`：
 *   · src/commands/package.ts::scanAndPackage / packageSkill
 *   · src/commands/import.ts::importSkill（仅提取契约所需字段）
 *   · 并内联 backend/skill_forge_service.py::SkillRegistry._normalize_packages 的
 *     「PackageResult → UnifiedSkillPackage(camelCase)」归一化，直接产出契约结构，
 *     便于云端复用（与现有 scan-and-package 输出结构对齐）。
 */

function existsSync(p: string): boolean {
  try {
    fs.accessSync(p);
    return true;
  } catch {
    return false;
  }
}

const SKIP_SCAN_DIRS = new Set([
  "node_modules",
  "__pycache__",
  ".git",
  ".svn",
  ".hg",
  "dist",
  "build",
  "$RECYCLE.BIN",
  "System Volume Information",
]);

/** IDE 点号配置目录到其 Skill 容器的相对路径。 */
const IDE_SKILL_CONTAINERS = new Map<string, string[]>([
  [".cursor", ["skills"]],
  [".codex", ["skills"]],
  [".codeium", ["windsurf", "skills"]],
  [".claude", ["skills"]],
  [".kiro", ["skills"]],
  [".trae", ["skills"]],
  [".trae-cn", ["skills"]],
  [".qoder", ["skills"]],
  [".workbuddy", ["skills"]],
]);

/** 列出可扫描的直接子目录；普通点号目录仍跳过，但保留受支持 IDE 的配置目录。 */
function listSubDirs(dir: string): string[] {
  const result: string[] = [];
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return result;
  }
  for (const entry of entries) {
    if (!entry.isDirectory() || SKIP_SCAN_DIRS.has(entry.name)) continue;
    if (
      entry.name.startsWith(".") &&
      !IDE_SKILL_CONTAINERS.has(entry.name.toLowerCase())
    ) continue;
    result.push(path.join(dir, entry.name));
  }
  return result;
}

/** 列出 dir 下的直接条目名（对齐 package.ts::listDirEntries）。 */
function listDirEntries(dir: string): string[] {
  try {
    return fs.readdirSync(dir);
  } catch {
    return [];
  }
}

interface ExtractedConfig {
  name?: string;
  description?: string;
  displayName?: string;
  shortDescription?: string;
}

/**
 * 提取契约所需配置字段 —— 复刻 import.ts 的 importFromCursor/importFromCodex
 * （importFrom = origin==="unknown" ? "codex" : origin）。
 */
function extractConfigFields(
  skillDir: string,
  origin: "cursor" | "codex" | "unknown",
): ExtractedConfig {
  const importFrom = origin === "unknown" ? "codex" : origin;

  const skillMdPath = path.join(skillDir, "SKILL.md");
  let frontmatter: Record<string, unknown> = {};
  if (existsSync(skillMdPath)) {
    ({ frontmatter } = parseFrontmatter(fs.readFileSync(skillMdPath, "utf-8")));
  }

  const config: ExtractedConfig = {
    name: frontmatter["name"] as string | undefined,
    description: frontmatter["description"] as string | undefined,
  };

  if (importFrom === "cursor") {
    return config; // cursor 导入不含 displayName / shortDescription
  }

  // codex 路径
  const metadata = frontmatter["metadata"] as Record<string, unknown> | undefined;
  if (metadata?.["short-description"]) {
    config.shortDescription = metadata["short-description"] as string;
  }

  const agentYamlPath = path.join(skillDir, "agents", "openai.yaml");
  if (existsSync(agentYamlPath)) {
    let agentYaml: Record<string, unknown> = {};
    try {
      agentYaml = parseYaml<Record<string, unknown>>(
        fs.readFileSync(agentYamlPath, "utf-8"),
      );
    } catch {
      agentYaml = {};
    }
    const iface = agentYaml["interface"] as Record<string, unknown> | undefined;
    if (iface) {
      config.displayName = iface["display_name"] as string | undefined;
      const rawShort =
        config.shortDescription ?? (iface["short_description"] as string | undefined);
      if (rawShort) {
        config.shortDescription =
          rawShort.length > 256 ? rawShort.slice(0, 253) + "..." : rawShort;
      }
    }
  }

  return config;
}

/** 复刻 package.ts::packageSkill + _normalize_packages，直接产出契约 UnifiedSkillPackage。 */
export function packageSkill(skillDir: string): UnifiedSkillPackage {
  const id = path.basename(skillDir);
  const detection = detectOrigin(skillDir);
  const config = extractConfigFields(skillDir, detection.origin);

  const scripts = listDirEntries(path.join(skillDir, "scripts"));
  const references = listDirEntries(path.join(skillDir, "references"));
  const assets = listDirEntries(path.join(skillDir, "assets"));

  const installedAt = {
    cursor: existsSync(path.join(cursorSkillsDir(), id, "SKILL.md")),
    codex: existsSync(path.join(codexSkillsDir(), id, "SKILL.md")),
    windsurf: existsSync(path.join(windsurfSkillsDir(), id, "SKILL.md")),
    claude: existsSync(path.join(claudeSkillsDir(), id, "SKILL.md")),
    kiro: existsSync(path.join(kiroSkillsDir(), id, "SKILL.md")),
    trae: existsSync(path.join(traeSkillsDir(), id, "SKILL.md")),
    qoder: existsSync(path.join(qoderSkillsDir(), id, "SKILL.md")),
    workbuddy: existsSync(path.join(workbuddySkillsDir(), id, "SKILL.md")),
  };

  return {
    id,
    origin: detection.origin,
    originConfidence: detection.confidence,
    originSignals: detection.signals,
    sourcePath: skillDir,
    name: config.name || id,
    displayName: config.displayName || "",
    description: config.description || "",
    shortDescription: config.shortDescription || "",
    hasScripts: scripts.length > 0,
    hasReferences: references.length > 0,
    hasAssets: assets.length > 0,
    installedAt,
  };
}

/**
 * 扫描 rootDir 自身、一级子目录及标准 IDE 点号目录中的 Skill，逐个识别并归一化输出。
 *
 * · rootDir 自身含 SKILL.md（用户直接选中了 skill 文件夹，「纯 md」技能无外层目录）→ 收 rootDir；
 * · rootDir 的一级子目录含 SKILL.md（容器目录，如 ~/.cursor/skills）→ 收各子目录；
 * · rootDir 是项目目录或用户目录时，识别 `.cursor/skills`、`.codex/skills` 等标准容器。
 * 两者并存（极少见）时一并收录——skill 资源目录 scripts/references/assets 不含 SKILL.md，不会重复。
 */
export function scanAndPackage(rootDir: string): UnifiedSkillPackage[] {
  const results: UnifiedSkillPackage[] = [];
  const candidates = new Set<string>();
  const addCandidate = (dir: string): void => {
    if (existsSync(path.join(dir, "SKILL.md"))) candidates.add(dir);
  };
  const addContainerSkills = (container: string): void => {
    addCandidate(container);
    for (const dir of listSubDirs(container)) addCandidate(dir);
  };
  const addIdeSkills = (ideDir: string): void => {
    const relative = IDE_SKILL_CONTAINERS.get(path.basename(ideDir).toLowerCase());
    if (relative) addContainerSkills(path.join(ideDir, ...relative));
  };

  addCandidate(rootDir);
  const children = listSubDirs(rootDir);
  for (const dir of children) addCandidate(dir);
  addIdeSkills(rootDir);
  for (const dir of children) addIdeSkills(dir);

  for (const dir of candidates) {
    try {
      results.push(packageSkill(dir));
    } catch (err) {
      // 单个 skill 解析失败不影响整体（对齐 bridge 行为）
      // eslint-disable-next-line no-console
      console.error(
        `[scan] 跳过 ${dir}：${(err as Error).message}`,
      );
    }
  }
  return results;
}
