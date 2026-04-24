"""
消息处理器模块 - 主入口
"""
from __future__ import annotations

import re
from nonebot import on_command, on_regex, get_driver, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot_plugin_apscheduler import scheduler

from .config import (
    driver,
    plugin_config,
    text_to_image,
    image_to_base64,
    _get_current_day_key,
)
from .arcade import arcade_data
from .history import history_data
from .service import (
    query_cache,
    _query_all,
    _query_place,
    _query_history,
    _query_location,
    _apply_delta,
    _set_single_count,
    _subscribe_arcade,
    _unsubscribe_arcade,
    _add_alias,
    _del_alias,
    _find_arcades,
    _format_arcade_list,
    _add_arcade,
    _delete_arcade,
    _help_text,
    _subscribe_regex,
    _bind_nearcade_id,
)
from .nearcade_service import search_nearcade_shops


# 正则表达式模式
SUBTRACT_PATTERN = r"^(.+?)(?<!\d)-(\d+)$"
ADD_PATTERN = r"^(.+?)(?<!\d)\+(\d+)$"
INCREMENT_PATTERN = r"^(.+?)(?<!\d)\+\+$"
DECREMENT_PATTERN = r"^(.+?)(?<!\d)--$"
HELP_PATTERN = r"^(help q|帮助排卡|排卡帮助|help 排卡|help queue)$"
SET_EQUAL_PATTERN = r"^(.+?)=(\d+)$"
SET_DIRECT_PATTERN = r"^(.+?)(?<!\d)(\d+)$"
# 查询模式
# 排序关键字以确保最长匹配优先
_SINGLE_QUERY_KEYWORDS_ORDERED = [
    "多少人", "有几人", "有几卡", "多少卡",
    "几卡", "几神", "几爷", "几爹", "几人",
    "jtj", "jk", "j", "几"
]
SINGLE_QUERY_PATTERN = rf"^(.+?)(?<!\d)({'|'.join(_SINGLE_QUERY_KEYWORDS_ORDERED)})$"
HISTORY_LOCATION_PATTERN = r"^(.+?)(?<!\d)(有谁|在哪)$"
ALL_QUERY_PATTERN = r"^(?:jtj|jk|j|几卡|几神|几爷|几爹|多少人|有几人|有几卡|多少卡|几人|几)$"
ADD_ALIAS_PATTERN = r"^添加别名\s+(.+?)\s+(.+)$"
DEL_ALIAS_PATTERN = r"^删除别名\s+(.+?)\s+(.+)$"
FIND_ARCADE_PATTERN = r"^查找机厅\s+(.+)$"
VIEW_LIST_PATTERN = r"^(机厅列表)$"
SUBSCRIBE_REGEX_PATTERN = r"^订阅机厅[\s\u3000]*(.+)"
UNSUBSCRIBE_REGEX_PATTERN = r"^取消订阅(?:机厅)?[\s\u3000]*(.+)"
ADD_ARCADE_PATTERN = r"^(添加机厅 | 新增机厅)\s+(.+)$"
DELETE_ARCADE_PATTERN = r"^(删除机厅 | 移除机厅)\s+(.+)$"
FIND_NEARCAADE_ID_PATTERN = r"^查机厅id\s+(.+)$"
BIND_NEARCAADE_ID_PATTERN = r"^绑定机厅id\s+(.+?)\s+(\d+)$"




def _reply_text(event: GroupMessageEvent, text: str) -> MessageSegment:
    """生成回复消息"""
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


def _check_and_reset_daily_data():
    """检查是否需要重置每日数据"""
    from datetime import datetime, timedelta
    
    now = datetime.now()
    # 如果当前时间是 4 点之后，且上次更新时间在 4 点之前，则重置数据
    if now.hour >= 4:
        # 检查是否有过期的数据需要重置
        should_reset = False
        for arcade in arcade_data.arcades:
            if isinstance(arcade, dict) and arcade.get('time'):
                try:
                    time_obj = datetime.fromisoformat(arcade['time'])
                    # 如果记录的时间是昨天或更早的日期（按游戏日计算），则重置
                    if time_obj.hour >= 4:
                        # 更新时间 >= 4 点，属于当天的游戏日
                        update_game_day = time_obj.date()
                    else:
                        # 更新时间 < 4 点，属于前一天的游戏日
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


@driver.on_startup
async def load_data():
    """启动时加载数据"""
    await arcade_data.load_arcades()
    history_data.load_history()
    # 启动时检查是否需要重置数据
    arcade_data.check_and_reset_if_needed()


