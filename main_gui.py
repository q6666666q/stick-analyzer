"""
摇杆射击行为分析工具 v2.1 - GUI 主程序
功能：录制 → 分析 → 生成 AI 调参提示词 → 参考曲线收集

v2.1 新增/改进:
- 第七节：腰射 vs 开镜 不对称分析（差异 > 30% 给针对性曲线建议）
- 第八节：走位 vs 站桩 模式对比（走位组 ×1.3 阈值放宽）
- 过冲细分类型：大幅过冲（>0.15）vs 小抖动（0.05-0.15），调参建议精确到高/中/低段
- 行为分类细化：完美稳定 ⭐ / 稳定射击 ✓ / 接近稳定 / 中等稳定 等档位
  + 每档玩家直觉解释
- TMR 传感器措辞修正：从「霍尔阵营」改为「接近碳膜」（已是主流 FPS 默认）
- AI 提示词模板加入新章节解读规则 + 关键澄清"RC 是钝化操作不会导致过冲"
- 关键 bug 修复：SDL 跨线程 button 状态读不到（SDL_JOYSTICK_THREAD）
- XBOX 风格手柄优先 XInput（避免 pygame/SDL 在第三方控制器上的兼容性问题）
- 高回报率手柄（4000-8000Hz）卡顿优化（屏蔽 SDL joystick events）
- 采样率说明改为协议上限解释（不再误导成"链路瓶颈"）

v2.0 既有功能：
- 双驱动控制器支持：pygame（PS / Switch / 通用 HID）+ XInput（XBOX 系列）
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
DEFAULT_ADS_BUTTON = "TRIGGER_LEFT"      # LT / L2，FPS 玩家最常用的开镜键
TARGET_RATE_HZ = 500   # pygame 实际能力 ~500Hz；XInput 也用同值确保 GUI 流畅

APP_VERSION = "v2.1"
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

请把每个空白下划线那行替换成你自己的情况，下面有例子可以直接复制粘贴。

- 我的手柄型号：________________
  填你的手柄型号即可。

- 我的曲线编辑方式：________________
  从下面三种里选一个填进去：
    1) 支持 JSON 导入导出（在调参 APP 里能找到曲线导入/导出按钮）
    2) 只能在调参 APP 里拖动节点
    3) 不确定 —— 这个最通用，AI 会按"拖动节点"的方式给你坐标

- 我的曲线可调节点数：______ 个点
  数一下你的调参 APP 里曲线编辑界面有几个**可拖动的点**（包括起点 0,0 和终点 100,100）。
  常见情况：2 个点 / 4 个点 / 6 个点 / 8 个点（最常见）。

- 我的曲线模式：________________
  从下面两种里选一个填进去：
    1) 腰射 + 开镜分开两套曲线
    2) 只有一条综合曲线（所有状态共用，不区分腰射和开镜）

- 我的死区设置：______ %
  在调参 APP 里看死区数值（百分比），不知道就填 0 表示默认。
  常见死区：0% / 5% / 10% / 15%。

## 二、我当前的曲线配置

把对应模式下的曲线填进去，**没有的曲线类型整段删掉**。

### 如果你是「腰射 + 开镜分开」模式

#### 选 JSON 方式时（手柄支持导入导出）：

腰射曲线：
```
{
  "name": "腰射",
  "data": [0, 0, 6.0, 5.5, 16.0, 19.5, 32.0, 36.0, 50.0, 54.0, 68.0, 72.5, 86.0, 88.5, 100, 100]
}
```
^ 把上面 data 里的数字换成你 APP 里实际的曲线坐标（X1,Y1,X2,Y2... 交替）。

开镜曲线：
```
{
  "name": "开镜",
  "data": [0, 0, ..., 100, 100]
}
```

#### 选拖动节点方式时（不支持 JSON）：

腰射曲线（按你 APP 里的节点数量填）：
- 节点 1：X=0,    Y=0
- 节点 2：X=____, Y=____
- 节点 3：X=____, Y=____
- ...（按实际节点数加行）
- 最后一节点：X=100, Y=100

开镜曲线：
- 节点 1：X=0,    Y=0
- 节点 2：X=____, Y=____
- ...

### 如果你是「只有一条综合曲线」模式

#### 选 JSON 方式时：
```
{
  "name": "综合",
  "data": [0, 0, ..., 100, 100]
}
```

#### 选拖动节点方式时：
- 节点 1：X=0,    Y=0
- 节点 2：X=____, Y=____
- ...
- 最后一节点：X=100, Y=100

## 三、我的操作风格（必填）

- 开火时左摇杆怎么动：________________
  从下面里选一个填进去（或者自己描述）：
    1) 左右快速移动（A/D 走位）
    2) 缓慢推动（小步微调）
    3) 静止不动（站桩输出）
    4) 混合（前期走位、后期站定输出）
    5) 其他：______（自己描述）

  > 这一项很重要：左摇杆动得越多，瞄准/压枪的难度越高，AI 调参时要相应放宽要求。

## 四、我的痛点（必填，越具体越好）

把你当前体感上的具体问题写在这里。下面是例子，参考着写自己的：
- 中近距离贴脸甩枪跟不上
- 开镜后准星会在敌人身上小幅晃动停不下来
- 远程压枪到后段会过冲（甩过头）

如果你只有一条综合曲线，请说明痛点主要发生在「腰射时」还是「开镜时」。
例："开镜远程压枪过冲，但腰射感觉还行" → AI 会优先优化开镜场景。

## 五、我的 RC（防抖/增抖）设置

> ✓ 软件已经自动算好你的 RC 百分比，下面这块**不用改**，AI 会从下面的【数据分析报告】里直接读到。
> 如果你的手柄完全没有 RC 功能，可以在体感痛点里补一句"没有 RC"。

## 六、数据分析报告

{REPORT_CONTENT}

## 七、参考曲线（可选，但有的话强烈建议附上）

如果你能找到下面任何一种参考曲线，贴在这里 AI 会综合判断：
- 游戏内置曲线截图（描述或节点：______）
- 网上公开的同游戏曲线参数：______
- 朋友用着体感很好的曲线：______
- 调参 APP 内置社区分享的配置：______

参考曲线对 AI 很有价值，因为：
- 数学预设可能不是 100% 精确，参考曲线能补全缺失信息
- 看别人调好的曲线可以了解"业内共识的合理范围"
- AI 可以综合多个数据源给出更接近"通用最佳"的方案

## 八、我希望你做什么

1. **严格匹配我的曲线模式**：
   - 如果我是「综合曲线」，只输出一条曲线，不要给两条
   - 如果是「腰射 + 开镜分开」，输出两条
2. **综合分析报告 + 操作风格 + 体感痛点 + 参考曲线**，告诉我曲线哪段需要调整
3. **严格按我的曲线点数给方案**（4 个点的别给 8 个点）
4. **根据我的曲线编辑方式输出**：
   - JSON 方式 → 输出完整 JSON
   - 拖动节点方式 → 列出每个节点的 X、Y 值（小数点后 1 位）
5. **如果是综合曲线模式**：
   - 综合曲线是腰射和开镜的折中
   - 告诉我调整后在哪个场景表现更好
   - 两个场景冲突时优先满足体感痛点里更突出的那个
6. **如果我提供了反曲线数学建议，当作参考而不是绝对答案**
7. 解释为什么这样改，以及预期改善什么

## 重要原则（请 AI 严格遵守）

- 不要为了改而改，数据显示某段已经很好就不要动
- 体感优先于数据，数据有噪声，体感是真实的
- 一次只改 2-3 个节点，避免破坏整体平衡
- 改完后告诉我应该测试什么场景来验证
- 曲线点数少（2-4 个）时，重点放在节点 X 位置和 Y 高度
- 不要假设我有几条曲线，按我填的"曲线模式"严格匹配
- 关于 RC（防抖/增抖）：
  - 看报告里给的"百分比"理解强度（70% = 强增抖，30% = 轻度）
  - 没有 RC 功能（百分比 0%）→ 别给超激进的曲线，没有硬件兜底
  - 强增抖（>60%）→ 低段曲线稍保守一点，避免硬件+曲线双重放大
  - 防抖方向（特别是强防抖）→ 跟手感会变肉，曲线低段可以稍激进些补偿
- 关于死区：
  - 死区越大，低段微推进入"激活"越慢，曲线低段斜率可以适当抬高补偿
  - 死区为 0（无死区）时，低段曲线要更柔和，避免过度敏感
- 关于左摇杆配合：
  - 走位类（A/D 移动）：压枪稳定度阈值应放宽，因为人在移动中瞄准必然抖
  - 站桩输出：可以用最严格的稳定度阈值要求
- 关于传感器类型：
  - TMR（主流 FPS 出厂默认）：算法已成熟，延迟和线性度接近碳膜 ALPS，
    无需特殊调整，按通用 FPS 调参逻辑即可
  - 碳膜 ALPS（传统）：基准方案，按通用 FPS 调参逻辑
  - 霍尔（非 FPS 主流）：中心响应钝、圆周率差、斜角信号缺失，
    若主导推杆区间在 X<10 中心钝化区，建议第一个曲线点设在 (4, 20)
    附近做反死区补偿（仅对霍尔有效，TMR/碳膜不需要）
  - 不要把 TMR 和霍尔混为一谈 —— TMR 现已是主流 FPS 默认，不再有"中心钝"问题

- 关于报告「第三节 过冲细分类型」：
  - 大幅过冲（>0.15 幅度）：高段曲线斜率过高，准星甩过目标
  - 小抖动（0.05-0.15 幅度）：低段曲线斜率过陡 / 硬件本底高 / 高强度 RC 噪声
  - 报告里会标"主要是大幅过冲（X%）"或"主要是小抖动" → 据此选择调高段还是低段
  - 注意：RC 是钝化操作（叠抖动让玩家变钝），不会导致大幅过冲；
    大幅过冲只可能是高段斜率问题，不要建议"降 RC 强度"

- 关于报告「第七节 腰射 vs 开镜 不对称分析」：
  - 报告会算两种模式各自的稳定度等级 + 相对差异 %
  - 差异 > 30% 触发"不对称问题"标记
  - "开镜抖动比腰射高"→ ADS 曲线低段过激/中段过陡，重点调 ADS 那条
  - "腰射抖动比开镜高"→ 腰射曲线低段微控不足，重点调腰射那条
  - 如果是综合曲线模式（无法分别调），综合曲线应偏向较差的那个场景

- 关于报告「第八节 走位 vs 站桩 对比」：
  - 走位组用 ×1.3 放宽阈值评级（实战中走位本身瞄准就难）
  - "走位劣化 +30-50%" → 正常范围，多练走位射击肌肉记忆即可
  - "走位劣化 +50% 以上" → 怀疑左摇杆死区过小/左右摇杆曲线不协调/硬件交叉串扰，
    通常不是右摇杆曲线本身的问题
  - 全走位（无站桩对比）→ 实战常态，参考走位组单独评级即可
  - "基线过小" 标记 → 说明站桩样本中右摇杆几乎没动，无法形成可信对照，
    建议忽略走位/站桩对比，看其他指标
"""
# ===========================================================
class StickRecorder:
    """后台录制线程（使用 controller_backend 抽象层）"""

    # 性能档位（采样率 Hz, GUI 更新间隔秒）
    PERF_PROFILES = {
        "high":   {"rate": 500, "gui_interval": 0.1, "label": "高精度（默认）"},
        "normal": {"rate": 250, "gui_interval": 0.2, "label": "平衡"},
        "low":    {"rate": 125, "gui_interval": 0.5, "label": "低性能（旧电脑）"},
    }

    def __init__(self, output_path, metadata, fire_button, ads_button,
                 controller_info, controller_manager,
                 on_update, on_done,
                 perf_profile="high",
                 noise_floor_x=0.0, noise_floor_y=0.0,
                 mark_button=None):
        self.output_path = output_path
        self.metadata = metadata
        self.fire_button = fire_button       # 逻辑代码（如 RIGHT_SHOULDER）
        self.ads_button = ads_button
        self.controller_info = controller_info  # ControllerInfo
        self.controller_manager = controller_manager  # ControllerManager
        self.on_update = on_update
        self.on_done = on_done
        self.perf_profile = perf_profile
        # [T0.3] 录制前校准得到的传感器本底（rx/ry 的标准差）
        self.noise_floor_x = float(noise_floor_x)
        self.noise_floor_y = float(noise_floor_y)
        # [T2.1] 玩家手动标记按键（按一下打一个 "good" 标记到 CSV）
        self.mark_button = mark_button       # 逻辑代码或 None
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
        # [T0.3] 写入硬件本底（用于分析时减除）
        csv_file.write(f"# meta: noise_floor_x={self.noise_floor_x:.6f}\n")
        csv_file.write(f"# meta: noise_floor_y={self.noise_floor_y:.6f}\n")
        # [T0.2] 标称采样率（实际有效率由分析器统计）
        profile_for_meta = self.PERF_PROFILES.get(self.perf_profile,
                                                   self.PERF_PROFILES["high"])
        csv_file.write(f"# meta: nominal_rate={profile_for_meta['rate']}\n")
        csv_file.write(f"# meta: started={datetime.now().isoformat()}\n")

        # 按键列：用统一的逻辑代码作为列名（小写）
        btn_columns = [f"btn_{b.lower()}" for b in cb.LOGICAL_BUTTONS]
        writer = csv.writer(csv_file)
        writer.writerow([
            "timestamp_ns", "elapsed_s",
            "lx", "ly", "rx", "ry",
            "lt", "rt",
        ] + btn_columns + ["fire", "ads", "mark"])

        start_ns = time.time_ns()
        sample_count = 0
        fire_count = 0
        ads_count = 0
        # [T0.2] 重复帧统计：连续两帧 (rx,ry,lx,ly) 完全相同视为底层未更新
        dup_frames = 0
        last_signature = None
        # [T2.1] 标记键状态：边沿触发，避免一直按住时连续标记
        mark_count = 0
        last_mark_pressed = False
        # 根据性能档位决定采样率和 GUI 更新间隔
        profile = self.PERF_PROFILES.get(self.perf_profile,
                                          self.PERF_PROFILES["high"])
        target_rate = profile["rate"]
        gui_interval_s = profile["gui_interval"]
        sample_interval_ns = int(1e9 / target_rate)
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

                # [T2.1] 边沿检测：从未按 → 按下 = 一次标记事件
                mark = ""
                if self.mark_button:
                    cur_mark = bool(buttons_dict.get(self.mark_button, False))
                    if cur_mark and not last_mark_pressed:
                        mark = "good"
                        mark_count += 1
                    last_mark_pressed = cur_mark

                elapsed = (now_ns - start_ns) / 1e9

                # [T0.2] 重复帧检测：6 位精度的轴值签名
                cur_sig = (round(state.rx, 6), round(state.ry, 6),
                           round(state.lx, 6), round(state.ly, 6))
                if last_signature is not None and cur_sig == last_signature:
                    dup_frames += 1
                last_signature = cur_sig

                row = [
                    now_ns, f"{elapsed:.6f}",
                    f"{state.lx:.5f}", f"{state.ly:.5f}",
                    f"{state.rx:.5f}", f"{state.ry:.5f}",
                    f"{state.lt:.4f}", f"{state.rt:.4f}",
                ]
                for b in cb.LOGICAL_BUTTONS:
                    row.append(int(bool(buttons_dict.get(b, False))))
                row.extend([int(fire), int(ads), mark])
                writer.writerow(row)

                sample_count += 1
                if fire:
                    fire_count += 1
                if ads:
                    ads_count += 1

                # GUI 更新降频（根据性能档位）
                if (now_ns - last_update_ns) / 1e9 > gui_interval_s:
                    rate = sample_count / max(elapsed, 1e-6)
                    # [T0.2] 实时算有效采样率
                    dup_ratio = dup_frames / max(sample_count, 1)
                    effective_rate = rate * (1.0 - dup_ratio)
                    self.on_update({
                        "elapsed": elapsed,
                        "samples": sample_count,
                        "rate": rate,
                        "effective_rate": effective_rate,
                        "dup_ratio": dup_ratio,
                        "fire_pct": 100 * fire_count / max(sample_count, 1),
                        "ads_pct": 100 * ads_count / max(sample_count, 1),
                        "lx": state.lx, "ly": state.ly,
                        "rx": state.rx, "ry": state.ry,
                        "lt": state.lt, "rt": state.rt,
                        "fire": fire, "ads": ads,
                        "mark_count": mark_count,
                        "just_marked": (mark == "good"),
                    })
                    last_update_ns = now_ns

                next_sample_ns += sample_interval_ns
                # 防止时间漂移过大（比如系统卡顿后），重新对齐
                if next_sample_ns < now_ns:
                    next_sample_ns = now_ns + sample_interval_ns

        finally:
            csv_file.close()
            elapsed_total = (time.time_ns() - start_ns) / 1e9
            rate = sample_count / max(elapsed_total, 1e-6)
            dup_ratio = dup_frames / max(sample_count, 1)
            summary = {
                "duration": elapsed_total,
                "samples": sample_count,
                "rate": rate,
                "effective_rate": rate * (1.0 - dup_ratio),
                "dup_frames": dup_frames,
                "dup_ratio": dup_ratio,
                "fire_count": fire_count,
                "ads_count": ads_count,
                "mark_count": mark_count,
                "output": str(self.output_path),
                "noise_floor_x": self.noise_floor_x,
                "noise_floor_y": self.noise_floor_y,
            }
            self.on_done(True, summary)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"摇杆射击行为分析工具 {APP_VERSION}")
        self.geometry("1000x1100")
        self.recorder = None
        self.csv_path_var = tk.StringVar()
        self.last_report_content = ""

        # 安装全局异常钩子（捕获所有未处理异常，弹出反馈窗口）
        if error_reporter is not None:
            try:
                error_reporter.install_exception_hook(self)
            except Exception as e:
                print(f"[警告] 异常钩子安装失败: {e}")

        # [T-1.2 紧急修复] 控制器管理器改为异步初始化
        # 此前在 __init__ 里同步创建 ControllerManager()，会调用 pygame.init()，
        # 在某些 Windows 系统上会阻塞数秒（扫描音视频子系统、HID 设备），
        # 导致窗口建好但 mainloop 未启动 → 窗口不显示，进程在跑但 hwnd=0。
        # 现在改为：__init__ 里只搭 UI 框架，异步线程后台跑重型初始化。
        self.controller_mgr = None
        self._init_pending = True   # UI 上有 controller_mgr 检查的地方据此判断

        # 槽位选择变量（4 个槽位）
        self.slot_var = tk.IntVar(value=0)
        self.slot_radio_buttons = []  # GUI Radiobutton 引用，用于动态更新

        self._build_ui()

        # UI 搭好后立即让窗口可见，再异步启动重型初始化
        # update_idletasks 会把所有挂起的几何计算执行掉，update 会让窗口实际显示
        self.update_idletasks()
        self.update()

        # 异步启动控制器后端：mainloop 启动后 50ms 触发，确保窗口已渲染
        self.after(50, self._async_bootstrap_controllers)

    def _async_bootstrap_controllers(self):
        """[T-1.2] 在后台线程里创建 ControllerManager 并扫描手柄。

        流程：
          1. 主线程调用本方法 → 立刻在 scan_status_label 显示"正在初始化…"
          2. 启动 daemon 线程跑 _bootstrap_worker（创建 ControllerManager + scan）
          3. 工作线程完成后用 self.after(0, _on_bootstrap_done, ...) 回主线程
          4. 主线程更新 self.controller_mgr 并刷新 UI
        如果 cb 模块本身缺失，本方法会立即在主线程报错（不需要后台线程）。
        """
        if cb is None:
            messagebox.showerror(
                "缺少模块",
                "找不到 controller_backend.py 模块，请确认它和本程序在同一目录")
            self._init_pending = False
            try:
                self.scan_status_label.configure(
                    text="后端模块缺失，无法识别手柄",
                    foreground="#C0392B")
            except Exception:
                pass
            return

        # 显示"初始化中"
        try:
            self.scan_status_label.configure(
                text="正在初始化手柄驱动…", foreground="#2980B9")
        except Exception:
            pass

        def _bootstrap_worker():
            """后台线程：创建 ControllerManager 并完成首次扫描。"""
            err_msg = None
            mgr = None
            scan_msg = ""
            try:
                mgr = cb.ControllerManager()
                # 首次扫描，把结果一并带回主线程
                try:
                    scan_msg = mgr.scan_and_assign()
                except Exception as e:
                    scan_msg = f"扫描出错: {e}"
            except Exception as e:
                import traceback
                err_msg = f"{e}\n\n{traceback.format_exc()}"

            # 切回主线程更新 UI
            self.after(0, self._on_bootstrap_done, mgr, scan_msg, err_msg)

        threading.Thread(
            target=_bootstrap_worker,
            daemon=True,
            name="controller-bootstrap",
        ).start()

    def _on_bootstrap_done(self, mgr, scan_msg: str, err_msg):
        """[T-1.2] 异步初始化完成回调，运行在主线程。"""
        self._init_pending = False

        if err_msg is not None:
            messagebox.showerror(
                "驱动初始化失败",
                "控制器驱动初始化时出错：\n\n" + err_msg)
            try:
                self.scan_status_label.configure(
                    text="驱动初始化失败，请重启程序",
                    foreground="#C0392B")
            except Exception:
                pass
            return

        self.controller_mgr = mgr

        # 检查驱动可用性（迁移自原 __init__）
        if mgr is not None and not mgr.has_pygame() and not mgr.has_xinput():
            messagebox.showerror(
                "缺少驱动库",
                "未检测到 pygame 或 XInput-Python 库。\n"
                "请运行：pip install pygame XInput-Python")

        # 把首次扫描的结果显示出来 + 刷新 UI
        try:
            if scan_msg:
                self.scan_status_label.configure(text=scan_msg, foreground="#222")
            self._refresh_slot_display()
            self._refresh_button_combos_for_current_slot()
        except Exception as e:
            print(f"[警告] 初始扫描后刷新 UI 失败: {e}")

        # [T0.1] 首次启动显示欢迎面板（用 after 让 UI 先渲染）
        self.after(300, self._show_welcome_if_needed)

    # ========== [T0.1] 欢迎面板 ==========
    def _config_path(self) -> Path:
        """用户配置文件路径：~/.stickanalyzer/config.json"""
        return Path.home() / ".stickanalyzer" / "config.json"

    def _load_config(self) -> dict:
        path = self._config_path()
        if not path.exists():
            return {}
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_config(self, cfg: dict):
        path = self._config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[警告] 保存配置失败: {e}")

    def _show_welcome_if_needed(self):
        """首次启动显示欢迎面板，介绍工具用途和 3 步工作流。"""
        cfg = self._load_config()
        if cfg.get("welcome_seen") is True:
            return

        dlg = tk.Toplevel(self)
        dlg.title("欢迎使用摇杆射击行为分析工具")
        dlg.geometry("620x520")
        dlg.transient(self)
        dlg.resizable(False, False)
        # 居中
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 620) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 520) // 2
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

        # 标题
        ttk.Label(
            dlg,
            text="欢迎使用 摇杆射击行为分析工具",
            font=("", 16, "bold")).pack(pady=(18, 4))
        ttk.Label(
            dlg,
            text="一个用来量化你压枪稳不稳、反推曲线该怎么调的工具",
            foreground="#555").pack(pady=(0, 18))

        # 内容区
        body_frame = ttk.Frame(dlg)
        body_frame.pack(fill="both", expand=True, padx=24, pady=0)

        what_text = (
            "【适合谁】\n"
            "  • FPS 手柄玩家（Apex / 战地 / TheFinals 等）\n"
            "  • 已经在用调参 APP（北通 / 飞智 / 莱仕达 / 八位堂等）改过曲线，\n"
            "    但不确定"
            "改的方向对不对的人\n"
            "  • 想知道自己压枪到底稳在哪、不稳在哪的人\n"
            "\n"
            "【不适合谁】\n"
            "  • 鼠标键盘玩家（本工具只分析摇杆数据）\n"
            "  • 想用工具判断手柄硬件是否损坏（这不是测试仪）\n"
            "\n"
            "【工作流：3 步】\n"
            "  ① 录制：连上手柄，正常打一局靶场或匹配 → 软件记录摇杆轨迹\n"
            "  ② 分析：上传刚才录的 CSV → 看自己稳定度评分和波形\n"
            "  ③ 调参：复制软件生成的提示词到 AI（如 Claude），让它帮你改曲线\n"
            "\n"
            "【录制前会有 3 秒静止校准】\n"
            "  程序会让你松开摇杆 3 秒，记录传感器本底（用来让分析更准）。\n"
            "  这是正常步骤，不是 bug。"
        )
        text_widget = tk.Text(
            body_frame, wrap="word", height=20,
            font=("", 10), relief="flat",
            background=dlg.cget("bg"), borderwidth=0)
        text_widget.insert("1.0", what_text)
        text_widget.configure(state="disabled")
        text_widget.pack(fill="both", expand=True)

        # 底部
        bottom = ttk.Frame(dlg)
        bottom.pack(fill="x", padx=24, pady=14)

        dont_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bottom, text="不再显示这个欢迎信息",
            variable=dont_show_var).pack(side="left")

        def _close():
            if dont_show_var.get():
                cfg["welcome_seen"] = True
                self._save_config(cfg)
            dlg.destroy()

        ttk.Button(bottom, text="知道了，开始使用",
                   command=_close).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", _close)

    # ========== [T1.1] RC 强度自动计算 ==========
    def _recompute_rc_intensity(self):
        """监听 RC 范围/数值/方向变化，自动算百分比和等级码，刷新 UI 标签。

        计算结果同时写入 self.meta_vars[f"{prefix}_intensity"]，录制时直接用。
        """
        if not hasattr(self, "_rc_auto_labels"):
            return
        for prefix, lbl in self._rc_auto_labels.items():
            try:
                rmin = float(self.meta_vars[f"{prefix}_range_min"].get() or 0)
                rmax = float(self.meta_vars[f"{prefix}_range_max"].get() or 0)
                value = float(self.meta_vars[prefix].get() or 0)
                direction = self.meta_vars[f"{prefix}_direction"].get()
            except (ValueError, KeyError, AttributeError):
                continue

            pct, code, display = self._calc_rc_intensity(
                rmin, rmax, value, direction)
            intensity_var = self.meta_vars.get(f"{prefix}_intensity")
            if intensity_var is not None:
                intensity_var.set(code)
            try:
                lbl.configure(text=display)
            except tk.TclError:
                # 控件已销毁
                pass

    @staticmethod
    def _calc_rc_intensity(rmin, rmax, value, direction):
        """根据 RC 范围、当前值、方向算出强度。

        返回 (pct: float, code: str, display: str)
            code ∈ {"none", "antishake", "light", "medium", "strong", "extreme"}
            display 是给 UI 显示的中文标签
        """
        if rmin == 0 and rmax == 0:
            return 0.0, "none", "→ 无 RC 功能"
        if direction == "neutral" or value == 0:
            return 0.0, "none", "→ 0% 中性"

        max_abs = max(abs(rmin), abs(rmax))
        if max_abs == 0:
            return 0.0, "none", "→ 范围无效"
        pct = min(100.0, abs(value) / max_abs * 100.0)

        if direction == "antishake":
            # 防抖方向不细分等级，统一归到 antishake
            return pct, "antishake", f"→ {pct:.0f}% 防抖"

        # 动感方向按百分比分级（边界值含在下界，与 GUI 描述"0-30% 轻度"一致）
        if pct <= 30:
            code, name = "light", "轻度"
        elif pct <= 60:
            code, name = "medium", "中度"
        elif pct <= 90:
            code, name = "strong", "强"
        else:
            code, name = "extreme", "极限"
        return pct, code, f"→ {pct:.0f}% {name}增抖"

    def _on_rc_dual_toggle(self):
        """[T1.1] 单 RC / 双 RC 模式切换显示。"""
        if not hasattr(self, "_rc_single_frame"):
            return
        if self.meta_vars["rc_dual"].get():
            # 切到双 RC：隐藏单 RC，显示双 RC
            self._rc_single_frame.pack_forget()
            self._rc_dual_frame.pack(fill="x")
        else:
            # 切到单 RC：隐藏双 RC，显示单 RC
            self._rc_dual_frame.pack_forget()
            self._rc_single_frame.pack(fill="x")
        self._recompute_rc_intensity()

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

        # [T2.1] 标记键 - 玩家按一下标记"这次压得好"
        ttk.Label(key_frame, text="标记键 (MARK):", width=14).grid(
            row=2, column=0, sticky="e", padx=5, pady=5)
        self.mark_button_var = tk.StringVar(value="BACK")  # 默认 BACK 键
        mark_combo = ttk.Combobox(key_frame, state="readonly", width=30)
        mark_combo.grid(row=2, column=1, sticky="w", padx=5, pady=5)
        mark_combo.bind("<<ComboboxSelected>>",
                        lambda e: self._on_button_change(mark_combo, "mark"))
        self.mark_combo = mark_combo
        ttk.Label(key_frame, foreground="#3498DB", font=("", 8),
                  text="录制时按一下这个键 = 标记'刚才那次压得好'，"
                       "用于事后和算法评分对照",
                  wraplength=900).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 4))

        # 按键提示文本（动态更新）
        self.key_hint_label = ttk.Label(
            key_frame,
            text="按键标签会根据上方选中的控制器自动调整。",
            foreground="gray", font=("", 8))
        self.key_hint_label.grid(
            row=4, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # [Bug 修复] 测试键位按钮 —— 弹窗实时显示按键映射
        # 让用户能 30 秒自检"我按 RT 时软件认到了什么"
        ttk.Button(
            key_frame, text="🎯 测试键位映射",
            command=self._open_button_test_dialog
        ).grid(row=0, column=2, rowspan=3, sticky="ns", padx=10, pady=5)

        # 初次填充按键下拉（先按默认 XBOX 布局，扫描后会更新）
        self._refresh_button_combos(cb.LAYOUT_XBOX if cb else "xbox")

        # ====== 性能模式（如果电脑卡可调低）======
        perf_frame = ttk.LabelFrame(parent, text="性能模式", padding=10)
        perf_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(perf_frame, text="采样精度:", width=14).grid(
            row=0, column=0, sticky="e", padx=5, pady=2)
        self.perf_profile_var = tk.StringVar(value="high")
        perf_options = [
            ("⚡ 高精度（默认，500Hz）- 推荐配置较好的电脑", "high"),
            ("🔋 平衡（250Hz）- 大多数电脑", "normal"),
            ("🐢 低性能（125Hz）- 老电脑或同时运行 Apex 卡顿时", "low"),
        ]
        self._perf_options = perf_options
        perf_combo = ttk.Combobox(perf_frame,
                                   values=[o[0] for o in perf_options],
                                   state="readonly", width=50)
        perf_combo.current(0)
        perf_combo.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        perf_combo.bind("<<ComboboxSelected>>",
                        lambda e: self._on_perf_change(perf_combo))
        self.perf_combo = perf_combo

        ttk.Label(perf_frame,
                  text="提示：录制时如果游戏掉帧或电脑卡顿，请切换到「低性能」模式。\n"
                       "采样率降低不会显著影响分析准确度（200Hz 就足够压枪分析）。",
                  foreground="#666", font=("", 8), justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # 元数据输入区
        meta_frame = ttk.LabelFrame(
            parent, text="本次记录元数据（建议填写）", padding=10)
        meta_frame.pack(fill="x", padx=10, pady=5)

        self.meta_vars = {}

        # ===== [T1.1] 摇杆传感器类型 + 回报率 =====
        sensor_row = ttk.Frame(meta_frame)
        sensor_row.pack(fill="x", pady=(0, 6))
        ttk.Label(sensor_row, text="摇杆传感器类型:",
                  width=16).pack(side="left", padx=5)

        sensor_options = [
            ("TMR（主流 FPS 默认）", "tmr"),
            ("碳膜 ALPS（传统）", "alps"),
            ("霍尔（非主流，钝）", "hall"),
            ("不确定（按 TMR）", "tmr"),
        ]
        # 默认选 TMR（第 1 个选项，当前主流）
        v_sensor_label = tk.StringVar(value=sensor_options[0][0])
        v_sensor_code = tk.StringVar(value="tmr")
        self.meta_vars["sensor_type"] = v_sensor_code

        def _sync_sensor_code(*_):
            label = v_sensor_label.get()
            for lbl, code in sensor_options:
                if lbl == label:
                    v_sensor_code.set(code)
                    return
        v_sensor_label.trace_add("write", _sync_sensor_code)

        ttk.Combobox(sensor_row, textvariable=v_sensor_label,
                     values=[o[0] for o in sensor_options],
                     state="readonly", width=28).pack(side="left", padx=5)

        # 回报率输入
        ttk.Label(sensor_row, text="回报率:").pack(side="left", padx=(15, 2))
        v_polling = tk.StringVar(value="1000")
        self.meta_vars["polling_rate"] = v_polling
        ttk.Entry(sensor_row, textvariable=v_polling, width=6).pack(
            side="left", padx=2)
        ttk.Label(sensor_row, text="Hz",
                  foreground="#666").pack(side="left", padx=(0, 4))
        ttk.Label(sensor_row,
                  text="（手柄向电脑发数据的频率，常见 125/250/500/1000）",
                  foreground="#888", font=("", 8)).pack(side="left", padx=5)

        # ===== [T1.1] RC 设置（自动算百分比，不再让用户自己折算） =====
        rc_group = ttk.LabelFrame(
            meta_frame,
            text="RC（防抖 / 增抖）设置 — 程序自动算百分比", padding=8)
        rc_group.pack(fill="x", pady=(0, 6))

        ttk.Label(
            rc_group, foreground="#666", font=("", 8), justify="left",
            text=("不同手柄 RC 范围差异大（±10、±100、±500 都有）。\n"
                  "下面填【范围】+【当前数值】+【方向】，程序自动算百分比并选等级。\n"
                  "手柄没有 RC 功能 → 把'最小'和'最大'都填 0，方向选'中性'。\n"
                  "防抖 = 抑制摇杆抖动；增抖 = 增强摇杆响应（让小幅推杆放大）。")
        ).pack(fill="x", pady=(0, 6), anchor="w")

        # 单/双 RC 模式切换勾选框
        v_dual_rc = tk.BooleanVar(value=False)
        self.meta_vars["rc_dual"] = v_dual_rc
        ttk.Checkbutton(
            rc_group,
            text="腰射和开镜的 RC 是分开设置的（不勾 = 用一组统一的 RC）",
            variable=v_dual_rc,
            command=self._on_rc_dual_toggle
        ).pack(anchor="w", pady=(0, 4))

        # 存每个 RC 行的"自动算结果"标签，供 _recompute_rc_intensity 更新
        self._rc_auto_labels = {}

        def _build_rc_row(parent, label_text, prefix):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=2)

            ttk.Label(row, text=label_text, width=10).pack(side="left", padx=2)

            ttk.Label(row, text="范围:").pack(side="left", padx=(6, 2))
            v_min = tk.StringVar(value="-10")
            v_max = tk.StringVar(value="10")
            self.meta_vars[f"{prefix}_range_min"] = v_min
            self.meta_vars[f"{prefix}_range_max"] = v_max
            ttk.Entry(row, textvariable=v_min, width=5).pack(side="left", padx=1)
            ttk.Label(row, text="到").pack(side="left", padx=1)
            ttk.Entry(row, textvariable=v_max, width=5).pack(side="left", padx=1)

            ttk.Label(row, text="当前值:").pack(side="left", padx=(8, 2))
            v_value = tk.StringVar(value="0")
            self.meta_vars[prefix] = v_value
            ttk.Entry(row, textvariable=v_value, width=6).pack(side="left", padx=1)

            ttk.Label(row, text="方向:").pack(side="left", padx=(8, 2))
            v_dir = tk.StringVar(value="neutral")
            self.meta_vars[f"{prefix}_direction"] = v_dir
            for code, txt in [("antishake", "防抖"),
                              ("neutral", "中性"),
                              ("motion", "增抖")]:
                ttk.Radiobutton(
                    row, text=txt, variable=v_dir, value=code,
                    command=self._recompute_rc_intensity
                ).pack(side="left", padx=1)

            auto_lbl = ttk.Label(
                row, text="→ 0%", foreground="#3498DB",
                font=("", 9, "italic"), width=22)
            auto_lbl.pack(side="left", padx=(6, 2))
            self._rc_auto_labels[prefix] = auto_lbl

            # intensity code 隐式存到 meta_vars，由重算逻辑更新
            self.meta_vars[f"{prefix}_intensity"] = tk.StringVar(value="none")

            # 监听三个数值变化
            for v in (v_min, v_max, v_value):
                v.trace_add("write",
                            lambda *a: self._recompute_rc_intensity())

        # 单 RC 模式（默认显示）
        self._rc_single_frame = ttk.Frame(rc_group)
        _build_rc_row(self._rc_single_frame, "RC:", "rc_combined")
        self._rc_single_frame.pack(fill="x")

        # 双 RC 模式（默认隐藏，勾选后显示）
        self._rc_dual_frame = ttk.Frame(rc_group)
        _build_rc_row(self._rc_dual_frame, "腰射 RC:", "rc_hipfire")
        _build_rc_row(self._rc_dual_frame, "开镜 RC:", "rc_ads")
        # 不 pack，等用户勾选才显示

        # 启动后立即算一次
        self.after(50, self._recompute_rc_intensity)

        # ===== 其他元数据字段（保持原样） =====
        others_frame = ttk.Frame(meta_frame)
        others_frame.pack(fill="x", pady=(4, 0))
        other_rows = [
            ("curve", "曲线版本/名称:", "",
             "便于后续区分多次记录，如 v1, v2, 试用版 等"),
            ("weapons", "主要使用武器:", "",
             "如 R99、R301（冲锋枪、步枪等）"),
            ("scene", "测试场景:", "训练场",
             "训练场 / 比赛 / 休闲对战 等"),
        ]
        for i, (key, label, default, hint) in enumerate(other_rows):
            ttk.Label(others_frame, text=label, width=14).grid(
                row=i, column=0, sticky="e", padx=5, pady=2)
            var = tk.StringVar(value=default)
            self.meta_vars[key] = var
            ttk.Entry(others_frame, textvariable=var, width=22).grid(
                row=i, column=1, sticky="w", padx=5, pady=2)
            ttk.Label(others_frame, text=hint, foreground="gray",
                      font=("", 8)).grid(
                row=i, column=2, sticky="w", padx=5, pady=2)

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
            elif btn_type == "ads":
                self.ads_button_var.set(logical_code)
            elif btn_type == "mark":
                self.mark_button_var.set(logical_code)

    # ========== [Bug 修复] 键位映射实时测试 ==========
    def _open_button_test_dialog(self):
        """弹窗实时显示当前手柄按键状态。

        让用户能直观看到"我按 RT 软件认到了什么"，自检键位选错没。
        """
        if self.controller_mgr is None:
            messagebox.showinfo("请稍候", "控制器管理器还没初始化，等几秒再点。")
            return
        ctrl = self.controller_mgr.get_current_controller()
        if ctrl is None:
            messagebox.showwarning(
                "未选择手柄",
                "请先在「① 选择控制器」里选定一个手柄，然后再点测试。")
            return
        # 录制中不让开测试窗（同时读 controller 会冲突）
        if self.recorder is not None and getattr(
                self.recorder, "_thread", None) is not None and self.recorder._thread.is_alive():
            messagebox.showinfo("正在录制", "正在录制中，请先停止录制再测试键位。")
            return

        dlg = tk.Toplevel(self)
        dlg.title("🎯 键位映射实时测试")
        dlg.geometry("520x520")
        dlg.transient(self)
        # 居中
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 520) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 520) // 2
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

        ttk.Label(dlg, text="按手柄上的任意键，看软件识别成什么",
                  font=("", 12, "bold")).pack(pady=(15, 4))
        ttk.Label(
            dlg,
            text=f"当前手柄: {ctrl.display_string()}（布局: {ctrl.layout}）\n"
                 f"如果你按 RT 但下面显示的不是 'RT 右扳机'，说明按键映射有 bug，"
                 f"请反馈给作者。",
            foreground="#555", justify="center",
            font=("", 9)).pack(pady=(0, 10))

        # 三块显示区
        # 1. 当前按下的键（高亮）
        pressed_frame = ttk.LabelFrame(dlg, text="当前按下的键", padding=8)
        pressed_frame.pack(fill="x", padx=15, pady=4)
        pressed_lbl = tk.Label(
            pressed_frame, text="（无）", font=("", 11, "bold"),
            foreground="#27AE60", height=2,
            wraplength=470, justify="center")
        pressed_lbl.pack(fill="x")

        # 2. 扳机数值
        trig_frame = ttk.LabelFrame(dlg, text="扳机模拟值", padding=8)
        trig_frame.pack(fill="x", padx=15, pady=4)
        lt_lbl = ttk.Label(trig_frame, text="左扳机 LT: 0.00",
                           font=("", 10))
        lt_lbl.pack(anchor="w")
        rt_lbl = ttk.Label(trig_frame, text="右扳机 RT: 0.00",
                           font=("", 10))
        rt_lbl.pack(anchor="w")

        # 3. 摇杆值
        stick_frame = ttk.LabelFrame(dlg, text="摇杆值", padding=8)
        stick_frame.pack(fill="x", padx=15, pady=4)
        ls_lbl = ttk.Label(stick_frame, text="左摇杆 L: ( 0.00,  0.00)",
                           font=("Consolas", 10))
        ls_lbl.pack(anchor="w")
        rs_lbl = ttk.Label(stick_frame, text="右摇杆 R: ( 0.00,  0.00)",
                           font=("Consolas", 10))
        rs_lbl.pack(anchor="w")

        # 4. 当前选定的开火/开镜键状态
        sel_frame = ttk.LabelFrame(
            dlg, text="你当前选定的键 / 实时状态", padding=8)
        sel_frame.pack(fill="x", padx=15, pady=4)

        fire_btn = self.fire_button_var.get()
        ads_btn = self.ads_button_var.get()
        mark_btn = (self.mark_button_var.get()
                    if hasattr(self, "mark_button_var") else "")
        if cb is not None:
            fire_disp = cb.get_button_display_name(ctrl.layout, fire_btn)
            ads_disp = cb.get_button_display_name(ctrl.layout, ads_btn)
            mark_disp = (cb.get_button_display_name(ctrl.layout, mark_btn)
                         if mark_btn else "")
        else:
            fire_disp = fire_btn
            ads_disp = ads_btn
            mark_disp = mark_btn

        fire_status = ttk.Label(
            sel_frame,
            text=f"🔫 开火键: {fire_disp}（{fire_btn}） — 状态: 未按",
            font=("", 10))
        fire_status.pack(anchor="w", pady=2)
        ads_status = ttk.Label(
            sel_frame,
            text=f"🎯 开镜键: {ads_disp}（{ads_btn}） — 状态: 未按",
            font=("", 10))
        ads_status.pack(anchor="w", pady=2)
        if mark_btn:
            mark_status = ttk.Label(
                sel_frame,
                text=f"⭐ 标记键: {mark_disp}（{mark_btn}） — 状态: 未按",
                font=("", 10))
            mark_status.pack(anchor="w", pady=2)
        else:
            mark_status = None

        # 关闭按钮
        ttk.Button(dlg, text="关闭", command=dlg.destroy).pack(pady=8)

        # 后台线程读取手柄状态
        stop_evt = threading.Event()
        dlg.protocol("WM_DELETE_WINDOW",
                     lambda: (stop_evt.set(), dlg.destroy()))

        def _poll():
            while not stop_evt.is_set():
                try:
                    state = self.controller_mgr.read_state(ctrl)
                except Exception:
                    time.sleep(0.1)
                    continue
                # 在主线程更新 UI
                try:
                    self.after(0, _update_ui, state)
                except tk.TclError:
                    return
                time.sleep(0.05)  # 20 Hz 更新

        def _update_ui(state):
            try:
                # 当前按下的键
                pressed = []
                if cb is not None:
                    for logical, val in state.buttons.items():
                        if val:
                            disp = cb.get_button_display_name(
                                ctrl.layout, logical)
                            if disp.startswith("(") and disp.endswith(")"):
                                continue  # 跳过 "(无)"
                            pressed.append(f"{disp} [{logical}]")
                # 扳机
                if state.lt > 0.05:
                    pressed.append(f"LT 扳机 ({state.lt:.2f})")
                if state.rt > 0.05:
                    pressed.append(f"RT 扳机 ({state.rt:.2f})")

                pressed_lbl.configure(
                    text="\n".join(pressed) if pressed else "（无 — 按一下手柄按键试试）",
                    foreground="#27AE60" if pressed else "#888")

                lt_lbl.configure(text=f"左扳机 LT: {state.lt:.2f}")
                rt_lbl.configure(text=f"右扳机 RT: {state.rt:.2f}")
                ls_lbl.configure(
                    text=f"左摇杆 L: ({state.lx:+.2f}, {state.ly:+.2f})")
                rs_lbl.configure(
                    text=f"右摇杆 R: ({state.rx:+.2f}, {state.ry:+.2f})")

                # 当前选定键的状态
                fire_pressed = bool(state.buttons.get(fire_btn, False))
                if fire_btn == "TRIGGER_RIGHT":
                    fire_pressed = state.rt > 0.5
                elif fire_btn == "TRIGGER_LEFT":
                    fire_pressed = state.lt > 0.5
                fire_status.configure(
                    text=f"🔫 开火键: {fire_disp}（{fire_btn}） — "
                         f"状态: {'✅ 按下' if fire_pressed else '未按'}",
                    foreground="#27AE60" if fire_pressed else "#000")

                ads_pressed = bool(state.buttons.get(ads_btn, False))
                if ads_btn == "TRIGGER_RIGHT":
                    ads_pressed = state.rt > 0.5
                elif ads_btn == "TRIGGER_LEFT":
                    ads_pressed = state.lt > 0.5
                ads_status.configure(
                    text=f"🎯 开镜键: {ads_disp}（{ads_btn}） — "
                         f"状态: {'✅ 按下' if ads_pressed else '未按'}",
                    foreground="#27AE60" if ads_pressed else "#000")

                if mark_status is not None:
                    mark_pressed = bool(state.buttons.get(mark_btn, False))
                    mark_status.configure(
                        text=f"⭐ 标记键: {mark_disp}（{mark_btn}） — "
                             f"状态: {'✅ 按下' if mark_pressed else '未按'}",
                        foreground="#27AE60" if mark_pressed else "#000")
            except tk.TclError:
                pass

        threading.Thread(target=_poll, daemon=True,
                         name="button-test-poll").start()

    def _on_perf_change(self, combo):
        """性能模式切换"""
        idx = combo.current()
        if 0 <= idx < len(self._perf_options):
            label, code = self._perf_options[idx]
            self.perf_profile_var.set(code)

    # ========== 控制器槽位管理 ==========
    def _scan_controllers(self):
        """[T-1.2] 异步扫描手柄并刷新槽位显示。

        用户手动点"扫描"按钮也可能因为 pygame.joystick.quit/init 而短暂卡顿，
        所以同样放后台线程跑，主线程只负责更新 UI。
        """
        if self.controller_mgr is None:
            if self._init_pending:
                # 初始化还在进行，按钮被点了：忽略，让初始化完成后自然刷新
                try:
                    self.scan_status_label.configure(
                        text="正在初始化手柄驱动，请稍候…",
                        foreground="#2980B9")
                except Exception:
                    pass
            return

        # 立刻给用户视觉反馈
        try:
            self.scan_status_label.configure(
                text="正在扫描…", foreground="#2980B9")
        except Exception:
            pass

        def _scan_worker():
            try:
                msg = self.controller_mgr.scan_and_assign()
                err = None
            except Exception as e:
                msg = ""
                err = str(e)
            self.after(0, self._on_scan_done, msg, err)

        threading.Thread(
            target=_scan_worker, daemon=True, name="controller-scan"
        ).start()

    def _on_scan_done(self, msg: str, err):
        """[T-1.2] 扫描完成回调，主线程刷新 UI。"""
        try:
            if err is not None:
                self.scan_status_label.configure(
                    text=f"扫描失败：{err}", foreground="#C0392B")
                return
            self.scan_status_label.configure(text=msg, foreground="#222")
            self._refresh_slot_display()
            self._refresh_button_combos_for_current_slot()
        except Exception as e:
            print(f"[警告] 扫描完成回调失败: {e}")

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

        # [T2.1] 更新标记键下拉
        if hasattr(self, "mark_combo"):
            old_mark = self.mark_button_var.get()
            self.mark_combo["values"] = display_labels
            if old_mark in logical_codes:
                self.mark_combo.current(logical_codes.index(old_mark))
            elif "BACK" in logical_codes:
                self.mark_combo.current(logical_codes.index("BACK"))
                self.mark_button_var.set("BACK")
            elif logical_codes:
                self.mark_combo.current(0)
                self.mark_button_var.set(logical_codes[0])

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
            if self._init_pending:
                messagebox.showinfo(
                    "请稍候",
                    "正在初始化手柄驱动，请等待几秒钟后再点击开始录制。")
            else:
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
        mark_btn = self.mark_button_var.get() if hasattr(self, "mark_button_var") else ""
        if fire_btn == ads_btn:
            messagebox.showerror("错误", "开火键和开镜键不能相同！")
            return
        # [T2.1] 标记键不能和开火/开镜冲突
        if mark_btn and mark_btn in (fire_btn, ads_btn):
            messagebox.showerror(
                "错误",
                f"标记键不能和开火键/开镜键相同！\n"
                f"当前：开火={fire_btn} 开镜={ads_btn} 标记={mark_btn}\n"
                f"请重新选一个不冲突的键作为标记键。")
            return

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = out_dir / f"stick_log_{timestamp_str}.csv"

        # [T1.1] 现在 meta_vars 里 sensor_type、rc_*_intensity、rc_*_direction
        # 已经是 code（"alps"/"hall"/"light"/"motion" 等），不再需要中文→code 映射。
        # 直接收集即可，但要正确处理 BooleanVar 等非字符串类型。
        metadata = {}
        for k, v in self.meta_vars.items():
            try:
                raw = v.get() if hasattr(v, "get") else v
            except Exception:
                raw = ""
            if isinstance(raw, bool):
                val = "true" if raw else "false"
            elif isinstance(raw, str):
                val = raw.strip()
            else:
                val = str(raw)
            metadata[k] = val if val else "unknown"

        # [T1.1] 单 RC 模式：把 rc_combined 的所有子字段同步到 rc_hipfire 和 rc_ads
        # 这样 analyzer.py 不用区分单/双 RC，老 CSV 兼容
        if metadata.get("rc_dual", "false") == "false":
            for sub in ("", "_range_min", "_range_max",
                        "_direction", "_intensity"):
                src_key = f"rc_combined{sub}"
                if src_key in metadata and metadata[src_key] not in ("unknown", ""):
                    metadata[f"rc_hipfire{sub}"] = metadata[src_key]
                    metadata[f"rc_ads{sub}"] = metadata[src_key]

        # [T0.3] 先做 3 秒静止校准，校准完成后才真正开始录制
        self._calibrate_then_record(
            output_path, metadata, fire_btn, ads_btn, mark_btn, ctrl)

    def _calibrate_then_record(self, output_path, metadata,
                                fire_btn, ads_btn, mark_btn, ctrl):
        """[T0.3] 录制前 3 秒静止校准，记录传感器本底噪声 + 回中虚位。

        校准期间打开一个 modal 弹窗显示倒计时，后台线程以 ~250Hz 收集
        松手状态下的 (rx, ry, lx, ly)，倒计时结束后算出每轴的 std 作为本底，
        关闭弹窗，启动真正的 StickRecorder。
        """
        # 录制按钮立刻禁用，防止用户重复点击
        self.start_btn["state"] = "disabled"

        dlg = tk.Toplevel(self)
        dlg.title("校准传感器本底")
        dlg.geometry("440x260")
        dlg.transient(self)
        dlg.resizable(False, False)
        # 禁止关闭（必须等校准结束）
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)
        # 居中显示
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 440) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 260) // 2
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

        ttk.Label(
            dlg,
            text="校准传感器本底",
            font=("", 14, "bold")).pack(pady=(20, 5))
        ttk.Label(
            dlg,
            text="请把双摇杆完全松手放好，保持 3 秒不动\n"
                 "（用于记录摇杆静止时的微小波动）",
            justify="center",
            foreground="#555").pack(pady=(0, 12))

        countdown_lbl = tk.Label(
            dlg, text="3", font=("", 48, "bold"), fg="#3498DB")
        countdown_lbl.pack(pady=4)

        live_lbl = ttk.Label(
            dlg, text="正在采集…", foreground="#888", font=("", 9))
        live_lbl.pack()

        # 后台线程收集摇杆数据
        samples = []         # list[(rx, ry, lx, ly)]
        stop_evt = threading.Event()
        err_holder = []

        def collect_worker():
            try:
                while not stop_evt.is_set():
                    try:
                        st = self.controller_mgr.read_state(ctrl)
                        samples.append((st.rx, st.ry, st.lx, st.ly))
                    except Exception as e:
                        err_holder.append(str(e))
                        break
                    time.sleep(0.004)  # ~250 Hz 采集
            except Exception as e:
                err_holder.append(str(e))

        threading.Thread(
            target=collect_worker, daemon=True,
            name="calibration-collect").start()

        # 倒计时 3 → 2 → 1 → "完成"
        def tick(remaining):
            if remaining > 0:
                countdown_lbl.configure(text=str(remaining), fg="#3498DB")
                # 实时显示当前采集到的样本数让用户安心
                live_lbl.configure(text=f"已采集 {len(samples)} 个样本…")
                self.after(1000, tick, remaining - 1)
            else:
                countdown_lbl.configure(text="完成", fg="#27AE60")
                live_lbl.configure(text=f"共采集 {len(samples)} 个样本")
                stop_evt.set()
                # 留 200ms 让收集线程退出，再做 finalize
                self.after(250, finalize)

        def finalize():
            # 计算每轴 std（纯 Python 实现，不依赖 numpy）
            def _std(arr):
                n = len(arr)
                if n < 2:
                    return 0.0
                mean = sum(arr) / n
                return (sum((x - mean) ** 2 for x in arr) / n) ** 0.5

            nfx = nfy = 0.0
            if err_holder:
                # 校准期间读手柄出错
                dlg.destroy()
                self.start_btn["state"] = "normal"
                messagebox.showerror(
                    "校准失败",
                    f"校准期间无法读取手柄状态：\n{err_holder[0]}\n\n"
                    "请重新点'开始录制'再试。")
                return
            if len(samples) >= 20:
                rxs = [s[0] for s in samples]
                rys = [s[1] for s in samples]
                nfx = _std(rxs)
                nfy = _std(rys)

            metadata["noise_floor_x"] = f"{nfx:.6f}"
            metadata["noise_floor_y"] = f"{nfy:.6f}"

            dlg.destroy()
            # 把校准结果记到 status_text，让用户看到
            self.status_text.delete(1.0, "end")
            self._log(f"✓ 校准完成：本底 X={nfx:.5f}  Y={nfy:.5f}  "
                      f"（采样 {len(samples)} 帧）")
            if max(nfx, nfy) > 0.01:
                self._log(
                    f"  [提示] 本底偏高，可能是回中虚位较大或摇杆有漂移迹象，"
                    f"分析报告会自动减去这部分。")
            self._actually_start_recording(
                output_path, metadata, fire_btn, ads_btn, mark_btn,
                ctrl, nfx, nfy)

        # 立即显示 3，开始倒计时
        tick(3)

    def _actually_start_recording(self, output_path, metadata,
                                   fire_btn, ads_btn, mark_btn,
                                   ctrl, nfx, nfy):
        """[T0.3] 校准完成后真正启动 Recorder。"""
        self.recorder = StickRecorder(
            output_path, metadata, fire_btn, ads_btn,
            controller_info=ctrl,
            controller_manager=self.controller_mgr,
            on_update=lambda s: self.after(0, self._on_recorder_update, s),
            on_done=lambda ok, info: self.after(0, self._on_recorder_done, ok, info),
            perf_profile=self.perf_profile_var.get(),
            noise_floor_x=nfx,
            noise_floor_y=nfy,
            mark_button=mark_btn or None)
        self.recorder.start()

        self.start_btn["state"] = "disabled"
        self.stop_btn["state"] = "normal"
        self.fire_combo["state"] = "disabled"
        self.ads_combo["state"] = "disabled"
        if hasattr(self, "mark_combo"):
            self.mark_combo["state"] = "disabled"
        self.perf_combo["state"] = "disabled"
        # 录制时禁用槽位切换
        for w in self.slot_widgets:
            w["radio"].configure(state="disabled")

        self._log(f"开始录制 → {output_path.name}")
        self._log(f"控制器: {ctrl.display_string()}")
        # 显示用户友好的按键标签
        if cb is not None:
            fire_label = cb.get_button_display_name(ctrl.layout, fire_btn)
            ads_label = cb.get_button_display_name(ctrl.layout, ads_btn)
            line = f"键位: 开火={fire_label}, 开镜={ads_label}"
            if mark_btn:
                mark_label = cb.get_button_display_name(ctrl.layout, mark_btn)
                line += f", 标记={mark_label}"
            self._log(line)
        else:
            line = f"键位: 开火={fire_btn}, 开镜={ads_btn}"
            if mark_btn:
                line += f", 标记={mark_btn}"
            self._log(line)
        if mark_btn:
            self._log(f"💡 录制时按一下'标记键'就标记当前为'压得好' —— "
                      f"事后报告会和算法评分对照")
        self._log("-" * 60)


    def _stop_record(self):
        if self.recorder:
            self.recorder.stop()
            self._log("正在停止...")

    def _on_recorder_update(self, s):
        bar_fire = "🔴 FIRE" if s["fire"] else "      "
        bar_ads = "🟢 ADS " if s["ads"] else "      "
        prefix = "状态 ▶"
        # [T0.2] 显示有效采样率（标称 + 有效）
        eff = s.get("effective_rate", s["rate"])
        if eff < 250:
            rate_str = f"采样率={s['rate']:.0f}Hz(有效{eff:.0f}⚠)"
        else:
            rate_str = f"采样率={s['rate']:.0f}Hz(有效{eff:.0f})"
        # [T2.1] 标记反馈：刚刚按下标记键时给一行提示，并维持总数
        mark_count = s.get("mark_count", 0)
        mark_str = f"⭐{mark_count}" if mark_count > 0 else ""
        if s.get("just_marked"):
            self._log(f"⭐ 已标记 第 {mark_count} 次（'压得好'）")
        cur = (f"{prefix} T={s['elapsed']:6.1f}s  {rate_str}  "
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
        if hasattr(self, "mark_combo"):
            self.mark_combo["state"] = "readonly"
        self.perf_combo["state"] = "readonly"
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
        # [T0.2] 有效采样率提示
        eff = info.get('effective_rate', info['rate'])
        dup = info.get('dup_ratio', 0.0)
        self._log(f"  有效采样率: {eff:.0f} Hz "
                  f"（重复帧 {dup*100:.1f}%）")
        if eff < 250:
            self._log(
                f"  [警告] 有效采样率较低，分析结果可能偏乐观。")
            self._log(
                f"         可能原因：手柄走蓝牙连接、底层 HID 报告率低、"
                f"USB 端口性能差。")
            self._log(f"         建议改用有线 USB 连接重测。")
        # [T0.3] 本底信息
        nfx = info.get('noise_floor_x', 0.0)
        nfy = info.get('noise_floor_y', 0.0)
        if nfx > 0 or nfy > 0:
            self._log(f"  传感器本底: X={nfx:.5f}  Y={nfy:.5f}（已记录到 CSV）")
        self._log(f"  开火帧: {info['fire_count']} "
                  f"({100*info['fire_count']/max(info['samples'],1):.1f}%)")
        self._log(f"  开镜帧: {info['ads_count']} "
                  f"({100*info['ads_count']/max(info['samples'],1):.1f}%)")
        # [T2.1] 标记总数
        marks = info.get('mark_count', 0)
        if marks > 0:
            self._log(f"  ⭐ 玩家标记: {marks} 次（'压得好'，分析时会和算法评分对照）")
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