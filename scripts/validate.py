"""Run release checks and retain individual logs, JUnit and a JSON summary."""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent


def main():
    working = ROOT / ".checks"
    reports = working / "reports"
    if reports.resolve() != reports:
        raise ValueError("Validation reports must stay within the repository.")
    reports.mkdir(parents=True, exist_ok=True)
    py = [sys.executable, "-B"]
    junit = reports / "unit.junit.xml"
    jobs = {
        "ruff": [*py, "-m", "ruff", "check", "--no-cache"],
        "ruff-format": [*py, "-m", "ruff", "format", "--check", "--no-cache"],
        "javascript": [*py, "scripts/lint_web.py"],
        "unit": [*py, "-m", "pytest", f"--basetemp={working / 'pytest'}", f"--junitxml={junit}"],
        "build": [*py, "scripts/build.py"],
        "chrome": [*py, "scripts/check_browser.py"],
    }
    results = {}
    for name, command in jobs.items():
        if name == "chrome" and results["build"]["exit_code"] != 0:
            results[name] = {"exit_code": None, "reason": "build failed"}
            continue
        begin = time.monotonic()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        (reports / f"{name}.log").write_text(result.stdout, encoding="utf-8")
        results[name] = {"exit_code": result.returncode, "seconds": round(time.monotonic() - begin, 3)}
        print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
        if result.returncode:
            print(result.stdout, flush=True)
    unit = {}
    if junit.is_file():
        suite = ElementTree.parse(junit).getroot().find("testsuite")
        if suite is not None:
            unit = {name: int(suite.get(name, 0)) for name in ("tests", "failures", "errors", "skipped")}
    browser_checks = 0
    if results["chrome"]["exit_code"] == 0:
        browser_checks = sum(
            line.startswith("PASS ") for line in (reports / "chrome.log").read_text("utf-8").splitlines()
        )
    summary = {
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "python": platform.python_version(),
        "node": subprocess.check_output(["node", "--version"], cwd=ROOT, text=True).strip(),
        "unit": unit,
        "chrome_checkpoints": browser_checks,
        "jobs": results,
    }
    (reports / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if all(job["exit_code"] == 0 for job in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
