#!/usr/bin/python3
"""Local HTTP API for the macOS fingerprint browser manager."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("FINGERPRINT_DATA_ROOT", str(ROOT))).expanduser()
PROFILES_JSON = DATA_ROOT / "profiles" / "profiles.json"
TEMPLATES_DIR = ROOT / "templates"
API_KEY = os.environ.get("FINGERPRINT_API_KEY", "local-dev-key")
PORT = int(os.environ.get("FINGERPRINT_API_PORT", "18787"))


def source_app_path() -> Path:
    for candidate in (
        Path("/Applications/Chromium.app"),
        Path("/Applications/Google Chrome.app"),
    ):
        if candidate.exists():
            return candidate
    return Path("/Applications/Chromium.app")


def load_profiles() -> list[dict]:
    if not PROFILES_JSON.exists():
        return []
    with PROFILES_JSON.open("r", encoding="utf-8") as f:
        return json.load(f).get("profiles", [])


def save_profiles(profiles: list[dict]) -> None:
    PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
    if PROFILES_JSON.exists():
        backup = PROFILES_JSON.with_name("profiles.backup.json")
        try:
            shutil.copy2(PROFILES_JSON, backup)
        except OSError:
            pass
    temp = PROFILES_JSON.with_name(".profiles.json.tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump({"profiles": profiles}, f, ensure_ascii=False, indent=2)
    temp.replace(PROFILES_JSON)


def list_templates() -> list[dict]:
    if not TEMPLATES_DIR.exists():
        return []
    items = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append({"id": path.stem, "name": data.get("name", path.stem), "path": str(path)})
    return items


def load_template(template_id: str) -> dict:
    path = TEMPLATES_DIR / f"{template_id}.json"
    if not path.exists():
        raise FileNotFoundError(template_id)
    return json.loads(path.read_text(encoding="utf-8"))


def next_number(profiles: list[dict]) -> int:
    used = {int(item["number"]) for item in profiles}
    number = 1
    while number in used:
        number += 1
    return number


def normalize_open_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "chrome-extension://")):
        return value
    if "://" in value:
        return value
    return f"https://{value}"


def clean_name(name: str) -> str:
    value = str(name or "资料").replace("/", " ").replace(":", " ").strip()
    return value[:50] or "资料"


def app_path_for(name: str, number: int) -> Path:
    return DATA_ROOT / "apps" / f"profile-{number}" / f"{clean_name(name)}.app"


def running_processes() -> dict[int, int]:
    output = subprocess.check_output(["/bin/ps", "axo", "pid=,command="], text=True)
    running: dict[int, int] = {}
    for line in output.splitlines():
        if "/Contents/MacOS/Chromium" not in line or "Chromium Helper" in line:
            continue
        parts = line.strip().split(" ", 1)
        if len(parts) != 2:
            continue
        pid = int(parts[0])
        command = parts[1]
        marker = "--user-data-dir="
        if marker not in command:
            continue
        profile_path = command.split(marker, 1)[1].split(" ", 1)[0]
        name = Path(profile_path).name
        if name.startswith("profile-") and name.removeprefix("profile-").isdigit():
            running[int(name.removeprefix("profile-"))] = pid
    return running


def create_profile(payload: dict) -> dict:
    profiles = load_profiles()
    number = int(payload.get("number") or next_number(profiles))
    name = clean_name(payload.get("name") or "资料")
    seed_base = int(payload.get("fingerprint") or 10000 + number - 1)

    fingerprint_config = payload.get("fingerprint_config") or {}
    fingerprint_config = {
        "platform": fingerprint_config.get("platform", "macos"),
        "chrome_version": fingerprint_config.get("chrome_version", "148"),
        "user_agent": fingerprint_config.get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.215 Safari/537.36",
        ),
        "width": int(fingerprint_config.get("width", 1280)),
        "height": int(fingerprint_config.get("height", 720)),
        "device_scale_factor": str(fingerprint_config.get("device_scale_factor", "1")),
        "cpu_cores": int(fingerprint_config.get("cpu_cores", 8)),
        "memory_gb": int(fingerprint_config.get("memory_gb", 8)),
        "webrtc_policy": fingerprint_config.get("webrtc_policy", "disable-non-proxied-udp"),
    }

    args = [
        f"--fingerprint-platform={fingerprint_config['platform']}",
        f"--fingerprint-brand-version={fingerprint_config['chrome_version']}",
        f"--user-agent={fingerprint_config['user_agent']}",
        f"--window-size={fingerprint_config['width']},{fingerprint_config['height']}",
        f"--force-device-scale-factor={fingerprint_config['device_scale_factor']}",
        f"--fingerprint-hardware-concurrency={fingerprint_config['cpu_cores']}",
    ]
    if fingerprint_config["webrtc_policy"] == "disable-non-proxied-udp":
        args.append("--disable-non-proxied-udp")
    language = payload.get("language") or "zh-CN"
    timezone = payload.get("timezone") or "Asia/Shanghai"
    proxy = payload.get("proxy") or ""
    if language:
        args += [f"--lang={language}", f"--accept-lang={language}"]
    if timezone:
        args.append(f"--timezone={timezone}")
    if proxy:
        args.append(f"--proxy-server={proxy}")
    args += payload.get("extra_args") or []
    open_urls = [url for url in (normalize_open_url(item) for item in payload.get("open_urls") or []) if url]

    command = [
        "/usr/bin/python3",
        str(ROOT / "tools" / "create_fingerprint_profiles.py"),
        "--count",
        "1",
        "--start",
        str(number),
        "--source-app",
        str(payload.get("source_app") or source_app_path()),
        "--output-dir",
        str(DATA_ROOT / "apps"),
        "--profile-dir",
        str(DATA_ROOT / "profiles"),
        "--app-name",
        name,
        "--fingerprint-base",
        str(seed_base),
        "--force",
        "--cookie-json",
        payload.get("cookie_json") or "",
    ]
    for url in open_urls:
        command.append(f"--open-url={url}")
    for arg in args:
        command.append(f"--extra-arg={arg}")
    subprocess.check_call(command, cwd=DATA_ROOT)

    profile = {
        "number": number,
        "display_number": int(payload.get("display_number") or number),
        "name": name,
        "fingerprint": seed_base,
        "app_path": str(app_path_for(name, number)),
        "profile_path": str(DATA_ROOT / "profiles" / f"profile-{number}"),
        "args": args,
        "proxy": proxy or None,
        "remark": payload.get("remark") or None,
        "open_urls": open_urls or None,
        "cookie_json": payload.get("cookie_json") or None,
        "fingerprint_config": fingerprint_config,
    }
    profiles = [item for item in profiles if int(item["number"]) != number]
    profiles.append(profile)
    profiles.sort(key=lambda item: int(item["number"]))
    save_profiles(profiles)
    return profile


def create_batch(payload: dict) -> list[dict]:
    count = max(1, min(100, int(payload.get("count", 1))))
    name = payload.get("name") or "资料"
    created = []
    for _ in range(count):
        item_payload = dict(payload)
        item_payload.pop("count", None)
        item_payload["name"] = name
        item_payload.pop("number", None)
        created.append(create_profile(item_payload))
    return created


def open_profile(number: int) -> None:
    profile = next(item for item in load_profiles() if int(item["number"]) == number)
    subprocess.Popen(["open", "-n", profile["app_path"]])


def open_all() -> int:
    count = 0
    for profile in load_profiles():
        subprocess.Popen(["open", "-n", profile["app_path"]])
        count += 1
    return count


def close_profile(number: int) -> bool:
    pid = running_processes().get(number)
    if not pid:
        return False
    os.kill(pid, 15)
    return True


def close_all() -> int:
    count = 0
    for pid in running_processes().values():
        os.kill(pid, 15)
        count += 1
    return count


def clear_profile(number: int) -> None:
    profile_dir = ROOT / "profiles" / f"profile-{number}"
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)


def delete_profile(number: int) -> bool:
    close_profile(number)
    profiles = load_profiles()
    profile = next((item for item in profiles if int(item["number"]) == number), None)
    if not profile:
        return False
    for key in ("app_path", "profile_path"):
        path = Path(profile[key])
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    save_profiles([item for item in profiles if int(item["number"]) != number])
    return True


def update_profile(number: int, payload: dict) -> dict:
    profiles = load_profiles()
    for item in profiles:
        if int(item["number"]) == number:
            for key in ("name", "proxy", "remark", "open_urls", "cookie_json", "fingerprint_config", "args"):
                if key in payload:
                    item[key] = (
                        [url for url in (normalize_open_url(value) for value in payload[key] or []) if url]
                        if key == "open_urls"
                        else payload[key]
                    )
            save_profiles(profiles)
            return item
    raise KeyError(f"profile {number} not found")


class Handler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _authorized(self) -> bool:
        return self.headers.get("X-API-Key") == API_KEY

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"ok": True})
        elif path == "/templates":
            self._send(200, {"templates": list_templates()})
        elif path.startswith("/templates/"):
            self._send(200, {"template": load_template(path.split("/")[2])})
        elif path == "/profiles":
            running = running_processes()
            profiles = load_profiles()
            for item in profiles:
                item["running"] = int(item["number"]) in running
                item["pid"] = running.get(int(item["number"]))
            self._send(200, {"profiles": profiles})
        elif path.startswith("/profiles/"):
            number = int(path.split("/")[2])
            profile = next((item for item in load_profiles() if int(item["number"]) == number), None)
            if profile:
                self._send(200, {"profile": profile})
            else:
                self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        try:
            if path == "/profiles":
                self._send(200, {"profile": create_profile(self._read_json())})
            elif path == "/profiles/batch":
                self._send(200, {"profiles": create_batch(self._read_json())})
            elif path == "/profiles/open_all":
                self._send(200, {"opened": open_all()})
            elif path == "/profiles/close_all":
                self._send(200, {"closed": close_all()})
            elif path.startswith("/profiles/") and path.endswith("/open"):
                open_profile(int(path.split("/")[2]))
                self._send(200, {"ok": True})
            elif path.startswith("/profiles/") and path.endswith("/close"):
                self._send(200, {"closed": close_profile(int(path.split("/")[2]))})
            elif path.startswith("/profiles/") and path.endswith("/clear"):
                clear_profile(int(path.split("/")[2]))
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_PATCH(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        try:
            if path.startswith("/profiles/"):
                number = int(path.split("/")[2])
                self._send(200, {"profile": update_profile(number, self._read_json())})
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_DELETE(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        try:
            if path.startswith("/profiles/"):
                number = int(path.split("/")[2])
                self._send(200, {"deleted": delete_profile(number)})
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"本地 API 已启动: http://127.0.0.1:{PORT}")
    print(f"API Key: {API_KEY}")
    server.serve_forever()


if __name__ == "__main__":
    main()
