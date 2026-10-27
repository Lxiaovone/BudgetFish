# 开源前隐私检查清单

发布前逐项确认：

- [ ] 代码、文档、测试、日志里没有绝对路径（`C:\...`、`D:\...`、`/home/...`）。
- [ ] 没有真实飞书 App ID、App Secret、`open_id`、`chat_id`。
- [ ] 没有真实云端 API Key、Bearer Token、密码、寄存柜钥匙。
- [ ] 没有人名、学校、设备型号、课表、聊天原文进入 Prompt。
- [ ] `prompts/persona.txt` 只放本地，已进 `.gitignore`；仓库只提交 `persona.example.txt`。
- [ ] `memory_core.md` 只放本地；仓库只提交 `memory_core.example.md`。
- [ ] 运行数据（`data/`、`Mem_*`、`tag_index.json`、`quota.json`、`state.json`、
      `downloads/`、`*.log`）没有提交。
- [ ] 本地专属插件（桌宠、课表、寄存柜、远程隧道、本机文件操作）已删除，
      或移到 `examples/` 并默认禁用。
- [ ] Git 历史里没有旧 `.env` 或真实标识；不确定就新建空仓库或 squash。
- [ ] 测试只用临时目录和假事件。
