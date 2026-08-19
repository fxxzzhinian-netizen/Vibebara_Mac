const allowUnsigned = process.argv.includes("--allow-unsigned");
const requestedPlatform = process.argv
  .find((arg) => arg.startsWith("--platform="))
  ?.slice("--platform=".length);
const platform = requestedPlatform || process.platform;
const updateUrl = process.env.VIBEBARA_UPDATE_URL || "";

const errors = [];
if (!allowUnsigned && platform === "darwin") {
  const signingLink = process.env.MAC_CSC_LINK || process.env.CSC_LINK;
  const signingPassword =
    process.env.MAC_CSC_KEY_PASSWORD || process.env.CSC_KEY_PASSWORD;
  const hasApiKeyNotary =
    process.env.APPLE_API_KEY &&
    process.env.APPLE_API_KEY_ID &&
    process.env.APPLE_API_ISSUER;
  const hasAppleIdNotary =
    process.env.APPLE_ID &&
    process.env.APPLE_APP_SPECIFIC_PASSWORD &&
    process.env.APPLE_TEAM_ID;
  const hasKeychainNotary =
    process.env.APPLE_KEYCHAIN && process.env.APPLE_KEYCHAIN_PROFILE;
  if (!signingLink) {
    errors.push("缺少 MAC_CSC_LINK（或 CSC_LINK）Developer ID 证书");
  }
  if (!signingPassword) {
    errors.push("缺少 MAC_CSC_KEY_PASSWORD（或 CSC_KEY_PASSWORD）证书密码");
  }
  if (!hasApiKeyNotary && !hasAppleIdNotary && !hasKeychainNotary) {
    errors.push(
      "缺少 Apple 公证凭据：配置 API Key、Apple ID 或 Keychain profile 任一组合",
    );
  }
} else if (!allowUnsigned) {
  const signingLink = process.env.WIN_CSC_LINK || process.env.CSC_LINK;
  const signingPassword =
    process.env.WIN_CSC_KEY_PASSWORD || process.env.CSC_KEY_PASSWORD;
  if (!signingLink) {
    errors.push("缺少 WIN_CSC_LINK（或 CSC_LINK）代码签名证书");
  }
  if (!signingPassword) {
    errors.push(
      "缺少 WIN_CSC_KEY_PASSWORD（或 CSC_KEY_PASSWORD）证书密码",
    );
  }
}

try {
  const url = new URL(updateUrl);
  if (url.protocol !== "https:") {
    errors.push("VIBEBARA_UPDATE_URL 必须使用 HTTPS");
  }
} catch {
  errors.push("缺少或无法解析 VIBEBARA_UPDATE_URL");
}

if (errors.length > 0) {
  console.error("[release] 发布环境不完整：");
  for (const error of errors) console.error(`  - ${error}`);
  process.exit(1);
}

if (allowUnsigned) {
  console.warn(
    `[release] 警告：正在构建未签名 ${platform} 自动更新包，仅校验 HTTPS 更新源`,
  );
} else {
  console.log(`[release] ${platform} 签名、公证与 HTTPS 更新源检查通过`);
}
