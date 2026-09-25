# X100 RAG 问答助手项目交接文档

> 本文供后续开发者、外包人员或 AI 接手项目时阅读。先阅读本文，再阅读 `README.md`、`X100_RAG真正实现改造报告.md` 和 `X100_DeepSeek_API接入改造报告.md`。

## 1. 项目一句话说明

这是一个本地运行的 X100 客服问答 Demo，使用真实中文 Embedding、持久化向量、服务端权限过滤、真实 Top-K、Context 组装和 DeepSeek API 生成答案，并对引用和敏感输出做校验。

当前实现定位是：

> **真实向量 RAG + 服务端权限控制 + DeepSeek API 的本地原型**

它不是生产系统。身份认证、正式工单授权、数据库加密、部署级审计和高可用能力仍需要后续建设。

## 2. 接手前必须知道的安全规则

1. 绝不能把 `.env.local` 提交、复制到聊天、截图或发给其他人。
2. `.env.local` 是项目根目录的本地密钥文件，包含 DeepSeek API Key。
3. 不要在终端输出完整 Key；检查配置时只显示 `已配置/未配置`。
4. 不要把 API Key 放入前端、React 环境变量、SQLite、向量库、README 或测试文件。
5. 不要把 `00_X100_绝密_内部手册.md` 的真实口令、入口或内部参数复制到前端、日志、测试输出或模型提示词之外的地方。
6. 不要把前端角色切换当成生产权限。当前角色切换只是本地 Demo 功能。
7. 任何权限变更都必须在服务端实现，不能只隐藏页面元素。
8. 修改 RAG、权限或 LLM 代码后，必须重新运行核心测试和构建。

## 3. 项目目录

```text
项目根目录/
├─ 00_X100_绝密_内部手册.md       # 绝密原始资料，不可对用户暴露
├─ 01_X100_WiFi故障.md             # 对客知识
├─ 02_X100设备离线.md              # 对客知识
├─ 03_X100升级失败.md              # 对客知识
├─ 04_X100密码忘记.md              # 对客知识
├─ 05_X100售后政策.md              # 对客知识
├─ 99_办公室绿植浇水备忘.md         # 无关文件，必须排除
├─ .env.example                    # 可提交的配置模板，无真实 Key
├─ .env.local                      # 本地真实配置，不提交
├─ .rag-data/                      # 本地模型缓存和 SQLite 向量索引
├─ server/
│  ├─ config.py                    # 路径、模型、Top-K、阈值和文档白名单
│  ├─ secrets.py                   # 读取 .env.local 和环境变量
│  ├─ embedding.py                 # BGE Embedding 与向量生成
│  ├─ ingest.py                    # Markdown 解析、切片、脱敏、入库
│  ├─ rag.py                       # RAG 主流程、权限、检索、Context、引用校验
│  ├─ llm.py                       # DeepSeek HTTP 调用和错误映射
│  ├─ api.py                       # Python HTTP API、会话和服务端权限
│  └─ tests/                       # 核心、API 和 DeepSeek Mock 测试
├─ src/
│  ├─ App.tsx                      # 前端页面和 API 调用
│  ├─ main.tsx                     # React 入口
│  ├─ styles.css                   # 页面样式
│  └─ auth.css                     # 身份选择区域样式
├─ scripts/dev.mjs                 # 同时启动 Python API 和 Vite
├─ README.md                       # 面向使用者的启动说明
└─ package.json                    # pnpm 命令
```

## 4. 本地启动

### 4.1 环境要求

- Node.js
- pnpm
- Python 3.9+
- Python 依赖见 `requirements.txt`
- 首次建立向量索引需要下载 BGE 模型，可能需要网络和较长时间

### 4.2 配置 DeepSeek

将真实配置放在项目根目录的：

```text
.env.local
```

格式：

```dotenv
DEEPSEEK_API_KEY=真实Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

`.env.local` 已加入 `.gitignore`。如使用其他兼容模型，只修改配置，不要在代码中硬编码多个模型名。

### 4.3 安装、建库和启动

```powershell
python -m pip install -r requirements.txt
pnpm install
pnpm ingest
pnpm dev
```

浏览器打开 Vite 输出的本地地址。`pnpm dev` 会启动：

- Python RAG API：`http://127.0.0.1:8005`
- Vite 前端开发服务：`http://127.0.0.1:5173`
- MCP Server：首次发生工具调用时由 Agent Host 自动启动的本机 stdio 子进程

MCP Server 不需要单独启动，浏览器也不连接 MCP。只有在协议调试时才直接运行 `python -m server.mcp_server`，并通过 stdin/stdout 发送 JSON-RPC。修改 `.env.local` 后需重启 `pnpm dev`；`MCP_ENABLED=0` 可切换到兼容 registry。

### 4.4 验证命令

```powershell
pnpm test:core
pnpm build
python -m compileall -q server
Invoke-RestMethod http://127.0.0.1:8005/api/health
```

