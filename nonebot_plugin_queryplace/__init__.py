from __future__ import annotations

import json
import re
import aiohttp
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading
from contextlib import contextmanager

from nonebot import on_message, get_driver
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import base64

driver = get_driver()
plugin_config = driver.config

MACHINE_CALC_MODE = getattr(plugin_config, "machine_calc_mode", "all") or "all"

def _parse_bool(value: Any, default: bool = True) -> bool:
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

__plugin_usage__ = """
查询卡数插件（NoneBot2）
支持机台类型计算机均人数（配置在 NoneBot 配置项中）：
- mai: 机均人数将以舞萌DX的机台数量进行计算
- chu: 机均人数将以中二节奏的机台数量进行计算  
- all 或留空: 机均人数将以舞萌DX和中二节奏的机台总数进行计算

支持本地/在线机台数据切换（配置在 NoneBot 配置项中）：
- use_online_database: true 使用在线API获取机厅数据
- use_online_database: false 使用本地数据

指令：
- 机厅名++：增加 1 卡
- 机厅名--：减少 1 卡
- 机厅名+N：增加 N 卡
- 机厅名-N：减少 N 卡
- 机厅名N：直接设置卡数为 N
- 机厅名=N：直接设置卡数为 N
- 机厅名几/j/J：查询该机厅卡数（包括"有几人"、"有多少人"等表达方式）
- 订阅机厅名：订阅机厅（仅限群管理员）
- 取消订阅机厅名：取消订阅机厅（仅限群管理员）
- 添加别名 机厅名 别名：为机厅添加别名（仅限群管理员）
- 删除别名 机厅名 别名：删除机厅别名（仅限群管理员）
- 添加机厅 <店名> <地址> <舞萌DX机台数量> <中二节奏机台数量> <简称>：添加机厅信息（仅限群管理员）
- 删除机厅 <店名>：删除机厅信息（仅限群管理员）
- j 或 几 或 jtj：查询本群所有机厅卡数
- 查找机厅 <关键词>：使用关键词查找机厅
- 机厅名 有谁：查看该机厅的历史记录
- 机厅全名/简称在哪：查询机厅地址
"""

def text_to_image(text: str, font_size: int = 20) -> Image.Image:
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
    output_buffer = BytesIO()
    img.save(output_buffer, format)
    byte_data = output_buffer.getvalue()
    base64_str = base64.b64encode(byte_data).decode()
    return 'base64://' + base64_str

BOT_DATA_DIR = Path.cwd() / "data" / "nonebot_plugin_queryplace"
BOT_DATA_DIR.mkdir(parents=True, exist_ok=True)
ARCADE_DATA_FILE = BOT_DATA_DIR / "arcades.json"
LOCAL_ARCADE_FILE = BOT_DATA_DIR / "arcades-local.json"
HISTORY_DATA_FILE = BOT_DATA_DIR / "history.json"

# 字体配置
PLUGIN_DIR = Path(__file__).parent
FONT_FILE = PLUGIN_DIR / "SourceHanSansSC-Bold.otf"

def _get_font(size: int = 20) -> ImageFont.FreeTypeFont:
    """获取渲染字体，优先使用插件目录下的SourceHanSansSC-Bold.otf"""
    if FONT_FILE.exists():
        try:
            return ImageFont.truetype(str(FONT_FILE), size)
        except Exception as e:
            print(f"Failed to load custom font {FONT_FILE}: {e}")
            return ImageFont.load_default()
    else:
        print(f"Font file not found: {FONT_FILE}, using default font")
        return ImageFont.load_default()