@scheduler.scheduled_job("cron", hour=4, minute=0, id="reset_daily_data")
async def reset_daily_data():
    """每天 4 点重置数据"""
    print("正在重置每日数据...")
    arcade_data.reset_daily_data()
    # 清空历史记录 - 使用统一的游戏日逻辑
    current_day_key = _get_current_day_key()
    history_data.last_reset_date = current_day_key
    history_data.history = {}  # 清空所有历史记录
    history_data.save_history()
    print("每日数据重置完成")


# 帮助命令
help_matcher = on_command("help q", aliases={"帮助排卡", "排卡帮助", "help 排卡", "help queue"}, priority=10, block=True)

@help_matcher.handle()
async def handle_help(bot: Bot, event: GroupMessageEvent) -> None:
    """处理帮助命令"""
    _check_and_reset_daily_data()
    help_text = _help_text()
    img = text_to_image(help_text)
    base64_img = image_to_base64(img)
    await help_matcher.finish(MessageSegment.reply(event.message_id) + MessageSegment.image(base64_img))


# 机厅列表命令
list_matcher = on_command("机厅列表", priority=10, block=True)

@list_matcher.handle()
async def handle_list(bot: Bot, event: GroupMessageEvent) -> None:
    """处理机厅列表命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    list_text = _format_arcade_list(group_id)
    await list_matcher.finish(_reply_text(event, list_text))


# 查询所有机厅命令
all_query_matcher = on_regex(ALL_QUERY_PATTERN, priority=5, block=True)

@all_query_matcher.handle()
async def handle_all_query(bot: Bot, event: GroupMessageEvent) -> None:
    """处理查询所有机厅命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    response = _query_all(group_id)
    if response:
        await all_query_matcher.finish(_reply_text(event, response))


# 订阅机厅命令
subscribe_matcher = on_regex(SUBSCRIBE_REGEX_PATTERN, priority=10, block=True)

@subscribe_matcher.handle()
async def handle_subscribe(bot: Bot, event: GroupMessageEvent) -> None:
    """处理订阅机厅命令"""
    _check_and_reset_daily_data()
    if not _is_admin(event):
        await subscribe_matcher.finish(_reply_text(event, "权限不足：仅群管理员可订阅机厅"))
        return
    group_id = str(event.group_id)
    text = str(event.get_message()).strip()
    match = re.match(SUBSCRIBE_REGEX_PATTERN, text)
    if match:
        arcade_name = match.group(1).strip()
        response = _subscribe_regex(group_id, arcade_name, True)
        await subscribe_matcher.finish(_reply_text(event, response))


# 取消订阅机厅命令
unsubscribe_matcher = on_regex(UNSUBSCRIBE_REGEX_PATTERN, priority=10, block=True)

@unsubscribe_matcher.handle()
async def handle_unsubscribe(bot: Bot, event: GroupMessageEvent) -> None:
    """处理取消订阅机厅命令"""
    _check_and_reset_daily_data()
    if not _is_admin(event):
        await unsubscribe_matcher.finish(_reply_text(event, "权限不足：仅群管理员可取消订阅机厅"))
        return
    group_id = str(event.group_id)
    text = str(event.get_message()).strip()
    match = re.match(UNSUBSCRIBE_REGEX_PATTERN, text)
    if match:
        arcade_name = match.group(1).strip()
        response = _subscribe_regex(group_id, arcade_name, False)
        await unsubscribe_matcher.finish(_reply_text(event, response))


# 添加别名命令
add_alias_matcher = on_regex(ADD_ALIAS_PATTERN, priority=10, block=True)

@add_alias_matcher.handle()
async def handle_add_alias(bot: Bot, event: GroupMessageEvent) -> None:
    """处理添加别名命令"""
    _check_and_reset_daily_data()
    if not _is_admin(event):
        await add_alias_matcher.finish(_reply_text(event, "权限不足：仅群管理员可添加别名"))
        return
    text = str(event.get_message()).strip()
    match = re.match(ADD_ALIAS_PATTERN, text)
    if match:
        arcade_name, alias = match.groups()
        response = _add_alias(arcade_name, alias)
        await add_alias_matcher.finish(_reply_text(event, response))


# 删除别名命令
del_alias_matcher = on_regex(DEL_ALIAS_PATTERN, priority=10, block=True)

@del_alias_matcher.handle()
async def handle_del_alias(bot: Bot, event: GroupMessageEvent) -> None:
    """处理删除别名命令"""
    _check_and_reset_daily_data()
    if not _is_admin(event):
        await del_alias_matcher.finish(_reply_text(event, "权限不足：仅群管理员可删除别名"))
        return
    text = str(event.get_message()).strip()
    match = re.match(DEL_ALIAS_PATTERN, text)
    if match:
        arcade_name, alias = match.groups()
        response = _del_alias(arcade_name, alias)
        await del_alias_matcher.finish(_reply_text(event, response))


