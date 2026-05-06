"""
摇杆射击行为分析工具 - GUI 主程序
功能：录制 → 分析 → 生成 AI 调参提示词 → 参考曲线收集

v2.0 主要功能：
- 双驱动控制器支持：pygame（PS4/PS5/DualSense Edge/通用 HID）+ XInput（XBOX）
- 4 槽位手柄管理（按插入顺序）
- 按键标签自动适配（PS 显示 × ○ □ △，XBOX 显示 A B X Y）
- DualSense Edge 背键 FN1/FN2/RB1/RB2 支持
- 三步式工作流：录制 → 分析 → AI 提示词
- 参考曲线收集指南（纯文字引导，不操作游戏）
"""
import sys
import os
import threading
import subprocess
import csv
import time
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# 引入控制器抽象层
try:
    import controller_backend as cb
except ImportError:
    cb = None

# 引入错误反馈模块
try:
    import error_reporter
except ImportError:
    error_reporter = None

# ==================== 默认配置 ====================
DEFAULT_FIRE_BUTTON = "RIGHT_SHOULDER"   # 逻辑代码（RB / R1 / R 等等）
DEFAULT_ADS_BUTTON = "DPAD_UP"
TARGET_RATE_HZ = 500   # pygame 实际能力 ~500Hz；XInput 也用同值确保 GUI 流畅

APP_VERSION = "v2.0"
# ===================================================


def _import_analyzer():
    try:
        import analyzer as analyzer_mod
        return analyzer_mod
    except ImportError:
        return None


# ==================== AI 调参提示词模板 ====================
AI_PROMPT_TEMPLATE = """我在玩 FPS 游戏（如 Apex Legends），想让你帮我根据数据优化我的手柄摇杆曲线。

## 一、我的手柄信息（必填）

【请填写你的手柄型号和支持的曲线点数。不同手柄支持的可调节点数不一样，常见情况：】

- 我的手柄型号：______（例如：北通宙斯系列 / 雷蛇飓兽 / 八位堂 / 飞智 / 莱仕达 / 其他）
- 我的曲线编辑方式：______（请从下方选一个）
  - [ ] A. 支持 JSON 导入导出（直接粘贴曲线 JSON）
  - [ ] B. 只能在 APP 里手动拖动节点输入坐标（需要给我列出每个节点的 X, Y 数值）
  - [ ] C. 我也不确定，请按 B 方式给我（最通用）

- 我的曲线可调节点数：______（数一下你的 APP 里有几个可调点，包括起点终点）
  - [ ] 2 个点（起点 + 终点，最简单的线性调整）
  - [ ] 4 个点（起点 + 2 个中间点 + 终点）
  - [ ] 6 个点
  - [ ] 8 个点（最常见）
  - [ ] 其他：____ 个点

## 二、我当前的曲线配置

【根据你上面选的方式，从下面任选一种填写：】

### 方式 A（JSON 导入型）：
腰射曲线：
{
  "name": "腰射",
  "data": [0, 0, ..., 100, 100]
}

开镜曲线：
{
  "name": "开镜",
  "data": [0, 0, ..., 100, 100]
}

### 方式 B（手动输入型，按节点列出）：
腰射曲线（共 N 个点）：
- 节点 1：X=0,    Y=0
- 节点 2：X=__,   Y=__
- 节点 3：X=__,   Y=__
- ...
- 节点 N：X=100,  Y=100

开镜曲线（共 N 个点）：
- 节点 1：X=0,    Y=0
- 节点 2：X=__,   Y=__
- ...

## 三、我的痛点（必填，越具体越好）

【请把你当前体感上的具体问题写在这里。例如：】
- 中近距离贴脸甩枪跟不上
- 开镜后准星会在敌人身上小幅晃动停不下来
- 远程压枪到后段会过冲

## 四、我的 RC（动感）设置（如果手柄有这个功能）

【不同手柄 RC 数值范围差异极大（±10、±100、±500 都有），所以请用相对比例描述：】
- 我的手柄是否支持 RC 功能：[ ] 是  [ ] 否（不支持就跳过下面）
- 我的 APP 里 RC 可调范围是：从 ____ 到 ____（例如 -10 到 +10，或 -500 到 +500）
- 我当前的 RC 设置是：______（具体数字）
- 折算成百分比大约是：______%（例如 RC=-7 在 ±10 范围里就是 70%）
- 方向：[ ] 动感方向  [ ] 防抖方向  [ ] 中性/0

## 五、数据分析报告

{REPORT_CONTENT}

## 六、参考曲线（如果你有的话，可以一起提供给 AI）

【如果你能找到游戏的真实曲线，或者其他玩家公开的成熟曲线，可以贴在这里：】

例如：
- 我从游戏设置截图里看到的曲线（截图描述或节点：______）
- 某 B站大佬公布的同游戏曲线参数：______
- 我朋友用着体感很好的曲线：______
- 调参 APP 里别人分享的配置：______

【这些参考曲线对 AI 很有价值，因为：】
- 数学预设可能不是 100% 精确，参考曲线能补全缺失的信息
- 看别人调好的曲线可以了解"业内共识的合理范围"
- AI 可以综合多个数据源得出更接近"通用最佳"的方案

## 七、我希望你做什么

1. **综合分析报告里的数据 + 我的体感痛点 + 参考曲线**，告诉我曲线哪段需要调整
2. **严格按照我的曲线点数限制**给出修改方案（如果我只有 4 个点，就别给 8 个点的方案）
3. **根据我的曲线编辑方式输出**：
   - 如果我选了方式 A：输出完整 JSON
   - 如果我选了方式 B：列出每个节点的 X、Y 值（精确到小数点后 1 位），方便我手动输入
4. **如果我提供了反曲线数学建议，把它当作参考而不是绝对答案**——数学上的反函数不一定是体感最佳
5. 解释为什么这样改，以及预期会改善什么

## 重要原则

- 不要为了改而改，如果数据显示某段已经很好就不要动
- 体感优先于数据，数据有噪声，体感是真实的
- 一次只改 2-3 个节点，避免破坏整体平衡
- 改完后告诉我应该测试什么场景来验证
- 如果我的曲线点数较少（2-4 个），重点放在节点的 X 位置和 Y 高度，因为可调空间有限
- **关于 RC（动感）**：
  - 不同手柄 RC 数值范围不一样（±10、±100、±500 都有），不要假设我的 RC 范围
  - 看我提供的"百分比"来理解强度（70% = 强动感，30% = 轻度动感）
  - 如果我的手柄没有 RC 功能（百分比是 0%），别给超激进的曲线，因为没有硬件 RC 兜底
  - 如果我的 RC 是强动感（>60%），低段曲线可以稍微保守一点，避免硬件+曲线双重放大导致抖动
"""
# ===========================================================


