"""
摇杆数据分析器 v2.1
================================
报告章节结构（v2.1）:
    一、开火前稳定度
    二、开火中稳定度
    三、过冲/反转统计 + 大幅过冲 vs 小抖动 细分（T3.3 新）
    四、行为分类 + 玩家直觉解释（T3.4 新）
    五、主导推杆区间（霍尔反死区补偿建议）
    六、自动化调参建议（针对性高/中/低段 + RC 澄清）
    七、腰射 vs 开镜 不对称分析（T3.1 新）
    八、走位 vs 站桩 模式对比（T3.2 新，1.3x 阈值放宽）
    九、今日状态一致性（CV 计算）
    十、玩家自评 vs 算法评分对照

变化：
- 自动检测所有"开火爆发"事件，无需外部击杀时间戳
- 兼容 v1.0 / v2.0 / v2.1 的 CSV 格式
- 完整爆发分析模式：分析每次开火从开始到结束的全过程

使用方法：
    # 自动分析所有开火爆发（推荐）
    python analyzer.py stick_log_xxx.csv

    # 仅分析最新 N 个事件
    python analyzer.py stick_log_xxx.csv --max_events 30

    # 想跳过太短的爆发（如误触）
    python analyzer.py stick_log_xxx.csv --min_duration 0.2

输出文件（与 CSV 同目录）：
    <basename>_report.txt        : 文字报告 + 调参建议
    <basename>_event_NN.png      : 每次开火事件的波形图
    <basename>_summary.png       : 总览统计图
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
# 关键：必须在 import pyplot 之前设置后端为 Agg（无 GUI）
# Agg 后端不会尝试创建窗口图标，避免 PyInstaller 打包后的 _tkinter.TclError
# 同时内存释放更彻底，性能更好（我们只需要保存图片，不需要交互式显示）
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 中文字体 - 自动检测系统可用中文字体
def _setup_chinese_font():
    """智能配置中文字体，兼容 PyInstaller 打包"""
    candidates = [
        "Microsoft YaHei", "Microsoft YaHei UI", "SimHei",
        "SimSun", "NSimSun", "FangSong", "KaiTi",
        "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = [name for name in candidates if name in available]
    if not chosen:
        # PyInstaller 打包后可能找不到，强制扫描 Windows 字体目录
        import os
        win_fonts_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
        if os.path.isdir(win_fonts_dir):
            for fn in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
                fp = os.path.join(win_fonts_dir, fn)
                if os.path.exists(fp):
                    try:
                        font_manager.fontManager.addfont(fp)
                    except Exception:
                        pass
            available = {f.name for f in font_manager.fontManager.ttflist}
            chosen = [name for name in candidates if name in available]
    chosen.append("DejaVu Sans")
    matplotlib.rcParams["font.sans-serif"] = chosen
    matplotlib.rcParams["axes.unicode_minus"] = False

_setup_chinese_font()


# ==================== 配置 ====================
WINDOW_BEFORE_S = 2.0       # 事件前观察窗口
WINDOW_AFTER_S = 1.5        # 事件后观察窗口（包含整个开火过程）
FIRE_GAP_THRESHOLD_S = 0.4  # 开火间隔超过此值视为不同爆发
DEFAULT_MIN_DURATION_S = 0.05
PRE_FIRE_STABILITY_MS = 100  # 开火前稳定度评估窗口
DURING_FIRE_STABILITY_MS = 300  # 开火中稳定度评估窗口（默认）
# ===============================================


# ==================== [T2.3] 武器射速感知 ====================
# 常见 FPS 武器的 RPM（rounds per minute）/ 每秒射速。
# 关键词匹配——只要用户填的武器名包含其中一个，就拿对应的 RPM。
# 数值是各游戏社区里相对成熟的近似值，主要用于分类（高/中/低射速）。
WEAPON_RPM = {
    # 高射速冲锋枪
    "r99": 1080, "r-99": 1080, "volt": 720, "alternator": 600,
    "car": 930, "p2020": 420,
    # 步枪 / 突击步枪
    "r301": 810, "r-301": 810, "flatline": 600, "havoc": 672,
    "hemlock": 930, "30-30": 192, "nemesis": 720,
    # 轻机枪
    "spitfire": 540, "rampage": 312, "devotion": 900, "lstar": 600,
    # 霰弹
    "eva": 138, "mastiff": 156, "peacekeeper": 102, "mozambique": 234,
    # 半自动 / DMR
    "g7": 240, "scout": 240, "wingman": 156, "bocek": 162,
    # 拉栓 / 单发
    "kraber": 30, "sentinel": 30, "longbow": 78, "triple": 96,
    # 通用类别词（兜底）
    "smg": 800, "冲锋枪": 800,
    "rifle": 600, "步枪": 600, "突击步枪": 600,
    "lmg": 600, "轻机枪": 600,
    "shotgun": 150, "霰弹": 150, "霰弹枪": 150,
    "dmr": 240, "marksman": 240,
    "sniper": 30, "狙击": 30, "狙击枪": 30, "拉栓": 30,
}


def detect_weapon_rpm(weapons_str: str) -> int:
    """从用户填的武器字段里推断 RPM。识别不到返回 0（按默认处理）。"""
    if not weapons_str:
        return 0
    s = weapons_str.lower()
    # 优先匹配长关键词（r-301 比 r3 更精确）
    for name in sorted(WEAPON_RPM.keys(), key=len, reverse=True):
        if name in s:
            return WEAPON_RPM[name]
    return 0


def rpm_to_during_window_ms(rpm: int) -> int:
    """根据武器射速选择 during_stability 窗口长度。

    - 高射速（>900 RPM）：200ms（够看到 3-4 发节奏）
    - 中等射速：300ms（默认）
    - 低射速（<150 RPM，霰弹/狙击/单发）：返回 0 表示跳过分析
    """
    if rpm <= 0:
        return DURING_FIRE_STABILITY_MS  # 不识别 → 默认
    if rpm > 900:
        return 200
    if rpm < 150:
        return 0  # 单发/拉栓武器没有"压枪过程"
    return DURING_FIRE_STABILITY_MS


def load_csv(path: Path) -> tuple:
    """加载 CSV 数据，同时解析头部元数据。返回 (df, metadata)

    [T0.2] metadata 里会自动追加：
        effective_rate     : 实际有效采样率（排除底层重发的重复帧）
        duplicate_ratio    : 重复帧占比（0.0 ~ 1.0）
        nominal_rate       : 标称采样率（来自 CSV 头）
    [T0.3] 也会读取：
        noise_floor_x / noise_floor_y : 录制前校准得到的传感器本底
    """
    print(f"[*] 加载 {path}...")

    # 先读取元数据行（以 # 开头）
    metadata = {}
    skip_rows = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                skip_rows += 1
                # 解析 # meta: key=value
                if "meta:" in line:
                    try:
                        kv = line.split("meta:", 1)[1].strip()
                        k, v = kv.split("=", 1)
                        metadata[k.strip()] = v.strip()
                    except ValueError:
                        pass
            else:
                break

    df = pd.read_csv(path, skiprows=skip_rows)
    df["elapsed_s"] = df["elapsed_s"].astype(float)

    # [T0.2] 检测重复帧并算有效采样率
    # 连续两行 (rx, ry, lx, ly) 完全相同 = 底层未更新（HID 重发）
    if len(df) > 1 and all(c in df.columns for c in ("rx", "ry", "lx", "ly")):
        sig = (df["rx"].round(6).astype(str) + "|"
               + df["ry"].round(6).astype(str) + "|"
               + df["lx"].round(6).astype(str) + "|"
               + df["ly"].round(6).astype(str))
        dup_mask = sig.eq(sig.shift())
        dup_count = int(dup_mask.sum())
        dup_ratio = dup_count / len(df)
        duration_s = float(df["elapsed_s"].iloc[-1] - df["elapsed_s"].iloc[0])
        nominal_rate = len(df) / max(duration_s, 1e-6)
        effective_rate = nominal_rate * (1.0 - dup_ratio)
        metadata["nominal_rate"] = f"{nominal_rate:.1f}"
        metadata["effective_rate"] = f"{effective_rate:.1f}"
        metadata["duplicate_ratio"] = f"{dup_ratio:.4f}"

    print(f"[√] 加载完成：{len(df)} 帧，时长 {df['elapsed_s'].iloc[-1]:.1f} 秒")
    if "effective_rate" in metadata:
        print(f"[√] 标称采样率 {metadata['nominal_rate']}Hz，"
              f"有效 {metadata['effective_rate']}Hz "
              f"（重复帧 {float(metadata['duplicate_ratio'])*100:.1f}%）")
    if metadata:
        print(f"[√] 元数据：{metadata}")
    return df, metadata


def get_stability_thresholds(metadata: dict) -> dict:
    """根据 RC 动感强度等级 + 传感器类型调整稳定度阈值。

    [T1.3] 传感器类型放宽倍数：
        - TMR：×1.00（已接近碳膜的延迟与线性度，主流 FPS 手柄出厂默认）
        - 碳膜 ALPS：×1.00（传统线性高、中心灵敏、零延迟）
        - 霍尔：×1.25（中心钝、圆周率差、斜角信号缺失、ms 级延迟，
                       非 FPS 主流方案）
        - 不确定：按 TMR 处理（当前主流，最贴近实际）

    注: TMR 算法已经成熟，跟碳膜差异很小，不需要再单独放宽阈值；
        霍尔仍有显著的中心钝化、回中虚位、磁场干扰问题。

    优先用 rc_ads_intensity 字段（动感强度等级），向后兼容老格式 rc_ads（数值）。
    """
    # 默认（中性 / 无 RC）
    thresholds = {
        "pre_stable": 0.04,
        "pre_unstable": 0.10,
        "during_stable": 0.04,
        "during_unstable": 0.08,
        "rev_good": 10,
        "rev_bad": 25,
        "intensity_label": "无 RC / 中性",
        "sensor_label": "碳膜 / 默认",
        "sensor_factor": 1.00,
    }

    # 强度等级 → 阈值放宽倍数（基于实测数据校准）
    intensity_factors = {
        "none": 1.00,        # 无 RC，标准阈值
        "antishake": 0.90,   # 防抖方向，可能稍微更稳
        "light": 1.10,       # 轻度动感
        "medium": 1.25,      # 中度动感
        "strong": 1.45,      # 强动感
        "extreme": 1.70,     # 拉满
    }
    intensity_labels = {
        "none": "无 RC 功能",
        "antishake": "防抖方向",
        "light": "轻度增抖",
        "medium": "中度增抖",
        "strong": "强增抖",
        "extreme": "极限增抖",
    }

    # 优先用新格式
    intensity = metadata.get("rc_ads_intensity", "").strip().lower()

    factor = None
    if intensity and intensity in intensity_factors:
        factor = intensity_factors[intensity]
        thresholds["intensity_label"] = intensity_labels[intensity]
    else:
        # 向后兼容：老格式 rc_ads 是数值
        # 但只对 ±10 范围的小数值生效，避免 -500 这种值算出离谱的放宽倍数
        try:
            rc_ads = float(metadata.get("rc_ads", "0"))
            if -15 <= rc_ads < 0:
                # 老格式且在合理范围内才用数值法
                factor = 1.0 + abs(rc_ads) * 0.05
                thresholds["intensity_label"] = f"老格式 RC={rc_ads}"
            elif rc_ads < -15:
                # 数值过大说明手柄 RC 范围不是 ±10，按"中度增抖"兜底
                factor = intensity_factors["medium"]
                thresholds["intensity_label"] = (
                    f"老格式 RC={rc_ads}（数值范围未知，按中度增抖处理）")
        except (ValueError, TypeError):
            pass

    if factor is not None and factor != 1.0:
        thresholds["pre_stable"] *= factor
        thresholds["pre_unstable"] *= factor
        thresholds["during_stable"] *= factor
        thresholds["during_unstable"] *= factor

    # [T1.3] 传感器类型放宽因子，叠在 RC 因子之上
    sensor_factors = {
        "alps": 1.00,     # 碳膜（传统）
        "tmr": 1.00,      # TMR（已接近碳膜，主流 FPS 默认）
        "hall": 1.25,     # 霍尔（中心钝，非 FPS 主流）
        "unknown": 1.00,  # 默认按 TMR / 碳膜（当前主流）
    }
    sensor_labels = {
        "alps": "碳膜 ALPS",
        "tmr": "TMR（隧道磁阻）",
        "hall": "霍尔",
        "unknown": "未知 / 默认（按主流处理）",
    }
    sensor = metadata.get("sensor_type", "unknown").strip().lower()
    sensor_factor = sensor_factors.get(sensor, 1.00)
    thresholds["sensor_label"] = sensor_labels.get(sensor, "未知")
    thresholds["sensor_factor"] = sensor_factor

    if sensor_factor != 1.0:
        thresholds["pre_stable"] *= sensor_factor
        thresholds["pre_unstable"] *= sensor_factor
        thresholds["during_stable"] *= sensor_factor
        thresholds["during_unstable"] *= sensor_factor

    return thresholds


def detect_fire_bursts(df: pd.DataFrame,
                       min_duration_s: float = DEFAULT_MIN_DURATION_S) -> list:
    """检测开火爆发段，返回 [(start_s, end_s), ...]"""
    fire_mask = df["fire"].astype(bool).values
    times = df["elapsed_s"].values

    bursts = []
    in_burst = False
    burst_start = 0.0
    last_fire_t = 0.0

    for t, f in zip(times, fire_mask):
        if f:
            if not in_burst:
                burst_start = t
                in_burst = True
            last_fire_t = t
        else:
            if in_burst and (t - last_fire_t) > FIRE_GAP_THRESHOLD_S:
                if last_fire_t - burst_start >= min_duration_s:
                    bursts.append((burst_start, last_fire_t))
                in_burst = False

    if in_burst and last_fire_t - burst_start >= min_duration_s:
        bursts.append((burst_start, last_fire_t))

    return bursts


def analyze_burst(df: pd.DataFrame, burst_start: float, burst_end: float,
                  noise_floor_x: float = 0.0,
                  noise_floor_y: float = 0.0,
                  weapon_rpm: int = 0) -> dict:
    """分析单个开火爆发

    [T0.3] noise_floor_x / noise_floor_y 是录制前校准得到的传感器本底标准差。
    pre_stability / during_stability 会减去本底（按平方相减再开方），
    保证报告里看到的"抖动"是真正手部+曲线引起的，不混入硬件本身的噪声。

    [T2.3] weapon_rpm 是武器射速，用于动态调整 during_stability 窗口长度：
        - >900 RPM（高射速冲锋枪）：200ms 窗口
        - 150-900 RPM（中等射速）：300ms 窗口（默认）
        - <150 RPM（霰弹/狙击/单发）：跳过 during 分析（NaN）
    """
    t_win_start = burst_start - WINDOW_BEFORE_S
    t_win_end = burst_end + WINDOW_AFTER_S
    win = df[(df["elapsed_s"] >= t_win_start)
             & (df["elapsed_s"] <= t_win_end)].copy()

    if len(win) < 10:
        return None

    # 相对时间：以开火起始为 0
    win["rel_t"] = win["elapsed_s"] - burst_start
    burst_duration = burst_end - burst_start

    def _denoise(std_x: float, std_y: float) -> float:
        """合成 X/Y 标准差，并减去本底（平方差再开方，因为方差可加）。

        clamp 到 0 以防本底估高了导致负数。
        """
        var_x = max(0.0, std_x ** 2 - noise_floor_x ** 2)
        var_y = max(0.0, std_y ** 2 - noise_floor_y ** 2)
        return float(np.sqrt(var_x + var_y))

    # ===== 指标 1：开火前 100ms 稳定度 =====
    pre_window = win[(win["rel_t"] >= -PRE_FIRE_STABILITY_MS / 1000.0)
                     & (win["rel_t"] <= 0)]
    if len(pre_window) > 5:
        pre_rx_std = pre_window["rx"].std()
        pre_ry_std = pre_window["ry"].std()
        pre_stability = _denoise(pre_rx_std, pre_ry_std)
    else:
        pre_stability = float("nan")

    # ===== 指标 2：开火中稳定度 =====
    # [T2.3] 根据武器射速动态调整窗口
    during_window_ms = rpm_to_during_window_ms(weapon_rpm)
    if during_window_ms <= 0:
        # 单发 / 拉栓武器：没有"压枪过程"概念，跳过分析
        during_stability = float("nan")
    else:
        fire_during = win[(win["rel_t"] >= 0)
                          & (win["rel_t"] <= during_window_ms / 1000.0)]
        if len(fire_during) > 5:
            # 减去趋势（拟合线性后取残差），因为压枪本身有持续位移
            rx_arr = fire_during["rx"].values
            ry_arr = fire_during["ry"].values
            x_idx = np.arange(len(rx_arr))
            if len(x_idx) > 2:
                rx_trend = np.polyfit(x_idx, rx_arr, 1)
                ry_trend = np.polyfit(x_idx, ry_arr, 1)
                rx_residual = rx_arr - np.polyval(rx_trend, x_idx)
                ry_residual = ry_arr - np.polyval(ry_trend, x_idx)
                during_stability = _denoise(rx_residual.std(),
                                             ry_residual.std())
            else:
                during_stability = _denoise(rx_arr.std(), ry_arr.std())
        else:
            during_stability = float("nan")

    # ===== 指标 3：推杆量分布 =====
    rx = win["rx"].values
    ry = win["ry"].values
    magnitude = np.sqrt(rx ** 2 + ry ** 2)
    avg_magnitude = float(np.mean(magnitude))
    max_magnitude = float(np.max(magnitude))

    # ===== 指标 4：开火爆发期间的方向反转 =====
    # 算法：先用 50ms 滑动均值平滑掉高频噪声，
    # 再统计速度（diff）符号变化，最后只保留振幅 > 0.05 的反转
    # [T3.3] 同时按反转幅度细分:
    #   - 大幅过冲（>0.15）: 单次甩过头，通常是高段曲线灵敏度过高
    #   - 小抖动（0.05-0.15）: 高频微小修正，通常是低段过激或硬件本底
    burst_data = win[(win["rel_t"] >= 0) & (win["rel_t"] <= burst_duration)]
    if len(burst_data) > 50:
        smooth_win = max(5, min(50, len(burst_data) // 5))

        def count_meaningful_reversals(arr):
            """返回 (total, large_overshoots, small_jitters, max_amplitude)"""
            kernel = np.ones(smooth_win) / smooth_win
            smoothed = np.convolve(arr, kernel, mode="valid")
            if len(smoothed) < 4:
                return 0, 0, 0, 0.0
            v = np.diff(smoothed)
            sign_change_idx = np.where(np.diff(np.sign(v)) != 0)[0]
            total = 0
            large = 0
            small = 0
            max_amp = 0.0
            last_extreme_val = smoothed[0]
            for idx in sign_change_idx:
                cur_extreme = smoothed[idx + 1]
                amp = abs(cur_extreme - last_extreme_val)
                if amp > 0.05:
                    total += 1
                    if amp > 0.15:
                        large += 1
                    else:
                        small += 1
                    if amp > max_amp:
                        max_amp = amp
                    last_extreme_val = cur_extreme
            return total, large, small, max_amp

        rx_t, rx_l, rx_s, rx_m = count_meaningful_reversals(
            burst_data["rx"].values)
        ry_t, ry_l, ry_s, ry_m = count_meaningful_reversals(
            burst_data["ry"].values)
        total_reversals = int(rx_t + ry_t)
        large_overshoots = int(rx_l + ry_l)
        small_jitters = int(rx_s + ry_s)
        max_reversal_amplitude = float(max(rx_m, ry_m))
    else:
        total_reversals = 0
        large_overshoots = 0
        small_jitters = 0
        max_reversal_amplitude = 0.0

    # ===== 指标 5：主导推杆区间（开火中和开火前 0.5 秒） =====
    relevant = win[(win["rel_t"] >= -0.5) & (win["rel_t"] <= burst_duration)]
    rel_mag = np.sqrt(relevant["rx"] ** 2 + relevant["ry"] ** 2).values
    nonzero = rel_mag[rel_mag > 0.05]
    if len(nonzero) > 10:
        dom_low = float(np.percentile(nonzero, 25)) * 100
        dom_high = float(np.percentile(nonzero, 75)) * 100
    else:
        dom_low = dom_high = 0

    # ===== 指标 6：是否在 ADS 状态下开火 =====
    fire_pre = win[(win["rel_t"] >= -0.05) & (win["rel_t"] <= 0)]
    is_ads = bool(fire_pre["ads"].astype(bool).any()) if len(fire_pre) > 0 else False

    # ===== 指标 7：左摇杆动作幅度（走位识别） =====
    lx_range = float(win["lx"].max() - win["lx"].min())
    ly_range = float(win["ly"].max() - win["ly"].min())
    is_moving = lx_range > 0.3 or ly_range > 0.3

    return {
        "burst_start": burst_start,
        "burst_end": burst_end,
        "duration": burst_duration,
        "data": win,
        "pre_stability": pre_stability,
        "during_stability": during_stability,
        "avg_magnitude": avg_magnitude,
        "max_magnitude": max_magnitude,
        "total_reversals": total_reversals,
        # [T3.3] 反转细分
        "large_overshoots": large_overshoots,        # 单次幅度 > 0.15
        "small_jitters": small_jitters,              # 0.05 < 幅度 <= 0.15
        "max_reversal_amplitude": max_reversal_amplitude,
        "dominant_input_low": dom_low,
        "dominant_input_high": dom_high,
        "is_ads": is_ads,
        "is_moving": is_moving,
        "lx_range": lx_range,
        "ly_range": ly_range,
        # [T2.3] 武器射速感知信息
        "weapon_rpm": weapon_rpm,
        "during_window_ms": during_window_ms,
    }


def classify_burst(m: dict) -> str:
    """根据指标分类射击行为
    [T3.4] 档位从粗到细: 完美稳定 ⭐ > 稳定射击 ✓ > 接近稳定 > 中等稳定 > 严重问题 ⚠
    """
    if m is None:
        return "数据不足"
    pre = m["pre_stability"]
    dur = m["during_stability"]
    rev = m["total_reversals"]
    avg_mag = m.get("avg_magnitude", 0.0)

    # 严重问题：任一指标爆表（最高优先级）
    if not np.isnan(pre) and pre > 0.10:
        return "开火前抖动 ⚠"
    if not np.isnan(dur) and dur > 0.08:
        return "开火中抖动 ⚠"
    if rev > 25:
        return "频繁过冲 ⚠"

    # 微调跟枪：推杆量极小（跟"稳定"是不同维度）
    if avg_mag < 0.10:
        return "微调跟枪"

    # 稳定档位（按 pre + rev 综合细分）
    if not np.isnan(pre):
        if pre < 0.025 and rev < 5:
            return "完美稳定 ⭐"
        if pre < 0.04 and rev < 10:
            return "稳定射击 ✓"
        if pre < 0.06 and rev < 15:
            return "接近稳定"

    return "中等稳定"


# [T3.4] 分类对应的玩家直觉解释（按从好到差排列）
CLASSIFICATION_EXPLANATIONS = {
    "完美稳定 ⭐": "教科书级压枪，准星几乎纹丝不动",
    "稳定射击 ✓": "理想状态，压枪稳、命中率高",
    "接近稳定": "基本稳但有微调，实战可用",
    "中等稳定": "能打中但不稳，需要练习",
    "微调跟枪": "远距离精修目标，推杆量很小",
    "开火前抖动 ⚠": "瞄准时手抖，准星没停在敌人身上（曲线低段问题/瞄太久/紧张）",
    "开火中抖动 ⚠": "后坐力没压住，曲线匹配差（中段过陡）",
    "频繁过冲 ⚠": "准星反复修正越过目标，斜率太高",
    "数据不足": "burst 时长太短或采样不足",
}


def plot_burst(m: dict, output_path: Path, title: str):
    """单个爆发的波形图"""
    win = m["data"]
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

    # 子图 1：右摇杆 X/Y
    axes[0].plot(win["rel_t"], win["rx"], label="RX 水平",
                 color="#E74C3C", linewidth=1.2)
    axes[0].plot(win["rel_t"], win["ry"], label="RY 垂直",
                 color="#3498DB", linewidth=1.2)
    axes[0].axvline(0, color="red", linestyle="--", alpha=0.7, label="开火起始")
    axes[0].axvline(m["duration"], color="orange", linestyle="--",
                    alpha=0.7, label="开火结束")
    axes[0].axhline(0, color="gray", linestyle=":", alpha=0.3)
    axes[0].axvspan(0, m["duration"], alpha=0.08, color="red",
                    label="开火持续期")
    axes[0].set_ylabel("右摇杆值")
    axes[0].set_title(title)
    axes[0].legend(loc="upper right", fontsize=8, framealpha=0.85)
    axes[0].grid(True, alpha=0.3)
    axes[0].set_ylim(-1.05, 1.05)

    info = (
        f"开火前 100ms 稳定度: {m['pre_stability']:.4f}\n"
        f"开火中 300ms 稳定度: {m['during_stability']:.4f}\n"
        f"开火期方向反转: {m['total_reversals']} 次\n"
        f"主导推杆区间: X={m['dominant_input_low']:.0f}–"
        f"{m['dominant_input_high']:.0f}\n"
        f"开镜: {'是' if m['is_ads'] else '否'} | "
        f"走位: {'是' if m['is_moving'] else '否'}"
    )
    axes[0].text(0.02, 0.97, info, transform=axes[0].transAxes,
                 verticalalignment="top", fontsize=8,
                 bbox=dict(boxstyle="round,pad=0.4",
                           facecolor="white", edgecolor="gray", alpha=0.85))

    # 子图 2：推杆量
    magnitude = np.sqrt(win["rx"] ** 2 + win["ry"] ** 2)
    axes[1].plot(win["rel_t"], magnitude, color="#9B59B6", linewidth=1.5)
    axes[1].axvline(0, color="red", linestyle="--", alpha=0.7)
    axes[1].axvline(m["duration"], color="orange", linestyle="--", alpha=0.7)
    axes[1].axvspan(0, m["duration"], alpha=0.08, color="red")
    axes[1].fill_between(win["rel_t"], 0, magnitude, alpha=0.2, color="#9B59B6")
    axes[1].set_ylabel("右摇杆推杆量 |R|")
    axes[1].grid(True, alpha=0.3)
    axes[1].set_ylim(0, 1.05)

    # 子图 3：开火/开镜状态 + 左摇杆
    axes[2].plot(win["rel_t"], win["lx"], label="LX (左右走位)",
                 color="#16A085", linewidth=1.0, alpha=0.8)
    axes[2].plot(win["rel_t"], win["ly"], label="LY (前后走位)",
                 color="#F39C12", linewidth=1.0, alpha=0.8)
    axes[2].fill_between(win["rel_t"], -0.05,
                         win["fire"].astype(float) * 1.05,
                         alpha=0.25, color="red", label="开火中")
    axes[2].fill_between(win["rel_t"], -0.05,
                         win["ads"].astype(float) * (-1.05),
                         alpha=0.25, color="green", label="开镜中")
    axes[2].axvline(0, color="red", linestyle="--", alpha=0.7)
    axes[2].axvline(m["duration"], color="orange", linestyle="--", alpha=0.7)
    axes[2].set_ylabel("左摇杆 / 状态")
    axes[2].set_xlabel("相对开火时间 (秒)")
    axes[2].legend(loc="upper right", fontsize=8, framealpha=0.85, ncol=2)
    axes[2].grid(True, alpha=0.3)
    axes[2].set_ylim(-1.1, 1.1)

    plt.tight_layout()
    plt.savefig(output_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    # 显式释放 - 修复 v2.0 内存泄漏
    del fig, axes
    import gc
    gc.collect()


def plot_summary(events: list, output_path: Path):
    """统计总览

    [T-1.1 紧急修复] 此前 pre_stabs / dur_stabs 用 if not np.isnan() 单独过滤，
    导致和 mags / revs 长度不一致，scatter 时报 "x and y must be the same size"。
    现在改为：用一次循环同步过滤所有指标，保证四个列表索引对齐。
    """
    metrics_list = [e["metrics"] for e in events if e["metrics"] is not None]
    if not metrics_list:
        return

    # 同步过滤：四个列表索引一一对应
    valid_metrics = [
        m for m in metrics_list
        if not np.isnan(m["pre_stability"])
        and not np.isnan(m["during_stability"])
    ]
    pre_stabs = [m["pre_stability"] for m in valid_metrics]
    dur_stabs = [m["during_stability"] for m in valid_metrics]
    revs = [m["total_reversals"] for m in valid_metrics]
    mags = [m["avg_magnitude"] for m in valid_metrics]
    centers = [(m["dominant_input_low"] + m["dominant_input_high"]) / 2
               for m in valid_metrics]

    if not valid_metrics:
        # 全部事件都缺关键指标，没法画散点图
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    if pre_stabs:
        axes[0, 0].hist(pre_stabs, bins=20, color="#3498DB",
                        alpha=0.7, edgecolor="black")
        axes[0, 0].axvline(0.04, color="green", linestyle="--", label="稳定 (<0.04)")
        axes[0, 0].axvline(0.10, color="red", linestyle="--", label="抖动 (>0.10)")
    axes[0, 0].set_xlabel("开火前 100ms 稳定度")
    axes[0, 0].set_ylabel("事件数")
    axes[0, 0].set_title("开火前稳定度分布（瞄准是否稳）")
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=0.3)

    if dur_stabs:
        axes[0, 1].hist(dur_stabs, bins=20, color="#E67E22",
                        alpha=0.7, edgecolor="black")
        axes[0, 1].axvline(0.04, color="green", linestyle="--", label="稳定 (<0.04)")
        axes[0, 1].axvline(0.08, color="red", linestyle="--", label="抖动 (>0.08)")
    axes[0, 1].set_xlabel("开火中 300ms 稳定度（去趋势）")
    axes[0, 1].set_ylabel("事件数")
    axes[0, 1].set_title("开火中稳定度分布（压枪是否稳）")
    axes[0, 1].legend()
    axes[0, 1].grid(True, alpha=0.3)

    # 散点图：mags 和 pre_stabs 现在长度一定相等
    colors = ["#27AE60" if m["is_ads"] else "#E67E22" for m in valid_metrics]
    axes[1, 0].scatter(mags, pre_stabs, c=colors, alpha=0.7, s=50)
    axes[1, 0].set_xlabel("平均推杆量")
    axes[1, 0].set_ylabel("开火前稳定度")
    axes[1, 0].set_title("推杆量 vs 稳定度（绿=开镜，橙=腰射）")
    axes[1, 0].grid(True, alpha=0.3)

    axes[1, 1].hist(centers, bins=20, color="#9B59B6",
                    alpha=0.7, edgecolor="black")
    axes[1, 1].set_xlabel("主导推杆量（百分比 0-100）")
    axes[1, 1].set_ylabel("事件数")
    axes[1, 1].set_title("你最常用的推杆区间（曲线调参核心依据）")
    axes[1, 1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    # 显式释放 - 修复 v2.0 内存泄漏
    del fig, axes
    import gc
    gc.collect()


def generate_report(events: list, csv_path: Path,
                    metadata: dict, thresholds: dict) -> str:
    """生成文字报告"""
    metrics_list = [e["metrics"] for e in events if e["metrics"] is not None]
    if not metrics_list:
        return "[!] 没有可分析的事件"

    n = len(metrics_list)
    pre_stabs = [m["pre_stability"] for m in metrics_list
                 if not np.isnan(m["pre_stability"])]
    dur_stabs = [m["during_stability"] for m in metrics_list
                 if not np.isnan(m["during_stability"])]
    revs = [m["total_reversals"] for m in metrics_list]
    mags = [m["avg_magnitude"] for m in metrics_list]
    durations = [m["duration"] for m in metrics_list]
    ads_count = sum(1 for m in metrics_list if m["is_ads"])
    moving_count = sum(1 for m in metrics_list if m["is_moving"])

    classifications = [classify_burst(m) for m in metrics_list]
    class_count = {}
    for c in classifications:
        class_count[c] = class_count.get(c, 0) + 1

    all_dom = [(m["dominant_input_low"] + m["dominant_input_high"]) / 2
               for m in metrics_list]
    common_low = float(np.percentile(all_dom, 25))
    common_high = float(np.percentile(all_dom, 75))

    L = []
    L.append("=" * 70)
    L.append("           摇杆射击行为分析报告")
    L.append("=" * 70)
    L.append(f"源文件: {csv_path.name}")

    # 元数据展示
    if metadata:
        L.append("")
        L.append("配置元数据:")
        if "curve" in metadata:
            L.append(f"  曲线版本: {metadata['curve']}")
        if "rc_hipfire" in metadata:
            hip_int = metadata.get("rc_hipfire_intensity", "")
            int_str = f"（{hip_int}）" if hip_int and hip_int != "unknown" else ""
            L.append(f"  腰射 RC: {metadata['rc_hipfire']}{int_str}")
        if "rc_ads" in metadata:
            ads_int = metadata.get("rc_ads_intensity", "")
            int_str = f"（{ads_int}）" if ads_int and ads_int != "unknown" else ""
            L.append(f"  开镜 RC: {metadata['rc_ads']}{int_str}")
        if "weapons" in metadata:
            L.append(f"  使用武器: {metadata['weapons']}")
        if "scene" in metadata:
            L.append(f"  场景: {metadata['scene']}")

        # 显示阈值调整说明
        intensity_label = thresholds.get("intensity_label", "")
        if intensity_label and intensity_label not in ("无 RC / 中性", "无 RC 功能"):
            base = 0.04
            adjusted = thresholds["pre_stable"]
            pct = (adjusted / base - 1) * 100
            L.append(f"  [注] RC 强度: {intensity_label}，"
                     f"稳定度阈值已自动调整 {pct:+.0f}%")

        # [T1.3] 传感器类型说明
        sensor_label = thresholds.get("sensor_label", "")
        sensor_factor = thresholds.get("sensor_factor", 1.0)
        if sensor_label:
            if sensor_factor != 1.0:
                pct = (sensor_factor - 1.0) * 100
                L.append(f"  [注] 摇杆传感器: {sensor_label}，"
                         f"阈值额外放宽 {pct:+.0f}%（中心钝化补偿）")
            else:
                L.append(f"  摇杆传感器: {sensor_label}")

        # [T0.2] 采样率诊断
        if "effective_rate" in metadata:
            try:
                eff = float(metadata["effective_rate"])
                nom = float(metadata.get("nominal_rate", "0") or 0)
                dup = float(metadata.get("duplicate_ratio", "0") or 0)
                rate_line = (f"  采样率: 标称 {nom:.0f} Hz，"
                             f"实际有效 {eff:.0f} Hz "
                             f"（重复帧 {dup*100:.1f}%）")
                L.append(rate_line)

                # 对比用户填的回报率
                try:
                    polling = float(metadata.get("polling_rate", "0") or 0)
                except (ValueError, TypeError):
                    polling = 0
                if polling > 0:
                    L.append(f"  手柄回报率（用户填写）: {polling:.0f} Hz")

                # 软件采样上限由 pygame/SDL 协议决定（通常 500-1000Hz），
                # 与手柄回报率无关 —— 即使手柄是 1000/4000/8000Hz，
                # 软件这层也只能拿到 SDL 协议范围内的数据。
                # 这对压枪分析（关注 5-50Hz 频段）完全够用。
                if eff >= 400:
                    L.append("  [说明] 软件采样上限由 pygame/SDL 协议决定（~500-1000Hz）。"
                             "对压枪分析够用，")
                    L.append("         不必担心手柄回报率高（1000-8000Hz）"
                             "的差异 —— SDL 这层无法区分。")
                elif eff >= 200:
                    L.append("  [提示] 实际采样率一般。SDL 协议正常上限是 500-1000Hz，")
                    L.append("         你这次只到 {:.0f}Hz，可能是后台占用了"
                             "CPU 或蓝牙连接不稳。".format(eff))
                    L.append("         分析结果基本可信，但建议下次有线连接重测。")
                else:
                    L.append("  [警告] 实际有效采样率过低（<200Hz），"
                             "稳定度数值可能偏乐观。")
                    L.append("         可能是蓝牙断连、CPU 占用过高、"
                             "或第三方驱动限频。")
                    L.append("         建议改用有线 USB 直连 + 关闭其他占用程序后重测。")
            except (ValueError, TypeError):
                pass

        # [T0.3] 硬件本底校准说明
        try:
            nfx = float(metadata.get("noise_floor_x", "0") or 0)
            nfy = float(metadata.get("noise_floor_y", "0") or 0)
        except (ValueError, TypeError):
            nfx = nfy = 0.0
        if nfx > 0 or nfy > 0:
            L.append(f"  传感器本底（已扣除）: X={nfx:.5f}  Y={nfy:.5f}")
            if max(nfx, nfy) > 0.015:
                L.append("  [提示] 本底偏高，可能是回中虚位较大、摇杆有"
                         "漂移迹象，或周围磁场干扰（霍尔摇杆较常见）。")

        # [T2.3] 武器射速识别
        weapon_rpm = 0
        if metrics_list:
            weapon_rpm = metrics_list[0].get("weapon_rpm", 0)
        if weapon_rpm > 0:
            window_ms = rpm_to_during_window_ms(weapon_rpm)
            if window_ms <= 0:
                L.append(f"  武器射速: {weapon_rpm} RPM "
                         f"（单发/拉栓武器 → 已跳过开火中稳定度分析）")
            else:
                L.append(f"  武器射速: {weapon_rpm} RPM "
                         f"（开火中分析窗口已自动设为 {window_ms}ms）")

        L.append("")

    L.append(f"分析事件总数: {n}")
    L.append(f"  - 开镜射击: {ads_count} ({100*ads_count/n:.1f}%)")
    L.append(f"  - 腰射射击: {n - ads_count} ({100*(n-ads_count)/n:.1f}%)")
    L.append(f"  - 走位射击: {moving_count} ({100*moving_count/n:.1f}%)")
    L.append(f"开火持续: 平均 {np.mean(durations):.2f}s，"
             f"中位 {np.median(durations):.2f}s")
    L.append("")

    L.append("-" * 70)
    L.append(" 一、开火前稳定度（瞄准是否稳停在敌人身上）")
    L.append("-" * 70)
    if pre_stabs:
        L.append(f"  平均: {np.mean(pre_stabs):.4f}  中位: {np.median(pre_stabs):.4f}")
        L.append(f"  最差: {np.max(pre_stabs):.4f}  最好: {np.min(pre_stabs):.4f}")
        L.append(f"  评级（已根据RC调整）: <{thresholds['pre_stable']:.3f}=稳，"
                 f"{thresholds['pre_stable']:.3f}-{thresholds['pre_unstable']:.3f}=一般，"
                 f">{thresholds['pre_unstable']:.3f}=抖")
    L.append("")

    L.append("-" * 70)
    L.append(" 二、开火中稳定度（压枪是否稳）")
    L.append("-" * 70)
    if dur_stabs:
        L.append(f"  平均: {np.mean(dur_stabs):.4f}  中位: {np.median(dur_stabs):.4f}")
        L.append(f"  最差: {np.max(dur_stabs):.4f}  最好: {np.min(dur_stabs):.4f}")
        L.append(f"  评级（已根据RC调整）: <{thresholds['during_stable']:.3f}=稳，"
                 f"{thresholds['during_stable']:.3f}-{thresholds['during_unstable']:.3f}=一般，"
                 f">{thresholds['during_unstable']:.3f}=抖")
    L.append("")

    L.append("-" * 70)
    L.append(" 三、过冲/反转统计")
    L.append("-" * 70)
    L.append(f"  平均反转次数: {np.mean(revs):.1f} 次/事件")
    L.append(f"  中位数: {np.median(revs):.0f} 次/事件")
    L.append(f"  最高: {np.max(revs):.0f} 次")
    L.append(f"  评级: <10=好，10-25=一般，>25=过冲严重")

    # [T3.3] 反转细分类型：大幅过冲（甩过头）vs 小抖动（手抖/曲线噪声）
    large_list = [m.get("large_overshoots", 0) for m in metrics_list]
    small_list = [m.get("small_jitters", 0) for m in metrics_list]
    max_amp_list = [m.get("max_reversal_amplitude", 0.0) for m in metrics_list]
    avg_large = float(np.mean(large_list)) if large_list else 0.0
    avg_small = float(np.mean(small_list)) if small_list else 0.0
    max_amp = float(np.max(max_amp_list)) if max_amp_list else 0.0

    L.append("")
    L.append(f"  细分类型（反转幅度分布）:")
    L.append(f"    大幅过冲（>0.15，甩过头）: 平均 {avg_large:.1f} 次/事件")
    L.append(f"    小抖动（0.05-0.15，微修正）: 平均 {avg_small:.1f} 次/事件")
    L.append(f"    单次最大反转幅度: {max_amp:.3f}")

    # 类型识别 + 倾向性提示
    total_classified = avg_large + avg_small
    if total_classified > 0.5:  # 至少有一些反转才下结论
        large_ratio = avg_large / total_classified
        if large_ratio > 0.50:
            L.append(f"    → 主要是大幅过冲（{large_ratio*100:.0f}%）：")
            L.append(f"      高段曲线斜率过高，准星甩过目标后回拉修正")
        elif large_ratio < 0.20:
            L.append(f"    → 主要是小抖动（{(1-large_ratio)*100:.0f}%）：")
            L.append(f"      可能原因: 低段曲线斜率过陡 / 硬件本底偏高 / 手部微抖")
            L.append(f"      / 高强度 RC 增抖（RC 越强摇杆越钝、内置噪声越大）")
            L.append("      （和『开火前抖动』成因接近，看二者是否同时高）")
        else:
            L.append(f"    → 大幅过冲与小抖动并存，需同时检查曲线高低段")
    L.append("")

    L.append("-" * 70)
    L.append(" 四、行为分类")
    L.append("-" * 70)
    for cls, cnt in sorted(class_count.items(), key=lambda x: -x[1]):
        pct = 100 * cnt / n
        bar = "█" * int(pct / 2)
        L.append(f"  {cls:18} | {cnt:4} 次 ({pct:5.1f}%) {bar}")

    # [T3.4] 列出本次出现的分类的玩家直觉解释（按从好到差顺序）
    seen_classes = set(class_count.keys())
    L.append("")
    L.append("  分类说明（玩家直觉对照）:")
    for cls, exp in CLASSIFICATION_EXPLANATIONS.items():
        if cls in seen_classes:
            L.append(f"    {cls:14} = {exp}")
    L.append("")

    L.append("-" * 70)
    L.append(" 五、关键发现：你的主导推杆区间")
    L.append("-" * 70)
    L.append(f"  你开火时最常用的推杆量: X={common_low:.0f}–{common_high:.0f}")
    L.append("  → 曲线这段的设计对你影响最大")

    # [T1.4] 霍尔玩家若主导区间在中心钝化区，自动给反死区补偿建议
    # （TMR 已接近碳膜响应，不再需要这条建议）
    sensor = metadata.get("sensor_type", "unknown").strip().lower()
    if sensor == "hall" and common_low < 10:
        L.append("")
        L.append(f"  [⚠ 重要] 你是霍尔摇杆且主导推杆区间在 X<10 中心钝化区。")
        L.append(f"        霍尔摇杆中心响应钝（圆周率差、斜角信号缺失），")
        L.append(f"        建议曲线第一个非零点设在 X=4, Y=20 附近做反死区补偿。")
        L.append(f"        这是 TheFinals 玩家社区在 ALC 拟合实验中验证的经验值。")

    L.append("")

    L.append("-" * 70)
    L.append(" 六、自动化调参建议")
    L.append("-" * 70)

    avg_pre = np.mean(pre_stabs) if pre_stabs else 0
    avg_dur = np.mean(dur_stabs) if dur_stabs else 0
    avg_rev = np.mean(revs)

    issues = []
    if avg_pre > thresholds["pre_unstable"]:
        issues.append("瞄准抖动")
        L.append(f"  [警] 开火前抖动严重（{avg_pre:.4f} > {thresholds['pre_unstable']:.3f}）：")
        L.append(f"     瞄准时准星无法稳定停在敌人身上")
        L.append(f"     原因: X={common_low:.0f}–{common_high:.0f} 段曲线斜率过高")
        L.append(f"     → 把这段对应节点的 Y 值降低 1.5-2.5 单位")
    elif avg_pre > thresholds["pre_stable"] * 1.5:
        L.append(f"  [提示] 瞄准稳定度中等（{avg_pre:.4f}）")
        L.append(f"     → X={common_low:.0f}–{common_high:.0f} 段 Y 值降低 0.5-1 单位")
    elif pre_stabs:
        L.append(f"  [√] 瞄准稳定度良好（{avg_pre:.4f} < {thresholds['pre_stable']:.3f}）")
    L.append("")

    if avg_dur > thresholds["during_unstable"]:
        issues.append("压枪抖动")
        L.append(f"  [警] 开火中压枪抖动（{avg_dur:.4f} > {thresholds['during_unstable']:.3f}）：")
        L.append(f"     压枪过程不稳，子弹散布严重")
        L.append(f"     原因: 压枪时落在的推杆区间斜率过高")
        L.append(f"     → 检查 ADS 曲线 X={common_low:.0f}–{common_high:.0f} 段是否过陡")
    elif avg_dur > thresholds["during_stable"] * 1.5:
        L.append(f"  [提示] 压枪稳定度中等（{avg_dur:.4f}）")
    elif dur_stabs:
        L.append(f"  [√] 压枪稳定度良好（{avg_dur:.4f}）")
    L.append("")

    # [T3.3] 过冲建议根据细分类型给针对性方案
    _total_cl = avg_large + avg_small
    _large_ratio = (avg_large / _total_cl) if _total_cl > 0.5 else 0.5

    if avg_rev > thresholds["rev_bad"]:
        issues.append("过冲")
        L.append(f"  [警] 过冲严重（{avg_rev:.1f} 次/事件）：")
        if _large_ratio > 0.50:
            # 主要是大幅过冲 → 高段斜率问题（跟 RC 无关，RC 反而是钝化）
            L.append(f"     类型: 大幅过冲为主"
                     f"（{avg_large:.1f}/事件 > 0.15 幅度）")
            L.append(f"     原因: 高段曲线斜率过高，准星甩过目标后回拉")
            L.append(f"     → 降低高段（X=70-100）输出，"
                     f"节点 6、7 的 Y 值降低 1.5-2 单位")
            L.append(f"     注: 大幅过冲跟 RC 无关 —— RC 增抖是钝化操作，"
                     f"不会让你甩过头")
        elif _large_ratio < 0.20:
            # 主要是小抖动 → 低段过激 / 本底 / RC 噪声
            L.append(f"     类型: 高频小抖动为主"
                     f"（{avg_small:.1f}/事件 在 0.05-0.15 幅度）")
            L.append(f"     可能原因: 低段曲线斜率过陡 / 硬件本底偏高 / "
                     f"高强度 RC 增抖")
            L.append(f"     → 降低低段（X=10-30）输出，"
                     f"节点 1、2 的 Y 值降低 1-1.5 单位")
            L.append(f"     → 也检查死区是否设过小（中心钝化区噪声会被放大），"
                     f"以及当前 RC 强度是否过高")
        else:
            # 混合
            L.append(f"     类型: 大幅过冲（{avg_large:.1f}/事件）"
                     f"+ 小抖动（{avg_small:.1f}/事件）并存")
            L.append(f"     → 同时降低低段（X=10-30）1 单位"
                     f"和高段（X=70-100）1.5 单位")
    elif avg_rev > 12:
        L.append(f"  [提示] 有一定过冲（{avg_rev:.1f} 次/事件）")
        if _large_ratio > 0.50:
            L.append(f"     倾向大幅过冲（{avg_large:.1f}/事件）"
                     f"→ 适度降低高段斜率")
        elif _large_ratio < 0.20:
            L.append(f"     倾向小抖动（{avg_small:.1f}/事件）"
                     f"→ 适度降低低段斜率")
        else:
            L.append(f"     可适度降低中段斜率")
    else:
        L.append(f"  [√] 过冲控制良好（{avg_rev:.1f} 次/事件）")
    L.append("")

    # （腰射 vs 开镜 详细不对称分析见 第七节）
    # （走位 vs 站桩 详细对比见 第八节）

    if not issues:
        L.append("  [总结] 所有指标良好，曲线匹配度很高")
    else:
        L.append(f"  [总结] 主要问题: {', '.join(issues)}")
    L.append("")

    # ===== [T3.1] 腰射 vs 开镜 模式不对称分析 =====
    # 给两种模式各算一套独立等级，差异 > 30% 时给针对性曲线建议
    if ads_count > 0 and ads_count < n:
        L.append("-" * 70)
        L.append(" 七、腰射 vs 开镜 模式不对称分析")
        L.append("-" * 70)

        ads_only = [m for m in metrics_list if m["is_ads"]]
        hip_only = [m for m in metrics_list if not m["is_ads"]]

        def _safe_avg(metrics, key):
            vals = [m[key] for m in metrics
                    if m.get(key) is not None
                    and not (isinstance(m.get(key), float) and np.isnan(m[key]))]
            return float(np.mean(vals)) if vals else float("nan")

        hip_pre_v = _safe_avg(hip_only, "pre_stability")
        hip_dur_v = _safe_avg(hip_only, "during_stability")
        hip_rev_v = _safe_avg(hip_only, "total_reversals")
        hip_dlow = _safe_avg(hip_only, "dominant_input_low")
        hip_dhigh = _safe_avg(hip_only, "dominant_input_high")

        ads_pre_v = _safe_avg(ads_only, "pre_stability")
        ads_dur_v = _safe_avg(ads_only, "during_stability")
        ads_rev_v = _safe_avg(ads_only, "total_reversals")
        ads_dlow = _safe_avg(ads_only, "dominant_input_low")
        ads_dhigh = _safe_avg(ads_only, "dominant_input_high")

        # 各自模式专属阈值（腰射用 rc_hipfire_intensity，开镜复用主阈值）
        hip_md = dict(metadata)
        hip_intensity = (metadata.get("rc_hipfire_intensity", "")
                         or "").strip()
        if hip_intensity:
            hip_md["rc_ads_intensity"] = hip_intensity
            hip_md.pop("rc_ads", None)  # 防止老格式数值字段冲突
        hip_th = get_stability_thresholds(hip_md)
        ads_th = thresholds  # 主阈值已基于 rc_ads_intensity

        def _grade_stab(val, t_stable, t_unstable):
            if np.isnan(val):
                return "—"
            if val <= t_stable:
                return "稳"
            if val <= t_unstable:
                return "一般"
            return "抖"

        def _grade_rev(val, good, bad):
            if np.isnan(val):
                return "—"
            if val <= good:
                return "好"
            if val <= bad:
                return "一般"
            return "过冲"

        def _diff_pct(a, b):
            """a 相对 b 的差异百分比；正数 = a 更差（指标本身越大越差）"""
            if np.isnan(a) or np.isnan(b) or b <= 0:
                return float("nan"), "—"
            d = (a - b) / b * 100
            return d, f"{d:+.0f}%"

        n_hip = len(hip_only)
        n_ads = len(ads_only)
        L.append(f"  样本量: 腰射 N={n_hip}, 开镜 N={n_ads}")
        if min(n_hip, n_ads) < 3:
            L.append("  [提示] 单边样本量较少（<3），不对称结论仅供参考")

        # RC 强度对比（仅当腰射/开镜分别填写时显示）
        hip_label = hip_th.get("intensity_label", "")
        ads_label = ads_th.get("intensity_label", "")
        if hip_label and ads_label and hip_label != ads_label:
            L.append(f"  RC 强度: 腰射={hip_label}，开镜={ads_label}"
                     f"（已分别校准阈值）")

        L.append("")
        L.append("  指标         | 腰射             | 开镜             | 差异")
        L.append("  " + "-" * 64)

        pre_d, pre_s = _diff_pct(ads_pre_v, hip_pre_v)
        dur_d, dur_s = _diff_pct(ads_dur_v, hip_dur_v)
        rev_d, rev_s = _diff_pct(ads_rev_v, hip_rev_v)

        if not (np.isnan(hip_pre_v) and np.isnan(ads_pre_v)):
            hg = _grade_stab(hip_pre_v, hip_th["pre_stable"],
                             hip_th["pre_unstable"])
            ag = _grade_stab(ads_pre_v, ads_th["pre_stable"],
                             ads_th["pre_unstable"])
            hp = "—" if np.isnan(hip_pre_v) else f"{hip_pre_v:.4f}"
            ap = "—" if np.isnan(ads_pre_v) else f"{ads_pre_v:.4f}"
            L.append(f"  开火前稳定度 | {hp:<8} ({hg:<2})  | "
                     f"{ap:<8} ({ag:<2})  | {pre_s}")
        if not (np.isnan(hip_dur_v) and np.isnan(ads_dur_v)):
            hg = _grade_stab(hip_dur_v, hip_th["during_stable"],
                             hip_th["during_unstable"])
            ag = _grade_stab(ads_dur_v, ads_th["during_stable"],
                             ads_th["during_unstable"])
            hd = "—" if np.isnan(hip_dur_v) else f"{hip_dur_v:.4f}"
            ad_ = "—" if np.isnan(ads_dur_v) else f"{ads_dur_v:.4f}"
            L.append(f"  开火中稳定度 | {hd:<8} ({hg:<2})  | "
                     f"{ad_:<8} ({ag:<2})  | {dur_s}")
        if not (np.isnan(hip_rev_v) and np.isnan(ads_rev_v)):
            hg = _grade_rev(hip_rev_v, hip_th["rev_good"], hip_th["rev_bad"])
            ag = _grade_rev(ads_rev_v, ads_th["rev_good"], ads_th["rev_bad"])
            hr = "—" if np.isnan(hip_rev_v) else f"{hip_rev_v:5.1f}"
            ar = "—" if np.isnan(ads_rev_v) else f"{ads_rev_v:5.1f}"
            L.append(f"  反转次数     | {hr:<8} ({hg:<4}) | "
                     f"{ar:<8} ({ag:<4}) | {rev_s}")
        if not (np.isnan(hip_dlow) or np.isnan(ads_dlow)):
            L.append(f"  主导推杆区间 | X={hip_dlow:>4.0f}-{hip_dhigh:<4.0f}"
                     f"        | X={ads_dlow:>4.0f}-{ads_dhigh:<4.0f}"
                     f"        | —")

        # 不对称结论 + 针对性建议
        L.append("")
        ASYMMETRY_THRESHOLD = 30.0  # 差异百分比阈值（%）
        asymmetries = []
        if not np.isnan(pre_d) and abs(pre_d) > ASYMMETRY_THRESHOLD:
            asymmetries.append(("pre", pre_d))
        if not np.isnan(dur_d) and abs(dur_d) > ASYMMETRY_THRESHOLD:
            asymmetries.append(("dur", dur_d))
        if not np.isnan(rev_d) and abs(rev_d) > ASYMMETRY_THRESHOLD:
            asymmetries.append(("rev", rev_d))

        if not asymmetries:
            L.append("  [√] 两种模式表现对称（差异均 < 30%），")
            L.append("      腰射/开镜曲线匹配度良好，无明显不对称问题。")
        else:
            L.append("  [⚠ 不对称问题]")
            for kind, d in asymmetries:
                if kind == "pre":
                    if d > 0:
                        L.append(f"  • 开镜瞄准抖动比腰射高 {d:+.0f}%")
                        L.append("    → ADS 曲线低段过激: 开镜后小幅修正被放大成抖动")
                        ads_low = ads_dlow if not np.isnan(ads_dlow) else 20
                        ads_high = ads_dhigh if not np.isnan(ads_dhigh) else 40
                        L.append(f"    → 建议: ADS 曲线 X={ads_low:.0f}-"
                                 f"{ads_high:.0f} 段对应节点 Y 值降低 1.5-2 单位")
                    else:
                        L.append(f"  • 腰射瞄准抖动比开镜高 {-d:.0f}%")
                        L.append("    → 腰射曲线低段微控不足: 慢推不响应导致猛推追枪")
                        hip_low = hip_dlow if not np.isnan(hip_dlow) else 10
                        hip_high = hip_dhigh if not np.isnan(hip_dhigh) else 30
                        L.append(f"    → 建议: 腰射曲线 X={hip_low:.0f}-"
                                 f"{hip_high:.0f} 段提升斜率（Y 升高 1-1.5 单位）")
                        L.append("           或检查死区是否设过大")
                elif kind == "dur":
                    if d > 0:
                        L.append(f"  • 开镜压枪抖动比腰射高 {d:+.0f}%")
                        L.append("    → ADS 曲线中段（压枪所在区间）斜率过高")
                        L.append("    → 建议: ADS 曲线 X=40-70 段 Y 值降低 1-2 单位")
                    else:
                        L.append(f"  • 腰射压枪抖动比开镜高 {-d:.0f}%")
                        L.append("    → 腰射模式抖动反常，可能是腰射曲线高段")
                        L.append("      过陡或腰射 RC 强度设置过激")
                elif kind == "rev":
                    if d > 0:
                        L.append(f"  • 开镜过冲比腰射高 {d:+.0f}%")
                        L.append("    → 开镜下准星反复修正、越过目标后回拉")
                        L.append("    → 建议: ADS 曲线中段（X=40-70）适度降低斜率")
                    else:
                        L.append(f"  • 腰射过冲比开镜高 {-d:.0f}%")
                        L.append("    → 腰射跟枪甩过头，可能是腰射高段灵敏度过高")

        L.append("")

    # ===== [T3.2] 走位 vs 站桩 模式对比 =====
    # 走位时左右手协调难度增加，pre/during 阈值放宽 1.3x 给走位组，
    # 避免把『走位本身的劣化』误判成曲线问题
    if moving_count > 0:
        L.append("-" * 70)
        L.append(" 八、走位 vs 站桩 模式对比")
        L.append("-" * 70)

        move_only = [m for m in metrics_list if m.get("is_moving")]
        stat_only = [m for m in metrics_list if not m.get("is_moving")]
        n_move = len(move_only)
        n_stat = len(stat_only)

        def _t32_avg(metrics, key):
            vals = [m[key] for m in metrics
                    if m.get(key) is not None
                    and not (isinstance(m.get(key), float)
                             and np.isnan(m[key]))]
            return float(np.mean(vals)) if vals else float("nan")

        move_pre = _t32_avg(move_only, "pre_stability")
        move_dur = _t32_avg(move_only, "during_stability")
        move_rev = _t32_avg(move_only, "total_reversals")
        stat_pre = _t32_avg(stat_only, "pre_stability")
        stat_dur = _t32_avg(stat_only, "during_stability")
        stat_rev = _t32_avg(stat_only, "total_reversals")

        # 走位放宽阈值
        MOVE_RELAX = 1.3
        m_th_pre_s = thresholds["pre_stable"] * MOVE_RELAX
        m_th_pre_u = thresholds["pre_unstable"] * MOVE_RELAX
        m_th_dur_s = thresholds["during_stable"] * MOVE_RELAX
        m_th_dur_u = thresholds["during_unstable"] * MOVE_RELAX

        def _t32_grade(val, t_s, t_u):
            if np.isnan(val):
                return "—"
            if val <= t_s:
                return "稳"
            if val <= t_u:
                return "一般"
            return "抖"

        def _t32_diff(a, b, min_baseline=0.005):
            """返回 (相对差异%, 显示字符串, 是否可信)。
            基线 < min_baseline 时百分比失真（除以接近零），
            改输出绝对差 + 不可信标记。
            """
            if np.isnan(a) or np.isnan(b):
                return float("nan"), "—", False
            if b < min_baseline:
                abs_d = a - b
                if abs(abs_d) < 0.01:
                    return float("nan"), "≈ 同(基线过小)", False
                return float("nan"), f"+{abs_d:.3f}(基线过小)", False
            d = (a - b) / b * 100
            return d, f"{d:+.0f}%", True

        L.append(f"  样本量: 走位 N={n_move}, 站桩 N={n_stat}")
        L.append(f"  评级阈值: 走位组 ×{MOVE_RELAX} 放宽（左右手协调更难），"
                 f"站桩组用标准阈值")
        L.append("")
        L.append("  指标         | 走位 (放宽)      | 站桩 (标准)      | 走位劣化")
        L.append("  " + "-" * 64)

        pre_d, pre_s_str, pre_reliable = _t32_diff(move_pre, stat_pre)
        dur_d, dur_s_str, dur_reliable = _t32_diff(move_dur, stat_dur)

        # 反转次数用绝对差显示（整数差异更直观）
        if np.isnan(move_rev) or np.isnan(stat_rev):
            rev_s_str = "—"
        else:
            rev_s_str = f"{move_rev - stat_rev:+.1f} 次"

        if not (np.isnan(move_pre) and np.isnan(stat_pre)):
            mg = _t32_grade(move_pre, m_th_pre_s, m_th_pre_u)
            sg = _t32_grade(stat_pre, thresholds["pre_stable"],
                            thresholds["pre_unstable"])
            ms = "—" if np.isnan(move_pre) else f"{move_pre:.4f}"
            ss = "—" if np.isnan(stat_pre) else f"{stat_pre:.4f}"
            L.append(f"  开火前稳定度 | {ms:<8} ({mg:<2}) | "
                     f"{ss:<8} ({sg:<2}) | {pre_s_str}")

        if not (np.isnan(move_dur) and np.isnan(stat_dur)):
            mg = _t32_grade(move_dur, m_th_dur_s, m_th_dur_u)
            sg = _t32_grade(stat_dur, thresholds["during_stable"],
                            thresholds["during_unstable"])
            ms = "—" if np.isnan(move_dur) else f"{move_dur:.4f}"
            ss = "—" if np.isnan(stat_dur) else f"{stat_dur:.4f}"
            L.append(f"  开火中稳定度 | {ms:<8} ({mg:<2}) | "
                     f"{ss:<8} ({sg:<2}) | {dur_s_str}")

        if not (np.isnan(move_rev) and np.isnan(stat_rev)):
            ms = "—" if np.isnan(move_rev) else f"{move_rev:5.1f}"
            ss = "—" if np.isnan(stat_rev) else f"{stat_rev:5.1f}"
            L.append(f"  反转次数     | {ms:<8}       | {ss:<8}       "
                     f"| {rev_s_str}")

        L.append("")

        # 结论 + 建议
        if n_stat == 0:
            # 全走位（用户的真实情况，实战常态）
            L.append(f"  [说明] 本次录制全部为走位射击（实战常态，无静止对比）。")
            L.append(f"        走位组放宽阈值: pre<={m_th_pre_s:.3f}=稳，"
                     f"during<={m_th_dur_s:.3f}=稳。")
            L.append(f"        建议下次录一段纯站桩对比，"
                     f"看走位本身贡献了多少劣化。")
        elif n_move == 0:
            # 全站桩 — 不会进入这个分支（moving_count > 0 已保证）
            pass
        else:
            # 双边都有，给针对性结论
            ASYMM_THRESHOLD = 30.0
            findings = []
            # 不可信差异（基线过小）不算劣化
            if pre_reliable and pre_d > ASYMM_THRESHOLD:
                findings.append(("pre", pre_d))
            if dur_reliable and dur_d > ASYMM_THRESHOLD:
                findings.append(("dur", dur_d))

            # 基线过小时单独提示（站桩样本里右摇杆几乎没动）
            baseline_too_small = (not pre_reliable and not dur_reliable
                                  and not np.isnan(move_pre)
                                  and not np.isnan(stat_pre))

            if baseline_too_small:
                L.append(f"  [说明] 站桩组基线偏低"
                         f"（pre={stat_pre:.4f}, dur={stat_dur:.4f}）：")
                L.append(f"        站桩时右摇杆几乎没动，无法形成可信对照。")
                L.append(f"        建议下次站桩时也做些瞄准微调，"
                         f"让数据有可比性。")
            elif not findings:
                if pre_reliable and pre_d < -10:
                    L.append(f"  [！] 走位反而比站桩稳（{pre_d:+.0f}%），")
                    L.append(f"      可能是站桩样本少/偶然，参考价值有限")
                else:
                    L.append(f"  [√] 走位与站桩表现接近"
                             f"（pre 差异 {pre_s_str}），")
                    L.append(f"      左右摇杆曲线协调良好")
            else:
                L.append("  [⚠ 走位明显劣化]")
                for kind, d in findings:
                    if kind == "pre":
                        if d > 50:
                            L.append(f"  • 走位瞄准抖动比站桩高 +{d:.0f}%（严重）")
                            L.append("    → 左摇杆推动时干扰右摇杆，"
                                     "怀疑是左右摇杆曲线不协调")
                            L.append("    → 检查左摇杆死区是否设过小（导致")
                            L.append("      走位时无意带动右摇杆产生噪声）")
                            L.append("    → 或检查手柄是否有摇杆交叉串扰"
                                     "（硬件问题）")
                        else:
                            L.append(f"  • 走位瞄准抖动比站桩高 +{d:.0f}%")
                            L.append("    → 左右手协调能力不足，"
                                     "练习走位射击的肌肉记忆")
                            L.append("    → 或检查左摇杆死区设置")
                    elif kind == "dur":
                        L.append(f"  • 走位压枪抖动比站桩高 +{d:.0f}%")
                        L.append("    → 走位时压枪手感不稳，"
                                 "可能是左摇杆持续输入分散了精力")
                        L.append("    → 实战中先练『站桩压枪稳』，"
                                 "再叠加『走位』")

        L.append("")

    # ===== [T2.2] 状态一致性（"心流代理"指标）=====
    # 算所有事件的 pre/dur 稳定度变异系数 CV = std/mean
    # CV 越小 = 表现越稳定（每次都差不多）；CV 越大 = 表现飘
    if len(pre_stabs) >= 4 or len(dur_stabs) >= 4:
        L.append("-" * 70)
        L.append(" 九、今日状态一致性（看你今天发挥稳不稳）")
        L.append("-" * 70)

        def _cv(arr):
            if len(arr) < 2:
                return None
            mean = float(np.mean(arr))
            if mean <= 0:
                return None
            return float(np.std(arr) / mean)

        cv_pre = _cv(pre_stabs)
        cv_dur = _cv(dur_stabs)
        if cv_pre is not None:
            L.append(f"  开火前稳定度 CV: {cv_pre:.2f}"
                     f"（每次的瞄准稳定度差异）")
        if cv_dur is not None:
            L.append(f"  开火中稳定度 CV: {cv_dur:.2f}"
                     f"（每次的压枪稳定度差异）")

        # 综合判断
        cv_max = max(filter(lambda x: x is not None, [cv_pre, cv_dur]),
                     default=None)
        if cv_max is not None:
            if cv_max < 0.30:
                L.append("  → 表现非常一致 ✓ 今天手感稳，"
                         "数据反映的是你的真实水平")
            elif cv_max < 0.60:
                L.append("  → 表现基本一致，可作为可靠参考")
            else:
                L.append("  → ⚠ 表现飘，今天状态可能不在线")
                L.append("    建议：今天数据仅供参考，先休息或简单训练几局再分析；")
                L.append("    或者过两天再录一次对比，看是状态问题还是曲线问题。")
        L.append("")

    # ===== [T2.1] 玩家自评事件对照 =====
    # 找 mark="good" 的时间点，匹配到最近的 burst，对比"自评好"和"非自评"的算法评分
    marked_events = []
    unmarked_events = []
    if "mark" in metrics_list[0]["data"].columns:
        # 找全数据里所有 mark=good 的时间戳
        all_data = pd.concat([m["data"] for m in metrics_list],
                             ignore_index=True).drop_duplicates("elapsed_s")
        good_marks_ts = (all_data[all_data["mark"] == "good"]["elapsed_s"]
                         .tolist() if "mark" in all_data.columns else [])

        # 每个 mark 关联到最近的开火事件（在 burst 期间或 burst 后 2 秒内）
        marked_burst_indices = set()
        for ts in good_marks_ts:
            best_idx = None
            best_dist = 2.0  # 最多向前找 2 秒
            for i, m in enumerate(metrics_list):
                bs = m["burst_start"]
                be = m["burst_end"]
                if bs <= ts <= be + 2.0:
                    dist = max(0, ts - be)
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = i
            if best_idx is not None:
                marked_burst_indices.add(best_idx)

        marked_events = [metrics_list[i] for i in marked_burst_indices]
        unmarked_events = [m for i, m in enumerate(metrics_list)
                           if i not in marked_burst_indices]

    if marked_events:
        L.append("-" * 70)
        L.append(" 十、玩家自评 vs 算法评分对照")
        L.append("-" * 70)
        L.append(f"  你标记了 {len(marked_events)} 次"
                 f"（认为'压得好'）")
        L.append(f"  其余 {len(unmarked_events)} 次未标记")
        L.append("")

        def _safe_mean(arr, key):
            vals = [m[key] for m in arr
                    if not np.isnan(m.get(key, float("nan")))]
            return float(np.mean(vals)) if vals else None

        marked_pre = _safe_mean(marked_events, "pre_stability")
        unmarked_pre = _safe_mean(unmarked_events, "pre_stability")
        marked_dur = _safe_mean(marked_events, "during_stability")
        unmarked_dur = _safe_mean(unmarked_events, "during_stability")

        L.append("  指标         | 你认为压得好  | 其余事件     | 算法是否同意")
        L.append("  " + "-" * 60)
        if marked_pre is not None and unmarked_pre is not None:
            agree = "✓ 同意" if marked_pre < unmarked_pre else "✗ 不同意"
            L.append(f"  开火前稳定度 | {marked_pre:.4f}      "
                     f"| {unmarked_pre:.4f}     | {agree}")
        if marked_dur is not None and unmarked_dur is not None:
            agree = "✓ 同意" if marked_dur < unmarked_dur else "✗ 不同意"
            L.append(f"  开火中稳定度 | {marked_dur:.4f}      "
                     f"| {unmarked_dur:.4f}     | {agree}")

        # 判断算法和直觉的一致性
        agreements = []
        if marked_pre is not None and unmarked_pre is not None:
            agreements.append(marked_pre < unmarked_pre)
        if marked_dur is not None and unmarked_dur is not None:
            agreements.append(marked_dur < unmarked_dur)
        if agreements:
            L.append("")
            if all(agreements):
                L.append("  → 算法评分和你的直觉完全一致 ✓")
                L.append("    说明算法的稳定度阈值校准得当，可以放心参考。")
            elif not any(agreements):
                L.append("  → ⚠ 算法和你的直觉相反")
                L.append("    可能原因：")
                L.append("    1) 你的直觉关注的是命中率/速度，而算法看的是稳定度")
                L.append("    2) 你按标记键时延迟了，标到了下一次事件")
                L.append("    3) 当前阈值可能不适合你的硬件，建议手动调校")
            else:
                L.append("  → 算法和你的直觉部分一致，混合判断")
        L.append("")
    elif "mark" in metrics_list[0].get("data", pd.DataFrame()).columns:
        # 有 mark 列但用户没按 → 给个温和提示
        L.append("-" * 70)
        L.append(" 十、玩家自评 vs 算法评分对照")
        L.append("-" * 70)
        L.append("  这次录制没有打标记。下次录制时按一下'标记键'就能标记")
        L.append("  '这次压得好'，分析时会和算法评分对照，")
        L.append("  能帮你判断算法的稳定度阈值是否符合你的直觉。")
        L.append("")

    L.append("=" * 70)
    L.append("  详细每次开火波形见 _event_*.png")
    L.append("  统计总览见 _summary.png")
    L.append("=" * 70)

    return "\n".join(L)


def main():
    parser = argparse.ArgumentParser(
        description="摇杆数据分析器")
    parser.add_argument("csv_file", help="stick_logger 输出的 CSV 文件")
    parser.add_argument("--max_events", type=int, default=20,
                        help="最多分析多少个事件（默认20，避免图太多）")
    parser.add_argument("--min_duration", type=float,
                        default=DEFAULT_MIN_DURATION_S,
                        help="最短爆发持续秒数，过滤误触（默认0.05）")
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"[X] 找不到文件：{csv_path}")
        sys.exit(1)

    df, metadata = load_csv(csv_path)
    thresholds = get_stability_thresholds(metadata)

    if "fire" not in df.columns:
        print(f"[X] CSV 缺少 fire 列，请用本工具最新版本的 stick_logger.py 重新录制")
        sys.exit(1)

    bursts = detect_fire_bursts(df, args.min_duration)
    print(f"[*] 检测到 {len(bursts)} 次开火爆发")
    if not bursts:
        print("[X] 没有检测到任何开火事件")
        print("    请确认 stick_logger.py 顶部的 FIRE_BUTTON 配置正确")
        print("    （你的开火键应配置为 RIGHT_SHOULDER）")
        sys.exit(1)

    if len(bursts) > args.max_events:
        print(f"[!] 事件过多，仅分析最后 {args.max_events} 次")
        bursts = bursts[-args.max_events:]

    print(f"[*] 开始分析...")
    events = []
    base = csv_path.stem
    out_dir = csv_path.parent

    # [T0.3] 从元数据取本底（录制前校准时写入），分析时减除
    try:
        nfx = float(metadata.get("noise_floor_x", "0") or 0)
        nfy = float(metadata.get("noise_floor_y", "0") or 0)
    except (ValueError, TypeError):
        nfx = nfy = 0.0
    if nfx > 0 or nfy > 0:
        print(f"[√] 应用硬件本底校准：X={nfx:.5f}  Y={nfy:.5f}")

    # [T2.3] 从元数据推断武器 RPM，用于动态调整 during 窗口
    weapon_rpm = detect_weapon_rpm(metadata.get("weapons", ""))
    if weapon_rpm > 0:
        win_ms = rpm_to_during_window_ms(weapon_rpm)
        if win_ms <= 0:
            print(f"[√] 武器识别：{metadata['weapons']}（{weapon_rpm} RPM，"
                  f"单发/拉栓 → 跳过开火中稳定度分析）")
        else:
            print(f"[√] 武器识别：{metadata['weapons']}（{weapon_rpm} RPM，"
                  f"开火中窗口={win_ms}ms）")

    for i, (b_start, b_end) in enumerate(bursts, 1):
        m = analyze_burst(df, b_start, b_end,
                          noise_floor_x=nfx, noise_floor_y=nfy,
                          weapon_rpm=weapon_rpm)
        if m is None:
            continue
        cls = classify_burst(m)
        events.append({"index": i, "metrics": m, "classification": cls})

        png_path = out_dir / f"{base}_event_{i:02d}.png"
        title = (f"开火 #{i} @ {b_start:.2f}s 持续{m['duration']:.2f}s | "
                 f"{'ADS' if m['is_ads'] else '腰射'} | {cls}")
        plot_burst(m, png_path, title)
        pre = m["pre_stability"]
        dur = m["during_stability"]
        pre_str = f"{pre:.4f}" if not np.isnan(pre) else "N/A"
        dur_str = f"{dur:.4f}" if not np.isnan(dur) else "N/A"
        print(f"  [{i}/{len(bursts)}] @ {b_start:6.2f}s | {cls:18} | "
              f"前稳={pre_str} | 中稳={dur_str} | 反转={m['total_reversals']:3d}")

    summary_path = out_dir / f"{base}_summary.png"
    plot_summary(events, summary_path)
    print(f"[√] 总览图：{summary_path}")

    report = generate_report(events, csv_path, metadata, thresholds)
    report_path = out_dir / f"{base}_report.txt"
    report_path.write_text(report, encoding="utf-8")
    print()
    print(report)
    print()
    print(f"[√] 报告已保存：{report_path}")


if __name__ == "__main__":
    main()