# 添加机厅命令
add_arcade_matcher = on_regex(ADD_ARCADE_PATTERN, priority=10, block=True)

@add_arcade_matcher.handle()
async def handle_add_arcade(bot: Bot, event: GroupMessageEvent) -> None:
    """处理添加机厅命令"""
    _check_and_reset_daily_data()
    if not _is_admin(event):
        await add_arcade_matcher.finish(_reply_text(event, "权限不足：仅群管理员可添加机厅"))
        return
    text = str(event.get_message()).strip()
    match = re.match(ADD_ARCADE_PATTERN, text)
    if match:
        command_text = match.group(2).strip()
        response = _add_arcade(command_text)
        await add_arcade_matcher.finish(_reply_text(event, response))


# 删除机厅命令
delete_arcade_matcher = on_regex(DELETE_ARCADE_PATTERN, priority=10, block=True)

@delete_arcade_matcher.handle()
async def handle_delete_arcade(bot: Bot, event: GroupMessageEvent) -> None:
    """处理删除机厅命令"""
    _check_and_reset_daily_data()
    if not _is_admin(event):
        await delete_arcade_matcher.finish(_reply_text(event, "权限不足：仅群管理员可删除机厅"))
        return
    text = str(event.get_message()).strip()
    match = re.match(DELETE_ARCADE_PATTERN, text)
    if match:
        command_text = match.group(2).strip()
        response = _delete_arcade(command_text)
        await delete_arcade_matcher.finish(_reply_text(event, response))


# 查找机厅命令
find_arcade_matcher = on_regex(FIND_ARCADE_PATTERN, priority=10, block=True)

@find_arcade_matcher.handle()
async def handle_find_arcade(bot: Bot, event: GroupMessageEvent) -> None:
    """处理查找机厅命令"""
    _check_and_reset_daily_data()
    text = str(event.get_message()).strip()
    match = re.match(FIND_ARCADE_PATTERN, text)
    if match:
        keyword = match.group(1)
        text_result = _find_arcades(keyword)
        img = text_to_image(text_result)
        base64_img = image_to_base64(img)
        await find_arcade_matcher.finish(MessageSegment.reply(event.message_id) + MessageSegment.image(base64_img))


# 查机厅id命令
find_nearcade_id_matcher = on_regex(FIND_NEARCAADE_ID_PATTERN, priority=10, block=True)

@find_nearcade_id_matcher.handle()
async def handle_find_nearcade_id(bot: Bot, event: GroupMessageEvent) -> None:
    """处理查机厅id命令"""
    _check_and_reset_daily_data()
    text = str(event.get_message()).strip()
    match = re.match(FIND_NEARCAADE_ID_PATTERN, text)
    if match:
        keyword = match.group(1)
        result = await search_nearcade_shops(keyword)
        
        if not result or not result['shops']:
            await find_nearcade_id_matcher.finish(_reply_text(event, "未在 Nearcade 上找到匹配的机厅。"))
            return

        lines = [f"在 Nearcade 上找到 {result['totalCount']} 个结果："]
        for shop in result['shops']:
            shop_id = shop.get('id', '未知ID')
            name = shop.get('name', '未知名称')
            address = shop.get('address', '未知地址')
            lines.append(f"机厅名: {name}\n地址: {address}\nID: {shop_id}\n--------------------")

        response_text = "\n".join(lines)
        img = text_to_image(response_text)
        base64_img = image_to_base64(img)
        await find_nearcade_id_matcher.finish(MessageSegment.reply(event.message_id) + MessageSegment.image(base64_img))


# 绑定机厅id命令
bind_nearcade_id_matcher = on_regex(BIND_NEARCAADE_ID_PATTERN, priority=10, block=True)

@bind_nearcade_id_matcher.handle()
async def handle_bind_nearcade_id(bot: Bot, event: GroupMessageEvent) -> None:
    """处理绑定机厅id命令"""
    _check_and_reset_daily_data()
    if not _is_admin(event):
        await bind_nearcade_id_matcher.finish(_reply_text(event, "权限不足：仅群管理员可绑定机厅ID"))
        return
    
    text = str(event.get_message()).strip()
    match = re.match(BIND_NEARCAADE_ID_PATTERN, text)
    if match:
        arcade_name, nearcade_id = match.groups()
        response = _bind_nearcade_id(arcade_name, nearcade_id)
        await bind_nearcade_id_matcher.finish(_reply_text(event, response))


# 查询单个机厅人数命令
single_query_matcher = on_regex(SINGLE_QUERY_PATTERN, priority=10, block=True)

