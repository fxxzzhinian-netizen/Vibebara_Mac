// 资源文件树节点（scripts/references/assets 文件夹树）。
export interface ResTreeNode {
  name: string
  path: string
  isDir: boolean
  children?: ResTreeNode[]
}

type GlyphType =
  | 'code'
  | 'doc'
  | 'config'
  | 'data'
  | 'web'
  | 'style'
  | 'image'
  | 'audio'
  | 'video'
  | 'archive'

const wrapSvg = (label: string, content: string) => `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" role="img" aria-label="${label} file icon">
  ${content}
</svg>`

const fileSvg = (label: string, main: string, type: GlyphType = 'code') => {
  if (label === 'VUE') {
    return wrapSvg(
      label,
      '<path d="M1.5 3h4.2L12 13.8 18.3 3h4.2L12 21z" fill="#41B883"/><path d="M5.7 3h4L12 7l2.3-4h4L12 13.8z" fill="#35495E"/>',
    )
  }

  if (label === 'ENV') {
    return wrapSvg(
      label,
      `<text x="12" y="17.3" text-anchor="middle" font-family="Consolas, monospace" font-size="17" font-weight="700" fill="${main}">$</text>`,
    )
  }

  if (label === 'JSON') {
    return wrapSvg(
      label,
      `<text x="12" y="17" text-anchor="middle" font-family="Consolas, monospace" font-size="14" font-weight="700" fill="${main}">{ }</text>`,
    )
  }

  if (label === 'HTML') {
    return wrapSvg(
      label,
      `<path d="M9 6L3 12l6 6M15 6l6 6-6 6" fill="none" stroke="${main}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`,
    )
  }

  const glyphMap: Record<GlyphType, string> = {
    code: `<text x="12" y="17.2" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="${label.length > 3 ? 8 : 10.5}" font-weight="800" fill="${main}">${label}</text>`,
    doc: `<text x="12" y="17.2" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="${label.length > 3 ? 8 : 10.5}" font-weight="800" fill="${main}">${label}</text>`,
    config: `<path d="M13.6 2.5L6.5 13h4.7l-.8 8.5L17.5 11h-4.7z" fill="${main}"/>`,
    data: `<ellipse cx="12" cy="6.5" rx="7" ry="3" fill="none" stroke="${main}" stroke-width="1.8"/><path d="M5 6.5v10c0 1.7 3.1 3 7 3s7-1.3 7-3v-10M5 11.5c0 1.7 3.1 3 7 3s7-1.3 7-3" fill="none" stroke="${main}" stroke-width="1.8"/>`,
    web: `<circle cx="12" cy="12" r="8.5" fill="none" stroke="${main}" stroke-width="1.8"/><path d="M3.5 12h17M12 3.5c2.3 2.4 3.5 5.2 3.5 8.5S14.3 18.1 12 20.5M12 3.5C9.7 5.9 8.5 8.7 8.5 12s1.2 6.1 3.5 8.5" fill="none" stroke="${main}" stroke-width="1.5"/>`,
    style: `<path d="M5 19c4.8-.6 13-4.9 13-13 0-2.5-1.8-3.5-3.6-2.1C8.8 8 4.5 9.4 4.5 15.5c0 1.8.5 2.9.5 3.5z" fill="none" stroke="${main}" stroke-width="2" stroke-linejoin="round"/>`,
    image: `<rect x="3.5" y="4.5" width="17" height="15" rx="2" fill="none" stroke="${main}" stroke-width="1.8"/><circle cx="8.5" cy="9" r="1.7" fill="${main}"/><path d="M5 18l5.2-5.3 3.5 3.4 2.3-2.3 3.5 3.7" fill="none" stroke="${main}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`,
    audio: `<path d="M5 14h4l6 5V5L9 10H5v4z" fill="none" stroke="${main}" stroke-width="2" stroke-linejoin="round"/><path d="M18 9c1.5 1.6 1.5 4.4 0 6" fill="none" stroke="${main}" stroke-width="2" stroke-linecap="round"/>`,
    video: `<rect x="3.5" y="6" width="12" height="12" rx="2" fill="none" stroke="${main}" stroke-width="1.8"/><path d="M15.5 10l5-3v10l-5-3" fill="none" stroke="${main}" stroke-width="1.8" stroke-linejoin="round"/>`,
    archive: `<path d="M6 4h12v16H6zM8 2h8l2 2H6l2-2z" fill="none" stroke="${main}" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 4v16M10.5 7h3M10.5 11h3" stroke="${main}" stroke-width="1.5" stroke-linecap="round"/>`,
  }

  return wrapSvg(label, glyphMap[type])
}

