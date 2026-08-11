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

## 存储自动配对（输入决定后端）

`dta ingest` 的输入来源会自动决定存储后端，三个库（清洗库 / 归类库 / 二创库）保持一致：

| 输入来源 | 存储后端 | 三库落点 |
|---|---|---|
| `--format jsonl / csv` | `file` | `data/cleaned/` `data/events/` `data/articles/` |
| `--format mongo` | `mongo` | 集合 `articles` `events` `event_articles` |
| `--format mysql` | `mysql` | 表 `articles` `events` `event_articles` |

- ingest 时会把推导出的后端写入 `data/.storage.json`，后续 `wash / classify / generate / run` 自动读取，三个库天然一致；
- 优先级：环境变量 `DTA_STORAGE` > `data/.storage.json`（自动标记） > config 的 `storage.backend` > 默认 `mongo`；
- 手动切换：设 `DTA_STORAGE=file|mongo` 即可覆盖；或重新 `dta ingest` 换输入来源。

## MySQL 存储

存储后端也可选 MySQL（输入 mysql 时三库一致，落 MySQL 表）：

```bash
# 1) 装依赖
pip install "data-to-article[mysql]"

# 2) 建表（可选：MySqlBackend 首次连接也会自动建库建表）
mysql -u root -p < schema.sql

# 3) 配置（config/config.yaml）
#   storage:
#     backend: mysql
#     mysql: { host: localhost, port: 3306, user: root, password: "", database: data_to_article, table_prefix: dta_ }
#   或环境变量 MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB

# 4) 使用
dta ingest --format mysql --source articles
dta run
```

表清单（前缀默认 `dta_`，见 `schema.sql`）：

| 库 | 表 |
|---|---|
| 原始数据 | `dta_raw` |
| 清洗库 | `dta_cleaned` |
| 归类库 | `dta_events` + `dta_dedup`（查重指纹） |
| 二创库 | `dta_articles` |
| 运行记录 | `dta_runs` |

> 注意：MySQL 文档以 JSON 列存储（要求 MySQL 5.7+）；切换存储后端不会自动迁移数据。

## 使用方式（总控面板 dta serve）

浏览器控制台，六页完整功能：**概览 / 流水线 / 事件库 / 审核发布 / 搜索阅读 / 系统**。

### 1) 启动面板

```bash
./scripts/start_panel.sh          # Linux / macOS
.\scripts\start_panel.ps1        # Windows
# 或
dta serve --host 127.0.0.1 --port 8765
# 打开 http://127.0.0.1:8765
```

### 2) 首次初始化（系统页）

| 步骤 | 操作 |
|---|---|
| ① 存储 | 选 file / mongo / mysql → 填连接参数 → 测试连接 |
| ② 集合名自定义（连旧库时） | 映射 清洗/归类/二创 集合名（支持多个，逗号分隔；如 `etl_results_sina,etl_results_yi_cai`、`ai_events`、`event_articles`） |
| ③ LLM | provider / base_url / model / API Key |
| ④ 调度 | 每日 10:00 清洗+归类、14:00 二创（可选） |
| 保存 | 写 `config/config.yaml` + `config/.env`（密钥已 gitignore） |

### 3) 面板功能

| 页 | 功能 |
|---|---|
| 概览 | 三库统计、最近事件、最近运行 |
| 流水线 | 选阶段 → 运行/试运行 → 实时日志(SSE) → 运行历史 |
| 事件库 | 搜索、列表（已生成/未生成）、详情（参考原文 + 二创文章）、单事件生成、版本回滚 |
| 审核发布 | ① 待审核（通过/驳回）② 待发布（发布/预览）③ 发布记录 ④ 发布设置（自定义 URL/Headers/Defaults） |
| 搜索阅读 | 左右布局阅读器：**事件阅读器**（参考原文）/ **审核阅读器**（二创），参考原文按 content_fp 跨多个清洗集合解析 |
| 系统 | 存储 / LLM / 调度 / 集合名 初始化 |

### 4) 命令行用法（不用面板时）

```bash
dta ingest --format mongo --source results_sina   # 导入（输入决定三库存储）
dta run --only wash,classify,generate             # 一键全链
dta wash --hours 24                               # 单阶段
dta generate --event evt_xxx                      # 单事件生成
dta serve                                         # 起面板
```

### 5) 程序内调用

```python
from data_to_article.cli import main
main(["run", "--only", "wash,classify,generate", "--dry-run"])
```

### 6) 定时调度

```bash
# Linux cron（每天 10:00 清洗+归类，14:00 二创）
0 10 * * * cd /path/data-to-article && dta run --only wash,classify
0 14 * * * cd /path/data-to-article && dta run --only generate
# Windows 计划任务同理，命令换成 dta run ...
```

### 7) 数据位置

| 后端 | 清洗库 | 归类库 | 二创库 | 运行记录 |
|---|---|---|---|---|
| file | `data/cleaned/` | `data/events/` | `data/articles/` | `data/runs/` |
| mongo | 集合（可自定义） | 集合（可自定义） | 集合（可自定义） | `pipeline_runs` |
| mysql | `dta_cleaned` | `dta_events` | `dta_articles` | `dta_runs` |

### 8) 注意事项

- 面板默认只监听 `127.0.0.1`；服务器部署对外需自行加反向代理与鉴权；
- 发布后端默认 `none`（仅标记已发布）；接真实接口在「审核发布-发布设置」填 URL/Headers/Defaults（JSON，参照本地 publish.yaml）；
- 本地配置/密钥（`config/config.yaml`、`config/.env`、`data/`）均在 .gitignore，不会提交；
- 清洗/归类的多集合名（逗号分隔）用于统计与参考原文解析；流水线写入按单集合处理，建议新流水线用独立库。


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
