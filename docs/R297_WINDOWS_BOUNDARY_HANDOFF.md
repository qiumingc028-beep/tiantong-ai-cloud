# R297 Windows boundary candidate (not release approval)

CURRENT_RECOVERY_BASE_HEAD: `2c9e23e5e51fc0d54374549d0e63f6cbb31fac5f`

The dedicated recovery increment below builds on all changes through this head.
Its version is the commit containing this document; native certification remains
pending. The following source description records the earlier integration only.

ORIGINAL_BOUNDARY_BASE_HEAD: `826eac7585b11d56be62a4fa9a64e4ef7fa419a3`

INFRA_SOURCE: `ef38a43c4507b4f7f24808840ce6497c998aeeb0` contains ORIGINAL_BOUNDARY_BASE_HEAD;
integration is a fast-forward followed by the Windows boundary patch, not an
old-branch file replacement. The reviewed installer version is the full commit
containing this document (`git rev-parse HEAD`), never the earlier source SHA.

## Retained and changed

- Retained relay `recover_receipt`, original event digest, protected received_at,
  twelve-hour recovery limit, original ACK bytes, Broker APIs, both ACKs,
  Observer-before-DELETE, authorization revocation and generation fencing.
- Windows request/receipt/schema types reject bool and float aliases. Timely
  original receipts are required for old facts; changed signed events, scope,
  attempts, challenges, source workflows and late first receipts fail closed.
- Shared `r297_windows_file_security` queries owner/DACL/SIDs using
  `GetSecurityInfo` on the same `CreateFileW` handle used for reads. Every parent
  is held against deletion; leaf handles deny writing and replacement. Reparse
  points, remote/alternate-stream paths, non-regular files and hardlinks reject.
  OpenSSL uses the captured key path while all handles remain locked.
- The installer archives the new module and installs an admin-owned exact-DACL
  `protected/file-policy.json` with observer/candidate SIDs. Secret read grants
  must be limited to SYSTEM, Administrators and the fixed observer SID; only
  SYSTEM/Administrators may own or mutate the private key. Existing permissive
  private keys are rejected, not silently chmod-ed or declared safe.
- Installer identity preflight rejects Backup Operators, dangerous direct or
  nested-group user-right assignments, and existing processes retaining old
  logon tokens. An incomplete process-owner query fails closed. Both identities
  must be logged off before installation; native policy-export validation is
  still required on the authorized Windows host.
- CI identities bind the original full node ID using a domain-separated digest;
  display text remains redacted. Ordinals assigned after redaction are removed.
  These digests are not a credential store: real credentials must never appear
  in pytest parameter IDs. Coverage still requires exact union, no overlap,
  actual per-node teardown reports, same HEAD/run/attempt and successful jobs.

## Ownership / remaining work

① owns the three Windows core files and shared native helper; ⑤ owns Linux
installation, receipt sealing/transfer, orchestrator and workflow wiring. No
shared implementation was overwritten with an older side of a merge.

Windows body/sidecar two-hardlink recovery now has a dedicated implementation
in `r297_windows_file_security.recover_bound_file`, called by the trusted
Observer only after the original request/run approvals are validated. Its
callback verifies the original event signature, scope and protected receipt
before any link cleanup. Public `protected_open` and normal publication still
reject multiple links; private recovery does not widen those public interfaces.

The recovery holds the protected parent and both file objects, checks volume /
file identity, exactly two links, original bytes, owner/DACL, and the single
publisher temporary name. It deletes that opened temporary link using
FileDispositionInfoEx (DELETE | POSIX_SEMANTICS), closes its handle, and verifies
the original object's link count is one. It never deletes via an unchecked path.
Normal Windows publication and recovery share a nonblocking directory file lock
(coordination only, no second receipt ledger). Unsupported APIs and busy locks
fail closed; callers must retry, never interpret them as success.

File flushing and `NtFlushBuffersFileEx(flags=0)` directory barriers run before
cleanup, after cleanup, and on retries even when no temporary link remains.
Missing-sidecar publication and its ACL/content/flush checks now complete under
that same recovery lock, closing the cleanup-to-publication race between two
recoverers. No FileExistsError is ignored and the public writer stays exclusive.
No data-only/no-sync fallback or ignored directory-flush failure is allowed.
POSIX publication / sidecar B / ledger recovery are unchanged.

P1 remains **native validation**, not unimplemented cleanup: actual limited-user
Windows sharing modes, file disposition, directory flush and storage behavior
must be certified on the deployment filesystem. A native failure remains BLOCK
and requires a core fix by ①; it is not permission to remove a safety check.

P1 acceptance prerequisite: native Windows owner/DACL, candidate SID isolation,
parent junction/reparse and replacement-race tests have not run on this Mac.
Pure ACL-policy tests do not substitute for them. ⑤ must install this exact
candidate on an authorized test host and retain the results for ③/④.

