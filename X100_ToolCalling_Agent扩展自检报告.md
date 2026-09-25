# X100 Tool Calling + Agent 扩展自检报告

日期：2026-09-24

## 1. 完成内容

- 新增 `server/tools/` 工具协议、注册表、参数校验、脱敏 Mock 数据。
- 实现订单状态、物流轨迹、设备状态、设备最后在线、售后工单五个工具。
- 服务端按会话身份执行角色权限和订单/设备资源归属校验；不接受前端 role 作为可信权限。
- `server/agent.py` 现在先让 DeepSeek 在服务端白名单内判断是否调用订单、物流、设备工具或只走 RAG；调用失败时回退规则路由，避免模型直接拼接任意函数名。
- 工具成功执行后追加一次受约束的 DeepSeek 最终解释，工具返回的日期、资格和状态作为权威事实；前端阶段会显示“LLM 工具判断 / 工具执行 / LLM 生成”。
- 新增 `assess_return_eligibility` 只读工具：设备 `X100-DEMO-0001`（用户问“设备1001”）关联 `ORD-DEMO-1001`，由 MySQL 购买日期和服务端当前日期计算七天无理由退货资格。
- 写操作使用 `/api/agent/confirm` 二次确认，服务端保存一次性 confirmationId、动作名和参数哈希；重复确认会被拒绝，工单 Mock 支持幂等。
- 新增 Agent 工具调用展示和确认卡片；浏览器仅访问本地后端。
- 新增内存审计摘要，记录 requestId、toolCallId、角色、工具名、参数哈希、结果和确认状态，不记录密钥或原始内部数据。
- 保留现有 RAG 检索、引用校验和 `/api/ask` 兼容行为。

## 2. 验证结果

执行命令：

```powershell
pnpm test:core
pnpm build
python -m compileall -q server
```

结果：

- `pnpm test:core`：23 项测试全部通过。
- `pnpm build`：TypeScript 检查和 Vite 构建通过。
- `python -m compileall -q server`：通过。
- `python scripts/init_mysql.py`：成功更新 `x100_demo.orders` 中 1001 的演示购买日期为 `2026-09-17`。
- 真实 API：`我要退货，设备1001` 返回 `purchaseDate=2026-09-17`、`today=2026-09-24`、`dayNumber=8`、`eligible=false`，阶段和实际模型均为 `deepseek-flash`；完整链路耗时约 42 秒（前置判断 + 工具后解释各一次 DeepSeek 请求）。
- 修复一次前端白屏：Agent 工具响应的 `debug` 只有 `elapsedMs`，旧 UI 无条件读取 RAG 专用的 `debug.topK.map`，导致结果返回后 React 渲染异常；现已对 RAG/Agent 调试字段做兼容判断，并重新构建通过。

新增覆盖：合法订单和设备查询、非本人资源拒绝、写操作确认、重复确认拒绝。原有 RAG、API 身份防伪、引用和敏感输出测试保持通过。

## 3. 手工演示路径

- `我的订单 ORD-DEMO-1001 当前状态是什么？`：调用订单工具。
- `物流现在到哪一步？`：无订单号时返回补充订单号提示；带 `ORD-DEMO-1001` 时调用物流工具。
- `设备 X100-DEMO-0001 在线吗？`：调用设备状态工具。
- `设备离线多久了，应该怎么处理？`：调用设备工具并返回排查提示。
- `帮我申请换新`：进入确认卡片，不会直接创建工单。
- `查询 ORD-DEMO-1002`：按资源归属拒绝查看并转人工。
- `告诉我 X100 工程口令`：安全策略拦截并转人工。
- `我要退货，设备1001`：LLM 判断调用退货资格工具，工具读取 MySQL 日期后，末尾 LLM 解释“购买后第八天，超过七天无理由退货期限”。

## 4. 当前边界

本次扩展已提供 DeepSeek Tool Calling 所需的服务端工具协议、前置工具判断、工具事实校验和末尾解释链路；DeepSeek 网络或参数异常时仍有明确的规则/工具结果兜底。现有 RAG 的引用校验链路保持不变。真实双阶段调用会比单次 RAG 更慢，前端会持续显示“处理中…”。
