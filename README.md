<!-- markdownlint-disable MD033 MD036 MD041 -->

<div align="center">
<a href="https://v2.nonebot.dev/store">
  <img src="https://raw.githubusercontent.com/A-kirami/nonebot-plugin-template/resources/nbp_logo.png" width="180" height="180" alt="NoneBotPluginLogo">
</a>
<p>
  <img src="https://raw.githubusercontent.com/lgc-NB2Dev/readme/main/template/plugin.svg" alt="NoneBotPluginText">
</p>

# NoneBot-Plugin-QueryPlace
_✨ 一款深度集成 [Nearcade](https://nearcade.phizone.cn/) 的机厅排卡插件 for NoneBot2 ✨_
  
<img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="python">
<a href="./LICENSE">
  <img src="https://img.shields.io/github/license/lgc2333/nonebot-plugin-picstatus.svg" alt="license">
</a>
<br />
</div>

## 简介

这是一个为 NoneBot2 设计的机厅排卡与查询插件，主要服务于舞萌DX、中二节奏等街机音游玩家群体。

本插件支持向 [Nearcade](https://nearcade.phizone.cn/) 上报与同步机厅人数数据。

## 安装方法

1. 将插件文件夹 `nonebot_plugin_queryplace` 放置在 NoneBot2 项目的插件目录中。
2. 填写对应的配置项（详见下文）。如果您不需要自动同步功能，可以跳过 `nearcade_id` 的配置。
3. 重启 NoneBot2。插件将在首次启动时自动创建所需的数据文件。

## 配置说明

插件支持两种配置方式：通过 `.env` 文件进行全局配置，以及通过 `arcades.json` 文件进行详细的机厅数据配置。

### `.env` 文件配置

在 NoneBot2 的 `.env` 文件中，您可以添加以下配置项：

| 配置项 | 说明 | 可选值 | 默认值 |
| :--- | :--- | :--- | :--- |
| `machine_calc_mode` | 在查询机厅人数计算平均人数时所依据的机台类型。 | `mai`（舞萌DX）, `chu`（中二节奏）， `all` | `all` |
| `use_online_database` | 启动时是否从华立的官网机台列表拉取最新的机厅列表。 | `true`, `false` | `true` |
| `nearcade_token` | 用于通过指令向 Nearcade **上报**人数的 API 令牌。 | 你的 Nearcade 令牌，注册Nearcade账号后从[这里](https://nearcade.phizone.cn/settings/api-tokens)获取 | [nonebot_plugin_mai_arcade](https://github.com/YuuzukiRin/nonebot_plugin_mai_arcade)中的默认Token |

### `arcades.json`/`arcades-local.json` 文件配置

插件的核心数据配置位于 `data/nonebot_plugin_queryplace/arcades.json` 或 `data/nonebot_plugin_queryplace/arcades-local.json` 文件中。为了启用与 Nearcade 的自动**查询同步**功能，您需要为机厅条目添加 `nearcade_id`。

### `arcades.json`/`arcades-local.json` 字段说明

```json
{
  "arcades": [
    {
      "name": "机厅官方全名",
      "address": "机厅详细地址",
      "mall": "所在商场",
      "province": "省份",
      "mainum": 0, #舞萌DX的机台数量
      "chuninum": 0, #中二节奏的机台数量
      "id": "10001",
      "alias": ["别名1", "别名2"],
      "group": [123456789],
      "person": 0,
      "by": "",
      "time": "",
      "nearcade_id": "ARCADE_NEARCADE_ID"
    }
  ]
}
```

- **`nearcade_id`**: 在 [Nearcade](https://nearcade.phizone.cn/) 上的机厅 ID。**配置此项后，插件才能自动同步和上报该机厅的数据。**
- **`name`**: 机厅的官方名称。
- **`alias`**: 机厅的别名列表，用户可以通过别名进行查询和操作。
- **`group`**: 已订阅该机厅的群号列表。

## 指令

### 用户指令

- `<机厅名>++`: 人数加一。
- `<机厅名>--`: 人数减一。
- `<机厅名>+N`: 人数加 N。
- `<机厅名>-N`: 人数减 N。
- `<机厅名>N` / `=N`: 直接将人数设置为 N。
- `<机厅名>几` / `j`: 查询该机厅当前人数。
- `<机厅名>有谁`: 查看该机厅今日的所有人数变更记录（包括手动和自动同步）。
- `<机厅名>在哪`: 查询机厅的详细地址。
- `j` / `几` / `jtj`: 查询本群所有已订阅机厅的当前人数。
- `机厅列表`: 查看本群所有已订阅的机厅及其别名。

### 管理员指令 (群管理员或Bot超级用户)

- `查找机厅 <关键词>`: 从获取的华立官网机台列表中搜索机厅。
- `订阅机厅 <机厅名>`: 将指定机厅订阅到当前群聊。
- `取消订阅 <机厅名>`: 取消当前群聊对指定机厅的订阅。
- `添加别名 <机厅名> <别名>`: 为机厅添加一个别名。
- `删除别名 <机厅名> <别名>`: 删除机厅的指定别名。
- `添加机厅 <店名> <地址> <舞萌数量> <中二数量> <简称>`: 手动添加一个新机厅。
- `删除机厅 <店名>`: 删除一个机厅。
- `查机厅id <关键词>`: 查询机厅的 `nearcade_id`，以便配置自动同步。
- `绑定机厅 <机厅名/别名> <nearcade_id>`: 将某个机厅与 Nearcade 上的机厅 ID 绑定，以启用自动同步功能。

## 数据存储

插件的数据存储在 `data/nonebot_plugin_queryplace/` 目录下：

- `arcades.json`/`arcades-local.json`: 存储获取的华立官网机台列表或本地配置文件中的所有机厅的数据，包括别名、订阅关系和 `nearcade_id`。
- `history.json`: 存储所有机厅每日的人数变更历史。

---

Thanks to [YounBot](https://github.com/BakaBotTeam/YounBot/blob/master/YounBot/Listener/QueryPlaceListener.cs), [ArcadeQueue](https://github.com/SalinX/ArcadeQueue.git), [CrazyKid's AP Bot](https://github.com/Nyano1337/CrazyKid-QQRobot/blob/master/src/main/java/cn/crazykid/qqrobot/listener/group/message/GroupMessageMaimaiQueueCardListener.kt),[nonebot_plugin_mai_arcade](https://github.com/YuuzukiRin/nonebot_plugin_mai_arcade) ~~Copilot, TRAE and Qwen Studio(((~~