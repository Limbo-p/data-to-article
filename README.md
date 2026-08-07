# data-to-article

通用「数据到文章」流水线：**清洗 → 归类 → 二创**。不含爬虫模块——原始数据通过 `dta ingest` 从 JSONL / CSV / MongoDB 集合等来源接入。

三大接口均可自定义：

| 接口 | 说明 | 默认实现 |
|---|---|---|
| `StorageBackend` | 存储层（原始/清洗/事件/二创/运行记录/查重） | `MongoBackend`（默认）+ `JsonFileBackend`（零依赖兜底） |
| `IngestSource` | 原始数据接入 | JSONL / CSV / Mongo 集合，可自定义 |
| `BaseLLMClient` | LLM 调用（归类 + 二创） | `openai_compat` / `anthropic` / `gemini` / `mock`，可自定义 |

## 快速开始（无需 MongoDB、无需 API Key）

```bash
# 零依赖模式：file 存储 + mock LLM
python -m data_to_article.cli ingest --file examples/sample_articles.jsonl
python -m data_to_article.cli run --dry-run
# 或安装为命令后
dta ingest --file examples/sample_articles.jsonl
dta run --hours 24
```

## 命令

| 命令 | 说明 |
|---|---|
| `dta ingest --file x.jsonl` | 导入原始数据（jsonl/csv/mongo） |
| `dta wash --hours 24` | 清洗：清理/去重/系列过滤 -> 清洗产物 |
| `dta classify --hours 168` | 归类：LLM 路由 -> 新建/并入事件 |
| `dta generate --hours 168` | 二创：事件 -> 多视角文章 |
| `dta run --only wash,classify,generate` | 一键全链路 |

## 自定义接口

- **自定义存储**：`config` 里 `storage.backend: my_backend` + `storage.module: mypkg.MyBackend`（继承 `StorageBackend`）。
- **自定义 LLM**：`config` 里 `llm.provider: my_provider` + `llm.my_provider.module: mypkg.MyClient`（继承 `BaseLLMClient`）。
- **自定义导入**：实现 `IngestSource` 并在 `data_to_article.ingest.registry.get_ingest` 注册。
- **Prompt 模板**：`config/prompts/*.txt` 可直接编辑（不写代码调整二创/归类风格）。

## 安全声明

- 本仓库**不含任何真实 API Key / 签名 / 内部接口地址**；所有密钥只通过 `.env` / 环境变量提供（见 `.env.example`）。
- 二创为 AI 生成内容，真实性由使用者负责。

## 路线图

- [x] P0：骨架 + 三个接口 + file 存储 + mock LLM + CLI
- [x] P1：平移 清洗 / 归类 / 二创 并接入接口（wash/classify/generate 可跑）
- [ ] P2：LLM 插件化完善 + 运行记录增强 + 可选调度
- [ ] P3：测试补齐 + CI + 文档 + 示例 + 可选 docker-compose
