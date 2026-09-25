# X100 MCP 模式整改与施工计划

## 0. 给施工 AI 的总指令

请在现有项目基础上，将订单、物流、设备和售后工具从当前 Python 内部注册表模式改造成标准 MCP 模式，同时保留已经完成的真实向量 RAG、DeepSeek API、权限过滤、确认机制和引用校验。

施工必须遵守：

1. 先阅读本文、X100_RAG项目交接文档.md、README.md、server/agent.py、server/rag.py、server/llm.py 和 server/tools/。
2. 不要重写已经可用的 RAG，只改造 Agent 与工具调用层。
3. MCP Client 和 MCP Server 只能运行在服务端，浏览器不得直接连接 MCP。
4. 不得把 API Key、数据库连接、内部错误、绝密资料或未授权工具暴露给模型和前端。
5. 施工完成后必须执行测试、构建和 MCP 专项验收，未通过不能声称完成。
6. 如果所选 MCP SDK 接口与本文示例不同，以 SDK 官方接口为准，但必须保留本文的安全边界和功能行为。

## 1. 当前项目基线

当前已有：

- Python API：server/api.py
- RAG 主流程：server/rag.py
- DeepSeek 客户端：server/llm.py
- 密钥读取：server/secrets.py
- 文档解析和向量入库：server/ingest.py
- 工具协议和注册表：server/tools/base.py、server/tools/registry.py
- 订单、物流、设备工具：server/tools/order_tools.py、logistics_tools.py、device_tools.py
- Agent 路由：server/agent.py
- React 前端：src/App.tsx
- 测试：server/tests/

当前工具链仍然是：

    DeepSeek 自定义 JSON 路由
      → server/agent.py
      → registry[tool_name].execute(...)
      → Python handler

尚未完成：

- 标准 MCP Server
- MCP Client
- MCP Transport
- MCP list_tools / call_tool
- 真正的多轮工具调用循环
- MCP 工具级身份上下文传递

## 2. 目标架构

整改后：

    React 前端
       ↓ HTTP
    server/api.py
       ↓
    Agent Host（server/agent.py）
       ├─ RAG：server/rag.py
       ├─ DeepSeek：server/llm.py
       └─ MCP Client：server/mcp_client.py
              ↓ stdio（首版）
          MCP Server：server/mcp_server.py
              ↓
          订单 / 物流 / 设备 / 售后工具

### 2.1 首版 Transport

首版只使用本机 stdio Transport：

- Agent Host 启动或连接本地 MCP Server 子进程。
- MCP Server 不监听公网端口。
- 标准输出只输出 MCP 协议消息，日志写标准错误。
- 不允许通过命令行参数传递 API Key。
- 启动失败、协议错误、超时和断开连接都转人工。
- 首版不要同时实现远程 HTTP MCP。

## 3. MCP Server 改造

### 3.1 新增文件

建议新增：

    server/mcp_server.py
    server/mcp_context.py

如果 SDK 不提供所需类型，再新增：

    server/mcp_protocol.py

MCP Server 负责：

- 创建 MCP Server。
- 从显式白名单导出工具。
- 提供工具描述和 JSON Schema。
- 接收 Agent Host 的可信调用上下文。
- 对工具名、参数、角色、资源归属和风险等级做二次校验。
- 把现有 ToolResult 转换为 MCP 标准结果。

### 3.2 只允许暴露的工具

首版只暴露：

    get_order_status
    get_logistics_tracking
    get_device_status
    get_device_last_seen
    assess_return_eligibility
    create_service_ticket

禁止自动扫描 Python 函数、模块或类来生成工具。

### 3.3 MCP 工具定义

每个工具必须有：

- name
- description
- inputSchema
- 服务端风险等级
- 服务端允许角色
- 是否需要确认

示例：

    {
      "name": "get_device_status",
      "description": "查询当前用户有权查看的 X100 设备状态",
      "inputSchema": {
        "type": "object",
        "properties": {
          "deviceSn": {"type": "string"}
        },
        "required": ["deviceSn"],
        "additionalProperties": false
      }
    }

