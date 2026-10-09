// Claude Code Stop 훅: 코드를 바꾼 작업을 끝낼 때 scripts/check.py로 검증한다 (macOS·Linux·Windows 공통).
// - 코드 경로에 변경이 없으면 아무것도 하지 않는다.
// - 검증이 실패하면 종료 코드 2로 실패 내용을 Claude에게 돌려줘 고치게 한다.
// - 이미 한 번 막은 뒤(stop_hook_active)에도 실패하면 막지 않고 사용자에게 경고만 남긴다 (무한 반복 방지).
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CODE_PATHS = ["app", "tests", "frontend", "scripts", "pyproject.toml"];
const FEEDBACK_LINES = 80;
const CONDA_DIRS = ["miniconda3", "anaconda3", "miniforge3", "mambaforge", join("opt", "miniconda3"), join("opt", "anaconda3")];

function readInput() {
  try {
    return JSON.parse(readFileSync(0, "utf8"));
  } catch {
    return {};
  }
}

// 사용자에게 경고를 보여주고 멈추게 둔다. 파이프 출력이 잘리지 않도록 동기로 쓴다.
function warn(message) {
  writeSync(1, JSON.stringify({ systemMessage: message }));
  process.exit(0);
}

function codeChanged() {
  const git = spawnSync("git", ["status", "--porcelain", "--", ...CODE_PATHS], { cwd: ROOT, encoding: "utf8" });
  return git.status !== 0 || git.stdout.trim() !== "";
}

// mapgpt conda 환경의 파이썬. 훅은 셸 프로필을 읽지 않으므로 conda activate에 기대지 않는다.
function findPython() {
  if (process.env.MAPGPT_PYTHON) return process.env.MAPGPT_PYTHON;
  const envDirs = [];
  if (process.env.CONDA_PREFIX && basename(process.env.CONDA_PREFIX) === "mapgpt") envDirs.push(process.env.CONDA_PREFIX);
  if (process.env.CONDA_EXE) envDirs.push(join(dirname(dirname(process.env.CONDA_EXE)), "envs", "mapgpt"));
  envDirs.push(...CONDA_DIRS.map((dir) => join(homedir(), dir, "envs", "mapgpt")));
  const executable = (dir) => (process.platform === "win32" ? join(dir, "python.exe") : join(dir, "bin", "python"));
  return envDirs.map(executable).find((path) => existsSync(path));
}

const input = readInput();
if (!codeChanged()) process.exit(0);

const python = findPython();
if (!python) {
  warn("작업 후 검증을 건너뛰었습니다: mapgpt conda 환경의 파이썬을 찾지 못했습니다. MAPGPT_PYTHON 환경 변수(예: .claude/settings.local.json의 env)에 경로를 지정하세요.");
}

const check = spawnSync(python, [join(ROOT, "scripts", "check.py")], {
  cwd: ROOT,
  encoding: "utf8",
  env: { ...process.env, PYTHONUTF8: "1" },
  maxBuffer: 32 * 1024 * 1024,
});
if (check.error) warn(`작업 후 검증을 실행하지 못했습니다 (${python}): ${check.error.message}`);
if (check.status === 0) process.exit(0);

const lines = `${check.stdout}${check.stderr}`.trim().split(/\r?\n/);
const summary = lines.at(-1);
if (input.stop_hook_active) {
  warn(`작업 후 검증이 아직 실패합니다 (${summary}). python scripts/check.py로 확인하세요.`);
}
writeSync(2, `작업 후 검증(python scripts/check.py)이 실패했습니다. 실패한 단계를 고친 뒤 작업을 마치세요.\n\n${lines.slice(-FEEDBACK_LINES).join("\n")}\n`);
process.exit(2);
