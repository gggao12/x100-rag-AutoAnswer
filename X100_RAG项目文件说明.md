# X100 RAG 项目文件说明

本文按“业务知识、服务端、前端、测试、配置与报告”解释项目中每个需要维护或理解的文件。`node_modules`、构建目录、模型缓存和数据库属于生成/运行数据，不是源码；文末单独说明。

## 运行链路

```text
浏览器：index.html → src/main.tsx → src/App.tsx → /api（Vite 开发代理）
服务端：server/api.py → server/agent.py →（RAG：server/rag.py）或（工具：server/tools/registry.py → MySQL/Mock）
RAG：server/embedding.py + SQLite → Top-K/Context → server/llm.py（DeepSeek OpenAI 兼容）
入库：server/config.py 的 DOCUMENTS 白名单 → server/ingest.py → BGE 向量 → .rag-data/x100-rag.sqlite3
订单：.env.local → server/mysql_store.py → MySQL x100_demo.orders；连接失败才使用脱敏演示数据
配置：.env.local / 环境变量 → server/secrets.py → 仅 DeepSeek 服务端请求
验证：server/tests/ → pnpm test:core；前端类型检查与打包 → pnpm build
```

DeepSeek 请求边界：服务端先完成角色权限过滤、向量检索和 Context 限额，只把当前问题、必要的最近对话历史和最终授权 Context 发给 DeepSeek。整个知识库、无关文档、未入选候选、内部权限判断和 API Key 不进入请求正文。

## 根目录配置与启动文件

| 文件 | 用途 |
|---|---|
| `README.md` | 项目简介、安装和启动命令、密钥安全要求、RAG 边界及主要实现文件索引。 |
| `package.json` | Node 项目元信息、React/Vite/TypeScript 依赖，以及 `dev`、`ingest`、`api`、`build`、`test:core` 命令。改脚本或直接依赖时修改此文件。 |
| `pnpm-lock.yaml` | pnpm 锁定的完整依赖版本树；通常由 pnpm 更新，不手工改依赖版本。 |
| `pnpm-workspace.yaml` | pnpm workspace 配置，当前主要用于允许 esbuild 安装脚本。 |
| `requirements.txt` | Python 侧 NumPy、PyTorch、Transformers 依赖范围。 |
| `index.html` | Vite 页面外壳，提供 React 挂载点 `#root` 并加载 `/src/main.tsx`。 |
| `vite.config.ts` | Vite 插件、前端可见环境变量前缀 `VITE_` 和 `/api` 到 loopback Python API 的开发代理。 |
| `tsconfig.json` | TypeScript 项目引用入口，指向实际应用配置。 |
| `tsconfig.app.json` | `src/` 前端应用的 TypeScript 严格检查选项。 |
| `tsconfig.app.tsbuildinfo` | TypeScript 增量构建状态文件，自动生成；不编辑、不作为业务源码。 |
| `.gitignore` | 排除依赖、构建产物、向量数据库/模型缓存、Python 缓存和 `.env.local`。 |
| `.env.example` | 可复制的无密钥配置模板；API Key 留空，Base URL 和模型名提供默认值。 |
| `.env.local` | 本机私密配置文件，服务端从这里读取 DeepSeek Key；已被忽略。不要提交、截图、复制到报告或前端。本文不读取、不展示其内容。 |
| `scripts/dev.mjs` | 同时启动 Python API 和 Vite，先轮询 API 健康检查，任一进程退出时清理另一进程。 |
| `scripts/init_mysql.py` | 使用 `.env.local` 的 MySQL 账号创建 `x100_demo.orders` 并写入虚构演示订单。 |

## 启动方式

以下命令均在项目根目录 `D:\知识库\第二天模拟知识库` 的 PowerShell 中执行。首次启动需要先安装依赖、建立向量索引，并确保本机 MySQL 服务已经启动。

### 首次准备

```powershell
python -m pip install -r requirements.txt
pnpm install
Copy-Item .env.example .env.local
# 编辑 .env.local，填写 DEEPSEEK_API_KEY 和 X100_MYSQL_* 配置
pnpm ingest
python scripts/init_mysql.py
```

### 一键启动开发环境

```powershell
pnpm dev
```

`pnpm dev` 会先启动 Python API，等待 `http://127.0.0.1:8005/api/health` 就绪后再启动 Vite 前端。浏览器访问 `http://127.0.0.1:5173/`。按 `Ctrl+C` 会同时停止 API 和前端。

### 分开启动

需要分别调试服务时，打开两个 PowerShell 窗口：

```powershell
# 窗口一：API
pnpm api

# 窗口二：前端
pnpm exec vite --host 127.0.0.1
```

前端开发代理固定将 `/api` 转发到 `127.0.0.1:8005`。启动后可用下面命令确认服务状态：

