from nonebot.log import logger
import json
import aiohttp
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (
    ARCADE_DATA_FILE,
    LOCAL_ARCADE_FILE,
    BOT_DATA_DIR,
    USE_ONLINE_DATABASE,
    safe_file_write,
)


class ArcadeData:
    """机厅数据管理类"""
    
    def __init__(self):
        self.arcades: List[Dict[str, Any]] = []
        self.last_update = None
        self.current_file = ARCADE_DATA_FILE  # 默认使用 arcades.json
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
                    "alias": ["别名 1", "别名 2"],
                    "group": [],
                    "person": 0,
                    "by": "",
                    "time": "",
                    "nearcade_id": ""
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
                    "mainum: 舞萌 DX 机台数量（可选）",
                    "chuninum: 中二节奏机台数量（可选）",
                    "id: 机厅唯一标识符",
                    "alias: 别名列表（可选）",
                    "group: 已订阅该机厅的群组列表（由程序自动维护）",
                    "person: 当前卡数（由程序自动维护）",
                    "by: 最后更新者（由程序自动维护）",
                    "time: 最后更新时间（由程序自动维护）",
                    "nearcade_id: Nearcade 机厅 ID（可选，用于上报人数）",
                ]
            }
        }
        
        try:
            with safe_file_write(LOCAL_ARCADE_FILE) as f:
                json.dump(template_data, f, ensure_ascii=False, indent=2)
            logger.info(f"已创建本地数据库模板文件：{LOCAL_ARCADE_FILE}")
            logger.info("请编辑此文件以添加您的机厅数据，然后重启机器人。")
            return True
        except Exception as e:
            logger.error(f"创建本地数据库模板失败：{e}")
            return False

    async def load_arcades(self):
        """加载机厅数据"""
        # 根据配置决定加载哪个文件
        if not USE_ONLINE_DATABASE:
            # 检查本地文件是否存在，如果不存在则创建模板
            if not LOCAL_ARCADE_FILE.exists():
                logger.warning(f"本地数据库文件不存在：{LOCAL_ARCADE_FILE}")
                self.create_local_template()
                # 提示用户编辑数据库
                logger.info("\n" + "="*50)
                logger.info("本地数据库文件已创建为模板，请按以下步骤操作：")
                logger.info(f"1. 编辑文件：{LOCAL_ARCADE_FILE}")
                logger.info("2. 修改模板中的示例数据为您实际的机厅信息")
                logger.info("3. 保存文件后重启机器人")
                logger.info("="*50 + "\n")
            
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
                            item.setdefault('nearcade_id', '')
                            validated_arcades.append(item)
                        else:
                            logger.warning(f"警告：发现无效的机厅数据项，跳过：{item}")
                    
                    self.arcades = validated_arcades
                    self.last_update = data.get("last_update") if isinstance(data, dict) else None
            except Exception as e:
                logger.error(f"加载机厅数据失败：{e}")
                self.arcades = []
        await self.update_arcades()

    async def update_arcades(self):
        """更新机厅数据"""
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
                            item.setdefault('nearcade_id', '')
                            validated_local_data.append(item)
                        else:
                            logger.warning(f"警告：发现无效的本地机厅数据项，跳过：{item}")
                    
                    self.arcades = validated_local_data
                    self.last_update = data.get("last_update") if isinstance(data, dict) else datetime.now().isoformat()
                    # 确保使用本地文件
                    self.current_file = LOCAL_ARCADE_FILE
                    self._save_arcades()
                    logger.info("Loaded arcades from local file")
                except Exception as e:
                    logger.error(f"Failed to load local arcades: {e}")
            else:
                logger.warning("Local arcade file not found")
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
                        'time': '',
                        'nearcade_id': ''
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
                        item.setdefault('nearcade_id', '')
                        validated_arcades.append(item)
                    else:
                        logger.warning(f"警告：发现无效的机厅数据项，跳过：{item}")
                
                self.arcades = validated_arcades
                self.last_update = datetime.now().isoformat()
                # 确保使用在线数据文件
                self.current_file = ARCADE_DATA_FILE
                self._save_arcades()
                logger.info("Updated arcades from online API")

        except Exception as e:
            logger.error(f"Failed to update arcades: {e}")

    def _save_arcades(self):
        """保存机厅数据"""
        data = {
            "arcades": self.arcades,
            "last_update": self.last_update
        }
        try:
            with safe_file_write(self.current_file) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存机厅数据失败：{e}")

    def find_arcade_by_alias(self, name_or_alias: str, group_id: Optional[str] = None) -> tuple[Optional[Dict[str, Any]], str]:
        """
        查找机厅，优先查找当前群组订阅的机厅。
        返回匹配的机厅和所用的别名。
        """
        # 如果提供了 group_id，首先在订阅的机厅中查找
        if group_id:
            for arcade in self.arcades:
                if isinstance(arcade, dict):
                    # 检查是否在当前群组中
                    if int(group_id) in arcade.get('group', []):
                        if arcade.get('name') == name_or_alias:
                            return arcade, arcade['name']
                        if name_or_alias in arcade.get('alias', []):
                            return arcade, name_or_alias
        
        # 如果没有提供 group_id，或者在订阅的机厅中没找到，则在所有机厅中查找
        for arcade in self.arcades:
            if isinstance(arcade, dict):
                if arcade.get('name') == name_or_alias:
                    return arcade, arcade['name']
                if name_or_alias in arcade.get('alias', []):
                    return arcade, name_or_alias
        
        return None, name_or_alias

    def find_arcade(self, name_or_alias: str, group_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """查找机厅"""
        arcade, _ = self.find_arcade_by_alias(name_or_alias, group_id=group_id)
        return arcade

    def is_subscribed(self, group_id: str, arcade_name: str) -> bool:
        """检查群组是否订阅了机厅"""
        arcade = self.find_arcade(arcade_name)
        if arcade and isinstance(arcade, dict):
            return int(group_id) in arcade.get('group', [])
        return False

    def subscribe(self, group_id: str, arcade_name: str) -> bool:
        """订阅机厅"""
        arcade = self.find_arcade(arcade_name)
        if arcade and isinstance(arcade, dict):
            if int(group_id) not in arcade.get('group', []):
                arcade.setdefault('group', []).append(int(group_id))
                self._save_arcades()
                return True
        return False

    def unsubscribe(self, group_id: str, arcade_name: str) -> bool:
        """取消订阅机厅"""
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
                arcade['person'] = 0  # 重置人数为 0
                arcade['time'] = ''   # 清空时间
                arcade['by'] = ''     # 清空用户名
        self._save_arcades()
        logger.info("每日数据重置完成")
        
        # 更新最后重置时间记录
        try:
            with open(self.last_reset_time_file, 'w', encoding='utf-8') as f:
                f.write(datetime.now().isoformat())
        except Exception as e:
            logger.error(f"无法保存最后重置时间：{e}")

    def check_and_reset_if_needed(self):
        """检查是否需要重置数据，在机器人启动时调用"""
        from datetime import datetime, timedelta

        now = datetime.now()
        # 定义游戏日：从凌晨 4 点到次日凌晨 4 点
        if now.hour < 4:
            # 如果当前时间在凌晨 4 点之前，则游戏日属于前一天
            current_game_day = (now - timedelta(days=1)).date()
        else:
            # 否则，游戏日属于当天
            current_game_day = now.date()

        # 检查是否有任何机厅的数据需要重置
        should_reset = False
        for arcade in self.arcades:
            if isinstance(arcade, dict) and arcade.get('time'):
                try:
                    time_obj = datetime.fromisoformat(arcade['time'])
                    
                    # 计算数据所属的游戏日
                    if time_obj.hour < 4:
                        data_game_day = (time_obj - timedelta(days=1)).date()
                    else:
                        data_game_day = time_obj.date()

                    # 如果数据所属的游戏日早于当前游戏日，则需要重置
                    if data_game_day < current_game_day:
                        should_reset = True
                        break  # 只要有一个需要重置，就跳出循环

                except (ValueError, TypeError):
                    # 时间格式错误或类型不匹配，可以记录日志或忽略
                    logger.warning(f"机厅 '{arcade.get('name', '未知')}' 的时间格式无效，跳过检查。")
                    continue

        if should_reset:
            logger.info("检测到存在旧的游戏日数据，将执行每日数据重置。")
            self.reset_daily_data()
            return True
        
        logger.info("所有数据均为当前游戏日，无需重置。")
        return False
    
    def add_arcade(self, arcade_dict: Dict[str, Any]):
        """添加机厅"""
        # 生成唯一 ID
        existing_ids = [arc.get('id', '') for arc in self.arcades]
        if existing_ids:
            # 找到最大的数字 ID
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


# 全局实例
arcade_data = ArcadeData()