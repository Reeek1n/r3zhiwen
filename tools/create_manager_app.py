#!/usr/bin/python3
"""Build the native macOS profile manager app."""

from __future__ import annotations

import plistlib
import os
import subprocess
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "指纹浏览器.app"
CONTENTS = APP_PATH / "Contents"
MACOS = CONTENTS / "MacOS"
RESOURCES = CONTENTS / "Resources"
BUILD_DIR = ROOT / ".build" / "manager-icon"
RUNTIME_DIR = RESOURCES / "runtime"


def run(command: list[str], env: dict | None = None) -> None:
    subprocess.run(command, check=True, env=env)


def browser_app_path() -> Path:
    for candidate in (
        Path("/Applications/Chromium.app"),
        Path("/Applications/Google Chrome.app"),
    ):
        if candidate.exists():
            return candidate
    return Path("/Applications/Chromium.app")


def font_for(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/SF-Pro-Display-Bold.otf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def build_manager_icon(target_icns: Path) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    source_icon = browser_app_path() / "Contents" / "Resources" / "app.icns"
    iconset_dir = BUILD_DIR / "source.iconset"
    if iconset_dir.exists():
        subprocess.run(["rm", "-rf", str(iconset_dir)], check=True)
    run(["iconutil", "-c", "iconset", str(source_icon), "-o", str(iconset_dir)])

    pngs = sorted(iconset_dir.glob("*.png"), key=lambda p: p.stat().st_size, reverse=True)
    if not pngs:
        raise RuntimeError("无法提取浏览器图标")

    image = Image.open(pngs[0]).convert("RGBA").resize((1024, 1024), Image.LANCZOS)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    panel = (168, 156, 866, 868)
    draw.rounded_rectangle(panel, radius=180, fill=(17, 24, 39, 228))
    draw.rounded_rectangle((212, 228, 812, 744), radius=120, fill=(244, 247, 252, 255))
    draw.rounded_rectangle((248, 268, 776, 516), radius=88, fill=(222, 232, 248, 255))
    draw.rounded_rectangle((316, 544, 708, 680), radius=68, fill=(59, 130, 246, 255))
    draw.rounded_rectangle((364, 592, 660, 632), radius=20, fill=(255, 255, 255, 210))

    badge_box = (612, 136, 898, 422)
    draw.ellipse(badge_box, fill=(37, 99, 235, 255), outline=(255, 255, 255, 255), width=26)
    font = font_for(178)
    text = "M"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_x = badge_box[0] + ((badge_box[2] - badge_box[0]) - (bbox[2] - bbox[0])) / 2 - bbox[0]
    text_y = badge_box[1] + ((badge_box[3] - badge_box[1]) - (bbox[3] - bbox[1])) / 2 - bbox[1] - 8
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))

    final = Image.alpha_composite(image, overlay)
    if target_icns.exists():
        target_icns.unlink()
    final.save(
        target_icns,
        format="ICNS",
        sizes=[
            (16, 16),
            (32, 32),
            (64, 64),
            (128, 128),
            (256, 256),
            (512, 512),
            (1024, 1024),
        ],
    )


def main() -> None:
    MACOS.mkdir(parents=True, exist_ok=True)
    RESOURCES.mkdir(parents=True, exist_ok=True)
    if RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
    (RUNTIME_DIR / "tools").mkdir(parents=True, exist_ok=True)
    (RUNTIME_DIR / "templates").mkdir(parents=True, exist_ok=True)
    module_cache = ROOT / ".build" / "swift-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["CLANG_MODULE_CACHE_PATH"] = str(module_cache)
    env["SWIFT_MODULECACHE_PATH"] = str(module_cache)
    run(
        [
            "/usr/bin/swiftc",
            "-O",
            "-framework",
            "AppKit",
            str(ROOT / "src" / "FingerprintManager.swift"),
            "-o",
            str(MACOS / "FingerprintManager"),
        ],
        env=env,
    )
    shutil.copy2(ROOT / "tools" / "create_fingerprint_profiles.py", RUNTIME_DIR / "tools" / "create_fingerprint_profiles.py")
    shutil.copy2(ROOT / "tools" / "local_api.py", RUNTIME_DIR / "tools" / "local_api.py")
    shutil.copy2(ROOT / "templates" / "default.json", RUNTIME_DIR / "templates" / "default.json")
    shutil.copy2(ROOT / "templates" / "default.windows.json", RUNTIME_DIR / "templates" / "default.windows.json")
    build_manager_icon(RESOURCES / "manager.icns")
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": "指纹浏览器",
        "CFBundleExecutable": "FingerprintManager",
        "CFBundleIdentifier": "local.chromium.fingerprint.manager",
        "CFBundleIconFile": "manager.icns",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "指纹浏览器",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    with (CONTENTS / "Info.plist").open("wb") as f:
        plistlib.dump(plist, f)

    run(["xattr", "-cr", str(APP_PATH)])
    run(["codesign", "--force", "--deep", "--sign", "-", str(APP_PATH)])
    os.utime(APP_PATH, None)
    os.utime(CONTENTS, None)
    os.utime(RESOURCES, None)
    print(APP_PATH)


if __name__ == "__main__":
    main()
