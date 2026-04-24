"""
nonebot_plugin_queryplace - 查询卡数插件

重构后的模块化结构:
- modules/config: 配置和工具模块
- modules/arcade: 机厅数据管理模块
- modules/history: 历史记录管理模块  
- modules/service: 查询业务逻辑模块
- modules/handler: 消息处理器（主入口）
"""

from .modules.handler import *

__plugin_usage__ = """
排卡插件

- 核心功能 -
机厅名++：当前人数 +1
机厅名--：当前人数 -1
机厅名+N：当前人数 +N
机厅名-N：当前人数 -N
机厅名 N / 机厅名=N：设置当前人数为 N
机厅名 几/j/J：查询机厅人数
j / 几 / jtj：查询本群所有机厅人数

- 机厅信息 -
机厅列表：显示本群订阅的机厅
机厅名 有谁：查询最近更新记录
机厅名 在哪：查询机厅地址
查找机厅 <关键词>：查找本地机厅

- 机厅管理 (仅限群管理员) -
添加机厅 <店名> <地址> <舞萌DX机台数> <中二节奏机台数> <简称>
删除机厅 <店名>
添加别名 <机厅名> <别名>
删除别名 <机厅名> <别名>
订阅机厅 <机厅名>
取消订阅 <机厅名>

- Nearcade 联动 (需配置 .env 中的 nearcade_token) -
查机厅id <关键词>：从 Nearcade 搜索机厅 ID
绑定机厅id <本地机厅名> <Nearcade机厅ID> (仅限群管理员)
(绑定后，更新人数会自动上传，查询时会自动同步最新数据)

- 配置项 (在 .env.* 文件中配置) -
- `machine_calc_mode`: 机均人数计算方式。
    - `mai`: 按舞萌DX机台数计算
    - `chu`: 按中二节奏机台数计算
    - `all`: 按总机台数计算 (默认)
    - `off`: 关闭机均显示
- `use_online_database`: 是否使用在线机厅数据 (true/false)。
"""

__version__ = "2.0.0"