risk_level 和 allowed_roles 是服务端内部策略，不要作为模型可信输入。

### 3.4 MCP 身份上下文

新增服务端上下文对象：

    MCPPrincipal(
        user_id,
        role,
        internal_authorized,
        session_id,
        request_id,
        tool_call_id
    )

它由 Agent Host 创建并传给 MCP Server，不能由模型或前端传入的参数覆盖。

MCP Server 每次调用都要重新检查：

- 当前用户和角色
- 内部授权状态
- 订单或设备归属
- 工具是否允许当前角色
- 参数格式和额外字段
- 是否存在有效确认

### 3.5 MCP 结果

工具结果必须是结构化、最小化和脱敏的：

    {
      "ok": true,
      "toolName": "get_order_status",
      "toolCallId": "...",
      "data": {
        "status": "运输中",
        "item": "X100 主机",
        "eta": "2026-09-26"
      },
      "userMessage": "订单当前状态：运输中",
      "errorCode": null,
      "needHuman": false
    }

不得返回：

- 完整地址、电话、银行卡、密码、验证码
- 内部备注、数据库原始行
- 绝密资料、工程口令、内部入口
- Python 堆栈和第三方错误正文

## 4. MCP Client 改造

新增：

    server/mcp_client.py

提供最小接口：

    list_tools(principal)
    call_tool(name, arguments, principal, request_id)
    close()

要求：

- 只连接固定配置中的本地 MCP Server 命令。
- 子进程命令不能来自用户输入或模型输出。
- MCP 工具名先过本地白名单，再发送调用。
- 参数先做 JSON Schema 校验，再发送调用。
- 每次调用带 request ID 和 tool call ID。
- 单个用户请求最多 3 次工具调用。
- 单个 Agent 请求最多 4 个循环步骤。
- 相同工具和相同参数不得重复执行。
- 超时、退出、协议错误和断开连接转人工。

启动命令必须是固定配置，例如：

    python -m server.mcp_server

不要通过字符串拼接执行任意命令。

### 4.1 工具能力发现

流程：

    MCP Server 返回注册工具
      ↓
    Agent Host 根据 Principal 过滤
      ↓
    只把当前角色可用工具发送给 DeepSeek

用户身份不得看到或得到内部工具定义。

## 5. Agent 重构

### 5.1 目标

将 server/agent.py 从单次自定义路由改为 MCP Client 驱动的 Agent Loop。

目标流程：

    1. 读取可信 Principal
    2. 判断敏感问题和是否直接人工
    3. 获取当前角色可用 MCP tools
    4. 让 DeepSeek 判断走 RAG、工具或混合流程
    5. 工具调用先做名称、参数、权限和资源校验
    6. 写工具进入确认状态
    7. 读工具通过 MCP Client 执行
    8. 脱敏结果回传模型
    9. 继续循环或调用 RAG
   10. 做最终引用、事实和敏感输出校验
   11. 返回答案或人工转接

### 5.2 DeepSeek 工具调用

优先使用 DeepSeek/OpenAI-compatible API 的标准 tools 和 tool_calls 字段。

不要继续依赖自由文本函数名。若当前模型或接口不支持标准工具调用：

- 不得执行自由文本里的函数名。
- 可以保留受限 JSON 路由作为兼容模式。
- UI 和 README 必须标明这是 Legacy 路由，不是标准 MCP Tool Calling。
- MCP Server 的权限边界不能因此降低。

### 5.3 Agent 状态机

至少实现：

    ROUTING
    RAG_SEARCH
    TOOL_PENDING_CONFIRMATION
    TOOL_EXECUTING
    TOOL_RESULT_RECEIVED
    LLM_CONTINUE
    FINAL_VALIDATION
    DONE
    HANDOFF

每次状态变化写入响应 stages，前端显示阶段。

### 5.4 停止条件

以下任意情况都必须停止：

- 获得有来源的最终答案。
- 工具结果足够并完成解释。
- 需要用户确认。
- 工具无权、失败或超时。
- 达到最大循环次数。
- 检测到敏感请求或提示词注入。
- RAG 低于阈值且无工具可用。