const FILE_ICON_SVG_MAP: Record<string, string> = {
  // 代码 / 编程语言
  py: fileSvg('PY', '#3776AB', 'code'),
  ipynb: fileSvg('NB', '#F37626', 'code'),

  js: fileSvg('JS', '#C79200', 'code'),
  cjs: fileSvg('CJS', '#C79200', 'code'),
  mjs: fileSvg('MJS', '#C79200', 'code'),
  jsx: fileSvg('JSX', '#61DAFB', 'code'),

  ts: fileSvg('TS', '#3178C6', 'code'),
  tsx: fileSvg('TSX', '#3178C6', 'code'),

  vue: fileSvg('VUE', '#42B883', 'code'),
  go: fileSvg('GO', '#00ADD8', 'code'),
  rs: fileSvg('RS', '#DEA584', 'code'),
  java: fileSvg('JAVA', '#E76F00', 'code'),
  kt: fileSvg('KT', '#7F52FF', 'code'),
  rb: fileSvg('RB', '#CC342D', 'code'),
  php: fileSvg('PHP', '#777BB4', 'code'),

  c: fileSvg('C', '#00599C', 'code'),
  h: fileSvg('H', '#00599C', 'code'),
  cpp: fileSvg('C++', '#00599C', 'code'),
  cc: fileSvg('C++', '#00599C', 'code'),
  cs: fileSvg('C#', '#239120', 'code'),

  swift: fileSvg('SWIFT', '#FA7343', 'code'),

  sh: fileSvg('SH', '#4EAA25', 'code'),
  bash: fileSvg('BASH', '#4EAA25', 'code'),
  zsh: fileSvg('ZSH', '#4EAA25', 'code'),
  ps1: fileSvg('PS1', '#5391FE', 'code'),
  bat: fileSvg('BAT', '#4EAA25', 'code'),

  sql: fileSvg('SQL', '#336791', 'data'),

  // 标记 / 文档
  md: fileSvg('MD', '#083FA1', 'doc'),
  mdx: fileSvg('MDX', '#1B1F24', 'doc'),
  txt: fileSvg('TXT', '#6B7280', 'doc'),
  rst: fileSvg('RST', '#6B7280', 'doc'),
  pdf: fileSvg('PDF', '#D93025', 'doc'),
  doc: fileSvg('DOC', '#2B579A', 'doc'),
  docx: fileSvg('DOCX', '#2B579A', 'doc'),

  // 数据 / 配置
  json: fileSvg('JSON', '#F59E0B', 'data'),
  yaml: fileSvg('YAML', '#CB171E', 'config'),
  yml: fileSvg('YML', '#CB171E', 'config'),
  toml: fileSvg('TOML', '#9C4221', 'config'),
  ini: fileSvg('INI', '#64748B', 'config'),
  env: fileSvg('ENV', '#78A641', 'config'),
  xml: fileSvg('XML', '#E34F26', 'data'),
  csv: fileSvg('CSV', '#217346', 'data'),

  // 网页 / 样式
  html: fileSvg('HTML', '#E34F26', 'web'),
  htm: fileSvg('HTML', '#E34F26', 'web'),
  css: fileSvg('CSS', '#1572B6', 'style'),
  scss: fileSvg('SCSS', '#CC6699', 'style'),
  sass: fileSvg('SASS', '#CC6699', 'style'),
  less: fileSvg('LESS', '#1D365D', 'style'),

  // 图片 / 媒体
  png: fileSvg('PNG', '#8B5CF6', 'image'),
  jpg: fileSvg('JPG', '#8B5CF6', 'image'),
  jpeg: fileSvg('JPEG', '#8B5CF6', 'image'),
  gif: fileSvg('GIF', '#8B5CF6', 'image'),
  webp: fileSvg('WEBP', '#8B5CF6', 'image'),
  svg: fileSvg('SVG', '#FFB13B', 'image'),
  bmp: fileSvg('BMP', '#8B5CF6', 'image'),
  ico: fileSvg('ICO', '#8B5CF6', 'image'),

  mp3: fileSvg('MP3', '#EC4899', 'audio'),
  wav: fileSvg('WAV', '#EC4899', 'audio'),
  mp4: fileSvg('MP4', '#EF4444', 'video'),
  mov: fileSvg('MOV', '#EF4444', 'video'),

  // 压缩
  zip: fileSvg('ZIP', '#A16207', 'archive'),
  gz: fileSvg('GZ', '#A16207', 'archive'),
  tar: fileSvg('TAR', '#A16207', 'archive'),
  rar: fileSvg('RAR', '#A16207', 'archive'),
}

const DEFAULT_FILE_ICON_SVG = fileSvg('FILE', '#64748B', 'doc')

// 特殊文件名（无扩展名或固定命名）的图标。
const SPECIAL_FILE_ICON_SVG: Record<string, string> = {
  dockerfile: fileSvg('DOCK', '#2496ED', 'config'),
  license: fileSvg('LIC', '#6B7280', 'doc'),
  lock: fileSvg('LOCK', '#A16207', 'archive'),
  package: fileSvg('JSON', '#C7B900', 'data'),
  tsconfig: fileSvg('TS', '#3178C6', 'code'),
  vite: fileSvg('VITE', '#D6B600', 'config'),
}

/** 由文件名（含扩展名）返回类型图标的 SVG 字符串。 */
function fileIconSvg(name: string): string {
  const lower = (name || '').toLowerCase()
  if (lower === 'package.json' || lower === 'package-lock.json') return SPECIAL_FILE_ICON_SVG.package
  if (lower === 'tsconfig.json' || lower.startsWith('tsconfig.')) return SPECIAL_FILE_ICON_SVG.tsconfig
  if (lower === 'vite.config.ts' || lower === 'vite.config.js') return SPECIAL_FILE_ICON_SVG.vite
  if (lower === '.env' || lower.startsWith('.env.')) return FILE_ICON_SVG_MAP.env
  if (lower === 'dockerfile' || lower.endsWith('.dockerfile')) return SPECIAL_FILE_ICON_SVG.dockerfile
  if (lower === 'license' || lower === 'license.txt') return SPECIAL_FILE_ICON_SVG.license
  if (lower.endsWith('.lock') || lower === 'yarn.lock') return SPECIAL_FILE_ICON_SVG.lock
  const dot = lower.lastIndexOf('.')
  const ext = dot >= 0 ? lower.slice(dot + 1) : ''
  return FILE_ICON_SVG_MAP[ext] || DEFAULT_FILE_ICON_SVG
}

/** 由文件名返回可直接用于 <img src> 的 data URI。 */
export function fileIconUrl(name: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(fileIconSvg(name))}`
}
