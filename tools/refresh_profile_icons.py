#!/usr/bin/python3
"""Refresh profile app icons and optionally restart Dock."""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
import time
from pathlib import Path

import create_fingerprint_profiles as gen


ROOT = Path(__file__).resolve().parents[1]
PROFILES_JSON = ROOT / "profiles" / "profiles.json"
SOURCE_ICON = Path("/Applications/Chromium.app/Contents/Resources/app.icns")
LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)


def refresh(restart_dock: bool) -> None:
    data = json.loads(PROFILES_JSON.read_text(encoding="utf-8"))
    work = ROOT / "apps" / ".icon-work-refresh"
    base = gen.icon_base_image(SOURCE_ICON, work)
    version = str(int(time.time()))

    for profile in data.get("profiles", []):
        app = Path(profile["app_path"])
        number = int(profile.get("display_number") or profile["number"])
        resources = app / "Contents" / "Resources"
        profile_icon = resources / "profile.icns"
        app_icon = resources / "app.icns"
        gen.make_numbered_icon(base, number, profile_icon, work)
        shutil.copy2(profile_icon, app_icon)

        assets = resources / "Assets.car"
        if assets.exists():
            disabled = resources / "Assets.car.disabled"
            if disabled.exists():
                disabled.unlink()
            assets.rename(disabled)

        info = app / "Contents" / "Info.plist"
        with info.open("rb") as f:
            plist = plistlib.load(f)
        plist["CFBundleIconFile"] = "app.icns"
        plist.pop("CFBundleIconName", None)
        plist["CFBundleVersion"] = version
        with info.open("wb") as f:
            plistlib.dump(plist, f)

        subprocess.run(["touch", str(app)], check=True)
        subprocess.run(["xattr", "-cr", str(app)], check=True)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
        subprocess.run([str(LSREGISTER), "-f", str(app)], check=False)
        print(f"已刷新图标: {profile.get('name')} -> {number}")

    shutil.rmtree(work, ignore_errors=True)
    if restart_dock:
        subprocess.run(["killall", "Dock"], check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart-dock", action="store_true", help="重启 Dock 图标缓存")
    args = parser.parse_args()
    refresh(args.restart_dock)


if __name__ == "__main__":
    main()
