from __future__ import annotations
import hashlib, json, re, time, uuid, atexit
from typing import Any
from .tools import Principal, registry
from .tools.base import parameter_hash
from .rag import answer_question
from .llm import LLMServiceError, call_deepseek
from .mcp_client import MCPClient, MCPClientError
# Agent 的硬上限用于防止模型/规则异常导致工具无限循环或重复执行。
MAX_AGENT_STEPS=4
MAX_TOOL_CALLS=3
PENDING: dict[str,dict[str,Any]]={}
AUDIT_LOG: list[dict[str,Any]]=[]
ROUTABLE_TOOLS={"get_order_status","get_logistics_tracking","get_device_status","get_device_last_seen","assess_return_eligibility","create_service_ticket"}
MCP = MCPClient()
atexit.register(MCP.close)

def _mcp_execute(name, args, principal, request_id):
    """所有工具执行都经过 MCP；只有显式 MCP_ENABLED=0 才走兼容回退。"""
    if not MCP.enabled:
        return registry[name].execute(args, principal, request_id)
    try:
        raw = MCP.call_tool(name, args, principal, request_id)
        from .tools import ToolResult
        return ToolResult(bool(raw.get("ok")), raw.get("toolName", name), raw.get("toolCallId", request_id), raw.get("data", {}), raw.get("userMessage", ""), raw.get("errorCode"), bool(raw.get("needHuman")))
    except MCPClientError:
        from .tools import ToolResult
        return ToolResult(False, name, request_id, {}, "MCP 服务不可用，请转人工", "mcp_unavailable", True)

# 审计只保存参数哈希和脱敏状态，不保存订单原始记录或凭据。
def _audit(request_id, principal, tool_name, args, result, confirmation=None):
 AUDIT_LOG.append({"requestId":request_id,"toolCallId":result.requestId,"role":principal.role,"toolName":tool_name,"parametersHash":parameter_hash(args),"ok":result.ok,"errorCode":result.errorCode,"needConfirmation":registry[tool_name].risk_level=="write","confirmation":confirmation})

# 第一层路由使用服务端白名单规则，模型不能凭文本拼出任意函数名。
def classify(question): # 纵深防御，不让llm自由发挥，先规则筛选一边
 q=question.lower()
 if any(x in q for x in ("工程口令","内部手册","私钥","token")): return "handoff"
 if any(x in q for x in ("退货","七天","7天")): return "return"
 if any(x in q for x in ("工单","换新","退款","售后申请")): return "ticket"
 if "物流" in q or "到哪里" in q or "到哪一步" in q: return "logistics"
 if "订单" in q or "ord-demo" in q: return "order"
 if "设备" in q or "离线" in q or "在线" in q or "sn" in q: return "device"
 return "rag"

def _stage(name,status="completed"): return {"name":name,"status":status}

def _llm_route(question, history, hint):
 # 前置 LLM 只在服务端白名单内选择工具，无法确定时返回 rag；规则仍是故障兜底。
 context=("[ROUTER_MODE]\n可选工具：rag、get_order_status、get_logistics_tracking、get_device_status、"
          "get_device_last_seen、assess_return_eligibility、create_service_ticket。\n"
          "rag 表示只查知识库；create_service_ticket 仅在用户明确申请人工售后时选择。\n"
          f"规则初判提示（仅供参考）：{hint}")
 try:
  generated, model=call_deepseek(question,context,history,None)
  tool=generated.get("tool"); args=generated.get("arguments")
  if isinstance(tool,str) and tool in ROUTABLE_TOOLS|{"rag"} and isinstance(args,dict): return tool,args,model
  answer=generated.get("answer")
  if isinstance(answer,str):
   parsed=json.loads(answer)
   if isinstance(parsed,dict) and parsed.get("tool") in ROUTABLE_TOOLS|{"rag"}: return parsed["tool"],parsed.get("arguments",{}),model
 except (LLMServiceError,ValueError,TypeError,json.JSONDecodeError): pass
 return None,{},None

