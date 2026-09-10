# R297 Windows boundary candidate (not release approval)

CURRENT_RECOVERY_BASE_HEAD: `3037b67867aaed3246a49f655a6c4c28bff9eec8`

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
   `cf86fe1b053fcd1aceeab884c265bbdee2e9716c`. The cf86 plugin-isolation fix is
   accepted as delivered, but this chain is not integrated until ⑤'s cross-job
   identity-key transport fix and ④'s scope review arrive. Formal Evidence is
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
python -m ops.r297_windows_recovery_probe C:\ProgramData\TiantongAI\R297TrustedWindowsObserver\outbox
```

Use the installed task's isolated import setup (`-I` plus pinned code root), not
an arbitrary checkout or test environment. The probe verifies SIGNER_SHA /
CODE_MANIFEST first. It creates credential-free fixtures only in new directories,
kills the producer process at body/sidecar link publication, then starts two
recovery processes and requires at least one to succeed. Both are reaped on all
exits. Fixtures remain for inspection; output explicitly says filesystem-only,
no formal business Evidence, and no power-loss certification.

Additional native gates: invalid third link / foreign temporary / changed bytes,
candidate ACL grants, parent junction/reparse and replacement races, cleanup and
directory-flush interruptions, reboot/power-loss behavior, plus the full signed
receipt → `recover_trusted_output` → missing-sidecar publication path. The portable
filesystem-adapter tests cover control flow only, never Windows security claims.

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
