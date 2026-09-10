# R297 e79 integration handoff

R297_GO_LIVE=BLOCK
RELEASE_APPROVAL=NOT_GRANTED
RC_HEAD_LOCKED=NO

## Inputs and semantic mapping

- BASE_HEAD: `e79f72bbbf11d525781ab289ac04f9fe919af67d` (remote rechecked before integration).
- Runner: `1944fe1f74b4c411fb1ad3afe9b5520f53b885c1`, branch `codex/r297-runner-ack-recovery`. Integrated only the new delta of its two Runner files against e79, not its merge history. Product `frontend/stores.html` is not in this source.
- Infrastructure: `1696794b569defba22eef2ee776d45d755706185`, branch `codex/r297-takeover-infra-evidence-r3`. Applied its delta from `91a3c4930319b29f8f12af6e8bf0ff38c5549f45`; preserved e79 core. Prior sources already integrated were not replayed.

No whole-side conflict replacement. Existing recover_receipt, strict ACK integer
types, exact event digest binding, five-minute first verification, twelve-hour
protected recovery, sidecar/ledger link recovery and Process safety stops remain.
Owner UNKNOWN, datasets, migrations, queue fencing and WebSocket revocation code
were not rewritten.

## Integration corrections

- Receiver/Observer/Windows relay recover existing Producer bytes through the
  same Broker receipt API, before repairing publication. Only explicit missing
  receipt allows first verification of the SAME event. Protocol/transport errors
  remain BLOCK, not permission to issue a new event. No new ledger.
- Role services return original file bytes plus hash. Orchestrator validates
  these, never reserializes ACK inputs. Broker persists the original file hashes
  in the existing run and publishes read-only original ACK files and sidecars.
  See [the shared contract](R297_BROKER_TRANSACTION_HANDOFF.md).
- Runner uses zero-redirect routed requests and blocks service workers. Actual
  Chromium GET/navigation and POST 307 probes verify zero target requests; CI
  runs the same controlled probe inside the built Runtime image.
- Windows accepts the full, typed original Broker snapshot rather than a
  trimmed serialization. Recursive Producer ACL grants reach children after
  inheritance removal. Linux reloads each new role unit before starting it.
  Legacy Observer endpoint migration preserves the existing password.
- Runtime's actual docker invocation retains APP_ENV=acceptance,
  R297_CONTROLLED_CANARY=1 and its controlled dashboard target. Windows secretless
  build/SHA artifacts stay separate from the formal Environment job; its signer
  safety stop is retained. SKIPPED is not PASS.

## Validation and limitations

Precommit worktree checks (not certification of e79 or of a future SHA):
160/160 affected checks, Node 58/58, Linux real peer UID 43/43, Chromium controlled
redirect probe 3/3. Full R297 collected 521: 512 passed, 9 formal evidence
failures, 0 skipped/errors. A subsequent 24-check targeted run includes the
additional Receiver recovery cases. Postcommit results must be bound to the
delivered integration SHA separately; never reuse these as a new-HEAD PASS.

Remaining inputs and ownership:

- ②: deliver the independently committed minimal stores.html / actual request
  adapter redirect fix. Runner protection is not product-page protection.
- ⑤: the authorized Windows relay now returns the Broker's original receipt and
  the verifier publishes it as a SHA-bound artifact. Windows recovery beyond five
  minutes accepts only those original bytes and that receipt; it never connects
  to the Linux Unix socket. Real Windows DACL/rollback execution is still required.
- ⑤: run the real fixed-SHA services/Windows identity installation and workflow
  orchestration. Scope must come from protected configuration, with dynamic
  run/attempt/challenge. The CI source now reads scope vars but does not prove
  those values, protected Broker socket, original bundle or Windows resources
  are present. Do not switch formal APP_ENV to test.
- ③: fetch the published integration SHA and rerun full collection, database,
  Node, original-byte ACK, Producer outage/error, sidecar B and Process recovery
  gates; retain all nine evidence failures until original same-HEAD evidence exists.
- ④: review current delta and trust boundaries, especially Runner versus product
  page, original-file publication and cross-host Windows recovery. Static review
  and controlled browser tests are not real JD acceptance.

No main merge, production deployment, force push, evidence rewriting or release
approval is part of this handoff. The commit containing this document is a
reviewable integration candidate, not a locked RC.