def _extract_args(question, decision, routed_args):
 args={k:v for k,v in routed_args.items() if k in ("orderId","deviceSn") and isinstance(v,str)}
 if isinstance(args.get("orderId"),str): args["orderId"]=args["orderId"].upper().replace("ODR-", "ORD-")
 if decision in ("order","logistics") and "orderId" not in args:
  m=re.search(r"(?:ORD|ODR)-DEMO-\d{4}",question,re.I)
  if m: args["orderId"]=m.group(0).upper().replace("ODR-", "ORD-")
 if decision=="return":
  m=re.search(r"X100-DEMO-\d{4}",question,re.I)
  if m: args["deviceSn"]=m.group(0).upper()
  elif re.search(r"(?:设备|device)\s*1001",question,re.I): args["deviceSn"]="X100-DEMO-0001"
  m=re.search(r"(?:ORD|ODR)-DEMO-\d{4}",question,re.I)
  if m: args["orderId"]=m.group(0).upper().replace("ODR-", "ORD-")
 if decision=="device" and "deviceSn" not in args:
  m=re.search(r"X100-DEMO-\d{4}",question,re.I)
  if m: args["deviceSn"]=m.group(0).upper()
 return args

def _finalize_tool_with_llm(question,history,result,tool_name):
 # 工具数据是事实源，末尾 LLM 只负责解释，不能改写日期、资格或状态。
 context=("[TOOL_RESULT]\n以下是服务端授权工具的权威结果，只能据此解释，不能改写日期、资格或状态。"
          "若 eligible 为 false，要明确说明不能按七天无理由退货。\n"
          f"工具名：{tool_name}\n工具数据：{json.dumps(result.data,ensure_ascii=False)}\n工具摘要：{result.userMessage}")
 try:
  generated,model=call_deepseek(question,context,history,None)
  answer=generated.get("answer")
  if isinstance(answer,str) and answer.strip(): return answer.strip(),model,[]
 except LLMServiceError as exc:
  return result.userMessage,None,[f"DeepSeek 最终解释调用失败（{exc.kind}），已展示工具结果。"]
 return result.userMessage,None,["DeepSeek 未返回可用解释，已展示工具结论。"]
