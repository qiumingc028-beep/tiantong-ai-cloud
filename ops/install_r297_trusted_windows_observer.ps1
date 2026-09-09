param(
  [Parameter(Mandatory=$true)][string]$SourceCheckout,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$SignerSha,
  [Parameter(Mandatory=$true)][string]$PythonRuntimeRoot,
  [Parameter(Mandatory=$true)][string]$PythonExeRelativePath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$PythonSha256,
  [Parameter(Mandatory=$true)][string]$PythonRuntimeManifestPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$PythonRuntimeManifestSha256,
  [Parameter(Mandatory=$true)][string]$TrustedObserverAccount,
  [Parameter(Mandatory=$true)][string]$CandidateAccount
)
$ErrorActionPreference = 'Stop'

if (-not [Environment]::Is64BitOperatingSystem) { throw 'R297_WINDOWS_X64_REQUIRED' }
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'R297_WINDOWS_ADMIN_REQUIRED'
}
function Assert-LocalNonAdminAccount([string]$Account, [string]$Role) {
  $sid = ([Security.Principal.NTAccount]$Account).Translate(
    [Security.Principal.SecurityIdentifier]
  ).Value
  $name = ($Account -split '\\')[-1]
  $local = Get-LocalUser -Name $name -ErrorAction Stop
  if ($local.SID.Value -cne $sid) { throw "R297_${Role}_LOCAL_ACCOUNT_REQUIRED" }
  function Test-LocalGroupContains([string]$GroupSid, [string]$TargetSid, [hashtable]$Seen) {
    if ($Seen[$GroupSid]) { return $false }
    $Seen[$GroupSid] = $true
    foreach ($member in @(Get-LocalGroupMember -SID $GroupSid)) {
      if ($member.SID.Value -ceq $TargetSid) { return $true }
      if ($member.ObjectClass -eq 'Group' -and $member.PrincipalSource -eq 'Local') {
        if (Test-LocalGroupContains $member.SID.Value $TargetSid $Seen) { return $true }
      }
    }
    return $false
  }
  if (Test-LocalGroupContains 'S-1-5-32-544' $sid @{}) {
    throw "R297_${Role}_MUST_NOT_BE_ADMIN"
  }
  return $sid
}
if ((git -C $SourceCheckout rev-parse HEAD).Trim() -cne $SignerSha) { throw 'R297_SIGNER_SHA_MISMATCH' }
if (-not [string]::IsNullOrWhiteSpace((git -C $SourceCheckout status --porcelain))) {
  throw 'R297_SIGNER_CHECKOUT_DIRTY'
}

