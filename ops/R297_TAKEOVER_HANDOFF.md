# R297 controlled acceptance handoff

Status: BLOCK. This document grants no main merge, production deployment, or release approval.

## Windows job separation and frontend Runner integration

The integration following `efa916386365c7791287ac966792c45b16f0e71d` imports only
the two acceptance files from role ② source
`3c679e28e2f996e6d94096b506a44aab455c8761`; existing pages and product code are unchanged.
This is source delivery, not approval to publish this Runner's output as formal evidence.
Review found these open Runner defects for role ② and role ③ to reproduce and repair:

- Direct status/ticket requests do not participate in the current Owner operation/ack
  protocol and conflict with the page's previously successful operations (HTTP 409).
- The pagehide timeout does not cancel its inner timer loop, potentially preventing exit.
- Owner-page WebSocket preflight and popup navigation alone do not establish popup RFB
  readiness or a real Viewer frame; `novnc_page: PASS` is not reliable acceptance evidence.
- Expected negative HTTP responses may produce browser console errors; validate this in
  Chromium and distinguish only those exact negative requests without relaxing other errors.

Role ⑤ source `b5213a5dddaf6ffb52d9be86715d44f92b2a2095` already contains the job
separation. Its relevant structure is now carried forward by semantic hunks: build-windows
has no protected Environment/Secrets, publishes the exact-SHA build artifact independently,
and formal-windows-acceptance downloads that same run's exact-SHA artifact only on manual
dispatch. The independent-signer throw remains before any private-key materialization.
A skipped formal job on push/PR is NOT formal acceptance PASS.

The source's older pagehide-ID-derived acceptance run binding is not imported: it does not
provide the protected run_attempt/challenge protocol already required on mainline. The
existing Environment run ID is also not sufficient for formal acceptance; role ⑤ must
replace it with protected orchestration as part of the signer implementation. The hard
BLOCK remains in place; do not remove it to make candidate code execute with signing keys.

Prior dda5460/e5972bb/b5213a5 patches remain integrated, including protected-run validation,
non-consuming bundle precheck, independent signer blocking, component-exit diagnostics,
shared fail-closed redaction and private raw-log files. Patch integration is not inferred
from ancestry alone. Role ③'s next unpublished tests still require a source path or branch
handoff; they are not claimed integrated until their exact assertions can be inspected.

## Integration review of role ⑤ increment

Source `dda5460aae3c7cb3b3c165e8f6b63b4352da8f4d` is applied incrementally to
`acd7cb1ff63ff8ed6cd7e71eaa537d272bc135f3`, not by merging its parent history.
Owner UNKNOWN recovery, verified empty datasets and worker fencing remain unchanged.
Bundle construction now validates the protected run without consuming it; only formal
verification consumes the run. Runtime diagnostics identify an exited process and redact
logs, but do not establish or repair the health failure's root cause (owned by role ⑤).

Formal orchestration still has these explicit code/wiring blockers:

- Run consumption and the separate nonce ledger/output publication are not one recoverable
  transaction. A crash after consumption fails closed but cannot yet resume that acceptance.
- The current run-ledger reader requires its writer's UID and writable 0600 files. An
  independently isolated Receiver needs a trusted read-only challenge interface; do not
  grant it the orchestrator/verifier's writable identity to make this code pass.
- The five-minute run/event limit is not proven compatible with both long-cycle observations.
  Do not simply widen the freshness limit or call controlled tests real acceptance.
- The formal Windows job stops before signing-key materialization. A pinned independent
  signer and trusted observation resource are still absent; adding Secrets is not the fix.

Role ⑤ must supply the remaining protected orchestration design/fixes and actual container
failure diagnostics. These blockers are not waived by integrating this reviewable candidate.

## 2026-09-07 read-only environment observation

- Candidate source inspected: `402b078fadcfaecb07472813738c56f3c4e47b37`.
- `https://internal.tiantongai.com/api/health` returned HTTP 200, but reported release
  `8f4e105002afe22ee84cf738cb4ad9209e06bba6`; it is not the candidate.
- Backend, Worker, PostgreSQL, Redis and Nginx were running on the isolated host, and the
  Worker heartbeat was current. This only proves the old isolated deployment was healthy.