## 6. 工具和权限

保留现有工具处理函数，但所有调用必须经过 MCP Server。

角色权限：

    用户       公开 RAG、本人订单/物流/设备、确认后创建工单
    客服       按客服授权范围查询、确认后创建工单
    售后二线   按工单授权查询，内部资料需明确授权

权限顺序：

    可信身份
      → 工具白名单
      → 角色权限
      → 资源归属
      → 参数格式
      → 风险和确认
      → 工具执行

用户、模型和前端传来的 role、user_id、authorized 都不能作为可信授权依据。

## 7. 写操作和确认

以下操作必须用户确认：

- create_service_ticket
- 退款
- 换新
- 取消订单
- 修改地址
- 设备重置
- 远程诊断
- 固件操作

流程：

    模型提出写工具调用
      ↓
    服务端校验
      ↓
    生成一次性 confirmationId 和 parametersHash
      ↓
    前端显示脱敏动作摘要
      ↓
    用户确认
      ↓
    POST /api/agent/confirm
      ↓
    服务端重新校验会话、动作名、参数哈希和有效期
      ↓
    MCP Client 调用工具
      ↓
    返回工具结果

确认要求：

- 一次性使用。
- 过期时间建议 10 分钟。
- 角色变化、会话变化或参数哈希变化时拒绝。
- 工具使用幂等键。
- 记录确认前和确认后的审计事件。

## 8. RAG 与 MCP 混合

必须支持：

1. 纯 RAG：WiFi、离线排查、升级、密码、售后政策。
2. 纯工具：订单状态、物流、实时设备状态。
3. 工具 + RAG：先查设备状态，再用 02_X100设备离线.md 解释。
4. 工具 + 人工：先查询退货条件，再确认创建售后工单。

工具结果和知识库 Context 分开：

    [TOOL_RESULT]
    toolCallId=...
    toolName=get_device_status
    内容=...
    [/TOOL_RESULT]

    [RAG_CONTEXT]
    chunkId=...
    来源=02_X100设备离线.md
    内容=...
    [/RAG_CONTEXT]

实时数据引用 toolCallId，知识结论引用 chunkId，不能混淆。

## 9. API 和前端

保留：

    POST /api/ask

继续使用或更新：

    POST /api/agent
    POST /api/agent/confirm

Agent 响应至少包含：

    {
      "agentMode": "rag | tool | tool+rag | handoff",
      "stages": [],
      "toolCalls": [],
      "pendingConfirmation": null,
      "answer": "...",
      "sources": [],
      "citations": [],
      "needHuman": false,
      "handoffReason": null
    }

前端新增：

- Agent 阶段流程
- 工具名称和脱敏参数
- 工具执行状态
- 工具结果摘要
- 等待确认卡片
- 确认和取消按钮
- MCP 连接失败提示
- RAG 来源和工具来源分区显示

前端不执行工具、不判断权限、不连接 MCP、不显示 Key 或内部错误。

## 10. 配置和依赖

固定一个稳定的 Python MCP SDK 版本并写入 requirements.txt。

建议配置：

    MCP_ENABLED=1
    MCP_TRANSPORT=stdio
    MCP_SERVER_COMMAND=python
    MCP_SERVER_MODULE=server.mcp_server
    MCP_STARTUP_TIMEOUT_SECONDS=10
    MCP_TOOL_TIMEOUT_SECONDS=20
    MAX_AGENT_STEPS=4
    MAX_TOOL_CALLS=3

MCP_SERVER_MODULE 只允许固定值 server.mcp_server。不要执行用户提供的命令。

当 MCP_ENABLED=0 时允许 Legacy registry 回退，但 UI 必须显示 Legacy 模式，不能称为 MCP。

## 11. 测试计划

### 11.1 MCP 协议

- MCP Server 能启动并完成初始化。
- list_tools 只返回显式注册工具。
- 工具 Schema 可解析。
- 未知工具被拒绝。
- 非法参数和额外字段被拒绝。
- 工具结果结构稳定。
- Client 能处理关闭、超时和协议错误。

### 11.2 权限

