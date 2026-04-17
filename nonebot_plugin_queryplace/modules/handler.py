"""
消息处理器模块 - 主入口
"""
from __future__ import annotations

import re
from nonebot import on_message, get_driver, require
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
)


# 正则表达式模式
SUBTRACT_PATTERN = re.compile(r"^(.+?)(?<!\d)-(\d+)$")
ADD_PATTERN = re.compile(r"^(.+?)(?<!\d)\+(\d+)$")
INCREMENT_PATTERN = re.compile(r"^(.+?)(?<!\d)\+\+$")
DECREMENT_PATTERN = re.compile(r"^(.+?)(?<!\d)--$")
HELP_PATTERN = re.compile(r"^(help q|帮助排卡 | 排卡帮助|help 排卡|help queue)$", re.IGNORECASE)
SET_EQUAL_PATTERN = re.compile(r"^(.+?)=(\d+)$")
SET_DIRECT_PATTERN = re.compile(r"^(.+?)(?<!\d)(\d+)$")
QUERY_PATTERN = re.compile(r"^(.+?)(?<!\d)(几|j|jtj|多少人 | 有几人 | 有几卡 | 多少人 | 多少卡 | 几人 | 几卡|J|JTJ|jk|JK|几神 | 几爷 | 几爹)$", re.IGNORECASE)
HISTORY_PATTERN = re.compile(r"^(.+?)\有谁$", re.IGNORECASE)
ADD_ALIAS_PATTERN = re.compile(r"^添加别名\s+(.+?)\s+(.+)$")
DEL_ALIAS_PATTERN = re.compile(r"^删除别名\s+(.+?)\s+(.+)$")
FIND_ARCADE_PATTERN = re.compile(r"^查找机厅\s+(.+)$")
VIEW_LIST_PATTERN = re.compile(r"^(机厅列表)$", re.IGNORECASE)
SUBSCRIBE_REGEX_PATTERN = re.compile(r"^(订阅机厅 | 取消订阅机厅 | 取消订阅)\s+(.+)", re.IGNORECASE)
ADD_ARCADE_PATTERN = re.compile(r"^(添加机厅 | 新增机厅)\s+(.+)$", re.IGNORECASE)
DELETE_ARCADE_PATTERN = re.compile(r"^(删除机厅 | 移除机厅)\s+(.+)$", re.IGNORECASE)
LOCATION_QUERY_PATTERN = re.compile(r"^(.+?)(?<!\d)(在哪)$", re.IGNORECASE)

matcher = on_message(priority=10, block=False)


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


@matcher.handle()
async def handle_query(bot: Bot, event: GroupMessageEvent) -> None:
    """处理消息"""
    text = str(event.get_message()).strip()
    if not text:
        return

    # 检查是否需要重置每日数据
    _check_and_reset_daily_data()

    group_id = str(event.group_id)
    user_name = event.sender.nickname or str(event.user_id)

    # 帮助命令
    if HELP_PATTERN.fullmatch(text):
        help_text = _help_text()
        img = text_to_image(help_text)
        base64_img = image_to_base64(img)
        await matcher.finish(MessageSegment.reply(event.message_id) + MessageSegment.image(base64_img))
        return

    # 机厅列表
    if VIEW_LIST_PATTERN.fullmatch(text):
        list_text = _format_arcade_list(group_id)
        await matcher.finish(_reply_text(event, list_text))
        return

    # 查询所有机厅
    if text.lower() in {"j", "jtj", "jk", "几卡", "几神", "几爷", "几爹", "多少人", "有几人", "有几卡", "多少人", "多少卡", "几人", "几"}:
        response = _query_all(group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 查询机厅地址
    if m := LOCATION_QUERY_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _query_location(place)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 减少指定数量
    if m := SUBTRACT_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _apply_delta(place, -number, user_name, "subtract", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 增加指定数量
    if m := ADD_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _apply_delta(place, number, user_name, "add", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 增加 1
    if m := INCREMENT_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _apply_delta(place, 1, user_name, "increment", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 减少 1
    if m := DECREMENT_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _apply_delta(place, -1, user_name, "decrement", group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 设置为指定值 (=)
    if m := SET_EQUAL_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _set_single_count(place, number, user_name, group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 设置为指定值 (直接数字)
    if m := SET_DIRECT_PATTERN.fullmatch(text):
        place, number_text = m.groups()
        number = int(number_text)
        response = _set_single_count(place, number, user_name, group_id)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 查询单个机厅
    if m := QUERY_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _query_place(place, place)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 查询历史记录
    if m := HISTORY_PATTERN.fullmatch(text):
        place = m.group(1)
        response = _query_history(place)
        if response:
            await matcher.finish(_reply_text(event, response))
        return

    # 订阅/取消订阅
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

    # 添加别名
    if m := ADD_ALIAS_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可添加别名"))
            return
        arcade_name, alias = m.groups()
        response = _add_alias(arcade_name, alias)
        await matcher.finish(_reply_text(event, response))
        return

    # 删除别名
    if m := DEL_ALIAS_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可删除别名"))
            return
        arcade_name, alias = m.groups()
        response = _del_alias(arcade_name, alias)
        await matcher.finish(_reply_text(event, response))
        return

    # 添加机厅
    if m := ADD_ARCADE_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可添加机厅"))
            return
        command_text = m.group(2).strip()
        response = _add_arcade(command_text)
        await matcher.finish(_reply_text(event, response))
        return

    # 删除机厅
    if m := DELETE_ARCADE_PATTERN.fullmatch(text):
        if not _is_admin(event):
            await matcher.finish(_reply_text(event, "权限不足：仅群管理员可删除机厅"))
            return
        command_text = m.group(2).strip()
        response = _delete_arcade(command_text)
        await matcher.finish(_reply_text(event, response))
        return

    # 查找机厅
    if m := FIND_ARCADE_PATTERN.fullmatch(text):
        keyword = m.group(1)
        text_result = _find_arcades(keyword)
        img = text_to_image(text_result)
        base64_img = image_to_base64(img)
        await matcher.finish(MessageSegment.reply(event.message_id) + MessageSegment.image(base64_img))
        return