- Loopback port 18443 presented an expired internal self-signed certificate whose hostname
  did not match `internal.tiantongai.com`; it is not an acceptable candidate TLS endpoint.
- The protected trust manifest, pagehide binding, their sidecars and the persistent nonce
  ledger were absent from the isolated host. No candidate deployment or evidence run was
  attempted.
- Role ⑤ later reported the following environment changes in its handoff; the integrator
  has not reverified them and they are not acceptance evidence for the current HEAD.
  In an earlier separately authorized environment-repair run, loopback port 18443 originally
  presented an expired internal self-signed certificate whose
  hostname did not match `internal.tiantongai.com`. On 2026-09-07 it was replaced, with a
  rollback copy retained, by the host's existing Let's Encrypt certificate for
  `internal.tiantongai.com`; verified HTTPS returned 200 and Nginx remained healthy. This did
  not deploy candidate application code. This task did not rotate or overwrite TLS material.
- Three distinct acceptance signing keys were generated. The Receiver and Observer private
  keys are installed under separate non-login identities with mode 0400; the verifier cannot
  read either key. The root-owned trust manifest and sidecar are mode 0444, and the verifier's
  persistent nonce ledger and lock are mode 0600 in a mode-0700 directory. The Windows private
  key remains pending protected GitHub Environment provisioning.
- The same-HEAD pagehide binding remains absent until the final RC artifact exists. A proposed
  Observer role was not widened to all database tables: the old 0042 database lacks the three
  candidate scheduler tables, so the partial role was removed and must be created after the RC
  migration with SELECT limited to `stores`, `jd_workbench_sync_policies`, and `jd_sync_logs`.
  No candidate deployment or evidence run was attempted.
- Same-head native pagehide artifacts exist for Actions runs `34071629609` (artifact
  `10000690778`) and `34071628655` (artifact `10000688691`). They remain unsigned raw inputs,
  not formal Observer or Process evidence.

## Candidate and code gates

Use the current `codex/r297-cloud-integration` commit as the candidate; record its full SHA
before running anything. Do not reuse the older PR51 pagehide artifact. CI checks out the
PR source SHA explicitly on Linux and Windows. Each artifact must identify that same SHA.

The full repository pytest step runs even when the preceding evidence step fails. Its gate
requires every collected test to execute, at least the previous 1846 tests, and zero failures,
errors or skips. JUnit and the collected-node manifest are uploaded even on failure. Missing
formal evidence remains a failure; a code test report is not release approval.

Runtime unit tests, controlled canary metrics, native pagehide and Windows packaging are
separate from real authenticated JD acceptance. No current fixture is proof of a real JD login.

## Owner-operation causal receipts and human recovery

The repair delta starts at `402b078fadcfaecb07472813738c56f3c4e47b37`; use the
published candidate's full SHA, not that baseline, for the next acceptance run.
PR49/PR51 history, 0050–0054, dataset validation/upserts and safety tests remain intact.

Backend persists a unique `operation_id` with PENDING before each create/status/ticket/delete
call. Runtime receives `x-owner-operation-id`, exclusively creates a signed PENDING receipt
before execution, and fsyncs a SUCCESS receipt with the response SHA256 before returning 200.
The response echoes the ID and digest; Backend rejects absent/mismatched correlation.
Only `GET /internal/jd-browser/operations/{id}` can reconcile that operation: current session
state is not historical proof. Receipts contain scope, action, ID, status and digest, never
the ticket, cookie or credential. Duplicate IDs cannot execute again. Unknown outcomes,
missing/corrupt receipts and legacy rows without IDs stay PENDING; they cannot be automatically
certified from session state. Startup/periodic recovery retains claim-token fencing.

Environment dependency: Runtime's existing archive volume must be persistent, writable and
support exclusive create, atomic rename and fsync. Keep its master key stable across restarts;
key loss/rotation without receipt migration makes old receipts unverifiable (PENDING).
Do not delete receipts as session cleanup. Retention/disk capacity needs operational monitoring;
disk write failure is fail-closed. Roll out matching Backend/Runtime builds on an authorized
candidate environment; an older Runtime response lacks proof and the new Backend returns 503.
No deployment is authorized by this document.