```powershell
Invoke-WebRequest http://127.0.0.1:5173/api/health | Select-Object -ExpandProperty Content
```

修改知识库 Markdown 后重新执行 `pnpm ingest`；修改 MySQL 演示数据后重新执行 `python scripts/init_mysql.py`。常用验证命令为 `pnpm test:core` 和 `pnpm build`。

## 知识库 Markdown 原文

这些 Markdown 是业务资料，不是程序源码。是否入库由 `server/config.py` 的 `DOCUMENTS` 白名单决定，而不是由目录中的文件名自动决定。

| 文件 | 用途与索引范围 |
|---|---|
| `00_X100_绝密_内部手册.md` | 内部受限资料，进入独立内部表；入库前对凭据行做脱敏，默认用户/客服检索不到。 |
| `01_X100_WiFi故障.md` | X100 WiFi 故障、现象、自检和进阶排查；公开白名单文档。 |
| `02_X100设备离线.md` | X100 设备离线原因、处理步骤和预防建议；公开白名单文档。 |
| `03_X100升级失败.md` | 固件升级失败提示、升级步骤、卡进度处理及注意事项；公开白名单文档。 |
| `04_X100密码忘记.md` | APP、设备管理员和 WiFi 密码相关说明；公开白名单文档，敏感账号问题仍按规则转人工。 |
| `05_X100售后政策.md` | 保修范围、期限和寄修等售后资料；公开白名单文档。 |
| `99_办公室绿植浇水备忘.md` | 故意放入的无关资料；不在白名单中，**不会被解析、嵌入或查询**。 |

修改知识原文后，应按 README 说明重新运行 `pnpm ingest`，让切片、Embedding 和 SQLite 索引同步更新。

## Python 服务端 `server/`

| 文件 | 用途 |
|---|---|
| `server/__init__.py` | 标识 Python 包，供 `python -m server.api`、`python -m server.ingest` 使用。 |
| `server/config.py` | 集中定义项目目录、数据库位置、固定 BGE 模型、检索阈值、Top-K、角色和文档白名单，并加载 DeepSeek 配置。 |
| `server/secrets.py` | 读取 `.env.local` 与进程环境变量；环境变量优先；校验 Base URL/模型，并避免密钥出现在对象 repr 中。 |
| `server/embedding.py` | 固定 revision 加载 BGE 中文向量模型，负责文本向量化、批处理、掩码均值池化、归一化及 token 计数。 |
| `server/ingest.py` | 建表、解析 Markdown 标题/段落/表格、切片、内部资料脱敏、生成 Embedding，并写入独立公开/内部 SQLite 表。只处理白名单。 |
| `server/llm.py` | 只使用项目自己的 `DEEPSEEK_API_KEY` 构造 DeepSeek `/chat/completions` 请求；显式关闭思考，限制输出预算，并校验 JSON、引用和上游错误。 |
| `server/rag.py` | RAG 主流程：问题改写 → 风险拦截 → ACL 过滤 → 向量与词项佐证检索 → Top-K → Context 限额 → Mock/DeepSeek → 字段/敏感信息/引用校验 → 审计与转人工。无命中或无 Context 时不调用 LLM；模型超长引用在确认属于授权原文后规范化为前 30 字。 |
| `server/api.py` | 仅监听 loopback 的 HTTP API；管理会话、健康检查、兼容 `/api/ask`，以及 `/api/agent`、`/api/agent/confirm`。身份和授权只从服务端会话读取。 |

## Agent 与工具服务端 `server/agent.py`、`server/tools/`

| 文件 | 用途 |
|---|---|
| `server/agent.py` | 先由 DeepSeek 在白名单内判断是否查订单/物流/设备或只走 RAG，失败时规则兜底；工具执行后再由 DeepSeek 做事实约束下的最终解释；写操作保存一次性确认单并记录审计摘要。 |
| `server/agent_policy.py` | 集中定义工具风险等级与确认策略常量。 |
| `server/tools/base.py` | 定义 `Principal`、`ToolResult`、统一 `Tool` 协议、参数哈希及订单/SN 格式校验。 |
| `server/tools/registry.py` | 服务端工具白名单和 OpenAI-compatible 工具描述；模型或前端不能注册新工具。 |
| `server/tools/order_tools.py` | 查询订单、按购买日期判断七天无理由退货资格和创建售后工单；订单查询优先 MySQL，连接失败使用脱敏演示数据。 |
| `server/tools/logistics_tools.py` | 按订单归属查询脱敏物流摘要。 |
| `server/tools/device_tools.py` | 按设备归属查询设备状态和最后在线信息。 |
| `server/tools/validators.py` | 导出工具参数和哈希校验函数。 |
| `server/mysql_store.py` | 读取 `.env.local` 的 MySQL 配置，建立 `x100_demo.orders` 连接并将数据库字段转换为工具安全字段。 |
| `server/mysql_schema.sql` | 创建演示数据库、订单表并插入虚构订单。 |

