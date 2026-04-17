"""
历史记录管理模块
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from .config import (
    HISTORY_DATA_FILE,
    _get_current_day_key,
    safe_file_write,
)


class HistoryData:
    """历史记录数据管理类"""
    
    def __init__(self):
        self.history: Dict[str, List[Dict[str, Any]]] = {}
        self.last_reset_date = None

    def load_history(self):
        """加载历史记录"""
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
        """保存历史记录"""
        data = {
            "history": self.history,
            "last_reset_date": self.last_reset_date
        }
        try:
            with safe_file_write(HISTORY_DATA_FILE) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史数据失败：{e}")

    def add_record(self, arcade_name: str, action: str, user: str, 
                   count: int = None, old_count: int = None, new_count: int = None):
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


# 全局实例
history_data = HistoryData()
