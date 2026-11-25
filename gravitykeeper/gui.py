"""Native desktop UI. All filesystem-heavy work runs off the Tk event loop."""

import argparse
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .catalog import catalog, search, transcript
from .demo import fixture
from .detection import probe
from .errors import error_code
from .paths import isolated_directory
from .service import REPORT, capture, export, full_backup, new_snapshot
from .storage import load_json, package_snapshot, verify_snapshot, verify_zip


INK, MUTED, WHITE = "#1a2942", "#50647e", "#ffffff"
NAV, NAV_HOVER, ACTIVE = "#102238", "#1c3450", "#275077"
PAGE, LINE, BLUE, TEAL = "#f0f4f9", "#dce5ef", "#155bc3", "#42d4b1"

TEXT = {
    "home": ("Overview", "首页"),
    "history": ("Conversations", "历史会话"),
    "backups": ("Backups", "备份管理"),
    "projects": ("Projects", "项目索引"),
    "integrity": ("Integrity", "完整性检查"),
    "settings": ("Settings", "设置"),
    "home_title": ("Workspace overview", "工作区概览"),
    "home_caption": ("Protect and browse the Antigravity conversations saved on this PC.", "备份并浏览已保存在本机的 Antigravity 会话。"),
    "history_caption": ("Search and read conversations in a local export.", "在本机导出副本中搜索并阅读会话。"),
    "backups_caption": ("Select an existing snapshot to export, verify, or package.", "选择现有快照，以导出、校验或打包。"),
    "projects_caption": ("Find exported conversations by their original workspace.", "按原工作区查找已导出的会话。"),
    "integrity_caption": ("Recalculate SHA-256 for a snapshot or ZIP archive.", "重新计算快照或 ZIP 归档的 SHA-256。"),
    "settings_caption": ("Configure local locations and display language.", "配置本机目录及显示语言。"),
    "local": ("Local processing", "本机处理"),
    "local_note": ("Offline · Read-only source", "离线 · 源目录只读"),
    "snapshot": ("Full backup", "完整备份"),
    "backup_only": ("Raw backup only", "仅备份原始数据"),
    "export_only": ("Export snapshot", "仅导出会话"),
    "open": ("Open output folder", "打开输出目录"),
    "open_snapshot": ("Load snapshot…", "打开快照…"),
    "refresh": ("Refresh detection", "重新检测"),
    "hero": ("Create a local snapshot", "创建本机快照"),
    "hero_note": ("Copy raw files, then export Markdown and JSON from the verified copy.", "先复制原始文件，再从校验过的副本导出 Markdown 和 JSON。"),
    "version": ("Antigravity version", "Antigravity 版本"),
    "conversations": ("Detected conversations", "检测到的会话"),
    "workspaces": ("Workspaces", "项目工作区"),
    "size": ("Local data size", "本机数据大小"),
    "unknown": ("Unavailable", "暂不可用"),
    "latest": ("Selected snapshot", "当前快照"),
    "none": ("No snapshot selected", "未选择快照"),
    "raw_status": ("Raw backup", "原始备份"),
    "export_status": ("Conversation export", "会话导出"),
    "ready": ("Ready", "就绪"),
    "busy": ("A task is running. Please wait for it to finish.", "任务正在运行，请等待完成。"),
    "completed": ("Operation finished", "操作完成"),
    "error": ("Operation needs attention", "操作需要处理"),
    "search": ("Search", "搜索"),
    "query": ("Search titles, workspaces, or message text", "搜索标题、工作区或消息正文"),
    "title": ("Conversation", "会话"),
    "state": ("Status", "状态"),
    "steps": ("Steps", "步骤"),
    "preview": ("Transcript", "会话正文"),
    "previous": ("Previous", "上一页"),
    "next": ("Next", "下一页"),
    "pick_session": ("Select a conversation to read its transcript.", "选择会话以查看正文。"),
    "rows_hint": ("Browse or export a snapshot to see conversations here.", "打开已有快照或完成导出后即可查看会话。"),
    "compare": ("Verify snapshot", "校验快照"),
    "compare_zip": ("Verify ZIP…", "校验 ZIP…"),
    "make_zip": ("Create ZIP…", "创建 ZIP…"),
    "report": ("Verification details", "核验详情"),
    "vault": ("Backup location", "备份根目录"),
    "source": ("Custom Antigravity data location", "自定义 Antigravity 数据目录"),
    "auto": ("Leave empty for automatic detection.", "留空时自动检测。"),
    "choose": ("Browse…", "浏览…"),
    "save": ("Save settings", "保存设置"),
    "language": ("Language", "语言"),
    "project": ("Workspace", "工作区"),
    "project_count": ("Conversations", "会话数"),
    "unassigned": ("No workspace recorded", "没有记录工作区"),
    "demo": ("DEMO DATA", "合成演示数据"),
    "folder_missing": ("Select an existing local directory.", "请选择已存在的本机目录。"),
    "snapshot_missing": ("Select a GravityKeeper snapshot directory.", "请选择 GravityKeeper 快照目录。"),
    "archive_count": ("Entries", "条目数"),
    "verified": ("Verification passed", "校验通过"),
    "loaded": ("Snapshot loaded", "已打开快照"),
}

