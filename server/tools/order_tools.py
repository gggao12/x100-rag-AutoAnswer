from __future__ import annotations
from datetime import date
from .base import Tool, Principal, ToolResult, valid_order_id, valid_sn
from ..mysql_store import get_order as mysql_get_order
# 这是 MySQL 不可用时的本地演示兜底，正式查询优先读取 mysql_store。
ORDERS = {
 # 1001 用于演示“今天是购买后第八天”的退货政策判断。
 "ORD-DEMO-1001": {"owner":"demo-user", "status":"运输中", "orderedAt":"2026-09-17", "item":"X100 主机", "eta":"2026-09-26"},
 "ORD-DEMO-1002": {"owner":"other-user", "status":"已签收", "orderedAt":"2026-09-18", "item":"X100 配件", "eta":"2026-09-23"},
}
TICKETS: dict[str, dict] = {}
DEVICE_ORDER_MAP = {"X100-DEMO-0001": "ORD-DEMO-1001"}
def get_order_status(args, principal, rid):
    oid=args.get("orderId")
    if oid is None: return ToolResult(False,"get_order_status",rid,{},"请提供订单号后查询","missing_order_id",False)
    if not valid_order_id(oid): return ToolResult(False,"get_order_status",rid,{},"订单号格式不正确","invalid_order_id",False)
    # 先查 MySQL；只有连接失败或没有该演示订单时才使用内置数据。
    order=mysql_get_order(oid) or ORDERS.get(oid)
    if not order or order["owner"] != principal.user_id: return ToolResult(False,"get_order_status",rid,{},"无法查看该订单","resource_forbidden",True)
    data={k:order[k] for k in ("status","orderedAt","item","eta")}
    return ToolResult(True,"get_order_status",rid,data,f"订单 {oid} 当前状态：{order['status']}")

def assess_return_eligibility(args, principal, rid):
    """只读计算退货资格；日期和资格由服务端工具决定，LLM 只负责解释。"""
    device_sn, order_id = args.get("deviceSn"), args.get("orderId")
    if device_sn is not None and not valid_sn(device_sn):
        return ToolResult(False, "assess_return_eligibility", rid, {}, "设备编号格式不正确", "invalid_device_sn", False)
    if order_id is not None and not valid_order_id(order_id):
        return ToolResult(False, "assess_return_eligibility", rid, {}, "订单号格式不正确", "invalid_order_id", False)
    if not device_sn and not order_id:
        return ToolResult(False, "assess_return_eligibility", rid, {}, "请提供设备编号或订单号", "missing_identifier", False)
    resolved_order = order_id or DEVICE_ORDER_MAP.get(device_sn)
    if not resolved_order:
        return ToolResult(False, "assess_return_eligibility", rid, {}, "未找到该设备关联订单", "order_not_found", True)
    order = mysql_get_order(resolved_order) or ORDERS.get(resolved_order)
    if not order or order["owner"] != principal.user_id:
        return ToolResult(False, "assess_return_eligibility", rid, {}, "无法查看该订单的退货资格", "resource_forbidden", True)
    if not device_sn:
        device_sn = next((sn for sn, oid in DEVICE_ORDER_MAP.items() if oid == resolved_order), "")
    try:
        purchase_date = date.fromisoformat(str(order["orderedAt"]))
    except ValueError:
        return ToolResult(False, "assess_return_eligibility", rid, {}, "订单购买日期无效，请转人工核验", "invalid_purchase_date", True)
    today = date.today()
    elapsed_days, day_number, policy_days = (today - purchase_date).days, (today - purchase_date).days + 1, 7
    eligible = elapsed_days < policy_days
    reason = f"购买后第{day_number}天，已超过{policy_days}天无理由退货期限" if not eligible else f"购买后第{day_number}天，仍在{policy_days}天无理由退货期限内"
    data = {"deviceSn": device_sn, "orderId": resolved_order, "purchaseDate": purchase_date.isoformat(), "today": today.isoformat(), "elapsedDays": elapsed_days, "dayNumber": day_number, "policyDays": policy_days, "eligible": eligible, "reason": reason, "item": order["item"]}
    return ToolResult(True, "assess_return_eligibility", rid, data, reason)
def create_service_ticket(args, principal, rid): # rid是request/tool call的唯一ID
    key=args.get("idempotencyKey") or rid #幂等性，优先使用调用方提供的 idempotencyKey，没有就使用 rid
    if key in TICKETS: return ToolResult(True,"create_service_ticket",rid,TICKETS[key],"工单已存在，可使用原工单号")
    if not isinstance(args.get("subject"),str) or not args["subject"].strip() or not isinstance(args.get("description"),str): return ToolResult(False,"create_service_ticket",rid,{},"工单主题和描述不能为空","invalid_arguments",False)
    ticket={"ticketId":"TKT-DEMO-"+key[:8].upper(),"subject":args["subject"][:100],"status":"待人工处理"}; TICKETS[key]=ticket
    return ToolResult(True,"create_service_ticket",rid,ticket,"人工工单已创建")
ORDER_SCHEMA={"type":"object","properties":{"orderId":{"type":"string"}},"additionalProperties":False}
RETURN_SCHEMA={"type":"object","properties":{"deviceSn":{"type":"string"},"orderId":{"type":"string"}},"additionalProperties":False}
TICKET_SCHEMA={"type":"object","properties":{"subject":{"type":"string"},"description":{"type":"string"},"orderId":{"type":"string"},"deviceSn":{"type":"string"},"idempotencyKey":{"type":"string"}},"additionalProperties":False}
