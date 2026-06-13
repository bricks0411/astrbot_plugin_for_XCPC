# astrbot_plugin_for_XCPC

<p align="center">
  <img src="https://img.shields.io/badge/License-AGPL_3.0-blue.svg" alt="License: AGPL-3.0">
  <img src="https://img.shields.io/badge/Python-3.10+-yellow.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/AstrBot-v4.22.0+-orange.svg" alt="AstrBot v4.22.0+">
  <img src="https://img.shields.io/badge/Codeforces-API-red.svg" alt="Codeforces API">
</p>
<p align="center">
  <img src="https://count.getloli.com/@Brick0411andhisXCPCplugin?name=Brick0411andhisXCPCplugin&theme=green
&padding=10&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">
</p>



面向 XCPC / Codeforces 群聊场景的 AstrBot 插件，提供 Codeforces 用户信息查询、群内账号绑定、近期比赛查询与定时推送、群友 AC 播报等功能。

## 项目简介

`astrbot_plugin_for_XCPC` 以 Codeforces API 为数据源，围绕算法竞赛群聊中的常见需求提供一组轻量工具：

- 查询 Codeforces 用户信息，并通过 AstrBot 文转图服务渲染为卡片
- 查询近期 Codeforces 比赛，并渲染为中文比赛信息卡片
- 将 QQ / 平台用户与 Codeforces handle 按 AstrBot 会话维度绑定
- 周期性轮询已绑定用户的最新提交，发现新的 Accepted 后自动播报
- 支持每日固定时间向指定会话推送近期比赛信息
- 使用 SQLite 持久化绑定关系、播报开关和最近 AC 指纹

目前主要面向 AstrBot 群聊使用场景开发，已将会话标识统一为 `event.unified_msg_origin`，可直接用于 AstrBot 的跨平台消息发送。

## 功能说明

### 1. 用户信息查询

指令：

```text
/cf <Codeforces handle>
```

别名：

```text
/CF
/cF
/Cf
```

返回内容：

- Codeforces handle
- 当前 rating / rank
- 最高 rating
- 贡献值
- 关注数
- 最近在线时间
- 用户头像

查询结果会通过 AstrBot 官方 `html_render()` 接口渲染为图片卡片。卡片主色调会根据用户 rank 自动变化，并带有 `github.com/Brick0411` 水印。

### 2. 比赛信息查询

指令：

```text
/比赛
```

别名：

```text
/contest
/contests
/cf比赛
```

返回内容：

- 比赛名称
- 比赛 ID
- 比赛类型
- 当前阶段
- 开始日期与时间
- 比赛时长
- 距离开赛时间

比赛信息会渲染为中文图片卡片；若 AstrBot 文转图服务异常，则自动回退为纯文本结果。

### 3. 用户绑定

指令：

```text
/绑定 <Codeforces handle>
```

别名：

```text
/绑定cf <Codeforces handle>
```

说明：

- 绑定前会请求 Codeforces API 校验 handle 是否有效
- 同一 AstrBot 会话内，不允许多个用户绑定同一个 Codeforces handle
- 同一平台用户可以在不同 AstrBot 会话绑定不同 Codeforces handle
- 绑定关系以 `event.unified_msg_origin` 为会话 ID 存储

### 4. 解绑与查询绑定

解绑：

```text
/解绑
```

查询当前用户绑定：

```text
/查询绑定
```

### 5. 过题记录播报开关

开启当前用户的 AC 播报：

```text
/显示记录
```

关闭当前用户的 AC 播报：

```text
/隐藏记录
```

开启后，自动化任务会周期性查询该用户的最新提交。如果检测到新的 Accepted 提交，会向绑定所在会话发送播报，并记录本次提交指纹，避免重复播报。

### 6. 管理员指令

开启插件：

```text
/enable_cf
```

关闭插件：

```text
/disable_cf
```

查询当前管理员自己的最新提交指纹：

```text
/测试指纹
```

别名：

```text
/fingerprint
/test_fingerprint
```

管理员指令仅允许配置项 `Admin ID` 中的用户调用。

## 自动化任务

### 比赛定时推送

配置 `contest_push_time` 和 `contest_push_sessions` 后，插件会在每日指定时间向目标 AstrBot 会话推送近期比赛信息。

运行口径：

- 插件加载时输出下一次比赛推送时间
- 每次推送完成后输出下一次比赛推送时间
- 若未配置推送时间或目标会话，则跳过比赛自动推送
- 推送图片渲染失败时，回退为纯文本比赛信息

### 提交记录轮询

插件会按照 `loop_time` 周期轮询所有已绑定且开启播报的用户。

运行口径：

- 插件加载时输出下一次提交查询时间
- 每轮查询完成后输出下一次提交查询时间
- 同一个 Codeforces handle 被多个会话绑定时，API 只请求一次，再分发到各会话绑定
- 使用提交指纹避免重复播报
- 新绑定用户如果最新提交不是 AC，会写入基线指纹，避免历史记录被误报

### t2i 临时文件清理

AstrBot 文转图服务下载到本地的图片会保存在 `data/temp` 中。插件会定期清理过期图片：

- 插件启动时先清理一次
- 之后每 1 小时清理一次
- 只处理 `data/temp/io_temp_img_*`
- 只删除超过 24 小时的文件
- 不会清理刚生成、可能仍在发送流程中的图片

