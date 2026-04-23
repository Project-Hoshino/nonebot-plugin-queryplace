"""
Nearcade API 服务模块
"""
from __future__ import annotations

import httpx
import urllib.parse
from typing import Dict, List, Any

from nonebot.log import logger

from .config import NEARCAADE_TOKEN


async def search_nearcade_shops(keyword: str, page: int = 1, limit: int = 5) -> Dict[str, Any]:
    """
    通过关键词搜索 Nearcade 机厅

    Args:
        keyword: 搜索关键词
        page: 页码
        limit: 每页数量

    Returns:
        API 响应的字典
    """
    if not keyword:
        return {'shops': [], 'totalCount': 0}

    try:
        encoded_query = urllib.parse.quote(keyword)
        url = f"https://nearcade.phizone.cn/api/shops?q={encoded_query}&page={page}&limit={limit}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; NoneBot-QueryPlace-Plugin)',
            'Accept': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return {
                'shops': data.get('shops', []),
                'totalCount': data.get('totalCount', 0)
            }
    except Exception as e:
        logger.error(f"搜索 Nearcade 机厅失败: {e}")
        return {'shops': [], 'totalCount': 0}


async def update_nearcade_attendance(shop_id: str, count: int) -> bool:
    """
    更新 Nearcade 机厅的排队人数 (bemanicn 专用接口)

    Args:
        shop_id: Nearcade 机厅 ID (bemanicn ID)
        count: 当前排队人数

    Returns:
        是否成功更新
    """
    if not NEARCAADE_TOKEN:
        logger.warning("未配置 NEARCAADE_TOKEN，无法上报人数")
        return False

    headers = {
        'Authorization': f'Bearer {NEARCAADE_TOKEN}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (compatible; NoneBot-QueryPlace-Plugin)'
    }

    try:
        async with httpx.AsyncClient() as client:
            # Step 1: Get game_id from the bemanicn-specific endpoint
            get_url = f"https://nearcade.phizone.cn/api/shops/bemanicn/{shop_id}"
            get_response = await client.get(get_url, headers=headers)
            get_response.raise_for_status()
            
            shop_data = get_response.json()
            games = shop_data.get("shop", {}).get("games", [])
            if not games:
                logger.error(f"上报 Nearcade 人数失败：机厅 {shop_id} 没有找到任何游戏信息。")
                return False
            
            # Following mai_arcade's logic, use the first game's ID
            game_id = games[0].get("gameId")
            if not game_id:
                logger.error(f"上报 Nearcade 人数失败：机厅 {shop_id} 的第一个游戏没有 gameId。")
                return False

            # Step 2: Post attendance with game_id
            post_url = f"https://nearcade.phizone.cn/api/shops/bemanicn/{shop_id}/attendance"
            payload = {
                "games": [
                    {"id": game_id, "currentAttendances": count}
                ]
            }
            
            post_response = await client.post(post_url, headers=headers, json=payload)
            post_response.raise_for_status()
            
            logger.info(f"成功向 Nearcade (bemanicn) 上报机厅 {shop_id} 的人数: {count} (Game ID: {game_id})")
            return True
            
    except httpx.HTTPStatusError as e:
        logger.error(f"上报 Nearcade 人数时发生HTTP错误: {e.response.status_code} - {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"上报 Nearcade 人数时发生未知错误: {e}")
        return False


async def get_nearcade_attendance(shop_id: str) -> int | None:
    """
    从 Nearcade (bemanicn) 获取机厅的排队人数

    Args:
        shop_id: Nearcade 机厅 ID (bemanicn ID)

    Returns:
        当前排队人数，如果失败则返回 None
    """
    url = f"https://nearcade.phizone.cn/api/shops/bemanicn/{shop_id}/attendance"
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; NoneBot-QueryPlace-Plugin)',
        'Accept': 'application/json'
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            # The bemanicn endpoint returns a 'total' field for the attendance count
            total = data.get('total')
            if isinstance(total, int):
                logger.info(f"成功从 Nearcade (bemanicn) 获取机厅 {shop_id} 的人数: {total}")
                return total
            else:
                logger.warning(f"从 Nearcade (bemanicn) 获取机厅 {shop_id} 的人数时，返回的数据格式不正确: {data}")
                return None
    except httpx.HTTPStatusError as e:
        logger.error(f"从 Nearcade (bemanicn) 获取人数失败 (HTTP {e.response.status_code}): {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"从 Nearcade (bemanicn) 获取人数时发生未知错误: {e}")
        return None