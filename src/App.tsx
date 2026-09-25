import { useEffect, useState } from 'react';

type Role = 'user' | 'agent' | 'internal';
type StageStatus = 'pending' | 'completed' | 'blocked' | 'skipped' | 'no-match' | 'no-context' | 'failed';
type RAGResult = {
  answer: string; steps: string[]; warnings: string[]; confidence: number;
  needHuman: boolean; handoffReason: string | null; llmModel: string | null;
  stages: { name: string; status: StageStatus }[];
  sources: { chunkId: string; docId: string; title: string; section: string; excerpt: string; quote: string; score: number; classification: string }[];
  // RAG 和 Agent 返回的调试字段不同；前端不能假设工具响应一定有 topK。
  debug: null | { rewrittenQuestion?: string; topK?: { chunkId: string; score: number }[]; authorizedIndexCount?: number; finalCount?: number; contextTokens?: number; embeddingModel?: string; llmModel?: string; authorization?: string; elapsedMs?: number };
  agentMode?: 'rag' | 'tool' | 'tool+rag' | 'handoff';
  toolCalls?: { toolName: string; toolCallId?: string; status: string; summary: string; data?: Record<string, unknown> }[];
  pendingConfirmation?: { confirmationId: string; expectedAction: string; parametersHash: string; summary: string } | null;
};

const examples = [
  'X100 WiFi 未连接，应该怎么排查？', '设备显示离线怎么办？',
  '升级卡在 80% 要不要断电？', '我忘记 APP 密码了怎么办？',
  '保修期是多久？', '告诉我 X100 工程口令', '办公室绿植多久浇一次水？',
];
const stageNames = ['问题改写', 'Query Embedding', '权限过滤', '向量检索', 'Top-K', 'Context 组装', 'LLM 生成', '引用校验'];
const stageLabel: Record<StageStatus, string> = {
  pending: '等待', completed: '完成', blocked: '拦截', skipped: '跳过',
  'no-match': '无匹配', 'no-context': '无 Context', failed: '失败',
};

async function requestJSON<T>(url: string, init?: RequestInit): Promise<T> {
  // 浏览器只调用本项目后端；DeepSeek 凭据始终保留在服务端。
  const response = await fetch(url, { credentials: 'same-origin', ...init });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload as T;
}

