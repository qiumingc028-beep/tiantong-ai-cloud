param(
  [Parameter(Mandatory=$true)][string]$SourceCheckout,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$SignerSha,
  [Parameter(Mandatory=$true)][string]$PythonExe,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$PythonSha256,
  [Parameter(Mandatory=$true)][string]$TrustedObserverAccount,
  [Parameter(Mandatory=$true)][string]$CandidateAccount
)
$ErrorActionPreference = 'Stop'

if (-not [Environment]::Is64BitOperatingSystem) { throw 'R297_WINDOWS_X64_REQUIRED' }
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'R297_WINDOWS_ADMIN_REQUIRED'
}
if ((git -C $SourceCheckout rev-parse HEAD).Trim() -cne $SignerSha) { throw 'R297_SIGNER_SHA_MISMATCH' }
if (-not [string]::IsNullOrWhiteSpace((git -C $SourceCheckout status --porcelain))) {
  throw 'R297_SIGNER_CHECKOUT_DIRTY'
}

$pythonPath = (Resolve-Path -LiteralPath $PythonExe).Path
& fsutil reparsepoint query $pythonPath *> $null
if ($LASTEXITCODE -eq 0) { throw 'R297_PYTHON_REPARSE_POINT_REJECTED' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $pythonPath).Hash -cne $PythonSha256) {
  throw 'R297_PYTHON_SHA256_MISMATCH'
}
$pythonSignature = Get-AuthenticodeSignature -LiteralPath $pythonPath
if ($pythonSignature.Status -ne 'Valid') { throw 'R297_PYTHON_SIGNATURE_INVALID' }
$candidateSid = ([Security.Principal.NTAccount]$CandidateAccount).Translate(
  [Security.Principal.SecurityIdentifier]
).Value
$observerSid = ([Security.Principal.NTAccount]$TrustedObserverAccount).Translate(
  [Security.Principal.SecurityIdentifier]
).Value
$administratorSids = @(Get-LocalGroupMember -SID 'S-1-5-32-544' | ForEach-Object {
  try { $_.SID.Value } catch { $null }
})
if ($administratorSids -contains $candidateSid) { throw 'R297_CANDIDATE_MUST_NOT_BE_ADMIN' }
if ($administratorSids -contains $observerSid) { throw 'R297_OBSERVER_MUST_NOT_BE_ADMIN' }

$installRoot = Join-Path $env:ProgramFiles "TiantongAI\R297TrustedWindowsObserver\$SignerSha"
$dataRoot = Join-Path $env:ProgramData 'TiantongAI\R297TrustedWindowsObserver'
$codeRoot = Join-Path $installRoot 'code'
$inbox = Join-Path $dataRoot 'inbox'
$outbox = Join-Path $dataRoot 'outbox'
$protected = Join-Path $dataRoot 'protected'
foreach ($path in @($installRoot, $codeRoot, $dataRoot, $inbox, $outbox, $protected)) {
  New-Item -ItemType Directory -Force -Path $path | Out-Null
  & fsutil reparsepoint query $path *> $null
  if ($LASTEXITCODE -eq 0) { throw "R297_REPARSE_POINT_REJECTED:$path" }
}

$files = @(
  'ops\__init__.py',
  'ops\r297_acceptance_run.py',
  'ops\r297_evidence_events.py',
  'ops\r297_trusted_windows_observer.py',
  'ops\r297_windows_event_signer.py',
  'backend\__init__.py',
  'backend\services\__init__.py',
  'backend\services\jd_runtime_contract.py'
)
foreach ($relative in $files) {
  $destination = Join-Path $codeRoot $relative
  New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
  Copy-Item -LiteralPath (Join-Path $SourceCheckout $relative) -Destination $destination -Force
}
[IO.File]::WriteAllText((Join-Path $installRoot 'SIGNER_SHA'), "$SignerSha`n", [Text.UTF8Encoding]::new($false))

foreach ($path in @($installRoot, $dataRoot)) {
  & icacls $path /inheritance:r | Out-Null
  & icacls $path /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
}
& icacls $installRoot /grant "$TrustedObserverAccount`:(OI)(CI)RX" | Out-Null
& icacls $inbox /grant "$TrustedObserverAccount`:(OI)(CI)RX" | Out-Null
& icacls $outbox /grant "$TrustedObserverAccount`:(OI)(CI)M" | Out-Null
& icacls $protected /grant "$TrustedObserverAccount`:(OI)(CI)RX" | Out-Null
& icacls $installRoot /deny "$CandidateAccount`:(OI)(CI)F" | Out-Null
& icacls $dataRoot /deny "$CandidateAccount`:(OI)(CI)F" | Out-Null

$entry = "import sys;sys.path.insert(0,r'$codeRoot');from ops.r297_trusted_windows_observer import main;raise SystemExit(main())"
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument (
  "-I -c `"$entry`" `"$inbox\request.json`" `"$outbox\electron-exit.json`""
) -WorkingDirectory $codeRoot
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RestartCount 0
$principalTask = New-ScheduledTaskPrincipal -UserId $TrustedObserverAccount -LogonType ServiceAccount -RunLevel Limited
Register-ScheduledTask -TaskName 'R297TrustedWindowsObserver' -Action $action `
  -Settings $settings -Principal $principalTask -Force | Out-Null

$task = Get-ScheduledTask -TaskName 'R297TrustedWindowsObserver'
if ($task.Actions.Execute -cne $pythonPath -or $task.Actions.Arguments -notmatch 'r297_trusted_windows_observer') {
  throw 'R297_TRUSTED_OBSERVER_IMAGEPATH_INVALID'
}
foreach ($path in @($installRoot, $codeRoot, $dataRoot, $inbox, $outbox, $protected) + @(
  Get-ChildItem -LiteralPath $codeRoot -Recurse -Force | ForEach-Object FullName
)) {
  & fsutil reparsepoint query $path *> $null
  if ($LASTEXITCODE -eq 0) { throw "R297_REPARSE_POINT_REJECTED:$path" }
  $acl = Get-Acl -LiteralPath $path
  foreach ($entry in $acl.Access) {
    if ($entry.IdentityReference -like "*$CandidateAccount*" -and $entry.AccessControlType -eq 'Allow') {
      throw "R297_CANDIDATE_ACL_LEAK:$path"
    }
  }
}

Write-Output "R297_TRUSTED_WINDOWS_INSTALL=READY"
Write-Output "R297_TRUSTED_SIGNER_SHA=$SignerSha"
Write-Output "R297_TRUSTED_OBSERVER_TASK=$($task.TaskName)"
