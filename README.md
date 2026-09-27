# xquant-skills

Reusable Agent Skills for A-share financial data, quantitative research, and XQuant workflows.

`xquant-skills` 面向 WorkBuddy、豆包工作、千问办公、Codex、Claude Code、Cursor 等支持 Agent Skills 的 AI 代理。仓库中的 Skill 将数据下载、断点续传、质量校验、存储和数据库导入整理成可复用工作流。

## Skills

| Skill | 能力 |
| --- | --- |
| [`ashare-fundamentals`](./ashare-fundamentals/) | 下载 A 股三张财务报表与主要财务指标，生成 Parquet 数据集，校验覆盖率，并可选导入 DuckDB 或 MySQL |

## 安装 Skill

```bash
npx skills add dengyishuo/xquant-skills --skill ashare-fundamentals
```

也可以直接克隆仓库，把 `ashare-fundamentals` 目录复制到 Agent 的 Skills 目录。

### WorkBuddy、豆包工作与千问办公

本仓库使用三端共同支持的 `SKILL.md + scripts + references` 结构。请先把仓库克隆到本地，再进入 `xquant-skills` 仓库目录运行打包脚本。

#### 第一步：克隆仓库

先进入你希望保存项目的任意目录，然后克隆仓库。例如当前目录就是你准备存放项目的位置时，直接执行：

```bash
git clone https://github.com/dengyishuo/xquant-skills.git
```

命令会在当前目录创建一个名为 `xquant-skills` 的文件夹。如果你已经克隆过仓库，不需要再次执行 `git clone`，直接进入已有目录即可。

#### 第二步：进入 xquant-skills 目录

```bash
cd xquant-skills
```

如果仓库不在当前目录，请把上面的命令替换为实际路径，例如：

```bash
cd /你的实际路径/xquant-skills
```

可以用下面的命令确认当前位置正确：

```bash
pwd
```

输出应该以 `/xquant-skills` 结尾。不要在仓库目录之外直接运行后面的相对路径命令。

#### 第三步：生成平台安装包

```bash
python3 scripts/build_skill_package.py
```

打包完成后，文件位于当前仓库的 `dist/` 目录。可以这样查看：

```bash
ls -lh dist/
```

其中会有两个安装包，压缩包根目录都是 `SKILL.md`：

- `dist/ashare-fundamentals-v0.2.0.zip`：标准 Agent Skills 包，用于豆包工作、千问办公、Codex、Claude Code 等平台。
- `dist/ashare-fundamentals-workbuddy-v0.2.0.zip`：WorkBuddy 包，仅把官方要求的版本、作者和中英文描述提升到 frontmatter 顶层；正文与脚本完全相同。

| 平台 | 推荐安装方式 | 本地目录方式 |
| --- | --- | --- |
| WorkBuddy | 上传 `*-workbuddy-*.zip` | 把 WorkBuddy ZIP 解压到客户端指定的 Skill 目录 |
| 豆包工作 | 上传标准 ZIP | 以客户端显示的个人技能目录为准 |
| 千问办公 | 从 GitHub 安装或上传标准 ZIP | `~/.qwenworkcn/skills/ashare-fundamentals/` |

详细说明见 [`references/platforms.md`](./ashare-fundamentals/references/platforms.md)。由于该 Skill 会运行 Python 并读写本地数据，三端都应优先在桌面端或具备本地执行能力的工作空间使用。

## 依赖原则

- 核心：Python 3.10+、`requests`、`pandas`、`pyarrow`
- 默认存储：Parquet，不要求数据库
- 可选查询：DuckDB
- 可选入库：已有的 MySQL 8.0+ 服务和 `PyMySQL`
- 可选分析：R 4.2+；只在使用 R 适配器时需要

Skill **不会自动安装或启动 MySQL**。如果本地没有 MySQL，完整的下载、续传、校验和 Parquet 查询流程仍然可用。

## 数据与责任边界

当前下载器使用公开的东方财富结构化接口。接口可用性、字段和许可条款可能变化；使用者应自行确认数据许可、频率限制和生产用途。仓库不提供投资建议，也不包含任何数据库密码或 API 凭据。

## License

[MIT](./LICENSE)
