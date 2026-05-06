"""
摇杆数据记录器 v2.0
================================
变化：
- 支持配置任意按键作为"开火"和"开镜"事件
- 完整记录所有按键状态（用于事后灵活分析）
- 默认配置为 RB=开火，DPAD_UP=开镜（按用户实际键位）

使用方法：
1. 安装依赖：pip install -r requirements.txt
2. 连接手柄
3. 运行：python stick_logger.py
4. 打游戏...
5. Ctrl+C 停止，自动保存为 stick_log_<时间戳>.csv

如果你的键位不同，修改下方 FIRE_BUTTON / ADS_BUTTON 即可。

输出 CSV 字段：
    timestamp_ns: 系统纳秒级时间戳
    elapsed_s   : 距开始记录的秒数
    lx, ly      : 左摇杆 X/Y，范围 -1.0 ~ +1.0
    rx, ry      : 右摇杆 X/Y，范围 -1.0 ~ +1.0
    lt, rt      : 左右扳机，范围 0.0 ~ 1.0
    btn_*       : 各按键状态（0/1）
    fire        : 是否在开火（FIRE_BUTTON 按下）
    ads         : 是否在开镜（ADS_BUTTON 按下）
"""

import csv
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import XInput
except ImportError:
    print("缺少 XInput-Python 库，请运行：pip install XInput-Python")
    sys.exit(1)


# ==================== 用户配置 ====================
# 开火和开镜的按键名（区分大小写）
# 可选值：DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT,
#         START, BACK, LEFT_THUMB, RIGHT_THUMB,
#         LEFT_SHOULDER, RIGHT_SHOULDER, A, B, X, Y
# 也可设为 "TRIGGER_LEFT" / "TRIGGER_RIGHT" 表示扳机
FIRE_BUTTON = "RIGHT_SHOULDER"   # RB 右肩键
ADS_BUTTON = "DPAD_UP"           # 方向键上

TARGET_RATE_HZ = 1000            # 目标采样率
TRIGGER_THRESHOLD = 0.5          # 扳机被视为按下的阈值
DISPLAY_INTERVAL_S = 0.1         # 屏幕刷新间隔
# ===================================================


# 所有要记录的按键
ALL_BUTTONS = [
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
    "START", "BACK",
    "LEFT_THUMB", "RIGHT_THUMB",
    "LEFT_SHOULDER", "RIGHT_SHOULDER",
    "A", "B", "X", "Y",
]


def find_controller():
    """查找连接的手柄，返回手柄索引（0-3）或 None"""
    for i in range(4):
        if XInput.get_connected()[i]:
            return i
    return None


def is_button_pressed(button_name: str, buttons_dict: dict,
                      lt: float, rt: float) -> bool:
    """统一处理按键和扳机的'按下'判断"""
    if button_name == "TRIGGER_LEFT":
        return lt > TRIGGER_THRESHOLD
    if button_name == "TRIGGER_RIGHT":
        return rt > TRIGGER_THRESHOLD
    return bool(buttons_dict.get(button_name, False))