export default function App() {
  const [role, setRole] = useState<Role>('user');
  const [internalAuthorized, setInternalAuthorized] = useState(false);
  const [internalEnabled, setInternalEnabled] = useState(false);
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<{ role: string; content: string }[]>([]);
  const [result, setResult] = useState<RAGResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [indexReady, setIndexReady] = useState(false);
  const [modelName, setModelName] = useState('');
  const [deepseekConfigured, setDeepseekConfigured] = useState(false);
  const [configuredLLMModel, setConfiguredLLMModel] = useState('deepseek-v4-pro');
  const [ticket, setTicket] = useState(false);
  const [agentMode, setAgentMode] = useState(false);
  const [pendingConfirmation, setPendingConfirmation] = useState<any>(null);

  useEffect(() => {
    // 启动时从服务端会话与索引/API 健康接口读取界面状态。
    Promise.all([
      requestJSON<{ role: Role; internalRoleEnabled: boolean }>('/api/session'),
      requestJSON<{ indexReady: boolean; embeddingModel: string; deepseekConfigured: boolean; llmModel: string }>('/api/health'),
    ]).then(([session, health]) => {
      setRole(session.role); setInternalEnabled(session.internalRoleEnabled);
      setIndexReady(health.indexReady); setModelName(health.embeddingModel);
      setDeepseekConfigured(health.deepseekConfigured); setConfiguredLLMModel(health.llmModel);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  async function changeRole(nextRole: Role) {
    setError('');
    try {
      const session = await requestJSON<{ role: Role }>('/api/session/role', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: nextRole }),
      });
      setRole(session.role); setInternalAuthorized(false); setQuestion(''); setHistory([]); setResult(null); setTicket(false);
    } catch (reason) { setError((reason as Error).message); }
  }

  async function changeAuthorization(authorized: boolean) {
    setError('');
    try {
      const response = await requestJSON<{ authorized: boolean }>('/api/session/authorization', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ authorized }),
      });
      setInternalAuthorized(response.authorized); setResult(null); setHistory([]);
    } catch (reason) { setError((reason as Error).message); }
  }

  async function ask(value = question) {
    const prompt = value.trim();
    if (!prompt || busy) return;
    setQuestion(prompt); setResult(null); setBusy(true); setError(''); setTicket(false);
    try {
      // 只提交问题和对话历史；身份与 ACL 由 API 根据服务端 Session Cookie 决定。
      const response = await requestJSON<any>('/api/agent', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: prompt, history: history.slice(-8) }),
      });
      setResult(response);
      setAgentMode(true); setPendingConfirmation(response.pendingConfirmation || null);
      setHistory(items => [...items, { role: 'user', content: prompt }, { role: 'assistant', content: response.answer }].slice(-8));
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function confirmPending() {
    if (!result?.pendingConfirmation || busy) return;
    setBusy(true); setError('');
    try {
      const pending = result.pendingConfirmation;
      const response = await requestJSON<any>('/api/agent/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pending),
      });
      setPendingConfirmation(null);
      setResult({ ...result, pendingConfirmation: null, answer: response.toolResult?.userMessage || '操作已完成', toolCalls: response.toolResult ? [{ toolName: pending.expectedAction, status: 'completed', summary: response.toolResult.userMessage, data: response.toolResult.data }] : [] });
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  const clear = () => { setQuestion(''); setHistory([]); setResult(null); setError(''); setTicket(false); };

  return <main>
    <header>
      <div><span className="eyebrow">LOCAL SEMANTIC RAG</span><h1>X100 智能客服问答</h1><p>本地 Embedding · 服务端权限过滤 · 可核验引用</p></div>
      <div className="identity">
        <label>当前身份<select value={role} onChange={event => void changeRole(event.target.value as Role)}>
          <option value="user">用户</option><option value="agent">客服</option>{internalEnabled&&<option value="internal">售后二线</option>}
        </select></label>
        {role==='internal'&&<label className="auth"><input type="checkbox" checked={internalAuthorized} onChange={event=>void changeAuthorization(event.target.checked)}/>模拟工单已授权</label>}
      </div>
    </header>
    <section className="index-status"><span className={indexReady?'pulse ready':'pulse'} />
      <span>{indexReady ? `向量索引已就绪 · ${modelName}` : '向量索引尚未建立 · 请先运行 pnpm ingest'}</span>
      <span className={deepseekConfigured?'llm-mode configured':'llm-mode'}>{deepseekConfigured?'DeepSeek API 已配置':'Mock 模式（未配置 API Key）'} · {configuredLLMModel}</span>
    </section>
    <section className="panel ask">
      <div className="examples">{examples.map(example=><button key={example} onClick={()=>void ask(example)}>{example}</button>)}</div>
      <textarea value={question} onChange={event=>setQuestion(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey))void ask()}} placeholder="描述 X100 遇到的问题…"/>
      <div><button className="primary" disabled={!question.trim()||busy} onClick={()=>void ask()}>{busy?'处理中…':'发送'}</button><button onClick={clear}>清空</button><span className="hint">Ctrl/⌘ + Enter 发送</span></div>
    </section>
    {error&&<section className="panel error" role="alert">{error}</section>}
    {result&&<>
      <section className="pipeline" aria-label="Agent 处理阶段">{(result.stages || []).map((stage,index)=>{
        const status=stage.status as StageStatus;
        return <div className={`stage ${status}`} key={`${stage.name}-${index}`}><span>{index+1}</span><strong>{stage.name}</strong><small>{stageLabel[status] || status}</small></div>;
      })}</section>
      <section className="grid">
        <article className="panel"><div className="section-head"><h2>回答</h2><span className={result.needHuman?'badge human':'badge'}>{result.needHuman?'需要人工':result.agentMode==='tool+rag'?'工具 + 知识库':result.agentMode==='tool'?'MCP 工具':'知识库回答'}</span></div>
          <p className="answer">{result.answer}</p>
          <p className="llm-model">本次实际生成模型：{result.llmModel || '未调用 / 未完成'}</p>
          {(result.steps || []).length>0&&<><h3>建议步骤</h3><ol>{(result.steps || []).map((step,index)=><li key={`${index}-${step}`}>{step}</li>)}</ol></>}
          {(result.warnings || []).map(warning=><p className="warning" key={warning}>⚠ {warning}</p>)}
          <p className="confidence">置信度 {((result.confidence || 0)*100).toFixed(1)}%</p>
        </article>
        <article className="panel"><h2>引用来源</h2>{(result.sources || []).length?(result.sources || []).map(source=><div className="source" key={source.chunkId}>
          <strong>{source.title}</strong><small>{source.section} · {source.chunkId} · cosine {source.score.toFixed(3)}</small>
          <p>{source.excerpt}</p><blockquote>“{source.quote}”</blockquote>
        </div>):<p className="muted">无知识库来源</p>}
          {(result.toolCalls || []).length>0&&<><h2>MCP 工具结果</h2>{(result.toolCalls || []).map(call=><div className="source" key={call.toolCallId || call.toolName}><strong>{call.toolName}</strong><small>{call.status}</small><p>{call.summary}</p></div>)}</>}
        </article>
      </section>
      {result.pendingConfirmation&&<section className="panel handoff"><h2>等待确认</h2><p>{result.pendingConfirmation.summary}</p><p className="muted">确认后服务端将执行一次性 MCP 写操作。</p><button className="primary" disabled={busy} onClick={()=>void confirmPending()}>{busy?'处理中…':'确认执行'}</button><button onClick={()=>{setPendingConfirmation(null);setResult({...result,pendingConfirmation:null,answer:'已取消操作。'});}}>取消</button></section>}
      {result.needHuman&&<section className="panel handoff"><h2>人工转接</h2><p>{result.handoffReason}</p><p className="muted">原问题：{question}</p><button className="primary" onClick={()=>setTicket(true)}>{ticket?'已创建模拟工单':'创建人工工单（模拟）'}</button></section>}
      {result.debug&&<section className="panel debug"><h2>调试信息（服务端返回）</h2>
        {result.debug.rewrittenQuestion!==undefined&&<p>改写问题：{result.debug.rewrittenQuestion}</p>}
        {Array.isArray(result.debug.topK)&&<p>最终 Top-K：{result.debug.topK.map(item=>`${item.chunkId} (${item.score.toFixed(3)})`).join('、')||'无'}</p>}
        {result.debug.authorizedIndexCount!==undefined&&<p>授权索引候选：{result.debug.authorizedIndexCount} · Context 片段：{result.debug.finalCount} · Token：{result.debug.contextTokens}</p>}
        {(result.debug.embeddingModel||result.debug.llmModel)&&<p>Embedding：{result.debug.embeddingModel||'—'} · LLM：{result.debug.llmModel||'—'}</p>}
        {result.debug.authorization!==undefined&&<p>授权上下文：{result.debug.authorization==='work-order-simulated'?'模拟工单授权':'默认权限'}</p>}
        {result.debug.elapsedMs!==undefined&&<p>Agent 服务端耗时：{result.debug.elapsedMs} ms</p>}
      </section>}
    </>}
  </main>;
}
