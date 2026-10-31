"""Protocol contracts exercised against real services, without transport mocks."""

import io
import json
import unittest

from _base import KctxTestCase
from kctx.engine import Engine, MAX_REQUEST_BYTES, serve


def rpc(method, params=None, ident=1):
    return {"jsonrpc": "2.0", "id": ident, "method": method, "params": {} if params is None else params}


class EngineProtocolTests(KctxTestCase):
    def initialized(self):
        engine = Engine(self.root)
        self.addCleanup(engine.close)
        response = engine.request(rpc("initialize", {"protocol_version": "1"}))
        self.assertEqual(response["result"]["protocol_version"], "1")
        return engine

    def test_initialization_closed_schemas_and_capabilities(self):
        engine = Engine(self.root)
        self.addCleanup(engine.close)
        self.assertEqual(engine.request(rpc("graph.status"))["error"]["code"], -32002)
        for params in ({"protocol_version": "2"}, {"protocol_version": 1}, {"protocol_version": "1", "unknown": True}):
            self.assertEqual(engine.request(rpc("initialize", params))["error"]["code"], -32602)
        self.assertIn("error", engine.request(rpc("initialize", {"protocol_version": "1", "capabilities": ["sign"]})))
        result = engine.request(rpc("initialize", {"protocol_version": "1"}))["result"]
        self.assertFalse(result["batch"])
        self.assertTrue(result["notifications"])
        self.assertNotIn("knowledge.sign", result["methods"])
        self.assertNotIn("knowledge.restore", result["methods"])
        self.assertNotIn("graph.recover", result["methods"])
        self.assertIsNone(engine.operations.graph)
        self.assertIn("error", engine.request(rpc("initialize", {"protocol_version": "1"})))
        for method, params in (("graph.uses", {"target": "A", "limit": True}),
                               ("graph.uses", {"target": "A", "limit": "5"}),
                               ("graph.status", {"unknown": "secret-input"}),
                               ("knowledge.capture", {"file": "/etc/passwd"}),
                               ("cite.make", {"citation": {"kind": "web", "fields": {"private_key": "secret-input"}}}),
                               ("cite.make", {"citation": {"kind": "web", "fields": {"url": 2}}})):
            error = engine.request(rpc(method, params))["error"]
            self.assertEqual(error["code"], -32602)
            self.assertNotIn("secret-input", json.dumps(error))
            self.assertIn("diagnostic", error["data"])
        self.assertEqual(engine.request(rpc("knowledge.sign"))["error"]["code"], -32601)

    def test_malformed_frames_resynchronize_and_notifications_remain_silent(self):
        frames = [json.dumps(rpc("initialize", {"protocol_version": "1"})).encode(),
                  b'{"jsonrpc":"2.0","id":2,"method":"graph.status","params":{"n":NaN}}',
                  b'{"jsonrpc":"2.0","id":2,"method":"graph.status","params":{"n":1e999}}',
                  b'{"jsonrpc":"2.0","id":2,"id":3,"method":"graph.status"}',
                  b'"scalar"', b"[]", b"\xff", b"{" + b"x" * MAX_REQUEST_BYTES,
                  b'{"jsonrpc":"2.0","method":"unknown"}',
                  b'{"jsonrpc":"2.0","method":"cite.make","params":{"citation":{"kind":"web","fields":{"url":"https://example.test","q":"ref"}}}}',
                  json.dumps(rpc("cite.make", {"citation": {"kind": "web", "fields": {"url": "https://example.test", "q": "ref"}}}, ident="last")).encode(),
                  json.dumps(rpc("shutdown", ident="shutdown")).encode()]
        output = io.StringIO()
        self.assertEqual(serve(self.root, io.BytesIO(b"\n".join(frames) + b"\n"), output), 0)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 10)
        self.assertEqual([response["error"]["code"] for response in responses[1:8]], [-32700, -32700, -32700, -32600, -32600, -32700, -32600])
        self.assertEqual(responses[-2]["id"], "last")
        self.assertEqual(responses[-2]["result"]["exit_code"], 0)
        self.assertEqual(responses[-1]["id"], "shutdown")
        self.assertNotIn("\x1b", output.getvalue())

    def test_citations_use_contained_paths_and_report_staleness(self):
        engine = self.initialized()
        citation = "⟦cite kind=web url=https://example.test q=reference seen=2000-01-01T00:00Z ttl=1d⟧"
        path = self.root / "citation.md"
        path.write_text(citation + "\n")
        rendered = engine.request(rpc("cite.render", {"target": "citation.md"}))["result"]
        self.assertEqual(len(rendered["payload"]["rendered"]), 1)
        stale = engine.request(rpc("cite.stale", {"paths": ["citation.md"], "offline": True}))["result"]
        self.assertGreater(stale["payload"]["total"], 0)
        self.assertFalse(stale["complete"])
        self.assertNotEqual(stale["exit_code"], 0)
        for method, params in (("cite.render", {"target": "/etc/passwd"}),
                               ("cite.check", {"paths": ["../outside.md"]}),
                               ("cite.stale", {"paths": []})):
            self.assertIn("error", engine.request(rpc(method, params)))
        link = self.root / "link.md"
        link.symlink_to(path)
        self.assertIn("error", engine.request(rpc("cite.render", {"target": "link.md"})))

    def test_eof_and_shutdown_without_graph_do_not_require_native_storage(self):
        output = io.StringIO()
        self.assertEqual(serve(self.root, io.BytesIO(), output), 0)
        self.assertEqual(output.getvalue(), "")
        engine = self.initialized()
        self.assertEqual(engine.request(rpc("shutdown"))["result"]["exit_code"], 0)
        self.assertTrue(engine.stopped)
        self.assertEqual(engine.request(rpc("cite.make"))["error"]["code"], -32002)


if __name__ == "__main__":
    unittest.main()
