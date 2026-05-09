"""
打包脚本（v2.1）
================================
把所有 Python 模块打包成 StickAnalyzer。

两种模式（启动时会询问）：
  1. onedir 模式（推荐）：打包为文件夹，启动快（3-8 秒），分发为 zip
  2. onefile 模式：单个 EXE，启动慢（30-90 秒），双击即用

使用方法：
    1. 确保已激活虚拟环境（如果用了 .venv）
    2. pip install pyinstaller
    3. python build_exe.py

输出：
    onedir 模式 → dist/StickAnalyzer/StickAnalyzer.exe
    onefile 模式 → dist/StickAnalyzer.exe
"""
import subprocess
import sys
import os
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()

# 需要打包的模块（除了 main_gui.py 作为入口）
SUB_MODULES = [
    "analyzer.py",
    "controller_backend.py",
    "error_reporter.py",
]

# 关键的隐式导入（PyInstaller 静态分析可能漏掉的）
HIDDEN_IMPORTS = [
    # matplotlib 后端
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_tkagg",
    # 控制器驱动
    "pygame",
    "XInput",
    # 数据处理
    "pandas",
    "numpy",
    "PIL",
    # tkinter
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
]


def check_dependencies():
    """打包前检查所有依赖"""
    print("=" * 60)
    print("步骤 1：检查依赖")
    print("=" * 60)

    try:
        import PyInstaller
        print(f"[√] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[!] 未安装 PyInstaller，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "pyinstaller"])
        print("[√] PyInstaller 安装完成")

    required = {
        "pygame": "pygame",
        "matplotlib": "matplotlib",
        "numpy": "numpy",
        "pandas": "pandas",
    }
    missing = []
    for import_name, pkg_name in required.items():
        try:
            __import__(import_name)
            print(f"[√] {import_name}")
        except ImportError:
            missing.append(pkg_name)
            print(f"[X] {import_name} 未安装")

    try:
        import XInput
        print(f"[√] XInput-Python（可选，已安装）")
    except ImportError:
        print(f"[!] XInput-Python 未安装（可选，但建议装上）")

    if missing:
        print()
        print(f"[!] 缺少必需依赖：{', '.join(missing)}")
        choice = input("是否自动安装？[y/N]: ").strip().lower()
        if choice == "y":
            subprocess.check_call([sys.executable, "-m", "pip", "install",
                                   *missing])
            print("[√] 依赖安装完成")
        else:
            print("[X] 缺少依赖，无法继续")
            sys.exit(1)
    print()


def check_source_files():
    """检查源文件存在"""
    print("=" * 60)
    print("步骤 2：检查源文件")
    print("=" * 60)

    main_file = PROJECT_DIR / "main_gui.py"
    if not main_file.exists():
        print(f"[X] 找不到 main_gui.py")
        sys.exit(1)
    print(f"[√] main_gui.py")

    for mod in SUB_MODULES:
        path = PROJECT_DIR / mod
        if path.exists():
            print(f"[√] {mod}")
        else:
            print(f"[!] {mod} 不存在（如果不需要可忽略）")
    print()


def choose_mode() -> str:
    """让用户选择打包模式"""
    print("=" * 60)
    print("步骤 3：选择打包模式")
    print("=" * 60)
    print()
    print("两种打包模式可选：")
    print()
    print("  [1] onedir 模式（推荐）⭐")
    print("      - 打包为文件夹，包含 StickAnalyzer.exe 和 _internal/ 目录")
    print("      - 启动速度：3-8 秒")
    print("      - 杀软误报率低")
    print("      - 任务管理器只显示 1 个 StickAnalyzer 进程")
    print("      - 分发方式：把整个 StickAnalyzer 文件夹打包成 zip 发给用户")
    print("      - 用户解压后双击 StickAnalyzer.exe 即可")
    print()
    print("  [2] onefile 模式")
    print("      - 打包为单个 EXE 文件")
    print("      - 启动速度：30-90 秒（首次更慢，约 1 分钟）")
    print("      - 杀软误报率较高")
    print("      - [注意] 任务管理器会显示 2 个 StickAnalyzer 进程：")
    print("              1 个是 PyInstaller bootloader（解压临时文件用）")
    print("              1 个是真正的程序进程")
    print("              这是 onefile 模式的正常机制，不是 bug。")
    print("              但因为内存占用会翻倍，长时间运行不推荐。")
    print("      - 分发方式：直接发 EXE")
    print("      - 用户双击 EXE 即可（但要等待解压）")
    print()
    while True:
        choice = input("请选择 [1/2]，回车默认选 1: ").strip()
        if choice == "" or choice == "1":
            return "onedir"
        if choice == "2":
            return "onefile"
        print("无效选项，请输入 1 或 2")


def build(mode: str):
    """执行打包"""
    print()
    print("=" * 60)
    print(f"步骤 4：执行打包（{mode} 模式）")
    print("=" * 60)

    sep = ";" if sys.platform == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        f"--{mode}",                  # onefile 或 onedir
        "--windowed",
        "--name=StickAnalyzer",
        "--clean",
        "--noconfirm",
    ]

    for imp in HIDDEN_IMPORTS:
        cmd.append(f"--hidden-import={imp}")

    for mod in SUB_MODULES:
        path = PROJECT_DIR / mod
        if path.exists():
            cmd.append(f"--add-data={mod}{sep}.")

    cmd.append("main_gui.py")

    print("[*] 命令:")
    print(" ".join(cmd))
    print()
    print("[*] 开始打包，这可能需要 1-3 分钟...")
    print()

    try:
        subprocess.check_call(cmd, cwd=PROJECT_DIR)
    except subprocess.CalledProcessError as e:
        print(f"[X] 打包失败: {e}")
        sys.exit(1)


