"""
查询业务逻辑模块
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import (
    _is_same_day,
    _today_iso,
    _format_count_with_avg,
    _get_current_day_key,
)
from .arcade import arcade_data
from .history import history_data
from .nearcade_service import update_nearcade_attendance, get_nearcade_attendance




# 查询缓存类
class QueryCache:
    """查询缓存，用于跟踪最近的查询"""
    def __init__(self):
        self.cache = {}  # {group_id: {'timestamp': datetime, 'show_all': bool}}
    
    def update_query_time(self, group_id: str):
        """更新群组的查询时间"""
        self.cache[group_id] = {
            'timestamp': datetime.now(),
            'show_all': True  # 下次查询将显示全部
        }
    
    def should_show_all(self, group_id: str) -> bool:
        """判断是否应该显示全部机厅（10 秒内再次查询）"""
        if group_id not in self.cache:
            return False
        
        last_query_time = self.cache[group_id]['timestamp']
        elapsed = datetime.now() - last_query_time
        
        # 如果距离上次查询在 10 秒内，则显示全部
        if elapsed.total_seconds() <= 10:
            return True
        else:
            # 超过 10 秒则清除缓存
            del self.cache[group_id]
            return False


query_cache = QueryCache()


def _has_today_activity(arcade_name: str) -> bool:
    """检查指定机厅今天是否有活动（更新记录）"""
    today_str = _get_current_day_key()
    if today_str in history_data.history and arcade_name in history_data.history[today_str]:
        return len(history_data.history[today_str][arcade_name]) > 0
    return False


def _normalize_place(place: str) -> str:
    """标准化地点名称"""
    place = place.strip()
    # Try to find by name or alias
    arcade = arcade_data.find_arcade(place)
    if arcade:
        return arcade['name']
    return place


def _response_for_update(place: str, old_count: int, new_count: int, 
                         action: str, user: str) -> str:
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


async def _query_place(place: str, original_input: str) -> Optional[str]:
    """查询单个机厅"""
    place = _normalize_place(place)
    arcade, matched_alias = arcade_data.find_arcade_by_alias(original_input)
    if not arcade:
        return None

    # 检查是否为当天更新（今天 4 点后算当天周期）
    time_str = arcade.get('time', '')
    is_today = _is_same_day(time_str) if time_str else False

    # 如果机厅绑定了 Nearcade ID 且本地数据不是最新的，则尝试从 Nearcade 同步
    if arcade.get('nearcade_id') and not is_today:
        new_count = await get_nearcade_attendance(arcade['nearcade_id'])
        if new_count is not None:
            arcade['person'] = new_count
            arcade['time'] = _today_iso()
            arcade['by'] = 'Nearcade 同步'
            arcade_data._save_arcades()
            # 更新后重新检查 is_today
            is_today = True

    # 检查今天是否有活动（即使人数为 0，只要有更新记录就算有活动）
    has_activity = _has_today_activity(arcade['name'])
    
    # 使用完整机厅名称作为显示名称
    display_name = arcade['name']
    
    # 如果今天没有活动（既没更新时间，也没有历史记录），则显示未更新
    if not is_today or not has_activity:
        # 未更新的情况
        result = f"{display_name} 今日未更新。"
        result += f"\n设置卡数请直接发 \"{matched_alias}++\" \"{matched_alias}+数字\" 或 \"{matched_alias}--\" \"{matched_alias}-数字\" 或 \"{matched_alias}=数字\" \"{matched_alias}数字\""
        return result
    
    # 已更新的情况（即使人数为 0，但有活动记录）
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
    zero_count = 0     # 为 0 的机厅数量
    no_activity_count = 0  # 无活动的机厅数量
    
    for arcade in arcade_data.arcades:
        # 确保 arcade 是字典
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
            # 有活动且人数大于 0
            updated_count += 1
            if time_display:
                lines.append(f"{display_name}: {_format_count_with_avg(person, arcade)} ({time_display})")
            else:
                lines.append(f"{display_name}: {_format_count_with_avg(person, arcade)}")
            total += person
        elif is_today and person == 0:
            # 有活动但人数为 0
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
        return "今天还没有人更新卡数，望周知"
    
    # 检查是否需要显示全部机厅（10 秒内再次查询）
    show_all = query_cache.should_show_all(group_id)
    
    # 如果不需要显示全部，且有未活动的机厅，则只显示有活动的并提示剩余
    if not show_all and no_activity_count > 0:
        lines.append(f"...其余{no_activity_count}个：今日未更新 (10 秒内再查以显示)")
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
    
    lines.append(f"出勤总人数：{total}")
    lines.append("发送 \"<机厅名>++\" \"<机厅名>+数字\" 加卡，\"<机厅名>--\" \"<机厅名>-数字\" 减卡，\"<机厅名>=数字\" \"<机厅名>数字\" 设置卡数")
    
    # 更新查询时间戳，下次查询将在 10 秒内显示全部
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
            lines.append(f"{time_str} {user} 增加了 1 卡")
        elif action == "decrement":
            lines.append(f"{time_str} {user} 减少了 1 卡")
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


async def _apply_delta(place: str, delta: int, user_name: str = "", 
                 action_type: str = "add", group_id: str = "") -> Optional[str]:
    """应用增量更新"""
    place = _normalize_place(place)
    arcade = arcade_data.find_arcade(place)
    if not arcade:
        return None
    
    # 检查该机厅是否被当前群订阅
    if not arcade_data.is_subscribed(group_id, place):
        return f"该群未订阅机厅：{arcade['name']}，无法修改卡数。请先订阅该机厅。"
    
    # 检查操作数量是否超过限制
    if abs(delta) > 30:
        return "一次不能操作多于 30 张卡"
    
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
    
    # 如果绑定了 Nearcade ID，则上报人数
    if arcade.get('nearcade_id'):
        await update_nearcade_attendance(arcade['nearcade_id'], new_count)
    
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


async def _set_single_count(place: str, count: int, user_name: str = "", 
                      group_id: str = "") -> Optional[str]:
    """设置单个机厅的卡数"""
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
        return "一次不能操作多于 30 张卡"
    elif count > old_count and (count - old_count) > 30:
        return "一次不能操作多于 30 张卡"
    
    # 检查是否卡数发生变化
    if old_count == count:
        arcade = arcade_data.find_arcade(place)
        display_name = arcade['name'] if arcade else place
        return f"卡数没有变化。\n{display_name}现在{_format_count_with_avg(count, arcade)}"
    
    arcade['person'] = count
    arcade['time'] = _today_iso()
    arcade['by'] = user_name
    arcade_data._save_arcades()
    
    # 如果绑定了 Nearcade ID，则上报人数
    if arcade.get('nearcade_id'):
        await update_nearcade_attendance(arcade['nearcade_id'], count)
    
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
    """添加机厅别名"""
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
    """删除机厅别名"""
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


def _bind_nearcade_id(arcade_name: str, nearcade_id: str) -> str:
    """绑定机厅的 Nearcade ID"""
    arcade = arcade_data.find_arcade(arcade_name)
    if not arcade:
        return f"未找到名为 {arcade_name} 的机厅。"
        
    arcade['nearcade_id'] = nearcade_id
    arcade_data._save_arcades()
    
    return f"已成功将机厅 {arcade['name']} 绑定到 Nearcade ID: {nearcade_id}"


def _find_arcades(keyword: str) -> str:
    """查找机厅"""
    results = []
    keyword_lower = keyword.lower()
    for arcade in arcade_data.arcades:
        if not isinstance(arcade, dict):
            continue
        if keyword_lower in arcade.get('name', '').lower() or any(keyword_lower in alias.lower() for alias in arcade.get('alias', [])):
            display_name = arcade.get('name', '')  # 使用完整机厅名称
            # 格式化结果为新的样式
            result_line = f"==========\n店名：{display_name}\n地址：{arcade.get('address', '')}\n店铺 ID：{arcade.get('id', '')}\n舞萌 DX 机台数量：{arcade.get('mainum', 0)}\n中二节奏机台数量：{arcade.get('chuninum', 0)}"
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
        return '指令错误，请再次确认指令格式\n添加机厅 <店名> <地址> <舞萌 DX 机台数量> <中二节奏机台数量> <简称 1> [简称 2] ...'
    
    # 检查舞萌 DX 机台数量是否为数字
    if not args[2].isdigit():
        return '指令错误，请再次确认指令格式\n添加机厅 <店名> <地址> <舞萌 DX 机台数量> <中二节奏机台数量> <简称 1> [简称 2] ...'
    
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
        'id': '',  # ID 将在 add_arcade 方法中生成
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
        return f'未找到机厅：{name}'
    
    # 删除机厅
    if arcade_data.del_arcade(name):
        return f'已删除机厅：{name}'
    else:
        return f'删除机厅{name}失败'


def _help_text() -> str:
    """帮助文本"""
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
        "----以下功能仅限群管理员操作----\n",
        "  查找机厅 <关键词>   使用关键词查找机厅",
        "  订阅机厅 <机厅名>    订阅机厅",
        "  取消订阅机厅 <机厅名>  取消订阅",
        "  添加别名 <机厅名> <别名>  添加机厅别名",
        "  删除别名 <机厅名> <别名>  删除机厅别名",
        "  添加机厅 <店名> <地址> <舞萌 DX 机台数量> <中二节奏机台数量> <简称>  添加机厅信息",
        "  删除机厅 <店名>  删除机厅信息",
        "  查机厅id <关键词>：从 Nearcade 搜索机厅 ID",
        "  绑定机厅id <机厅名> <Nearcade机厅ID> 将本地机厅数据绑定Nearcade数据源"
        ""
    ])


def _subscribe_regex(group_id: str, name: str, is_subscribe: bool) -> str:
    """订阅或取消订阅机厅 - 支持模糊匹配和更友好的反馈"""
    # 首先尝试精确匹配（名称或 ID）
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
            names = [arc['name'] for arc in fuzzy_results[:5]]  # 只显示前 5 个
            extra_count = len(fuzzy_results) - 5 if len(fuzzy_results) > 5 else 0
            extra_text = f"，还有{extra_count}个结果" if extra_count > 0 else ""
            return f'找到多个相似的机厅：{"、".join(names)}{extra_text}，请使用完整名称或 ID 操作。'
        else:
            # 如果找到唯一匹配项，使用该机厅
            existing_arcades = fuzzy_results
    
    # 检查是否有多个匹配项
    if len(existing_arcades) > 1:
        return f'发现多个重复条目，请直接使用店铺 ID 更改机厅别名\n' + '\n'.join([ f'{arc["id"]}：{arc["name"]}' for arc in existing_arcades ])
    
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