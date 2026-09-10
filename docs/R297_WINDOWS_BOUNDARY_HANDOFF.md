# R297 Windows boundary candidate (not release approval)

BASE_HEAD: `826eac7585b11d56be62a4fa9a64e4ef7fa419a3`

INFRA_SOURCE: `ef38a43c4507b4f7f24808840ce6497c998aeeb0` contains BASE_HEAD;
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

P1: Windows legacy body/sidecar two-hardlink interruption recovery is **BLOCK**.
The existing stop remains; it must only be replaced after same-object ACL,
link-identity and durable cleanup tests run on Windows. POSIX sidecar B and
ledger recovery remain intact. This candidate does not claim that Windows
publish-stage recovery is complete.

P1 acceptance prerequisite: native Windows owner/DACL, candidate SID isolation,
parent junction/reparse and replacement-race tests have not run on this Mac.
Pure ACL-policy tests do not substitute for them. ⑤ must install this exact
candidate on an authorized test host and retain the results for ③/④.

⑤ follow-up patches, independent branch:

1. `install_r297_trusted_linux_host.sh:rollback_unit_switch`: stop services
   started during a first installation before removing/restoring unit files.
   `had_unit=0` currently skips `systemctl stop`, leaving processes alive after
   a later install failure. Include a first-install late-failure regression.
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

R297_GO_LIVE=BLOCK

RELEASE_APPROVAL=NOT_GRANTED

RC_HEAD_LOCKED=NO

Native API references: [GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo),
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
