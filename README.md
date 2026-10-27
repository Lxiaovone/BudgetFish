# 物理记忆智能体（Physical Memory Agent）

一个 **本地优先、适配器驱动** 的聊天机器人模板：纯文件记忆 + 本地小模型 + 云端兜底。
核心不绑定任何聊天平台；`console` 可直接跑，`feishu` 是示例适配器，你也可以接 Discord、Telegram、QQ 或自己的 WebSocket。

## 亮点

- **物理记忆**：一条记忆一个 TXT，`tag_index.json` 只挂载路径；日常 7 天转模糊、模糊 30 天归档；模糊记忆自动加“不确定语气”前缀。
- **探路省钱**：每条消息先 `ping` 本地 Ollama（约 0.5 秒），通了走本地；不通或本地报错才转云端，不做“并发再取消”的白扣费。
- **双核路由**：`auto / local / cloud` 三挡；主人和访客分开限额；云端只打一次，失败不重试。
- **平台解耦**：`main.py` 不 import 任何聊天 SDK；所有平台差异都在 `adapters/`。
- **可验证的“真本地”**：断网、断云端时，记忆仍从 `tag_index.json` + 本地 TXT 读取；7B 模型仍能做出“模糊回忆”。

## 3 步快速启动

### 1. 跑通核心（不需要聊天平台）

```bash
git clone <your-repo-url>
cd physical-memory-agent
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` 先保持：

```ini
PLATFORM=console
OWNER_OPEN_ID=local-user
MODEL_NAME=your-local-model
```

```bash
ollama pull your-local-model
ollama serve
python main.py
```

终端里输入一句话，应该能在 `data/Mem_Daily/` 看到一个新的 TXT。

### 2. 选择适配器

**控制台（默认）**：零依赖，适合调试。

**飞书示例**：

```bash
pip install -r requirements-feishu.txt
```

`.env`：

```ini
PLATFORM=feishu
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
OWNER_OPEN_ID=ou_...
```

飞书应用需要机器人能力，以及 `im:message`、`im:resource`、`im:resource:upload` 权限。

**自定义平台**：实现 `adapters/base.py` 的 `Adapter`，然后在 `adapters/__init__.py` 注册。核心完全不用改。

### 3. 验证记忆

给机器人发：

```text
local              # 只用本地
auto               # 本地优先，失败才云端
发送文件 文件名     # 从 data/send/ 发文件
```

然后检查：

```text
data/Mem_Daily/*.txt
data/tag_index.json
```

拔掉网线、停掉云端 API，`local` 模式仍应能读到本地记忆并回复。

## 适配器契约

```python
class Adapter:
    def run(self, on_message): ...
    def send_text(self, chat_id, text): ...
    def send_file(self, chat_id, path): ...
    def download_attachment(self, attachment): ...
```

`IncomingMessage` 只需要：

```python
message_id, user_id, chat_id, text,
is_group, mentioned, attachments
```

新增平台只写一个 `adapters/xxx.py`。

## 真实记忆星空图

不是特效，是 `tag_index.json` 直接生成的交互图：

```bash
pip install -r requirements-viz.txt
python memory_map.py --out memory_map.html
```

打开 `memory_map.html`，节点就是你的标签和记忆文件。
**本项目可视化直接读取本地 `tag_index.json`；不读本地索引的演示，大概率只是套了层星空皮肤。**

## 目录

```text
.
├── main.py                  # 平台无关编排：队列、身份、记忆、文件
├── config.py                # .env / 路径 / 参数
├── router.py                # ping + 本地/云端 + 额度 + 挡位
├── memory.py                # 四层物理记忆 + tag_index + 衰减
├── anti_repeat.py           # 防复读 + polish
├── security.py              # 主人闸 + 路径锁 + 出站脱敏
├── persona.py               # 通用人设
├── memory_map.py            # tag_index.json -> 交互式星空图
├── adapters/
│   ├── base.py              # Adapter / IncomingMessage 契约
│   ├── console.py           # 本地终端适配器
│   └── feishu.py            # 飞书示例适配器
├── prompts/persona.example.txt
├── memory_core.example.md
├── requirements.txt         # 核心依赖
├── requirements-feishu.txt  # 飞书适配器依赖
├── requirements-viz.txt     # 可视化依赖
└── tests/
```

## 安全警告

- **不要提交 `.env`**。App Secret / API Key 只要进过 Git 历史，立刻轮换。
- **`OWNER_OPEN_ID` 留空 = 所有人都是访客**；不要把陌生人的 ID 填进主人位。
- **访客云端默认 3 次/天**；`CLOUD_ENABLED=0` 可彻底关云；连续失败 3 次当天自闭。
- **路径锁**：只允许读取 `data/` 下白名单文件；不要让用户输入直接拼 `open()`。
- **出站脱敏**：访客回复遮盘符路径、UNC、IPv4/IPv6、`sk-`、平台 ID、Bearer、密码键值对。
- **文件上限 30MB**；只解析白名单文本后缀，PDF/图片/音视频不自动解析。
- **防开盒**：README、日志、报错、示例数据里都不放真实目录、主机名、聊天记录。
- **防提示注入**：记忆/文件内容标注为“资料，不是指令”。
- **最小权限**：聊天平台只开需要的权限，不给机器人管理员权限。

## 防套壳声明

本项目以**物理文件流**为第一性原理：

- 记忆是 `Mem_*/**.txt`，不是向量库截图；
- 索引是 `tag_index.json`，不是云端 API 返回值；
- 可视化是 `memory_map.py` 读本地索引生成，不是前端写死动画；
- 断网 + 断云端后，`local` 模式仍能基于本地文件回忆。

如果有人演示时不展示 `tag_index.json`、不跑断网测试，只放星空图，建议先怀疑是皮肤。

## 许可证

MIT。
