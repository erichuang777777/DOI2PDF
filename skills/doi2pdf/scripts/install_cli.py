"""Install the DOI2PDF CLI paired with this agent skill."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


RELEASE = "v0.7.0"
REPOSITORY = "https://github.com/erichuang777777/DOI2PDF.git"


def install_target() -> str:
    skill_dir = Path(__file__).resolve().parents[1]
    wheels = sorted((skill_dir / "assets").glob("doi2pdf-*.whl"))
    if wheels:
        return str(wheels[-1])
    repository_root = skill_dir.parents[1]
    if (repository_root / "pyproject.toml").is_file():
        return str(repository_root)
    return f"doi2pdf @ git+{REPOSITORY}@{RELEASE}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install DOI2PDF for this skill")
    parser.add_argument("--with-browser", action="store_true", help="Also install Playwright and Chromium for institutional login")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without changing the environment")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result")
    args = parser.parse_args(argv)

    extras = "web,browser" if args.with_browser else "web"
    target = install_target()
    if " @ git+" in target:
        package = target.replace("doi2pdf @", f"doi2pdf[{extras}] @", 1)
    else:
        package = f"{target}[{extras}]"
    commands = [[sys.executable, "-m", "pip", "install", package]]
    if args.with_browser:
        commands.append([sys.executable, "-m", "playwright", "install", "chromium"])

    if not args.dry_run:
        for command in commands:
            subprocess.run(command, check=True)

    payload = {"schema": 1, "ok": True, "target": target, "commands": commands, "dry_run": args.dry_run}
    print(json.dumps(payload) if args.json else "\n".join(" ".join(command) for command in commands))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
