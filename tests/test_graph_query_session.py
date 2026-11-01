"""Unified stdio acceptance against real native Dolt generations."""

import base64
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import unittest

from _base import KctxTestCase
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kctx.adapters.files.knowledge import canonical, digest, save
from kctx.domain.ids import AuthorityKeyId, PlanId, PolicyDigest
from kctx.services.knowledge import KnowledgeEngine


@unittest.skipUnless(shutil.which("dolt") or (Path.home() / ".local/bin/dolt").is_file(), "native Dolt required")
class QuerySessionIntegrationTest(KctxTestCase):
    def test_pinned_rpc_publication_refresh_and_eof_cleanup(self):
        from kctx.engine import MAX_REQUEST_BYTES
        from kctx.graph import queries, sync
        from kctx.graph.models import GraphNodeId
        from kctx.graph.query_session import QuerySession

        repo = self.make_git_repo("sessions")
        key = Ed25519PrivateKey.generate()
        key_path = self.root / "operator.pem"
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        policy = {"schema_version": 2, "kb_id": "test-kb", "policy_version": "review-policy", "trusted_keys": {"reviewer-key": {"public_key": key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(), "target_uses": ["review"]}}}
        save(repo / ".kctx" / "knowledge-policy.json", policy)
        anchor = PolicyDigest(digest(canonical(policy)))
        knowledge_dir = self.root / "knowledge-dolt"
        self.set_config(root=str(repo), graph_dir=str(self.root / "graph"), knowledge_dir=str(knowledge_dir), knowledge_policy_digest=anchor.val)
        self.commit_file(repo, "inventory/assets/a.json", '{"id":"a","kind":"service","name":"A"}\n')
        self.commit_file(repo, "inventory/assets/b.json", '{"id":"b","kind":"service","name":"B"}\n')
        self.commit_file(repo, "inventory/relationships/consumes__b__a.json", '{"id":"consumes__b__a","from":"b","to":"a","type":"consumes"}\n')
        sync.sync(repo)
        expected = queries.uses(GraphNodeId("a"), kb_root=repo)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        native_pids = []
        with subprocess.Popen([sys.executable, "-m", "kctx", "serve"], cwd=repo,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as process:
            try:
                def response():
                    self.assertTrue(select.select([process.stdout], [], [], 60)[0], "session response timed out")
                    line = process.stdout.readline()
                    self.assertTrue(line, "session exited before a response")
                    return json.loads(line)

                def request(method, params=None, ident="request"):
                    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}}).encode() + b"\n")
                    process.stdin.flush()
                    return response()

                initialized = request("initialize", {"protocol_version": "2"})
                self.assertIn("cite.make", initialized["result"]["methods"])
                self.assertIn("knowledge.admit", initialized["result"]["methods"])
                citation = request("cite.make", {"citation": {"kind": "web", "fields": {"url": "https://example.test", "q": "reference"}}})
                self.assertEqual(citation["result"]["exit_code"], 0)
                self.assertIn("https://example.test", request("cite.render", {"target": citation["result"]["payload"]["line"]})["result"]["payload"]["rendered"][0])
                captured = request("knowledge.capture", {"kind": "document", "source": "docs/design.md", "revision": "revision-17", "content_base64": base64.b64encode(b"Reviewed exact bytes\n").decode(), "observed_at": 1})["result"]["payload"]
                scope = {"project": "test-kb", "selector": ""}
                statement = {"formula": {"tag": "atom", "atom": {"subject": "service", "predicate": "reviewed", "args": []}}, "scope": scope, "polarity": "positive"}
                claim = {"id": "reviewed", "revision": "r1"}
                witness = {"tag": "attest", "attestation": "attestation-1"}
                context = {"snapshot": "bootstrap:test-kb", "semantic_version": "2.0.0", "ruleset": "core-2", "checker": "kctx-2", "policy": {"id": "review-policy", "require_fresh": True, "require_validation": False, "require_uncontested": True, "ttl": 100, "authorized_actors": ["reviewer-key"]}, "now": 5, "target": scope, "intended_use": "review", "sources": [{"source": captured["source"], "revision": captured["revision"], "content": captured["content"]}]}
                kb = {"snapshot": "generation-1", "observations": [{"id": "observation-1", "source": captured["source"], "revision": captured["revision"], "content": captured["content"], "observed_at": 1, "outcome": "ok"}], "claims": [{"id": "reviewed", "revision": "r1", "statement": statement}], "attestations": [{"id": "attestation-1", "claim": claim, "observation": "observation-1", "statement": statement, "authority": "reviewer-key"}], "enumerations": [], "derivations": [{"id": "derivation-1", "claim": claim, "witness": witness}], "corrections": [], "receipts": []}
                context["snapshot"] = kb["snapshot"]
                candidate = {"schema_version": 3, "expected_snapshot": "bootstrap:test-kb", "kb": kb, "capture_ids": [captured["id"]], "contexts": [{"id": "review", "context": context}], "assignments": [{"claim": claim, "context": "review", "witness": witness}], "retired_contexts": [], "authority_key": "reviewer-key"}
                planned = request("knowledge.propose", {"candidate": candidate, "target_use": "review", "now": 5})["result"]["payload"]
                operator = KnowledgeEngine(repo, knowledge_dir, anchor)
                approval = operator.sign(PlanId(planned["id"]), key_path, AuthorityKeyId("reviewer-key"))
                admitted = request("knowledge.admit", {"plan": planned["id"], "approval": approval.wire()})["result"]["payload"]
                context["snapshot"] = "generation-1"
                retrieved = request("knowledge.context", {"context_id": "review", "context": context, "claims": [claim], "release": admitted["release"]})["result"]
                self.assertTrue(retrieved["complete"])
                self.assertEqual(retrieved["generation"]["release"], admitted["release"])
                self.assertIn(b'"support":"positive"', canonical(retrieved["payload"]))
                explained = request("knowledge.explain", {"context_id": "review", "context": context, "claim": claim, "release": admitted["release"]})["result"]
                self.assertTrue(explained["complete"])
                self.assertTrue(request("knowledge.recover")["result"]["complete"])
                self.assertIn("error", request("knowledge.sign", {"private_key": str(key_path)}))
                self.assertIn("candidates", request("authored.home", {"ident": "a"})["result"]["payload"])
                self.assertIn("referrers", request("authored.uses", {"target": "a"})["result"]["payload"])
                self.assertEqual(request("authored.context", {"ident": "a"})["result"]["payload"]["asset"], "a")
                first = request("graph.uses", {"target": "a"})["result"]
                self.assertEqual(first["payload"], expected)
                generation = first["generation"]
                self.assertTrue(generation["is_current_publication"])
                children = Path(f"/proc/{process.pid}/task/{process.pid}/children")
                native_pids = [int(value) for value in children.read_text().split()]
                self.assertTrue(native_pids, "the production session must own a native server")
                self.assertEqual(request("graph.impact", {"target": "a", "depth": 2})["result"]["payload"]["total"], 1)
                self.assertEqual(request("graph.diff", {"kb_sha_a": "HEAD", "kb_sha_b": "WORKING"})["result"]["payload"]["sample"], [])
                self.assertTrue(request("graph.status")["result"]["complete"])
                origins = request("graph.source_paths", {"target": "a", "revision": generation["kb_sha"]})["result"]["payload"]
                self.assertEqual(origins["paths"], ["inventory/relationships/consumes__b__a.json"])
                self.assertEqual(origins["dolt_ref"], generation["data_commit"])
                for method, params in (("sql", {"query": "DELETE FROM nodes"}),
                                       ("graph.uses", {"target": "a", "limit": 1001}),
                                       ("graph.source_paths", {"target": "a", "limit": 1001}),
                                       ("graph.impact", {"target": "a", "depth": 11}),
                                       ("graph.uses", {"target": "a", "include_illus": "false"})):
                    self.assertIn("error", request(method, params))
                for malformed in (b"{not json}\n", b"\xff\n", b"[]\n",
                                  b'{"jsonrpc":"3.0","id":"bad-version","method":"graph.status"}\n',
                                  b'{"jsonrpc":"2.0","id":1,"id":2,"method":"graph.status"}\n',
                                  b"[" * 2000 + b"]" * 2000 + b"\n"):
                    process.stdin.write(malformed)
                    process.stdin.flush()
                    self.assertIn("error", response())
                process.stdin.write(b"x" * (MAX_REQUEST_BYTES + 1) + b"\n")
                process.stdin.flush()
                self.assertIn("error", response())
                self.assertEqual(request("graph.uses", {"target": "a"})["result"]["payload"], expected)

                self.commit_file(repo, "inventory/assets/c.json", '{"id":"c","kind":"service","name":"C"}\n')
                self.commit_file(repo, "inventory/relationships/consumes__c__a.json", '{"id":"consumes__c__a","from":"c","to":"a","type":"consumes"}\n')
                self.assertEqual(request("graph.sync")["result"]["exit_code"], 0)
                pinned = request("graph.uses", {"target": "a"})["result"]
                self.assertEqual(pinned["payload"], expected)
                self.assertEqual(pinned["generation"]["data_commit"], generation["data_commit"])
                self.assertFalse(pinned["generation"]["is_current_publication"])
                self.assertFalse(pinned["complete"])
                self.assertNotEqual(pinned["exit_code"], 0)
                self.assertFalse(request("graph.status")["result"]["payload"]["up_to_date"])
                self.set_config(graph_dir=str(self.root / "missing-graph"))
                self.assertIn("error", request("graph.refresh"))
                self.set_config(graph_dir=str(self.root / "graph"))
                self.assertEqual(request("graph.uses", {"target": "a"})["result"]["generation"]["data_commit"], generation["data_commit"])
                refreshed = request("graph.refresh")["result"]
                self.assertTrue(refreshed["complete"])
                self.assertNotEqual(refreshed["generation"]["data_commit"], generation["data_commit"])
                self.assertEqual(request("graph.uses", {"target": "a"})["result"]["payload"]["total"], 2)
                native_pids.extend(int(value) for value in children.read_text().split())
                process.stdin.close()
                self.assertEqual(process.wait(timeout=15), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                if not process.stdin.closed:
                    process.stdin.close()
                process.wait(timeout=15)
        for pid in native_pids:
            self.assertFalse(Path(f"/proc/{pid}").exists(), f"native child leaked: {pid}")
        with QuerySession(repo) as session:
            self.assertEqual(session.uses(GraphNodeId("a"))["total"], 2)
            self.assertTrue(session.identity()["is_current_publication"])
            historical = session.source_paths(GraphNodeId("a"), revision=generation["kb_sha"])
            self.assertEqual(historical["paths"], origins["paths"])
            self.assertEqual(historical["dolt_ref"], generation["data_commit"])
            current = session.source_paths(GraphNodeId("a"), limit=1)
            self.assertEqual(current["total"], 2)
            self.assertEqual(current["returned"], 1)
        with self.assertRaisesRegex(Exception, "not open"):
            session.uses(GraphNodeId("a"))


if __name__ == "__main__":
    unittest.main()
