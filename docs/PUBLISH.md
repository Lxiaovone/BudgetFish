# 发布到 GitHub

## 仓库名建议

1. `physical-memory-agent`（当前目录名）
2. `memfolder`
3. `tagmem`
4. `offline-memory-agent`
5. `local-memory-agent`

先确定名字，再创建空仓库。发布后不要再改目录名，否则 README 里的 clone 命令会失效。

## 第一次只上传 README 也行

在 GitHub 创建一个**空仓库**（不要勾 README），然后：

```bash
cd physical-memory-agent
git init -b main
git add .
git status                 # 确认 .env、data/、日志没有被加入
git commit -m "Initial public release: physical memory agent"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

如果你在网页上已经勾了 README：进仓库先把自动生成的 README 删掉，再上传本地文件，
避免两个 README 冲突。

## 用 GitHub Desktop（不装命令行 Git）

1. 打开 GitHub Desktop，登录；
2. File → Add local repository；
3. 选 `<你的桌面>/physical-memory-agent`；
4. 提示不是 Git 仓库时，点 **create a repository here**；
5. 提交 Summary：`Initial public release: physical memory agent`；
6. 点 **Publish repository**，取消 Keep this code private；
7. 发布后检查根目录直接是 `main.py`、`README.md`、`adapters/`，不要多一层文件夹。

## 首次发布前扫描

```bash
grep -RInE 'sk-[A-Za-z0-9]{20,}|ou_[A-Za-z0-9]{20,}|cli_[A-Za-z0-9]{10,}' . \
  --exclude-dir=.git --exclude-dir=__pycache__
```

预期：只有 `.env.example` 里的 `sk-xxxxxxxx` 占位符。

确认：

- `.env` 没有被跟踪；
- `data/` 没有被跟踪；
- `prompts/persona.txt`、`memory_core.md` 没有被跟踪；
- `LICENSE` 已改成你的署名；
- README 标题和仓库名一致。

## 打第一个 tag

```bash
git tag -a v0.1.0 -m "first public template"
git push origin v0.1.0
```

然后到 GitHub Releases 从 tag 创建版本，可附 zip。
