"""手柄按键诊断工具

直接用 pygame 读手柄原始索引，并对照 controller_backend 的映射逻辑，
帮你定位 RB / RT / 任何按键映射不上的根本原因。

运行：
    .venv\\Scripts\\python.exe _diagnose_buttons.py

按 Ctrl+C 退出。
"""
import sys
import io
import time

# Windows 控制台中文输出
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

import pygame
import controller_backend as cb


def main():
    print("=" * 70)
    print("  StickAnalyzer 按键诊断工具")
    print("=" * 70)

    pygame.init()
    pygame.joystick.init()

    n = pygame.joystick.get_count()
    if n == 0:
        print("[X] pygame 没扫到任何手柄。请插上手柄/连蓝牙后重试。")
        return

    print(f"\n[√] pygame 检测到 {n} 个手柄")

    # 让用户选一个
    joys = []
    for i in range(n):
        j = pygame.joystick.Joystick(i)
        j.init()
        joys.append(j)
        print(f"  [{i}] 名称={j.get_name()}")
        print(f"      GUID={j.get_guid() if hasattr(j, 'get_guid') else 'N/A'}")
        print(f"      num_axes={j.get_numaxes()}  "
              f"num_buttons={j.get_numbuttons()}  "
              f"num_hats={j.get_numhats()}")

    if n == 1:
        idx = 0
    else:
        try:
            idx = int(input(f"\n选择手柄编号 (0-{n-1})，默认 0: ") or "0")
        except ValueError:
            idx = 0

    j = joys[idx]
    name = j.get_name()
    num_buttons = j.get_numbuttons()
    num_hats = j.get_numhats()
    num_axes = j.get_numaxes()

    print("\n" + "=" * 70)
    print(f"  已选择: {name}")
    print(f"  num_buttons={num_buttons}  num_hats={num_hats}  num_axes={num_axes}")
    print("=" * 70)

    # 查 controller_backend 决定走哪张表
    layout = cb._PygameBackend().detect_layout(name, num_buttons)
    print(f"\n[*] controller_backend 判定 layout = {layout!r}")

    button_map = cb.get_pygame_button_map(layout,
                                          num_hats=num_hats,
                                          num_buttons=num_buttons)
    # 反查这张表是哪一张
    table_name = "未知"
    for tn, tref in [
        ("PYGAME_BUTTON_TO_LOGICAL_XBOX", cb.PYGAME_BUTTON_TO_LOGICAL_XBOX),
        ("PYGAME_BUTTON_TO_LOGICAL_PS", cb.PYGAME_BUTTON_TO_LOGICAL_PS),
        ("PYGAME_BUTTON_TO_LOGICAL_SWITCH", cb.PYGAME_BUTTON_TO_LOGICAL_SWITCH),
    ]:
        if button_map is tref:
            table_name = tn
            break

    print(f"[*] 当前选中的按键映射表 = {table_name}")
    print(f"\n[*] 此表的 button 索引 → 逻辑名:")
    for k in sorted(button_map.keys()):
        marker = ""
        if button_map[k] == "RIGHT_SHOULDER":
            marker = "  ← RB（开火默认键）"
        elif button_map[k] == "LEFT_SHOULDER":
            marker = "  ← LB"
        print(f"      [{k:2d}] → {button_map[k]}{marker}")

    # 找 RIGHT_SHOULDER 在哪个索引
    rb_idx = None
    for k, v in button_map.items():
        if v == "RIGHT_SHOULDER":
            rb_idx = k
            break
    if rb_idx is None:
        print("\n[!] 当前映射表里没有 RIGHT_SHOULDER（RB），"
              "录制时按 RB 永远不会被识别为开火！")
    else:
        print(f"\n[*] 当前认为 RB 在 button 索引 {rb_idx}")

    print("\n" + "=" * 70)
    print("  实时按键监控（按 Ctrl+C 退出）")
    print("=" * 70)
    print("  按下手柄上任意键，我会同时打印「原始 button 索引」和"
          "「映射后的逻辑名」")
    print("  请重点试一下 RB（右肩键）和 LB（左肩键），")
    print("  看 RB 实际报的是哪个索引，是否对得上当前表里的索引。")
    print()

    last_buttons = [False] * num_buttons
    last_hat = (0, 0) if num_hats > 0 else None
    last_axes = [0.0] * num_axes

    try:
        while True:
            pygame.event.pump()
            pygame.event.clear()

            # 检测按键变化
            for i in range(num_buttons):
                pressed = bool(j.get_button(i))
                if pressed != last_buttons[i]:
                    logical = button_map.get(i, "(未映射)")
                    state = "按下" if pressed else "松开"
                    flag = ""
                    if logical == "RIGHT_SHOULDER":
                        flag = "  ★ 这是开火键"
                    elif logical == "(未映射)":
                        flag = "  ⚠ 未映射 — 这个按键被丢弃了"
                    print(f"  [按键] index={i:2d}  逻辑名={logical:20s}  "
                          f"状态={state}{flag}")
                    last_buttons[i] = pressed

            # 检测 hat（方向键，老 raw Joystick 抽象）
            if num_hats > 0:
                hx, hy = j.get_hat(0)
                if (hx, hy) != last_hat:
                    print(f"  [HAT0] x={hx:+d}, y={hy:+d}  "
                          f"（{'上' if hy>0 else '下' if hy<0 else '中'}, "
                          f"{'左' if hx<0 else '右' if hx>0 else '中'}）")
                    last_hat = (hx, hy)

            # 检测扳机（轴 4/5）
            for ai in (4, 5):
                if ai < num_axes:
                    val = float(j.get_axis(ai))
                    if abs(val - last_axes[ai]) > 0.20:
                        # 归一化到 0~1
                        norm = (val + 1.0) / 2.0
                        name_ = "LT" if ai == 4 else "RT"
                        print(f"  [扳机] axis{ai} ({name_})  raw={val:+.2f}  "
                              f"归一化={norm:.2f}")
                        last_axes[ai] = val

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n\n[*] 退出诊断")


if __name__ == "__main__":
    main()
