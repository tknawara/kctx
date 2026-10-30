from _base import KctxTestCase

import inventory
from errors import KctxError


class AliasResolutionTest(KctxTestCase):
    """Q02: an asset moves or is renamed — stable identity and prior evidence
    survive, and aliases resolve correctly."""

    def test_q02_show_resolves_by_alias_and_by_id(self):
        inventory.asset_add(
            self.root,
            kind="repo",
            name="new-service-name",
            id="repo-new-service-name",
            aliases=["old-service-name", "legacy-svc"],
        )

        by_id = inventory.asset_show(self.root, "repo-new-service-name")
        by_alias = inventory.asset_show(self.root, "old-service-name")
        by_other_alias = inventory.asset_show(self.root, "legacy-svc")

        self.assertEqual(by_id["id"], "repo-new-service-name")
        self.assertEqual(by_alias["id"], by_id["id"])
        self.assertEqual(by_other_alias["id"], by_id["id"])

    def test_show_unknown_ident_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            inventory.asset_show(self.root, "nope")
        self.assertEqual(ctx.exception.category, "not-found")


class ImpactBoundaryTest(KctxTestCase):
    """Q05/Q22: no consumers recorded within the traversal budget, and the
    budget itself is exhausted — impact must report the coverage boundary
    (inventory absence is not proof of no consumers) and name the edges left
    unexplored, rather than imply the traversal was exhaustive."""

    def _build_chain(self):
        for name in ("a", "b", "c", "d"):
            inventory.asset_add(self.root, kind="service", name=name, id=f"svc-{name}")
        inventory.rel_add(self.root, type="depends-on", from_="svc-a", to="svc-b")
        inventory.rel_add(self.root, type="depends-on", from_="svc-b", to="svc-c")
        inventory.rel_add(self.root, type="depends-on", from_="svc-c", to="svc-d")

    def test_q22_unexplored_edges_reported_when_depth_exhausted(self):
        self._build_chain()
        result = inventory.impact(self.root, "svc-a", depth=2)

        reached_ids = {r["asset"] for r in result["reached"]}
        self.assertEqual(reached_ids, {"svc-b", "svc-c"})
        self.assertNotIn("svc-d", reached_ids)

        unexplored_targets = {e["to"] for e in result["unexplored_edges"]}
        self.assertIn("svc-d", unexplored_targets)

    def test_q05_coverage_boundary_note_always_present(self):
        inventory.asset_add(self.root, kind="service", name="lonely", id="svc-lonely")
        result = inventory.impact(self.root, "svc-lonely", depth=3)

        self.assertEqual(result["reached"], [])
        self.assertIn("not proof of no consumers", result["note"])
