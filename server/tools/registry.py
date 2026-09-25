from .base import Tool
from .order_tools import get_order_status, assess_return_eligibility, create_service_ticket, ORDER_SCHEMA, RETURN_SCHEMA, TICKET_SCHEMA
from .logistics_tools import get_logistics_tracking
from .device_tools import get_device_status, get_device_last_seen
ALLOWED_TOOLS={
 "get_order_status":Tool("get_order_status","查询当前用户有权查看的订单状态",ORDER_SCHEMA,"read",("user","agent","internal"),get_order_status),
 "assess_return_eligibility":Tool("assess_return_eligibility","根据购买日期和当前日期判断七天无理由退货资格",RETURN_SCHEMA,"read",("user","agent","internal"),assess_return_eligibility),
 "get_logistics_tracking":Tool("get_logistics_tracking","查询订单物流轨迹",{"type":"object","properties":{"orderId":{"type":"string"}},"additionalProperties":False},"read",("user","agent","internal"),get_logistics_tracking),
 "get_device_status":Tool("get_device_status","查询当前用户有权查看的 X100 设备状态",{"type":"object","properties":{"deviceSn":{"type":"string"}},"additionalProperties":False},"read",("user","agent","internal"),get_device_status),
 "get_device_last_seen":Tool("get_device_last_seen","查询设备最后在线时间和离线原因",{"type":"object","properties":{"deviceSn":{"type":"string"}},"additionalProperties":False},"read",("user","agent","internal"),get_device_last_seen),
 "create_service_ticket":Tool("create_service_ticket","创建售后人工工单",TICKET_SCHEMA,"write",("user","agent","internal"),create_service_ticket),
}
registry=ALLOWED_TOOLS
def tools_for(principal): return [t for t in ALLOWED_TOOLS.values() if principal.role in t.allowed_roles]