预期健康状态包括：

```json
{
  "ok": true,
  "indexReady": true,
  "llmMode": "deepseek",
  "deepseekConfigured": true
}
```

## 5. 端到端数据流

```text
前端 /api/ask
  ↓
server.api：读取服务端会话角色
  ↓
server.rag.answer_question
  ↓
问题改写
  ↓
敏感问题前置拦截
  ↓
Query Embedding
  ↓
按角色选择 public_chunks 或 internal_chunks
  ↓
SQLite 精确余弦相似度检索
  ↓
Candidate K → 分数重排 → 相似度阈值 → 最终 Top-K
  ↓
Context 组装和 token 限制
  ↓
server.llm：DeepSeek 或明确标记的 Mock
  ↓
结构化 JSON、chunk ID、quote、敏感信息校验
  ↓
返回答案、来源、阶段状态和人工转接信息
```

## 6. 关键实现说明

### 6.1 文档入库

`server/ingest.py` 只读取 `server/config.py` 中明确列出的 00–05 六个文档，不扫描目录下所有 Markdown。

入库流程：

1. 读取 Markdown。
2. 解析标题、段落和表格。
3. 按章节切片，保留文档 ID、章节、版本和密级。
4. 对绝密资料删除敏感凭据行。
5. 调用 `server.embedding.embed_texts` 生成向量。
6. 普通内容写入 `public_chunks`，绝密内容写入 `internal_chunks`。
7. 删除白名单之外的旧索引记录。

如果修改原始文档或切片规则，重新执行：

```powershell
pnpm ingest
```

### 6.2 向量检索

当前配置位于 `server/config.py`：

- Embedding：`BAAI/bge-small-zh-v1.5`
- 向量维度：512
- Candidate K：20
- Final K：4
- 相似度和混合分数阈值由配置控制
- 当前使用 SQLite 中的精确余弦扫描，适合小型 Demo

扩大数据量时，可以将 SQLite 精确扫描替换为 pgvector、FAISS、Chroma 或其他向量数据库，但必须保留服务端权限过滤和第二次授权复核。

### 6.3 权限

`server.rag.allowed_tables` 负责在读取和评分向量前选择索引：

- `user`：只读公开索引
- `agent`：只读公开索引
- `internal` 未授权：只读公开索引
- `internal` 已授权：公开索引 + 内部隔离索引

当前内部授权是本地 Demo 的模拟工单状态，保存在 API 进程内存中。生产环境必须替换为可信身份服务和正式工单授权。

### 6.4 DeepSeek

`server/secrets.py`：读取 `.env.local`，并允许进程环境变量覆盖文件配置。

`server/llm.py`：

- 调用 DeepSeek Chat Completions。
- 只发送问题、有限历史和授权 Context。
- API Key 只放在 Authorization 请求头。
- 禁止重定向，避免凭据转发。
- HTTP 错误、超时和非法 JSON 映射为安全错误。
- 模型返回后由 `server.rag.validate_generation` 继续校验。

未配置 Key 时，系统使用明确标记的 `mock-extractive-v1`，只做授权片段摘录，不能称为真实模型生成。

### 6.5 引用校验

模型返回的每个 `chunkId` 必须存在于本次授权 Context，`quote` 必须逐字出现在对应 chunk 中。任何引用伪造、缺失、越权或结构错误都会停止自动回复并转人工。

## 7. 前端说明

前端 `src/App.tsx` 不直接调用 DeepSeek，只调用本地后端 API。

页面包括：

- 身份选择
- 问题输入和示例问题
- RAG 阶段状态
- 回答和建议步骤
- 引用来源及相似度
- 人工转接
- 客服和内部角色可见的脱敏调试信息
- DeepSeek / Mock 模式状态

不得在前端增加：

- API Key 输入框
- 直接调用 DeepSeek 的代码
- 未授权候选文档展示
- 被过滤绝密文档的标题或数量

## 8. 如何扩展功能

### 8.1 增加公开知识文档

1. 添加 Markdown 文件。
2. 在 `server/config.py` 的 `DOCUMENTS` 中加入明确配置。
3. 设置 `classification="public"` 和允许角色。
4. 运行 `pnpm ingest`。
5. 用相关、无关和敏感问题测试检索边界。
6. 更新 README 或知识库清单。

### 8.2 增加内部文档

1. 先确认密级、责任人和授权角色。
2. 只允许真正需要的内部角色访问。
3. 确认入库脱敏规则不会留下口令、令牌或内部入口。
4. 保持内部 collection 与公开 collection 隔离。
5. 增加未授权、授权和提示词注入测试。
6. 不要用前端隐藏代替权限控制。

### 8.3 增加真实登录

需要替换：

- `server.api` 的内存会话表
- 开发环境的角色切换接口
- 模拟工单授权接口

接入可信身份提供方后，服务端从验证后的会话或令牌读取角色，浏览器提交的 `role` 字段不能作为授权依据。需要补充会话过期、CSRF、Cookie 安全属性和租户隔离。