Device ONLINE/IDLE/SYNCING/OFFLINE/PAUSED or a device-uploaded dataset is not proof of JD human
recovery. The shared check requires a successful cloud capture for the same store and current
claim generation, started after the latest error and finished by the current time. Missing
proof returns 409 without clearing the block. Policy toggles can request retry but cannot clear
human errors. Reporting a human error fences an active Worker immediately. Scheduler/reaper/
completion status writers preserve the block until a newer proven capture completes; existing
periodic scheduling remains the recovery probe (a same-window prior success can defer retry to
the next window). Stale Workers cannot commit or ACK under the revoked generation.

These are controlled contracts, not proof that real JD selectors or human handling work.
Role ③/④ must verify the published delta; role ②/⑤ must supply any additional branch handoff.
After planned code convergence, role ⑥ registers RC_HEAD separately from release acceptance.

## User configuration: existing Windows workflow

The GitHub connection was verified on 2026-09-07 with create/list/delete probes for both an
Environment Secret and an Environment Variable. It can administer `r297-controlled-canary`.
No formal value was available, so no required Secret or scope Variable was invented or set.
- Subsequent role ⑤ handoff (not reverified by the integrator) reports scope variables for namespace
`r297-controlled-canary` and tenant/company/store `1/1/3`. The environment still has no
required reviewer or branch policy, so signing keys were not uploaded into an unprotected
environment. If the selected policy forbids self-review, first invite one trusted collaborator
who can review this Environment; GitHub does not universally require a second reviewer.
Restrict deployments to the integration and evidence branches before provisioning Secrets.

Open repository Settings → Environments → `r297-controlled-canary` → Add environment secret.
Use that Environment, not a repository-wide secret. The existing Windows workflow already
reads these exact names:

| Secret | Value to supply privately | Purpose |
|---|---|---|
| `R297_WINDOWS_RUNNER_PRIVATE_KEY_BASE64` | Base64 of the acceptance Windows signer's private PEM; never a test key | Sign observed native Windows process exit |
| `R297_EVIDENCE_TRUST_MANIFEST_BASE64` | Base64 of the approved acceptance public-key manifest | Pin three distinct signer roles and their allowed events |
| `R297_EVIDENCE_TRUST_MANIFEST_SHA256` | SHA256 of the decoded manifest bytes, independently approved | Reject a substituted trust manifest |
| `R297_WINDOWS_CANARY_BACKEND_HTTPS_URL` | Isolated candidate Backend HTTPS origin | Install/pair against the candidate, never an old production release |
| `R297_WINDOWS_CANARY_PAIRING_ISSUER_BEARER` | Short-lived Owner authorization for that isolated Backend | Obtain one-use pairing codes; not a JD account password |
| `R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64` | Base64 of the exact Backend server certificate DER | Verify certificate chain, hostname and certificate binding |

Also set Environment variables `R297_EVIDENCE_NAMESPACE`, `R297_EVIDENCE_TENANT_ID`,
`R297_EVIDENCE_COMPANY_ID`, and `R297_EVIDENCE_STORE_ID` to the actual authorized acceptance
scope. Platform is fixed to `jd`. A protected orchestrator must issue a fresh `run_id`,
positive `run_attempt`, and random challenge in the persistent run ledger, bound once to the
pagehide workflow run, candidate SHA, and complete scope. Every producer validates that same
record and the verifier atomically consumes it. Do not use static Environment run IDs, invent
IDs, reuse a source run, or use a production Owner token. Pull-request and push runs retain
the build/security checks but do not consume protected material or claim formal acceptance.

Protect the Environment with reviewed branch/deployment rules and required review before
releasing real material to a candidate. No secret belongs in an issue, PR body, workflow
literal, chat or test report. A signing key and the trust approval cannot both be supplied
by an untrusted event producer.

## Linux: current protected-host contract (not wired to Environment Secrets)

These are existing protected environment/mount inputs, not GitHub Secret names that the
current Linux workflow consumes. Setting an identically named GitHub Secret alone does not
mount a file or produce an event.

