#!/usr/bin/python3
"""Create numbered Windows Chromium profile launchers."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "apps_windows"
DEFAULT_PROFILE_DIR = ROOT / "profiles_windows"
DEFAULT_CONFIG_PATH = ROOT / "profiles" / "profiles.windows.json"

WINDOWS_BROWSER_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Chromium\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Chromium\Application\chrome.exe"),
]


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def font_for(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    from PIL import ImageFont

    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def make_numbered_icon(number: int, target_ico: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (256, 256), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 238, 238), radius=56, fill=(33, 115, 245, 255))
    draw.rounded_rectangle((28, 28, 228, 228), radius=48, outline=(255, 255, 255, 220), width=6)

    text = str(number)
    font_size = 112 if len(text) <= 2 else 92
    font = font_for(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (256 - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = (256 - (bbox[3] - bbox[1])) / 2 - bbox[1] - 6
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    target_ico.parent.mkdir(parents=True, exist_ok=True)
    image.save(target_ico, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])


def normalize_open_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "chrome-extension://")):
        return value
    if "://" in value:
        return value
    return f"https://{value}"


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
        "name": "Profile Bootstrap",
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


def batch_quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def wrapper_cmd(profile_dir: Path, chromium_exe: Path, extra_args: list[str], open_urls: list[str]) -> str:
    arg_lines = [f"  {batch_quote(str(arg))} ^" for arg in extra_args]
    url_lines = [f"  {batch_quote(url)} ^" for url in (normalize_open_url(item) for item in open_urls) if url]
    lines = [
        "@echo off",
        "setlocal",
        f"set \"EXECUTABLE={chromium_exe}\"",
        f"set \"PROFILE_DIR={profile_dir}\"",
        'if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"',
        "start \"\" \"%EXECUTABLE%\" ^",
        '  --user-data-dir="%PROFILE_DIR%" ^',
        "  --no-first-run ^",
        "  --no-default-browser-check ^",
    ]
    lines.extend(arg_lines)
    lines.extend(url_lines)
    lines.append("  %*")
    lines.append("endlocal")
    return "\r\n".join(lines) + "\r\n"


def wrapper_vbs(cmd_path: Path) -> str:
    return textwrap.dedent(
        f"""\
        Set shell = CreateObject("WScript.Shell")
        shell.Run Chr(34) & "{cmd_path}" & Chr(34), 0, False
        """
    )


def shortcut_script(target_path: Path, shortcut_path: Path, icon_path: Path, working_dir: Path) -> str:
    return textwrap.dedent(
        f"""\
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut({json.dumps(str(shortcut_path), ensure_ascii=False)})
        $shortcut.TargetPath = {json.dumps(str(target_path), ensure_ascii=False)}
        $shortcut.WorkingDirectory = {json.dumps(str(working_dir), ensure_ascii=False)}
        $shortcut.IconLocation = {json.dumps(str(icon_path), ensure_ascii=False)}
        $shortcut.Save()
        """
    )


def create_windows_shortcut(target_path: Path, shortcut_path: Path, icon_path: Path, working_dir: Path) -> None:
    script = shortcut_script(target_path, shortcut_path, icon_path, working_dir)
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )


def sanitized_name(name: str) -> str:
    clean = str(name or "资料").replace("/", " ").replace("\\", " ").replace(":", " ").strip()
    return clean[:50] or "资料"


def next_number(profiles: list[dict]) -> int:
    used = {int(item["number"]) for item in profiles}
    number = 1
    while number in used:
        number += 1
    return number


def load_profiles(config_path: Path) -> list[dict]:
    if not config_path.exists():
        return []
    return json.loads(config_path.read_text(encoding="utf-8")).get("profiles", [])


def save_profiles(config_path: Path, profiles: list[dict]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def detect_windows_browser() -> Path | None:
    for candidate in WINDOWS_BROWSER_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def create_profile_launcher(
    source_exe: Path,
    output_dir: Path,
    profile_root: Path,
    number: int,
    app_name: str,
    display_number: int,
    extra_args: list[str],
    cookies_text: str,
    open_urls: list[str],
    force: bool,
) -> dict:
    profile_name = sanitized_name(app_name)
    app_dir = output_dir / f"profile-{number}" / profile_name
    cmd_path = app_dir / f"{profile_name}.cmd"
    vbs_path = app_dir / f"{profile_name}.vbs"
    shortcut_path = app_dir / f"{profile_name}.lnk"
    icon_path = app_dir / f"{profile_name}.ico"
    profile_dir = profile_root / f"profile-{number}"

    if app_dir.exists() and force:
        remove_path(app_dir)
    elif app_dir.exists():
        raise FileExistsError(f"{app_dir} exists; pass --force to rebuild it")

    app_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile_args = list(extra_args)
    bootstrap_extension = create_bootstrap_extension(profile_dir, cookies_text)
    if bootstrap_extension is not None:
        profile_args.append(f"--load-extension={bootstrap_extension.resolve()}")

    cmd_path.write_text(
        wrapper_cmd(profile_dir.resolve(), source_exe.resolve(), profile_args, open_urls),
        encoding="utf-8",
        newline="\r\n",
    )
    vbs_path.write_text(wrapper_vbs(cmd_path.resolve()), encoding="utf-8", newline="\r\n")
    make_numbered_icon(display_number, icon_path)
    if os.name == "nt":
        create_windows_shortcut(vbs_path.resolve(), shortcut_path.resolve(), icon_path.resolve(), app_dir.resolve())

    return {
        "app_dir": str(app_dir.resolve()),
        "app_path": str(vbs_path.resolve()),
        "shortcut_path": str(shortcut_path.resolve()),
        "launcher_path": str(cmd_path.resolve()),
        "icon_path": str(icon_path.resolve()),
        "profile_path": str(profile_dir.resolve()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create numbered Chromium profile launchers for Windows.")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--source-exe", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--app-name", default="资料")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--display-number", type=int)
    parser.add_argument("--fingerprint-base", type=int, default=10000)
    parser.add_argument("--cookie-json", default="")
    parser.add_argument("--remark", default="")
    parser.add_argument("--proxy", default="")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="extra Chromium command-line argument; can be repeated",
    )
    parser.add_argument(
        "--open-url",
        action="append",
        default=[],
        help="URL to open on browser startup; can be repeated",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_exe = (args.source_exe.expanduser() if args.source_exe else detect_windows_browser())
    if source_exe is None or not source_exe.exists():
        raise SystemExit(
            "Source executable not found. Install Chrome/Chromium or pass --source-exe "
            r'"C:\Program Files\Google\Chrome\Application\chrome.exe"'
        )

    profiles = load_profiles(args.config)
    created: list[dict] = []
    for index in range(args.count):
        number = next_number(profiles)
        fingerprint = args.fingerprint_base + number - 1
        display_number = args.display_number if args.display_number is not None and args.count == 1 else number
        extra_args = [
            f"--fingerprint-platform=windows",
            f"--fingerprint-brand-version=148",
            f"--fingerprint={fingerprint}",
            f"--lang={args.language}",
            f"--accept-lang={args.language}",
            f"--timezone={args.timezone}",
        ]
        if args.proxy.strip():
            extra_args.append(f"--proxy-server={args.proxy.strip()}")
        extra_args.extend(args.extra_arg)

        launcher = create_profile_launcher(
            source_exe=source_exe,
            output_dir=args.output_dir,
            profile_root=args.profile_dir,
            number=number,
            app_name=args.app_name,
            display_number=display_number,
            extra_args=extra_args,
            cookies_text=args.cookie_json,
            open_urls=args.open_url,
            force=args.force,
        )

        profile = {
            "number": number,
            "display_number": display_number,
            "name": sanitized_name(args.app_name),
            "fingerprint": fingerprint,
            "app_path": launcher["app_path"],
            "app_dir": launcher["app_dir"],
            "launcher_path": launcher["launcher_path"],
            "icon_path": launcher["icon_path"],
            "profile_path": launcher["profile_path"],
            "args": extra_args,
            "proxy": args.proxy.strip() or None,
            "remark": args.remark.strip() or None,
            "open_urls": [url for url in (normalize_open_url(item) for item in args.open_url) if url] or None,
            "cookie_json": args.cookie_json or None,
            "fingerprint_config": {
                "platform": "windows",
                "chrome_version": "148",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.215 Safari/537.36",
                "width": 1280,
                "height": 720,
                "device_scale_factor": "1",
                "cpu_cores": 8,
                "memory_gb": 8,
                "webrtc_policy": "disable-non-proxied-udp",
            },
            "platform_target": "windows",
        }
        profiles.append(profile)
        profiles.sort(key=lambda item: int(item["number"]))
        created.append(profile)

    save_profiles(args.config, profiles)
    print("Created Windows profiles:")
    for item in created:
        print(f"  [{item['number']}] {item['name']} -> {item['app_path']}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