⑤ follow-up patches, independent branch:

1. Linux first-install rollback is fixed in infrastructure parent
   `0d77211781c436ba18b308878de7e135503f671c`; do not redo it. The full pending
   chain is `ef38a43c4507b4f7f24808840ce6497c998aeeb0` →
   `0d77211781c436ba18b308878de7e135503f671c` →
   `360d9a2c4142b39085f9a379b4e15c0031fec76f` →
   `cf86fe1b053fcd1aceeab884c265bbdee2e9716c` →
   `9319c7014e36c51ccb82f763a0e6dac47b08e4c6`. The cf86 plugin-isolation fix is
   accepted as delivered and 9319's same-runner identity-key patch is fetched.
   The chain still awaits ⑤'s assert, child-cleanup and cache-isolation follow-up
   and ③/④ confirmation; it has not been merged. Formal Evidence is
   a separate gate, not a prerequisite for integrating safe evidence code.
2. Windows workflow push/PR path filters must include
   `ops/r297_windows_file_security.py` and its tests. This candidate also changes
   existing trigger paths, but a later helper-only patch would otherwise miss CI.
3. Provision key owner/DACL exactly, keep candidate outside privileged groups,
   install the protected SID policy, and test the actual limited observer task
   identity. Configure acceptance scope/APP_ENV and transfer only sealed Broker
   receipts. No caller-provided trusted time, test-mode bypass or new ledger.

③ input: this candidate's exact SHA, all existing tests plus the Windows policy,
strict-type, original-receipt and colliding-redaction identity regressions.
④ input: same SHA and native boundary above; distinguish static analysis from
native evidence. Existing formal Evidence failures remain blockers.

## Native probe for ⑤

Install the exact new candidate, including `ops/r297_windows_recovery_probe.py`
in the pinned signer manifest. With that pinned interpreter/code and the actual
limited observer identity, execute the module against the protected outbox:

```text
python -m ops.r297_windows_recovery_probe C:\ProgramData\TiantongAI\R297TrustedWindowsObserver\outbox --request <protected-original-request.json> --original-event <protected-original-event.json>
```

Use the installed task's isolated import setup (`-I` plus pinned code root), not
an arbitrary checkout or test environment. The probe verifies SIGNER_SHA /
CODE_MANIFEST first and requires APP_ENV=acceptance. Both input files and their
sidecars must be protected, single-link original files. The event must already
be more than five minutes old, with a timely protected relay receipt still
inside the twelve-hour recovery period. Use the same installed signer SHA and
protected run binding, artifact manifest, page Observer ACK and relay receipt
as the original observation. No command option supplies a trusted clock or
receipt; the existing fixed readers load those approvals. Missing prerequisites
are BLOCK, never a reason to generate synthetic signed business evidence.

The probe copies original signed bytes only into fresh protected subdirectories,
interrupts fixture publication after body/sidecar hardlink creation, and calls
the complete `recover_trusted_output` entry for every recovery. It checks missing
and altered receipts before cleanup, missing-sidecar completion, original inode
and byte preservation, and native dual-BUSY failure while holding the publication
lock. Two subsequent recovery processes require at least one success; all child
processes are reaped even on timeout or failed startup. Retry checks the complete
entry again. No business process is rerun, timestamp changed or signature created.
Fixture directories remain for inspection, never overwrite source evidence, and
are not ingestion inputs. The report is recovery-test evidence only, not a new
formal business result or power-loss certification.

Additional native gates: invalid third link / foreign temporary / changed bytes,
candidate ACL grants, parent junction/reparse and replacement races, cleanup and
directory-flush interruptions, reboot/power-loss behavior, and execution of this
full signed receipt → `recover_trusted_output` → missing-sidecar probe. The portable
filesystem-adapter tests cover control flow only, never Windows security claims.

This increment changes `ops/r297_windows_recovery_probe.py`,
`ops/r297_windows_file_security.py`, `ops/r297_trusted_windows_observer.py`,
`tests/test_r297_windows_recovery.py` and this handoff. The prior installer and
all existing hardening remain in 2c9e23e. ⑤ owns workflow launch and path-filter wiring for the
probe, shared Windows helper, observer, installer and their tests; ① owns these
core/probe implementations. Do not independently overwrite shared files.

After any HEAD change: rebuild the pinned signer archive/CODE_MANIFEST, rerun
affected core and native probes, and regenerate candidate-bound CI/Process/
Windows artifacts. Do not re-label earlier artifacts with the new SHA.

R297_GO_LIVE=BLOCK

RELEASE_APPROVAL=NOT_GRANTED

RC_HEAD_LOCKED=NO

Native API references: [GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo),
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
Recovery barriers: [NtFlushBuffersFileEx](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntflushbuffersfileex),
[file disposition semantics](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/2e860264-018a-47b3-8555-565a13b35a45).
