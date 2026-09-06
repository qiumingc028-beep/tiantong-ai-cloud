# R297 controlled acceptance handoff

Status: BLOCK. This document grants no main merge, production deployment, or release approval.

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

## User configuration: existing Windows workflow

The GitHub connection available to this takeover supports Git/PR/Actions operations but does
not expose Secrets or Environment administration. Secret values were neither read nor set.

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
`R297_EVIDENCE_COMPANY_ID`, `R297_EVIDENCE_STORE_ID` to the actual authorized acceptance
scope. Platform is fixed to `jd`. Do not invent IDs or use a production Owner token.

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

Actual JD login requires the Owner to use the controlled public login/noVNC flow, including
any required verification. Do not submit the JD password/cookies to ChatGPT or GitHub.
The Runtime currently relies on dataset selectors whose compatibility with an actual JD
page is unverified. Authorized real-page observations are needed to finish and validate
those adapters; controlled HTML cannot substitute for them.

Only after the code, stable PostgreSQL migration/recovery, same-SHA real Windows/Process,
real JD read-only data parity, zero-leak and independent security gates pass can the
candidate be presented for RELEASE_APPROVAL.
