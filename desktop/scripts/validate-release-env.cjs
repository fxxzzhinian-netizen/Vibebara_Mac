const signingLink = process.env.WIN_CSC_LINK || process.env.CSC_LINK;
const signingPassword =
  process.env.WIN_CSC_KEY_PASSWORD || process.env.CSC_KEY_PASSWORD;
const updateUrl = process.env.VIBEBARA_UPDATE_URL || "";
const allowUnsigned = process.argv.includes("--allow-unsigned");

const errors = [];
if (!allowUnsigned && !signingLink) {
  errors.push("缺少 WIN_CSC_LINK（或 CSC_LINK）代码签名证书");
}
if (!allowUnsigned && !signingPassword) {
  errors.push(
    "缺少 WIN_CSC_KEY_PASSWORD（或 CSC_KEY_PASSWORD）证书密码",
  );
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
  console.warn("[release] 警告：正在构建未签名自动更新包，仅校验 HTTPS 更新源");
} else {
  console.log("[release] 签名凭据和 HTTPS 更新源检查通过");
}