| Role | Existing input | Provisioning action on the isolated acceptance host |
|---|---|---|
| page receiver | `R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH` | Mount its independently authorized private PEM readable only by that signer |
| Observer | `R297_OBSERVER_PRIVATE_KEY_PATH` | Mount a different Observer private PEM only in the Observer process |
| Observer | `R297_OBSERVER_DATABASE_URL` | Inject a PostgreSQL URL for the candidate DB's SELECT-only role |
| verifier | `R297_EVIDENCE_NONCE_LEDGER` | Supply a persistent, writable nonce ledger outside the disposable output directory |
| orchestrator/verifier | `R297_ACCEPTANCE_RUN_LEDGER` | Persist issued/consumed run challenges outside disposable jobs |
| all roles | `/etc/tiantong/r297-evidence-trust-manifest.json` and `.sha256` | Administrator provisions the approved root-owned, read-only trust anchor |
| page receiver | `/etc/tiantong/r297-pagehide-artifact-binding.json` and `.sha256` | Pin the newly generated candidate artifact's run/SHA/archive/content hashes |

The verifier must receive no signer private key. Run the existing
`python -m ops.r297_evidence_preflight --role ROLE` inside each role's isolated environment.
It reports names/status only. Do not copy another role's key to satisfy a preflight.

## Remaining integration work and real credentials

Windows observations now use the public Owner-scoped
`GET /api/jd-workbench/stores/{store_id}/acceptance-status` route. It is disabled outside
controlled acceptance/test mode. The workflow checks Backend release and all five scope
fields before issuing a pairing code, then requires a new completed cloud window after
native Electron exit. This read-only observation is not the independent signed Observer.

The existing Process generator still requires a genuine `--signed-event-bundle`; no bundle
has been supplied. It creates a fresh isolated database and later requires events for that
run's namespace, scope and observation times. An old or cross-environment bundle is invalid.
The page receiver, two database observations (after page close and after Electron exit), and
Windows runner must be orchestrated against the same live acceptance run before teardown.
This orchestration and final material wiring are still BLOCK; merely adding Secrets cannot
certify it. `signed-event-bundle` is generated evidence, not a manually authored Secret.
The current candidate Windows workflow is not an independent signing boundary because it
checks out candidate code while holding the signing key. Formal signing must move to a
protected fixed `SIGNER_SHA` and a trusted Windows observation resource that executes no
candidate script or downloaded executable. Until then, do not give the candidate job the
Windows private key or call its output formal Windows evidence.

Actual JD login requires the Owner to use the controlled public login/noVNC flow, including
any required verification. Do not submit the JD password/cookies to ChatGPT or GitHub.
The Runtime currently relies on dataset selectors whose compatibility with an actual JD
page is unverified. Authorized real-page observations are needed to finish and validate
those adapters; controlled HTML cannot substitute for them.

The executable producer order is:

1. `python -m ops.r297_authenticated_observer receive ...` validates the same-HEAD native
   pagehide Artifact and its protected binding, then emits a signed page event plus sidecar.
2. In the Observer-only identity, `python -m ops.r297_authenticated_observer observe ...`
   reads the live candidate database with the SELECT-only role and signs the first observation.
3. The Windows workflow installs and exits the real Electron client, then emits its signed
   exit event plus sidecar. It aligns the exit to within 120 seconds of the database-reported
   next cycle, then uses a bounded 240-second post-exit observation window.
4. Before the candidate environment is stopped, the Observer runs `observe` again against
   the signed Electron event.
5. In a verifier-only identity, `python -m ops.r297_evidence_bundle OUTPUT PAGE PAGE_OBSERVER
   ELECTRON ELECTRON_OBSERVER --namespace ... --tenant-id ... --company-id ... --store-id ...
   --platform jd --release-sha ... --run-id ...` verifies all four sidecars, signatures,
   roles, order and scope, then publishes the bundle with a crash-recoverable sidecar commit
   marker. It refuses signer private keys.

The formal verifier still enforces its five-minute freshness window and durable nonce ledger.
The Windows client remains alive until the database-authoritative `next_sync_at` is within
120 seconds, then exits and signs; this supports 300/900/1800/3600-second policies without
making an old event acceptable. Every event also carries the same protected run ID, so two
runs on one release/store cannot be combined. Do not tear down the database or runtime until
the bundle and formal Process evidence have both completed.

Only after the code, stable PostgreSQL migration/recovery, same-SHA real Windows/Process,
real JD read-only data parity, zero-leak and independent security gates pass can the
candidate be presented for RELEASE_APPROVAL.
