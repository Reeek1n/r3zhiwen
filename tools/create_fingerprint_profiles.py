#!/usr/bin/python3
"""Create numbered macOS Chromium profile apps.

Each generated .app has:
  - its own CFBundleIdentifier
  - a numbered icon
  - a fixed --user-data-dir profile directory
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "apps"
DEFAULT_PROFILE_DIR = ROOT / "profiles"


def default_source_app() -> Path:
    for candidate in (
        Path("/Applications/Chromium.app"),
        Path("/Applications/Google Chrome.app"),
    ):
        if candidate.exists():
            return candidate
    return Path("/Applications/Chromium.app")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def font_for(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def icon_base_image(source_icon: Path, work_dir: Path) -> Image.Image:
    iconset = work_dir / "source.iconset"
    remove_path(iconset)
    run(["iconutil", "-c", "iconset", str(source_icon), "-o", str(iconset)])

    pngs = sorted(iconset.glob("*.png"), key=lambda p: p.stat().st_size, reverse=True)
    if not pngs:
        raise RuntimeError(f"No PNGs extracted from {source_icon}")

    return Image.open(pngs[0]).convert("RGBA").resize((1024, 1024), Image.LANCZOS)


def make_numbered_icon(base: Image.Image, number: int, target_icns: Path, work_dir: Path) -> None:
    image = base.copy()
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    badge_size = 410 if number < 100 else 470
    margin = 72
    left = image.width - badge_size - margin
    top = image.height - badge_size - margin
    right = image.width - margin
    bottom = image.height - margin

    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=badge_size // 2,
        fill=(24, 119, 242, 245),
        outline=(255, 255, 255, 255),
        width=28,
    )

    text = str(number)
    font_size = 250 if len(text) <= 2 else 200
    font = font_for(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = left + (badge_size - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = top + (badge_size - (bbox[3] - bbox[1])) / 2 - bbox[1] - 10
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    image = Image.alpha_composite(image, overlay)

    iconset = work_dir / f"profile-{number}.iconset"
    remove_path(iconset)
    iconset.mkdir(parents=True)

    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for size, name in sizes:
        image.resize((size, size), Image.LANCZOS).save(iconset / name)

    remove_path(target_icns)
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(target_icns)])


def normalize_open_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "chrome-extension://")):
        return value
    if "://" in value:
        return value
    return f"https://{value}"


def chromium_executable(source_app: Path) -> Path:
    with (source_app / "Contents" / "Info.plist").open("rb") as f:
        plist = plistlib.load(f)
    executable = plist.get("CFBundleExecutable", "Chromium")
    return source_app / "Contents" / "MacOS" / executable


def wrapper_script(
    profile_dir: Path,
    chromium_binary: Path,
    extra_args: list[str],
    open_urls: list[str],
) -> str:
    quoted_extra = " ".join(f'"{arg}"' for arg in extra_args)
    quoted_urls = " ".join(f'"{url}"' for url in (normalize_open_url(item) for item in open_urls) if url)
    return textwrap.dedent(
        f"""\
        #!/bin/zsh
        set -e

        EXECUTABLE="{chromium_binary}"
        PROFILE_DIR="{profile_dir}"

        mkdir -p "$PROFILE_DIR"
        exec "$EXECUTABLE" \\
          --user-data-dir="$PROFILE_DIR" \\
          --no-first-run \\
          --no-default-browser-check \\
          {quoted_extra} \\
          {quoted_urls} \\
          "$@"
        """
    )


def parse_cookie_text(cookie_text: str) -> list[dict]:
    if not cookie_text.strip():
        return []
    try:
        parsed = json.loads(cookie_text)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(cookie_text)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("Cookie must be a JSON array or object")
    return [item for item in parsed if isinstance(item, dict)]


def create_bootstrap_extension(profile_dir: Path, cookies_text: str) -> Path | None:
    cookies = parse_cookie_text(cookies_text)
    if not cookies:
        return None

    extension_dir = profile_dir / "bootstrap_extension"
    remove_path(extension_dir)
    extension_dir.mkdir(parents=True)

    manifest = {
        "manifest_version": 3,
        "name": "资料启动助手",
        "version": "1.0",
        "permissions": ["cookies", "storage"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "worker.js"},
        "content_scripts": [
            {
                "matches": ["<all_urls>"],
                "js": ["content.js"],
                "run_at": "document_start",
            }
        ],
    }
    (extension_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    import_id = hashlib.sha256(
        json.dumps(cookies, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    worker = f"""
const cookies = {json.dumps(cookies, ensure_ascii=False)};
const importId = {json.dumps(import_id)};
const importKey = "cookie-import:" + importId;

function cookieUrl(cookie) {{
  if (cookie.url) return cookie.url;
  const domain = String(cookie.domain || "").replace(/^\\./, "");
  if (!domain) return null;
  const scheme = cookie.secure === false ? "http" : "https";
  const path = cookie.path || "/";
  return `${{scheme}}://${{domain}}${{path}}`;
}}

async function importCookies() {{
  for (const source of cookies) {{
    const cookie = {{ ...source }};
    cookie.url = cookieUrl(cookie);
    if (!cookie.url || !cookie.name) continue;
    delete cookie.hostOnly;
    delete cookie.session;
    delete cookie.storeId;
    delete cookie.sameSite;
    try {{
      await chrome.cookies.set(cookie);
    }} catch (error) {{
      console.warn("Cookie import failed", cookie.name, error);
    }}
  }}
}}