# 文件锁管理器
class FileLockManager:
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
    获取当前日期的键值（以每天凌晨4点为界）
    例如：如果当前时间是凌晨3点，则返回昨天的日期
    如果当前时间是凌晨4点或之后，则返回今天的日期
    """
    now = datetime.now()
    if now.hour >= 4:
        # 如果当前时间 >= 4点，返回今天的日期
        return now.date().isoformat()
    else:
        # 如果当前时间 < 4点，返回昨天的日期
        return (now - timedelta(days=1)).date().isoformat()

def _is_same_day(timestamp: str) -> bool:
    """
    判断给定的时间戳是否属于当前游戏日（以每天凌晨4点为界）
    """
    try:
        last_updated = datetime.fromisoformat(timestamp)
        now = datetime.now()
        
        # 获取当前游戏日（基于4点为界的日期）
        if now.hour >= 4:
            current_game_day = now.date()  # 当前时间 >= 4点，属于今天的游戏日
        else:
            current_game_day = (now - timedelta(days=1)).date()  # 当前时间 < 4点，属于昨天的游戏日
        
        # 获取更新时间所属的游戏日
        if last_updated.hour >= 4:
            update_game_day = last_updated.date()  # 更新时间 >= 4点，属于当天的游戏日
        else:
            update_game_day = (last_updated - timedelta(days=1)).date()  # 更新时间 < 4点，属于前一天的游戏日
        
        return current_game_day == update_game_day
    except Exception:
        return False

def _has_today_activity(arcade_name: str) -> bool:
    """
    检查指定机厅今天是否有活动（更新记录）
    """
    today_str = _get_current_day_key()
    if today_str in history_data.history and arcade_name in history_data.history[today_str]:
        return len(history_data.history[today_str][arcade_name]) > 0
    return False

# History data structure
class HistoryData:
    def __init__(self):
        self.history: Dict[str, List[Dict[str, Any]]] = {}
        self.last_reset_date = None

    def load_history(self):
        if HISTORY_DATA_FILE.exists():
            try:
                with HISTORY_DATA_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.history = data.get("history", {})
                    self.last_reset_date = data.get("last_reset_date")
            except Exception:
                self.history = {}
                self.last_reset_date = None
        else:
            self.history = {}
            self.last_reset_date = None

    def save_history(self):
        data = {
            "history": self.history,
            "last_reset_date": self.last_reset_date
        }
        try:
            with safe_file_write(HISTORY_DATA_FILE) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史数据失败: {e}")

    def add_record(self, arcade_name: str, action: str, user: str, count: int = None, old_count: int = None, new_count: int = None):
        """添加历史记录"""
        today_str = _get_current_day_key()  # 使用统一的日期键
        if today_str not in self.history:
            self.history[today_str] = {}
        
        if arcade_name not in self.history[today_str]:
            self.history[today_str][arcade_name] = []
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        record = {
            "time": timestamp,
            "user": user,
            "action": action,
            "count": count,
            "old_count": old_count,
            "new_count": new_count
        }
        
        self.history[today_str][arcade_name].append(record)
        self.save_history()

    def get_records(self, arcade_name: str) -> List[Dict[str, Any]]:
        """获取特定机厅的今日历史记录"""
        today_str = _get_current_day_key()  # 使用统一的日期键
        if today_str in self.history and arcade_name in self.history[today_str]:
            return self.history[today_str][arcade_name]
        return []

    def clear_today_history(self):
        """清空今日历史记录"""
        today_str = _get_current_day_key()  # 使用统一的日期键
        if today_str in self.history:
            self.history.pop(today_str, None)
            self.save_history()
            print(f"已清空 {today_str} 的历史记录")

    def clear_all_history(self):
        """清空所有历史记录"""
        self.history = {}
        self.save_history()

history_data = HistoryData()

# Query cache to track recent queries
class QueryCache:
    def __init__(self):
        self.cache = {}  # {group_id: {'timestamp': datetime, 'show_all': bool}}
    
    def update_query_time(self, group_id: str):
        """更新群组的查询时间"""
        self.cache[group_id] = {
            'timestamp': datetime.now(),
            'show_all': True  # 下次查询将显示全部
        }
    
    def should_show_all(self, group_id: str) -> bool:
        """判断是否应该显示全部机厅（10秒内再次查询）"""
        if group_id not in self.cache:
            return False
        
        last_query_time = self.cache[group_id]['timestamp']
        elapsed = datetime.now() - last_query_time
        
        # 如果距离上次查询在10秒内，则显示全部
        if elapsed.total_seconds() <= 10:
            return True
        else:
            # 超过10秒则清除缓存
            del self.cache[group_id]
            return False

query_cache = QueryCache()

# Arcade data structure
class ArcadeData:
    def __init__(self):
        self.arcades: List[Dict[str, Any]] = []
        self.last_update = None
        self.current_file = ARCADE_DATA_FILE  # 默认使用arcades.json
        self.last_reset_time_file = BOT_DATA_DIR / "last_reset_time.txt"  # 记录最后重置时间的文件

    def create_local_template(self):
        """创建本地数据库模板文件"""
        template_data = {
            "arcades": [
                {
                    "name": "示例机厅名称",
                    "address": "示例地址",
                    "mall": "示例商场",
                    "province": "示例省份",
                    "mainum": 0,
                    "chuninum": 0,
                    "id": "example_id",
                    "alias": ["别名1", "别名2"],
                    "group": [],
                    "person": 0,
                    "by": "",
                    "time": ""
                }
            ],
            "last_update": datetime.now().isoformat(),
            "template_info": {
                "description": "这是本地机厅数据模板文件",
                "instructions": [
                    "name: 机厅名称（必填）",
                    "address: 机厅地址（可选）",
                    "mall: 商场名称（可选）",
                    "province: 省份（可选）",
                    "mainum: 舞萌DX机台数量（可选）",
                    "chuninum: 中二节奏机台数量（可选）",
                    "id: 机厅唯一标识符",
                    "alias: 别名列表（可选）",
                    "group: 已订阅该机厅的群组列表（由程序自动维护）",
                    "person: 当前卡数（由程序自动维护）",
                    "by: 最后更新者（由程序自动维护）",
                    "time: 最后更新时间（由程序自动维护）"
                ]
            }
        }
        
        try:
            with safe_file_write(LOCAL_ARCADE_FILE) as f:
                json.dump(template_data, f, ensure_ascii=False, indent=2)
            print(f"已创建本地数据库模板文件: {LOCAL_ARCADE_FILE}")
            print("请编辑此文件以添加您的机厅数据，然后重启机器人。")
            return True
        except Exception as e:
            print(f"创建本地数据库模板失败: {e}")
            return False

    async def load_arcades(self):
        # 根据配置决定加载哪个文件
        if not USE_ONLINE_DATABASE:
            # 检查本地文件是否存在，如果不存在则创建模板
            if not LOCAL_ARCADE_FILE.exists():
                print(f"本地数据库文件不存在: {LOCAL_ARCADE_FILE}")
                self.create_local_template()
                # 提示用户编辑数据库
                print("\n" + "="*50)
                print("本地数据库文件已创建为模板，请按以下步骤操作：")
                print(f"1. 编辑文件: {LOCAL_ARCADE_FILE}")
                print("2. 修改模板中的示例数据为您实际的机厅信息")
                print("3. 保存文件后重启机器人")
                print("="*50 + "\n")
            
            self.current_file = LOCAL_ARCADE_FILE
        else:
            self.current_file = ARCADE_DATA_FILE
            
        if self.current_file.exists():
            try:
                with self.current_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 确保数据格式正确
                    raw_arcades = data.get("arcades", []) if isinstance(data, dict) else []
                    
                    # 验证数据结构，确保每个项目都是字典
                    validated_arcades = []
                    for item in raw_arcades:
                        if isinstance(item, dict):
                            # 确保必要字段存在
                            item.setdefault('name', '')
                            item.setdefault('address', '')
                            item.setdefault('mall', '')
                            item.setdefault('province', '')
                            item.setdefault('mainum', 0)
                            item.setdefault('chuninum', 0)
                            item.setdefault('id', '')
                            item.setdefault('alias', [])
                            item.setdefault('group', [])
                            item.setdefault('person', 0)
                            item.setdefault('by', '')
                            item.setdefault('time', '')
                            validated_arcades.append(item)
                        else:
                            print(f"警告：发现无效的机厅数据项，跳过: {item}")
                    
                    self.arcades = validated_arcades
                    self.last_update = data.get("last_update") if isinstance(data, dict) else None
            except Exception as e:
                print(f"加载机厅数据失败: {e}")
                self.arcades = []
        await self.update_arcades()

    async def update_arcades(self):
        if not USE_ONLINE_DATABASE:
            # Load from local ArcadeQueue data
            if LOCAL_ARCADE_FILE.exists():
                try:
                    with LOCAL_ARCADE_FILE.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # 正确解析本地数据结构，只处理 arcades 数组
                    raw_arcades = data.get("arcades", []) if isinstance(data, dict) else []
                    
                    # 验证数据结构，确保每个项目都是字典
                    validated_local_data = []
                    for item in raw_arcades:
                        if isinstance(item, dict):
                            # 确保必要字段存在
                            item.setdefault('name', '')
                            item.setdefault('address', '')
                            item.setdefault('mall', '')
                            item.setdefault('province', '')
                            item.setdefault('mainum', 0)
                            item.setdefault('chuninum', 0)
                            item.setdefault('id', '')
                            item.setdefault('alias', [])
                            item.setdefault('group', [])
                            item.setdefault('person', 0)
                            item.setdefault('by', '')
                            item.setdefault('time', '')
                            validated_local_data.append(item)
                        else:
                            print(f"警告：发现无效的本地机厅数据项，跳过: {item}")
                    
                    self.arcades = validated_local_data
                    self.last_update = data.get("last_update") if isinstance(data, dict) else datetime.now().isoformat()
                    # 确保使用本地文件
                    self.current_file = LOCAL_ARCADE_FILE
                    self._save_arcades()
                    print("Loaded arcades from local file")
                except Exception as e:
                    print(f"Failed to load local arcades: {e}")
            else:
                print("Local arcade file not found")
            return

        # Online mode
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                # Get maimai data
                async with session.get('http://wc.wahlap.net/maidx/rest/location') as resp:
                    if resp.status == 200:
                        maidata = await resp.json()
                    else:
                        maidata = None

                # Get chunithm data
                async with session.get('https://wc.wahlap.net/chunithm/rest/location') as resp:
                    if resp.status == 200:
                        chunidata = await resp.json()
                    else:
                        chunidata = None

            if maidata or chunidata:
                maidata_dict = {arc['id']: arc for arc in maidata} if maidata else {}
                chunidata_dict = {arc['id']: arc for arc in chunidata} if chunidata else {}

                arcades = []
                for _arc in maidata or []:
                    arcade_dict = {
                        'name': _arc['arcadeName'],
                        'address': _arc['address'],
                        'mall': _arc['mall'],
                        'province': _arc['province'],
                        'mainum': _arc['machineCount'],
                        'chuninum': chunidata_dict.get(_arc['id'], {}).get('machineCount', 0),
                        'id': _arc['id'],
                        'alias': [],
                        'group': [],
                        'person': 0,
                        'by': '',
                        'time': ''
                    }
                    arcades.append(arcade_dict)

                # 确保每个项目都有必要的字段
                validated_arcades = []
                for item in arcades:
                    if isinstance(item, dict):
                        item.setdefault('name', '')
                        item.setdefault('address', '')
                        item.setdefault('mall', '')
                        item.setdefault('province', '')
                        item.setdefault('mainum', 0)
                        item.setdefault('chuninum', 0)
                        item.setdefault('id', '')
                        item.setdefault('alias', [])
                        item.setdefault('group', [])
                        item.setdefault('person', 0)
                        item.setdefault('by', '')
                        item.setdefault('time', '')
                        validated_arcades.append(item)
                
                self.arcades = validated_arcades
                self.last_update = datetime.now().isoformat()
                # 确保使用在线数据文件
                self.current_file = ARCADE_DATA_FILE
                self._save_arcades()
                print("Updated arcades from online API")

        except Exception as e:
            print(f"Failed to update arcades: {e}")

    def _save_arcades(self):
        data = {
            "arcades": self.arcades,
            "last_update": self.last_update
        }
        try:
            with safe_file_write(self.current_file) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存机厅数据失败: {e}")

    def find_arcade_by_alias(self, name_or_alias: str) -> tuple[Optional[Dict[str, Any]], str]:
        """查找机厅并返回匹配的别名（如果有的话）"""
        for arcade in self.arcades:
            if isinstance(arcade, dict):  # 确保是字典
                if arcade.get('name') == name_or_alias:
                    return arcade, arcade['name']
                if name_or_alias in arcade.get('alias', []):
                    return arcade, name_or_alias
        return None, name_or_alias

    def find_arcade(self, name_or_alias: str) -> Optional[Dict[str, Any]]:
        arcade, _ = self.find_arcade_by_alias(name_or_alias)
        return arcade

    def is_subscribed(self, group_id: str, arcade_name: str) -> bool:
        arcade = self.find_arcade(arcade_name)
        if arcade and isinstance(arcade, dict):
            return int(group_id) in arcade.get('group', [])
        return False

    def subscribe(self, group_id: str, arcade_name: str) -> bool:
        arcade = self.find_arcade(arcade_name)
        if arcade and isinstance(arcade, dict):
            if int(group_id) not in arcade.get('group', []):
                arcade.setdefault('group', []).append(int(group_id))
                self._save_arcades()
                return True
        return False

    def unsubscribe(self, group_id: str, arcade_name: str) -> bool:
        arcade = self.find_arcade(arcade_name)
        if arcade and isinstance(arcade, dict):
            if int(group_id) in arcade.get('group', []):
                arcade['group'].remove(int(group_id))
                self._save_arcades()
                return True
        return False

    def delete_arcade(self, arcade_name: str) -> bool:
        """删除机厅"""
        arcade = self.find_arcade(arcade_name)
        if arcade and isinstance(arcade, dict):
            self.arcades.remove(arcade)
            self._save_arcades()
            return True
        return False

    def reset_daily_data(self):
        """重置每日数据 - 重置所有机厅的人数、时间和用户名"""
        for arcade in self.arcades:
            if isinstance(arcade, dict):
                arcade['person'] = 0  # 重置人数为0
                arcade['time'] = ''   # 清空时间
                arcade['by'] = ''     # 清空用户名
        self._save_arcades()
        print("每日数据重置完成")
        
        # 更新最后重置时间记录
        try:
            with open(self.last_reset_time_file, 'w', encoding='utf-8') as f:
                f.write(datetime.now().isoformat())
        except Exception as e:
            print(f"无法保存最后重置时间: {e}")

    def check_and_reset_if_needed(self):
        """检查是否需要重置数据（基于文件修改时间）"""
        # 检查最后重置时间文件是否存在
        if self.last_reset_time_file.exists():
            try:
                with open(self.last_reset_time_file, 'r', encoding='utf-8') as f:
                    last_reset_str = f.read().strip()
                    last_reset = datetime.fromisoformat(last_reset_str)
                    # 如果最后重置时间不是今天，则重置
                    if last_reset.date() != datetime.now().date():
                        print(f"检测到上次重置时间是 {last_reset.date()}，今天是 {datetime.now().date()}，需要重置数据")
                        self.reset_daily_data()
                        return True
            except Exception as e:
                print(f"读取最后重置时间失败: {e}")
        else:
            # 如果没有记录重置时间的文件，说明可能是首次运行或文件丢失
            # 检查当前数据中是否有昨天的数据
            has_old_data = False
            for arcade in self.arcades:
                if isinstance(arcade, dict) and arcade.get('time'):
                    try:
                        time_obj = datetime.fromisoformat(arcade['time'])
                        if time_obj.date() < datetime.now().date():
                            has_old_data = True
                            break
                    except:
                        pass
            
            if has_old_data:
                print("检测到存在旧数据，执行重置")
                self.reset_daily_data()
                return True
        
        # 检查是否有今天凌晨4点之后的旧数据
        now = datetime.now()
        # 如果当前时间是4点之后，且有今天4点之前的数据，则重置
        if now.hour >= 4:
            has_old_data = False
            for arcade in self.arcades:
                if isinstance(arcade, dict) and arcade.get('time'):
                    try:
                        time_obj = datetime.fromisoformat(arcade['time'])
                        # 检查是否是今天的日期，但是早于4点
                        if time_obj.date() == now.date() and time_obj.hour < 4:
                            has_old_data = True
                            break
                    except:
                        pass
            
            if has_old_data:
                print("检测到今天4点前的旧数据，执行重置")
                self.reset_daily_data()
                return True
        
        return False
    
    def add_arcade(self, arcade_dict: Dict[str, Any]):
        """添加机厅"""
        # 生成唯一ID
        existing_ids = [arc.get('id', '') for arc in self.arcades]
        if existing_ids:
            # 找到最大的数字ID
            numeric_ids = [int(id_val) for id_val in existing_ids if id_val.isdigit()]
            if numeric_ids:
                next_id = max(numeric_ids) + 1
            else:
                next_id = 10000
        else:
            next_id = 10000
        
        arcade_dict['id'] = str(next_id)
        self.arcades.append(arcade_dict)
        self._save_arcades()
    
    def search_fullname(self, name: str) -> List[Dict[str, Any]]:
        """搜索机厅全名，返回所有匹配项"""
        results = []
        for arcade in self.arcades:
            if isinstance(arcade, dict):
                if arcade.get('name') == name or arcade.get('id') == name:
                    results.append(arcade)
                elif name in arcade.get('alias', []):
                    results.append(arcade)
        return results

    def del_arcade(self, name: str) -> bool:
        """删除机厅"""
        for i, arcade in enumerate(self.arcades):
            if isinstance(arcade, dict) and (arcade.get('name') == name or arcade.get('id') == name):
                self.arcades.pop(i)
                self._save_arcades()
                return True
        return False
    
    def update_arcade(self, name: str, mainum: int = None, chuninum: int = None) -> bool:
        """更新机厅信息"""
        for arcade in self.arcades:
            if isinstance(arcade, dict) and (arcade.get('name') == name or arcade.get('id') == name):
                if mainum is not None:
                    arcade['mainum'] = int(mainum)
                if chuninum is not None:
                    arcade['chuninum'] = int(chuninum)
                self._save_arcades()
                return True
        return False

arcade_data = ArcadeData()

@driver.on_startup
async def load_data():
    await arcade_data.load_arcades()
    history_data.load_history()
    # 启动时检查是否需要重置数据
    arcade_data.check_and_reset_if_needed()

SUBTRACT_PATTERN = re.compile(r"^(.+?)(?<!\d)-(\d+)$")
ADD_PATTERN = re.compile(r"^(.+?)(?<!\d)\+(\d+)$")
INCREMENT_PATTERN = re.compile(r"^(.+?)(?<!\d)\+\+$")
DECREMENT_PATTERN = re.compile(r"^(.+?)(?<!\d)--$")
# MULTI_ADD_PATTERN = re.compile(r"^(.+?)(?<!\d)(\d+(?:,\d+)*)$")
HELP_PATTERN = re.compile(r"^(help q|帮助排卡|排卡帮助|help 排卡|help queue)$", re.IGNORECASE)
SET_EQUAL_PATTERN = re.compile(r"^(.+?)=(\d+)$")
SET_DIRECT_PATTERN = re.compile(r"^(.+?)(?<!\d)(\d+)$")
QUERY_PATTERN = re.compile(r"^(.+?)(?<!\d)(几|j|jtj|多少人|有几人|有几卡|多少人|多少卡|几人|几卡|J|JTJ|jk|JK|几神|几爷|几爹)$", re.IGNORECASE)
HISTORY_PATTERN = re.compile(r"^(.+?)\有谁$", re.IGNORECASE)
ADD_ALIAS_PATTERN = re.compile(r"^添加别名\s+(.+?)\s+(.+)$")
DEL_ALIAS_PATTERN = re.compile(r"^删除别名\s+(.+?)\s+(.+)$")
FIND_ARCADE_PATTERN = re.compile(r"^查找机厅\s+(.+)$")
VIEW_LIST_PATTERN = re.compile(r"^(机厅列表)$", re.IGNORECASE)
SUBSCRIBE_REGEX_PATTERN = re.compile(r"^(订阅机厅|取消订阅机厅|取消订阅)\s+(.+)", re.IGNORECASE)
ADD_ARCADE_PATTERN = re.compile(r"^(添加机厅|新增机厅)\s+(.+)$", re.IGNORECASE)
DELETE_ARCADE_PATTERN = re.compile(r"^(删除机厅|移除机厅)\s+(.+)$", re.IGNORECASE)
LOCATION_QUERY_PATTERN = re.compile(r"^(.+?)(?<!\d)(在哪)$", re.IGNORECASE)

matcher = on_message(priority=10, block=False)

def _normalize_place(place: str) -> str:
    place = place.strip()
    # Try to find by name or alias
    arcade = arcade_data.find_arcade(place)
    if arcade:
        return arcade['name']
    return place


def _today_iso() -> str:
    return datetime.now().isoformat()


def _get_machine_count(arcade: Dict[str, Any]) -> int:
    """Get machine count based on config mode"""
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


def _response_for_update(place: str, old_count: int, new_count: int, action: str, user: str) -> str:
    """生成更新响应消息"""
    if old_count == new_count:
        arcade = arcade_data.find_arcade(place)
        display_name = arcade['name'] if arcade else place
        return f"卡数没有变化。\n{display_name}现在{_format_count_with_avg(new_count, arcade)}"
    
    delta = new_count - old_count
    if action == "increment":
        summary = f"增加了 {delta} 卡"
    elif action == "decrement":
        summary = f"减少了 {abs(delta)} 卡"
    elif action == "add":
        summary = f"增加了 {delta} 卡"
    elif action == "subtract":
        summary = f"减少了 {abs(delta)} 卡"
    elif action == "set":
        summary = f"设置卡数为 {new_count}"
    else:
        summary = "卡数更新"
    
    arcade = arcade_data.find_arcade(place)
    display_name = arcade['name'] if arcade else place
    return f"更新成功！{summary}\n{display_name}现在{_format_count_with_avg(new_count, arcade)}"


def _query_place(place: str, original_input: str) -> Optional[str]:
    place = _normalize_place(place)
    arcade, matched_alias = arcade_data.find_arcade_by_alias(original_input)
    if not arcade:
        return None
    
    # 检查是否为当天更新（今天4点后算当天周期）
    time_str = arcade.get('time', '')
    is_today = _is_same_day(time_str) if time_str else False
    
    # 检查今天是否有活动（即使人数为0，只要有更新记录就算有活动）
    has_activity = _has_today_activity(arcade['name'])
    
    # 使用完整机厅名称作为显示名称
    display_name = arcade['name']
    
    # 如果今天没有活动（既没更新时间，也没有历史记录），则显示未更新
    if not is_today or not has_activity:
        # 未更新的情况
        result = f"{display_name} 今日未更新。"
        result += f"\n设置卡数请直接发 \"{matched_alias}++\" \"{matched_alias}+数字\" 或 \"{matched_alias}--\" \"{matched_alias}-数字\" 或 \"{matched_alias}=数字\" \"{matched_alias}数字\""
        return result
    
    # 已更新的情况（即使人数为0，但有活动记录）
    person = arcade.get('person', 0)
    time_str = arcade.get('time', '')
    by_user = arcade.get('by', '')
    
    # 格式化时间显示
    time_display = ""
    if time_str:
        try:
            dt = datetime.fromisoformat(time_str)
            time_display = dt.strftime("%H:%M:%S")
        except:
            time_display = time_str.split("T")[1].split(".")[0] if "T" in time_str else time_display
    
    # 使用完整机厅名称作为显示名称
    display_name = arcade['name']
    # 使用用户实际输入的别名作为指令提示中的别名
    result = f"{display_name}现在{_format_count_with_avg(person, arcade)}。"
    
    if by_user and time_display:
        result += f"\n最后由 {by_user} 更新于 {time_display}。"
    
    # 使用用户实际输入的别名作为指令提示中的名称
    result += f"\n设置卡数请直接发 \"{matched_alias}++\" \"{matched_alias}+数字\" 或 \"{matched_alias}--\" \"{matched_alias}-数字\" 或 \"{matched_alias}=数字\" \"{matched_alias}数字\""
    
    return result


def _query_all(group_id: str) -> Optional[str]:
    """查询所有已订阅的机厅"""
    lines: List[str] = []
    total = 0
    found_any = False
    updated_count = 0  # 已更新的机厅数量
    zero_count = 0     # 为0的机厅数量
    no_activity_count = 0  # 无活动的机厅数量
    
    for arcade in arcade_data.arcades:
        # 确保arcade是字典
        if not isinstance(arcade, dict):
            continue
            
        # 检查该机厅是否被该群订阅
        if int(group_id) not in arcade.get('group', []):
            continue
        
        found_any = True
        person = arcade.get('person', 0)
        time_str = arcade.get('time', '')
        
        # 检查是否为当天更新
        is_today = _is_same_day(time_str) if time_str else False
        # 检查今天是否有活动
        has_activity = _has_today_activity(arcade['name'])
        
        # 格式化时间显示
        time_display = ""
        if time_str and is_today:
            try:
                dt = datetime.fromisoformat(time_str)
                time_display = dt.strftime("%H:%M:%S")
            except:
                # 如果解析失败，尝试提取时间部分
                if "T" in time_str:
                    time_part = time_str.split("T")[1].split(".")[0]
                    time_display = time_part
                else:
                    time_display = time_str
        
        # 使用完整机厅名称作为显示名称
        display_name = arcade['name']
        
        # 如果今天没有活动，则视为未更新
        if not has_activity:
            no_activity_count += 1
        elif is_today and person > 0:
            # 有活动且人数大于0
            updated_count += 1
            if time_display:
                lines.append(f"{display_name}: {_format_count_with_avg(person, arcade)} ({time_display})")
            else:
                lines.append(f"{display_name}: {_format_count_with_avg(person, arcade)}")
            total += person
        elif is_today and person == 0:
            # 有活动但人数为0
            updated_count += 1
            if time_display:
                lines.append(f"{display_name}: {_format_count_with_avg(person, arcade)} ({time_display})")
            else:
                lines.append(f"{display_name}: {_format_count_with_avg(person, arcade)}")
            total += person
    
    if not found_any:
        return None
    
    # 如果所有已订阅的机厅都没有活动，则显示统一提示
    if updated_count == 0:
        return "今天还没有人更新卡数, 望周知"
    
    # 检查是否需要显示全部机厅（10秒内再次查询）
    show_all = query_cache.should_show_all(group_id)
    
    # 如果不需要显示全部，且有未活动的机厅，则只显示有活动的并提示剩余
    if not show_all and no_activity_count > 0:
        lines.append(f"...其余{no_activity_count}个: 今日未更新 (10秒内再查以显示)")
    elif no_activity_count > 0:  # 如果需要显示全部，则显示所有机厅
        # 显示所有未活动的机厅
        for arcade in arcade_data.arcades:
            if not isinstance(arcade, dict):
                continue
                
            if int(group_id) not in arcade.get('group', []):
                continue
                
            # 检查今天是否有活动
            has_activity = _has_today_activity(arcade['name'])
            
            if not has_activity:  # 未活动的机厅
                display_name = arcade['name']
                lines.append(f"{display_name}: 今日未更新")
    
    lines.append(f"出勤总人数: {total}")
    lines.append("发送 \"<机厅名>++\" \"<机厅名>+数字\" 加卡, \"<机厅名>--\" \"<机厅名>-数字\" 减卡, \"<机厅名>=数字\" \"<机厅名>数字\" 设置卡数")
    
    # 更新查询时间戳，下次查询将在10秒内显示全部
    query_cache.update_query_time(group_id)
    
    return "\n".join(lines)

def _query_history(place: str) -> Optional[str]:
    """查询机厅历史记录"""
    place = _normalize_place(place)  # 将别名转换为正式名称
    arcade = arcade_data.find_arcade(place)
    if not arcade:
        return
    
    records = history_data.get_records(place)  # 使用正式名称查询历史记录
    if not records:
        return f"{arcade['name']} 历史记录:\n暂无加减卡记录。"
    
    lines = [f"{arcade['name']} 历史记录:"]
    for record in records:
        time_str = record["time"]
        user = record["user"]
        action = record["action"]
        old_count = record.get("old_count")
        new_count = record.get("new_count")
        
        if action == "increment":
            lines.append(f"{time_str} {user} 增加了1卡")
        elif action == "decrement":
            lines.append(f"{time_str} {user} 减少了1卡")
        elif action == "add":
            count = record.get("count", 0)
            lines.append(f"{time_str} {user} 增加了{count}卡")
        elif action == "subtract":
            count = record.get("count", 0)
            lines.append(f"{time_str} {user} 减少了{count}卡")
        elif action == "set":
            lines.append(f"{time_str} {user} 设置卡数为{new_count}")
    
    return "\n".join(lines)

def _query_location(place: str) -> Optional[str]:
    """查询机厅地址信息"""
    original_place = place
    place = _normalize_place(place)  # 将别名转换为正式名称
    arcade = arcade_data.find_arcade(place)
    if not arcade:
        return
    
    # 获取机厅地址信息
    address = arcade.get('address', '地址未知')
    
    # 构造地址信息
    if address and address != '地址未知':
        location_info = f"{address}"
    
    # 如果没有详细地址信息，则返回基本提示
    if not address or address == '地址未知':
        return f"{arcade['name']} 地址信息未知"
    
    return location_info

def _apply_delta(place: str, delta: int, user_name: str = "", action_type: str = "add", group_id: str = "") -> Optional[str]:
    place = _normalize_place(place)
    arcade = arcade_data.find_arcade(place)
    if not arcade:
        return None
    
    # 检查该机厅是否被当前群订阅
    if not arcade_data.is_subscribed(group_id, place):
        return f"该群未订阅机厅：{arcade['name']}，无法修改卡数。请先订阅该机厅。"
    
    # 检查操作数量是否超过限制
    if abs(delta) > 30:
        return "一次不能操作多于30张卡"
    
    old_count = arcade.get('person', 0)
    new_count = max(0, old_count + delta)
    # 检查是否卡数发生变化
    if old_count == new_count:
        arcade = arcade_data.find_arcade(place)
        display_name = arcade['name'] if arcade else place
        return f"卡数没有变化。\n{display_name}现在{_format_count_with_avg(new_count, arcade)}"
    
    arcade['person'] = new_count
    arcade['time'] = _today_iso()
    arcade['by'] = user_name
    arcade_data._save_arcades()
    
    # 记录历史
    if action_type == "add":
        history_data.add_record(place, "add", user_name, abs(delta), old_count, new_count)
    elif action_type == "subtract":
        history_data.add_record(place, "subtract", user_name, abs(delta), old_count, new_count)
    elif action_type == "increment":
        history_data.add_record(place, "increment", user_name, 1, old_count, new_count)
    elif action_type == "decrement":
        history_data.add_record(place, "decrement", user_name, 1, old_count, new_count)
    
    return _response_for_update(place, old_count, new_count, action_type, user_name)


def _set_single_count(place: str, count: int, user_name: str = "", group_id: str = "") -> Optional[str]:
    if count < 0:
        return None
    place = _normalize_place(place)
    arcade = arcade_data.find_arcade(place)
    if not arcade:
        return None
    
    # 检查该机厅是否被当前群订阅
    if not arcade_data.is_subscribed(group_id, place):
        return f"该群未订阅机厅：{arcade['name']}，无法修改卡数。请先订阅该机厅。"
    
    # 检查设置的数量是否超过当前人数太多（如果是减少）
    old_count = arcade.get('person', 0)
    if old_count > 0 and count < old_count and (old_count - count) > 30:
        return "一次不能操作多于30张卡"
    elif count > old_count and (count - old_count) > 30:
        return "一次不能操作多于30张卡"
    
    # 检查是否卡数发生变化
    if old_count == count:
        arcade = arcade_data.find_arcade(place)
        display_name = arcade['name'] if arcade else place
        return f"卡数没有变化。\n{display_name}现在{_format_count_with_avg(count, arcade)}"
    
    arcade['person'] = count
    arcade['time'] = _today_iso()
    arcade['by'] = user_name
    arcade_data._save_arcades()
    
    # 记录历史
    history_data.add_record(place, "set", user_name, count, old_count, count)
    
    return _response_for_update(place, old_count, count, "set", user_name)

def _subscribe_arcade(group_id: str, arcade_name: str) -> str:
    """订阅机厅 - 支持通过名称或别名订阅"""
    arcade_name = arcade_name.strip()
    # 首先尝试查找机厅（通过名称或别名）
    arcade = arcade_data.find_arcade(arcade_name)
    if not arcade:
        # 如果没找到，尝试模糊搜索
        results = arcade_data.search_fullname(arcade_name)
        if not results:
            return f"未找到机厅：{arcade_name}，请检查名称是否正确。"
        elif len(results) > 1:
            # 如果找到多个匹配项，列出供用户确认
            names = [arc['name'] for arc in results]
            return f"找到多个匹配的机厅：{'、'.join(names)}，请使用完整名称订阅。"
        else:
            # 如果找到唯一匹配项，使用该机厅
            arcade = results[0]
            arcade_name = arcade['name']
    else:
        # 如果找到了，使用完整名称
        arcade_name = arcade['name']
    
    if arcade_data.is_subscribed(group_id, arcade_name):
        return f"已订阅机厅：{arcade['name']}"
    if arcade_data.subscribe(group_id, arcade_name):
        return f"订阅成功：{arcade['name']}"
    return f"订阅失败：{arcade_name}"

def _unsubscribe_arcade(group_id: str, arcade_name: str) -> str:
    """取消订阅机厅 - 支持通过名称或别名取消订阅"""
    arcade_name = arcade_name.strip()
    # 首先尝试查找机厅（通过名称或别名）
    arcade = arcade_data.find_arcade(arcade_name)
    if not arcade:
        # 如果没找到，尝试模糊搜索
        results = arcade_data.search_fullname(arcade_name)
        if not results:
            return f"未找到机厅：{arcade_name}，请检查名称是否正确。"
        elif len(results) > 1:
            # 如果找到多个匹配项，列出供用户确认
            names = [arc['name'] for arc in results]
            return f"找到多个匹配的机厅：{'、'.join(names)}，请使用完整名称取消订阅。"
        else:
            # 如果找到唯一匹配项，使用该机厅
            arcade = results[0]
            arcade_name = arcade['name']
    else:
        # 如果找到了，使用完整名称
        arcade_name = arcade['name']
    
    if not arcade_data.is_subscribed(group_id, arcade_name):
        return f"未订阅机厅：{arcade['name']}"
    if arcade_data.unsubscribe(group_id, arcade_name):
        return f"取消订阅成功：{arcade['name']}"
    return f"取消订阅失败：{arcade_name}"

def _add_alias(arcade_name: str, alias: str) -> str:
    arcade_name = arcade_name.strip()
    alias = alias.strip()
    arcade = arcade_data.find_arcade(arcade_name)
    if not arcade:
        return f"未找到机厅：{arcade_name}"
    if alias in arcade.get('alias', []):
        return f"别名已存在：{alias}"
    arcade.setdefault('alias', []).append(alias)
    arcade_data._save_arcades()
    return f"为机厅 {arcade['name']} 添加别名：{alias}"

def _del_alias(arcade_name: str, alias: str) -> str:
    arcade_name = arcade_name.strip()
    alias = alias.strip()
    arcade = arcade_data.find_arcade(arcade_name)
    if not arcade:
        return f"未找到机厅：{arcade_name}"
    if alias not in arcade.get('alias', []):
        return f"别名不存在：{alias}"
    arcade['alias'].remove(alias)
    arcade_data._save_arcades()
    return f"从机厅 {arcade['name']} 删除别名：{alias}"

def _find_arcades(keyword: str) -> str:
    results = []
    keyword_lower = keyword.lower()
    for arcade in arcade_data.arcades:
        if not isinstance(arcade, dict):
            continue
        if keyword_lower in arcade.get('name', '').lower() or any(keyword_lower in alias.lower() for alias in arcade.get('alias', [])):
            display_name = arcade.get('name', '')  # 使用完整机厅名称
            # 格式化结果为新的样式
            result_line = f"==========\n店名：{display_name}\n地址：{arcade.get('address', '')}\n店铺ID：{arcade.get('id', '')}\n舞萌DX机台数量：{arcade.get('mainum', 0)}\n中二节奏机台数量：{arcade.get('chuninum', 0)}"
            results.append(result_line)
    
    if not results:
        return "未找到匹配的机厅"
    
    # 在结果前面加上提示文字
    formatted_results = ["查找到以下结果"] + results
    return "\n".join(formatted_results)

def _format_arcade_list(group_id: str) -> str:
    """格式化机厅及其别名列表，只显示该群订阅的机厅"""
    lines = ["机厅名称及别名如下:"]
    subscribed_arcades = []
    
    for arcade in arcade_data.arcades:
        if not isinstance(arcade, dict):
            continue
        # 检查该机厅是否被该群订阅
        if int(group_id) not in arcade.get('group', []):
            continue
        
        name = arcade.get('name', '')
        aliases = arcade.get('alias', [])
        # 过滤掉空字符串别名
        valid_aliases = [a for a in aliases if a.strip()]
        if valid_aliases:
            alias_str = "、".join(valid_aliases)
            lines.append(f"{name}: {alias_str}")
        else:
            lines.append(name) # 如果没有别名，只显示名字
        subscribed_arcades.append(name)
    
    if not subscribed_arcades:
        lines.append("本群尚未订阅任何机厅")
    
    return "\n".join(lines)

def _add_arcade(text: str) -> str:
    """添加机厅功能"""
    args = text.strip().split()
    
    if len(args) < 3:
        return '指令错误，请再次确认指令格式\n添加机厅 <店名> <地址> <舞萌DX机台数量> <中二节奏机台数量> <简称1> [简称2] ...'
    
    # 检查舞萌DX机台数量是否为数字
    if not args[2].isdigit():
        return '指令错误，请再次确认指令格式\n添加机厅 <店名> <地址> <舞萌DX机台数量> <中二节奏机台数量> <简称1> [简称2] ...'
    
    # 检查中二节奏机台数量是否为数字（如果提供了）
    chuni_num = int(args[3]) if len(args) > 3 and args[3].isdigit() else 0
    
    # 检查是否已存在同名机厅
    if arcade_data.search_fullname(args[0]):
        return f'{args[0]} 已存在'
    
    # 生成新机厅信息
    arcade_dict = {
        'name': args[0],
        'address': args[1],
        'mall': '',
        'province': '',
        'mainum': int(args[2]),
        'chuninum': chuni_num,
        'id': '',  # ID将在add_arcade方法中生成
        'alias': args[4:] if len(args) > 4 else [],
        'group': [],
        'person': 0,
        'by': '',
        'time': ''
    }
    
    # 添加机厅
    arcade_data.add_arcade(arcade_dict)
    return f'{args[0]} 添加成功'

def _delete_arcade(text: str) -> str:
    """删除机厅功能"""
    name = text.strip()
    
    if not name:
        return '指令错误，请再次确认指令格式\n删除机厅 <店名>，店名需要输入全称而不是简称哦！'
    
    # 检查是否找到机厅
    if not arcade_data.search_fullname(name):
        return f'未找到机厅: {name}'
    
    # 删除机厅
    if arcade_data.del_arcade(name):
        return f'已删除机厅: {name}'
    else:
        return f'删除机厅{name}失败'

def _help_text() -> str:
    return "\n".join([
        "排卡插件帮助",
        "命令：",
        "  <机厅名>++        增加 1 卡",
        "  <机厅名>--        减少 1 卡",
        "  <机厅名>+N        增加 N 卡",
        "  <机厅名>-N        减少 N 卡",
        "  <机厅名>N         直接设置卡数为 N",
        "  <机厅名>=N        直接设置卡数为 N",
        "  <机厅名>几 / <机厅名>j  查询该机厅卡数",
        "  <机厅名>有谁        查看该机厅今日历史记录",
        "  <机厅名>在哪  查询该机厅地址",
        "  j / jtj / jk / 几 /几卡       查询本群所有机厅卡数",
        "  机厅列表        查看本群订阅的所有机厅及其别名",
        "----以下功能仅限群管理员操作----\n"
        "  查找机厅 <关键词>   使用关键词查找机厅",
        "  订阅机厅 <机厅名>    订阅机厅",
        "  取消订阅机厅 <机厅名>  取消订阅",
        "  添加别名 <机厅名> <别名>  添加机厅别名",
        "  删除别名 <机厅名> <别名>  删除机厅别名",
        "  添加机厅 <店名> <地址> <舞萌DX机台数量> <中二节奏机台数量> <简称>  添加机厅信息",
        "  删除机厅 <店名>  删除机厅信息",
        ""
    ])

def _reply_text(event: GroupMessageEvent, text: str) -> MessageSegment:
    return MessageSegment.reply(event.message_id) + text

def _is_admin(event: GroupMessageEvent) -> bool:
    """检查用户是否为群管理员、群主或 Bot 超级管理员"""
    if event.sender.role in ('owner', 'admin'):
        return True
    try:
        superusers = getattr(plugin_config, 'superusers', set()) or set()
        superusers = {str(uid) for uid in superusers}
        return str(event.user_id) in superusers
    except Exception:
        return False

# 定时清理过期数据的任务
from nonebot import require
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

@scheduler.scheduled_job("cron", hour=4, minute=0, id="reset_daily_data")
async def reset_daily_data():
    """每天4点重置数据"""
    print("正在重置每日数据...")
    arcade_data.reset_daily_data()
    # 清空历史记录 - 使用统一的游戏日逻辑
    current_day_key = _get_current_day_key()
    history_data.last_reset_date = current_day_key
    history_data.history = {}  # 清空所有历史记录
    history_data.save_history()
    print("每日数据重置完成")

def _check_and_reset_daily_data():
    """检查是否需要重置每日数据"""
    now = datetime.now()
    # 如果当前时间是4点之后，且上次更新时间在4点之前，则重置数据
    if now.hour >= 4:
        # 检查是否有过期的数据需要重置
        should_reset = False
        for arcade in arcade_data.arcades:
            if isinstance(arcade, dict) and arcade.get('time'):
                try:
                    time_obj = datetime.fromisoformat(arcade['time'])
                    # 如果记录的时间是昨天或更早的日期（按游戏日计算），则重置
                    if time_obj.hour >= 4:
                        # 更新时间 >= 4点，属于当天的游戏日
                        update_game_day = time_obj.date()
                    else:
                        # 更新时间 < 4点，属于前一天的游戏日
                        update_game_day = (time_obj - timedelta(days=1)).date()
                    
                    # 当前时间的游戏日
                    if now.hour >= 4:
                        current_game_day = now.date()
                    else:
                        current_game_day = (now - timedelta(days=1)).date()
                    
                    # 如果更新的游戏日不是当前游戏日，则需要重置
                    if update_game_day < current_game_day:
                        should_reset = True
                        break
                except:
                    pass
        if should_reset:
            arcade_data.reset_daily_data()
    
    current_day_key = _get_current_day_key()
    if history_data.last_reset_date != current_day_key:
        if history_data.last_reset_date is not None and history_data.last_reset_date != current_day_key:
            history_data.history = {}
            print(f"清空历史记录，从 {history_data.last_reset_date} 到 {current_day_key}")
        history_data.last_reset_date = current_day_key
        history_data.save_history()

def _subscribe_regex(group_id: str, name: str, is_subscribe: bool) -> str:
    """订阅或取消订阅机厅 - 支持模糊匹配和更友好的反馈"""
    # 首先尝试精确匹配（名称或ID）
    existing_arcades = arcade_data.search_fullname(name)
    if not existing_arcades:
        # 如果没找到，尝试模糊搜索（包含关键词的名称或别名）
        fuzzy_results = []
        name_lower = name.lower()
        for arcade in arcade_data.arcades:
            if not isinstance(arcade, dict):
                continue
            if name_lower in arcade.get('name', '').lower() or any(name_lower in alias.lower() for alias in arcade.get('alias', [])):
                fuzzy_results.append(arcade)
        if not fuzzy_results:
            return f'未找到名为"{name}"的机厅，请检查名称是否正确。'
        elif len(fuzzy_results) > 1:
            # 如果找到多个匹配项，列出供用户确认
            names = [arc['name'] for arc in fuzzy_results[:5]]  # 只显示前5个
            extra_count = len(fuzzy_results) - 5 if len(fuzzy_results) > 5 else 0
            extra_text = f"，还有{extra_count}个结果" if extra_count > 0 else ""
            return f'找到多个相似的机厅：{"、".join(names)}{extra_text}，请使用完整名称或ID操作。'
        else:
            # 如果找到唯一匹配项，使用该机厅
            existing_arcades = fuzzy_results
    
    # 检查是否有多个匹配项
    if len(existing_arcades) > 1:
        return f'发现多个重复条目，请直接使用店铺ID更改机厅别名\n' + '\n'.join([ f'{arc["id"]}：{arc["name"]}' for arc in existing_arcades ])
    
    # 获取第一个匹配的机厅
    arcade = existing_arcades[0]
    arcade_name = arcade['name']
    
    if is_subscribe:
        # 订阅
        if arcade_data.is_subscribed(group_id, arcade_name):
            return f'已订阅机厅：{arcade["name"]}'
        if arcade_data.subscribe(group_id, arcade_name):
            return f'订阅成功：{arcade["name"]}'
        return f'订阅失败：{arcade_name}'
    else:
        # 取消订阅
        if not arcade_data.is_subscribed(group_id, arcade_name):
            return f'未订阅机厅：{arcade["name"]}'
        if arcade_data.unsubscribe(group_id, arcade_name):
            return f'取消订阅成功：{arcade["name"]}'
        return f'取消订阅失败：{arcade_name}'

@matcher.handle()
async def handle_query(bot: Bot, event: GroupMessageEvent) -> None:
    text = str(event.get_message()).strip()
    if not text:
        return

    # 检查是否需要重置每日数据
    _check_and_reset_daily_data()

    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)

    if HELP_PATTERN.fullmatch(text):
        help_text = _help_text()
        img = text_to_image(help_text)
        base64_img = image_to_base64(img)
        await matcher.finish(MessageSegment.reply(event.message_id) + MessageSegment.image(base64_img))
        return

    if VIEW_LIST_PATTERN.fullmatch(text):
        list_text = _format_arcade_list(group_id)
        await matcher.finish(_reply_text(event, list_text))
        return

    if text.lower() in {"j", "jtj", "jk", "几卡", "几神", "几爷", "几爹", "多少人", "有几人", "有几卡", "多少人", "多少卡", "几人", "几"}:
        response = _query_all(group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 添加机厅地址查询功能
    if m := LOCATION_QUERY_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _query_location(place)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := SUBTRACT_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _apply_delta(place, -number, user_name, "subtract", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := ADD_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _apply_delta(place, number, user_name, "add", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := INCREMENT_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _apply_delta(place, 1, user_name, "increment", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := DECREMENT_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _apply_delta(place, -1, user_name, "decrement", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := SET_EQUAL_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _set_single_count(place, number, user_name, group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := SET_DIRECT_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _set_single_count(place, number, user_name, group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 分段卡数功能已禁用，避免与普通数字命令冲突
    # if m := MULTI_ADD_PATTERN.fullmatch(text):
    #     place, numbers_text = m.groups()
    #     numbers = [int(n) for n in numbers_text.split(",") if n != ""]
    #     if any(n < 0 for n in numbers):
    #         return
    #     response = _set_counts(place, numbers)
    #     if response:
    #         await matcher.finish(_reply_text(event, response))
    #     return

    if m := QUERY_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _query_place(place, place)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := HISTORY_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _query_history(place)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    if m := SUBSCRIBE_REGEX_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可订阅机厅"))
            return
        prefix = m.group(1)
        arcade_name = m.group(2).strip()
        is_subscribe = prefix in ['订阅机厅', '订阅']  # 支持多种订阅命令
        response = _subscribe_regex(group_id, arcade_name, is_subscribe)
        await matcher.finish(_reply_text(event, response))
        return

    if m := ADD_ALIAS_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可添加别名"))
            return
        arcade_name, alias = m.groups()
        response = _add_alias(arcade_name, alias)
        await matcher.finish(_reply_text(event, response))
        return

    if m := DEL_ALIAS_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可删除别名"))
            return
        arcade_name, alias = m.groups()
        response = _del_alias(arcade_name, alias)
        await matcher.finish(_reply_text(event, response))
        return

    if m := ADD_ARCADE_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可添加机厅"))
            return
        command_text = m.group(2).strip()
        response = _add_arcade(command_text)
        await matcher.finish(_reply_text(event, response))
        return

    if m := DELETE_ARCADE_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可删除机厅"))
            return
        command_text = m.group(2).strip()
        response = _delete_arcade(command_text)
        await matcher.finish(_reply_text(event, response))
        return

    if m := FIND_ARCADE_PATTERN.fullmatch(text):
        keyword = m.group(1)
        text_result = _find_arcades(keyword)
        img = text_to_image(text_result)
        base64_img = image_to_base64(img)
        await matcher.finish(MessageSegment.reply(event.message_id) + MessageSegment.image(base64_img))
        return
