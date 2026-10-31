from _base import KctxTestCase

from kctx.services import inventory
from kctx.errors import KctxError
from kctx.domain.ids import AssetId
from kctx.domain.vocabulary import AssetKind, RelationshipType


class AliasResolutionTest(KctxTestCase):
    """Q02: an asset moves or is renamed — stable identity and prior evidence
    survive, and aliases resolve correctly."""

    def test_q02_show_resolves_by_alias_and_by_id(self):
        inventory.asset_add(
            self.root,
            kind=AssetKind.REPO,
            name="new-service-name",
            id=AssetId("repo-new-service-name"),
            aliases=("old-service-name", "legacy-svc"),
        )

        by_id = inventory.asset_show(self.root, "repo-new-service-name")
        by_alias = inventory.asset_show(self.root, "old-service-name")
        by_other_alias = inventory.asset_show(self.root, "legacy-svc")

        self.assertEqual(by_id.id, AssetId("repo-new-service-name"))
        self.assertEqual(by_alias.id, by_id.id)
        self.assertEqual(by_other_alias.id, by_id.id)
        self.assertEqual(inventory.get_asset(self.root, by_id.id), by_id)
        with self.assertRaises(KctxError) as ctx:
            inventory.get_asset(self.root, AssetId("old-service-name"))
        self.assertEqual(ctx.exception.category, "not-found")

    def test_show_unknown_ident_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            inventory.asset_show(self.root, "nope")
        self.assertEqual(ctx.exception.category, "not-found")

    def test_q03_ambiguous_alias_and_name_report_all_candidates(self):
        for asset_id in ("first", "second"):
            inventory.asset_add(
                self.root, kind=AssetKind.SERVICE, name="Shared name",
                id=AssetId(asset_id), aliases=("shared",),
            )
        for query in ("shared", "Shared name"):
            with self.subTest(query=query):
                with self.assertRaises(KctxError) as ctx:
                    inventory.resolve_asset(self.root, query)
                self.assertEqual(ctx.exception.category, "conflict")
                self.assertIn("first", str(ctx.exception))
                self.assertIn("second", str(ctx.exception))

    def test_exact_identity_has_priority_over_alias_and_name(self):
        exact = inventory.asset_add(
            self.root, kind=AssetKind.SERVICE, name="Exact asset", id=AssetId("first"),
        )
        inventory.asset_add(
            self.root, kind=AssetKind.SERVICE, name="first",
            id=AssetId("second"), aliases=("first",),
        )
        self.assertEqual(inventory.resolve_asset(self.root, "first"), exact)

    def test_alias_and_name_on_same_record_are_one_match(self):
        asset = inventory.asset_add(
            self.root, kind=AssetKind.SERVICE, name="shared",
            id=AssetId("first"), aliases=("shared",),
        )
        self.assertEqual(inventory.resolve_asset(self.root, "shared"), asset)


class ImpactBoundaryTest(KctxTestCase):
    """Q05/Q22: no consumers recorded within the traversal budget, and the
    budget itself is exhausted — impact must report the coverage boundary
    (inventory absence is not proof of no consumers) and name the edges left
    unexplored, rather than imply the traversal was exhaustive."""

    def _build_chain(self):
        for name in ("a", "b", "c", "d"):
            inventory.asset_add(self.root, kind=AssetKind.SERVICE, name=name, id=AssetId(f"svc-{name}"))
        inventory.rel_add(self.root, type=RelationshipType.DEPENDS_ON, from_=AssetId("svc-a"), to=AssetId("svc-b"))
        inventory.rel_add(self.root, type=RelationshipType.DEPENDS_ON, from_=AssetId("svc-b"), to=AssetId("svc-c"))
        inventory.rel_add(self.root, type=RelationshipType.DEPENDS_ON, from_=AssetId("svc-c"), to=AssetId("svc-d"))

    def test_q22_unexplored_edges_reported_when_depth_exhausted(self):
        self._build_chain()
        result = inventory.impact(self.root, "svc-a", depth=2)
        self.assertEqual(inventory.impact(self.root, AssetId("svc-a"), depth=2), result)

        reached_ids = {r.asset for r in result.reached}
        self.assertEqual(reached_ids, {AssetId("svc-b"), AssetId("svc-c")})
        self.assertNotIn(AssetId("svc-d"), reached_ids)

        unexplored_targets = {e.to for e in result.unexplored_edges}
        self.assertIn(AssetId("svc-d"), unexplored_targets)

    def test_q05_coverage_boundary_note_always_present(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name="lonely", id=AssetId("svc-lonely"))
        result = inventory.impact(self.root, "svc-lonely", depth=3)

        self.assertEqual(result.reached, ())
        self.assertIn("not proof of no consumers", result.note)
