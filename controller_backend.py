"""
controller_backend.py
================================
控制器抽象层：统一 pygame（PS/PS4/PS5/DualSense Edge/通用 HID）
和 XInput（XBOX 系列）两种驱动，提供 4 槽位管理。

设计目标：
- 双驱动并存，自动去重（避免同一物理设备被两个驱动识别）
- 4 个固定槽位，按插入顺序占位
- 按键映射逻辑名称化（ACTION_SOUTH / EAST / WEST / NORTH ...）
- 提供给 GUI 用于显示原生按键标签（× ○ □ △ vs A B X Y）
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# 静默 pygame 启动横幅
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


# ==================== 协议常量 ====================
PROTO_PYGAME = "pygame"
PROTO_XINPUT = "xinput"

# 按键布局（决定 GUI 显示什么标签）
LAYOUT_XBOX = "xbox"
LAYOUT_PS = "ps"
LAYOUT_PS_EDGE = "ps_edge"      # DualSense Edge，多了背键 FN1/FN2/RB1/RB2
LAYOUT_SWITCH = "switch"
LAYOUT_GENERIC = "generic"

MAX_SLOTS = 4


# ==================== 逻辑按键代码 ====================
# 这些是统一的"逻辑名"，CSV 写入用这套，GUI 显示时根据布局映射成原生标签

LOGICAL_BUTTONS = [
    # 面板按键（南/东/西/北）
    "ACTION_SOUTH",     # XBOX A / PS ×
    "ACTION_EAST",      # XBOX B / PS ○
    "ACTION_WEST",      # XBOX X / PS □
    "ACTION_NORTH",     # XBOX Y / PS △

    # 方向键
    "DPAD_UP",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",

    # 肩键
    "LEFT_SHOULDER",    # LB / L1
    "RIGHT_SHOULDER",   # RB / R1

    # 摇杆按下
    "LEFT_THUMB",       # L3
    "RIGHT_THUMB",      # R3

    # 选择/开始
    "BACK",             # BACK / SHARE
    "START",            # START / OPTIONS

    # PS 中央
    "GUIDE",            # XBOX GUIDE / PS HOME
    "TOUCHPAD",         # PS 触摸板按下（XBOX 没有）

    # DualSense Edge 专属（背键、功能键）
    "EDGE_FN1",
    "EDGE_FN2",
    "EDGE_RB1",
    "EDGE_RB2",

    # 扳机当按键用（部分场景需要）
    "TRIGGER_LEFT",     # 等价 LT > 0.5
    "TRIGGER_RIGHT",    # 等价 RT > 0.5
]


# 各布局下的中文显示名
BUTTON_DISPLAY_NAMES: dict[str, dict[str, str]] = {
    LAYOUT_XBOX: {
        "ACTION_SOUTH": "A 键",
        "ACTION_EAST": "B 键",
        "ACTION_WEST": "X 键",
        "ACTION_NORTH": "Y 键",
        "DPAD_UP": "方向键上",
        "DPAD_DOWN": "方向键下",
        "DPAD_LEFT": "方向键左",
        "DPAD_RIGHT": "方向键右",
        "LEFT_SHOULDER": "LB 左肩键",
        "RIGHT_SHOULDER": "RB 右肩键",
        "LEFT_THUMB": "L3 左摇杆按下",
        "RIGHT_THUMB": "R3 右摇杆按下",
        "BACK": "BACK / 视图",
        "START": "START / 菜单",
        "GUIDE": "XBOX GUIDE",
        "TOUCHPAD": "(无)",
        "EDGE_FN1": "(无)",
        "EDGE_FN2": "(无)",
        "EDGE_RB1": "(无)",
        "EDGE_RB2": "(无)",
        "TRIGGER_LEFT": "LT 左扳机",
        "TRIGGER_RIGHT": "RT 右扳机",
    },
    LAYOUT_PS: {
        "ACTION_SOUTH": "× 叉",
        "ACTION_EAST": "○ 圆",
        "ACTION_WEST": "□ 方",
        "ACTION_NORTH": "△ 三角",
        "DPAD_UP": "方向键上",
        "DPAD_DOWN": "方向键下",
        "DPAD_LEFT": "方向键左",
        "DPAD_RIGHT": "方向键右",
        "LEFT_SHOULDER": "L1 左肩键",
        "RIGHT_SHOULDER": "R1 右肩键",
        "LEFT_THUMB": "L3 左摇杆按下",
        "RIGHT_THUMB": "R3 右摇杆按下",
        "BACK": "SHARE / CREATE",
        "START": "OPTIONS",
        "GUIDE": "PS HOME",
        "TOUCHPAD": "触摸板按下",
        "EDGE_FN1": "(无)",
        "EDGE_FN2": "(无)",
        "EDGE_RB1": "(无)",
        "EDGE_RB2": "(无)",
        "TRIGGER_LEFT": "L2 左扳机",
        "TRIGGER_RIGHT": "R2 右扳机",
    },
    LAYOUT_PS_EDGE: {
        "ACTION_SOUTH": "× 叉",
        "ACTION_EAST": "○ 圆",
        "ACTION_WEST": "□ 方",
        "ACTION_NORTH": "△ 三角",
        "DPAD_UP": "方向键上",
        "DPAD_DOWN": "方向键下",
        "DPAD_LEFT": "方向键左",
        "DPAD_RIGHT": "方向键右",
        "LEFT_SHOULDER": "L1 左肩键",
        "RIGHT_SHOULDER": "R1 右肩键",
        "LEFT_THUMB": "L3 左摇杆按下",
        "RIGHT_THUMB": "R3 右摇杆按下",
        "BACK": "SHARE / CREATE",
        "START": "OPTIONS",
        "GUIDE": "PS HOME",
        "TOUCHPAD": "触摸板按下",
        "EDGE_FN1": "FN1 功能键",
        "EDGE_FN2": "FN2 功能键",
        "EDGE_RB1": "RB1 后置左键",
        "EDGE_RB2": "RB2 后置右键",
        "TRIGGER_LEFT": "L2 左扳机",
        "TRIGGER_RIGHT": "R2 右扳机",
    },
    LAYOUT_SWITCH: {
        "ACTION_SOUTH": "B 键",
        "ACTION_EAST": "A 键",
        "ACTION_WEST": "Y 键",
        "ACTION_NORTH": "X 键",
        "DPAD_UP": "方向键上",
        "DPAD_DOWN": "方向键下",
        "DPAD_LEFT": "方向键左",
        "DPAD_RIGHT": "方向键右",
        "LEFT_SHOULDER": "L 左肩键",
        "RIGHT_SHOULDER": "R 右肩键",
        "LEFT_THUMB": "L摇 按下",
        "RIGHT_THUMB": "R摇 按下",
        "BACK": "- 减号",
        "START": "+ 加号",
        "GUIDE": "HOME",
        "TOUCHPAD": "(无)",
        "EDGE_FN1": "(无)",
        "EDGE_FN2": "(无)",
        "EDGE_RB1": "(无)",
        "EDGE_RB2": "(无)",
        "TRIGGER_LEFT": "ZL 左扳机",
        "TRIGGER_RIGHT": "ZR 右扳机",
    },
    LAYOUT_GENERIC: {  # 兜底，用通用名
        "ACTION_SOUTH": "Btn 1 (下)",
        "ACTION_EAST": "Btn 2 (右)",
        "ACTION_WEST": "Btn 3 (左)",
        "ACTION_NORTH": "Btn 4 (上)",
        "DPAD_UP": "方向键上",
        "DPAD_DOWN": "方向键下",
        "DPAD_LEFT": "方向键左",
        "DPAD_RIGHT": "方向键右",
        "LEFT_SHOULDER": "左肩键",
        "RIGHT_SHOULDER": "右肩键",
        "LEFT_THUMB": "左摇杆按下",
        "RIGHT_THUMB": "右摇杆按下",
        "BACK": "BACK",
        "START": "START",
        "GUIDE": "GUIDE",
        "TOUCHPAD": "(可能无)",
        "EDGE_FN1": "(可能无)",
        "EDGE_FN2": "(可能无)",
        "EDGE_RB1": "(可能无)",
        "EDGE_RB2": "(可能无)",
        "TRIGGER_LEFT": "左扳机",
        "TRIGGER_RIGHT": "右扳机",
    },
}


# ==================== pygame 按键索引映射 ====================
# !!! 重要 !!!
# pygame 在不同手柄上的 button index 完全不同：
# 1. 对于 XBOX 风格手柄（XInput 协议），pygame 暴露的是 Joystick API（不是 SDL GameController），
#    button 索引与 SDL GameController 不同
# 2. 对于 PS 系列（DualShock/DualSense），pygame 走 SDL GameController 抽象，
#    与 SDL GameController 文档一致
# 所以需要分别维护两套映射表


# XBOX 风格手柄（包括天剑等 XInput 协议手柄）的 pygame Joystick button 索引
# 对应 Windows 下 XInput 协议手柄通过 pygame 时的实际行为
PYGAME_BUTTON_TO_LOGICAL_XBOX = {
    0: "ACTION_SOUTH",      # A
    1: "ACTION_EAST",       # B
    2: "ACTION_WEST",       # X
    3: "ACTION_NORTH",      # Y
    4: "LEFT_SHOULDER",     # LB ← 关键！
    5: "RIGHT_SHOULDER",    # RB ← 关键！修复 v2.0 bug
    6: "BACK",              # BACK / View
    7: "START",             # START / Menu
    8: "LEFT_THUMB",        # L3
    9: "RIGHT_THUMB",       # R3
    10: "GUIDE",            # XBOX Guide 键（少数手柄会暴露）
}


# PS 系列手柄（DualSense / DualSense Edge / DualShock 4）pygame SDL GameController button 索引
# 参考：https://wiki.libsdl.org/SDL2/SDL_GameControllerButton
PYGAME_BUTTON_TO_LOGICAL_PS = {
    0: "ACTION_SOUTH",      # × / Cross
    1: "ACTION_EAST",       # ○ / Circle
    2: "ACTION_WEST",       # □ / Square
    3: "ACTION_NORTH",      # △ / Triangle
    4: "BACK",              # SHARE / CREATE
    5: "GUIDE",             # PS Home
    6: "START",             # OPTIONS
    7: "LEFT_THUMB",        # L3
    8: "RIGHT_THUMB",       # R3
    9: "LEFT_SHOULDER",     # L1
    10: "RIGHT_SHOULDER",   # R1
    11: "DPAD_UP",
    12: "DPAD_DOWN",
    13: "DPAD_LEFT",
    14: "DPAD_RIGHT",
    15: "TOUCHPAD",         # 触摸板按下
    # DualSense Edge 背键
    16: "EDGE_FN1",
    17: "EDGE_FN2",
    18: "EDGE_RB1",
    19: "EDGE_RB2",
    20: "EDGE_RB1",         # 备用
    21: "EDGE_RB2",
}


# Switch Pro Controller（基于 SDL GameController，但部分手柄 ABXY 位置和 XBOX 不同）
PYGAME_BUTTON_TO_LOGICAL_SWITCH = {
    0: "ACTION_SOUTH",      # B（Switch 的下方按键）
    1: "ACTION_EAST",       # A
    2: "ACTION_WEST",       # Y
    3: "ACTION_NORTH",      # X
    4: "BACK",              # -
    5: "GUIDE",
    6: "START",             # +
    7: "LEFT_THUMB",
    8: "RIGHT_THUMB",
    9: "LEFT_SHOULDER",     # L
    10: "RIGHT_SHOULDER",   # R
    11: "DPAD_UP",
    12: "DPAD_DOWN",
    13: "DPAD_LEFT",
    14: "DPAD_RIGHT",
}


# 通用兜底（按 XBOX 风格猜测，更适合"未知 XInput 兼容手柄"）
PYGAME_BUTTON_TO_LOGICAL_GENERIC = PYGAME_BUTTON_TO_LOGICAL_XBOX


def get_pygame_button_map(layout: str) -> dict:
    """根据布局返回对应的 pygame button → 逻辑名映射表"""
    if layout == LAYOUT_XBOX:
        return PYGAME_BUTTON_TO_LOGICAL_XBOX
    if layout in (LAYOUT_PS, LAYOUT_PS_EDGE):
        return PYGAME_BUTTON_TO_LOGICAL_PS
    if layout == LAYOUT_SWITCH:
        return PYGAME_BUTTON_TO_LOGICAL_SWITCH
    return PYGAME_BUTTON_TO_LOGICAL_GENERIC


# 旧的统一映射表（向后兼容用，但不推荐直接使用）
SDL_BUTTON_TO_LOGICAL = PYGAME_BUTTON_TO_LOGICAL_PS


# ==================== XInput 按键映射 ====================
XINPUT_BUTTON_TO_LOGICAL = {
    "A": "ACTION_SOUTH",
    "B": "ACTION_EAST",
    "X": "ACTION_WEST",
    "Y": "ACTION_NORTH",
    "DPAD_UP": "DPAD_UP",
    "DPAD_DOWN": "DPAD_DOWN",
    "DPAD_LEFT": "DPAD_LEFT",
    "DPAD_RIGHT": "DPAD_RIGHT",
    "LEFT_SHOULDER": "LEFT_SHOULDER",
    "RIGHT_SHOULDER": "RIGHT_SHOULDER",
    "LEFT_THUMB": "LEFT_THUMB",
    "RIGHT_THUMB": "RIGHT_THUMB",
    "BACK": "BACK",
    "START": "START",
}


# ==================== 数据类 ====================

@dataclass
class ControllerInfo:
    """单个手柄信息"""
    slot: int                    # 0-3
    name: str                    # 显示名，如 "DualSense Edge Wireless Controller"
    protocol: str                # PROTO_PYGAME / PROTO_XINPUT
    layout: str                  # LAYOUT_XBOX / LAYOUT_PS_EDGE / ...
    guid: str = ""               # pygame 的 GUID，XInput 没有
    handle: Any = None           # 实际句柄（pygame.Joystick 或 XInput 索引）
    num_axes: int = 0
    num_buttons: int = 0
    num_hats: int = 0
    is_active: bool = True       # 是否仍在线（被拔出后变 False）

    def display_string(self) -> str:
        """给 GUI 显示的字符串"""
        proto = "pygame" if self.protocol == PROTO_PYGAME else "XInput"
        return f"{self.name} [{proto}]"


@dataclass
class ControllerState:
    """单帧的统一状态"""
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    lt: float = 0.0
    rt: float = 0.0
    buttons: dict[str, bool] = field(default_factory=dict)


# ==================== 后端实现 ====================

class _PygameBackend:
    """pygame 实现"""

    def __init__(self):
        self._initialized = False
        self._available = self._try_init()

    def _try_init(self) -> bool:
        try:
            import pygame
            pygame.init()
            pygame.joystick.init()
            self._initialized = True
            return True
        except ImportError:
            return False
        except Exception as e:
            print(f"[警告] pygame 初始化失败: {e}")
            return False

    def is_available(self) -> bool:
        return self._available

    def scan(self) -> list[dict]:
        """扫描所有 pygame 识别的手柄，返回原始信息"""
        if not self._available:
            return []
        try:
            import pygame
            # 必须重新初始化 joystick 系统才能识别新插入的设备
            pygame.joystick.quit()
            pygame.joystick.init()

            results = []
            count = pygame.joystick.get_count()
            for i in range(count):
                try:
                    j = pygame.joystick.Joystick(i)
                    j.init()
                    name = j.get_name()
                    guid = j.get_guid() if hasattr(j, "get_guid") else ""
                    results.append({
                        "index": i,
                        "name": name,
                        "guid": guid,
                        "handle": j,
                        "num_axes": j.get_numaxes(),
                        "num_buttons": j.get_numbuttons(),
                        "num_hats": j.get_numhats(),
                    })
                except Exception as e:
                    print(f"[警告] pygame 手柄 {i} 初始化失败: {e}")
            return results
        except Exception as e:
            print(f"[警告] pygame 扫描失败: {e}")
            return []

    def detect_layout(self, name: str, num_buttons: int) -> str:
        """根据手柄名称和按键数判断布局"""
        n = name.lower()
        if "dualsense edge" in n or "ps5 edge" in n:
            return LAYOUT_PS_EDGE
        if any(k in n for k in [
            "dualsense", "playstation", "ps5", "ps4", "ps3",
            "dualshock", "wireless controller",
        ]):
            # 普通 PS 手柄但按键多于 16 个 → 可能是 Edge
            if num_buttons >= 17:
                return LAYOUT_PS_EDGE
            return LAYOUT_PS
        if any(k in n for k in [
            "xbox", "x-box", "microsoft", "xinput",
        ]):
            return LAYOUT_XBOX
        if any(k in n for k in [
            "switch", "joy-con", "joycon", "nintendo", "pro controller",
        ]):
            return LAYOUT_SWITCH
        return LAYOUT_GENERIC

    def read_state(self, info: ControllerInfo) -> ControllerState:
        """从指定手柄读一帧"""
        try:
            import pygame
            # 必须调用 pump 让 SDL 内部更新 joystick 状态
            # 同时清空事件队列，防止事件堆积导致内存占用增加
            pygame.event.pump()
            # 清空事件队列（我们不处理事件，只读状态）
            pygame.event.clear()
            j = info.handle
            state = ControllerState()

            # 摇杆轴：pygame SDL2 GameController 标准
            # axis 0/1 = 左摇杆 X/Y，axis 2/3 = 右摇杆 X/Y，axis 4/5 = LT/RT
            n = info.num_axes
            if n >= 1:
                state.lx = float(j.get_axis(0))
            if n >= 2:
                # pygame Y 轴方向：上为 -1，下为 +1（XInput 是反的，统一成 XInput 风格）
                state.ly = -float(j.get_axis(1))
            if n >= 3:
                state.rx = float(j.get_axis(2))
            if n >= 4:
                state.ry = -float(j.get_axis(3))
            if n >= 5:
                # 扳机：pygame 给 -1（未按）到 +1（按到底），归一化到 0~1
                lt_raw = float(j.get_axis(4))
                state.lt = (lt_raw + 1.0) / 2.0
            if n >= 6:
                rt_raw = float(j.get_axis(5))
                state.rt = (rt_raw + 1.0) / 2.0

            # 按键 - 根据手柄布局选用对应的 button 映射表
            # 这是 v2.0 关键修复：XBOX 手柄通过 pygame 走 Joystick API，
            # button index 和 PS 手柄通过 SDL GameController 抽象不一样
            button_map = get_pygame_button_map(info.layout)
            buttons = {}
            for i in range(info.num_buttons):
                pressed = bool(j.get_button(i))
                logical = button_map.get(i)
                if logical:
                    buttons[logical] = pressed
            # DPAD 通常是 hat（在某些手柄上），如果 hat > 0 就用 hat
            if info.num_hats > 0:
                hx, hy = j.get_hat(0)
                # pygame hat：上 +1，下 -1
                buttons["DPAD_UP"] = hy > 0
                buttons["DPAD_DOWN"] = hy < 0
                buttons["DPAD_LEFT"] = hx < 0
                buttons["DPAD_RIGHT"] = hx > 0

            # 扳机当按键
            buttons["TRIGGER_LEFT"] = state.lt > 0.5
            buttons["TRIGGER_RIGHT"] = state.rt > 0.5

            # 补齐所有逻辑按键（默认 False）
            for logical in LOGICAL_BUTTONS:
                buttons.setdefault(logical, False)

            state.buttons = buttons
            return state
        except Exception as e:
            return ControllerState()


class _XInputBackend:
    """XInput 实现（保留作为 XBOX 兼容设备的备选）"""

    def __init__(self):
        self._available = False
        try:
            import XInput
            self._XInput = XInput
            self._available = True
        except ImportError:
            self._XInput = None

    def is_available(self) -> bool:
        return self._available

    def scan(self) -> list[dict]:
        """扫描 XInput 0-3 槽位"""
        if not self._available:
            return []
        results = []
        try:
            connected = self._XInput.get_connected()
            for i in range(4):
                if connected[i]:
                    results.append({
                        "index": i,
                        "name": f"XBOX 360 兼容控制器 #{i}",
                        "guid": f"xinput_{i}",
                        "handle": i,
                        "num_axes": 6,
                        "num_buttons": 14,
                        "num_hats": 0,
                    })
        except Exception as e:
            print(f"[警告] XInput 扫描失败: {e}")
        return results

    def read_state(self, info: ControllerInfo) -> ControllerState:
        if not self._available:
            return ControllerState()
        try:
            idx = info.handle
            xinput_state = self._XInput.get_state(idx)
            (lx, ly), (rx, ry) = self._XInput.get_thumb_values(xinput_state)
            lt, rt = self._XInput.get_trigger_values(xinput_state)
            buttons_raw = self._XInput.get_button_values(xinput_state)

            state = ControllerState(
                lx=float(lx), ly=float(ly), rx=float(rx), ry=float(ry),
                lt=float(lt), rt=float(rt),
            )
            buttons = {}
            for xinput_name, logical in XINPUT_BUTTON_TO_LOGICAL.items():
                buttons[logical] = bool(buttons_raw.get(xinput_name, False))
            buttons["TRIGGER_LEFT"] = lt > 0.5
            buttons["TRIGGER_RIGHT"] = rt > 0.5
            # XInput 没有 GUIDE/TOUCHPAD/EDGE_*，全为 False
            for logical in LOGICAL_BUTTONS:
                buttons.setdefault(logical, False)
            state.buttons = buttons
            return state
        except Exception:
            return ControllerState()


# ==================== 控制器管理器 ====================

class ControllerManager:
    """4 槽位管理器"""

    def __init__(self):
        self._pygame = _PygameBackend()
        self._xinput = _XInputBackend()
        # 4 个槽位，初始全空
        self.slots: list[Optional[ControllerInfo]] = [None] * MAX_SLOTS
        self._current_slot: Optional[int] = None  # 用户当前选中的槽位

    def has_pygame(self) -> bool:
        return self._pygame.is_available()

    def has_xinput(self) -> bool:
        return self._xinput.is_available()

    def scan_and_assign(self) -> str:
        """重新扫描并分配槽位。返回一段说明文字（适合显示在 GUI）"""
        # 1. 扫描两个后端
        pygame_devs = self._pygame.scan() if self._pygame.is_available() else []
        xinput_devs = self._xinput.scan() if self._xinput.is_available() else []

        # 2. 去重：pygame 已识别为 XBOX 风格的手柄数 = XInput 看到的设备数时，
        #    很可能是同一批设备（XInput 协议手柄被两个驱动都看到），
        #    保留 pygame 版本（方便 button 映射用我们的 PYGAME_*_XBOX 表读 RB/LB）
        pygame_xbox_count = sum(
            1 for d in pygame_devs
            if any(k in d["name"].lower() for k in ["xbox", "x-box", "xinput",
                   "controller for windows"]))

        xinput_filtered = []
        if pygame_xbox_count >= len(xinput_devs):
            # pygame 完全覆盖了 XInput 设备，丢弃 XInput 重复项
            pass
        else:
            # pygame 没全部识别到，可能有部分手柄只能用 XInput
            # 简单策略：只跳过前 N 个（N = pygame_xbox_count），剩下的用 XInput
            xinput_filtered = xinput_devs[pygame_xbox_count:]

        # 3. 合并候选列表（pygame 优先排前面）
        candidates: list[tuple[str, dict]] = []
        for d in pygame_devs:
            candidates.append((PROTO_PYGAME, d))
        for d in xinput_filtered:
            candidates.append((PROTO_XINPUT, d))

        # 4. 保持已有槽位中"仍然在线"的设备
        #    通过 GUID（pygame）或 index（XInput）匹配
        new_slots: list[Optional[ControllerInfo]] = [None] * MAX_SLOTS
        used_candidates: set[int] = set()

        # 先把现有槽位中还在线的保留下来
        for slot_idx, existing in enumerate(self.slots):
            if existing is None:
                continue
            for cand_idx, (proto, dev) in enumerate(candidates):
                if cand_idx in used_candidates:
                    continue
                if proto == existing.protocol:
                    if proto == PROTO_PYGAME and dev["guid"] == existing.guid and dev["guid"]:
                        # GUID 匹配
                        existing.handle = dev["handle"]  # 句柄可能变了
                        existing.num_axes = dev["num_axes"]
                        existing.num_buttons = dev["num_buttons"]
                        existing.num_hats = dev["num_hats"]
                        existing.is_active = True
                        new_slots[slot_idx] = existing
                        used_candidates.add(cand_idx)
                        break
                    elif proto == PROTO_XINPUT and dev["index"] == existing.handle:
                        existing.is_active = True
                        new_slots[slot_idx] = existing
                        used_candidates.add(cand_idx)
                        break

        # 然后把新增的设备填入空槽位
        for cand_idx, (proto, dev) in enumerate(candidates):
            if cand_idx in used_candidates:
                continue
            # 找第一个空槽位
            free_idx = next((i for i, s in enumerate(new_slots) if s is None), None)
            if free_idx is None:
                # 槽位已满
                continue

            if proto == PROTO_PYGAME:
                layout = self._pygame.detect_layout(dev["name"], dev["num_buttons"])
            else:
                layout = LAYOUT_XBOX

            info = ControllerInfo(
                slot=free_idx,
                name=dev["name"],
                protocol=proto,
                layout=layout,
                guid=dev["guid"],
                handle=dev["handle"],
                num_axes=dev["num_axes"],
                num_buttons=dev["num_buttons"],
                num_hats=dev["num_hats"],
                is_active=True,
            )
            new_slots[free_idx] = info

        self.slots = new_slots

        # 5. 维护当前选中槽位（如果原来选中的槽位变空了，自动选第一个非空槽位）
        if self._current_slot is not None and self.slots[self._current_slot] is None:
            self._current_slot = None
        if self._current_slot is None:
            for i, s in enumerate(self.slots):
                if s is not None:
                    self._current_slot = i
                    break

        # 6. 返回扫描总结
        active_count = sum(1 for s in self.slots if s is not None)
        overflow = len(candidates) - active_count
        msg_parts = [f"扫描完成：检测到 {active_count} 个手柄"]
        if overflow > 0:
            msg_parts.append(
                f"⚠ 还有 {overflow} 个手柄未显示（槽位已满），请拔出未使用的手柄后重新扫描")
        return "，".join(msg_parts)

    def get_slot(self, slot_idx: int) -> Optional[ControllerInfo]:
        if 0 <= slot_idx < MAX_SLOTS:
            return self.slots[slot_idx]
        return None

    def get_current_slot(self) -> Optional[int]:
        return self._current_slot

    def set_current_slot(self, slot_idx: Optional[int]) -> None:
        if slot_idx is None or self.slots[slot_idx] is not None:
            self._current_slot = slot_idx

    def get_current_controller(self) -> Optional[ControllerInfo]:
        if self._current_slot is None:
            return None
        return self.slots[self._current_slot]

    def read_state(self, info: ControllerInfo) -> ControllerState:
        """从指定手柄读一帧"""
        if info.protocol == PROTO_PYGAME:
            return self._pygame.read_state(info)
        elif info.protocol == PROTO_XINPUT:
            return self._xinput.read_state(info)
        return ControllerState()


# ==================== 工具函数 ====================

def get_button_display_name(layout: str, logical_button: str) -> str:
    """根据手柄布局获取按键的中文显示名"""
    return BUTTON_DISPLAY_NAMES.get(layout, BUTTON_DISPLAY_NAMES[LAYOUT_GENERIC]).get(
        logical_button, logical_button)


def get_button_options_for_layout(layout: str) -> list[tuple[str, str]]:
    """返回 [(显示名, 逻辑代码), ...]，用于 GUI 下拉框"""
    options = []
    # 屏蔽不存在的按键（显示名是 "(无)"）
    names = BUTTON_DISPLAY_NAMES.get(layout, BUTTON_DISPLAY_NAMES[LAYOUT_GENERIC])
    for logical in LOGICAL_BUTTONS:
        display = names.get(logical, logical)
        if display.startswith("(") and display.endswith(")"):
            continue  # 跳过 "(无)" 之类
        options.append((display, logical))
    return options


# ==================== 自测 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("控制器后端自测")
    print("=" * 60)
    mgr = ControllerManager()
    print(f"pygame 可用: {mgr.has_pygame()}")
    print(f"XInput 可用: {mgr.has_xinput()}")
    print()
    print(mgr.scan_and_assign())
    print()
    for i, slot in enumerate(mgr.slots):
        if slot is None:
            print(f"  槽位 {i+1}: [空]")
        else:
            print(f"  槽位 {i+1}: {slot.display_string()}  布局={slot.layout}")
    print()

    # 如果有手柄，读 5 次状态
    cur = mgr.get_current_controller()
    if cur is not None:
        print(f"测试读取 {cur.name} 5 次：")
        for i in range(5):
            s = mgr.read_state(cur)
            pressed = [k for k, v in s.buttons.items() if v]
            print(f"  [{i+1}] L=({s.lx:+.2f},{s.ly:+.2f}) "
                  f"R=({s.rx:+.2f},{s.ry:+.2f}) "
                  f"LT={s.lt:.2f} RT={s.rt:.2f} "
                  f"按键={pressed}")
            time.sleep(0.5)
