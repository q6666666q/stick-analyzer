"""
摇杆数据分析器 v2.0
================================
变化：
- 自动检测所有"开火爆发"事件，无需外部击杀时间戳
- 兼容 v1.0 和 v2.0 的 CSV 格式
- 增加"完整爆发分析"模式：分析每次开火从开始到结束的全过程

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
import matplotlib.pyplot as plt
import matplotlib
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
DURING_FIRE_STABILITY_MS = 300  # 开火中稳定度评估窗口
# ===============================================


def load_csv(path: Path) -> tuple:
    """加载 CSV 数据，同时解析头部元数据。返回 (df, metadata)"""
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
    print(f"[√] 加载完成：{len(df)} 帧，时长 {df['elapsed_s'].iloc[-1]:.1f} 秒")
    if metadata:
        print(f"[√] 元数据：{metadata}")
    return df, metadata


def get_stability_thresholds(metadata: dict) -> dict:
    """根据 RC 动感强度等级调整稳定度阈值。

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
        "light": "轻度动感",
        "medium": "中度动感",
        "strong": "强动感",
        "extreme": "极限动感",
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
                # 数值过大说明手柄 RC 范围不是 ±10，按"中度动感"兜底
                factor = intensity_factors["medium"]
                thresholds["intensity_label"] = (
                    f"老格式 RC={rc_ads}（数值范围未知，按中度动感处理）")
        except (ValueError, TypeError):
            pass

    if factor is not None and factor != 1.0:
        thresholds["pre_stable"] *= factor
        thresholds["pre_unstable"] *= factor
        thresholds["during_stable"] *= factor
        thresholds["during_unstable"] *= factor

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


