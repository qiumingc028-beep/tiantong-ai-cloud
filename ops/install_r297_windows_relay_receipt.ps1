param(
  [Parameter(Mandatory=$true)][string]$SourceReceipt,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'R297_WINDOWS_ADMIN_REQUIRED'
}
$source = (Resolve-Path -LiteralPath $SourceReceipt).Path
& fsutil reparsepoint query $source *> $null
if ($LASTEXITCODE -eq 0) { throw 'R297_RELAY_RECEIPT_REPARSE_POINT_REJECTED' }
$content = [IO.File]::ReadAllBytes($source)
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
if ($actual -cne $ExpectedSha256.ToLowerInvariant()) { throw 'R297_RELAY_RECEIPT_SHA256_MISMATCH' }
$sourceSidecar = "$source.sha256"
if (-not (Test-Path -LiteralPath $sourceSidecar -PathType Leaf)) { throw 'R297_RELAY_RECEIPT_SIDECAR_MISSING' }
if ((Get-Content -Raw -LiteralPath $sourceSidecar).Trim() -cne "$actual  $([IO.Path]::GetFileName($source))") {
  throw 'R297_RELAY_RECEIPT_SIDECAR_MISMATCH'
}
$receipt = [Text.Encoding]::UTF8.GetString($content) | ConvertFrom-Json
$required = @(
  'schema_version', 'verifier_id', 'source_workflow_run_id', 'event_sha256', 'sequence',
  'received_at', 'namespace', 'tenant_id', 'company_id', 'store_id', 'platform',
  'release_sha', 'run_id', 'run_attempt', 'challenge'
)
if ((Compare-Object @($receipt.psobject.Properties.Name | Sort-Object) @($required | Sort-Object)) -or
    $receipt.schema_version -ne 1 -or $receipt.verifier_id -cne 'tiantong-r297-receipt-broker-v1' -or
    $receipt.sequence -ne 3 -or $receipt.event_sha256 -notmatch '^[0-9a-f]{64}$') {
  throw 'R297_RELAY_RECEIPT_SCHEMA_INVALID'
}

$protected = Join-Path $env:ProgramData 'TiantongAI\R297TrustedWindowsObserver\protected'
if (-not (Test-Path -LiteralPath $protected -PathType Container)) { throw 'R297_TRUSTED_PROTECTED_ROOT_MISSING' }
& fsutil reparsepoint query $protected *> $null
if ($LASTEXITCODE -eq 0) { throw 'R297_RELAY_RECEIPT_REPARSE_POINT_REJECTED' }
$destination = Join-Path $protected 'windows-relay-receipt.json'
$destinationSidecar = "$destination.sha256"
$temporary = Join-Path $protected ('.relay-receipt-' + [guid]::NewGuid().ToString('N'))
$temporarySidecar = "$temporary.sha256"
try {
  [IO.File]::WriteAllBytes($temporary, $content)
  [IO.File]::WriteAllText($temporarySidecar, "$actual  windows-relay-receipt.json`n", [Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $temporary -Destination $destination -Force
  Move-Item -LiteralPath $temporarySidecar -Destination $destinationSidecar -Force
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -cne $actual -or
      (Get-Content -Raw -LiteralPath $destinationSidecar).Trim() -cne "$actual  windows-relay-receipt.json") {
    throw 'R297_RELAY_RECEIPT_PUBLICATION_FAILED'
  }
} finally {
  Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $temporarySidecar -Force -ErrorAction SilentlyContinue
}
Write-Output "R297_WINDOWS_RELAY_RECEIPT_SHA256=$actual"
Write-Output 'R297_WINDOWS_RELAY_RECEIPT=READY'