### 8.4 增加工单系统

人工转接目前只是页面上的模拟按钮。正式接入时：

1. 服务端创建工单，不由前端直接写入外部系统。
2. 只传递必要的问题、设备信息、检索结果摘要和授权范围。
3. 不把绝密原文或 API Key 写入工单。
4. 保存外部工单 ID 和状态，不保存不必要的敏感正文。
5. 增加失败重试和幂等键。

### 8.5 增加流式输出

只有在以下条件满足后再做：

- 已有输出敏感扫描策略。
- 能在流式过程中阻断敏感片段。
- 引用校验可以在最终答案完成后执行。
- 上游断开、超时和半截 JSON 能安全转人工。

当前非流式 JSON 是更容易校验的默认实现。

### 8.6 增加会话记忆

只能保存必要的近期对话。扩展时需要：

- 限制历史条数和字符数。
- 丢弃客户端伪造的 `system` 消息。
- 防止历史内容覆盖当前权限。
- 不把历史中的绝密内容发送给无权角色。
- 对个人信息设置保留和删除策略。

## 9. 不要做的改动

- 不要把 `retrieveCandidates` 改回关键词匹配来代替向量检索。
- 不要删除 `filterByPermission` 或服务端 ACL。
- 不要先检索所有索引，再在前端隐藏结果。
- 不要把所有原文放入 Context 让模型自行保密。
- 不要在低相似度时强行调用 DeepSeek。
- 不要接受模型返回的未经校验的 citation。
- 不要为了“回答更完整”降低权限阈值或泄露内部内容。
- 不要把真实 Key 写入测试、提交记录或截图。
- 不要把本地开发的角色切换直接带到生产环境。

## 10. 故障排查

### 页面提示向量索引未建立

```powershell
pnpm ingest
```

确认 `.rag-data/x100-rag.sqlite3` 存在且 `/api/health` 的 `indexReady` 为 `true`。

### 页面显示 Mock 模式

检查：

1. `.env.local` 是否在项目根目录。
2. 变量名是否为 `DEEPSEEK_API_KEY`。
3. Key 是否为空。
4. 修改配置后是否重启了 `pnpm dev`。
5. `/api/health` 是否显示 `deepseekConfigured: true`。

### DeepSeek 返回错误

不要查看或打印 Key。先检查：

- Base URL 和模型名是否正确。
- API 额度和限流状态。
- 服务端是否能访问 API 地址。
- 请求是否因为无 Context 或低相似度而被有意跳过。

### 自动转人工

可能原因：

- 相似度低于阈值。
- Context 为空。
- API 超时或错误。
- 模型返回非 JSON。
- 引用 chunk ID 不存在。
- quote 不在授权片段中。
- 输出触发敏感信息扫描。
- 问题属于账号、退款、换新、验证码或安全事件。

## 11. 交接验收清单

接手者完成修改后必须提供：

- 修改文件清单和设计说明。
- `pnpm ingest` 结果（如涉及文档或切片）。
- `pnpm test:core` 结果。
- `pnpm build` 结果。
- Python 编译检查结果。
- `/api/health` 结果，不能包含 Key。
- 普通问题、低相似度问题、绝密问题各一项验证结果。
- 权限边界和数据流说明。
- 新增配置项写入 `.env.example`，但不得写真实值。
- 说明是否发送了真实 DeepSeek 请求及可能的费用影响。

## 12. 当前状态快照

截至最近一次检查：

- 公开向量切片：24 个。
- Embedding：`BAAI/bge-small-zh-v1.5`，512 维。
- DeepSeek 模式：已配置，可由服务端调用。
- 模型配置：`deepseek-v4-pro`。
- 核心自动化测试：26 项通过（含 MCP 边界测试）。
- TypeScript/Vite 构建：通过。
- Python 编译检查：通过。
- 当前为本地 Demo，不是生产部署。

接手者如果发现本文与代码行为不一致，应以代码和自动化测试为准，并及时更新本文和 README。

## 13. MCP 模式整改状态

订单、物流、设备和售后工具现由 `server/mcp_server.py` 通过本机 stdio JSON-RPC 暴露，`server/mcp_client.py` 是 Agent Host 唯一调用入口。Server 只导出六个显式工具，并在每次调用重新执行角色、内部授权、资源归属、参数和风险校验；Principal 来自服务端会话。浏览器不连接 MCP，子进程标准输出只承载协议消息。

`MCP_ENABLED=1`（默认）启用 MCP；设为 `0` 可回退旧 registry 兼容模式。创建售后工单继续通过 `/api/agent/confirm` 完成一次性确认和幂等执行。专项测试位于 `server/tests/test_mcp.py`，当前全套测试 26 项通过；交付验证命令为 `pnpm build`、`python -m compileall -q server` 和 `python -m unittest discover -s server/tests`。