$sourcePythonRoot = (Resolve-Path -LiteralPath $PythonRuntimeRoot).Path
$runtimeManifestPath = (Resolve-Path -LiteralPath $PythonRuntimeManifestPath).Path
& fsutil reparsepoint query $runtimeManifestPath *> $null
if ($LASTEXITCODE -eq 0) { throw 'R297_PYTHON_MANIFEST_REPARSE_POINT_REJECTED' }
$runtimeManifestBytes = [IO.File]::ReadAllBytes($runtimeManifestPath)
$sha256 = [Security.Cryptography.SHA256]::Create()
try {
  $runtimeManifestDigest = ([BitConverter]::ToString(
    $sha256.ComputeHash($runtimeManifestBytes)
  )).Replace('-', '').ToLowerInvariant()
} finally { $sha256.Dispose() }
if ($runtimeManifestDigest -cne $PythonRuntimeManifestSha256.ToLowerInvariant()) {
  throw 'R297_PYTHON_MANIFEST_SHA256_MISMATCH'
}
$trustedRuntimeManifest = @(
  [Text.Encoding]::UTF8.GetString($runtimeManifestBytes) | ConvertFrom-Json
)
$trustedPaths = @{}
foreach ($item in $trustedRuntimeManifest) {
  if ($null -eq $item) { throw 'R297_PYTHON_MANIFEST_SCHEMA_INVALID' }
  $names = @($item.psobject.Properties.Name | Sort-Object)
  if ($names.Count -ne 2 -or
      $names[0] -cne 'path' -or $names[1] -cne 'sha256') {
    throw 'R297_PYTHON_MANIFEST_SCHEMA_INVALID'
  }
  if ([IO.Path]::IsPathRooted($item.path) -or
      ($item.path -split '[\\/]' | Where-Object { $_ -eq '..' }) -or
      $item.sha256 -notmatch '^[0-9a-f]{64}$' -or $trustedPaths[$item.path.ToLowerInvariant()]) {
    throw 'R297_PYTHON_MANIFEST_SCHEMA_INVALID'
  }
  $trustedPaths[$item.path.ToLowerInvariant()] = $true
}
$trustedRuntimeManifest = @($trustedRuntimeManifest | Sort-Object path)
if ([IO.Path]::IsPathRooted($PythonExeRelativePath) -or
    ($PythonExeRelativePath -split '[\\/]' | Where-Object { $_ -eq '..' })) {
  throw 'R297_PYTHON_RELATIVE_PATH_INVALID'
}
$sourcePython = (Resolve-Path -LiteralPath (Join-Path $sourcePythonRoot $PythonExeRelativePath)).Path
if (-not $sourcePython.StartsWith(
  $sourcePythonRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase
)) { throw 'R297_PYTHON_PATH_ESCAPE' }
foreach ($path in @($sourcePythonRoot, $sourcePython) + @(
  Get-ChildItem -LiteralPath $sourcePythonRoot -Recurse -Force | ForEach-Object FullName
)) {
  & fsutil reparsepoint query $path *> $null
  if ($LASTEXITCODE -eq 0) { throw "R297_PYTHON_REPARSE_POINT_REJECTED:$path" }
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePython).Hash -cne $PythonSha256) {
  throw 'R297_PYTHON_SHA256_MISMATCH'
}
$pythonSignature = Get-AuthenticodeSignature -LiteralPath $sourcePython
if ($pythonSignature.Status -ne 'Valid') { throw 'R297_PYTHON_SIGNATURE_INVALID' }
$candidateSid = Assert-LocalNonAdminAccount $CandidateAccount 'CANDIDATE'
$observerSid = Assert-LocalNonAdminAccount $TrustedObserverAccount 'OBSERVER'
if ($candidateSid -ceq $observerSid) { throw 'R297_WINDOWS_IDENTITY_COLLISION' }
$existingTask = Get-ScheduledTask -TaskName 'R297TrustedWindowsObserver' -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.State -eq 'Running') {
  throw 'R297_TRUSTED_OBSERVER_TASK_RUNNING'
}
$previousTaskXml = $null
if ($existingTask) {
  $previousExecute = [IO.Path]::GetFullPath([string]$existingTask.Actions.Execute)
  $trustedBase = [IO.Path]::GetFullPath((Join-Path $env:ProgramFiles 'TiantongAI\R297TrustedWindowsObserver'))
  if (-not $previousExecute.StartsWith($trustedBase.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'R297_PREVIOUS_TASK_NOT_TRUSTED'
  }
  $previousRoot = Split-Path (Split-Path $previousExecute -Parent) -Parent
  $previousShaPath = Join-Path $previousRoot 'SIGNER_SHA'
  $previousManifestPath = Join-Path $previousRoot 'CODE_MANIFEST.json'
  if (-not (Test-Path -LiteralPath $previousShaPath -PathType Leaf) -or
      -not (Test-Path -LiteralPath $previousManifestPath -PathType Leaf)) {
    throw 'R297_PREVIOUS_TASK_NOT_TRUSTED'
  }
  $previousTaskXml = Export-ScheduledTask -TaskName 'R297TrustedWindowsObserver'
}
$sourceRuntimeManifest = @(
  Get-ChildItem -LiteralPath $sourcePythonRoot -Recurse -Force -File |
    Sort-Object FullName | ForEach-Object {
      [pscustomobject]@{
        path = $_.FullName.Substring($sourcePythonRoot.TrimEnd('\').Length + 1)
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
      }
    }
)
if (($trustedRuntimeManifest | ConvertTo-Json -Compress) -cne
    ($sourceRuntimeManifest | ConvertTo-Json -Compress)) {
  throw 'R297_SOURCE_PYTHON_RUNTIME_MISMATCH'
}

$versionBase = Join-Path $env:ProgramFiles 'TiantongAI\R297TrustedWindowsObserver'
$installRoot = Join-Path $versionBase $SignerSha
$installStage = Join-Path $versionBase (".stage-{0}" -f [guid]::NewGuid())
$dataRoot = Join-Path $env:ProgramData 'TiantongAI\R297TrustedWindowsObserver'
$codeRoot = Join-Path $installStage 'code'
$runtimeRoot = Join-Path $installStage 'python-runtime'
$inbox = Join-Path $dataRoot 'inbox'
$outbox = Join-Path $dataRoot 'outbox'
$protected = Join-Path $dataRoot 'protected'
$dataRootExisted = Test-Path -LiteralPath $dataRoot
$dataAclBackup = @{}
if ($dataRootExisted) {
  foreach ($item in @($dataRoot) + @(Get-ChildItem -LiteralPath $dataRoot -Recurse -Force | ForEach-Object FullName)) {
    $dataAclBackup[$item] = Get-Acl -LiteralPath $item
  }
}
$publishedNewVersion = $false
$newDataPaths = @()
trap {
  if (Test-Path -LiteralPath $installStage) {
    Remove-Item -LiteralPath $installStage -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $installStage) { throw 'R297_STAGE_ROLLBACK_FAILED' }
  }
  if ($publishedNewVersion -and (Test-Path -LiteralPath $installRoot)) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $installRoot) { throw 'R297_VERSION_ROLLBACK_FAILED' }
  }
  if ($dataRootExisted) {
    foreach ($item in $dataAclBackup.Keys) {
      if (Test-Path -LiteralPath $item) {
        Set-Acl -LiteralPath $item -AclObject $dataAclBackup[$item]
        if ((Get-Acl -LiteralPath $item).Sddl -cne $dataAclBackup[$item].Sddl) { throw 'R297_DATA_ACL_ROLLBACK_FAILED' }
      }
    }
    foreach ($item in @($newDataPaths | Sort-Object Length -Descending)) {
      if (Test-Path -LiteralPath $item) { Remove-Item -LiteralPath $item -Recurse -Force }
    }
  } elseif (Test-Path -LiteralPath $dataRoot) {
    Remove-Item -LiteralPath $dataRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
  throw
}
if (Test-Path -LiteralPath $installRoot) { throw 'R297_TRUSTED_VERSION_ALREADY_INSTALLED' }
foreach ($path in @($versionBase, $installStage, $codeRoot, $runtimeRoot, $dataRoot, $inbox, $outbox, $protected)) {
  if ($path.StartsWith($dataRoot, [StringComparison]::OrdinalIgnoreCase) -and -not (Test-Path -LiteralPath $path)) {
    $newDataPaths += $path
  }
  New-Item -ItemType Directory -Force -Path $path | Out-Null
  & fsutil reparsepoint query $path *> $null
  if ($LASTEXITCODE -eq 0) { throw "R297_REPARSE_POINT_REJECTED:$path" }
}
Copy-Item -Path (Join-Path $sourcePythonRoot '*') -Destination $runtimeRoot -Recurse -Force
$pythonPath = (Resolve-Path -LiteralPath (Join-Path $runtimeRoot $PythonExeRelativePath)).Path
if (-not $pythonPath.StartsWith(
  $runtimeRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase
)) { throw 'R297_PROTECTED_PYTHON_PATH_ESCAPE' }
if (
  (Get-FileHash -Algorithm SHA256 -LiteralPath $pythonPath).Hash -cne $PythonSha256 -or
  (Get-AuthenticodeSignature -LiteralPath $pythonPath).Status -ne 'Valid'
) { throw 'R297_PROTECTED_PYTHON_VALIDATION_FAILED' }
$protectedRuntimeManifest = @(
  Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Force -File |
    Sort-Object FullName | ForEach-Object {
      [pscustomobject]@{
        path = $_.FullName.Substring($runtimeRoot.TrimEnd('\').Length + 1)
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
      }
    }
)
if (($sourceRuntimeManifest | ConvertTo-Json -Compress) -cne
    ($protectedRuntimeManifest | ConvertTo-Json -Compress)) {
  throw 'R297_PROTECTED_PYTHON_RUNTIME_MISMATCH'
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
$sourceArchive = Join-Path $env:TEMP ("r297-trusted-source-{0}.zip" -f [guid]::NewGuid())
$codeStage = Join-Path $env:TEMP ("r297-trusted-source-{0}" -f [guid]::NewGuid())
try {
  $gitFiles = @($files | ForEach-Object { $_.Replace('\', '/') })
  & git -C $SourceCheckout archive --format=zip --output=$sourceArchive $SignerSha -- @gitFiles
  if ($LASTEXITCODE -ne 0) { throw 'R297_SIGNER_ARCHIVE_FAILED' }
  Expand-Archive -LiteralPath $sourceArchive -DestinationPath $codeStage
  foreach ($relative in $files) {
    $destination = Join-Path $codeRoot $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath (Join-Path $codeStage $relative) -Destination $destination -Force
  }
} finally {
  Remove-Item -LiteralPath $sourceArchive -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $codeStage -Recurse -Force -ErrorAction SilentlyContinue
}
[IO.File]::WriteAllText((Join-Path $installStage 'SIGNER_SHA'), "$SignerSha`n", [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText(
  (Join-Path $installStage 'PYTHON_RUNTIME_MANIFEST.json'),
  (($trustedRuntimeManifest | ConvertTo-Json -Compress) + "`n"),
  [Text.UTF8Encoding]::new($false)
)
$codeManifest = @(
  Get-ChildItem -LiteralPath $codeRoot -Recurse -Force -File |
    Sort-Object FullName | ForEach-Object {
      [pscustomobject]@{
        path = $_.FullName.Substring($codeRoot.TrimEnd('\').Length + 1).Replace('\', '/')
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
      }
    }
)
[IO.File]::WriteAllText(
  (Join-Path $installStage 'CODE_MANIFEST.json'),
  (($codeManifest | ConvertTo-Json -Compress) + "`n"),
  [Text.UTF8Encoding]::new($false)
)

foreach ($path in @($installStage, $dataRoot)) {
  & icacls $path /inheritance:r | Out-Null
  & icacls $path /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
  & icacls $path /setowner '*S-1-5-32-544' /T /C | Out-Null
}
& icacls $installStage /inheritance:r /T /C | Out-Null
& icacls $installStage /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null
& icacls $installStage /grant "$TrustedObserverAccount`:(OI)(CI)RX" /T /C | Out-Null
& icacls $dataRoot /inheritance:r /T /C | Out-Null
& icacls $dataRoot /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null
& icacls $inbox /grant "$TrustedObserverAccount`:(OI)(CI)RX" /T /C | Out-Null
& icacls $outbox /grant "$TrustedObserverAccount`:(OI)(CI)M" /T /C | Out-Null
& icacls $protected /grant "$TrustedObserverAccount`:(OI)(CI)RX" /T /C | Out-Null
& icacls $installStage /deny "$CandidateAccount`:(OI)(CI)F" | Out-Null
& icacls $dataRoot /deny "$CandidateAccount`:(OI)(CI)F" | Out-Null

foreach ($path in @($installStage, $codeRoot, $runtimeRoot, $dataRoot, $inbox, $outbox, $protected) + @(
  Get-ChildItem -LiteralPath $codeRoot -Recurse -Force | ForEach-Object FullName
) + @(
  Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Force | ForEach-Object FullName
) + @(
  Get-ChildItem -LiteralPath $dataRoot -Recurse -Force | ForEach-Object FullName
)) {
  & fsutil reparsepoint query $path *> $null
  if ($LASTEXITCODE -eq 0) { throw "R297_REPARSE_POINT_REJECTED:$path" }
  $acl = Get-Acl -LiteralPath $path
  $allowedWriters = @('S-1-5-18', 'S-1-5-32-544')
  if ($path -ceq $outbox -or $path.StartsWith($outbox.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    $allowedWriters += $observerSid
  }
  $owner = $acl.Owner
  try { $owner = ([Security.Principal.NTAccount]$owner).Translate([Security.Principal.SecurityIdentifier]).Value } catch {}
  if (@('S-1-5-18', 'S-1-5-32-544') -notcontains $owner) {
    throw "R297_UNTRUSTED_OWNER:$path"
  }
  foreach ($entry in $acl.Access) {
    if ($entry.AccessControlType -ne 'Allow') { continue }
    try {
      $sid = $entry.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    } catch { throw "R297_UNRESOLVED_ACL_IDENTITY:$path" }
    $writeRights = [int]([Security.AccessControl.FileSystemRights]::WriteData -bor
      [Security.AccessControl.FileSystemRights]::AppendData -bor
      [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
      [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
      [Security.AccessControl.FileSystemRights]::Delete -bor
      [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
      [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
      [Security.AccessControl.FileSystemRights]::TakeOwnership)
    if (([int]$entry.FileSystemRights -band $writeRights) -ne 0 -and $allowedWriters -notcontains $sid) {
      throw "R297_UNAUTHORIZED_WRITE_ACE:$path"
    }
  }
}

Write-Output 'R297_NEW_INSTALL_VALIDATED=PASS'
Move-Item -LiteralPath $installStage -Destination $installRoot
$publishedNewVersion = $true
$codeRoot = Join-Path $installRoot 'code'
$runtimeRoot = Join-Path $installRoot 'python-runtime'
$pythonPath = (Resolve-Path -LiteralPath (Join-Path $runtimeRoot $PythonExeRelativePath)).Path

$entry = "import sys;sys.path.insert(0,r'$codeRoot');from ops.r297_trusted_windows_observer import main;raise SystemExit(main())"
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument (
  "-I -c `"$entry`" `"$inbox\request.json`" `"$outbox\electron-exit.json`""
) -WorkingDirectory $codeRoot
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RestartCount 0
$principalTask = New-ScheduledTaskPrincipal -UserId $TrustedObserverAccount -LogonType ServiceAccount -RunLevel Limited
try {
  if ($existingTask) {
    Disable-ScheduledTask -TaskName 'R297TrustedWindowsObserver' | Out-Null
    if ((Get-ScheduledTask -TaskName 'R297TrustedWindowsObserver').State -eq 'Running') {
      throw 'R297_TRUSTED_OBSERVER_TASK_RUNNING'
    }
    Unregister-ScheduledTask -TaskName 'R297TrustedWindowsObserver' -Confirm:$false
  }
  Register-ScheduledTask -TaskName 'R297TrustedWindowsObserver' -Action $action `
    -Settings $settings -Principal $principalTask -Force | Out-Null
  $task = Get-ScheduledTask -TaskName 'R297TrustedWindowsObserver'
  if ($task.Actions.Execute -cne $pythonPath -or $task.Actions.Arguments -notmatch 'r297_trusted_windows_observer') {
    throw 'R297_TRUSTED_OBSERVER_IMAGEPATH_INVALID'
  }
} catch {
  Unregister-ScheduledTask -TaskName 'R297TrustedWindowsObserver' -Confirm:$false `
    -ErrorAction SilentlyContinue
  if ($previousTaskXml) {
    Register-ScheduledTask -TaskName 'R297TrustedWindowsObserver' -Xml $previousTaskXml -Force | Out-Null
    if (-not (Get-ScheduledTask -TaskName 'R297TrustedWindowsObserver' -ErrorAction SilentlyContinue)) {
      throw 'R297_TASK_ROLLBACK_FAILED'
    }
    Write-Output 'R297_TRUSTED_INSTALL_ROLLBACK=PASS'
  }
  if (Test-Path -LiteralPath $installRoot) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $installRoot) { throw 'R297_VERSION_ROLLBACK_FAILED' }
    $publishedNewVersion = $false
  }
  throw
}

Write-Output "R297_TRUSTED_WINDOWS_INSTALL=READY"
Write-Output "R297_TRUSTED_SIGNER_SHA=$SignerSha"
Write-Output "R297_TRUSTED_OBSERVER_TASK=$($task.TaskName)"
