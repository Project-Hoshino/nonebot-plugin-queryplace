<!-- markdownlint-disable MD033 MD036 MD041 -->

<div align="center">
<a href="https://v2.nonebot.dev/store">
  <img src="https://raw.githubusercontent.com/A-kirami/nonebot-plugin-template/resources/nbp_logo.png" width="180" height="180" alt="NoneBotPluginLogo">
</a>
<p>
  <img src="https://raw.githubusercontent.com/lgc-NB2Dev/readme/main/template/plugin.svg" alt="NoneBotPluginText">
</p>
<img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="python">
<a href="./LICENSE">
  <img src="https://img.shields.io/github/license/lgc2333/nonebot-plugin-picstatus.svg" alt="license">
</a>
<br />
</div>
# NoneBot-Plugin-QueryPlace


_✨ 机厅排卡插件 for NoneBot2 ✨_

## 这是一个用于查询和管理机厅卡数的 NoneBot2 插件，主要用于舞萌DX和中二节奏等街机音乐游戏的机厅排队情况统计。

### 安装方法（~~屎山代码，慎用。~~暂不支持nb install方式安装）

1. 将插件文件放置在 NoneBot2 项目的插件目录中
2. 在 `.env` 配置文件中添加以下配置项（可选）

### 配置项

在 NoneBot2 的 `.env` 配置文件中可添加以下选项：

```bash
# 机台类型计算机均人数（默认为 "all"）
# "mai": 以舞萌DX机台数量计算
# "chu": 以中二节奏机台数量计算  
# "all": 以舞萌DX和中二节奏机台总数计算
machine_calc_mode=all

# 是否使用在线数据库（默认为 true）
# true: 使用在线API获取机厅数据
# false: 使用本地数据
use_online_database=true
```

### 基础指令

#### 普通用户指令

- `<机厅名>++`: 增加 1 卡
- `<机厅名>--`: 减少 1 卡
- `<机厅名>+N`: 增加 N 卡
- `<机厅名>-N`: 减少 N 卡
- `<机厅名>N`: 直接设置卡数为 N
- `<机厅名>=N`: 直接设置卡数为 N
- `<机厅名>几`/`j`/`J`: 查询该机厅卡数
- `<机厅名>有谁`: 查看该机厅的历史记录
- `机厅全名/简称在哪`: 查询机厅地址
- `j`/`几`/`jtj`: 查询本群所有机厅卡数
- `机厅列表`: 查看本群订阅的所有机厅及其别名

#### 管理员指令（仅限群管理员或Bot超级管理员）

- `查找机厅 <关键词>`: 使用关键词查找机厅
- `订阅机厅 <机厅名>`: 订阅机厅
- `取消订阅 <机厅名>`: 取消订阅机厅
- `添加别名 <机厅名> <别名>`: 为机厅添加别名
- `删除别名 <机厅名> <别名>`: 删除机厅别名
- `添加机厅 <店名> <地址> <舞萌DX机台数量> <中二节奏机台数量> <简称>`: 添加机厅信息
- `删除机厅 <店名>`: 删除机厅信息

### 数据存储

插件会在项目目录下创建 `data/nonebot_plugin_queryplace` 文件夹，包含以下文件：

- `arcades.json`: 在线模式下的机厅数据
- `arcades-local.json`: 本地模式下的机厅数据模板
- `history.json`: 操作历史记录

### 本地数据库使用

当 `use_online_database` 设置为 `false` 时，插件会使用本地数据库：

1. 首次运行时会自动创建 `arcades-local.json` 模板文件
2. 编辑模板文件，将示例数据替换为实际的机厅信息
3. 重启机器人使配置生效

本地数据库模板格式：
```json
{
  "arcades": [
    {
      "name": "机厅名称",
      "address": "机厅地址",
      "mall": "商场名称（？）",
      "province": "省份",
      "mainum": 0,  # 舞萌DX机台数量
      "chuninum": 0,  # 中二节奏机台数量
      "id": "唯一标识符",
      "alias": ["别名1", "别名2"],
      "group": [], # 订阅该机厅的群列表
      "person": 0,
      "by": "",
      "time": ""
    }
  ]
}
```

Thanks to [YounBot](https://github.com/BakaBotTeam/YounBot/blob/master/YounBot/Listener/QueryPlaceListener.cs), [ArcadeQueue](https://github.com/SalinX/ArcadeQueue.git), [CrazyKid's AP Bot](https://github.com/Nyano1337/CrazyKid-QQRobot/blob/master/src/main/java/cn/crazykid/qqrobot/listener/group/message/GroupMessageMaimaiQueueCardListener.kt), ~~Copilot and Qwen(((~~