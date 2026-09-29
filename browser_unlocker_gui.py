"""Small Windows front end for the verified, reversible CUA browser patch."""

from dataclasses import replace
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import codex_browser_patch as patch


VERSION = "0.1.0-beta.1"
LABELS = {
    "missing": ("未找到浏览器运行时", "#976116"),
    "original": ("可解锁", "#186649"),
    "patched": ("已解锁（磁盘状态）", "#186649"),
    "disabled": ("补丁存在，开关已关闭", "#976116"),
    "unsupported": ("当前版本不受支持", "#a34539"),
    "conflict": ("检测到文件或恢复资料冲突", "#a34539"),
    "running": ("请先退出 Codex / Codex++", "#976116"),
}


def installed_codex():
    """Read the current user's Store registration, not a patch target."""
    command = (
        "Get-AppxPackage -Name OpenAI.Codex | "
        "Select-Object Version,InstallLocation | ConvertTo-Json -Compress"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, errors="replace", timeout=12,
        creationflags=flags, check=True,
    )
    if not result.stdout.strip():
        return "", ""
    packages = json.loads(result.stdout)
    if isinstance(packages, dict):
        packages = [packages]
    package = max(packages, key=lambda item: tuple(
        int(piece) for piece in item["Version"].split(".")))
    return package["Version"], package["InstallLocation"]


def default_homes():
    homes = []
    if os.environ.get("CODEX_HOME"):
        homes.append(patch.plain(Path(os.environ["CODEX_HOME"])))
    fallback = patch.plain(Path.home() / ".codex")
    if all(not patch.same_path(home, fallback) for home in homes):
        homes.append(fallback)
    return homes


def inspect(home_override=None, runtime_root=None, state_root=None):
    """No filesystem writes; path overrides also enable isolated fixture tests."""
    local = os.environ.get("LOCALAPPDATA")
    patch.require(local or runtime_root is not None, "LOCALAPPDATA is missing")
    runtime_root = patch.plain(runtime_root or Path(local) / "OpenAI/Codex/runtimes/cua_node")
    state_root = patch.plain(state_root or Path(local) / "CodexWinApiBrowserPatch")
    homes = [patch.plain(home_override)] if home_override else default_homes()
    try:
        selection = patch.find_runtime(homes, runtime_root)
    except (patch.Refused, OSError, ValueError, UnicodeError) as exc:
        snapshot = patch.inspect_status(runtime_root, state_root, None)
        return replace(snapshot, code="unsupported",
                       detail="CUA descriptor cannot be used: " + str(exc)), None
    return patch.inspect_status(runtime_root, state_root, selection), selection


def probe():
    """Safe packaged-resource check; does not read or modify a live runtime."""
    helper = Path(patch.__file__).with_name("require-identification.mjs").read_bytes()
    if b"cppNativeIdentificationReader" not in helper:
        raise RuntimeError("Bundled identification helper is invalid")
    if sys.stdout is not None:
        print(json.dumps({"version": VERSION, "helper_bytes": len(helper),
                          "resource": "ok"}, separators=(",", ":")))


def detail_text(snapshot):
    messages = {
        "missing": "尚未找到生成的 CUA 浏览器描述文件。启动过 Codex 后刷新。",
        "original": "服务文件为受支持的原件。退出 Codex 后可进行解锁。",
        "patched": "文件和本工具的恢复记录一致。仍需重新打开 Codex 实测浏览器。",
        "disabled": "补丁文件仍在，但本地开关已关闭。可在退出应用后重新启用或还原。",
        "unsupported": "当前运行时或插件描述文件不在已验证范围内。",
        "conflict": "检测到其他修改或恢复资料冲突，本工具不会覆盖。",
        "running": "Codex / Codex++ 尚在运行。请正常退出后刷新。",
    }
    text = messages[snapshot.code]
    if snapshot.code in {"unsupported", "conflict", "running"}:
        text += "\n" + snapshot.detail
    return text