async function boot() {{
  const state = await chrome.storage.local.get(importKey);
  if (state[importKey]) return;
  await importCookies();
  await chrome.storage.local.set({{ [importKey]: true }});
}}

chrome.runtime.onInstalled.addListener(boot);
chrome.runtime.onStartup.addListener(boot);
chrome.runtime.onMessage.addListener((message) => {{
  if (message && message.type === "import-cookies") {{
    boot();
  }}
}});
"""
    (extension_dir / "worker.js").write_text(worker.strip() + "\n", encoding="utf-8")
    (extension_dir / "content.js").write_text(
        'chrome.runtime.sendMessage({ type: "import-cookies" }).catch(() => {});\n',
        encoding="utf-8",
    )
    return extension_dir


def write_plist(plist_path: Path, number: int, bundle_prefix: str, app_name: str) -> None:
    plist = {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleDisplayName": app_name,
        "CFBundleExecutable": "FingerprintLauncher",
        "CFBundleIdentifier": f"{bundle_prefix}.profile{number}",
        "CFBundleIconFile": "app.icns",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": app_name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as f:
        plistlib.dump(plist, f)


def update_localized_display_names(resources_dir: Path, app_name: str) -> None:
    content = f'CFBundleDisplayName = "{app_name}";\nCFBundleName = "{app_name}";\n'
    for path in resources_dir.rglob("InfoPlist.strings"):
        path.write_text(content, encoding="utf-8")


def create_profile_app(
    source_app: Path,
    output_dir: Path,
    profile_root: Path,
    number: int,
    bundle_prefix: str,
    app_name: str,
    base_icon: Image.Image,
    force: bool,
    extra_args: list[str],
    fingerprint_seed: int | None,
    cookies_text: str,
    open_urls: list[str],
) -> Path:
    target_app = output_dir / f"profile-{number}" / f"{app_name}.app"
    profile_dir = profile_root / f"profile-{number}"

    if target_app.exists():
        if not force:
            raise FileExistsError(f"{target_app} exists; pass --force to rebuild it")
        remove_path(target_app)

    output_dir.mkdir(parents=True, exist_ok=True)
    target_app.parent.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    contents_dir = target_app / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    info_plist = contents_dir / "Info.plist"
    write_plist(info_plist, number, bundle_prefix, app_name)

    launcher = macos_dir / "FingerprintLauncher"
    profile_args = list(extra_args)
    if fingerprint_seed is not None:
        profile_args.insert(0, f"--fingerprint={fingerprint_seed}")
    bootstrap_extension = create_bootstrap_extension(profile_dir, cookies_text)
    if bootstrap_extension is not None:
        profile_args.append(f"--load-extension={bootstrap_extension.resolve()}")

    launcher.write_text(
        wrapper_script(profile_dir.resolve(), chromium_executable(source_app).resolve(), profile_args, open_urls),
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    profile_icon = resources_dir / "profile.icns"
    runtime_icon = resources_dir / "app.icns"
    make_numbered_icon(base_icon, number, profile_icon, output_dir / ".icon-work")
    shutil.copy2(profile_icon, runtime_icon)
    update_localized_display_names(resources_dir, app_name)

    run(["xattr", "-cr", str(target_app)])
    run(["codesign", "--force", "--deep", "--sign", "-", str(target_app)])
    return target_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create numbered Chromium profile apps for macOS."
    )
    parser.add_argument("--count", type=int, required=True, help="number of profile apps")
    parser.add_argument("--start", type=int, default=1, help="first profile number")
    parser.add_argument("--source-app", type=Path, default=default_source_app())
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--app-name", default="资料")
    parser.add_argument("--bundle-prefix", default="local.chromium.fingerprint")
    parser.add_argument("--force", action="store_true", help="replace existing generated apps")
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="extra Chromium command-line argument; can be repeated",
    )
    parser.add_argument(
        "--fingerprint-base",
        type=int,
        help="add --fingerprint for each created profile; seeds increment from this base",
    )
    parser.add_argument("--cookie-json", default="", help="cookies to import on browser startup")
    parser.add_argument(
        "--open-url",
        action="append",
        default=[],
        help="URL to open on browser startup; can be repeated",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_app = args.source_app.expanduser().resolve()
    if not source_app.exists():
        raise SystemExit(f"Source app not found: {source_app}")

    source_icon = source_app / "Contents" / "Resources" / "app.icns"
    if not source_icon.exists():
        raise SystemExit(f"Source icon not found: {source_icon}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    base_icon = icon_base_image(source_icon, args.output_dir / ".icon-work")

    created = []
    for index, number in enumerate(range(args.start, args.start + args.count)):
        created.append(
            create_profile_app(
                source_app=source_app,
                output_dir=args.output_dir,
                profile_root=args.profile_dir,
                number=number,
                bundle_prefix=args.bundle_prefix,
                app_name=args.app_name,
                base_icon=base_icon,
                force=args.force,
                extra_args=args.extra_arg,
                fingerprint_seed=(
                    None if args.fingerprint_base is None else args.fingerprint_base + index
                ),
                cookies_text=args.cookie_json,
                open_urls=args.open_url,
            )
        )

    shutil.rmtree(args.output_dir / ".icon-work", ignore_errors=True)
    print("已创建:")
    for app in created:
        print(f"  {app}")
    print(f"资料目录: {args.profile_dir.resolve()}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
