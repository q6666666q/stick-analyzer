# EXE 打包使用指南

## 一键打包

在工程目录下运行：

```bash
python build_exe.py
```

脚本会自动：
1. 检查并安装 PyInstaller
2. 把 `main_gui.py` + `analyzer.py` 打包成单个 `StickAnalyzer.exe`
3. 输出到 `dist/StickAnalyzer.exe`

打包过程大约 1-2 分钟，最终 EXE 大小约 80-150MB（包含了 matplotlib、pandas 等所有依赖）。

## 使用方法

直接双击 `StickAnalyzer.exe` 即可运行，**完全不需要 Python 环境**。

第一次启动可能需要 5-10 秒（解压依赖到临时目录）。

## GUI 使用流程

### 标签 1：录制摇杆数据

1. 填写元数据（RC 值、曲线版本、武器、场景等）—— 可选，但建议填
2. 选择输出目录
3. 点击 **● 开始录制**
4. 正常打游戏（屏幕上有实时状态显示，按 RB 应看到 FIRE 标记，按方向上键应看到 ADS 标记）
5. 打完后回到 GUI 点 **■ 停止录制**
6. 程序提示是否切换到分析页面

### 标签 2：分析数据

1. CSV 路径会自动填入（刚录的那个），或手动选择历史 CSV
2. 调整参数：最大事件数、最短爆发时长
3. 点 **▶ 开始分析**
4. 结果显示在下方文本框
5. 完成后可点 **📁 打开输出目录** 查看生成的图表

## 改键位

如果你的开火/开镜键和默认不同，需要修改源码：

打开 `main_gui.py`，找到顶部：
```python
FIRE_BUTTON = "RIGHT_SHOULDER"
ADS_BUTTON = "DPAD_UP"
```

改成你需要的，然后重新打包：
```bash
python build_exe.py
```

可选值：`A`、`B`、`X`、`Y`、`DPAD_UP/DOWN/LEFT/RIGHT`、
`LEFT_SHOULDER`、`RIGHT_SHOULDER`、`TRIGGER_LEFT`、`TRIGGER_RIGHT` 等。

## 常见问题

### Q: 双击 EXE 没反应？
- 可能被杀软误杀（PyInstaller 打包的 EXE 经常被误判）
- 把 EXE 加入杀软白名单，或用命令行运行看错误：`StickAnalyzer.exe`

### Q: 提示"未检测到任何手柄"？
- 确认手柄连接正常，并被识别为 XBOX 360 兼容控制器
- 在 Windows 设置 → 设备 → 蓝牙和其他设备 里能看到手柄

### Q: 录制时按键没反应（FIRE/ADS 标记不亮）？
- 默认键位是 RB + 方向上键
- 如果你的键位不同，按"改键位"章节修改并重新打包

### Q: 生成的图中文显示方框？
- 确保系统装了 Microsoft YaHei 字体（Windows 自带）
- 如果是精简版 Windows，可能需要安装中文字体包

### Q: EXE 太大（100MB+）？
- 这是正常的，因为打包了 matplotlib、pandas、numpy 等大库
- 如果想减小，可以用 `--exclude-module` 排除不需要的模块
- 或者改用 nuitka 打包（体积更小但更慢）

### Q: 打包失败？
- 查看错误信息，最常见的是依赖缺失
- 先确认能直接运行：`python main_gui.py`，能跑通再打包
- PyInstaller 版本建议 6.0+