def main():
    print("=" * 60)
    print("  摇杆数据记录器 v2.0")
    print("=" * 60)
    print()
    print(f"键位配置：")
    print(f"  开火键 (FIRE) = {FIRE_BUTTON}")
    print(f"  开镜键 (ADS)  = {ADS_BUTTON}")
    print()

    # 询问元数据
    print("--- 本次记录元数据（用于分析报告，可直接回车跳过）---")
    try:
        rc_hipfire = input("当前腰射 RC 值（如 -3）: ").strip() or "unknown"
        rc_ads = input("当前开镜 RC 值（如 -7）: ").strip() or "unknown"
        curve_name = input("当前曲线版本/名称（如 v5）: ").strip() or "unknown"
        weapons_used = input("本次主要使用武器（如 R99,R301）: ").strip() or "unknown"
        scene = input("场景（训练场/比赛/休闲）: ").strip() or "unknown"
    except (EOFError, KeyboardInterrupt):
        rc_hipfire = rc_ads = curve_name = weapons_used = scene = "unknown"
    print()

    # 检测控制器
    controller_idx = find_controller()
    if controller_idx is None:
        print("[X] 未检测到任何手柄，请连接手柄后重试")
        sys.exit(1)
    print(f"[√] 检测到 XInput 手柄：手柄 {controller_idx}")

    # 输出文件
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(f"stick_log_{timestamp_str}.csv")
    print(f"[√] 输出文件：{output_file.resolve()}")
    print(f"[√] 目标采样率：{TARGET_RATE_HZ} Hz")
    print()
    print("开始记录... 按 Ctrl+C 停止")
    print("提示：屏幕的 ADS/Fire 标记应该和你按键同步亮起")
    print("-" * 60)

    # 准备 CSV
    btn_columns = [f"btn_{b.lower()}" for b in ALL_BUTTONS]
    csv_file = open(output_file, "w", newline="", encoding="utf-8")

    # 写入元数据头部（注释行，分析器会解析）
    csv_file.write(f"# meta: rc_hipfire={rc_hipfire}\n")
    csv_file.write(f"# meta: rc_ads={rc_ads}\n")
    csv_file.write(f"# meta: curve={curve_name}\n")
    csv_file.write(f"# meta: weapons={weapons_used}\n")
    csv_file.write(f"# meta: scene={scene}\n")
    csv_file.write(f"# meta: fire_button={FIRE_BUTTON}\n")
    csv_file.write(f"# meta: ads_button={ADS_BUTTON}\n")
    csv_file.write(f"# meta: started={datetime.now().isoformat()}\n")

    writer = csv.writer(csv_file)
    writer.writerow([
        "timestamp_ns", "elapsed_s",
        "lx", "ly", "rx", "ry",
        "lt", "rt",
    ] + btn_columns + ["fire", "ads"])

    # 主循环
    start_ns = time.time_ns()
    last_display_ns = start_ns
    sample_count = 0
    fire_count = 0
    ads_count = 0
    sample_interval_ns = int(1e9 / TARGET_RATE_HZ)
    next_sample_ns = start_ns

    try:
        while True:
            now_ns = time.time_ns()
            if now_ns < next_sample_ns:
                continue

            try:
                state = XInput.get_state(controller_idx)
            except XInput.XInputNotConnectedError:
                print("\n[!] 手柄断开连接")
                break

            (lx, ly), (rx, ry) = XInput.get_thumb_values(state)
            lt, rt = XInput.get_trigger_values(state)
            buttons = XInput.get_button_values(state)

            fire = is_button_pressed(FIRE_BUTTON, buttons, lt, rt)
            ads = is_button_pressed(ADS_BUTTON, buttons, lt, rt)
            elapsed = (now_ns - start_ns) / 1e9

            row = [
                now_ns, f"{elapsed:.6f}",
                f"{lx:.5f}", f"{ly:.5f}", f"{rx:.5f}", f"{ry:.5f}",
                f"{lt:.4f}", f"{rt:.4f}",
            ]
            for b in ALL_BUTTONS:
                row.append(int(bool(buttons.get(b, False))))
            row.extend([int(fire), int(ads)])
            writer.writerow(row)

            sample_count += 1
            if fire:
                fire_count += 1
            if ads:
                ads_count += 1

            # 屏幕刷新
            if (now_ns - last_display_ns) / 1e9 > DISPLAY_INTERVAL_S:
                actual_rate = sample_count / max(elapsed, 1e-6)
                fire_pct = 100 * fire_count / max(sample_count, 1)
                ads_pct = 100 * ads_count / max(sample_count, 1)
                status = []
                if ads:
                    status.append("[ADS]")
                if fire:
                    status.append("[FIRE]")
                status_str = " ".join(status) if status else "      "
                sys.stdout.write(
                    f"\rT={elapsed:7.1f}s | "
                    f"LX={lx:+.3f} LY={ly:+.3f} | "
                    f"RX={rx:+.3f} RY={ry:+.3f} | "
                    f"采样率={actual_rate:.0f}Hz | "
                    f"ADS={ads_pct:.1f}% Fire={fire_pct:.1f}% {status_str}"
                )
                sys.stdout.flush()
                last_display_ns = now_ns

            next_sample_ns += sample_interval_ns
            if next_sample_ns < now_ns:
                next_sample_ns = now_ns + sample_interval_ns

    except KeyboardInterrupt:
        print("\n\n[√] 收到停止信号")

    finally:
        csv_file.close()
        elapsed_total = (time.time_ns() - start_ns) / 1e9
        print("-" * 60)
        print(f"[√] 记录完成")
        print(f"    总时长：{elapsed_total:.1f} 秒")
        print(f"    总样本：{sample_count} 帧")
        print(f"    平均采样率：{sample_count/max(elapsed_total,1e-6):.0f} Hz")
        print(f"    开火帧数：{fire_count} ({100*fire_count/max(sample_count,1):.1f}%)")
        print(f"    开镜帧数：{ads_count} ({100*ads_count/max(sample_count,1):.1f}%)")
        print(f"    输出文件：{output_file.resolve()}")

        if fire_count == 0:
            print()
            print("[!] 警告：没有检测到任何开火事件")
            print(f"    请确认你的开火键确实是 {FIRE_BUTTON}")
            print(f"    如果不是，请编辑 stick_logger.py 顶部的 FIRE_BUTTON 配置")

        print()
        print("下一步：python analyzer.py", output_file.name)


if __name__ == "__main__":
    main()