def analyze_burst(df: pd.DataFrame, burst_start: float, burst_end: float) -> dict:
    """分析单个开火爆发"""
    t_win_start = burst_start - WINDOW_BEFORE_S
    t_win_end = burst_end + WINDOW_AFTER_S
    win = df[(df["elapsed_s"] >= t_win_start)
             & (df["elapsed_s"] <= t_win_end)].copy()

    if len(win) < 10:
        return None

    # 相对时间：以开火起始为 0
    win["rel_t"] = win["elapsed_s"] - burst_start
    burst_duration = burst_end - burst_start

    # ===== 指标 1：开火前 100ms 稳定度 =====
    pre_window = win[(win["rel_t"] >= -PRE_FIRE_STABILITY_MS / 1000.0)
                     & (win["rel_t"] <= 0)]
    if len(pre_window) > 5:
        pre_rx_std = pre_window["rx"].std()
        pre_ry_std = pre_window["ry"].std()
        pre_stability = float(np.sqrt(pre_rx_std ** 2 + pre_ry_std ** 2))
    else:
        pre_stability = float("nan")

    # ===== 指标 2：开火中 300ms 稳定度 =====
    fire_during = win[(win["rel_t"] >= 0)
                      & (win["rel_t"] <= DURING_FIRE_STABILITY_MS / 1000.0)]
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
            during_stability = float(np.sqrt(rx_residual.std() ** 2
                                             + ry_residual.std() ** 2))
        else:
            during_stability = float(np.sqrt(rx_arr.std() ** 2
                                             + ry_arr.std() ** 2))
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
    burst_data = win[(win["rel_t"] >= 0) & (win["rel_t"] <= burst_duration)]
    if len(burst_data) > 50:
        smooth_win = max(5, min(50, len(burst_data) // 5))

        def count_meaningful_reversals(arr):
            # 简单滑动平均
            kernel = np.ones(smooth_win) / smooth_win
            smoothed = np.convolve(arr, kernel, mode="valid")
            if len(smoothed) < 4:
                return 0
            v = np.diff(smoothed)
            # 符号变化点
            sign_change_idx = np.where(np.diff(np.sign(v)) != 0)[0]
            count = 0
            last_extreme_val = smoothed[0]
            for idx in sign_change_idx:
                # 当前极值
                cur_extreme = smoothed[idx + 1]
                if abs(cur_extreme - last_extreme_val) > 0.05:
                    count += 1
                    last_extreme_val = cur_extreme
            return count

        rx_rev = count_meaningful_reversals(burst_data["rx"].values)
        ry_rev = count_meaningful_reversals(burst_data["ry"].values)
        total_reversals = int(rx_rev + ry_rev)
    else:
        total_reversals = 0

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
        "dominant_input_low": dom_low,
        "dominant_input_high": dom_high,
        "is_ads": is_ads,
        "is_moving": is_moving,
        "lx_range": lx_range,
        "ly_range": ly_range,
    }


def classify_burst(m: dict) -> str:
    """根据指标分类射击行为"""
    if m is None:
        return "数据不足"
    pre = m["pre_stability"]
    dur = m["during_stability"]
    rev = m["total_reversals"]

    if not np.isnan(pre) and pre < 0.04 and rev < 10:
        return "稳定射击 ✓"
    if not np.isnan(pre) and pre > 0.10:
        return "开火前抖动 ⚠"
    if not np.isnan(dur) and dur > 0.08:
        return "开火中抖动 ⚠"
    if rev > 25:
        return "频繁过冲 ⚠"
    if m["avg_magnitude"] < 0.10:
        return "微调跟枪"
    return "中等稳定"


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
    plt.close()


def plot_summary(events: list, output_path: Path):
    """统计总览"""
    metrics_list = [e["metrics"] for e in events if e["metrics"] is not None]
    if not metrics_list:
        return

    pre_stabs = [m["pre_stability"] for m in metrics_list
                 if not np.isnan(m["pre_stability"])]
    dur_stabs = [m["during_stability"] for m in metrics_list
                 if not np.isnan(m["during_stability"])]
    revs = [m["total_reversals"] for m in metrics_list]
    mags = [m["avg_magnitude"] for m in metrics_list]
    centers = [(m["dominant_input_low"] + m["dominant_input_high"]) / 2
               for m in metrics_list]

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

    colors = ["#27AE60" if m["is_ads"] else "#E67E22" for m in metrics_list]
    axes[1, 0].scatter(mags, pre_stabs[:len(mags)] if pre_stabs else mags,
                       c=colors, alpha=0.7, s=50)
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
    plt.close()


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
            L.append(f"  [注] 动感等级: {intensity_label}，"
                     f"稳定度阈值已自动调整 {pct:+.0f}%")
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
    L.append("")

    L.append("-" * 70)
    L.append(" 四、行为分类")
    L.append("-" * 70)
    for cls, cnt in sorted(class_count.items(), key=lambda x: -x[1]):
        pct = 100 * cnt / n
        bar = "█" * int(pct / 2)
        L.append(f"  {cls:18} | {cnt:4} 次 ({pct:5.1f}%) {bar}")
    L.append("")

    L.append("-" * 70)
    L.append(" 五、关键发现：你的主导推杆区间")
    L.append("-" * 70)
    L.append(f"  你开火时最常用的推杆量: X={common_low:.0f}–{common_high:.0f}")
    L.append("  → 曲线这段的设计对你影响最大")
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

    if avg_rev > thresholds["rev_bad"]:
        issues.append("过冲")
        L.append(f"  [警] 过冲严重（{avg_rev:.1f} 次/事件）：")
        L.append(f"     准星反复修正，越过目标后回拉")
        L.append(f"     → 降低中段（X=40-70）输出，节点 4、5 的 Y 值降低 1.5-2 单位")
    elif avg_rev > 12:
        L.append(f"  [提示] 有一定过冲（{avg_rev:.1f} 次/事件）")
        L.append(f"     可适度降低中段斜率")
    else:
        L.append(f"  [√] 过冲控制良好（{avg_rev:.1f} 次/事件）")
    L.append("")

    # ADS vs 腰射对比
    if ads_count > 0 and ads_count < n:
        ads_metrics = [m for m in metrics_list if m["is_ads"]]
        non_ads_metrics = [m for m in metrics_list if not m["is_ads"]]
        ads_pre = np.mean([m["pre_stability"] for m in ads_metrics
                           if not np.isnan(m["pre_stability"])])
        non_ads_pre = np.mean([m["pre_stability"] for m in non_ads_metrics
                               if not np.isnan(m["pre_stability"])])
        L.append(f"  ADS 模式开火前稳定度: {ads_pre:.4f}")
        L.append(f"  腰射模式开火前稳定度: {non_ads_pre:.4f}")
        if ads_pre > non_ads_pre * 1.3:
            L.append(f"  → 开镜稳定度差于腰射，ADS 曲线低段可能过激")
        elif non_ads_pre > ads_pre * 1.3:
            L.append(f"  → 腰射稳定度差于开镜，腰射曲线低段微控不足")
    L.append("")

    # 走位射击额外分析
    if moving_count > 0:
        moving_metrics = [m for m in metrics_list if m["is_moving"]]
        moving_pre = [m["pre_stability"] for m in moving_metrics
                      if not np.isnan(m["pre_stability"])]
        if moving_pre:
            L.append(f"  走位射击稳定度: {np.mean(moving_pre):.4f}（共 {moving_count} 次）")
            if np.mean(moving_pre) > 0.10:
                L.append(f"  → 走位时瞄准明显变差，可能是左右摇杆曲线协调问题")
    L.append("")

    if not issues:
        L.append("  [总结] 所有指标良好，曲线匹配度很高")
    else:
        L.append(f"  [总结] 主要问题: {', '.join(issues)}")
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

    for i, (b_start, b_end) in enumerate(bursts, 1):
        m = analyze_burst(df, b_start, b_end)
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