## 前端 `src/`

| 文件 | 用途 |
|---|---|
| `src/main.tsx` | React 应用入口，将 `App` 挂到页面 `#root`，并加载两份样式表。 |
| `src/App.tsx` | 问答界面、示例问题、身份控件、Agent 工具卡片/确认卡片、RAG 阶段状态、答案/来源/转人工和调试信息展示。浏览器不持有任何模型或数据库凭据。 |
| `src/styles.css` | 页面主题、布局、问题输入、流程阶段、答案卡片、引用、索引/模型状态和窄屏响应式样式。 |
| `src/auth.css` | 身份切换和模拟工单授权控件样式；仅负责展示，不执行权限判断。 |

## 自动化测试 `server/tests/`

| 文件 | 用途 |
|---|---|
| `server/tests/test_core.py` | 入库白名单、Markdown/表格解析、内部资料脱敏、向量相似度/混合门控、授权表选择、引用及敏感输出验证。 |
| `server/tests/test_api.py` | 用本地临时 HTTP 服务验证请求体伪造 `role` 或内部授权不会改变服务端身份。 |
| `server/tests/test_deepseek.py` | 用 loopback Mock HTTP 服务和虚假 Key 测试配置优先级、授权 Context、JSON 请求格式、历史过滤、错误/超时/非法 JSON，以及低相似度或空 Context 不调用模型。不会连接或计费真实 DeepSeek。 |

## 需求、实施与自检文档

| 文件 | 用途与状态 |
|---|---|
| `X100_RAG问答助手建设大纲.md` | 原始目标、业务边界、角色权限、RAG 流程、安全及验收要求。 |
| `X100_RAG真正实现改造报告.md` | 从演示 RAG 改为真实本地向量检索/权限隔离的实施要求。 |
| `X100_RAG真正实现改造自检报告.md` | 真实向量 RAG 阶段自检记录；开头已标明是 DeepSeek 接入前的历史快照。 |
| `X100_RAG问答助手_Demo自检报告.md` | 最初 Demo 阶段的验证与限制记录，属于较早阶段材料。 |
| `X100_DeepSeek_API接入改造报告.md` | DeepSeek API 接入要求、密钥边界、请求格式、校验、错误策略与验收清单。 |
| `X100_DeepSeek_API接入自检报告.md` | DeepSeek 接入后的当前自检结果、费用/截图说明、模型状态和回归验证记录。 |
| `X100_RAG项目文件说明.md` | 本文件：逐文件目录和阅读导航。 |

## 自动生成目录与维护提示

| 路径 | 用途 |
|---|---|
| `node_modules/` | pnpm 安装的 Node 依赖；由安装命令管理。 |
| `.pnpm-store/` | pnpm 包缓存。 |
| `dist/` | `pnpm build` 生成的前端静态产物；不要在这里直接改源码。 |
| `.rag-data/models/` | BGE 模型及缓存；首次入库时下载，体积较大。 |
| `.rag-data/x100-rag.sqlite3` | 本地持久化的文档切片、向量、权限元数据及审计记录；不要手工编辑或随意分享。 |
| `server/__pycache__/`、`server/tests/__pycache__/` | Python 运行生成的字节码缓存。 |

JSON（如 `package.json`、`tsconfig*.json`）及生成的锁文件不适合插入普通注释；它们的职责已在此处解释。关键业务流程注释位于 Python/TypeScript 源码中；`src/auth.css` 也注明 UI 控件只是演示展示，真正权限判断在服务端。

## 最近整改记录

| 问题 | 原因 | 当前处理 |
|---|---|---|
| 返回“DeepSeek 返回内容不是有效 JSON” | V4 Pro 默认 thinking 消耗输出预算，或模型响应带代码块/前后说明 | 关闭 thinking；设置 4096 输出预算；兼容多种 JSON 外层格式；`finish_reason=length` 单独识别。 |
| 返回“无法校验回答引用” | 模型把整段 Context 复制到 `quote`，超过 30 字 | 先确认完整引用逐字存在于授权片段，再截取前 30 字返回；伪造 chunkId 和不存在的原文仍拦截。 |
| 无关问题进入回答 | 仅靠向量相似度可能产生误命中 | 同时使用原始余弦下限和词项佐证混合分数；无授权结果时跳过 LLM。 |

这部分整改已用“设备显示离线怎么办？”完成真实 API 验证，最终 `LLM 生成` 和 `引用校验` 均为 `completed`。

> 模型和凭据边界：当前使用 `deepseek-flash`。LLM 只读取项目 `.env.local`/进程环境中的 `DEEPSEEK_*` 配置，不读取 `~/.claude/settings.json`，避免混用 Claude Token。
