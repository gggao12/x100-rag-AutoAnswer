# X100 RAG DeepSeek API 接入自检报告

**日期：** 2026-09-23  
**结论：** DeepSeek 服务端接入、结构化输出校验、引用校验和本地回归测试已完成；本地服务健康，真实 API 配置已加载。一次真实请求成功到达 `deepseek-v4-pro`，模型因当时 Context 没有排查步骤而安全转人工。随后已调整检索门控，让有词项佐证的“快速自检”知识片段可进入 Context，并通过本地检索回归；为避免产生第二次费用，本次没有再次发送真实 API 请求。

**2026-09-24 整改记录：** 修复模型返回内容带 Markdown 代码块、前后说明文字或文本分段时被误判为无效 JSON 的问题。服务端现在先兼容提取 JSON 对象，再执行原有结构、引用和敏感内容校验；本次修复未发送新的真实 API 请求。

**2026-09-24 追加整改：** 实际复现“设备显示离线怎么办？”后确认 DeepSeek 返回 `finish_reason=length`，原因是 `deepseek-v4-pro` 默认开启 thinking，推理内容耗尽了 JSON 输出预算。请求已改为 `thinking: {"type": "disabled"}`，并将截断响应单独映射为明确的截断错误。

**2026-09-24 引用整改：** 关闭 thinking 后，真实返回已是完整 JSON，但模型有一条引用超过 30 字，触发引用校验。服务端现在先确认整条引用逐字存在于授权片段，再将超长引用规范化为前 30 字；伪造 chunkId 或不存在的原文仍会被拦截。

**2026-09-24 最终验证：** 使用同一问题“设备显示离线怎么办？”完成复现和修复验证。最终结果为 `deepseek-v4-pro`、`LLM 生成=completed`、`引用校验=completed`、`needHuman=false`。本轮共使用 8 次真实调试请求，未超过用户限定的 10 次。

## 改造内容

- 新增 `server/secrets.py`：服务端读取项目根目录 `.env.local`，支持环境变量覆盖文件配置；API Key 不进入浏览器、响应和常规日志。
- 新增 `server/llm.py`：通过 DeepSeek 官方 Chat Completions 接口发起非流式 JSON 请求；网络异常、超时、HTTP 错误和非 JSON 输出均转为安全的人工作业提示。
- 更新 `server/rag.py`：保留向量检索、服务端权限过滤、授权 Context 和引用校验；DeepSeek 输出需通过结构、chunk ID、短引文和敏感信息验证。无命中或无 Context 时跳过模型调用。
- 更新 `server/config.py`、`server/api.py`：集中提供模型及状态配置；健康接口仅暴露是否配置、运行模式和模型名。
- 更新 `src/App.tsx`、`src/styles.css`：显示 DeepSeek/Mock 状态及本次实际生成模型，不展示密钥。
- 更新 `vite.config.ts`、`scripts/dev.mjs`：限制前端环境变量前缀，并在 API 健康检查成功后启动开发前端。
- 更新 `README.md`、`.env.example`、`.gitignore`；新增 DeepSeek、API 权限和端到端流程测试。
- 旧的 [X100_RAG真正实现改造自检报告.md](X100_RAG真正实现改造自检报告.md) 已标注为历史快照，避免与本报告状态混淆。

## 配置与密钥

当前本地健康接口返回：`ok=true`、`llmMode=deepseek`、`llmModel=deepseek-v4-pro`、`deepseekConfigured=true`。`.env.local` 已存在且读取成功；报告、测试输出和前端均未读取或记录其密钥值。

`.env.example` 内容：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

接口为 `https://api.deepseek.com/chat/completions`，使用 Bearer 鉴权、`temperature: 0`、`stream: false` 和 JSON response format。模型名及请求格式以 [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/) 为依据。

## 检索边界回归

为解决“耳机一只有声音一只没有声音怎么办？”及单独“怎么办”错误进入知识库的问题，检索采用两级门控：原始余弦相似度下限 `0.40`，同时要求余弦与词项佐证混合得分不低于 `0.60`。这不是把“怎么办”作为关键词匹配；停用词处理会剔除泛化问法字词。检索验证结果：

| 查询 | 结果 | 模型调用 |
|---|---|---|
| 耳机一只有声音一只没有声音怎么办？ | 无授权知识片段 | 跳过 |
| 怎么办 | 无授权知识片段 | 跳过 |
| X100 WiFi 未连接，应该怎么排查？ | 命中 WiFi 现象及快速自检片段 | 有授权 Context 时才调用 |
| 办公室绿植多久浇一次水？ | 无匹配 | 跳过 |

检索仅基于已配置的知识文档；`99_办公室绿植浇水备忘.md` 不进入索引。自动化测试覆盖低相似/无 Context 不调用 LLM，真实耳机问题的本地向量检索结果为空。

## 真实 API 与降级证据

- 在浏览器中实际发出过一次普通 X100 WiFi 查询，服务端返回的模型标识为 `deepseek-v4-pro`，DeepSeek 生成和引用验证阶段均完成。
- 当次授权 Context 只有“常见现象”而没有具体操作步骤，模型按规则要求转人工，没有编造排查方法；因此这是成功的 API 往返，不是一个自动解答成功案例。
- 随后完成混合检索门控调整，离线真实向量检索验证可命中“快速自检”片段。没有再进行真实模型请求，避免新增 API 费用。
- 截图未保存：浏览器热更新后截图捕获为空白页。以上真实调用证据来自页面/API 阶段结果及当前健康接口；低相似度和敏感权限边界另由本地自动化测试覆盖。
- API Key 未写入报告、README、测试样例或前端构建产物；`.gitignore` 忽略 `.env.local`，Vite 仅公开 `VITE_` 前缀变量。

## 验证结果

```text
pnpm test:core              通过，20 tests
pnpm build                  通过（tsc -b + vite build）
python -m compileall -q server 通过
GET /api/health             通过：deepseek / deepseek-v4-pro / configured=true
dist 敏感字样扫描           未发现 DEEPSEEK_API_KEY 或 sk- 格式密钥样式
```

测试使用本地 Mock HTTP 服务和虚假测试 Key，覆盖配置优先级、请求模型和 JSON 格式、授权 Context、历史过滤、缺失 Key 不发请求、401/403/429/503、超时、非法 JSON、伪造引用/不合规输出、敏感内容、低相似度不调用、无 Context 不调用及用户不能伪造内部身份。此次没有重跑 `pnpm ingest`：本轮只改模型接入及检索门控，没有改文档解析或切片逻辑。

## 当前边界

- DeepSeek 调用会产生费用并受账号额度、限流和网络状态影响；Mock HTTP 测试不会产生模型费用。
- `.env.local` 仅用于本地开发；生产环境应使用部署平台 Secret，并接入正式身份认证、授权和审计。
- BGE 向量检索和当前 ACL 继续运行在本地；模型只接收服务端筛选后的授权 Context。