def show_result(mode: str):
    """显示结果"""
    print()
    print("=" * 60)

    if mode == "onefile":
        exe_path = PROJECT_DIR / "dist" / "StickAnalyzer.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / 1024 / 1024
            print(f"✅ 打包成功！(onefile 模式)")
            print("=" * 60)
            print(f"EXE 位置: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
            print()
            print("⚠ 注意：onefile 模式启动慢，第一次启动可能需要 30-90 秒")
            print("   如果觉得太慢，建议用 onedir 模式重新打包")
        else:
            print("❌ EXE 未生成，请检查上方错误")
            sys.exit(1)
    else:  # onedir
        out_dir = PROJECT_DIR / "dist" / "StickAnalyzer"
        exe_path = out_dir / "StickAnalyzer.exe"
        if exe_path.exists():
            # 计算总目录大小
            total_size = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
            size_mb = total_size / 1024 / 1024
            file_count = sum(1 for _ in out_dir.rglob("*") if _.is_file())
            print(f"✅ 打包成功！(onedir 模式 - 推荐)")
            print("=" * 60)
            print(f"输出目录: {out_dir}")
            print(f"主程序: {exe_path}")
            print(f"目录大小: {size_mb:.1f} MB（包含 {file_count} 个文件）")
            print()
            print("使用说明：")
            print("  • 进入 dist/StickAnalyzer/ 文件夹")
            print("  • 双击 StickAnalyzer.exe 即可运行")
            print("  • 启动速度：3-8 秒")
            print()
            print("分发说明：")
            print("  • 把整个 StickAnalyzer 文件夹打包成 zip")
            print("  • 用户解压到任意位置，双击 StickAnalyzer.exe 运行")
            print("  • 不要单独发 StickAnalyzer.exe，它需要 _internal/ 目录")
            print()

            # 提示用户是否自动打 zip
            try:
                choice = input("是否自动打包成 zip 方便分发？[y/N]: ").strip().lower()
                if choice == "y":
                    zip_path = PROJECT_DIR / "dist" / "StickAnalyzer.zip"
                    print(f"[*] 正在创建 {zip_path}...")
                    if zip_path.exists():
                        zip_path.unlink()
                    shutil.make_archive(
                        str(zip_path.with_suffix("")),
                        "zip",
                        root_dir=str(PROJECT_DIR / "dist"),
                        base_dir="StickAnalyzer"
                    )
                    if zip_path.exists():
                        zip_size = zip_path.stat().st_size / 1024 / 1024
                        print(f"[√] 已创建 {zip_path}（{zip_size:.1f} MB）")
            except Exception as e:
                print(f"[!] 自动打 zip 失败: {e}")
        else:
            print("❌ 输出目录或 EXE 未生成，请检查上方错误")
            sys.exit(1)


def main():
    print()
    print("█" * 60)
    print("█  摇杆射击行为分析工具 v2.1 打包脚本")
    print("█" * 60)
    print()

    check_dependencies()
    check_source_files()
    mode = choose_mode()
    build(mode)
    show_result(mode)


if __name__ == "__main__":
    main()