PHASES = {
    "capture": ("Copying raw files", "复制原始文件"),
    "discover": ("Discovering local data", "检测本机数据"),
    "hash": ("Writing SHA-256 checksums", "生成 SHA-256 校验和"),
    "verify": ("Verifying snapshot files", "校验快照文件"),
    "artifacts": ("Archiving attachments", "归档会话工件"),
    "export": ("Exporting conversations", "导出会话"),
    "zip": ("Writing ZIP", "写入 ZIP"),
    "verify_zip": ("Verifying ZIP entries", "校验 ZIP 条目"),
    "search": ("Searching local exports", "搜索本机导出"),
}


def readable_bytes(number):
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024 or suffix == "TiB":
            return f"{number:,.1f} {suffix}" if suffix != "B" else f"{number:,} B"
        number /= 1024
    return ""


class App:
    def __init__(self, root, config, demo=None, smoke_report=None):
        self.root, self.config, self.demo = root, config, demo
        self.smoke_report = smoke_report
        self.state = self.load_config()
        self.locale = self.state.get("language", "en")
        self.vault = Path(self.state.get("vault", str(Path.home() / "Documents" / "GravityKeeper Backups")))
        self.source = Path(self.state["source"]) if self.state.get("source") else None
        self.page = "home"
        self.snapshot = None
        self.probe_result = None
        self.busy = False
        self.events = queue.Queue()
        self.last_status = "ready"
        self.detail = ""
        self.history_filter = None
        self.result_text = ""
        self.query_text = ""
        self.smoke_result = {}
        if demo:
            self.vault = demo / "Archive"
            self.source = fixture(demo / "Fictional profile")
        root.title("GravityKeeper" + (" — Demo" if demo else ""))
        root.minsize(900, 600)
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = min(1180, screen_w - 40), min(770, screen_h - 74)
        root.geometry(f"{width}x{height}+{max(8, (screen_w-width)//2)}+{max(8, (screen_h-height)//2 - 8)}")
        root.configure(background=PAGE)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.styles()
        self.render()
        root.after(45, self.drain)
        root.after(100, self.refresh)

    def tr(self, key):
        return TEXT[key][self.locale == "zh"]

    def load_config(self):
        if self.demo:
            return {}
        try:
            data = load_json(self.config)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK,
                        rowheight=38, font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", background="#eaf0f7", foreground=INK,
                        padding=8, borderwidth=0, font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#d9eaff")], foreground=[("selected", INK)])
        style.configure("Local.Horizontal.TProgressbar", troughcolor="#e2ebf5", background=BLUE,
                        borderwidth=0, lightcolor=BLUE, darkcolor=BLUE, thickness=7)

    def text(self, parent, value, size=10, fg=INK, bg=PAGE, weight="normal", **options):
        return tk.Label(parent, text=value, fg=fg, bg=bg, font=("Segoe UI", size, weight), **options)

    def button(self, parent, key, callback, primary=False, **pack):
        color, foreground = (BLUE, WHITE) if primary else (WHITE, INK)
        button = tk.Button(parent, text=self.tr(key), command=callback, bg=color, fg=foreground,
                           activebackground="#dbeafa" if not primary else "#10448b",
                           activeforeground=foreground, relief="flat", cursor="hand2", padx=14, pady=8,
                           highlightthickness=1, highlightbackground=BLUE if primary else LINE,
                           font=("Segoe UI", 10, "bold"))
        button.pack(**pack)
        return button

    def surface(self, parent):
        return tk.Frame(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)

    def render(self):
        for child in self.root.winfo_children():
            child.destroy()
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        side = tk.Frame(self.root, bg=NAV, width=218)
        side.grid(row=0, column=0, sticky="ns")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=NAV)
        brand.pack(fill="x", padx=18, pady=(28, 32))
        mark = tk.Canvas(brand, width=35, height=35, bg=NAV, highlightthickness=0)
        mark.pack(side="left", padx=(0, 9))
        mark.create_oval(3, 3, 33, 33, outline="#66efd2", width=2)
        mark.create_arc(8, 8, 29, 29, start=45, extent=253, style="arc", outline=WHITE, width=2)
        mark.create_oval(16, 16, 21, 21, outline=TEAL, fill=TEAL)
        self.text(brand, "GravityKeeper", 14, WHITE, NAV, "bold").pack(side="left")
        for key, icon in (("home", "⌂"), ("history", "≡"), ("backups", "▤"),
                          ("projects", "▦"), ("integrity", "✓"), ("settings", "⚙")):
            active = self.page == key
            btn = tk.Button(side, text=f"  {icon}    {self.tr(key)}", anchor="w", width=20, pady=11,
                            command=lambda value=key: self.navigate(value), bg=ACTIVE if active else NAV,
                            activebackground=NAV_HOVER, fg=WHITE if active else "#c1d3e8",
                            activeforeground=WHITE, cursor="hand2", relief="flat", borderwidth=0,
                            font=("Segoe UI", 11, "bold" if active else "normal"))
            btn.pack(fill="x", padx=12, pady=1)
        local = tk.Frame(side, bg=NAV)
        local.pack(side="bottom", fill="x", padx=20, pady=20)
        self.text(local, "●  " + self.tr("local"), 10, TEAL, NAV, "bold").pack(anchor="w")
        self.text(local, self.tr("local_note"), 9, "#9eb8d2", NAV).pack(anchor="w", pady=(4, 0))
        panel = tk.Frame(self.root, bg=PAGE)
        panel.grid(row=0, column=1, sticky="nsew")
        mast = tk.Frame(panel, bg=PAGE)
        mast.pack(fill="x", padx=28, pady=(24, 15))
        title = self.tr("home_title" if self.page == "home" else self.page)
        self.text(mast, title, 23, INK, PAGE, "bold").pack(anchor="w")
        self.text(mast, self.tr(self.page + "_caption"), 10, MUTED).pack(anchor="w", pady=(4, 0))
        if self.demo:
            self.text(mast, self.tr("demo"), 9, "#126c57", "#d7f4eb", "bold", padx=8, pady=3).place(relx=1, x=0, y=4, anchor="ne")
        footer = tk.Frame(panel, bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        footer.pack(side="bottom", fill="x", padx=28, pady=(10, 18))
        self.status = self.text(footer, self.tr(self.last_status), 10, MUTED, WHITE, anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=12, pady=9)
        self.progress = ttk.Progressbar(footer, length=154, style="Local.Horizontal.TProgressbar", maximum=100)
        self.progress.pack(side="right", padx=12)
        self.body = tk.Frame(panel, bg=PAGE)
        self.body.pack(fill="both", expand=True, padx=28)
        getattr(self, "show_" + self.page)()

    def navigate(self, page):
        if self.busy:
            return
        self.page = page
        self.render()

    def show_home(self):
        info = self.probe_result or {}
        executable = (info.get("installations") or [{}])[0].get("version")
        if self.demo:
            executable = "2.33.0"
        values = [executable or self.tr("unknown"), info.get("conversations", "—"),
                  info.get("workspaces") if info.get("workspaces") is not None else "—",
                  readable_bytes(info["bytes"]) if "bytes" in info else "—"]
        stats = tk.Frame(self.body, bg=PAGE)
        stats.pack(fill="x")
        for i, (key, value) in enumerate(zip(("version", "conversations", "workspaces", "size"), values)):
            stats.grid_columnconfigure(i, weight=1, uniform="stat")
            box = self.surface(stats)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            self.text(box, self.tr(key), 9, MUTED, WHITE).pack(anchor="w", padx=12, pady=(12, 0))
            self.text(box, value, 18, INK, WHITE, "bold").pack(anchor="w", padx=12, pady=(3, 13))
        hero = tk.Frame(self.body, bg=NAV_HOVER)
        hero.pack(fill="x", pady=16)
        self.text(hero, self.tr("hero"), 16, WHITE, NAV_HOVER, "bold").pack(anchor="w", padx=18, pady=(15, 1))
        self.text(hero, self.tr("hero_note"), 10, "#c7daef", NAV_HOVER).pack(anchor="w", padx=18)
        actions = tk.Frame(hero, bg=NAV_HOVER)
        actions.pack(fill="x", padx=18, pady=(13, 16))
        self.button(actions, "snapshot", lambda: self.make_snapshot(True), True, side="left")
        self.button(actions, "backup_only", lambda: self.make_snapshot(False), side="left", padx=(8, 0))
        self.button(actions, "export_only", self.export_selected, side="left", padx=(8, 0))
        latest = self.surface(self.body)
        latest.pack(fill="x")
        self.text(latest, self.tr("latest"), 13, INK, WHITE, "bold").pack(anchor="w", padx=16, pady=(11, 2))
        report = self.snapshot_report()
        summary = self.tr("none") if not self.snapshot else (
            f"{self.snapshot.name}   ·   {self.tr('raw_status')} {report.get('raw', '—')}   ·   "
            f"{self.tr('export_status')} {report.get('export', '—')}")
        self.text(latest, summary, 10, MUTED, WHITE, anchor="w").pack(fill="x", padx=16, pady=3)
        actions = tk.Frame(latest, bg=WHITE)
        actions.pack(fill="x", padx=16, pady=(6, 11))
        self.button(actions, "open_snapshot", self.choose_snapshot, side="left")
        self.button(actions, "open", self.open_output, side="left", padx=8)
        self.button(actions, "refresh", self.refresh, side="right")

    def table(self, parent, columns, widths):
        outer = self.surface(parent)
        outer.pack(fill="both", expand=True)
        tree = ttk.Treeview(outer, show="headings", columns=list(columns), selectmode="browse")
        scroller = ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroller.set)
        for index, (column, width) in enumerate(zip(columns, widths)):
            tree.heading(column, text=self.tr(column), anchor="w")
            tree.column(column, width=width, minwidth=min(width, 75), stretch=index == 0, anchor="w")
        scroller.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def show_history(self):
        tools = tk.Frame(self.body, bg=PAGE)
        tools.pack(fill="x", pady=(0, 10))
        self.query = tk.StringVar(value=self.query_text)
        entry = ttk.Entry(tools, textvariable=self.query, font=("Segoe UI", 11))
        entry.pack(side="left", fill="x", expand=True, ipady=6)
        entry.bind("<Return>", lambda _: self.do_search())
        self.button(tools, "search", self.do_search, True, side="left", padx=8)
        self.button(tools, "open_snapshot", self.choose_snapshot, side="right")
        self.text(self.body, self.tr("query"), 9, MUTED).pack(anchor="w", pady=(0, 6))
        panes = tk.PanedWindow(self.body, orient="vertical", bg=PAGE, bd=0, sashwidth=7)
        panes.pack(fill="both", expand=True)
        listing = tk.Frame(panes, bg=PAGE)
        panes.add(listing, minsize=130, height=200)
        self.history = self.table(listing, ("title", "state", "steps"), (400, 120, 75))
        self.history.bind("<<TreeviewSelect>>", lambda _: self.pick_conversation())
        shelf = self.surface(panes)
        panes.add(shelf, minsize=130, stretch="always")
        reader_bar = tk.Frame(shelf, bg=WHITE)
        reader_bar.pack(fill="x", padx=12, pady=(7, 3))
        self.text(reader_bar, self.tr("preview"), 11, INK, WHITE, "bold").pack(side="left")
        self.button(reader_bar, "next", lambda: self.reader_page(1), side="right")
        self.button(reader_bar, "previous", lambda: self.reader_page(-1), side="right", padx=5)
        self.page_count = self.text(reader_bar, "", 9, MUTED, WHITE)
        self.page_count.pack(side="right", padx=7)
        self.reader_body = ""
        self.reader_offset = 0
        self.reader = self.scrolling_text(shelf)
        self.set_text(self.reader, self.tr("pick_session"))
        entries = self.history_filter
        if entries is None and self.snapshot:
            entries = search(self.snapshot, "")
        self.fill_history(entries or [])

    def scrolling_text(self, parent):
        content = tk.Frame(parent, bg=WHITE)
        content.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        scrollbar = ttk.Scrollbar(content)
        text = tk.Text(content, wrap="word", relief="flat", padx=4, pady=5, bg=WHITE, fg=INK,
                       font=("Segoe UI", 10), yscrollcommand=scrollbar.set, height=8, undo=False)
        scrollbar.configure(command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.configure(state="disabled")
        return text

    def set_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def fill_history(self, entries):
        self.history.delete(*self.history.get_children())
        self.entries = entries
        for i, item in enumerate(entries):
            title = item["title"] + (f"  ({item['matches']})" if item["matches"] else "")
            self.history.insert("", "end", iid=str(i), values=(title, item["status"], item["steps"]))

    def do_search(self):
        if not self.snapshot:
            return self.choose_snapshot()
        self.query_text = self.query.get()
        selected = self.snapshot
        self.start("search", lambda cb: search(selected, self.query_text, progress=cb), self.apply_search)

    def apply_search(self, result):
        self.history_filter = result
        self.fill_history(result)

    def pick_conversation(self):
        selected = self.history.selection()
        if self.busy or not selected:
            return
        item = self.entries[int(selected[0])]
        selected_snapshot = self.snapshot

        def read(_):
            chosen = transcript(selected_snapshot, item)
            chunks = []
            for row in chosen["steps"]:
                value = row.get("content") or row.get("error")
                if isinstance(value, str):
                    value = value.removeprefix("<USER_REQUEST>\n").split("\n</USER_REQUEST>", 1)[0]
                    chunks.append(f"{row['step_index']}  ·  {row['type']}\n{value}")
            return "\n\n".join(chunks)

        self.start("search", read, self.set_reader)

    def set_reader(self, body):
        self.reader_body = body
        self.reader_offset = 0
        self.reader_page(0)

    def reader_page(self, offset):
        if not self.reader_body:
            return
        block = 48000
        page_count = (len(self.reader_body) + block - 1) // block
        self.reader_offset = max(0, min(self.reader_offset + offset, page_count - 1))
        start = self.reader_offset * block
        self.set_text(self.reader, self.reader_body[start:start + block])
        self.page_count.configure(text=f"{self.reader_offset + 1} / {page_count}")

    def snapshot_report(self):
        try:
            return load_json(self.snapshot / REPORT) if self.snapshot and (self.snapshot / REPORT).is_file() else {}
        except (OSError, ValueError):
            return {}

    def show_backups(self):
        controls = tk.Frame(self.body, bg=PAGE)
        controls.pack(fill="x", pady=(0, 10))
        self.button(controls, "open_snapshot", self.choose_snapshot, True, side="left")
        for key, action in (("export_only", self.export_selected), ("make_zip", self.make_zip), ("open", self.open_output)):
            self.button(controls, key, action, side="left", padx=(7, 0))
        self.backup_tree = self.table(self.body, ("latest", "raw_status", "export_status"), (350, 140, 145))
        found = set()
        if self.vault.is_dir():
            found.update(path for path in self.vault.iterdir() if (path / REPORT).is_file())
        if self.snapshot:
            found.add(self.snapshot)
        self.locations = sorted(found, reverse=True)
        for i, path in enumerate(self.locations):
            try:
                report = load_json(path / REPORT)
            except (OSError, ValueError):
                report = {}
            self.backup_tree.insert("", "end", iid=str(i), values=(path.name, report.get("raw", "—"), report.get("export", "—")))
        self.backup_tree.bind("<<TreeviewSelect>>", lambda _: self.select_backup())

    def select_backup(self):
        selected = self.backup_tree.selection()
        if selected:
            self.set_snapshot(self.locations[int(selected[0])])

    def show_projects(self):
        controls = tk.Frame(self.body, bg=PAGE)
        controls.pack(fill="x", pady=(0, 10))
        self.button(controls, "open_snapshot", self.choose_snapshot, True, side="left")
        self.button(controls, "open", self.open_output, side="left", padx=8)
        tree = self.table(self.body, ("project", "project_count"), (490, 145))
        data = catalog(self.snapshot) if self.snapshot else {"projects": []}
        for i, group in enumerate(data["projects"]):
            workspace = ", ".join(group["workspace_paths"]) or self.tr("unassigned")
            tree.insert("", "end", iid=str(i), values=(workspace, len(group["sessions"])))

        def open_project(_):
            selected = tree.selection()
            if self.busy or not selected:
                return
            group = data["projects"][int(selected[0])]
            self.history_filter = [item | {"matches": 0, "snippet": ""} for item in group["sessions"]]
            self.navigate("history")
        tree.bind("<Double-1>", open_project)
        tree.bind("<Return>", open_project)

    def show_integrity(self):
        controls = tk.Frame(self.body, bg=PAGE)
        controls.pack(fill="x", pady=(0, 10))
        self.button(controls, "compare", self.verify_selected, True, side="left")
        self.button(controls, "compare_zip", self.verify_zip_dialog, side="left", padx=(8, 0))
        self.button(controls, "make_zip", self.make_zip, side="right")
        area = self.surface(self.body)
        area.pack(fill="both", expand=True)
        self.text(area, self.tr("report"), 12, INK, WHITE, "bold").pack(anchor="w", padx=12, pady=8)
        self.integrity_text = self.scrolling_text(area)
        report = self.snapshot_report()
        self.set_text(self.integrity_text, self.result_text or (
            json.dumps(report, ensure_ascii=False, indent=2) if report else self.tr("none")))

    def show_settings(self):
        box = self.surface(self.body)
        box.pack(fill="x")
        self.source_text = tk.StringVar(value=str(self.source) if self.source else "")
        self.vault_text = tk.StringVar(value=str(self.vault))
        for key, variable in (("source", self.source_text), ("vault", self.vault_text)):
            self.text(box, self.tr(key), 11, INK, WHITE, "bold").pack(anchor="w", padx=14, pady=(13, 2))
            row = tk.Frame(box, bg=WHITE)
            row.pack(fill="x", padx=14)
            ttk.Entry(row, textvariable=variable, font=("Segoe UI", 10)).pack(side="left", expand=True, fill="x", ipady=6)
            self.button(row, "choose", lambda v=variable: self.pick_path(v), side="left", padx=(8, 0))
            if key == "source":
                self.text(box, self.tr("auto"), 9, MUTED, WHITE).pack(anchor="w", padx=14, pady=(2, 0))
        self.text(box, self.tr("language"), 11, INK, WHITE, "bold").pack(anchor="w", padx=14, pady=(13, 1))
        self.language = tk.StringVar(value=self.locale)
        choice = tk.Frame(box, bg=WHITE)
        choice.pack(fill="x", padx=14)
        for label, value in (("English", "en"), ("简体中文", "zh")):
            tk.Radiobutton(choice, text=label, value=value, variable=self.language, bg=WHITE, fg=INK,
                           activebackground=WHITE, font=("Segoe UI", 10)).pack(side="left", padx=(0, 12))
        self.button(box, "save", self.save_settings, True, anchor="w", padx=14, pady=12)

    def pick_path(self, variable):
        value = filedialog.askdirectory(parent=self.root)
        if value:
            variable.set(value)

    def save_settings(self):
        source, vault = self.source_text.get().strip(), self.vault_text.get().strip()
        if not vault or (source and not Path(source).is_dir()):
            return messagebox.showerror("GravityKeeper", self.tr("folder_missing"), parent=self.root)
        self.source = Path(source) if source else None
        self.vault = Path(vault)
        self.locale = self.language.get()
        if not self.demo:
            self.config.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.config.with_suffix(".tmp")
            temporary.write_text(json.dumps({"source": source, "vault": vault, "language": self.locale},
                                            ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.config)
        self.render()
        self.refresh()

    def choose_snapshot(self):
        if self.busy:
            return
        value = filedialog.askdirectory(parent=self.root)
        if value:
            path = Path(value)
            if not (path / "01_Raw_Backup" / "BACKUP_MANIFEST.json").is_file():
                messagebox.showerror("GravityKeeper", self.tr("snapshot_missing"), parent=self.root)
                return
            self.set_snapshot(path)
            self.render()

    def set_snapshot(self, path):
        self.snapshot = path
        self.history_filter = None
        self.query_text = ""
        self.result_text = ""
        self.last_status = "loaded"

    def open_output(self):
        target = self.snapshot or self.vault
        if target.is_dir():
            os.startfile(str(target))
        else:
            messagebox.showinfo("GravityKeeper", self.tr("folder_missing"), parent=self.root)

    def refresh(self):
        self.start("discover", lambda _: probe(self.source, include_workspaces=True,
                                                include_installations=not self.demo, scratch=self.demo), self.after_probe)

    def after_probe(self, result):
        self.probe_result = result
        self.render()
        if self.demo and not self.snapshot:
            self.make_snapshot(True)

    def make_snapshot(self, complete):
        path = new_snapshot(self.vault)
        if self.demo and not self.snapshot:
            path = self.vault / "Fictional sample snapshot"
        source = self.source
        operation = full_backup if complete else capture
        self.start("capture", lambda cb: operation(path, source, cb), lambda result: self.after_export(path, result))

    def export_selected(self):
        if not self.snapshot:
            return self.choose_snapshot()
        path = self.snapshot
        self.start("export", lambda cb: export(path, cb), lambda result: self.after_export(path, result))

    def after_export(self, path, result):
        self.set_snapshot(path)
        self.last_status = "completed" if result["raw"] == "COMPLETE" and result["export"] in {"COMPLETE", "NOT_RUN"} else "error"
        self.render()
        if self.smoke_report:
            self.smoke_result["backup"] = result["raw"]
            self.smoke_result["export"] = result["export"]
            self.smoke_result["sessions"] = result["sessions"]
            self.navigate("history")
            self.query.set("Riverside")
            self.do_search()
            self.root.after(50, self.smoke_continue)

    def smoke_continue(self):
        if self.busy:
            self.root.after(50, self.smoke_continue)
            return
        self.smoke_result["search_results"] = len(self.entries)
        target = self.vault / "smoke.zip"
        self.start("zip", lambda cb: package_snapshot(self.snapshot, target, cb), self.finish_smoke)

    def finish_smoke(self, result):
        self.smoke_result["verified_zip_entries"] = result["files"]
        self.smoke_report.write_text(json.dumps(self.smoke_result, indent=2), encoding="utf-8")
        self.root.after(100, self.close)

    def verify_selected(self):
        if not self.snapshot:
            return self.choose_snapshot()
        self.start("verify", lambda cb: verify_snapshot(self.snapshot, cb), self.after_verify)

    def verify_zip_dialog(self):
        chosen = filedialog.askopenfilename(parent=self.root, filetypes=[("ZIP", "*.zip")])
        if chosen:
            self.start("verify_zip", lambda cb: verify_zip(Path(chosen), cb), self.after_verify)

    def make_zip(self):
        if not self.snapshot:
            return self.choose_snapshot()
        chosen = filedialog.asksaveasfilename(parent=self.root, defaultextension=".zip",
                                              initialfile=self.snapshot.name + ".zip", filetypes=[("ZIP", "*.zip")])
        if chosen:
            self.start("zip", lambda cb: package_snapshot(self.snapshot, Path(chosen), cb), self.after_verify)

    def after_verify(self, result):
        result = {key: value for key, value in result.items() if key != "manifest"}
        self.result_text = self.tr("verified") + "\n\n" + json.dumps(result, ensure_ascii=False, indent=2)
        self.page = "integrity"
        self.render()
        self.status.configure(text=self.tr("verified"))

    def start(self, phase, work, completion):
        if self.busy:
            return
        self.busy = True
        self.work_done = completion
        self.progress.configure(value=0)
        self.status.configure(text=PHASES[phase][self.locale == "zh"])

        def notify(stage, done, total):
            self.events.put(("progress", (stage, done, total)))

        def worker():
            try:
                result = work(notify)
            except Exception as exc:
                self.events.put(("error", (error_code(exc, "operation_failed"), str(exc))))
            else:
                self.events.put(("done", result))
        threading.Thread(target=worker, name="gravitykeeper-job").start()

    def drain(self):
        try:
            update = None
            for _ in range(400):
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "progress":
                    update = payload
                    continue
                update = None
                self.busy = False
                self.progress.configure(value=0)
                if kind == "error":
                    self.last_status = "error"
                    self.status.configure(text=self.tr("error"))
                    if self.smoke_report:
                        self.smoke_report.write_text(json.dumps({"error": payload}), encoding="utf-8")
                        self.root.after(10, self.close)
                    else:
                        messagebox.showerror("GravityKeeper", f"{payload[0]}\n{payload[1]}", parent=self.root)
                else:
                    self.last_status = "completed"
                    self.status.configure(text=self.tr("completed"))
                    self.work_done(payload)
            if update:
                phase, done, total = update
                self.progress.configure(value=100 * done / total if total else 0)
                caption = PHASES[phase][self.locale == "zh"]
                self.status.configure(text=f"{caption}   {done:,} / {total:,}" if total else caption)
        finally:
            self.root.after(45, self.drain)

    def close(self):
        if self.busy:
            messagebox.showinfo("GravityKeeper", self.tr("busy"), parent=self.root)
            return
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="GravityKeeper")
    parser.add_argument("--demo", action="store_true", help="Open the actual app with a generated fictional profile")
    parser.add_argument("--demo-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-report", type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    config = local / "GravityKeeper" / "settings.json"
    if options.demo or options.smoke_report:
        parent = options.smoke_report.resolve().parent if options.smoke_report else options.demo_root
        with isolated_directory(parent, "gkd_") as temp:
            root = tk.Tk()
            App(root, config, temp, options.smoke_report)
            root.mainloop()
    else:
        root = tk.Tk()
        App(root, config)
        root.mainloop()
