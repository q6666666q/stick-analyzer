"""
error_reporter.py
================================
错误反馈模块。

功能：
- 弹出友好的错误反馈窗口，引导用户复制错误信息发给作者
- 自动收集系统信息（操作系统、Python 版本、依赖版本等）
- 全局异常钩子，捕获未处理的异常
- 错误日志本地保存（追加到 errors.log）

引导渠道：
- B站 / 抖音：josef_0464
- QQ 群：611624374（星辰不妙屋）
"""
from __future__ import annotations

import os
import sys
import platform
import traceback
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox


# 错误日志文件路径（在用户家目录或当前目录）
def _get_log_dir() -> Path:
    """获取日志目录。优先用程序所在目录，其次用户家目录"""
    try:
        # 程序所在目录
        if getattr(sys, "frozen", False):
            # PyInstaller 打包后
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).parent
        if os.access(app_dir, os.W_OK):
            return app_dir
    except Exception:
        pass
    # 兜底：用户家目录
    return Path.home()


LOG_FILE = _get_log_dir() / "stick_analyzer_errors.log"


# 联系方式（与 main_gui 保持一致）
CONTACT_BILIBILI = "B站 / 抖音: josef_0464"
CONTACT_QQ_GROUP = "QQ 群: 611624374 (星辰不妙屋)"


def collect_system_info() -> str:
    """收集系统信息，附在错误报告里"""
    lines = []
    lines.append("=" * 50)
    lines.append("系统信息")
    lines.append("=" * 50)
    try:
        lines.append(f"操作系统: {platform.system()} {platform.release()} "
                     f"({platform.version()})")
    except Exception:
        lines.append("操作系统: 未知")
    try:
        lines.append(f"机器架构: {platform.machine()}")
    except Exception:
        pass
    try:
        lines.append(f"Python 版本: {sys.version.split()[0]}")
    except Exception:
        pass

    # 工具版本
    try:
        import main_gui
        lines.append(f"工具版本: {getattr(main_gui, 'APP_VERSION', '未知')}")
    except Exception:
        pass

    # 关键依赖版本
    deps = ["pygame", "XInput", "matplotlib", "numpy", "pandas"]
    for name in deps:
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", None) or getattr(mod, "version", None)
            if callable(ver):
                ver = ver()
            elif hasattr(ver, "ver"):
                ver = ver.ver
            lines.append(f"{name}: {ver if ver else '已安装（版本未知）'}")
        except ImportError:
            lines.append(f"{name}: 未安装")
        except Exception as e:
            lines.append(f"{name}: 检测失败（{e}）")

    return "\n".join(lines)


def format_error_report(
    error_type: str,
    error_message: str,
    traceback_text: str = "",
    extra_context: str = "",
) -> str:
    """格式化完整的错误报告"""
    parts = []
    parts.append("=" * 50)
    parts.append("摇杆射击行为分析工具 - 错误报告")
    parts.append("=" * 50)
    parts.append(f"时间: {datetime.now().isoformat()}")
    parts.append(f"错误类型: {error_type}")
    parts.append(f"错误信息: {error_message}")
    parts.append("")

    if extra_context:
        parts.append("发生场景:")
        parts.append(extra_context)
        parts.append("")

    if traceback_text:
        parts.append("=" * 50)
        parts.append("详细堆栈")
        parts.append("=" * 50)
        parts.append(traceback_text)
        parts.append("")

    parts.append(collect_system_info())
    return "\n".join(parts)


