// Copies the PyInstaller output into desktop/resources/engine
const fs = require("fs"), path = require("path");
const src = path.join(__dirname, "../../../backend/dist/hcd-engine");
const dst = path.join(__dirname, "../../resources/engine");
fs.rmSync(dst, { recursive: true, force: true });
fs.cpSync(src, dst, { recursive: true });
console.log("engine copied →", dst);
