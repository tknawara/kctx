# Provider-neutral catalog: product design

Status: researched design for the distributable engine/Rust host, not a claim
that a dynamic catalog API has already shipped. The current generic calculus
has no Humio/Grafana/bbgithub primitives. Legacy source enums and citation aliases
still preserve those historical spellings at the Python compatibility boundary.

## Decision

Keep a small closed semantic language and an extensible, versioned catalog.
Do not compile every vendor into an asset-kind enum, and do not replace nominal
identities with unchecked strings. A catalog describes entities, relations,
schemas and acquisition capabilities; it does not install new inference rules.

## Boundaries

| Layer | Owns | Must not do |
| --- | --- | --- |
| Calculus | Claims, exact revisions, scoped positive/negative support, witnesses, coverage, freshness, receipts, admission and replay | Know product names, query syntax, SQL tables or connector credentials |
| Catalog | Namespaced kind/relation/provider identities, schema revisions, allowed endpoints, declared capabilities, aliases and migration profiles | Confer truth or admission merely because a descriptor validates |
| Providers | Fetch/query/enumerate/resolve exact sources and report outcome, retained bytes, revision, completeness, permissions and timings | Convert timeout/partial/denied into empty success; self-approve a captured claim |
| Policies | Authority, intended use, freshness, source eligibility, retention and scope requirements | Change historical facts or silently reinterpret an old receipt |
| Host/storage | Normalized persistence, pinned retrieval, migrations and publication | Treat a navigation join as an inference or a cache as independent evidence |

Catalog and policy artifacts are versioned domain data pinned by a release;
`config.toml` remains the sole deployment configuration surface. Provider
credentials remain in approved credential facilities, not catalog records.

## Identity and typing

- `AssetId` is immutable and survives rename or provider migration. A friendly
  namespace/name is an alias, never a historical identity.
- `AssetKindId`, `RelationKindId`, `ProviderId`, `CatalogRevision` and
  `SchemaRevision` are distinct nominal validated values. References bind the
  catalog/schema revision used to validate the record.
- Core enums remain closed: acquisition outcome, polarity, assessment support,
  correction kind, operation outcome. Dynamic kind/provider identifiers are
  resolved through the pinned registry, not added as arbitrary enum variants.
- The stable asset envelope contains identity, revision, kind reference, aliases
  and ownership/provenance. Kind-specific properties are validated against a
  pinned schema with explicit required/unknown-field rules. Built-in kinds can
  have generated or handwritten typed views; extension payloads remain bounded
  validated JSON, never `Any` throughout services.
- Relations declare source/target kind constraints and navigation meaning.
  A new `depends_on` label does not authorize transitive/reverse inference.
  New semantic operators require a kernel version, proof and conformance work.

## Initial catalog and extensions

Ship useful provider-neutral kinds such as document, repository, service, API,
dataset, query, dashboard, alert and decision. The exact default set is a product
schema decision, not a calculus theorem. A dashboard is an entity kind; Grafana
is one provider that can describe or query it. A log stream/query is a capability;
Humio is one implementation. Enterprise GitHub is deployment/provider settings,
not a separate knowledge primitive.

An extension declares namespaced identities, schema IDs/digests, supported source
kinds, capabilities, allowed query parameter shapes and migration behavior. Start
with reviewed built-in connectors and data-only catalog extensions. Arbitrary
in-process user plugins are not required for extensibility and enlarge the trust
boundary; consider isolated external provider processes only with a concrete use
case and a versioned constrained protocol.

Unknown provider/kind/version is an explicit unsupported capability. It does not
fall back to a generic implementation that claims equivalent guarantees. Schema
changes never rewrite the interpretation of previously admitted revisions.

## Agent contract and cross-session persistence

An agent discovers supported catalog kinds/capabilities, queries a provider,
retains the exact acquisition result, proposes structured scoped statements,
obtains applicable approval, and persists an admitted revision. A later session
retrieves a bounded context with claim revisions, contrary evidence, citations,
source dependencies and receipt identity. Reuse rechecks the selected context
and material dependencies; session continuity does not create timeless truth.

Raw dialogue, tool output and summaries can be retained as sources. They are not
automatically admitted knowledge, independent corroboration, authority, or a new
inference rule. The same contract supports software work, research, personal
projects and other domains without vendor-specific calculus changes.

## Research and rejected alternatives

[Backstage descriptors](https://backstage.io/docs/features/software-catalog/descriptor-format/)
separate a versioned `apiVersion`/`kind` envelope, metadata and kind-specific
`spec`; organizations can add kinds. [Its entity references](https://backstage.io/docs/features/software-catalog/references/)
use kind/namespace/name. Reuse the envelope and namespacing ideas, not the whole
software-portal model or its name-based references as immutable historical IDs.

[JSON Schema 2020-12](https://json-schema.org/draft/2020-12/release-notes)
provides versioned schema vocabulary and composition. Its
[object rules](https://json-schema.org/understanding-json-schema/reference/object)
make required and additional/unevaluated-property policies explicit. Use a pinned
schema dialect and locally pinned schema digests; do not dynamically fetch
untrusted `$ref` targets during ordinary validation.

Rejected: vendor enums in the semantic core; unrestricted JSON dictionaries as
domain models; a universal triple store/custom Datalog engine; letting catalog
schemas or fetched prose register executable inference; silently choosing a
provider or schema version that happens to be installed. These alternatives
weaken portability, type safety, reproducibility or the proof boundary.

## Acceptance before catalog implementation ships

Provider-neutral fixtures across at least two domains; static wrong-ID-namespace
rejection; unknown-kind/version and malformed-property refusal; namespace
ambiguity; rename-stable identity; exact schema/catalog replay; failed/partial
acquisition distinction; extension cannot self-admit or install inference;
old-session receipts remain interpretable after provider/schema upgrades.
