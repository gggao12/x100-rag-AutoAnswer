# X100 RAG 问答助手

本项目是本地运行的语义 RAG Demo。Python 服务端从固定白名单解析 Markdown，使用真实中文 Embedding 建立本地向量索引；查询阶段完成服务端角色过滤、余弦相似度 Top-K、余弦候选下限与词项佐证的混合分数判断、Context 组装，再选择 DeepSeek API 或明确标记的抽取式 Mock 模式。

## 环境与启动

需要 Node.js、pnpm、Python 3.9+。首次准备依赖和 DeepSeek 配置：

```powershell
python -m pip install -r requirements.txt
pnpm install
Copy-Item .env.example .env.local
# 编辑 .env.local，填入 DEEPSEEK_API_KEY
pnpm ingest
pnpm dev
```

推荐只使用 `pnpm dev` 启动开发环境。该命令会先启动 Python API，再启动 Vite 前端；浏览器访问 `http://127.0.0.1:5173/`，API 地址为 `http://127.0.0.1:8005/`。首次请求订单、物流、设备或售后工具时，Agent Host 会自动在服务端启动本机 MCP 子进程（`python -m server.mcp_server`），不需要在浏览器或另一个终端手动启动 MCP Server。

如需单独调试 API，可运行 `python -m server.api`；如需仅验证 MCP 协议，可运行 `python -m server.mcp_server`，它通过 stdin/stdout 处理 JSON-RPC。修改 `.env.local` 后请重启 `pnpm dev`。

首次 `pnpm ingest` 会下载固定版本的 `BAAI/bge-small-zh-v1.5` 到 `.rag-data/models`，并将 512 维向量写入 `.rag-data/x100-rag.sqlite3`。首次下载需要网络，模型使用 CPU 推理。

`.env.local` 位于项目根目录，只供本机开发，已加入 `.gitignore`；不得提交或截图展示。进程环境变量 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 优先于文件配置。生产环境应使用部署平台的 Secret，不要把真实 Key 保存在项目文件中。

DeepSeek 接入默认配置为 `https://api.deepseek.com` 和 `deepseek-flash`，由服务端请求 `/chat/completions`。如果未配置 Key，界面和 API 会明确显示 **Mock 模式**，不会伪称已调用 DeepSeek；Mock 仅从授权检索片段摘录并校验引用。真实 API 调用会产生费用并受 DeepSeek 限流影响。问题、必要的最近对话历史和授权 Context 会发送给 DeepSeek；未授权片段与服务端 Key 不进入请求正文，Key 只放在 Authorization 请求头中。

DeepSeek HTTP 错误、超时、非 JSON、伪造引用或敏感输出均转人工；原始第三方错误正文不会返回给浏览器或写入日志。相似度低于阈值或没有授权 Context 时，不调用生成 API。

服务端使用 DeepSeek 非 thinking 模式生成客服 JSON，避免推理内容占满输出预算；同时兼容纯 JSON、Markdown JSON 代码块、JSON 前后的简短说明，以及文本分段格式。引用必须来自授权片段，模型超长引用会被服务端截取为已验证的前 30 字，再通过字段和敏感信息校验。

## 验证命令

```powershell
pnpm build
pnpm test:core
```

## 数据隔离与实现边界

入库只读取 00–05 六个显式配置的 X100 Markdown，不扫描其他文件；`99_办公室绿植浇水备忘.md` 不进入解析或索引。00 文档单独存入内部索引，凭据行在 embedding 前脱敏。API 仅绑定 `127.0.0.1`。开发页面可切换模拟身份和工单授权，不代表生产身份认证。

向量存于 SQLite，使用精确余弦扫描，适合当前小型 Demo，不是 ANN 索引；余弦候选下限为 0.40，最终混合分数下限为 0.60，排序带轻量词项佐证，不是神经 reranker。生产环境需接入可信身份和正式审批系统、加密存储、审计保留策略及监控。

## 实现文件

完整目录说明（含知识库原文、测试、配置和生成文件）见 [X100_RAG项目文件说明.md](X100_RAG项目文件说明.md)。

- `server/secrets.py`：读取根目录 `.env.local`，支持环境变量优先级；不向浏览器暴露密钥。
- `server/llm.py`：DeepSeek Chat Completions、JSON 模式、历史裁剪、请求错误安全映射。
- `server/ingest.py`：白名单 Markdown 解析、脱敏、分块和持久化向量入库。
- `server/embedding.py`：固定 revision 的真实 BGE embedding。
- `server/rag.py`：服务端 ACL、余弦 Top-K、阈值、Context、DeepSeek/Mock、引用校验及审计。
- `server/api.py`：仅 loopback 的 Python API 和服务端会话。
- `server/mcp_server.py`：固定六工具白名单的本机 stdio JSON-RPC MCP Server。
- `server/mcp_client.py`：Agent Host 的 MCP 子进程客户端，带调用超时、协议错误和断开保护。
- `server/mcp_context.py`：服务端建立的 MCP Principal 上下文。
- `src/App.tsx`：真实 API 驱动的界面，显示 DeepSeek/Mock 状态和本次实际模型。


### MySQL 订单库

### MCP 工具模式

订单、物流、设备和售后工具通过服务端本机 stdio MCP Server 暴露。Agent Host 固定启动 `python -m server.mcp_server`，浏览器不会连接 MCP，标准输出只承载 JSON-RPC。工具名称和参数先经过本地白名单及服务端 Schema、角色和资源归属校验；`create_service_ticket` 仍需 `/api/agent/confirm` 一次性确认。

`.env.local` 可用 `MCP_ENABLED=0` 回退到旧 registry，响应会保留工具模式字段，但该配置用于兼容和故障排查。`MCP_TRANSPORT=stdio`、`MCP_SERVER_MODULE=server.mcp_server` 为固定配置，不支持通过请求覆盖。MCP Server 不读取命令行密钥，也不会把 Principal、内部授权或数据库原始记录返回给模型。

Agent 请求会先让 DeepSeek 在服务端白名单内判断是否需要订单/物流/设备工具；工具返回事实后，再由 DeepSeek 做一次受约束的最终解释。订单工具会优先读取本机 MySQL `x100_demo.orders`，连接失败时使用内置脱敏演示数据保证本地 Demo 可用。配置 `.env.local` 中的 `X100_MYSQL_*` 后，可在 MySQL 服务启动后执行：

```powershell
python scripts/init_mysql.py
```

也可以直接执行 `server/mysql_schema.sql`。当前订单演示数据为 `ORD-DEMO-1001`（demo-user，运输中，购买日期 2026-09-17）和 `ORD-DEMO-1002`（other-user，权限拒绝）。设备 `X100-DEMO-0001` /“设备1001”关联订单 1001，可用于验证七天无理由退货日期判断。

DeepSeek 调用只读取项目 `.env.local` 或进程环境中的 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`，不会读取 Claude Code 的 Token。当前模型为 `deepseek-flash`，请求使用 DeepSeek `/chat/completions` 兼容接口。
