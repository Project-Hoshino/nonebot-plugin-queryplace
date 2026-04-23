"""
配置和工具模块
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import base64

from nonebot import get_driver

driver = get_driver()
plugin_config = driver.config

NEARCAADE_TOKEN = getattr(plugin_config, "nearcade_token", "nk_eimMHQaX7F6g0LlLg6ihhweRQTyLxUTVKHuIdijadC") or "nk_eimMHQaX7F6g0LlLg6ihhweRQTyLxUTVKHuIdijadC"

MACHINE_CALC_MODE = getattr(plugin_config, "machine_calc_mode", "all") or "all"


def _parse_bool(value: Any, default: bool = True) -> bool:
    """解析布尔值配置"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true"):
            return True
        if normalized in ("false"):
            return False
    return default


USE_ONLINE_DATABASE = _parse_bool(getattr(plugin_config, "use_online_database", True), True)

# 数据目录配置
BOT_DATA_DIR = Path.cwd() / "data" / "nonebot_plugin_queryplace"
BOT_DATA_DIR.mkdir(parents=True, exist_ok=True)
ARCADE_DATA_FILE = BOT_DATA_DIR / "arcades.json"
LOCAL_ARCADE_FILE = BOT_DATA_DIR / "arcades-local.json"
HISTORY_DATA_FILE = BOT_DATA_DIR / "history.json"

# 字体配置
PLUGIN_DIR = Path(__file__).parent.parent  # 指向插件根目录
FONT_FILE = PLUGIN_DIR / "SourceHanSansSC-Bold.otf"


def _get_font(size: int = 20) -> ImageFont.FreeTypeFont:
    """获取渲染字体，优先使用插件目录下的 SourceHanSansSC-Bold.otf"""
    if FONT_FILE.exists():
        try:
            return ImageFont.truetype(str(FONT_FILE), size)
        except Exception as e:
            print(f"Failed to load custom font {FONT_FILE}: {e}")
            return ImageFont.load_default()
    else:
        print(f"Font file not found: {FONT_FILE}, using default font")
        return ImageFont.load_default()


def text_to_image(text: str, font_size: int = 20) -> Image.Image:
    """将文本转换为图片"""
    font = _get_font(font_size)
    padding = 10
    margin = 4
    lines = text.strip().split('\n')
    max_width = 0
    b = 0
    for line in lines:
        l, t, r, b = font.getbbox(line)
        max_width = max(max_width, r)
    wa = max_width + padding * 2
    ha = b * len(lines) + margin * (len(lines) - 1) + padding * 2
    im = Image.new('RGB', (wa, ha), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)
    for index, line in enumerate(lines):
        draw.text((padding, padding + index * (margin + b)), line, font=font, fill=(0, 0, 0))
    return im


def image_to_base64(img: Image.Image, format='PNG') -> str:
    """将图片转换为 base64 字符串"""
    output_buffer = BytesIO()
    img.save(output_buffer, format)
    byte_data = output_buffer.getvalue()
    base64_str = base64.b64encode(byte_data).decode()
    return 'base64://' + base64_str


# 文件锁管理器
class FileLockManager:
    """文件锁管理器，防止并发写入导致文件损坏"""
    def __init__(self):
        self.locks = {}
        self.global_lock = threading.Lock()
    
    def get_lock(self, file_path: str):
        with self.global_lock:
            if file_path not in self.locks:
                self.locks[file_path] = threading.Lock()
            return self.locks[file_path]


file_lock_manager = FileLockManager()


@contextmanager
def safe_file_write(file_path: Path, mode: str = "w", encoding: str = "utf-8"):
    """安全的文件写入上下文管理器，防止并发写入导致文件损坏"""
    lock = file_lock_manager.get_lock(str(file_path))
    with lock:
        temp_file = file_path.with_suffix(file_path.suffix + '.tmp')
        with temp_file.open(mode, encoding=encoding) as f:
            yield f
        # 原子性替换原文件
        temp_file.replace(file_path)


def _get_current_day_key() -> str:
    """
    获取当前日期的键值（以每天凌晨 4 点为界）
    例如：如果当前时间是凌晨 3 点，则返回昨天的日期
    如果当前时间是凌晨 4 点或之后，则返回今天的日期
    """
    now = datetime.now()
    if now.hour >= 4:
        return now.date().isoformat()
    else:
        return (now - timedelta(days=1)).date().isoformat()


def _is_same_day(timestamp: str) -> bool:
    """
    判断给定的时间戳是否属于当前游戏日（以每天凌晨 4 点为界）
    """
    try:
        last_updated = datetime.fromisoformat(timestamp)
        now = datetime.now()
        
        # 获取当前游戏日（基于 4 点为界的日期）
        if now.hour >= 4:
            current_game_day = now.date()
        else:
            current_game_day = (now - timedelta(days=1)).date()
        
        # 获取更新时间所属的游戏日
        if last_updated.hour >= 4:
            update_game_day = last_updated.date()
        else:
            update_game_day = (last_updated - timedelta(days=1)).date()
        
        return current_game_day == update_game_day
    except Exception:
        return False


def _today_iso() -> str:
    """获取当前时间的 ISO 格式字符串"""
    return datetime.now().isoformat()


def _get_machine_count(arcade: Dict[str, Any]) -> int:
    """根据配置模式获取机台数量"""
    if MACHINE_CALC_MODE == "mai":
        return arcade.get('mainum', 0)
    elif MACHINE_CALC_MODE == "chu":
        return arcade.get('chuninum', 0)
    else:  # "all" or default
        return arcade.get('mainum', 0) + arcade.get('chuninum', 0)


def _format_count_with_avg(person: int, arcade: Optional[Dict[str, Any]] = None) -> str:
    """格式化人数显示，包括机均计算"""
    count_str = f"{person}卡"
    if arcade and MACHINE_CALC_MODE != "off":
        machine_count = _get_machine_count(arcade)
        if machine_count > 1:
            avg = person // machine_count
            count_str += f" 机均{avg}卡"
    return count_str