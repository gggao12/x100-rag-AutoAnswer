import unittest
from server.agent import run_agent, confirm_action
from server.tools import Principal
class AgentToolTests(unittest.TestCase):
    def setUp(self): self.p=Principal()
    def test_order_tool_and_ownership(self):
        r=run_agent("我的订单 ORD-DEMO-1001 当前状态是什么？",[],self.p,"r1")
        self.assertEqual(r["toolCalls"][0]["toolName"],"get_order_status")
        denied=run_agent("查询 ORD-DEMO-1002",[],self.p,"r2")
        self.assertTrue(denied["needHuman"])
    def test_device_tool(self):
        r=run_agent("设备 X100-DEMO-0001 在线吗？",[],self.p,"r3")
        self.assertTrue(r["toolCalls"][0]["data"]["online"])
    def test_write_requires_confirmation_and_idempotency(self):
        r=run_agent("帮我申请换新",[],self.p,"r4")
        self.assertIsNotNone(r["pendingConfirmation"])
        p=r["pendingConfirmation"]
        done=confirm_action(p["confirmationId"],p["expectedAction"],p["parametersHash"],self.p)
        self.assertTrue(done["ok"])
        again=confirm_action(p["confirmationId"],p["expectedAction"],p["parametersHash"],self.p)
        self.assertFalse(again["ok"])
if __name__ == "__main__": unittest.main()

