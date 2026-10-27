# 架构说明

```text
任意聊天平台（适配器）
      │  IncomingMessage
      ▼
   main.py
   ├─ 去重 + 有界队列 + 单消费者
   ├─ 主人 / 访客闸（security.py）
   ├─ 挡位命令（router.py）
   ├─ 通过适配器收发文件
   └─ 生成回复
          ├─ memory.py     （四层文件夹 + JSON 缓存）
          ├─ router.py     （ping → 本地 7B / 云端）
          └─ anti_repeat.py（防复读 + polish）
```

## 记忆生命周期

```text
新记忆 ──► Mem_Daily/*.txt
              │ mtime 超过 7 天
              ▼
          Mem_Fuzzy/*.txt   （移动时刷新 mtime）
              │ mtime 超过 30 天
              ▼
          Mem_Archive/*.txt （不参与检索）
```

- 一条记忆一个 TXT，绝不追加。
- `tag_index.json` 只存标签 → 相对路径，是缓存；启动或损坏时按 TXT 头部重建。
- TXT 头部带标签，所以索引可以只靠文件恢复。
- 模糊记忆召回时自动加“不确定语气”前缀。
- 核心记忆不会被衰减任务移动。

## 路由

```text
ping /api/tags（约 0.5 秒）
  ├─ 通 → 本地 7B
  │     ├─ 成功 → 回复
  │     └─ 报错/空回复 → 云端（如果允许）
  └─ 不通 → 云端（如果允许）
```

- 云端只打一次，不重试。
- 主人 / 访客额度分开，存在 `data/quota.json`。
- 云端连续失败 3 次，当天自闭。
- `local` 挡绝不花钱；`cloud` 先云端、失败回本地；`auto` 先本地。

## 身份与输出

- `OWNER_OPEN_ID` 严格匹配；留空时所有人都是访客。
- 访客不读不写记忆。
- 访客回复会遮盘符路径、UNC、IP、API Key、平台 ID、Bearer。
- 主人回复保留路径（本地文件操作需要），但会去掉 emoji 垃圾。
