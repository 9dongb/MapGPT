"""작업 후 검증: 린트·포맷, 테스트(unit + integration), 화면 타입 검사·빌드를 차례로 실행한다.

프로젝트 가상환경(conda 환경 mapgpt 또는 venv)을 활성화하고 실행한다 (macOS·Linux·Windows 공통).

    python scripts/check.py

모든 단계를 실행한 뒤 하나라도 실패하면 종료 코드 1로 끝난다.
e2e 테스트는 실제 LLM이 필요해 여기서 돌리지 않는다 (AGENTS.md 9장).
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
TAIL_LINES = 40  # 실패한 단계에서 보여줄 마지막 출력 줄 수


def steps() -> list[tuple[str, list[str], Path, dict[str, str]]]:
    python = sys.executable
    npm = shutil.which("npm") or "npm"  # Windows에서는 npm.cmd 경로를 찾는다
    return [
        ("ruff check", [python, "-m", "ruff", "check", "app", "tests", "scripts"], ROOT, {}),
        ("ruff format", [python, "-m", "ruff", "format", "--check", "app", "tests", "scripts"], ROOT, {}),
        # DB에 연결하지 못하면 integration 테스트를 skip하지 않고 실패시킨다 (tests/conftest.py).
        ("pytest", [python, "-m", "pytest", "-q"], ROOT, {"MAPGPT_REQUIRE_DB": "1"}),
        ("npm typecheck", [npm, "run", "typecheck"], FRONTEND, {}),
        ("npm build", [npm, "run", "build"], FRONTEND, {}),
    ]


def run(command: list[str], cwd: Path, extra_env: dict[str, str]) -> tuple[bool, str]:
    if cwd == FRONTEND and not (FRONTEND / "node_modules").exists():
        return False, "frontend/node_modules가 없습니다. frontend에서 npm install을 먼저 실행하세요"
    env = {**os.environ, "PYTHONUTF8": "1", **extra_env}
    try:
        result = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        return False, f"실행 파일을 찾지 못했습니다: {command[0]}"
    return result.returncode == 0, result.stdout + result.stderr


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    if importlib.util.find_spec("pytest") is None or importlib.util.find_spec("ruff") is None:
        print(
            '프로젝트 가상환경(conda 환경 mapgpt 또는 .venv)을 활성화하고 pip install -e ".[dev]" 후 python scripts/check.py를 실행하세요'
        )
        return 1

    failed = []
    started = time.monotonic()
    for name, command, cwd, extra_env in steps():
        step_started = time.monotonic()
        ok, output = run(command, cwd, extra_env)
        print(f"[{'통과' if ok else '실패'}] {name} ({time.monotonic() - step_started:.1f}초)", flush=True)
        if not ok:
            failed.append(name)
            for line in output.strip().splitlines()[-TAIL_LINES:]:
                print(f"    {line}")

    if failed:
        print(f"\n검증 실패: {', '.join(failed)}")
        return 1
    print(f"\n검증 통과 ({len(steps())}단계, {time.monotonic() - started:.1f}초)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
