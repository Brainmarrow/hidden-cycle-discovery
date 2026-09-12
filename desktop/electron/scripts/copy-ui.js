// Copies the Next.js static export into desktop/resources/ui
const fs = require("fs"), path = require("path");
const src = path.join(__dirname, "../../../frontend/out");
const dst = path.join(__dirname, "../../resources/ui");
fs.rmSync(dst, { recursive: true, force: true });
fs.cpSync(src, dst, { recursive: true });
console.log("ui copied →", dst);