@single_query_matcher.handle()
async def handle_single_query(bot: Bot, event: GroupMessageEvent) -> None:
    """处理查询单个机厅人数命令"""
    _check_and_reset_daily_data()
    text = str(event.get_message()).strip()
    match = re.match(SINGLE_QUERY_PATTERN, text)
    if match:
        place, _ = match.groups()
        response = await _query_place(place, place)
        if response:
            await single_query_matcher.finish(_reply_text(event, response))


# 查询历史记录和地址命令
history_location_matcher = on_regex(HISTORY_LOCATION_PATTERN, priority=10, block=True)

@history_location_matcher.handle()
async def handle_history_location(bot: Bot, event: GroupMessageEvent) -> None:
    """处理查询历史记录和地址命令"""
    _check_and_reset_daily_data()
    text = str(event.get_message()).strip()
    match = re.match(HISTORY_LOCATION_PATTERN, text)
    if match:
        place, query_type = match.groups()
        if query_type == "有谁":
            response = _query_history(place)
        else:  # 在哪
            response = _query_location(place)
        if response:
            await history_location_matcher.finish(_reply_text(event, response))


# 减少指定数量命令
subtract_matcher = on_regex(SUBTRACT_PATTERN, priority=10, block=True)

@subtract_matcher.handle()
async def handle_subtract(bot: Bot, event: GroupMessageEvent) -> None:
    """处理减少指定数量命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)
    text = str(event.get_message()).strip()
    match = re.match(SUBTRACT_PATTERN, text)
    if match:
        place, number_text = match.groups()
        number = int(number_text)
        response = await _apply_delta(place, -number, user_name, "subtract", group_id)
        if response:
            await subtract_matcher.finish(_reply_text(event, response))


# 增加指定数量命令
add_matcher = on_regex(ADD_PATTERN, priority=10, block=True)

@add_matcher.handle()
async def handle_add(bot: Bot, event: GroupMessageEvent) -> None:
    """处理增加指定数量命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)
    text = str(event.get_message()).strip()
    match = re.match(ADD_PATTERN, text)
    if match:
        place, number_text = match.groups()
        number = int(number_text)
        response = await _apply_delta(place, number, user_name, "add", group_id)
        if response:
            await add_matcher.finish(_reply_text(event, response))


# 增加 1 命令
increment_matcher = on_regex(INCREMENT_PATTERN, priority=10, block=True)

@increment_matcher.handle()
async def handle_increment(bot: Bot, event: GroupMessageEvent) -> None:
    """处理增加 1 命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)
    text = str(event.get_message()).strip()
    match = re.match(INCREMENT_PATTERN, text)
    if match:
        place = match.group(1)
        response = await _apply_delta(place, 1, user_name, "increment", group_id)
        if response:
            await increment_matcher.finish(_reply_text(event, response))


# 减少 1 命令
decrement_matcher = on_regex(DECREMENT_PATTERN, priority=10, block=True)

@decrement_matcher.handle()
async def handle_decrement(bot: Bot, event: GroupMessageEvent) -> None:
    """处理减少 1 命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)
    text = str(event.get_message()).strip()
    match = re.match(DECREMENT_PATTERN, text)
    if match:
        place = match.group(1)
        response = await _apply_delta(place, -1, user_name, "decrement", group_id)
        if response:
            await decrement_matcher.finish(_reply_text(event, response))


# 设置为指定值 (=) 命令
set_equal_matcher = on_regex(SET_EQUAL_PATTERN, priority=10, block=True)

@set_equal_matcher.handle()
async def handle_set_equal(bot: Bot, event: GroupMessageEvent) -> None:
    """处理设置为指定值 (=) 命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)
    text = str(event.get_message()).strip()
    match = re.match(SET_EQUAL_PATTERN, text)
    if match:
        place, number_text = match.groups()
        number = int(number_text)
        response = await _set_single_count(place, number, user_name, group_id)
        if response:
            await set_equal_matcher.finish(_reply_text(event, response))


# 设置为指定值 (直接数字) 命令
set_direct_matcher = on_regex(SET_DIRECT_PATTERN, priority=10, block=True)

@set_direct_matcher.handle()
async def handle_set_direct(bot: Bot, event: GroupMessageEvent) -> None:
    """处理设置为指定值 (直接数字) 命令"""
    _check_and_reset_daily_data()
    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)
    text = str(event.get_message()).strip()
    match = re.match(SET_DIRECT_PATTERN, text)
    if match:
        place, number_text = match.groups()
        number = int(number_text)
        response = await _set_single_count(place, number, user_name, group_id)
        if response:
            await set_direct_matcher.finish(_reply_text(event, response))