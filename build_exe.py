"""
打包脚本：把 main_gui.py 和 analyzer.py 打成单个 EXE。
使用方法：
    1. pip install pyinstaller
    2. python build_exe.py
"""
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()


def main():
    # 检查依赖
    try:
        import PyInstaller
    except ImportError:
        print("[!] 未安装 PyInstaller，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "pyinstaller"])

    # PyInstaller 命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                          # 单文件 EXE
        "--windowed",                         # 不显示控制台（GUI 程序）
        "--name=StickAnalyzer",
        "--clean",                            # 清理临时文件
        "--noconfirm",                        # 覆盖输出
        # 隐式导入（确保 matplotlib 后端等被打包）
        "--hidden-import=matplotlib.backends.backend_agg",
        "--hidden-import=XInput",
        "--hidden-import=pandas",
        "--hidden-import=numpy",
        "--hidden-import=PIL",
        # 把 analyzer.py 作为普通模块打包（不是数据文件）
        "main_gui.py",
    ]

    # Windows 上，把 analyzer.py 作为额外的脚本一起打包
    # 改用 --add-data 让它能被 _import_analyzer() 找到
    if sys.platform == "win32":
        sep = ";"
    else:
        sep = ":"
    # analyzer.py 作为数据文件放到根目录
    cmd.insert(-1, f"--add-data=analyzer.py{sep}.")

    print("[*] 开始打包...")
    print(f"[*] 命令: {' '.join(cmd)}")
    print()

    try:
        subprocess.check_call(cmd, cwd=PROJECT_DIR)
    except subprocess.CalledProcessError as e:
        print(f"[X] 打包失败: {e}")
        sys.exit(1)

    exe_path = PROJECT_DIR / "dist" / "StickAnalyzer.exe"
    if exe_path.exists():
        print()
        print(f"[√] 打包成功！EXE 位置: {exe_path}")
        print(f"[√] 文件大小: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
        print()
        print("使用说明：")
        print("  - 直接双击 StickAnalyzer.exe 即可运行")
        print("  - 第一次启动可能需要 5-10 秒（加载 matplotlib）")
        print("  - 不需要安装 Python 或任何依赖")
        print("  - 可以拷贝到任何 Windows 电脑使用")
    else:
        print(f"[X] EXE 未生成，请检查上方错误")


if __name__ == "__main__":
    main()
