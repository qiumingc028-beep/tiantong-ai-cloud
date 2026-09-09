# R297 Broker transaction interface — review candidate, not release approval

BASE_HEAD: `1d3d2be2ce1f80b1f72cb746c7e9162b32b803e6`.
The candidate containing this file is the handoff SHA; no historical Evidence is rebound.
`R297_GO_LIVE=BLOCK`, `RELEASE_APPROVAL=NOT_GRANTED`, `RC_HEAD_LOCKED=NO`.

## Ownership and integrated sources

- ① owns `r297_acceptance_run`, `r297_evidence_events/storage`, `r297_evidence_broker/client`, `r297_process_acceptance`.
- ⑤ owns host identities, trusted signer installation, service configuration and workflow wiring. Send separate branch patches; only ① updates PR38.
- Infrastructure `8f8044be15db73e4bb9f953e9068a08c0822cc17`: six new Broker/installer/database/probe-test files integrated relative to previously integrated `b59c42d`. No old Observer, workflow, transaction or test tree copied over.
- Runner `04fb0d639c21191a189928751c3c9ba73bf8fde9`: only two Runner files integrated. Main freshness/signature assertions retained alongside root-owned run/ACK binding and ACK recovery/revocation checks. ACK recovery exits separately; not real-browser acceptance PASS.
- Tests `85ea6a013a27956f1f8be1cd2574ad8c9c6ad783`: new sidecar B assertion added to main protocol tests; no prior assertions removed.
- Existing redirect/proxy guards, WebSocket revocation, manual recovery generation observations and migrations remain unchanged.

## Transport and identities

Use `ops.r297_broker_client.broker_request(request)` with `APP_ENV=acceptance`
and `R297_ACCEPTANCE_BROKER_SOCKET` pointing at the root-owned AF_UNIX socket.
The client requires root-owned, non-writable-by-group/other socket parent,
no world socket access, and actual root server peer credentials. Server reads
Linux `SO_PEERCRED`; request UID fields grant nothing. Socket mode is 0660,
group `r297-evidence-producers`; root ledger directory/files remain 0700/0600.
No producer, including Verifier, opens or chmods these ledgers.

One newline-delimited JSON request/response, 4 MiB maximum, 15-second socket
timeout. Success is `{ok:true,value:...}`; error is `{ok:false,error:CODE}`.
No paths, signed bodies or credentials are included in wire error messages.
The Broker has no signing keys and uses the fixed trust manifest already used
by the existing verifier. Install/configure that manifest before formal use.

| Operation | Actual Unix user allowed | Request beyond `action` |
| --- | --- | --- |
| health | Any socket-authorized user | None; health is not transaction readiness |
| issue | r297-verifier | scope without run fields, source_workflow_run_id, run_attempt |
| receipt | sequence 1: r297-page-receiver; 2/4: r297-observer; 3: r297-windows-relay | event, source_workflow_run_id |
| validate | r297-verifier | scope + bundle; or scope + source_workflow_run_id + transaction_sha256 (null only before reservation) |
| reserve, nonce | r297-verifier | scope, original bundle; optional matching transaction_sha256 |
| verify | r297-verifier | scope, original bundle, consume_run; optional matching transaction_sha256 |
| begin, recover, complete | r297-verifier | scope, source_workflow_run_id, transaction_sha256 |
| stage | r297-verifier | same as recover + content_base64 (original full Process JSON bytes) |
| ack | r297-verifier | scope, source_workflow_run_id, raw_event, receiver_content_base64, observer_content_base64 |

Full scope has exactly namespace, tenant_id, company_id, store_id, platform,
release_sha, run_id, run_attempt, challenge. Transaction identity is SHA256 of
canonical JSON `{bundle,scope}` (sorted keys, compact separators, UTF-8).
No caller clock, caller output path or replacement nonce is accepted.

## Transaction and recovery contract

Reuse the existing protected run/nonce state machine, not another ledger.
First verification enforces five-minute event freshness. Original signed event
digests, trust manifest digest, complete scope, transaction and verified result
digest are durably bound. Previously verified exact facts may recover within
the existing twelve-hour window; re-signed timestamp edits are different facts.
Nonce tombstones are not discarded to make space. Existing size limits fail
closed; only expired staged body bytes are compacted, not replay identities.

