from .base import ToolResult, valid_order_id
from .order_tools import ORDERS
def get_logistics_tracking(args, principal, rid):
 oid=args.get("orderId")
 if not valid_order_id(oid): return ToolResult(False,"get_logistics_tracking",rid,{},"订单号格式不正确","invalid_order_id",False)
 order=ORDERS.get(oid)
 if not order or order["owner"]!=principal.user_id: return ToolResult(False,"get_logistics_tracking",rid,{},"无法查看该订单物流","resource_forbidden",True)
 data={"carrier":"演示物流","status":"运输中","updatedAt":"2026-09-24 09:30","nodes":["已从演示仓发出","到达配送中心"]}
 return ToolResult(True,"get_logistics_tracking",rid,data,f"订单 {oid} 最近物流状态：{data['status']}")
