$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'R297_NATIVE_WINDOWS_REQUIRED' }
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'R297_NATIVE_ADMIN_FIXTURE_REQUIRED'
}

$suffix = [guid]::NewGuid().ToString('N')
$observerName = "r297obs$suffix".Substring(0, 20)
$candidateName = "r297cand$suffix".Substring(0, 20)
$password = ConvertTo-SecureString (([guid]::NewGuid().ToString('N')) + '!Aa1') -AsPlainText -Force
$root = Join-Path $env:RUNNER_TEMP "r297-native-$suffix"
$results = @()
$primaryErrorCode = $null
$cleanupErrorCode = $null
$knownErrorCodes = @(
  'R297_NATIVE_CANDIDATE_BOUNDARY_FAILED',
  'R297_NATIVE_OBSERVER_BOUNDARY_FAILED',
  'R297_NATIVE_DELETE_UNEXPECTED_SUCCESS',
  'R297_NATIVE_HARDLINK_COUNT_INVALID'
)

function Set-BoundaryAcl([string]$Path, [string]$ObserverSid, [bool]$ObserverModify) {
  $acl = New-Object Security.AccessControl.DirectorySecurity
  $acl.SetAccessRuleProtection($true, $false)
  $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
  foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
      [Security.Principal.SecurityIdentifier]::new($sid), 'FullControl',
      'ContainerInherit,ObjectInherit', 'None', 'Allow'))
  }
  $rights = if ($ObserverModify) { 'Modify' } else { 'ReadAndExecute' }
  $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    [Security.Principal.SecurityIdentifier]::new($ObserverSid), $rights,
    'ContainerInherit,ObjectInherit', 'None', 'Allow'))
  Set-Acl -LiteralPath $Path -AclObject $acl
}

function Invoke-As([string]$Account, [securestring]$Password, [string]$Command) {
  $credential = [Management.Automation.PSCredential]::new("$env:COMPUTERNAME\$Account", $Password)
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
  $process = Start-Process -FilePath powershell.exe -Credential $credential -ArgumentList @(
    '-NoProfile','-NonInteractive','-EncodedCommand',$encoded
  ) -WorkingDirectory $env:SystemRoot -Wait -PassThru -WindowStyle Hidden
  return $process.ExitCode
}

try {
  New-LocalUser -Name $observerName -Password $password -AccountNeverExpires -PasswordNeverExpires | Out-Null
  New-LocalUser -Name $candidateName -Password $password -AccountNeverExpires -PasswordNeverExpires | Out-Null
  $observerSid = (Get-LocalUser -Name $observerName).SID.Value
  New-Item -ItemType Directory -Force -Path $root | Out-Null
  $secret = Join-Path $root 'private.pem'
  $trusted = Join-Path $root 'trusted-code.py'
  $outbox = Join-Path $root 'outbox'
  New-Item -ItemType Directory -Path $outbox | Out-Null
  [IO.File]::WriteAllText($secret, 'test-only-private-material')
  [IO.File]::WriteAllText($trusted, 'trusted-code')
  Set-BoundaryAcl $root $observerSid $false
  Set-BoundaryAcl $outbox $observerSid $true

  $candidateCommand = "try { [IO.File]::ReadAllText('$secret') | Out-Null; exit 10 } catch {} ; " +
    "try { [IO.File]::WriteAllText('$trusted','changed'); exit 11 } catch {} ; exit 0"
  if ((Invoke-As $candidateName $password $candidateCommand) -ne 0) {
    throw 'R297_NATIVE_CANDIDATE_BOUNDARY_FAILED'
  }
  $observerCommand = "[IO.File]::ReadAllText('$secret') | Out-Null; " +
    "[IO.File]::WriteAllText('$outbox\observer.txt','ok'); exit 0"
  if ((Invoke-As $observerName $password $observerCommand) -ne 0) {
    throw 'R297_NATIVE_OBSERVER_BOUNDARY_FAILED'
  }
  $results += 'R297_NATIVE_ACL_NEGATIVE=PASS'

  $locked = Join-Path $root 'locked.txt'
  [IO.File]::WriteAllText($locked, 'locked')
  $handle = [IO.File]::Open($locked, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
  try {
    try { Remove-Item -LiteralPath $locked -Force; throw 'R297_NATIVE_DELETE_UNEXPECTED_SUCCESS' }
    catch [IO.IOException] {}
  } finally { $handle.Dispose() }
  $results += 'R297_NATIVE_HANDLE_DELETE_DENIAL=PASS'

  $body = Join-Path $root 'body.json'
  $peer = Join-Path $root '.body.json.0123456789abcdef'
  [IO.File]::WriteAllText($body, '{"test":true}')
  New-Item -ItemType HardLink -Path $peer -Target $body | Out-Null
  $links = @(fsutil hardlink list $body | Where-Object { $_.Trim() })
  if ($links.Count -ne 2) { throw 'R297_NATIVE_HARDLINK_COUNT_INVALID' }
  Remove-Item -LiteralPath $peer -Force
  $results += 'R297_NATIVE_HARDLINK=PASS'
} catch {
  $errorCode = [string]$_.Exception.Message
  $primaryErrorCode = if ($knownErrorCodes -contains $errorCode) {
    $errorCode
  } else {
    'R297_NATIVE_PROBE_FAILED'
  }
} finally {
  try {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    Remove-LocalUser -Name $observerName -ErrorAction SilentlyContinue
    Remove-LocalUser -Name $candidateName -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath $root) -or
        (Get-LocalUser -Name $observerName -ErrorAction SilentlyContinue) -or
        (Get-LocalUser -Name $candidateName -ErrorAction SilentlyContinue)) {
      $cleanupErrorCode = 'R297_NATIVE_FIXTURE_CLEANUP_FAILED'
    }
  } catch {
    $cleanupErrorCode = 'R297_NATIVE_FIXTURE_CLEANUP_FAILED'
  }
}

if ($primaryErrorCode) {
  if ($cleanupErrorCode) { Write-Output "R297_NATIVE_CLEANUP_ERROR=$cleanupErrorCode" }
  throw $primaryErrorCode
}
if ($cleanupErrorCode) { throw $cleanupErrorCode }
$results | ForEach-Object { Write-Output $_ }