def append_to_log(report_text: str) -> None:
    """把错误报告追加到本地日志文件"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n\n")
            f.write(report_text)
            f.write("\n")
    except Exception:
        # 日志写入失败也不能影响弹窗
        pass


class ErrorReportDialog(tk.Toplevel):
    """错误反馈弹窗（非阻塞）"""

    def __init__(self, parent, error_type: str, error_message: str,
                 traceback_text: str = "", extra_context: str = ""):
        super().__init__(parent)
        self.title("⚠ 出错了 - 请帮助我们改进")
        self.geometry("680x600")

        # 居中
        try:
            self.transient(parent)
        except Exception:
            pass

        self.report_text = format_error_report(
            error_type, error_message, traceback_text, extra_context)

        # 自动写入日志
        append_to_log(self.report_text)

        self._build_ui(error_type, error_message)

    def _build_ui(self, error_type: str, error_message: str):
        # 顶部错误标题区
        top_frame = tk.Frame(self, bg="#FDF2F2", relief="solid", bd=1)
        top_frame.pack(fill="x", padx=10, pady=10)

        tk.Label(top_frame,
                 text="⚠ 程序遇到了错误",
                 bg="#FDF2F2", fg="#C92A2A",
                 font=("Microsoft YaHei", 12, "bold")).pack(anchor="w",
                                                              padx=10, pady=(8, 4))

        tk.Label(top_frame,
                 text=f"错误类型: {error_type}",
                 bg="#FDF2F2", fg="#333",
                 font=("Microsoft YaHei", 9)).pack(anchor="w", padx=10)

        # 错误消息（限长以免太长）
        msg_short = error_message
        if len(msg_short) > 200:
            msg_short = msg_short[:200] + "..."
        tk.Label(top_frame,
                 text=f"错误信息: {msg_short}",
                 bg="#FDF2F2", fg="#333",
                 font=("Microsoft YaHei", 9),
                 wraplength=620, justify="left").pack(anchor="w", padx=10,
                                                       pady=(0, 8))

        # 详细错误信息文本框
        detail_frame = ttk.LabelFrame(self, text="完整错误信息（请复制这部分）",
                                       padding=8)
        detail_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 滚动文本框
        text_container = tk.Frame(detail_frame)
        text_container.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(text_container)
        scrollbar.pack(side="right", fill="y")

        self.text_widget = tk.Text(text_container,
                                     wrap="word",
                                     font=("Consolas", 9),
                                     yscrollcommand=scrollbar.set,
                                     height=14)
        self.text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.text_widget.yview)

        self.text_widget.insert("1.0", self.report_text)
        self.text_widget.configure(state="normal")  # 允许选中复制

        # 联系方式区
        contact_frame = tk.Frame(self, bg="#FFF3CD", relief="solid", bd=1)
        contact_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Label(contact_frame,
                 text="📮 请把以上错误信息发给作者帮助修复 Bug：",
                 bg="#FFF3CD", fg="#856404",
                 font=("Microsoft YaHei", 10, "bold")).pack(anchor="w",
                                                              padx=10, pady=(8, 4))
        tk.Label(contact_frame,
                 text=f"  • {CONTACT_BILIBILI}",
                 bg="#FFF3CD", fg="#333",
                 font=("Microsoft YaHei", 9)).pack(anchor="w", padx=10)
        tk.Label(contact_frame,
                 text=f"  • {CONTACT_QQ_GROUP}",
                 bg="#FFF3CD", fg="#333",
                 font=("Microsoft YaHei", 9)).pack(anchor="w", padx=10,
                                                    pady=(0, 8))

        # 按钮区
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(btn_frame, text="📋 复制全部错误信息",
                   command=self._copy_to_clipboard).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="💾 保存到文件",
                   command=self._save_to_file).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="📁 打开错误日志位置",
                   command=self._open_log_dir).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="关闭",
                   command=self.destroy).pack(side="right", padx=2)

    def _copy_to_clipboard(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.report_text)
            self.update()
            messagebox.showinfo("成功",
                "错误信息已复制到剪贴板！\n\n"
                "请粘贴到聊天框发给：\n"
                f"• {CONTACT_BILIBILI}\n"
                f"• {CONTACT_QQ_GROUP}",
                parent=self)
        except Exception as e:
            messagebox.showerror("错误", f"复制失败: {e}", parent=self)

    def _save_to_file(self):
        from tkinter import filedialog
        f = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
            initialfile=f"error_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if f:
            try:
                Path(f).write_text(self.report_text, encoding="utf-8")
                messagebox.showinfo("成功", f"已保存到 {f}", parent=self)
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}", parent=self)

    def _open_log_dir(self):
        try:
            log_dir = LOG_FILE.parent
            if sys.platform == "win32":
                os.startfile(log_dir)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", str(log_dir)])
            else:
                import subprocess
                subprocess.run(["xdg-open", str(log_dir)])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开目录: {e}", parent=self)


# ==================== 全局异常钩子 ====================

_root_window = None  # 由 install_exception_hook 设置


def install_exception_hook(root: tk.Tk) -> None:
    """安装全局异常钩子。

    捕获两类异常：
    1. tkinter 主循环里的异常（report_callback_exception）
    2. 其他线程未捕获的异常（threading.excepthook）
    """
    global _root_window
    _root_window = root

    def on_tk_exception(exc_type, exc_value, exc_tb):
        """tkinter 主循环异常处理"""
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        # 防止反复弹窗（如果错误窗口本身也出错）
        try:
            ErrorReportDialog(
                _root_window,
                error_type=exc_type.__name__,
                error_message=str(exc_value),
                traceback_text=tb_text,
                extra_context="GUI 主循环中触发"
            )
        except Exception:
            # 错误窗口创建失败，回退到日志
            append_to_log(format_error_report(
                exc_type.__name__, str(exc_value), tb_text,
                "GUI 主循环中触发（错误窗口创建失败）"))

    def on_thread_exception(args):
        """子线程未捕获异常处理"""
        tb_text = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))

        # 子线程不能直接操作 GUI，要切回主线程
        def show():
            try:
                ErrorReportDialog(
                    _root_window,
                    error_type=args.exc_type.__name__,
                    error_message=str(args.exc_value),
                    traceback_text=tb_text,
                    extra_context=f"子线程异常 (thread: {args.thread.name})"
                )
            except Exception:
                append_to_log(format_error_report(
                    args.exc_type.__name__, str(args.exc_value), tb_text,
                    f"子线程异常 (thread: {args.thread.name})"))

        if _root_window is not None:
            try:
                _root_window.after(0, show)
            except Exception:
                # 主窗口已销毁，直接写日志
                append_to_log(format_error_report(
                    args.exc_type.__name__, str(args.exc_value), tb_text,
                    f"子线程异常（主窗口已销毁）"))

    # 安装 tkinter 钩子
    root.report_callback_exception = on_tk_exception

    # 安装 threading 钩子（Python 3.8+）
    if hasattr(threading, "excepthook"):
        threading.excepthook = on_thread_exception


def show_error_dialog(parent, error_type: str, error_message: str,
                       exception: Exception | None = None,
                       extra_context: str = "") -> None:
    """主动调用：弹出错误反馈窗口。

    用于 try/except 捕获后的友好提示。
    例如:
        try:
            do_something()
        except Exception as e:
            show_error_dialog(self, "录制失败", str(e), e, "用户开始录制时")
    """
    tb_text = ""
    if exception is not None:
        tb_text = "".join(traceback.format_exception(
            type(exception), exception, exception.__traceback__))
    try:
        ErrorReportDialog(parent, error_type, error_message, tb_text, extra_context)
    except Exception:
        # 极端情况：弹窗本身失败，至少写日志
        append_to_log(format_error_report(
            error_type, error_message, tb_text, extra_context))


# ==================== 自测 ====================
if __name__ == "__main__":
    print("收集到的系统信息：")
    print(collect_system_info())
    print()
    print(f"日志文件位置：{LOG_FILE}")

    # 弹一个测试窗口
    root = tk.Tk()
    root.title("测试")
    root.geometry("300x100")
    install_exception_hook(root)

    def trigger_error():
        # 故意触发异常测试
        raise ValueError("这是一个测试错误，演示错误反馈弹窗效果")

    def trigger_thread_error():
        def bad_worker():
            raise RuntimeError("这是子线程的测试错误")
        threading.Thread(target=bad_worker, daemon=True).start()

    ttk.Button(root, text="触发主线程异常", command=trigger_error).pack(pady=10)
    ttk.Button(root, text="触发子线程异常", command=trigger_thread_error).pack(pady=5)
    root.mainloop()
