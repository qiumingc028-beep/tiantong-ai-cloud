# R297 integration: unknown Owner outcomes and verified empty datasets

This is a code candidate contract, not real JD/Windows/process evidence or a frozen RC.

## One logical Owner operation

All four Owner endpoints accept a 32-lowercase-hex `x-owner-operation-id`.
Backend reserves it in the existing audit Saga under a Store row lock before
Runtime I/O. Without a key, Backend creates one; an unresolved operation for the
same Owner/store/action is coalesced, including after a browser refresh. The
runtime operation key is never replaced just because a response is unknown.

An unknown transport/receipt result returns HTTP 503 with a structured `detail`:
`status=UNKNOWN`, original `operation_id`, `query_url`, retry delay and recovery
deadline. Audit `PENDING` means recovery is pending, not that no side effect
happened. Retrying an unresolved or unacknowledged successful operation returns
409 with its original identity/result and does not invoke Runtime again.

Backend also persists `requires_acknowledgement` on new operations. If SUCCESS
was committed but its HTTP response was lost, even a refreshed client with a new
key must first observe the old operation result. Only a subsequent explicit new
intent carrying `x-owner-ack-operation-id` for that successful prior operation
may reserve a new key. The frontend retains retry/ack keys only in memory; no
ticket, credential or operation data is written to browser storage. Backend
durable reservation and acknowledgement rules protect the reload failure window.

Runtime still exclusively reserves the key before executing. A signed SUCCESS
temporary created after an effect is historical causal evidence: querying that
same operation can re-fsync/re-publish this receipt, never replay the effect.
Unsigned, corrupt or cross-scope material cannot confirm success. A canonical
SUCCESS left after directory-fsync failure is re-fsynced before it is returned.
No tickets or response credentials are retained in receipts.

Recovery backs off 30, 60, 120, 240, then at most 300 seconds, with a persisted
15-minute automatic deadline. Unconfirmed results then become audit UNKNOWN /
manual-review-required, excluded from periodic polling. Valid claims are honored
before deadline processing; expired claims retain token fencing.

Authorized Owner recovery interfaces:

- `GET /api/jd-workbench/stores/{store}/login-operations/{operation}`: read durable
  state only; does not execute/retry an effect or contact Runtime.
- `POST .../login-operations/{operation}/reconcile` with `{}`: one bounded receipt
  query under a fresh fenced claim. Manual checks have a five-minute cooldown;
  a valid correlated receipt can finish SUCCESS even after the automatic deadline.

If proof is permanently absent, keep UNKNOWN and investigate the operation's
protected receipt storage. Do not infer success from current session state,
manufacture a receipt, mark FAILED, or bypass the original intent with a new key.
Legacy audit rows without a causal operation ID are not retroactively certified.

## Legal empty list datasets

Metrics still require their full observations. For orders/products/ads, Backend
sends an explicit date range. A bare `[]`, missing selector, DOM boolean marker,
or cached/stale response is not completeness proof.

Before navigation, Runtime starts a bounded observer for the current page's
read-only dataset response. To prove zero rows it requires:

- a new main-frame GET, started during this capture, with no redirect and no
  ServiceWorker result, on the exact trusted dashboard origin;
- HTTP 200 JSON; request query `dataset`, `store_id`, `range_start`, `range_end`
  exactly matching the request; the browser must remain on its trusted page;
- response `status=OK`, `records=[]`, the same dataset/store/date fields,
  `authenticated=true`, `permission_granted=true`, `empty_state=true`,
  integer `total_count=0`, and `pagination_complete=true`.

These fields are an authenticated read-only adapter response contract, not
invented JD endpoint names. The actual JD adapter must supply/verify this contract
from the corresponding real API; without a compatible observed response, empty
collection fails closed. DOM script flags cannot substitute for network evidence.
Real JD adapter/browser closure remains an independent acceptance dependency.

Runtime emits only validated metadata as `empty_evidence` with
`source=authenticated_network_response`; Backend independently checks exact
fields/types/scope/date before creating a verified empty result. Direct adapters
returning bare lists cannot bypass this check. Legal proven zero returns saved=0
and updates successful sync time; missing proof updates neither business records
nor successful sync time. Nonempty strict schemas and atomic upserts are retained.

## Infrastructure handoff

Runtime container health-stage diagnosis belongs to role ⑤. Role ① needs a precise
product root cause before changing product code for that failure. At inspection,
⑤'s remote branch still pointed to `841423c5b48bc5859f13512074f194324a11bcee`;
its requested follow-up security commit has not been supplied. Do not merge that
old divergent side wholesale. Signed-event freshness and publication-crash
recovery findings remain separate from these two product contracts.