class Unlocker(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Codex Browser Unlocker")
        self.geometry("760x500")
        self.minsize(650, 460)
        self.configure(bg="#f4f6f5")
        self.home_override = None
        self.snapshot = None
        self.selection = None
        self.runtime_root = Path(os.environ["LOCALAPPDATA"]) / "OpenAI/Codex/runtimes/cua_node"
        self.state_root = Path(os.environ["LOCALAPPDATA"]) / "CodexWinApiBrowserPatch"
        self.responses = queue.Queue()
        self.busy = False
        self._build()
        self.after(100, self._drain)
        self.refresh()

    def _build(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Action.TButton", font=("Microsoft YaHei UI", 10), padding=(16, 9))
        style.configure("Tool.TButton", font=("Microsoft YaHei UI", 9), padding=(10, 6))

        outer = tk.Frame(self, bg="#f4f6f5", padx=28, pady=22)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        header = tk.Frame(outer, bg="#f4f6f5")
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Codex 浏览器解锁", font=("Microsoft YaHei UI", 17, "bold"),
                 bg="#f4f6f5", fg="#1c2925").pack(side="left")
        tk.Label(header, text="v" + VERSION, font=("Segoe UI", 9),
                 bg="#f4f6f5", fg="#66766e").pack(side="right", pady=7)

        tk.Frame(outer, bg="#d7dfda", height=1).grid(row=1, column=0, sticky="ew", pady=(15, 17))
        summary = tk.Frame(outer, bg="#e8f0ea", padx=16, pady=12)
        summary.grid(row=2, column=0, sticky="ew")
        summary.columnconfigure(0, weight=1)
        self.state_label = tk.Label(summary, text="检测中…", font=("Microsoft YaHei UI", 11, "bold"),
                                    bg="#e8f0ea", fg="#1c2925", anchor="w")
        self.state_label.grid(row=0, column=0, sticky="ew")
        self.detail_label = tk.Label(summary, text="", font=("Microsoft YaHei UI", 9),
                                     bg="#e8f0ea", fg="#52615a", anchor="w",
                                     justify="left", wraplength=630)
        self.detail_label.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        summary.bind("<Configure>", lambda event: self.detail_label.configure(
            wraplength=max(300, event.width - 32)))

        info = tk.Frame(outer, bg="#f4f6f5")
        info.grid(row=3, column=0, sticky="nsew", pady=(19, 12))
        info.columnconfigure(1, weight=1)
        self.values = {}
        rows = (
            ("Codex App 版本", "app_version"),
            ("Codex App 安装路径", "app_path"),
            ("Codex 数据目录", "home"),
            ("CUA 运行时版本", "cua_version"),
            ("实际补丁文件", "service"),
            ("恢复资料", "recovery"),
        )
        for index, (label, key) in enumerate(rows):
            tk.Label(info, text=label, font=("Microsoft YaHei UI", 9),
                     bg="#f4f6f5", fg="#607169", anchor="nw", width=18).grid(
                row=index, column=0, sticky="nw", pady=6)
            value = tk.Label(info, text="检测中…", font=("Segoe UI", 9),
                             bg="#f4f6f5", fg="#1c2925", anchor="nw", justify="left",
                             wraplength=495)
            value.grid(row=index, column=1, sticky="ew", pady=6)
            self.values[key] = value
        info.bind("<Configure>", lambda event: [
            value.configure(wraplength=max(240, event.width - 195))
            for value in self.values.values()
        ])

        footer = tk.Frame(outer, bg="#f4f6f5")
        footer.grid(row=4, column=0, sticky="ew")
        self.choose_button = ttk.Button(footer, text="选择 Codex 路径",
                                        style="Tool.TButton", command=self.choose)
        self.choose_button.pack(side="left")
        self.refresh_button = ttk.Button(footer, text="刷新", style="Tool.TButton",
                                         command=self.refresh)
        self.refresh_button.pack(side="left", padx=(8, 0))
        self.restore_button = ttk.Button(footer, text="还原", style="Action.TButton",
                                         command=lambda: self.perform("restore"))
        self.restore_button.pack(side="right")
        self.apply_button = ttk.Button(footer, text="解锁浏览器", style="Action.TButton",
                                       command=lambda: self.perform("apply"))
        self.apply_button.pack(side="right", padx=(0, 8))
        tk.Label(outer, text="仅适配已验证指纹；磁盘已解锁不等于实际浏览器连接成功。",
                 font=("Microsoft YaHei UI", 9), bg="#f4f6f5", fg="#68766f",
                 anchor="w").grid(row=5, column=0, sticky="ew", pady=(15, 0))
        self._buttons()

    def _buttons(self):
        self.choose_button.configure(state="disabled" if self.busy else "normal")
        self.refresh_button.configure(state="disabled" if self.busy else "normal")
        self.apply_button.configure(state="normal" if not self.busy and self.snapshot and
                                    self.snapshot.can_apply else "disabled")
        self.restore_button.configure(state="normal" if not self.busy and self.snapshot and
                                      self.snapshot.can_restore else "disabled")

    def _launch(self, task):
        self.busy = True
        self._buttons()
        threading.Thread(target=task, daemon=True).start()

    def _drain(self):
        while True:
            try:
                kind, payload = self.responses.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            if kind == "status":
                snapshot, selection, app_version, app_path = payload
                self.snapshot, self.selection = snapshot, selection
                title, color = LABELS[snapshot.code]
                self.state_label.configure(text=title, fg=color)
                self.detail_label.configure(text=detail_text(snapshot))
                values = {
                    "app_version": app_version or "未检测到已注册的 Codex App",
                    "app_path": app_path or "未检测到",
                    "home": str(self.home_override or (Path(selection[1]) if selection else
                                default_homes()[0])),
                    "cua_version": snapshot.version or "未知",
                    "service": snapshot.service or "未选中",
                    "recovery": str(self.state_root) + "  (" +
                                str(snapshot.recovery_count) + " 条恢复记录)",
                }
                for key, text in values.items():
                    self.values[key].configure(text=text)
            elif kind == "done":
                messagebox.showinfo("操作完成", payload, parent=self)
                self.refresh()
            else:
                self.state_label.configure(text="操作未完成" if kind == "operation-error"
                                           else "状态读取失败", fg="#a34539")
                self.detail_label.configure(text=str(payload))
                if kind == "operation-error":
                    messagebox.showerror("已拒绝修改", str(payload), parent=self)
                    self.refresh()
            self._buttons()
        self.after(100, self._drain)

    def refresh(self):
        if self.busy:
            return
        self.state_label.configure(text="检测中…", fg="#1c2925")
        self.detail_label.configure(text="正在核对运行时和恢复资料。")
        self.snapshot = None

        def work():
            try:
                snapshot, selection = inspect(self.home_override, self.runtime_root, self.state_root)
                try:
                    version, app_path = installed_codex()
                except (OSError, ValueError, subprocess.SubprocessError):
                    version, app_path = "读取失败", "无法读取当前用户注册信息"
                self.responses.put(("status", (snapshot, selection, version, app_path)))
            except (patch.Refused, OSError, ValueError, UnicodeError) as exc:
                self.responses.put(("status-error", str(exc)))
        self._launch(work)

    def choose(self):
        folder = filedialog.askdirectory(parent=self, title="选择包含插件缓存的 Codex 数据目录")
        if not folder:
            return
        try:
            selected = patch.plain(Path(folder))
        except (patch.Refused, OSError) as exc:
            messagebox.showerror("路径不可用", str(exc), parent=self)
            return
        if not (selected / "plugins/cache/openai-bundled/unified-computer-use").is_dir():
            messagebox.showerror("不是 Codex 数据目录",
                                 "请选择含插件缓存的 .codex 数据目录，不是 App 安装目录。"
                                 "若尚未生成插件描述文件，请先启动过 Codex。", parent=self)
            return
        self.home_override = selected
        self.refresh()

    def perform(self, action):
        if self.busy or not self.snapshot:
            return
        allowed = self.snapshot.can_apply if action == "apply" else self.snapshot.can_restore
        if not allowed:
            return
        verb = "解锁浏览器" if action == "apply" else "还原"
        target = self.snapshot.service if action == "apply" else str(self.state_root)
        if not messagebox.askyesno("确认" + verb,
                                   "确认 Codex 与 Codex++ 已完全退出，并在操作结束前不会再次启动？\n\n"
                                   "目标：" + target + "\n\n此操作会修改本机 CUA 缓存；"
                                   "如检测到运行进程或文件冲突将拒绝写入。",
                                   parent=self):
            return

        def work():
            try:
                latest, selection = inspect(self.home_override, self.runtime_root, self.state_root)
                if action == "apply":
                    patch.require(latest.can_apply, latest.detail)
                    patch.apply(self.runtime_root, self.state_root, selection)
                    text = "已写入并校验补丁。重新打开 Codex 后，在新的浏览器工具上下文中真人测试。"
                else:
                    patch.require(latest.can_restore, latest.detail)
                    patch.restore(self.runtime_root, self.state_root)
                    text = "还原操作完成。已保留恢复资料；扩展内部已保存的请求标识不会由此清除。"
                self.responses.put(("done", text))
            except (patch.Refused, OSError, ValueError, UnicodeError) as exc:
                self.responses.put(("operation-error", str(exc)))
        self._launch(work)


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    if len(sys.argv) == 2 and sys.argv[1] == "--probe":
        probe()
        return
    if len(sys.argv) != 1:
        raise SystemExit("Unknown argument")
    if not os.environ.get("LOCALAPPDATA"):
        raise SystemExit("LOCALAPPDATA is missing")
    Unlocker().mainloop()


if __name__ == "__main__":
    main()
