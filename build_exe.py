"""
打包脚本（v2.0）
================================
把所有 Python 模块打包成单个 StickAnalyzer.exe。

使用方法：
    1. 确保已激活虚拟环境（如果用了 .venv）
    2. pip install pyinstaller
    3. python build_exe.py

输出：dist/StickAnalyzer.exe
"""
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()

# v2.0 需要打包的模块（除了 main_gui.py 作为入口）
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
    # tkinter（一般会自动包含，但稳妥起见加上）
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

    # 检查 PyInstaller
    try:
        import PyInstaller
        print(f"[√] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[!] 未安装 PyInstaller，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "pyinstaller"])
        print("[√] PyInstaller 安装完成")

    # 检查打包必需的依赖
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

    # 检查可选依赖
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


def build():
    """执行打包"""
    print("=" * 60)
    print("步骤 3：执行打包")
    print("=" * 60)

    # 平台分隔符
    sep = ";" if sys.platform == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                  # 单文件 EXE
        "--windowed",                 # 不显示控制台
        "--name=StickAnalyzer",
        "--clean",                    # 清理临时文件
        "--noconfirm",                # 覆盖输出
    ]

    # 隐式导入
    for imp in HIDDEN_IMPORTS:
        cmd.append(f"--hidden-import={imp}")

    # 把所有子模块作为数据文件添加（这样 main_gui 的 import 才能找到它们）
    for mod in SUB_MODULES:
        path = PROJECT_DIR / mod
        if path.exists():
            cmd.append(f"--add-data={mod}{sep}.")

    # 入口文件
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


def show_result():
    """显示结果"""
    exe_path = PROJECT_DIR / "dist" / "StickAnalyzer.exe"
    print()
    print("=" * 60)
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / 1024 / 1024
        print(f"✅ 打包成功！")
        print("=" * 60)
        print(f"EXE 位置: {exe_path}")
        print(f"文件大小: {size_mb:.1f} MB")
        print()
        print("使用说明：")
        print("  • 直接双击 StickAnalyzer.exe 即可运行")
        print("  • 第一次启动可能需要 5-15 秒（解压依赖到临时目录）")
        print("  • 不需要在目标电脑安装 Python 或任何依赖")
        print("  • 可以拷贝到任何 Windows 10/11 电脑使用")
        print()
        print("注意事项：")
        print("  • 部分杀软可能误报（PyInstaller 打包的 EXE 常见问题）")
        print("  • 如果被杀软删除，加入白名单即可")
        print("  • 如果某些用户启动失败，报错信息会引导他们反馈")
    else:
        print(f"❌ EXE 未生成")
        print("=" * 60)
        print("请检查上方错误信息")
        sys.exit(1)


def main():
    print()
    print("█" * 60)
    print("█  摇杆射击行为分析工具 v2.0 打包脚本")
    print("█" * 60)
    print()

    check_dependencies()
    check_source_files()
    build()
    show_result()


if __name__ == "__main__":
    main()
