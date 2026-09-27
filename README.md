# xquant-skills

Reusable Agent Skills for A-share financial data, quantitative research, and XQuant workflows.

`xquant-skills` 面向 Codex、Claude Code、Cursor 等支持 Agent Skills 的 AI 编程代理。仓库中的 Skill 将数据下载、断点续传、质量校验、存储和数据库导入整理成可复用工作流。

## Skills

| Skill | 能力 |
| --- | --- |
| [`ashare-fundamentals`](./ashare-fundamentals/) | 下载 A 股三张财务报表与主要财务指标，生成 Parquet 数据集，校验覆盖率，并可选导入 DuckDB 或 MySQL |

## 安装 Skill

```bash
npx skills add dengyishuo/xquant-skills --skill ashare-fundamentals
```

也可以直接克隆仓库，把 `ashare-fundamentals` 目录复制到 Agent 的 Skills 目录。

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

