from .base import ToolResult, valid_sn
DEVICES={"X100-DEMO-0001":{"owner":"demo-user","online":True,"firmware":"1.2.0","lastSeen":"2026-09-24 10:20","reason":"正常心跳"},"X100-DEMO-0002":{"owner":"demo-user","online":False,"firmware":"1.1.8","lastSeen":"2026-09-23 18:10","reason":"WiFi 连接中断"}}
def _get(args, principal, rid, name):
 sn=args.get("deviceSn")
 if not valid_sn(sn): return ToolResult(False,name,rid,{},"设备 SN 格式不正确","invalid_device_sn",False)
 d=DEVICES.get(sn)
 if not d or d["owner"]!=principal.user_id: return ToolResult(False,name,rid,{},"无法查看该设备","resource_forbidden",True)
 return d
def get_device_status(args, principal, rid):
 d=_get(args,principal,rid,"get_device_status")
 if isinstance(d,ToolResult): return d
 data={"online":d["online"],"firmware":d["firmware"],"lastSeen":d["lastSeen"]}
 return ToolResult(True,"get_device_status",rid,data,"设备当前在线" if d["online"] else "设备当前离线")
def get_device_last_seen(args, principal, rid):
 d=_get(args,principal,rid,"get_device_last_seen")
 if isinstance(d,ToolResult): return d
 return ToolResult(True,"get_device_last_seen",rid,{"lastSeen":d["lastSeen"],"reason":d["reason"]},f"设备最后在线时间：{d['lastSeen']}")