class StickRecorder:
    """后台录制线程（使用 controller_backend 抽象层）"""

    def __init__(self, output_path, metadata, fire_button, ads_button,
                 controller_info, controller_manager,
                 on_update, on_done):
        self.output_path = output_path
        self.metadata = metadata
        self.fire_button = fire_button       # 逻辑代码（如 RIGHT_SHOULDER）
        self.ads_button = ads_button
        self.controller_info = controller_info  # ControllerInfo
        self.controller_manager = controller_manager  # ControllerManager
        self.on_update = on_update
        self.on_done = on_done
        self._stop_flag = False
        self._thread = None

    def start(self):
        self._stop_flag = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag = True

    def _run(self):
        if cb is None:
            self.on_done(False,
                "controller_backend.py 模块未找到，请确认它和本程序在同一目录")
            return

        if self.controller_info is None:
            self.on_done(False, "未选择手柄，请先在控制器选择区选定一个手柄")
            return

        try:
            csv_file = open(self.output_path, "w", newline="", encoding="utf-8")
        except Exception as e:
            self.on_done(False, f"无法创建文件: {e}")
            return

        # 写元数据（包含控制器信息）
        for k, v in self.metadata.items():
            csv_file.write(f"# meta: {k}={v}\n")
        csv_file.write(f"# meta: fire_button={self.fire_button}\n")
        csv_file.write(f"# meta: ads_button={self.ads_button}\n")
        csv_file.write(f"# meta: controller_name={self.controller_info.name}\n")
        csv_file.write(f"# meta: controller_protocol={self.controller_info.protocol}\n")
        csv_file.write(f"# meta: controller_layout={self.controller_info.layout}\n")
        if self.controller_info.guid:
            csv_file.write(f"# meta: controller_guid={self.controller_info.guid}\n")
        csv_file.write(f"# meta: started={datetime.now().isoformat()}\n")

        # 按键列：用统一的逻辑代码作为列名（小写）
        btn_columns = [f"btn_{b.lower()}" for b in cb.LOGICAL_BUTTONS]
        writer = csv.writer(csv_file)
        writer.writerow([
            "timestamp_ns", "elapsed_s",
            "lx", "ly", "rx", "ry",
            "lt", "rt",
        ] + btn_columns + ["fire", "ads"])

        start_ns = time.time_ns()
        sample_count = 0
        fire_count = 0
        ads_count = 0
        sample_interval_ns = int(1e9 / TARGET_RATE_HZ)
        next_sample_ns = start_ns
        last_update_ns = start_ns

        try:
            while not self._stop_flag:
                now_ns = time.time_ns()

                # 修复：用 sleep 让出 CPU（不再忙等待 spin loop）
                wait_ns = next_sample_ns - now_ns
                if wait_ns > 0:
                    # 1ms 以上的等待用 sleep（让出 CPU）
                    # 1ms 以下的剩余时间忽略，由调度器处理
                    if wait_ns > 1_000_000:
                        time.sleep(wait_ns / 1e9)
                    now_ns = time.time_ns()

                try:
                    state = self.controller_manager.read_state(self.controller_info)
                except Exception as e:
                    print(f"[警告] 读取手柄失败: {e}")
                    break

                # 按键状态
                buttons_dict = state.buttons
                fire = bool(buttons_dict.get(self.fire_button, False))
                ads = bool(buttons_dict.get(self.ads_button, False))

                elapsed = (now_ns - start_ns) / 1e9

                row = [
                    now_ns, f"{elapsed:.6f}",
                    f"{state.lx:.5f}", f"{state.ly:.5f}",
                    f"{state.rx:.5f}", f"{state.ry:.5f}",
                    f"{state.lt:.4f}", f"{state.rt:.4f}",
                ]
                for b in cb.LOGICAL_BUTTONS:
                    row.append(int(bool(buttons_dict.get(b, False))))
                row.extend([int(fire), int(ads)])
                writer.writerow(row)

                sample_count += 1
                if fire:
                    fire_count += 1
                if ads:
                    ads_count += 1

                # GUI 更新降频到 100ms 一次（避免主线程被频繁打断）
                if (now_ns - last_update_ns) / 1e9 > 0.1:
                    rate = sample_count / max(elapsed, 1e-6)
                    self.on_update({
                        "elapsed": elapsed,
                        "samples": sample_count,
                        "rate": rate,
                        "fire_pct": 100 * fire_count / max(sample_count, 1),
                        "ads_pct": 100 * ads_count / max(sample_count, 1),
                        "lx": state.lx, "ly": state.ly,
                        "rx": state.rx, "ry": state.ry,
                        "lt": state.lt, "rt": state.rt,
                        "fire": fire, "ads": ads,
                    })
                    last_update_ns = now_ns

                next_sample_ns += sample_interval_ns
                # 防止时间漂移过大（比如系统卡顿后），重新对齐
                if next_sample_ns < now_ns:
                    next_sample_ns = now_ns + sample_interval_ns

        finally:
            csv_file.close()
            elapsed_total = (time.time_ns() - start_ns) / 1e9
            summary = {
                "duration": elapsed_total,
                "samples": sample_count,
                "rate": sample_count / max(elapsed_total, 1e-6),
                "fire_count": fire_count,
                "ads_count": ads_count,
                "output": str(self.output_path),
            }
            self.on_done(True, summary)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"摇杆射击行为分析工具 {APP_VERSION}")
        self.geometry("980x900")
        self.recorder = None
        self.csv_path_var = tk.StringVar()
        self.last_report_content = ""

        # 安装全局异常钩子（捕获所有未处理异常，弹出反馈窗口）
        if error_reporter is not None:
            try:
                error_reporter.install_exception_hook(self)
            except Exception as e:
                print(f"[警告] 异常钩子安装失败: {e}")

        # 控制器管理器（核心新增）
        if cb is None:
            messagebox.showerror(
                "缺少模块",
                "找不到 controller_backend.py 模块，请确认它和本程序在同一目录")
            self.controller_mgr = None
        else:
            self.controller_mgr = cb.ControllerManager()
            # 启动时检查驱动可用性
            if not self.controller_mgr.has_pygame() and not self.controller_mgr.has_xinput():
                messagebox.showerror(
                    "缺少驱动库",
                    "未检测到 pygame 或 XInput-Python 库。\n"
                    "请运行：pip install pygame XInput-Python")

        # 槽位选择变量（4 个槽位）
        self.slot_var = tk.IntVar(value=0)
        self.slot_radio_buttons = []  # GUI Radiobutton 引用，用于动态更新

        self._build_ui()

        # 启动后立即扫描一次手柄
        if self.controller_mgr is not None:
            self.after(100, self._scan_controllers)

    def _build_ui(self):
        # ========== 顶部免费标语横幅 ==========
        banner = tk.Frame(self, bg="#FFF3CD", relief="solid", bd=1)
        banner.pack(fill="x", padx=10, pady=(10, 0))

        banner_inner = tk.Frame(banner, bg="#FFF3CD")
        banner_inner.pack(fill="x", padx=10, pady=6)

        tk.Label(banner_inner,
                 text="🎁 本软件完全免费",
                 bg="#FFF3CD", fg="#856404",
                 font=("Microsoft YaHei", 10, "bold")).pack(side="left")

        tk.Label(banner_inner,
                 text="  作者：B站 / 抖音  josef_0464",
                 bg="#FFF3CD", fg="#856404",
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(20, 0))

        tk.Label(banner_inner,
                 text="  反馈交流 QQ 群: 611624374",
                 bg="#FFF3CD", fg="#0078D4",
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=(15, 0))

        tk.Label(banner_inner,
                 text="⚠ 如果你是付费获得的，说明你被骗了！",
                 bg="#FFF3CD", fg="#D9534F",
                 font=("Microsoft YaHei", 9, "bold")).pack(side="right")

        # ========== Notebook 标签页 ==========
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.notebook = notebook

        tab_record = ttk.Frame(notebook)
        notebook.add(tab_record, text="① 录制摇杆数据")
        self._build_record_tab(tab_record)

        tab_analyze = ttk.Frame(notebook)
        notebook.add(tab_analyze, text="② 分析数据")
        self._build_analyze_tab(tab_analyze)

        tab_ai = ttk.Frame(notebook)
        notebook.add(tab_ai, text="③ 生成 AI 调参提示词")
        self._build_ai_tab(tab_ai)

        tab_inverse = ttk.Frame(notebook)
        notebook.add(tab_inverse, text="④ 参考曲线收集")
        self._build_inverse_tab(tab_inverse)

    # ========== 标签 1：录制 ==========
    def _build_record_tab(self, parent):
        # ====== 控制器选择区 ======
        ctrl_frame = ttk.LabelFrame(
            parent, text="① 选择控制器（最多 4 个槽位）", padding=10)
        ctrl_frame.pack(fill="x", padx=10, pady=(10, 5))

        # 4 个槽位（动态填充）
        self.slot_widgets = []
        for slot_idx in range(4):
            row_frame = ttk.Frame(ctrl_frame)
            row_frame.pack(fill="x", pady=1)

            rb = ttk.Radiobutton(row_frame, text=f"槽位 {slot_idx + 1}:",
                                 variable=self.slot_var, value=slot_idx,
                                 command=self._on_slot_changed,
                                 width=10)
            rb.pack(side="left")

            label = tk.Label(row_frame, text="[空]",
                             font=("", 9), foreground="#999",
                             anchor="w")
            label.pack(side="left", fill="x", expand=True, padx=5)

            self.slot_widgets.append({"radio": rb, "label": label})

        # 扫描按钮
        scan_frame = ttk.Frame(ctrl_frame)
        scan_frame.pack(fill="x", pady=(8, 2))
        ttk.Button(scan_frame, text="🔄 刷新设备列表",
                   command=self._scan_controllers).pack(side="left")

        self.scan_status_label = ttk.Label(scan_frame, text="",
                                            foreground="#666",
                                            font=("", 8))
        self.scan_status_label.pack(side="left", padx=10)

        # 提示信息
        ttk.Label(ctrl_frame,
                  text="提示：插入新手柄后请点「刷新设备列表」。"
                       "如果同一手柄被同时识别为 PS 和 XInput，会优先用 PS 协议。",
                  foreground="#666", font=("", 8),
                  wraplength=900).pack(anchor="w", pady=(4, 0))

        # ====== 键位映射设置 ======
        key_frame = ttk.LabelFrame(parent, text="② 键位映射设置", padding=10)
        key_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(key_frame, text="开火键 (FIRE):", width=14).grid(
            row=0, column=0, sticky="e", padx=5, pady=5)
        self.fire_button_var = tk.StringVar(value=DEFAULT_FIRE_BUTTON)
        fire_combo = ttk.Combobox(key_frame, state="readonly", width=30)
        fire_combo.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        fire_combo.bind("<<ComboboxSelected>>",
                        lambda e: self._on_button_change(fire_combo, "fire"))
        self.fire_combo = fire_combo

        ttk.Label(key_frame, text="开镜键 (ADS):", width=14).grid(
            row=1, column=0, sticky="e", padx=5, pady=5)
        self.ads_button_var = tk.StringVar(value=DEFAULT_ADS_BUTTON)
        ads_combo = ttk.Combobox(key_frame, state="readonly", width=30)
        ads_combo.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        ads_combo.bind("<<ComboboxSelected>>",
                       lambda e: self._on_button_change(ads_combo, "ads"))
        self.ads_combo = ads_combo

        # 按键提示文本（动态更新）
        self.key_hint_label = ttk.Label(
            key_frame,
            text="按键标签会根据上方选中的控制器自动调整。",
            foreground="gray", font=("", 8))
        self.key_hint_label.grid(
            row=2, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # 初次填充按键下拉（先按默认 XBOX 布局，扫描后会更新）
        self._refresh_button_combos(cb.LAYOUT_XBOX if cb else "xbox")

        # 元数据输入区
        meta_frame = ttk.LabelFrame(
            parent, text="本次记录元数据（可选，但建议填写）", padding=10)
        meta_frame.pack(fill="x", padx=10, pady=5)

        self.meta_vars = {}

        # ===== RC 强度等级选择（关键改动）=====
        # 不同手柄 RC 数值范围差异大（±10 / ±100 / ±500 都有），
        # 让用户选"动感强度等级"做归一化
        rc_intensity_options = [
            ("无 RC 功能 / RC=0（手柄不支持 RC）", "none"),
            ("轻度动感（≈ 总范围的 0-30%）", "light"),
            ("中度动感（≈ 总范围的 30-60%）", "medium"),
            ("强动感（≈ 总范围的 60-90%）", "strong"),
            ("极限动感（≈ 总范围的 90-100% / 拉满）", "extreme"),
            ("防抖方向（正值，抑制动作）", "antishake"),
        ]

        # 腰射 RC
        ttk.Label(meta_frame, text="腰射 RC 数值:", width=14).grid(
            row=0, column=0, sticky="e", padx=5, pady=2)
        v_hip_value = tk.StringVar(value="0")
        self.meta_vars["rc_hipfire"] = v_hip_value
        ttk.Entry(meta_frame, textvariable=v_hip_value, width=10).grid(
            row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(meta_frame, text="腰射 动感强度:", width=14).grid(
            row=0, column=2, sticky="e", padx=5, pady=2)
        v_hip_int = tk.StringVar(value=rc_intensity_options[0][0])
        self.meta_vars["rc_hipfire_intensity"] = v_hip_int
        ttk.Combobox(meta_frame, textvariable=v_hip_int,
                     values=[o[0] for o in rc_intensity_options],
                     state="readonly", width=32).grid(
            row=0, column=3, sticky="w", padx=5, pady=2)

        # 开镜 RC
        ttk.Label(meta_frame, text="开镜 RC 数值:", width=14).grid(
            row=1, column=0, sticky="e", padx=5, pady=2)
        v_ads_value = tk.StringVar(value="0")
        self.meta_vars["rc_ads"] = v_ads_value
        ttk.Entry(meta_frame, textvariable=v_ads_value, width=10).grid(
            row=1, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(meta_frame, text="开镜 动感强度:", width=14).grid(
            row=1, column=2, sticky="e", padx=5, pady=2)
        v_ads_int = tk.StringVar(value=rc_intensity_options[0][0])
        self.meta_vars["rc_ads_intensity"] = v_ads_int
        ttk.Combobox(meta_frame, textvariable=v_ads_int,
                     values=[o[0] for o in rc_intensity_options],
                     state="readonly", width=32).grid(
            row=1, column=3, sticky="w", padx=5, pady=2)

        # RC 提示信息（多行说明）
        rc_hint = (
            "RC 说明：不同手柄的 RC 数值范围差异很大（常见 ±10、±100、±500 都有）。\n"
            "● 数值栏：填你 APP 里看到的实际数字（如 -3、-50、-500），"
            "用于记录配置；不知道就填 0。\n"
            "● 动感强度栏：才是真正用于分析的关键！按你 APP 里 RC "
            "在【可调范围内的位置】选择。\n"
            "  例：APP 的 RC 范围是 -10~+10，你设了 -7，那就是 70%，选「强动感」。\n"
            "  例：APP 的 RC 范围是 -500~+500，你设了 -150，那就是 30%，选「轻度动感」。\n"
            "● 手柄完全没有 RC 功能 → 选「无 RC 功能」，数值填 0。"
        )
        ttk.Label(meta_frame, text=rc_hint, foreground="#666",
                  font=("", 8), justify="left").grid(
            row=2, column=0, columnspan=4, sticky="w", padx=5, pady=4)

        # 其他元数据字段
        other_rows = [
            ("curve", "曲线版本/名称:", "",
             "便于后续区分多次记录，如 v1, v2, 试用版 等"),
            ("weapons", "主要使用武器:", "",
             "如 R99, R301, 自瞄枪 等"),
            ("scene", "测试场景:", "训练场",
             "训练场 / 比赛 / 休闲对战 等"),
        ]
        for i, (key, label, default, hint) in enumerate(other_rows, start=3):
            ttk.Label(meta_frame, text=label, width=14).grid(
                row=i, column=0, sticky="e", padx=5, pady=2)
            var = tk.StringVar(value=default)
            self.meta_vars[key] = var
            ttk.Entry(meta_frame, textvariable=var, width=20).grid(
                row=i, column=1, sticky="w", padx=5, pady=2)
            ttk.Label(meta_frame, text=hint, foreground="gray",
                      font=("", 8)).grid(
                row=i, column=2, columnspan=2, sticky="w", padx=5, pady=2)

        # 输出位置
        out_frame = ttk.Frame(parent)
        out_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(out_frame, text="输出目录:").pack(side="left")
        self.out_dir_var = tk.StringVar(value=str(Path.cwd()))
        ttk.Entry(out_frame, textvariable=self.out_dir_var, width=50).pack(
            side="left", padx=5)
        ttk.Button(out_frame, text="选择...",
                   command=self._choose_out_dir).pack(side="left")

        # 按钮区
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(pady=10)
        self.start_btn = ttk.Button(btn_frame, text="● 开始录制",
                                    command=self._start_record)
        self.start_btn.pack(side="left", padx=5)
        self.stop_btn = ttk.Button(btn_frame, text="■ 停止录制",
                                   command=self._stop_record, state="disabled")
        self.stop_btn.pack(side="left", padx=5)

        # 状态显示区
        status_frame = ttk.LabelFrame(parent, text="实时状态", padding=10)
        status_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.status_text = scrolledtext.ScrolledText(
            status_frame, height=8, font=("Consolas", 9))
        self.status_text.pack(fill="both", expand=True)
        self._log("等待开始录制...\n\n"
                  "操作步骤：\n"
                  "1. 上方选择你的开火键和开镜键（必须选对！）\n"
                  "2. 填写元数据（RC 值不知道就填 0）\n"
                  "3. 点击 ● 开始录制\n"
                  "4. 正常打游戏，观察实时状态确认 FIRE/ADS 标记会亮\n"
                  "5. 打完后点 ■ 停止录制")

    def _on_button_change(self, combo, btn_type):
        """根据下拉框当前选项更新按键变量"""
        idx = combo.current()
        if idx >= 0 and idx < len(self._current_button_options):
            display_name, logical_code = self._current_button_options[idx]
            if btn_type == "fire":
                self.fire_button_var.set(logical_code)
            else:
                self.ads_button_var.set(logical_code)

    # ========== 控制器槽位管理 ==========
    def _scan_controllers(self):
        """重新扫描手柄并刷新槽位显示"""
        if self.controller_mgr is None:
            return
        msg = self.controller_mgr.scan_and_assign()
        self.scan_status_label.configure(text=msg)
        self._refresh_slot_display()
        self._refresh_button_combos_for_current_slot()

    def _refresh_slot_display(self):
        """根据当前槽位状态刷新 GUI"""
        if self.controller_mgr is None:
            return
        for i, widget in enumerate(self.slot_widgets):
            slot = self.controller_mgr.slots[i]
            if slot is None:
                widget["label"].configure(text="[空]", foreground="#999")
                widget["radio"].configure(state="disabled")
            else:
                widget["label"].configure(
                    text=slot.display_string(),
                    foreground="#222")
                widget["radio"].configure(state="normal")

        # 同步 slot_var 和 ControllerManager 的当前槽位
        cur = self.controller_mgr.get_current_slot()
        if cur is not None:
            self.slot_var.set(cur)

    def _on_slot_changed(self):
        """用户切换槽位时调用"""
        if self.controller_mgr is None:
            return
        new_slot = self.slot_var.get()
        if self.controller_mgr.slots[new_slot] is not None:
            self.controller_mgr.set_current_slot(new_slot)
            self._refresh_button_combos_for_current_slot()

    def _refresh_button_combos_for_current_slot(self):
        """根据当前选中槽位的手柄布局，刷新键位下拉框"""
        if self.controller_mgr is None or cb is None:
            return
        ctrl = self.controller_mgr.get_current_controller()
        if ctrl is None:
            self._refresh_button_combos(cb.LAYOUT_XBOX)
        else:
            self._refresh_button_combos(ctrl.layout)

    def _refresh_button_combos(self, layout: str):
        """根据按键布局，重新填充开火键和开镜键的下拉框选项"""
        if cb is None:
            return
        options = cb.get_button_options_for_layout(layout)
        self._current_button_options = options  # 保存供 _on_button_change 用

        display_labels = [opt[0] for opt in options]
        logical_codes = [opt[1] for opt in options]

        # 更新开火键下拉
        old_fire = self.fire_button_var.get()
        self.fire_combo["values"] = display_labels
        if old_fire in logical_codes:
            self.fire_combo.current(logical_codes.index(old_fire))
        elif DEFAULT_FIRE_BUTTON in logical_codes:
            self.fire_combo.current(logical_codes.index(DEFAULT_FIRE_BUTTON))
            self.fire_button_var.set(DEFAULT_FIRE_BUTTON)
        elif logical_codes:
            self.fire_combo.current(0)
            self.fire_button_var.set(logical_codes[0])

        # 更新开镜键下拉
        old_ads = self.ads_button_var.get()
        self.ads_combo["values"] = display_labels
        if old_ads in logical_codes:
            self.ads_combo.current(logical_codes.index(old_ads))
        elif DEFAULT_ADS_BUTTON in logical_codes:
            self.ads_combo.current(logical_codes.index(DEFAULT_ADS_BUTTON))
            self.ads_button_var.set(DEFAULT_ADS_BUTTON)
        elif logical_codes:
            self.ads_combo.current(0)
            self.ads_button_var.set(logical_codes[0])

        # 更新提示文字
        layout_label_map = {
            cb.LAYOUT_XBOX: "XBOX 风格",
            cb.LAYOUT_PS: "PlayStation 风格",
            cb.LAYOUT_PS_EDGE: "DualSense Edge 风格（含背键 FN1/FN2/RB1/RB2）",
            cb.LAYOUT_SWITCH: "Switch 风格",
            cb.LAYOUT_GENERIC: "通用 / 未识别",
        }
        layout_name = layout_label_map.get(layout, layout)
        self.key_hint_label.configure(
            text=f"当前布局: {layout_name}。按键标签会根据控制器协议自动适配。"
                 "选错键位会导致 FIRE/ADS 标记不亮。")

    # ========== 标签 2：分析 ==========
    def _build_analyze_tab(self, parent):
        file_frame = ttk.Frame(parent)
        file_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(file_frame, text="CSV 文件:").pack(side="left")
        ttk.Entry(file_frame, textvariable=self.csv_path_var, width=50).pack(
            side="left", padx=5, fill="x", expand=True)
        ttk.Button(file_frame, text="选择...",
                   command=self._choose_csv).pack(side="left")

        param_frame = ttk.LabelFrame(parent, text="分析参数（一般保持默认即可）", padding=10)
        param_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(param_frame, text="最大事件数:").grid(row=0, column=0, sticky="e")
        self.max_events_var = tk.IntVar(value=50)
        ttk.Spinbox(param_frame, from_=5, to=200, increment=5,
                    textvariable=self.max_events_var, width=10).grid(
            row=0, column=1, sticky="w", padx=5)

        ttk.Label(param_frame, text="最短爆发(秒):").grid(
            row=0, column=2, sticky="e", padx=10)
        self.min_dur_var = tk.DoubleVar(value=0.05)
        ttk.Spinbox(param_frame, from_=0.0, to=2.0, increment=0.05,
                    textvariable=self.min_dur_var, width=10).grid(
            row=0, column=3, sticky="w", padx=5)

        # 参数说明
        param_hint = (
            "● 最大事件数：最多分析多少次开火。事件太多会生成很多张图，"
            "默认 50 够用，不用改。\n"
            "● 最短爆发(秒)：开火持续多久才算一次有效射击，"
            "用于过滤误触（比如手抖按了一下就松开）。\n"
            "  默认 0.05 秒适合大多数情况，不用改。"
            "如果你专门用栓狙单点射，可以调到 0.0 让单发也被分析。"
        )
        ttk.Label(param_frame, text=param_hint, foreground="#666",
                  font=("", 8), justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=5, pady=(8, 2))

        self.analyze_btn = ttk.Button(parent, text="▶ 开始分析",
                                      command=self._start_analyze)
        self.analyze_btn.pack(pady=10)

        result_frame = ttk.LabelFrame(parent, text="分析结果", padding=10)
        result_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.result_text = scrolledtext.ScrolledText(
            result_frame, height=15, font=("Consolas", 9))
        self.result_text.pack(fill="both", expand=True)

        bottom_frame = ttk.Frame(parent)
        bottom_frame.pack(pady=5)
        self.open_dir_btn = ttk.Button(bottom_frame, text="📁 打开输出目录",
                                       command=self._open_output_dir,
                                       state="disabled")
        self.open_dir_btn.pack(side="left", padx=5)
        self.go_to_ai_btn = ttk.Button(
            bottom_frame, text="→ 下一步：生成 AI 提示词",
            command=lambda: self.notebook.select(2),
            state="disabled")
        self.go_to_ai_btn.pack(side="left", padx=5)

    # ========== 标签 3：AI 提示词 ==========
    def _build_ai_tab(self, parent):
        intro_frame = ttk.LabelFrame(parent, text="使用说明", padding=10)
        intro_frame.pack(fill="x", padx=10, pady=10)

        intro_text = (
            "完成分析后，本工具会自动把数据报告嵌入到提示词模板中。\n\n"
            "你需要在下方文本框中填写三处内容（已用【】标记）：\n"
            "  1. 你的手柄型号 + 曲线编辑方式 + 可调节点数\n"
            "     ⚠ 不同手柄支持的曲线点数不一样（2/4/6/8 点常见），\n"
            "       不能直接照搬别人的 JSON，否则会因为点数不对导入失败。\n"
            "     ⚠ 部分手柄不支持 JSON 导入，只能在 APP 里手动拖动节点，\n"
            "       这种情况要让 AI 给出每个节点的具体 X、Y 数值。\n\n"
            "  2. 你当前的曲线坐标（按你手柄实际的点数填）\n"
            "  3. 你的体感痛点（越具体越好）\n\n"
            "填完后点 [📋 复制全部到剪贴板]，粘贴给 AI（推荐 Claude / ChatGPT），\n"
            "AI 会综合数据 + 你的痛点 + 你的手柄限制，给出针对性的调整方案。"
        )
        ttk.Label(intro_frame, text=intro_text,
                  justify="left", foreground="#333").pack(anchor="w")

        # 提示词编辑区
        prompt_frame = ttk.LabelFrame(parent, text="提示词内容（可编辑）", padding=10)
        prompt_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.prompt_text = scrolledtext.ScrolledText(
            prompt_frame, font=("Consolas", 9), wrap="word")
        self.prompt_text.pack(fill="both", expand=True)

        self._refresh_prompt_template()

        # 按钮区
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="🔄 刷新（用最新分析报告）",
                   command=self._refresh_prompt_template).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="📋 复制全部到剪贴板",
                   command=self._copy_prompt).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="💾 保存为文件",
                   command=self._save_prompt).pack(side="left", padx=5)

    def _refresh_prompt_template(self):
        report = self.last_report_content or "【请先在 ② 分析数据 标签页完成一次分析，再回来这里】"
        content = AI_PROMPT_TEMPLATE.replace("{REPORT_CONTENT}", report)
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", content)

    def _copy_prompt(self):
        content = self.prompt_text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)
        self.update()
        messagebox.showinfo("成功", "提示词已复制到剪贴板！\n粘贴给 AI 即可。")

    def _save_prompt(self):
        content = self.prompt_text.get("1.0", "end-1c")
        f = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
            initialfile=f"ai_prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if f:
            try:
                Path(f).write_text(content, encoding="utf-8")
                messagebox.showinfo("成功", f"已保存到 {f}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")

    # ========== 标签 4：参考曲线收集指南 ==========
    def _build_inverse_tab(self, parent):
        # 上半：使用说明
        intro_frame = ttk.LabelFrame(parent, text="使用说明", padding=10)
        intro_frame.pack(fill="x", padx=10, pady=10)

        intro_text = (
            "本标签页提供「参考曲线收集」的工具和指南。\n"
            "\n"
            "💡 核心理念：\n"
            "  • 数学反函数不一定是体感最佳，比纯算法更可靠的是「别人调教过、被广泛验证的曲线」\n"
            "  • 把多份参考曲线一起交给 AI，让 AI 综合判断「业内共识 + 你的数据 + 你的痛点」\n"
            "  • 你的角色：收集 + 整理 + 描述体感；AI 的角色：综合分析 + 微调建议\n"
            "\n"
            "🔒 工具承诺：本工具不会向游戏发送任何输入、不读取游戏画面、不操作你的手柄。"
            "所有调整最终由你自己手动完成。"
        )
        ttk.Label(intro_frame, text=intro_text, justify="left",
                  foreground="#333", wraplength=900).pack(anchor="w")

        # 中部：左右分栏
        middle_frame = ttk.Frame(parent)
        middle_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # ====== 左侧：去哪找参考曲线（指南）======
        left = ttk.LabelFrame(middle_frame, text="📚 去哪找参考曲线", padding=10)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))

        guide_text = (
            "🎯 推荐渠道：\n"
            "\n"
            "1️⃣ 国内社区\n"
            "   • B站搜索：「Apex 曲线 调教」「Apex 手柄 配置」\n"
            "                「FPS 反曲线」「手柄 灵敏度 曲线」\n"
            "   • 抖音搜索：同上关键词\n"
            "   • 贴吧：APEX英雄吧、手柄吧、FPS游戏吧\n"
            "\n"
            "2️⃣ 国外社区\n"
            "   • Reddit：r/apexlegends、r/CompetitiveApex\n"
            "   • Discord：相关游戏的 controller-tips 频道\n"
            "   • YouTube：搜「Apex aim training」「stick curve」\n"
            "\n"
            "3️⃣ 调参 APP / 软件\n"
            "   • 北通宙斯系列、雷蛇飓兽 APP\n"
            "   • 飞智、莱仕达、八位堂的官方 APP\n"
            "   • 部分 APP 内置「社区曲线」分享功能\n"
            "\n"
            "4️⃣ 游戏内截图\n"
            "   • 进入游戏「灵敏度/手柄」设置\n"
            "   • 截图响应曲线图表\n"
            "   • 把截图丢给 AI（Claude / ChatGPT），让它\n"
            "     识别曲线节点的 (X, Y) 数值\n"
            "\n"
            "🌟 重点：找 3-5 条不同来源的曲线，对比共性，\n"
            "         共性部分往往就是业内共识的合理范围。"
        )
        ttk.Label(left, text=guide_text, justify="left",
                  font=("", 9), foreground="#333").pack(anchor="w", pady=(0, 8))

        # ====== 右侧：参考曲线收集区 ======
        right = ttk.LabelFrame(middle_frame,
            text="📝 把找到的参考曲线粘贴到这里", padding=10)
        right.pack(side="right", fill="both", expand=True, padx=(5, 0))

        right_intro = (
            "格式建议（可自由发挥，不用严格遵守）：\n"
            "  来源：（B站某 UP / 朋友 / 截图识别 等）\n"
            "  曲线：[0,0, 6,5.5, 16,19.5, ...] 或描述\n"
            "  评价：（这条曲线的体感特点）"
        )
        ttk.Label(right, text=right_intro, justify="left",
                  foreground="#666", font=("", 8)).pack(anchor="w", pady=(0, 4))

        self.refs_text = scrolledtext.ScrolledText(
            right, font=("Consolas", 9), height=15, wrap="word")
        self.refs_text.pack(fill="both", expand=True)

        # 默认填充模板
        default_refs = (
            "=== 参考曲线 1 ===\n"
            "来源：（在这里填来源）\n"
            "曲线：（节点数据或描述）\n"
            "评价：（体感特点）\n"
            "\n"
            "=== 参考曲线 2 ===\n"
            "来源：\n"
            "曲线：\n"
            "评价：\n"
            "\n"
            "=== 参考曲线 3 ===\n"
            "来源：\n"
            "曲线：\n"
            "评价：\n"
        )
        self.refs_text.insert("1.0", default_refs)

        # 按钮区
        btn_frame = ttk.Frame(right)
        btn_frame.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_frame, text="🗑 清空",
                   command=self._clear_refs).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="💾 保存到文件",
                   command=self._save_refs).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="➕ 注入到 AI 提示词",
                   command=self._inject_refs_to_prompt).pack(side="left", padx=2)

        # 底部小贴士
        tip_frame = ttk.Frame(parent)
        tip_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(tip_frame,
            text="💡 小贴士：参考曲线收集得越全，AI 给出的建议越精准。"
                 "建议至少收集 3 条不同来源的曲线再做对比。",
            foreground="#0078D4", font=("", 9, "italic")).pack(anchor="w")

    def _clear_refs(self):
        if messagebox.askyesno("确认", "确定要清空所有内容吗？"):
            self.refs_text.delete("1.0", "end")

    def _save_refs(self):
        content = self.refs_text.get("1.0", "end-1c").strip()
        if not content:
            messagebox.showwarning("提示", "内容为空，没什么可保存的")
            return
        f = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
            initialfile=f"reference_curves_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if f:
            try:
                Path(f).write_text(content, encoding="utf-8")
                messagebox.showinfo("成功", f"已保存到 {f}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")

    def _inject_refs_to_prompt(self):
        """把参考曲线追加到 AI 提示词中"""
        content = self.refs_text.get("1.0", "end-1c").strip()
        if not content:
            messagebox.showwarning("提示", "请先在右侧填写参考曲线")
            return

        injection = (
            "\n\n" + "=" * 50 + "\n"
            "【我收集的参考曲线】\n"
            + "=" * 50 + "\n"
            + content + "\n"
        )

        current = self.prompt_text.get("1.0", "end-1c")
        marker = "【我收集的参考曲线】"
        if marker in current:
            # 已有，替换
            start = current.find("=" * 50 + "\n" + marker)
            if start == -1:
                start = current.find(marker)
            # 找下一个章节标志
            end = current.find("\n## ", start)
            if end == -1:
                end = current.find("\n请", start)
            if end == -1:
                new_text = current[:start].rstrip() + injection
            else:
                new_text = current[:start].rstrip() + injection + current[end:]
        else:
            new_text = current + injection

        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", new_text)
        self.notebook.select(2)
        messagebox.showinfo("成功",
            "参考曲线已注入到 AI 提示词中！\n"
            "已自动跳转到「③ 生成 AI 调参提示词」标签页。")

    # ========== 通用辅助 ==========
    def _log(self, msg):
        self.status_text.insert("end", msg + "\n")
        self.status_text.see("end")

    def _result_log(self, msg):
        self.result_text.insert("end", msg + "\n")
        self.result_text.see("end")

    def _choose_out_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_dir_var.get())
        if d:
            self.out_dir_var.set(d)

    def _choose_csv(self):
        f = filedialog.askopenfilename(
            initialdir=self.out_dir_var.get(),
            filetypes=[("CSV 文件", "*.csv")])
        if f:
            self.csv_path_var.set(f)

    # ========== 录制控制 ==========
    def _start_record(self):
        out_dir = Path(self.out_dir_var.get())
        if not out_dir.exists():
            messagebox.showerror("错误", f"输出目录不存在: {out_dir}")
            return

        # 检查是否选择了控制器
        if self.controller_mgr is None:
            messagebox.showerror("错误", "控制器管理器未初始化")
            return

        ctrl = self.controller_mgr.get_current_controller()
        if ctrl is None:
            messagebox.showerror(
                "错误",
                "未选择控制器！请先在「① 选择控制器」中选定一个手柄。\n"
                "如果列表显示全部为「空」，请先点「🔄 刷新设备列表」。")
            return

        fire_btn = self.fire_button_var.get()
        ads_btn = self.ads_button_var.get()
        if fire_btn == ads_btn:
            messagebox.showerror("错误", "开火键和开镜键不能相同！")
            return

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = out_dir / f"stick_log_{timestamp_str}.csv"

        # 中文动感等级 → 简短 code 映射
        intensity_label_to_code = {
            "无 RC 功能 / RC=0（手柄不支持 RC）": "none",
            "轻度动感（≈ 总范围的 0-30%）": "light",
            "中度动感（≈ 总范围的 30-60%）": "medium",
            "强动感（≈ 总范围的 60-90%）": "strong",
            "极限动感（≈ 总范围的 90-100% / 拉满）": "extreme",
            "防抖方向（正值,抑制动作）": "antishake",
            "防抖方向（正值，抑制动作）": "antishake",
        }

        metadata = {}
        for k, v in self.meta_vars.items():
            val = v.get().strip()
            if k.endswith("_intensity") and val in intensity_label_to_code:
                metadata[k] = intensity_label_to_code[val]
            else:
                metadata[k] = val if val else "unknown"

        self.recorder = StickRecorder(
            output_path, metadata, fire_btn, ads_btn,
            controller_info=ctrl,
            controller_manager=self.controller_mgr,
            on_update=lambda s: self.after(0, self._on_recorder_update, s),
            on_done=lambda ok, info: self.after(0, self._on_recorder_done, ok, info))
        self.recorder.start()

        self.start_btn["state"] = "disabled"
        self.stop_btn["state"] = "normal"
        self.fire_combo["state"] = "disabled"
        self.ads_combo["state"] = "disabled"
        # 录制时禁用槽位切换
        for w in self.slot_widgets:
            w["radio"].configure(state="disabled")

        self.status_text.delete(1.0, "end")
        self._log(f"开始录制 → {output_path.name}")
        self._log(f"控制器: {ctrl.display_string()}")
        # 显示用户友好的按键标签
        if cb is not None:
            fire_label = cb.get_button_display_name(ctrl.layout, fire_btn)
            ads_label = cb.get_button_display_name(ctrl.layout, ads_btn)
            self._log(f"键位: 开火={fire_label}, 开镜={ads_label}")
        else:
            self._log(f"键位: 开火={fire_btn}, 开镜={ads_btn}")
        self._log("-" * 60)


    def _stop_record(self):
        if self.recorder:
            self.recorder.stop()
            self._log("正在停止...")

    def _on_recorder_update(self, s):
        bar_fire = "🔴 FIRE" if s["fire"] else "      "
        bar_ads = "🟢 ADS " if s["ads"] else "      "
        prefix = "状态 ▶"
        cur = (f"{prefix} T={s['elapsed']:6.1f}s  采样率={s['rate']:.0f}Hz  "
               f"L=({s['lx']:+.2f},{s['ly']:+.2f}) "
               f"R=({s['rx']:+.2f},{s['ry']:+.2f}) "
               f"FIRE={s['fire_pct']:.1f}% ADS={s['ads_pct']:.1f}% "
               f"{bar_fire} {bar_ads}")

        content = self.status_text.get("1.0", "end-1c")
        rows = content.split("\n")
        replaced = False
        for i in range(len(rows) - 1, -1, -1):
            if rows[i].startswith(prefix):
                rows[i] = cur
                replaced = True
                break
        if not replaced:
            rows.append(cur)

        self.status_text.delete("1.0", "end")
        self.status_text.insert("1.0", "\n".join(rows))
        self.status_text.see("end")

    def _on_recorder_done(self, ok, info):
        self.start_btn["state"] = "normal"
        self.stop_btn["state"] = "disabled"
        self.fire_combo["state"] = "readonly"
        self.ads_combo["state"] = "readonly"
        # 恢复槽位选择
        self._refresh_slot_display()

        if not ok:
            self._log(f"\n[错误] {info}")
            # 录制失败弹错误反馈窗（区分常见可恢复错误和严重错误）
            recoverable_keywords = ["未检测到", "未选择", "无法创建", "目录"]
            if any(kw in str(info) for kw in recoverable_keywords):
                # 常见用户错误，普通提示即可
                messagebox.showerror("录制失败", str(info))
            elif error_reporter is not None:
                # 程序异常，弹反馈窗
                error_reporter.show_error_dialog(
                    self, "录制失败", str(info), None,
                    "录制过程中发生异常")
            else:
                messagebox.showerror("录制失败", str(info))
            return

        self._log("")
        self._log("-" * 60)
        self._log("✓ 录制完成")
        self._log(f"  时长: {info['duration']:.1f} 秒")
        self._log(f"  样本: {info['samples']} 帧")
        self._log(f"  采样率: {info['rate']:.0f} Hz")
        self._log(f"  开火帧: {info['fire_count']} "
                  f"({100*info['fire_count']/max(info['samples'],1):.1f}%)")
        self._log(f"  开镜帧: {info['ads_count']} "
                  f"({100*info['ads_count']/max(info['samples'],1):.1f}%)")
        self._log(f"  文件: {info['output']}")

        if info['fire_count'] == 0:
            messagebox.showwarning(
                "提示",
                f"没有检测到开火事件！\n"
                f"可能是开火键选错了（当前选: {self.fire_button_var.get()}）\n"
                f"请重新检查键位设置后再试。")
        else:
            self.csv_path_var.set(info['output'])
            if messagebox.askyesno("录制完成", "录制成功！\n是否切换到分析页面？"):
                self.notebook.select(1)

    # ========== 分析控制 ==========
    def _start_analyze(self):
        csv_path = self.csv_path_var.get()
        if not csv_path or not Path(csv_path).exists():
            messagebox.showerror("错误", "请先选择有效的 CSV 文件")
            return

        self.analyze_btn["state"] = "disabled"
        self.go_to_ai_btn["state"] = "disabled"
        self.result_text.delete(1.0, "end")
        self._result_log(f"开始分析 {Path(csv_path).name}...\n")

        threading.Thread(
            target=self._run_analyzer,
            args=(csv_path, self.max_events_var.get(), self.min_dur_var.get()),
            daemon=True).start()

    def _run_analyzer(self, csv_path, max_events, min_dur):
        try:
            analyzer = _import_analyzer()
            if analyzer is None:
                self.after(0, self._result_log,
                           "[错误] 找不到 analyzer.py，请确认它和本程序在同一目录")
                self.after(0, lambda: self.analyze_btn.configure(state="normal"))
                return

            csv_p = Path(csv_path)
            df, metadata = analyzer.load_csv(csv_p)
            thresholds = analyzer.get_stability_thresholds(metadata)

            if "fire" not in df.columns:
                self.after(0, self._result_log,
                           "[错误] CSV 缺少 fire 列，请用本工具重新录制")
                self.after(0, lambda: self.analyze_btn.configure(state="normal"))
                return

            bursts = analyzer.detect_fire_bursts(df, min_dur)
            self.after(0, self._result_log,
                       f"检测到 {len(bursts)} 次开火爆发")

            if not bursts:
                self.after(0, self._result_log,
                           "[警告] 没有检测到开火事件，请检查录制时按键设置")
                self.after(0, lambda: self.analyze_btn.configure(state="normal"))
                return

            if len(bursts) > max_events:
                self.after(0, self._result_log,
                           f"事件过多，仅分析最后 {max_events} 次")
                bursts = bursts[-max_events:]

            events = []
            base = csv_p.stem
            out_dir = csv_p.parent

            for i, (b_start, b_end) in enumerate(bursts, 1):
                m = analyzer.analyze_burst(df, b_start, b_end)
                if m is None:
                    continue
                cls = analyzer.classify_burst(m)
                events.append({"index": i, "metrics": m, "classification": cls})

                png_path = out_dir / f"{base}_event_{i:02d}.png"
                title = (f"开火 #{i} @ {b_start:.2f}s 持续{m['duration']:.2f}s | "
                         f"{'ADS' if m['is_ads'] else '腰射'} | {cls}")
                analyzer.plot_burst(m, png_path, title)

                self.after(0, self._result_log,
                           f"  [{i}/{len(bursts)}] @ {b_start:6.2f}s | {cls}")

            summary_path = out_dir / f"{base}_summary.png"
            analyzer.plot_summary(events, summary_path)

            report = analyzer.generate_report(events, csv_p, metadata, thresholds)
            report_path = out_dir / f"{base}_report.txt"
            report_path.write_text(report, encoding="utf-8")

            self.after(0, self._result_log, "\n" + "=" * 50)
            self.after(0, self._result_log, "分析完成！\n")
            self.after(0, self._result_log, report)
            self.after(0, self._result_log, f"\n报告：{report_path}")
            self.after(0, self._result_log, f"总览图：{summary_path}")

            self.last_report_content = report
            self._last_output_dir = out_dir

            self.after(0, lambda: self.open_dir_btn.configure(state="normal"))
            self.after(0, lambda: self.go_to_ai_btn.configure(state="normal"))
            self.after(0, self._refresh_prompt_template)

        except Exception as e:
            import traceback
            err = traceback.format_exc()
            self.after(0, self._result_log, f"\n[错误] {e}\n{err}")
            # 弹出错误反馈窗口
            if error_reporter is not None:
                exc = e
                self.after(0, lambda: error_reporter.show_error_dialog(
                    self, "分析失败", str(exc), exc,
                    f"分析 CSV 文件: {csv_path}"))

        finally:
            self.after(0, lambda: self.analyze_btn.configure(state="normal"))

    def _open_output_dir(self):
        if hasattr(self, "_last_output_dir"):
            try:
                if sys.platform == "win32":
                    os.startfile(self._last_output_dir)
                elif sys.platform == "darwin":
                    subprocess.run(["open", str(self._last_output_dir)])
                else:
                    subprocess.run(["xdg-open", str(self._last_output_dir)])
            except Exception as e:
                messagebox.showerror("错误", f"无法打开目录: {e}")


if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        # 程序启动失败的最后一道防线
        import traceback
        tb = traceback.format_exc()
        # 尝试用错误反馈窗口
        try:
            if error_reporter is not None:
                # 创建一个临时 root 来承载错误窗口
                temp_root = tk.Tk()
                temp_root.withdraw()
                error_reporter.show_error_dialog(
                    temp_root, "程序启动失败", str(e), e,
                    "程序无法正常启动")
                temp_root.mainloop()
            else:
                # 退化到原生 messagebox
                tk.Tk().withdraw()
                messagebox.showerror(
                    "启动失败",
                    f"程序无法启动:\n\n{e}\n\n"
                    f"请把错误信息发给 B站/抖音 josef_0464 或 QQ 群 611624374\n\n"
                    f"详细堆栈:\n{tb}")
        except Exception:
            # 连 tkinter 都用不了，就只能 print 了
            print("=" * 60)
            print("程序启动失败")
            print("=" * 60)
            print(tb)
            print("=" * 60)
            print("请把以上错误信息发给：")
            print("  B站 / 抖音: josef_0464")
            print("  QQ 群: 611624374 (星辰不妙屋)")
            print("=" * 60)
            input("按回车键退出...")
