#!/usr/bin/env node

const { spawnSync, spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const venvDir = path.join(projectRoot, ".venv");
const isWindows = process.platform === "win32";
const pythonNameCandidates = isWindows ? ["python", "python3", "py"] : ["python3", "python"];

const venvPython = path.join(venvDir, isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python");
const venvPip = path.join(venvDir, isWindows ? "Scripts" : "bin", isWindows ? "pip.exe" : "pip");
const requirementsPath = path.join(projectRoot, "requirements.txt");
const depsMarker = path.join(venvDir, ".deps-installed");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.error) {
    console.error(result.error.message);
    process.exit(result.status ?? 1);
  }
  if (result.status !== 0) {
    process.exit(result.status);
  }
}

function findPython() {
  for (const candidate of pythonNameCandidates) {
    const which = spawnSync(isWindows ? "where" : "which", [candidate], { stdio: "ignore" });
    if (which.status === 0) {
      return candidate;
    }
  }
  console.error("Unable to locate python. Please install Python 3.x and try again.");
  process.exit(1);
}

function ensureVenv() {
  if (!fs.existsSync(venvPython)) {
    const python = findPython();
    console.error(`Creating virtual environment with ${python} ...`);
    run(python, ["-m", "venv", venvDir], { cwd: projectRoot });
  }
}

function ensureDependencies() {
  if (!fs.existsSync(requirementsPath)) {
    console.warn("requirements.txt not found; skipping dependency install.");
    return;
  }
  const requirementsHash = crypto.createHash("sha256").update(fs.readFileSync(requirementsPath)).digest("hex");
  const needsInstall = !fs.existsSync(depsMarker) || fs.readFileSync(depsMarker, "utf8") !== requirementsHash;
  if (needsInstall) {
    console.error("Installing Python dependencies ...");
    run(venvPip, ["install", "--upgrade", "pip"], { cwd: projectRoot });
    run(venvPip, ["install", "-r", requirementsPath], { cwd: projectRoot });
    fs.writeFileSync(depsMarker, requirementsHash);
  }
}

function startServer() {
  const serverPath = path.join(projectRoot, "server.py");
  if (!fs.existsSync(serverPath)) {
    console.error(`Unable to locate server.py at ${serverPath}`);
    process.exit(1);
  }
  const child = spawn(venvPython, [serverPath], {
    cwd: projectRoot,
    stdio: "inherit",
    env: process.env,
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 0);
    }
  });
}

function main() {
  ensureVenv();
  ensureDependencies();
  startServer();
}

main();