## 配置说明

配置文件由 AstrBot WebUI / `_conf_schema.json` 管理。

### 管理员设置

| 配置项 | 类型 | 默认值 | 说明 |
| :-- | :-- | :-- | :-- |
| `enable` | `bool` | `true` | 插件总开关，关闭后不响应功能指令 |
| `API key` | `list[string]` | `[]` | 预留的 Codeforces API key 列表，留空表示不配置 |
| `Admin ID` | `list[string]` | `[]` | 管理员 ID 列表，仅列表内用户可调用管理员指令 |

### 比赛推送设置

| 配置项 | 类型 | 默认值 | 说明 |
| :-- | :-- | :-- | :-- |
| `contest_number` | `int` | `5` | 单次查询或推送展示的比赛数量 |
| `contest_push_time` | `string` | `""` | 每日比赛推送时间，格式为 `HH:MM`，留空表示不启用 |
| `contest_push_sessions` | `list[string]` | `[]` | 接收比赛自动推送的 AstrBot 会话 ID 列表 |

### 轮询设置

| 配置项 | 类型 | 默认值 | 说明 |
| :-- | :-- | :-- | :-- |
| `loop_time` | `int` | `600` | 自动查询提交记录的间隔，单位为秒 |

## 图片渲染

用户信息卡片和比赛信息卡片都使用 AstrBot 官方 `html_render()` 接口和 AstrBot 提供的文转图服务渲染。插件仅维护：

- HTML / Jinja2 模板
- 渲染数据
- 截图参数

插件本身不直接启动浏览器进程，也不使用 PIL 绘制卡片。部署到 Linux 服务器时，插件侧无需额外管理 Playwright 浏览器运行时；只需确保 AstrBot 实例可以访问其文转图服务。

若 AstrBot 文转图服务返回 502 / 5xx，插件会记录“返回文件不是图片”的错误，并回退为文本信息发送。

## 数据存储

绑定数据存储在 AstrBot 插件数据目录：

```text
AstrBot/data/plugin_data/astrbot_plugin_for_XCPC/user_bindings.sqlite3
```

数据表：

```sql
CREATE TABLE IF NOT EXISTS cf_bindings (
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    cf_handle TEXT NOT NULL,
    enable_broadcast INTEGER NOT NULL DEFAULT 1 CHECK (enable_broadcast IN (0, 1)),
    last_ac_fingerprint TEXT,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, group_id)
);
```

索引：

```sql
CREATE INDEX IF NOT EXISTS idx_bind_group
ON cf_bindings(group_id);

CREATE INDEX IF NOT EXISTS idx_bind_handle
ON cf_bindings(cf_handle);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bind_group_handle
ON cf_bindings(group_id, cf_handle COLLATE NOCASE);
```

说明：

- `user_id` 为平台用户 ID
- `group_id` 实际存储 AstrBot 会话 ID，即 `event.unified_msg_origin`
- `enable_broadcast` 控制该用户是否参与 AC 播报
- `last_ac_fingerprint` 记录最近一次已播报提交，避免重复推送
- SQLite 启用 WAL 模式，运行时维护内存索引提升查询效率

## 安装方式

将插件目录放入：

```text
AstrBot/data/plugins/
```

目录名建议保持为：

```text
astrbot_plugin_for_XCPC
```

然后在 AstrBot 中加载或重载插件。

本插件主要依赖 AstrBot 运行环境以及 Python 标准库，Codeforces API 请求由项目内模块完成。图片渲染依赖 AstrBot 的文转图服务。

## 项目结构

```text
astrbot_plugin_for_XCPC/
├── automation/
│   ├── __init__.py
│   ├── auto_push.py
│   └── README.md
├── contests/
│   ├── contest_card.py
│   ├── contest_info.py
│   ├── models.py
│   └── README.md
├── storage/
│   ├── models.py
│   ├── user_db.py
│   └── README.md
├── user_handle/
│   ├── models.py
│   ├── user_card.py
│   ├── user_info.py
│   └── README.md
├── user_status/
│   ├── models.py
│   ├── user_status.py
│   └── README.md
├── _conf_schema.json
├── main.py
├── metadata.yaml
└── README.md
```

## 技术实现

- AstrBot 插件 API
- Codeforces API
- SQLite 持久化存储
- WAL 模式与内存索引
- `asyncio` 后台任务
- AstrBot `html_render()` 文转图
- Jinja2 HTML 模板
- 提交指纹去重

## 注意事项

- Codeforces API 有访问频率限制，提交轮询中会对 handle 查询做节流处理。
- `contest_push_sessions` 必须填写 AstrBot 完整会话 ID，而不是纯数字群号。
- 如果用户切换绑定的 Codeforces handle，最近 AC 指纹会重置。
- t2i 图片清理只处理 `io_temp_img_*`，不会清理其它 AstrBot 临时文件。

## License

本项目基于 GNU Affero General Public License v3.0 发布。

你可以在遵守 AGPL-3.0 协议的前提下使用、修改和分发本项目。

## 贡献

- 提交 Issue 报告问题
- 提交 Pull Request 改进功能
- 提出更适合 XCPC / Codeforces 群聊场景的建议
