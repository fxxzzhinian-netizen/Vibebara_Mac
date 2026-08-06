export interface VersionNumberSource {
  seq: number
  version_number?: string | null
}

export const VERSION_NUMBER_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)$/

export function versionNumberOf(version: VersionNumberSource): string {
  return version.version_number || `1.${version.seq}`
}

export function isValidVersionNumber(value: string): boolean {
  return VERSION_NUMBER_PATTERN.test(value.trim())
}

export function nextVersionNumber(versions: VersionNumberSource[]): string {
  if (!versions.length) return '1.1'
  const latest = versions.reduce((current, item) =>
    item.seq > current.seq ? item : current,
  )
  const current = versionNumberOf(latest)
  if (!isValidVersionNumber(current)) return '1.1'
  const [major, minor] = current.split('.').map(Number)
  const used = new Set(versions.map(versionNumberOf))
  let candidate = `${major}.${minor + 1}`
  while (used.has(candidate)) {
    const [candidateMajor, candidateMinor] = candidate.split('.').map(Number)
    candidate = `${candidateMajor}.${candidateMinor + 1}`
  }
  return candidate
}
