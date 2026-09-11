# R297 a0 product and partitioned CI integration

BASE_HEAD=a0b6e36cb0eb6e5c237278016913e665816761c9
FRONTEND_SOURCE=e002981fe26450f54ae734d8d7f572e3528e96f6
INFRA_SOURCE=326dab4a6796480917631d911e7182ecd4e44072
R297_GO_LIVE=BLOCK
RELEASE_APPROVAL=NOT_GRANTED
RC_HEAD_LOCKED=NO

## Semantic mapping

- Frontend: only the three requested product files from e002981 versus a0.
  stores.html now routes API, Owner operations, preflight and ticket exchange
  through the same-origin adapter with redirect:error. Integration adds a
  regression and rejects a same-origin absolute URL whose // pathname would be
  reinterpreted as an external origin when passed to fetch. Existing Runner
  history is not replayed.
- Infra: incremental CI split, allowed matrix selection, timeout progress and
  report upload changes from 326dab4 are retained. New receipt-client assertions
  are adapted to a0's existing recovery entry point; their missing-receipt-only
  fallback and conflict rejection assertions remain.
- Do NOT take the source's sidecar-before-receipt implementation or remove a0's
  RoleService original bytes/hash response. Broker, shared recovery, orchestrator,
  Windows complete snapshot validation and installation corrections remain
  unchanged from a0. No Windows recovery implementation is inferred from source
  ancestry or test counts.

## Exact CI completion contract

Main execution excludes only tests/test_task_center_full_entrypoint_ownership.py;
the independent ownership job executes that file. The final pytest-complete-gate
job always runs after both jobs and independently collects all tests from the
same checked-out release SHA. It requires:

1. Both GitHub job results equal success, never skipped/cancelled/failure.
2. Both reports bind the same full SHA, workflow run and attempt.
3. Both pytest sessions completed with exit 0 and matching zero-failure,
   zero-error, zero-skip JUnit totals.
4. Actual completed execution identities exactly match each collected list.
5. The two lists have no duplicates/intersection and their union equals the
   independent full-repository collection. 1700/500 are guardrails only, not
   evidence of completeness.

The collection lists contain SHA256 of the ORIGINAL UTF-8 pytest nodeid, not raw
parameter values. Separate display files and progress names are redacted.
Execution records carry the same original identity hash, so display redaction
collisions cannot hide missing tests. Outputs must be fresh; report absence,
partial progress, cancellation or a stale attempt keeps the final gate BLOCK.
No failed evidence test is deselected by this split.

The existing Chromium redirect probe additionally runs the product adapter in a
separate browser context WITHOUT the Runner routing guard. Normal request,
redirected POST and ambiguous // pathname are checked independently; these are
controlled regressions, not real JD acceptance.

## Ownership and remaining prerequisites

- ① alone integrates/publishes PR38 and owns shared Broker/transaction semantics.
- ② owns product/Runner follow-ups using this integrated request adapter.
- ⑤ owns Windows native receipt recovery, hardlink ACL boundary, fixed-SHA service
  installation and actual workflow/service wiring. No such production or host
  installation is executed by this integration. Coordinate shared-file deltas
  against the new HEAD, not by replacing a0's files with the older branch.
- ③ reruns the delivered SHA; ④ reviews it. Local collection equality is separate
  from successful execution of both full CI tasks. Missing Process/Windows formal
  evidence remains BLOCK and must not be replaced with controlled fixtures.

Precommit evidence: front-end missing adapter and ambiguous-path regressions,
missing exact aggregator, raw nodeid leakage and fault-injected telemetry fsync
were observed failing before fixes. Recovery/ACK targeted checks 166/166 and
controlled Runner/product browser checks 3/3 each passed; final committed-SHA
counts and CI links are reported separately. This is not an RC freeze.
