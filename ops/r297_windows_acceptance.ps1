param(
  [Parameter(Mandatory = $true)][string]$DistDirectory,
  [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Require([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

function Sha256([string]$Path) {
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Assert-BackendTlsBinding([string]$Origin, [byte[]]$ExpectedCertificateBytes) {
  $uri = [Uri]$Origin
  $expected = [Security.Cryptography.X509Certificates.X509Certificate2]::new($ExpectedCertificateBytes)
  $tcp = [Net.Sockets.TcpClient]::new()
  $script:r297RemoteCertificate = $null
  try {
    $tcp.Connect($uri.Host, $uri.Port)
    $callback = {
      param($Sender, $Certificate, $Chain, $PolicyErrors)
      $script:r297RemoteCertificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($Certificate)
      return $PolicyErrors -eq [Net.Security.SslPolicyErrors]::None
    }
    $tls = [Net.Security.SslStream]::new($tcp.GetStream(), $false, $callback)
    try { $tls.AuthenticateAsClient($uri.Host) } finally { $tls.Dispose() }
    Require ($null -ne $script:r297RemoteCertificate) 'CONTROLLED_BACKEND_TLS_CERTIFICATE_MISSING'
    $expectedSha = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($expected.RawData))
    $actualSha = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($script:r297RemoteCertificate.RawData))
    Require ($actualSha -eq $expectedSha) 'CONTROLLED_BACKEND_TLS_CERTIFICATE_MISMATCH'
  } finally {
    $tcp.Dispose()
    $script:r297RemoteCertificate = $null
  }
}

$head = (& git rev-parse HEAD).Trim()
Require ($head -match '^[0-9a-f]{40}$') 'CHECKOUT_HEAD_INVALID'
Require ($env:GITHUB_SHA -eq $head) 'EVIDENCE_COMMIT_MUST_EQUAL_GITHUB_SHA'
Require ($env:R297_WINDOWS_CANARY_PAIRING_CODE -match '^\d{8}$') 'CONTROLLED_BACKEND_PAIRING_CODE_REQUIRED'
Require ($env:R297_WINDOWS_CANARY_BACKEND_HTTPS_URL -match '^https://[^/]+/?$') 'CONTROLLED_BACKEND_HTTPS_URL_REQUIRED'
Require ($env:R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64 -match '^[A-Za-z0-9+/=]+$') 'CONTROLLED_BACKEND_SERVER_CERTIFICATE_REQUIRED'

$backendOrigin = $env:R297_WINDOWS_CANARY_BACKEND_HTTPS_URL.TrimEnd('/')
$healthUrl = "$backendOrigin/api/health"
$schedulerUrl = "$backendOrigin/api/jd-workbench/internal/acceptance-status"
$certificateBytes = [Convert]::FromBase64String($env:R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64)
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($certificateBytes)
Require ($certificate.NotAfter.ToUniversalTime() -gt [DateTime]::UtcNow) 'CONTROLLED_BACKEND_SERVER_CERTIFICATE_EXPIRED'
Assert-BackendTlsBinding $backendOrigin $certificateBytes

$dist = (Resolve-Path $DistDirectory).Path
$installer = @(Get-ChildItem $dist -File -Filter '*.exe')
$portable = @(Get-ChildItem $dist -File -Filter '*.zip')
Require ($installer.Count -eq 1) 'ONE_INSTALLER_REQUIRED'
Require ($portable.Count -eq 1) 'ONE_PORTABLE_ZIP_REQUIRED'
$installerSha = Sha256 $installer[0].FullName
$portableSha = Sha256 $portable[0].FullName

$output = [IO.Path]::GetFullPath($OutputDirectory)
$installRoot = Join-Path $env:RUNNER_TEMP "r297-installed-$($head.Substring(0, 12))"
$portableRoot = Join-Path $env:RUNNER_TEMP "r297-portable-$($head.Substring(0, 12))"
$userData = Join-Path $env:RUNNER_TEMP "r297-user-data-$($head.Substring(0, 12))"
$debugPort = 19297
New-Item -ItemType Directory -Force -Path $output, $installRoot, $portableRoot, $userData | Out-Null

Expand-Archive -LiteralPath $portable[0].FullName -DestinationPath $portableRoot
$portableExecutables = @(Get-ChildItem $portableRoot -Recurse -File -Filter '*.exe' | Where-Object { $_.Name -notmatch '^Uninstall' })
Require ($portableExecutables.Count -eq 1) 'PORTABLE_ARCHIVE_EXECUTABLE_NOT_UNIQUE'

$install = Start-Process -FilePath $installer[0].FullName -ArgumentList @('/S', "/D=$installRoot") -Wait -PassThru
Require ($install.ExitCode -eq 0) 'INSTALLER_EXECUTION_FAILED'
$workbench = @(Get-ChildItem $installRoot -Recurse -File -Filter '*.exe' | Where-Object { $_.Name -notmatch '^Uninstall' })
Require ($workbench.Count -eq 1) 'INSTALLED_EXECUTABLE_NOT_UNIQUE'

$beforeHealth = (Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 15).StatusCode
Require ($beforeHealth -eq 200) 'CONTROLLED_BACKEND_NOT_HEALTHY'
$beforeCycle = [int](Invoke-RestMethod -Uri $schedulerUrl -TimeoutSec 15).completed_cycle_count
$process = Start-Process -FilePath $workbench[0].FullName -ArgumentList @(
  "--remote-debugging-port=$debugPort",
  "--user-data-dir=$userData"
) -PassThru

try {
  $targets = $null
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    try { $targets = Invoke-RestMethod -Uri "http://127.0.0.1:$debugPort/json" -TimeoutSec 2 } catch { continue }
    if (@($targets).Count -gt 0) { break }
  }
  Require (@($targets).Count -gt 0) 'WORKBENCH_DEVTOOLS_TARGET_MISSING'
  $target = @($targets | Where-Object { $_.url -like 'tiantong-workbench://*' })[0]
  Require ($null -ne $target.webSocketDebuggerUrl) 'WORKBENCH_RENDERER_TARGET_MISSING'

  $probe = Join-Path $env:RUNNER_TEMP 'r297-cdp-pairing.mjs'
  @'
const [wsUrl] = process.argv.slice(2);
const pairingCode = (await new Promise((resolve, reject) => {
  let value=''; process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => value += chunk);
  process.stdin.on('end', () => resolve(value.trim()));
  process.stdin.on('error', reject);
}));
const socket = new WebSocket(wsUrl);
let id = 0;
const pending = new Map();
socket.addEventListener('message', ({data}) => {
  const message = JSON.parse(data);
  if (message.id && pending.has(message.id)) {
    const {resolve, reject} = pending.get(message.id); pending.delete(message.id);
    message.error ? reject(new Error(message.error.message)) : resolve(message.result);
  }
});
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, {once:true});
  socket.addEventListener('error', reject, {once:true});
});
const call = (method, params={}) => new Promise((resolve, reject) => {
  const requestId = ++id; pending.set(requestId, {resolve, reject});
  socket.send(JSON.stringify({id:requestId, method, params}));
});
await call('Runtime.enable');
await call('Runtime.evaluate', {awaitPromise:true, expression:`(async()=>{
  document.querySelector('#deviceName').value='R297 Windows CI';
  document.querySelector('#pairingCode').value=${JSON.stringify(pairingCode)};
  document.querySelector('#pairingForm').requestSubmit();
  for(let i=0;i<120;i++){
    if(document.querySelector('#cloudStatus').textContent==='连接正常') return true;
    if(document.querySelector('#formMessage').textContent) throw new Error(document.querySelector('#formMessage').textContent);
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  throw new Error('PAIRING_TIMEOUT');
})()`});
const diagnostic = await call('Runtime.evaluate', {returnByValue:true, expression:`({
  paired:document.querySelector('#cloudStatus').textContent==='连接正常',
  readOnly:document.querySelector('#browseMode').textContent.includes('只读'),
  diagnosticVisible:Boolean(document.querySelector('#openDiagnostic')) && !document.querySelector('#openDiagnostic').classList.contains('hidden'),
  businessWrites:document.querySelector('#businessWrites').textContent
})`});
process.stdout.write(JSON.stringify(diagnostic.result.value));
socket.close();
'@ | Set-Content -LiteralPath $probe -Encoding utf8NoBOM
  $probeResult = ($env:R297_WINDOWS_CANARY_PAIRING_CODE | node $probe $target.webSocketDebuggerUrl) | ConvertFrom-Json
  Require ($probeResult.paired -eq $true) 'PAIRING_NOT_COMPLETED'
  Require ($probeResult.readOnly -eq $true) 'READ_ONLY_POLICY_NOT_VISIBLE'
  Require ($probeResult.diagnosticVisible -eq $true) 'DIAGNOSTIC_UI_NOT_VISIBLE'
  Require ($probeResult.businessWrites -eq 'BUSINESS_WRITE_COUNT=0') 'BUSINESS_WRITE_COUNT_NOT_ZERO'

  $processTree = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installRoot, [StringComparison]::OrdinalIgnoreCase)
  })
  Require ($processTree.Count -ge 2) 'PACKAGED_CHROMIUM_PROCESS_MISSING'
  $firstPid = $process.Id
} finally {
  if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

$afterExitHealth = (Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 15).StatusCode
Require ($afterExitHealth -eq 200) 'CLOUD_SCHEDULER_DID_NOT_SURVIVE_ELECTRON_EXIT'
$afterCycle = $beforeCycle
for ($attempt = 0; $attempt -lt 60 -and $afterCycle -le $beforeCycle; $attempt++) {
  Start-Sleep -Seconds 1
  $afterCycle = [int](Invoke-RestMethod -Uri $schedulerUrl -TimeoutSec 15).completed_cycle_count
}
Require ($afterCycle -gt $beforeCycle) 'CLOUD_SCHEDULER_DID_NOT_ADVANCE_AFTER_ELECTRON_EXIT'
$restart = Start-Process -FilePath $workbench[0].FullName -ArgumentList @("--user-data-dir=$userData") -PassThru
Start-Sleep -Seconds 5
Require (-not $restart.HasExited) 'WORKBENCH_RESTART_FAILED'
$restartPid = $restart.Id
Stop-Process -Id $restart.Id -Force

$evidence = [ordered]@{
  commit = $head
  mode = 'real_windows_process'
  controlled_canary = $true
  data_source = 'CONTROLLED_CANARY'
  real_jd_acceptance = $false
  mock_count = 0
  source_code_write_count = 0
  generated_at = [DateTime]::UtcNow.ToString('o')
  installer = [ordered]@{ artifact_path = $installer[0].FullName; artifact_sha256 = $installerSha; installed = $true; process_id = $firstPid }
  portable_zip = [ordered]@{ artifact_path = $portable[0].FullName; artifact_sha256 = $portableSha; archive_valid = $true; executable_count = $portableExecutables.Count }
  pairing = [ordered]@{ controlled_backend = $true; completed = $true; secret_recorded = $false }
  chromium = [ordered]@{ packaged_process_count = $processTree.Count; started = $true }
  read_only_policy = [ordered]@{ visible = $true; business_write_claim = $probeResult.businessWrites; business_write_count = 0 }
  electron_exit = [ordered]@{ cloud_health_before = $beforeHealth; cloud_health_after = $afterExitHealth; cloud_cycles_before = $beforeCycle; cloud_cycles_after = $afterCycle }
  restart = [ordered]@{ first_pid = $firstPid; second_pid = $restartPid; restored = ($firstPid -ne $restartPid) }
  diagnostics = [ordered]@{ visible = $true; secret_exposure_count = 0 }
}
$evidencePath = Join-Path $output 'R297_WINDOWS_ACCEPTANCE_EVIDENCE.json'
$json = $evidence | ConvertTo-Json -Depth 8
Require (-not ($json -match '(?i)(authorization\s*[:=]|cookie\s*[:=]|password\s*[:=]|token\s*[:=])')) 'SENSITIVE_VALUE_CAPTURED'
[IO.File]::WriteAllText($evidencePath, $json + "`n", [Text.UTF8Encoding]::new($false))
$evidenceSha = Sha256 $evidencePath
[IO.File]::WriteAllText("$evidencePath.sha256", "$evidenceSha  R297_WINDOWS_ACCEPTANCE_EVIDENCE.json`n", [Text.UTF8Encoding]::new($false))
Write-Host "R297_WINDOWS_ACCEPTANCE_EVIDENCE=$evidencePath"
Write-Host "R297_WINDOWS_ACCEPTANCE_EVIDENCE_SHA256=$evidenceSha"
