#!/usr/bin/python3
"""Validate local profile persistence wiring."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILES_JSON = ROOT / "profiles" / "profiles.json"


def main() -> int:
    if not PROFILES_JSON.exists():
        print(f"缺少配置文件: {PROFILES_JSON}")
        return 1

    data = json.loads(PROFILES_JSON.read_text(encoding="utf-8"))
    ok = True
    for profile in data.get("profiles", []):
        number = int(profile["number"])
        name = profile.get("name") or f"profile-{number}"
        app_path = Path(profile["app_path"])
        profile_path = Path(profile["profile_path"])
        launcher = app_path / "Contents" / "MacOS" / "FingerprintLauncher"

        checks = [
            (app_path.exists(), "App 存在", app_path),
            (profile_path.exists(), "资料目录存在", profile_path),
            (launcher.exists(), "启动器存在", launcher),
        ]
        if launcher.exists():
            text = launcher.read_text(encoding="utf-8", errors="replace")
            checks.append((str(profile_path) in text, "启动器绑定资料目录", profile_path))
            checks.append(("--user-data-dir=" in text, "启动参数包含 user-data-dir", launcher))

        print(f"\n[{number}] {name}")
        for passed, label, path in checks:
            print(f"  {'OK' if passed else '失败'} {label}: {path}")
            ok = ok and passed

    backup = PROFILES_JSON.with_name("profiles.backup.json")
    print(f"\n配置文件: {PROFILES_JSON}")
    print(f"备份文件: {backup if backup.exists() else '暂无'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