def run_agent(question, history, principal, request_id):
 started=time.time(); stages=[_stage("意图判断")]; calls=[]; hint=classify(question)
 decision=hint
 if decision=="handoff": return {"answer":"该请求需要授权人工处理。","needHuman":True,"handoffReason":"涉及受限信息或高风险操作","stages":stages+[_stage("人工转接","blocked")],"toolCalls":[],"pendingConfirmation":None,"citations":[],"steps":[],"warnings":[],"sources":[],"confidence":0.0,"llmModel":None,"debug":None}
 routed_tool,routed_args,route_model=_llm_route(question,history,hint)
 # 退货资格判断是只读政策分析；即使模型误选写工具，也不能绕过日期核验流程。
 if hint=="return" and routed_tool not in ("assess_return_eligibility", "rag"):
  routed_tool, routed_args = "assess_return_eligibility", {}
 stages.append(_stage("LLM 工具判断" if routed_tool else "LLM 工具判断","completed" if routed_tool else "failed"))
 tool_name=None
 if routed_tool=="rag": decision="rag"
 elif routed_tool:
  tool_name=routed_tool
  decision={"get_order_status":"order","get_logistics_tracking":"logistics","get_device_status":"device","get_device_last_seen":"device","assess_return_eligibility":"return","create_service_ticket":"ticket"}[routed_tool]
 # 知识类问题交回原 RAG，保留向量检索、引用校验和敏感信息检查。
 if decision=="rag":
  result=answer_question(question,history,principal.role,principal.internal_authorized,request_id)
  result["agentMode"]="rag"; result["stages"]=stages+result.get("stages",[]); result["toolCalls"]=[]; result["pendingConfirmation"]=None; return result
 tool_name=tool_name or {"order":"get_order_status","logistics":"get_logistics_tracking","device":"get_device_status","return":"assess_return_eligibility","ticket":"create_service_ticket"}[decision]
 args=_extract_args(question,decision,routed_args)
 if tool_name=="create_service_ticket": args={"subject":"X100 售后申请","description":question}
 # 没有设备 SN 的通用离线排查属于知识问题，不应因缺少查询对象而拦截。
 if decision=="device" and not args and ("怎么办" in question or "显示离线" in question):
  result=answer_question(question,history,principal.role,principal.internal_authorized,request_id)
  result["agentMode"]="rag"; result["stages"]=stages+result.get("stages",[]); result["toolCalls"]=[]; result["pendingConfirmation"]=None
  return result
 tool=registry[tool_name]
 stages.append(_stage("工具选择"))
    # 写工具只生成一次性确认单，确认前不执行副作用；哈希绑定原始参数。
 if tool.risk_level=="write":
  cid=uuid.uuid4().hex; pending={"confirmationId":cid,"expectedAction":tool_name,"parametersHash":parameter_hash(args),"parameters":args,"principal":principal,"requestId":request_id,"created":time.time()}; PENDING[cid]=pending
  return {"answer":"请确认是否创建售后人工工单。","needHuman":False,"handoffReason":None,"stages":stages+[_stage("工具选择"),_stage("等待确认","pending")],"toolCalls":[],"pendingConfirmation":{"confirmationId":cid,"expectedAction":tool_name,"parametersHash":pending["parametersHash"],"summary":"创建售后人工工单"},"citations":[],"agentMode":"tool","steps":[],"warnings":[],"sources":[],"confidence":0.0,"llmModel":route_model,"debug":None}
 result=_mcp_execute(tool_name,args,principal,request_id); _audit(request_id,principal,tool_name,args,result)
 calls.append({"toolName":tool_name,"toolCallId":result.requestId,"status":"completed" if result.ok else "failed","summary":result.userMessage,"data":result.data if result.ok else {}})
 answer=result.userMessage
 # 设备问题组合工具事实与 RAG 解释；工具结果不冒充知识库引用。
 if decision=="device" and result.ok and ("离线" in question or "怎么办" in question):
  rag_result=answer_question(question,history,principal.role,principal.internal_authorized,request_id)
  return {**rag_result,"answer":f"{result.userMessage}\n\n{rag_result.get('answer','')}","stages":stages+[_stage("工具执行")]+rag_result.get("stages",[]),"toolCalls":calls,"pendingConfirmation":None,"agentMode":"tool+rag"}
 if result.ok: answer,final_model,warnings=_finalize_tool_with_llm(question,history,result,tool_name)
 else: answer,final_model,warnings=result.userMessage,None,[]
 return {"answer":answer,"needHuman":result.needHuman,"handoffReason":result.userMessage if result.needHuman else None,"stages":stages+[_stage("工具执行","completed" if result.ok else "failed"),_stage("LLM 生成","completed" if final_model else ("failed" if result.ok else "skipped"))],"toolCalls":calls,"pendingConfirmation":None,"citations":[],"agentMode":"tool","requestId":request_id,"steps":[],"warnings":warnings,"sources":[],"confidence":1.0 if result.ok else 0.0,"llmModel":final_model or route_model,"debug":{"elapsedMs":int((time.time()-started)*1000)}}

def confirm_action(confirmation_id, expected_action, parameters_hash, principal):
    # 确认时重新比对会话、动作和参数哈希，防止确认单被跨会话或改参复用。
 p=PENDING.pop(confirmation_id,None)
 if not p or time.time()-p["created"]>600: return {"ok":False,"error":"确认已过期或不存在"}
 if p["expectedAction"]!=expected_action or p["parametersHash"]!=parameters_hash or p["principal"]!=principal: return {"ok":False,"error":"确认参数不一致"}
 result=_mcp_execute(expected_action,{**p["parameters"],"idempotencyKey":confirmation_id},principal,p["requestId"]); _audit(p["requestId"],principal,expected_action,p["parameters"],result,"confirmed")
 return {"ok":result.ok,"toolResult":result.as_dict(),"error":None if result.ok else result.userMessage}
