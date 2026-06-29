#!/usr/bin/python3
"""Small macOS profile manager for fingerprint Chromium builds."""

from __future__ import annotations

import json
import subprocess
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from create_fingerprint_profiles import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROFILE_DIR,
    DEFAULT_SOURCE_APP,
    create_profile_app,
    icon_base_image,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "profiles" / "profiles.json"


@dataclass
class Profile:
    number: int
    name: str
    fingerprint: int
    app_path: str
    profile_path: str
    args: list[str]


def load_profiles() -> list[Profile]:
    if not CONFIG_PATH.exists():
        return []
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Profile(**item) for item in raw.get("profiles", [])]


def save_profiles(profiles: list[Profile]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump({"profiles": [asdict(item) for item in profiles]}, f, indent=2)


def split_args(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class Manager(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("指纹浏览器")
        self.geometry("980x620")
        self.minsize(860, 540)

        self.profiles = load_profiles()

        self.source_app = tk.StringVar(value=str(DEFAULT_SOURCE_APP))
        self.app_name = tk.StringVar(value="资料")
        self.fingerprint_base = tk.IntVar(value=10000)
        self.language = tk.StringVar(value="zh-CN")
        self.timezone = tk.StringVar(value="Asia/Shanghai")
        self.proxy = tk.StringVar(value="")

        self.create_widgets()
        self.refresh()

    def create_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        settings = ttk.Frame(self, padding=12)
        settings.grid(row=0, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="浏览器 App").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.source_app).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(settings, text="选择", command=self.choose_source).grid(row=0, column=2)

        ttk.Label(settings, text="资料名称").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.app_name, width=22).grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))

        defaults = ttk.Frame(settings)
        defaults.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        for index in range(8):
            defaults.columnconfigure(index, weight=1)

        ttk.Label(defaults, text="指纹种子").grid(row=0, column=0, sticky="w")
        ttk.Entry(defaults, textvariable=self.fingerprint_base, width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(defaults, text="语言").grid(row=0, column=2, sticky="w")
        ttk.Entry(defaults, textvariable=self.language, width=12).grid(row=0, column=3, sticky="w")
        ttk.Label(defaults, text="时区").grid(row=0, column=4, sticky="w")
        ttk.Entry(defaults, textvariable=self.timezone, width=18).grid(row=0, column=5, sticky="w")
        ttk.Label(defaults, text="代理").grid(row=0, column=6, sticky="w")
        ttk.Entry(defaults, textvariable=self.proxy, width=26).grid(row=0, column=7, sticky="ew")

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        table_frame = ttk.Frame(body)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        body.add(table_frame, weight=3)

        columns = ("number", "name", "fingerprint", "profile")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.table.heading("number", text="#")
        self.table.heading("name", text="资料")
        self.table.heading("fingerprint", text="指纹")
        self.table.heading("profile", text="数据目录")
        self.table.column("number", width=52, anchor="center", stretch=False)
        self.table.column("name", width=160)
        self.table.column("fingerprint", width=110, anchor="center")
        self.table.column("profile", width=360)
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.bind("<Double-1>", lambda _event: self.open_selected())

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        side = ttk.Frame(body, padding=(12, 0, 0, 0))
        body.add(side, weight=1)
        side.columnconfigure(0, weight=1)

        ttk.Button(side, text="创建资料", command=self.create_profile).grid(row=0, column=0, sticky="ew")
        ttk.Button(side, text="打开窗口", command=self.open_selected).grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(side, text="在访达中显示", command=self.reveal_selected).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(side, text="Delete From List", command=self.delete_selected).grid(row=3, column=0, sticky="ew", pady=(8, 0))

        ttk.Label(side, text="额外启动参数，每行一个").grid(row=4, column=0, sticky="w", pady=(24, 4))
        self.extra_args = tk.Text(side, height=12, width=36)
        self.extra_args.grid(row=5, column=0, sticky="nsew")
        self.extra_args.insert(
            "1.0",
            "--fingerprint-platform=macos\n--disable-non-proxied-udp\n",
        )
        side.rowconfigure(5, weight=1)

    def choose_source(self) -> None:
        path = filedialog.askdirectory(
            title="选择浏览器 App",
            initialdir="/Applications",
        )
        if path:
            self.source_app.set(path)

    def refresh(self) -> None:
        self.table.delete(*self.table.get_children())
        for profile in sorted(self.profiles, key=lambda item: item.number):
            self.table.insert(
                "",
                tk.END,
                iid=str(profile.number),
                values=(profile.number, profile.name, profile.fingerprint, profile.profile_path),
            )

    def selected_profile(self) -> Profile | None:
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("指纹浏览器", "请先选择一个资料。")
            return None
        number = int(selection[0])
        return next((item for item in self.profiles if item.number == number), None)

    def next_number(self) -> int:
        used = {item.number for item in self.profiles}
        number = 1
        while number in used:
            number += 1
        return number

    def default_args(self, fingerprint: int) -> list[str]:
        args = [f"--fingerprint={fingerprint}"]
        if self.language.get().strip():
            lang = self.language.get().strip()
            args.extend([f"--lang={lang}", f"--accept-lang={lang}"])
        if self.timezone.get().strip():
            args.append(f"--timezone={self.timezone.get().strip()}")
        if self.proxy.get().strip():
            args.append(f"--proxy-server={self.proxy.get().strip()}")
        args.extend(split_args(self.extra_args.get("1.0", tk.END)))
        return args

    def create_profile(self) -> None:
        source_app = Path(self.source_app.get()).expanduser()
        if not source_app.exists():
            messagebox.showerror("指纹浏览器", f"找不到 App：\n{source_app}")
            return

        try:
            number = self.next_number()
            fingerprint = self.fingerprint_base.get() + number - 1
            name = f"{self.app_name.get().strip() or '资料'} {number}"
            base_icon = icon_base_image(source_app / "Contents" / "Resources" / "app.icns", DEFAULT_OUTPUT_DIR / ".icon-work")
            app_path = create_profile_app(
                source_app=source_app,
                output_dir=DEFAULT_OUTPUT_DIR,
                profile_root=DEFAULT_PROFILE_DIR,
                number=number,
                bundle_prefix="local.chromium.fingerprint",
                app_name=self.app_name.get().strip() or "Fingerprint",
                base_icon=base_icon,
                force=True,
                extra_args=self.default_args(fingerprint),
                fingerprint_seed=None,
            )
            profile = Profile(
                number=number,
                name=name,
                fingerprint=fingerprint,
                app_path=str(app_path.resolve()),
                profile_path=str((DEFAULT_PROFILE_DIR / f"profile-{number}").resolve()),
                args=self.default_args(fingerprint),
            )
            self.profiles.append(profile)
            save_profiles(self.profiles)
            self.refresh()
            self.table.selection_set(str(number))
            self.open_profile(profile)
        except Exception as exc:
            messagebox.showerror("指纹浏览器", str(exc))

    def open_profile(self, profile: Profile) -> None:
        subprocess.Popen(["open", "-n", profile.app_path])

    def open_selected(self) -> None:
        profile = self.selected_profile()
        if profile:
            self.open_profile(profile)

    def reveal_selected(self) -> None:
        profile = self.selected_profile()
        if profile:
            subprocess.Popen(["open", "-R", profile.app_path])

    def delete_selected(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        self.profiles = [item for item in self.profiles if item.number != profile.number]
        save_profiles(self.profiles)
        self.refresh()


def main() -> None:
    Manager().mainloop()


if __name__ == "__main__":
    main()
