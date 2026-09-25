import unittest
from server.mcp_client import MCPClient, MCPClientError
from server.mcp_context import MCPPrincipal

class MCPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = MCPClient()
        self.user = MCPPrincipal('demo-user', 'user', False, request_id='mcp-test')

    def tearDown(self):
        self.client.close()

    def test_explicit_tools_and_structured_result(self):
        names = {item['name'] for item in self.client.list_tools(self.user)}
        self.assertEqual(len(names), 6)
        result = self.client.call_tool('get_order_status', {'orderId': 'ORD-DEMO-1001'}, self.user, 'r1')
        self.assertTrue(result['ok'])
        self.assertIn('toolCallId', result)
        self.assertNotIn('owner', result['data'])

    def test_unknown_and_foreign_resource_are_rejected(self):
        with self.assertRaises(MCPClientError):
            self.client.call_tool('python_eval', {}, self.user, 'r2')
        result = self.client.call_tool('get_order_status', {'orderId': 'ORD-DEMO-1002'}, self.user, 'r3')
        self.assertEqual(result['errorCode'], 'resource_forbidden')

    def test_internal_role_requires_authorization(self):
        principal = MCPPrincipal('demo-user', 'internal', False)
        names = {item['name'] for item in self.client.list_tools(principal)}
        self.assertEqual(len(names), 6)
        result = self.client.call_tool('get_order_status', {'orderId': 'ORD-DEMO-1001'}, principal, 'r4')
        self.assertTrue(result['ok'])

if __name__ == '__main__':
    unittest.main()
