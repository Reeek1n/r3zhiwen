#!/usr/bin/python3
"""Windows profile manager for Chromium launchers."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tkinter as tk
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from tkinter import filedialog, messagebox, ttk

from create_windows_profiles import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROFILE_DIR,
    create_profile_launcher,
    detect_windows_browser,
    load_profiles,
    normalize_open_url,
    sanitized_name,
    save_profiles,
)


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_LOG_PATH = ROOT / "logs" / "windows_manager.log"
CREATE_NO_WINDOW = 0x08000000


def configure_logging() -> None:
    WINDOWS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=WINDOWS_LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def show_fatal_error(message: str) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("指纹浏览器 Windows 版", message)
        root.destroy()
    except Exception:
        pass


def startup_url_args(open_urls: Sequence[str]) -> list[str]:
    return [url for url in (normalize_open_url(item) for item in open_urls) if url]


def browser_launch_args(profile: dict, source_exe: Path) -> list[str]:
    browser_exe = Path(str(profile.get("browser_exe_path") or source_exe))
    profile_path = str(Path(str(profile["profile_path"])))
    args = [
        str(browser_exe),
        f"--user-data-dir={profile_path}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    args.extend(str(item) for item in profile.get("args") or [])
    args.extend(startup_url_args(profile.get("open_urls") or []))
    return args


@dataclass
class FingerprintConfig:
    platform: str = "windows"
    chrome_version: str = "148"
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.215 Safari/537.36"
    width: int = 1280
    height: int = 720
    device_scale_factor: str = "1"
    cpu_cores: int = 8
    memory_gb: int = 8
    webrtc_policy: str = "disable-non-proxied-udp"


class Manager(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("指纹浏览器 Windows 版")
        self.geometry("1220x760")
        self.minsize(1040, 640)

        self.config_path = DEFAULT_CONFIG_PATH
        self.output_dir = DEFAULT_OUTPUT_DIR
        self.profile_dir = DEFAULT_PROFILE_DIR
        self.profiles = load_profiles(self.config_path)

        self.detected_browser = detect_windows_browser()
        self.source_exe = tk.StringVar(value=str(self.detected_browser) if self.detected_browser else "")
        self.create_name = tk.StringVar(value="资料")
        self.create_display_number = tk.StringVar(value="")
        self.create_proxy = tk.StringVar(value="")
        self.create_language = tk.StringVar(value="zh-CN")
        self.create_timezone = tk.StringVar(value="Asia/Shanghai")
        self.create_fingerprint_base = tk.StringVar(value="10000")
        self.batch_name = tk.StringVar(value="资料")
        self.batch_count = tk.StringVar(value="5")
        self.search_text = tk.StringVar(value="")
        self.running_profiles: dict[str, int] = {}

        logging.info("Windows manager starting")
        self._build()
        self.refresh_table()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        ttk.Label(top, text="Chrome 路径").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.source_exe).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(top, text="选择", command=self.choose_source).grid(row=0, column=2)
        self.summary_label = ttk.Label(top, text="窗口总览")
        self.summary_label.grid(row=0, column=3, sticky="e")
        status_text = "已自动识别外置 Chrome" if self.detected_browser else "未识别到浏览器，请手动选择 chrome.exe"
        self.browser_status = ttk.Label(top, text=status_text)
        self.browser_status.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(6, 0))

        toolbar = ttk.Frame(self, padding=(12, 0, 12, 10))
        toolbar.grid(row=1, column=0, sticky="ew")
        for index in range(15):
            toolbar.columnconfigure(index, weight=0)
        toolbar.columnconfigure(14, weight=1)

        ttk.Button(toolbar, text="创建窗口", command=self.show_create_dialog).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="批量创建", command=self.show_batch_dialog).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="打开窗口", command=self.open_selected).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="打开全部", command=self.open_all).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="关闭窗口", command=self.close_selected).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(toolbar, text="关闭全部", command=self.close_all).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(toolbar, text="编辑", command=self.edit_selected).grid(row=0, column=6, padx=(0, 8))
        ttk.Button(toolbar, text="重置资料", command=self.clear_selected).grid(row=0, column=7, padx=(0, 8))
        ttk.Button(toolbar, text="打开目录", command=self.reveal_selected).grid(row=0, column=8, padx=(0, 8))
        ttk.Button(toolbar, text="导出", command=self.export_profiles).grid(row=0, column=9, padx=(0, 8))
        ttk.Button(toolbar, text="导入", command=self.import_profiles).grid(row=0, column=10, padx=(0, 8))
        ttk.Button(toolbar, text="删除窗口", command=self.delete_selected).grid(row=0, column=11, padx=(0, 8))
        ttk.Button(toolbar, text="刷新列表", command=self.refresh_table).grid(row=0, column=12, padx=(0, 8))
        ttk.Label(toolbar, text="搜索").grid(row=0, column=13, padx=(8, 4))
        search = ttk.Entry(toolbar, textvariable=self.search_text)
        search.grid(row=0, column=14, sticky="ew")
        search.bind("<KeyRelease>", lambda _event: self.refresh_table())

        table_frame = ttk.Frame(self, padding=(12, 0, 12, 12))
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("number", "name", "status", "profile", "proxy", "site", "remark")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.table.heading("number", text="序号")
        self.table.heading("name", text="窗口名称")
        self.table.heading("status", text="状态")
        self.table.heading("profile", text="资料目录")
        self.table.heading("proxy", text="代理")
        self.table.heading("site", text="打开网址")
        self.table.heading("remark", text="备注")
        self.table.column("number", width=70, anchor="center", stretch=False)
        self.table.column("name", width=160, anchor="w")
        self.table.column("status", width=80, anchor="center", stretch=False)
        self.table.column("profile", width=340, anchor="w")
        self.table.column("proxy", width=180, anchor="w")
        self.table.column("site", width=220, anchor="w")
        self.table.column("remark", width=200, anchor="w")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.bind("<Double-1>", lambda _event: self.open_selected())

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

    def choose_source(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 Chrome 可执行文件",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.source_exe.set(path)
            self.browser_status.config(text="当前使用手动选择的外置浏览器")

    def selected_profile(self) -> dict | None:
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("指纹浏览器", "请先选择一个窗口。")
            return None
        number = int(selection[0])
        return next((item for item in self.profiles if int(item["number"]) == number), None)

    def filtered_profiles(self) -> list[dict]:
        keyword = self.search_text.get().strip().lower()
        if not keyword:
            return sorted(self.profiles, key=lambda item: int(item["number"]))
        result = []
        for item in self.profiles:
            haystack = " ".join(
                [
                    str(item.get("number", "")),
                    str(item.get("display_number", "")),
                    str(item.get("name", "")),
                    str(item.get("profile_path", "")),
                    str(item.get("proxy", "")),
                    str(item.get("remark", "")),
                    " ".join(item.get("open_urls") or []),
                ]
            ).lower()
            if keyword in haystack:
                result.append(item)
        return sorted(result, key=lambda item: int(item["number"]))

    def refresh_table(self) -> None:
        self.profiles = load_profiles(self.config_path)
        self.running_profiles = self.running_windows()
        self.table.delete(*self.table.get_children())
        for item in self.filtered_profiles():
            profile_path = str(Path(item.get("profile_path", "")))
            self.table.insert(
                "",
                tk.END,
                iid=str(item["number"]),
                values=(
                    item.get("display_number") or item["number"],
                    item.get("name", ""),
                    "运行" if profile_path in self.running_profiles else "未开",
                    item.get("profile_path", ""),
                    item.get("proxy") or "直连",
                    (item.get("open_urls") or ["-"])[0],
                    item.get("remark") or "-",
                ),
            )
        opened = sum(1 for item in self.profiles if item.get("profile_path", "") in self.running_profiles)
        browser_source = "外置 Chrome" if self.source_exe.get().strip() else "未选择浏览器"
        self.summary_label.config(text=f"窗口总数 {len(self.profiles)}  运行中 {opened}  浏览器 {browser_source}")
        self.browser_status.config(text=f"共 {len(self.profiles)} 个窗口，运行中 {opened} 个")

    def running_windows(self) -> dict[str, int]:
        if os.name != "nt":
            return {}
        try:
            output = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('chrome.exe','chromium.exe') } | "
                    "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
                ],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return {}

        output = output.strip()
        if not output:
            return {}
        try:
            records = json.loads(output)
        except json.JSONDecodeError:
            return {}
        if isinstance(records, dict):
            records = [records]

        running: dict[str, int] = {}
        for record in records:
            command_line = str(record.get("CommandLine") or "")
            pid = int(record.get("ProcessId") or 0)
            marker = "--user-data-dir="
            if marker not in command_line:
                continue
            remainder = command_line.split(marker, 1)[1].strip()
            if remainder.startswith('"'):
                profile_path = remainder.split('"', 2)[1]
            else:
                profile_path = remainder.split(" ", 1)[0].strip()
            if profile_path:
                running[str(Path(profile_path))] = pid
        return running

    def next_number(self) -> int:
        used = {int(item["number"]) for item in self.profiles}
        number = 1
        while number in used:
            number += 1
        return number

    def default_args(self, fingerprint: int, proxy: str, language: str, timezone: str, config: FingerprintConfig, extra_args: list[str]) -> list[str]:
        args = [
            f"--fingerprint-platform={config.platform}",
            f"--fingerprint-brand-version={config.chrome_version}",
            f"--user-agent={config.user_agent}",
            f"--window-size={config.width},{config.height}",
            f"--force-device-scale-factor={config.device_scale_factor}",
            f"--fingerprint-hardware-concurrency={config.cpu_cores}",
            f"--fingerprint={fingerprint}",
        ]
        if config.webrtc_policy == "disable-non-proxied-udp":
            args.append("--disable-non-proxied-udp")
        if language:
            args.extend([f"--lang={language}", f"--accept-lang={language}"])
        if timezone:
            args.append(f"--timezone={timezone}")
        if proxy:
            args.append(f"--proxy-server={proxy}")
        args.extend(extra_args)
        return args

    def create_labeled_entry(self, parent: ttk.Frame, row: int, column: int, label: str, variable: tk.StringVar) -> None:
        base_column = column * 2
        ttk.Label(parent, text=label).grid(row=row, column=base_column, sticky="w", pady=(10 if row else 0, 0))
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=base_column + 1, sticky="ew", padx=(8, 16 if column == 0 else 0), pady=(10 if row else 0, 0))

    def create_group(self, parent: ttk.Frame, title: str, row: int) -> ttk.LabelFrame:
        group = ttk.LabelFrame(parent, text=title, padding=12)
        group.grid(row=row, column=0, sticky="nsew", pady=(12 if row else 0, 0))
        group.columnconfigure(1, weight=1)
        group.columnconfigure(3, weight=1)
        return group

    def create_text_block(self, parent: ttk.Frame, row: int, title: str, height: int, initial_text: str = "") -> tk.Text:
        ttk.Label(parent, text=title).grid(row=row, column=0, sticky="nw", pady=(0 if row == 0 else 12, 0))
        text_widget = tk.Text(parent, height=height)
        text_widget.grid(row=row + 1, column=0, sticky="nsew", pady=(6, 0))
        if initial_text:
            text_widget.insert("1.0", initial_text)
        return text_widget

    def build_profile_form(self, dialog: tk.Toplevel, title: str, submit_text: str, submit_command, profile: dict | None = None) -> None:
        dialog.title(title)
        dialog.geometry("860x760")
        dialog.transient(self)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=16)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas, padding=(0, 0, 6, 0))
        scroll_frame.columnconfigure(0, weight=1)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        def _sync_width(event) -> None:
            canvas.itemconfigure(canvas_window, width=event.width)

        def _update_scroll(_event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", _sync_width)
        scroll_frame.bind("<Configure>", _update_scroll)

        basics = self.create_group(scroll_frame, "基础设置", 0)
        self.create_labeled_entry(basics, 0, 0, "窗口名称", self.create_name)
        self.create_labeled_entry(basics, 0, 1, "图标序号", self.create_display_number)
        self.create_labeled_entry(basics, 1, 0, "代理", self.create_proxy)
        self.create_labeled_entry(basics, 1, 1, "语言", self.create_language)
        self.create_labeled_entry(basics, 2, 0, "时区", self.create_timezone)
        self.create_labeled_entry(basics, 2, 1, "指纹种子", self.create_fingerprint_base)

        notes = self.create_group(scroll_frame, "备注与登录", 1)
        notes.columnconfigure(0, weight=1)
        notes.rowconfigure(1, weight=1)
        notes.rowconfigure(3, weight=1)
        remark_text = self.create_text_block(notes, 0, "备注", 4, profile.get("remark") if profile else "")
        cookie_text = self.create_text_block(notes, 2, "Cookie JSON", 8, profile.get("cookie_json") if profile else "")

        startup = self.create_group(scroll_frame, "启动行为", 2)
        startup.columnconfigure(0, weight=1)
        startup.rowconfigure(1, weight=1)
        startup.rowconfigure(3, weight=1)
        urls_text = self.create_text_block(startup, 0, "打开网址", 6, "\n".join(profile.get("open_urls") or []) if profile else "")
        default_args_text = "\n".join(profile.get("args") or []) if profile else "--disable-features=AutomationControlled\n"
        args_text = self.create_text_block(startup, 2, "启动参数", 8, default_args_text)

        footer = ttk.Frame(scroll_frame)
        footer.grid(row=3, column=0, sticky="e", pady=(16, 0))
        ttk.Button(footer, text="取消", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(
            footer,
            text=submit_text,
            command=lambda: submit_command(dialog, remark_text, cookie_text, urls_text, args_text),
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def show_create_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        self.create_name.set("资料")
        self.create_display_number.set("")
        self.create_proxy.set("")
        self.create_language.set("zh-CN")
        self.create_timezone.set("Asia/Shanghai")
        self.create_fingerprint_base.set("10000")
        self.build_profile_form(dialog, "创建 Windows 窗口", "创建并打开", self.create_profile)

    def create_profile(self, dialog: tk.Toplevel, remark_text: tk.Text, cookie_text: tk.Text, urls_text: tk.Text, args_text: tk.Text) -> None:
        source_exe = Path(self.source_exe.get()).expanduser()
        if not source_exe.exists():
            messagebox.showerror("指纹浏览器", f"找不到 Chrome：\n{source_exe}")
            return

        number = self.next_number()
        display_number = int(self.create_display_number.get()) if self.create_display_number.get().strip().isdigit() else number
        name = sanitized_name(self.create_name.get())
        proxy = self.create_proxy.get().strip()
        language = self.create_language.get().strip()
        timezone = self.create_timezone.get().strip()
        fingerprint = (int(self.create_fingerprint_base.get() or "10000")) + number - 1
        config = FingerprintConfig()
        extra_args = [line.strip() for line in args_text.get("1.0", tk.END).splitlines() if line.strip()]
        urls = [normalize_open_url(line) for line in urls_text.get("1.0", tk.END).splitlines() if line.strip()]
        cookies = cookie_text.get("1.0", tk.END).strip()
        remark = remark_text.get("1.0", tk.END).strip()
        args = self.default_args(fingerprint, proxy, language, timezone, config, extra_args)

        try:
            launcher = create_profile_launcher(
                source_exe=source_exe,
                output_dir=self.output_dir,
                profile_root=self.profile_dir,
                number=number,
                app_name=name,
                display_number=display_number,
                extra_args=args,
                cookies_text=cookies,
                open_urls=urls,
                force=True,
            )
        except Exception as exc:
            messagebox.showerror("指纹浏览器", str(exc))
            return

        profile = {
            "number": number,
            "display_number": display_number,
            "name": name,
            "fingerprint": fingerprint,
            "app_path": launcher["app_path"],
            "app_dir": launcher["app_dir"],
            "browser_exe_path": launcher["browser_exe_path"],
            "launcher_path": launcher["launcher_path"],
            "icon_path": launcher["icon_path"],
            "profile_path": launcher["profile_path"],
            "args": args,
            "proxy": proxy or None,
            "remark": remark or None,
            "open_urls": urls or None,
            "cookie_json": cookies or None,
            "fingerprint_config": config.__dict__,
            "platform_target": "windows",
        }
        self.profiles.append(profile)
        self.profiles.sort(key=lambda item: int(item["number"]))
        save_profiles(self.config_path, self.profiles)
        dialog.destroy()
        self.refresh_table()
        self._open_profile(profile)

    def _profile_form_values(self, remark_text: tk.Text, cookie_text: tk.Text, urls_text: tk.Text, args_text: tk.Text) -> tuple[str, str, str, str, int, list[str], str, str]:
        name = sanitized_name(self.create_name.get())
        proxy = self.create_proxy.get().strip()
        language = self.create_language.get().strip()
        timezone = self.create_timezone.get().strip()
        display_number = int(self.create_display_number.get()) if self.create_display_number.get().strip().isdigit() else 0
        urls = [normalize_open_url(line) for line in urls_text.get("1.0", tk.END).splitlines() if line.strip()]
        cookies = cookie_text.get("1.0", tk.END).strip()
        remark = remark_text.get("1.0", tk.END).strip()
        extra_args = [line.strip() for line in args_text.get("1.0", tk.END).splitlines() if line.strip()]
        return name, proxy, language, timezone, display_number, urls, cookies, remark, extra_args

    def show_batch_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("批量创建窗口")
        dialog.geometry("420x180")
        dialog.transient(self)
        dialog.grab_set()

        root = ttk.Frame(dialog, padding=16)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="名称前缀").grid(row=0, column=0, sticky="w")
        ttk.Entry(root, textvariable=self.batch_name).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(root, text="创建数量").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(root, textvariable=self.batch_count).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        ttk.Label(root, text="说明").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(root, text="批量创建只生成窗口，不自动打开").grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        footer = ttk.Frame(root)
        footer.grid(row=3, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(footer, text="取消", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(footer, text="开始创建", command=lambda: self.batch_create(dialog)).pack(side=tk.RIGHT, padx=(0, 8))

    def batch_create(self, dialog: tk.Toplevel) -> None:
        source_exe = Path(self.source_exe.get()).expanduser()
        if not source_exe.exists():
            messagebox.showerror("指纹浏览器", f"找不到 Chrome：\n{source_exe}")
            return
        count = max(1, min(100, int(self.batch_count.get() or "1")))
        base_name = sanitized_name(self.batch_name.get())
        base_seed = int(self.create_fingerprint_base.get() or "10000")
        config = FingerprintConfig()
        created = 0
        for _ in range(count):
            number = self.next_number()
            fingerprint = base_seed + number - 1
            args = self.default_args(
                fingerprint,
                self.create_proxy.get().strip(),
                self.create_language.get().strip(),
                self.create_timezone.get().strip(),
                config,
                [],
            )
            launcher = create_profile_launcher(
                source_exe=source_exe,
                output_dir=self.output_dir,
                profile_root=self.profile_dir,
                number=number,
                app_name=base_name,
                display_number=number,
                extra_args=args,
                cookies_text="",
                open_urls=[],
                force=True,
            )
            self.profiles.append(
                {
                    "number": number,
                    "display_number": number,
                    "name": base_name,
                    "fingerprint": fingerprint,
                    "app_path": launcher["app_path"],
                    "app_dir": launcher["app_dir"],
                    "browser_exe_path": launcher["browser_exe_path"],
                    "launcher_path": launcher["launcher_path"],
                    "icon_path": launcher["icon_path"],
                    "profile_path": launcher["profile_path"],
                    "args": args,
                    "proxy": self.create_proxy.get().strip() or None,
                    "remark": "批量创建",
                    "open_urls": None,
                    "cookie_json": None,
                    "fingerprint_config": config.__dict__,
                    "platform_target": "windows",
                }
            )
            self.profiles.sort(key=lambda item: int(item["number"]))
            created += 1
        save_profiles(self.config_path, self.profiles)
        dialog.destroy()
        self.refresh_table()
        messagebox.showinfo("指纹浏览器", f"已创建 {created} 个窗口。")

    def open_all(self) -> None:
        opened = 0
        for profile in self.filtered_profiles():
            self._open_profile(profile)
            opened += 1
        if opened:
            self.browser_status.config(text=f"已打开 {opened} 个窗口")

    def close_selected(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        profile_path = str(Path(profile.get("profile_path", "")))
        pid = self.running_profiles.get(profile_path)
        if not pid:
            messagebox.showinfo("指纹浏览器", "这个窗口当前没有在运行。")
            return
        self._kill_pid(pid)
        self.refresh_table()

    def close_all(self) -> None:
        closed = 0
        for profile_path, pid in list(self.running_profiles.items()):
            self._kill_pid(pid)
            closed += 1
        self.refresh_table()
        if closed:
            self.browser_status.config(text=f"已关闭 {closed} 个窗口")

    def _kill_pid(self, pid: int) -> None:
        if os.name != "nt":
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

    def edit_selected(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        dialog = tk.Toplevel(self)
        self.create_name.set(profile.get("name", "资料"))
        self.create_display_number.set(str(profile.get("display_number") or profile.get("number") or ""))
        self.create_proxy.set(profile.get("proxy") or "")
        self.create_language.set("zh-CN")
        self.create_timezone.set("Asia/Shanghai")
        self.create_fingerprint_base.set(str(profile.get("fingerprint", 10000) - int(profile.get("number", 1)) + 1))
        self.build_profile_form(
            dialog,
            "编辑窗口",
            "保存",
            lambda dlg, remark_text, cookie_text, urls_text, args_text: self.save_profile(
                dlg, profile, remark_text, cookie_text, urls_text, args_text
            ),
            profile,
        )

    def save_profile(self, dialog: tk.Toplevel, original: dict, remark_text: tk.Text, cookie_text: tk.Text, urls_text: tk.Text, args_text: tk.Text) -> None:
        source_exe = Path(self.source_exe.get()).expanduser()
        if not source_exe.exists():
            messagebox.showerror("指纹浏览器", f"找不到 Chrome：\n{source_exe}")
            return
        name, proxy, language, timezone, display_number, urls, cookies, remark, extra_args = self._profile_form_values(
            remark_text, cookie_text, urls_text, args_text
        )
        config_dict = original.get("fingerprint_config") or FingerprintConfig().__dict__
        config = FingerprintConfig(**config_dict)
        fingerprint = int(self.create_fingerprint_base.get() or original.get("fingerprint", 10000))
        args = self.default_args(fingerprint, proxy, language, timezone, config, extra_args)
        launcher = create_profile_launcher(
            source_exe=source_exe,
            output_dir=self.output_dir,
            profile_root=self.profile_dir,
            number=int(original["number"]),
            app_name=name,
            display_number=display_number or int(original.get("display_number") or original["number"]),
            extra_args=args,
            cookies_text=cookies,
            open_urls=urls,
            force=True,
        )
        updated = {
            **original,
            "name": name,
            "display_number": display_number or int(original.get("display_number") or original["number"]),
            "fingerprint": fingerprint,
            "app_path": launcher["app_path"],
            "app_dir": launcher["app_dir"],
            "browser_exe_path": launcher["browser_exe_path"],
            "launcher_path": launcher["launcher_path"],
            "icon_path": launcher["icon_path"],
            "profile_path": launcher["profile_path"],
            "args": args,
            "proxy": proxy or None,
            "remark": remark or None,
            "open_urls": urls or None,
            "cookie_json": cookies or None,
        }
        self.profiles = [updated if int(item["number"]) == int(original["number"]) else item for item in self.profiles]
        self.profiles.sort(key=lambda item: int(item["number"]))
        save_profiles(self.config_path, self.profiles)
        dialog.destroy()
        self.refresh_table()

    def clear_selected(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        if not messagebox.askyesno("指纹浏览器", f"确定重置 {profile.get('name', '该窗口')} 的资料目录吗？"):
            return
        profile_dir = Path(profile.get("profile_path", ""))
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        messagebox.showinfo("指纹浏览器", "资料目录已重置。")

    def export_profiles(self) -> None:
        target = filedialog.asksaveasfilename(
            title="导出配置",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile="profiles.windows.export.json",
        )
        if not target:
            return
        Path(target).write_text(
            json.dumps({"profiles": self.profiles}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.browser_status.config(text="已导出窗口配置")

    def import_profiles(self) -> None:
        source = filedialog.askopenfilename(
            title="导入配置",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not source:
            return
        data = json.loads(Path(source).read_text(encoding="utf-8"))
        imported = data.get("profiles", [])
        if not isinstance(imported, list):
            messagebox.showerror("指纹浏览器", "配置文件格式不正确。")
            return
        self.profiles = imported
        save_profiles(self.config_path, self.profiles)
        self.refresh_table()
        self.browser_status.config(text="已导入窗口配置")

    def _open_profile(self, profile: dict) -> None:
        source_exe = Path(self.source_exe.get()).expanduser()
        if not source_exe.exists():
            messagebox.showerror("指纹浏览器", f"找不到 Chrome：\n{source_exe}")
            return
        if os.name == "nt":
            subprocess.Popen(
                browser_launch_args(profile, source_exe),
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
        else:
            subprocess.Popen(browser_launch_args(profile, source_exe))

    def open_selected(self) -> None:
        profile = self.selected_profile()
        if profile:
            self._open_profile(profile)

    def reveal_selected(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        target = profile.get("app_dir") or profile.get("profile_path")
        if not target:
            return
        if os.name == "nt":
            os.startfile(target)
        else:
            subprocess.Popen(["open", target])

    def delete_selected(self) -> None:
        profile = self.selected_profile()
        if not profile:
            return
        if not messagebox.askyesno("指纹浏览器", f"确定删除 {profile.get('name', '该窗口')} 吗？"):
            return
        for key in ("app_dir", "profile_path"):
            path = Path(profile.get(key, ""))
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        self.profiles = [item for item in self.profiles if int(item["number"]) != int(profile["number"])]
        save_profiles(self.config_path, self.profiles)
        self.refresh_table()


def main() -> None:
    configure_logging()
    try:
        Manager().mainloop()
    except Exception as exc:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logging.exception("Windows manager crashed")
        show_fatal_error(
            "程序启动失败或运行时崩溃。\n\n"
            f"错误信息：{exc}\n\n"
            f"日志文件：{WINDOWS_LOG_PATH}\n\n"
            "请把日志内容发我。"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
