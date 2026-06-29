#!/usr/bin/python3
"""Build the Windows manager exe with PyInstaller."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist_windows"
BUILD_DIR = ROOT / "build_windows"
SPEC_PATH = ROOT / "windows_manager.spec"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build 指纹浏览器 Windows manager exe.")
    parser.add_argument("--name", default="指纹浏览器-Windows")
    parser.add_argument("--console", action="store_true", help="build with console window")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        args.name,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(ROOT),
        "--paths",
        str(ROOT / "tools"),
        "--add-data",
        f"{ROOT / 'templates'}{';' if sys.platform == 'win32' else ':'}templates",
        "--add-data",
        f"{ROOT / 'tools'}{';' if sys.platform == 'win32' else ':'}tools",
    ]
    if not args.console:
        command.append("--windowed")
    command.append(str(ROOT / "tools" / "windows_manager.py"))
    subprocess.run(command, check=True)
    print(DIST_DIR / args.name)
    print(SPEC_PATH)


if __name__ == "__main__":
    main()
