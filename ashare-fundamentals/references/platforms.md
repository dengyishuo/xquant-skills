# Platform compatibility

The same Skill directory supports WorkBuddy, Doubao Work, and QwenWork. Keep one source of truth; do not maintain platform-specific copies of the downloader scripts.

## Build the universal upload package

From the repository root:

```bash
python3 scripts/build_skill_package.py
```

The command creates a standard Agent Skills ZIP and a WorkBuddy ZIP. Both place `SKILL.md` at the archive root and include the same `scripts/`, `references/`, `agents/`, and dependency files. The only difference is WorkBuddy's required top-level metadata. Do not unzip and repackage them before uploading.

## WorkBuddy

Use **Experts · Skills · Connectors → Skills → Add Skill → Upload Skill** and select `ashare-fundamentals-workbuddy-v0.2.2.zip`. For project-local development, extract that WorkBuddy package—not the standard source folder—into `.workbuddy/skills/ashare-fundamentals/` or the user Skill directory shown by the client.

WorkBuddy requires `description`, `description_zh`, `description_en`, `version`, and `author` metadata. These fields are maintained in the shared `SKILL.md`. The Skill needs Bash/local-command permission to run Python. Review outbound network and workspace write permissions before the first download.

Official format documentation: <https://open.workbuddy.cn/docs/skill>

## Doubao Work

Open **技能·连接器 → 新建/上传技能** and upload the standard package `ashare-fundamentals-v0.2.2.zip`. Prefer local-computer mode because the downloader runs Python, accesses public HTTPS endpoints, and writes Parquet files. A cloud computer must separately provide Python, dependencies, network access, and persistent storage.

If the client already discovers local Agent Skills, point it at the `ashare-fundamentals` folder. Do not guess or hard-code a private installation path: use the directory shown by the installed client, because local and cloud Skill stores are separate.

## QwenWork / 千问办公

Either upload the standard package in **扩展 → 技能 → 安装技能**, or send the repository URL in a conversation and ask QwenWork to install `ashare-fundamentals`. For direct filesystem installation:

```bash
mkdir -p ~/.qwenworkcn/skills
cp -R ashare-fundamentals ~/.qwenworkcn/skills/ashare-fundamentals
```

QwenWork documents `~/.qwenworkcn/skills/` as its desktop Skill directory. Use the desktop client when local Python execution is required.

Official documentation: <https://docs.qwenwork.cn/features/skills>

## First-run verification prompt

After installation, use a read-only prompt first:

```text
使用 ashare-fundamentals 检查运行环境和依赖，只报告缺项，不安装软件、不下载数据、不修改数据库。
```

Then run a two-symbol test in a dedicated output directory before a full-market download.
