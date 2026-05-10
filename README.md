# astrbot_plugin_for_XCPC

一个面向 XCPC / Codeforces 群聊场景的 AstrBot 插件，计划提供 Codeforces 用户信息查询、群内账号绑定、近期比赛推送以及群友过题播报等功能。

## 计划功能

> 标有 ✅ 的功能表示已经完成。

### 1. 查询 Codeforces 用户信息

- 查询指定 Codeforces 用户的基本信息 ✅
  - `rating`
  - `rank`
  - `maxRating`
  - `maxRank`
  - 头像 / 头衔 / 贡献值等扩展信息
- 将查询结果渲染为图片
  - 图片主色调根据用户 `rank` 自动区分
    - `newbie`
    - `pupil`
    - `specialist`
    - `expert`
    - `candidate master`
    - `master`
    - `international master`
    - `grandmaster`
    - `international grandmaster`
    - `legendary grandmaster`
    - `unrated` 使用灰色主题。

### 2. 绑定 Codeforces 用户

支持群成员在不同群聊中绑定自己的 Codeforces 账号，绑定关系以群为单位隔离

#### 设计目标

- 支持同一 QQ 用户在不同群绑定不同的 `cf_handle`
- 支持快速查询绑定信息
- 支持插件加载 / 重载后恢复绑定数据
- 支持用户单独控制是否参与过题播报

#### 存储方案

采用 SQLite 持久化存储，并启用 WAL 预写日志策略以提升并发读写表现

运行时维护一份内存缓存，用于提升查询和轮询效率

- 插件启动或重载时，从数据库加载绑定关系到内存
- 绑定、解绑、修改配置时，同步更新内存状态
- 关键变更立即写入数据库，避免因异常退出造成数据丢失
- 对于非关键统计类数据，可根据需要采用定时批量写回策略

#### 表结构设计

初步设计如下：

|        字段名         |   类型    | 说明                                           |
| :-------------------: | :-------: | :--------------------------------------------- |
|       `user_id`       |  `TEXT`   | 平台用户 ID，修改后立刻写回数据库              |
|      `group_id`       |  `TEXT`   | 群聊 ID，修改后立刻写回数据库                  |
|      `cf_handle`      |  `TEXT`   | 绑定的 Codeforces 用户名，修改后立刻写回数据库 |
|  `enable_broadcast`   | `INTEGER` | 是否允许过题播报，`1` 表示开启，`0` 表示关闭   |
| `last_ac_fingerprint` |  `TEXT`   | 最近一次已播报 AC 记录的指纹，默认为 `NULL`    |
|     `updated_at`      | `INTEGER` | 最近更新时间戳（过题记录），默认为 `0`          |

主键：

```sql
PRIMARY KEY (user_id, group_id)
```

索引：

```mysql
CREATE INDEX IF NOT EXISTS idx_bind_group
ON cf_bindings(group_id);

CREATE INDEX IF NOT EXISTS idx_bind_handle
ON cf_bindings(cf_handle);
```

说明：

- `(user_id, group_id)` 作为主键，可以唯一确定某个用户在某个群中的绑定关系
- 创建 `group_id` 单列索引，按群获取全部绑定用户
- 创建 `cf_handle` 索引，根据 `cf_handle` 反查用户 ID

### 3. 近期比赛推送

支持定时获取 / 手动获取 Codeforces 近期比赛信息，并推送到指定群聊。

#### 功能规划

- 每日定时通过 Codeforces API 获取近期比赛列表
- 通过指令唤醒推送比赛列表功能 ✅
- 支持管理员配置需要推送的会话
- 支持配置推送时间
- 支持配置赛前提醒时间
- 将比赛信息渲染为图片后发送

#### 推送内容

计划包含：

- 比赛名称
- 比赛开始时间
- 距离开始的剩余时间
- 比赛时长
- 比赛链接
- 比赛阶段，例如 `BEFORE`、`RUNNING`、`FINISHED`

### 4. 群友过题播报

支持周期性轮询群内已绑定的 Codeforces 用户，并在检测到新的 Accepted 提交时自动播报

#### 功能规划

- 每隔一段时间获取指定群聊中所有已绑定且开启播报的 `cf_handle`
- 通过 Codeforces API 查询用户近期提交记录
- 检测最近一次新的 AC 提交
- 使用指纹机制避免重复播报
- 播报成功后更新对应用户的最近 AC 指纹
- 轮询间隔作为可配置项，由管理员配置