`validate` with a bundle previews verification without committing nonces.
`reserve` durably verifies/reserves and commits exact nonce bindings before
returning. `nonce` repeats this idempotently; retry the same request after I/O
failure. `verify` retains the verification-only consume option; do not use it
to prematurely consume a Process run. Process uses reserve/begin/stage/complete.

`reserve/recover` return state, transaction_sha256, verified, started,
content_base64, content_sha256 and published_sha256. `begin` atomically marks
business execution started; a second begin is BLOCK, never permission to rerun.
Stage requires begin and exact binding/verified sections. The trusted Verifier
must run `_validate_process_evidence` first (the Process entrypoint does this).
Broker does not open peer-supplied raw-log/fixture paths as root or certify real
business behavior based only on a JSON body.

- Receipt response lost: repeat exact signed event under its original role;
  original receipt timestamp is retained. Another event with the same nonce is rejected.
- Reserve response lost/crash before begin: recover/reserve exact transaction;
  begin once if no prior start or local output exists.
- Begin acknowledged or response unknown, no staged bytes: `PROCESS_SIDE_EFFECTS_UNKNOWN`
  / `R297_PROCESS_RECOVERY_REQUIRES_VERIFIED_RESUME`; no business replay.
- Stage response lost: recover the original staged bytes and digest. Keep the
  original raw log and fixture files; missing/altered subordinates BLOCK.
- Body or sidecar publication interrupted: validate original content, owner,
  mode, inode and sole transaction temp-link, unlink only that link, fsync.
  Unknown links/content are rejected without deleting the published object.
- Nonce crash: retry original bundle; persisted verification bridges the
  run/nonce write boundary. No new signature, PID, timestamp, challenge or nonce.
- Complete response lost: recover original consumed record, original staged
  bytes and digest; completion is idempotent. Broker publication is under its
  own `outputs/<run_id>` directory, never a caller-chosen path.

ACK verifies the two original signed events against root-persisted receipts,
then persists `ack_verification` in that same run record. It publishes an
immutable root-owned `ack-broker-result.json` plus sidecar beneath the snapshot
directory. Response has path and SHA256. Retries preserve original verified_at
and hashes; Runner checks all bindings and a twelve-hour bound. This artifact
is not a signed event and is not a release approval.

Errors: `PERMISSION_DENIED`, `INVALID_REQUEST`, `TRANSACTION_CONFLICT`,
`RECOVERY_EXPIRED`, `PROCESS_SIDE_EFFECTS_UNKNOWN`, `IO_RETRY`.
Transport timeout/IO_RETRY means outcome unknown: query/retry the exact request
with bounded exponential backoff (e.g. 1,2,4,8,16,30 seconds) only inside the
recovery deadline. Never hot-poll, replace facts, or map BLOCK/SKIPPED to PASS.

## Inputs to ②③④⑤

- ②: consume Broker issue snapshot and ACK artifact; verify recovered ACK only
  revokes the old Viewer and does not report complete browser acceptance.
- ③: run this exact candidate's complete collection/zero-skip/redaction gate,
  including sidecar B, original five-minute outage/re-sign tests, cross-ledger
  fault injection, and `tests/r297_broker_linux_peer_probe.py` in a root,
  network-disabled disposable Linux container. Do not reuse old-head counts.
- ④: review actual UID authorization, persistent proof identity, publication
  recovery and retained Observer/Viewer fences on this candidate.
- ⑤: wire Receiver/Observer receipts and Windows relay to their separate UIDs;
  wire the Verifier to these APIs and provision immutable public ACK/snapshot
  inputs. Linux packaging now uses one complete module list.
  Two confirmed source Windows installation defects remain for ⑤: write-ACL
  mask includes composite read bits; archive install has no `.git` while the
  runtime fixed-signer check requires it. Do not delete the signer guard or
  claim installation usable before a protected installation smoke passes.
  Windows interrupted hardlink cleanup explicitly BLOCKs until a trusted ACL
  owner check exists; Unix UID/mode checks must not be treated as Windows ACL proof.

No service installation, production connection, real JD acceptance, Windows
signer acceptance or release approval was performed by this integration.