- 用户只能看到公开工具。
- 角色变化会改变工具列表。
- 伪造 role=internal 无效。
- 非本人订单和设备被拒绝。
- Principal 不能由模型修改。
- 未授权角色不能读内部资料或工具结果。

### 11.3 Agent

- WiFi 问题只走 RAG。
- 订单问题走订单工具。
- 物流问题走物流工具。
- 设备状态走设备工具。
- 设备状态加处理建议走 MCP + RAG。
- 工具失败不编造结果。
- 达到最大步数转人工。
- 未知工具或自由文本函数名不执行。
- 相同调用不会无限重复。

### 11.4 写操作

- 创建工单先进入待确认。
- 未确认不能创建。
- 正确确认只创建一次。
- 重复确认失败。
- 参数哈希变化失败。
- 确认过期失败。
- 角色变化后确认失败。

### 11.5 安全

- API Key 不出现在前端、响应、日志、数据库和构建产物。
- 工具结果不含凭据、绝密原文或不必要个人信息。
- 工具结果中的提示词注入不会改变 Agent 行为。
- 异常不返回堆栈。
- 低相似度 RAG 不调用模型。
- 前端参数不能越权。

## 12. 分阶段施工

### 阶段 1：MCP Server

任务：

- 选择并固定 MCP SDK。
- 新增 mcp_server.py。
- 从现有 registry 显式导出 6 个工具。
- 实现 list_tools 和 call_tool。
- 增加身份上下文和结果脱敏。
- 增加 MCP Server 测试。

完成标准：

- stdio 能启动。
- 6 个工具可以被发现。
- 工具结果与旧 registry 结果一致。
- 未知工具和非法参数被拒绝。

### 阶段 2：MCP Client

任务：

- 新增 mcp_client.py。
- Agent Host 启动 MCP Server 子进程。
- 实现请求 ID、工具调用 ID、超时和关闭。
- 实现 MCP_ENABLED 开关和 Legacy 回退。
- 测试 MCP 断开和超时。

完成标准：

- Agent 能通过 MCP 查询订单、物流和设备。
- MCP 失败安全转人工。
- 权限测试通过。

### 阶段 3：Agent Loop

任务：

- 将 server/agent.py 改为状态机。
- 支持多工具调用。
- 将 MCP 工具结果回传 DeepSeek。
- 支持 RAG + MCP 混合。
- 执行最大步数、调用数和重复调用保护。

完成标准：

- 设备状态和处理建议可以完成 MCP + RAG。
- 工具失败、循环异常和低置信度转人工。

### 阶段 4：确认和前端

任务：

- 接入 MCP 写工具确认。
- 增加工具卡片和确认卡片。
- 分开显示工具来源和 RAG 来源。
- 显示 MCP 模式和连接失败。

完成标准：

- 写操作确认前不执行。
- 重复确认不重复创建。
- 用户能看懂将执行的动作。

### 阶段 5：验收和交付

执行：

    pnpm test:core
    pnpm build
    python -m compileall -q server

提交：

- 修改文件清单
- SDK 和版本说明
- MCP 启动命令
- MCP 与 Legacy 切换说明
- 普通、混合、越权和写操作测试证据
- README 更新
- X100_RAG项目交接文档.md 更新
- X100_MCP整改自检报告.md

## 13. 最终验收标准

只有全部满足才算完成：

- 工具通过 MCP Server 标准暴露。
- Agent Host 通过 MCP Client 调用。
- 工具不是模型自由拼接函数名执行。
- 工具名和参数经过白名单及 Schema 校验。
- Principal 由服务端建立，模型和前端不能伪造。
- 订单、物流和设备有资源归属校验。
- 读操作可自动执行，写操作必须确认。
- Agent 有循环、调用数和重复调用保护。
- RAG 仍是真实向量检索和授权 Context。
- RAG 引用与工具结果引用分离。
- MCP 不泄露 Key、绝密内容、数据库原文或堆栈。
- MCP、模型和工具故障都能安全转人工。
- 前端能显示 Agent 阶段、工具状态、确认状态和来源。
- 核心测试、MCP 测试、安全测试和构建全部通过。
