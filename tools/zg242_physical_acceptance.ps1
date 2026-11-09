# MBR-004/#242. Physical Windows operator runner; never counts hosted CI as acceptance.
[CmdletBinding()]
param([string]$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
      [string]$AcceptedMain = 'd7e580c190d00e1d00a573a6b845c75ddddc1d4c',
      [string]$OutputRoot = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Port = 18765
$work = $null
$src = $null
$worktreeAdded = $false

function Must-Succeed([string]$Description) {
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit $LASTEXITCODE)." }
}
function Confirm-Operator([string]$Description, [string]$Token) {
    Write-Host ([Environment]::NewLine + $Description) -ForegroundColor Cyan
    if ((Read-Host "Type $Token to attest completion, anything else aborts") -cne $Token) {
        throw "Operator did not attest $Token; no acceptance receipt issued."
    }
}
function Evidence-Path([string]$Description) {
    $answer = (Read-Host "Full path inside $work for $Description").Trim().Trim('"')
    $path = [IO.Path]::GetFullPath($answer)
    $root = [IO.Path]::GetFullPath($work).TrimEnd('\') + '\'
    if (-not $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Evidence must be saved inside the isolated work directory.'
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing file: $Description" }
    return $path
}
function Start-Compose([string]$Python, [string]$SessionName) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) { throw "Local port $Port is already occupied; refusing another server's HTTP response." }
    $log = Join-Path $work "$SessionName-console.txt"
    $child = @'
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath '__WORK__'
Start-Transcript -LiteralPath '__LOG__' -Force | Out-Null
try {
    & '__PYTHON__' -I -m zaaggenz_runtime --workspace compose --no-browser --port __PORT__
    exit $LASTEXITCODE
} finally {
    Stop-Transcript | Out-Null
}
'@
    $child = $child.Replace('__WORK__', $work.Replace("'", "''")).Replace('__LOG__', $log.Replace("'", "''")).Replace('__PYTHON__', $Python.Replace("'", "''")).Replace('__PORT__', [string]$Port)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($child))
    $started = (Get-Date).ToUniversalTime().ToString('o')
    $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($proc.HasExited) { throw "Compose $SessionName process ended before HTTP readiness (exit $($proc.ExitCode))." }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/timeline" -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "Compose $SessionName did not start at loopback HTTP port $Port." }
    Write-Host "Compose ready: http://127.0.0.1:$Port/timeline" -ForegroundColor Green
    Start-Process "http://127.0.0.1:$Port/timeline"
    return @{ process = $proc; started = $started; log = $log }
}
function Finish-Compose($Session, [string]$Name) {
    Confirm-Operator 'In the separate runtime PowerShell console, press Ctrl+C to stop Python normally, then close that console. Do not use Task Manager or window X.' 'CTRL-C-STOPPED'
    if (-not $Session.process.WaitForExit(60000)) { throw "$Name process has not exited; do not force-kill it and claim normal shutdown." }
    if ($Session.process.ExitCode -ne 0) { throw "$Name runtime exit code $($Session.process.ExitCode); preserve console log." }
    if (-not (Test-Path -LiteralPath $Session.log)) { throw "Missing $Name runtime transcript." }
    return @{ ready = $true; process_exited = $true; exit_code = $Session.process.ExitCode;
        operator_attested_ctrl_c = $true; operator_attested_workflow = $true;
        startup_utc = $Session.started; shutdown_utc = (Get-Date).ToUniversalTime().ToString('o');
        console_log_sha256 = (Get-FileHash -LiteralPath $Session.log -Algorithm SHA256).Hash.ToLowerInvariant() }
}
try {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
        throw 'Physical Windows 11 x64 required; hosted CI is not sufficient.'
    }
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    if (-not $os.Caption.Contains('Windows 11')) { throw "Windows 11 required; detected $($os.Caption)." }
    if ($env:GITHUB_ACTIONS -or $env:CI) { throw 'Hosted CI is not physical operator acceptance.' }
    $Repository = (Resolve-Path -LiteralPath $Repository).Path
    & git -C $Repository rev-parse --is-inside-work-tree | Out-Null
    Must-Succeed 'Git checkout check'
    & git -C $Repository cat-file -e ($AcceptedMain + '^{commit}')
    Must-Succeed 'Accepted source commit check'
    $harnessSha = (& git -C $Repository rev-parse HEAD).Trim()
    Must-Succeed 'Harness source commit check'
    & py -3.13 -c 'import sys; assert sys.version_info[:2] == (3, 13) and sys.maxsize > 2**32'
    Must-Succeed '64-bit Python 3.13 preflight'
    if (-not $OutputRoot) { $OutputRoot = Join-Path $env:TEMP ("zg242-" + [guid]::NewGuid().ToString('N')) }
    $work = [IO.Path]::GetFullPath($OutputRoot)
    if (Test-Path -LiteralPath $work) { throw 'OutputRoot must not exist: never overwrite an acceptance run.' }
    New-Item -ItemType Directory -Path $work | Out-Null
    $src = Join-Path $work 'accepted-source'
    $buildVenv = Join-Path $work 'build-venv'
    $installedVenv = Join-Path $work 'installed-venv'
    $dist = Join-Path $work 'dist'
    $snapshot = Join-Path $work 'snapshot-private.json'
    $receipt = Join-Path $work 'receipt-shareable.json'
    $helper = Join-Path $PSScriptRoot 'zg242_receipt.py'
    if (-not (Test-Path -LiteralPath $helper)) { throw 'Matching receipt helper missing from this branch.' }
    Confirm-Operator 'Build pinned accepted source and install Python dependencies locally. No VST or cloud audio calls. Confirm authorised installation.' 'INSTALL-APPROVED'
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    & git -C $Repository worktree add --detach $src $AcceptedMain
    Must-Succeed 'Create temporary accepted-source worktree'
    $worktreeAdded = $true
    Push-Location $src
    try {
        & py -3.13 baseline/recovered_source/materialize_v2.py --out .
        Must-Succeed 'Authenticated recovered source materialization'
        & py -3.13 -m venv $buildVenv
        Must-Succeed 'Build venv creation'
        $builder = Join-Path $buildVenv 'Scripts\python.exe'
        & $builder -m pip install -c constraints/ci.txt -e '.[test]'
        Must-Succeed 'Pinned build dependencies'
        & $builder -m build --wheel --outdir $dist
        Must-Succeed 'Wheel build'
        & $builder tools/artifact_acceptance.py --dist $dist --kind wheel --constraints constraints/ci.txt --report (Join-Path $work 'wheel-acceptance-private.json')
        Must-Succeed 'Wheel artifact smoke'
    } finally { Pop-Location }
    $candidates = @(Get-ChildItem -LiteralPath $dist -Filter '*.whl' -File)
    if ($candidates.Count -ne 1) { throw 'Expected exactly one built wheel.' }
    $wheel = $candidates[0].FullName
    & py -3.13 -m venv $installedVenv
    Must-Succeed 'Independent installed venv creation'
    $python = Join-Path $installedVenv 'Scripts\python.exe'
    & $python -m pip install -c (Join-Path $src 'constraints\ci.txt') $wheel
    Must-Succeed 'Pinned wheel installation'
    $identityScript = @'
import hashlib, importlib.metadata, json, pathlib, platform, sys
from zaaggenz_timeline.server import ROOT
from zaaggenz_web_release import build_web_releases
import zaaggenz_runtime.server as backend
root = pathlib.Path(ROOT).resolve()
if not root.is_relative_to(pathlib.Path(sys.prefix).resolve()):
    raise RuntimeError('runtime loaded outside installed wheel venv')
releases = build_web_releases(root, unified_runtime=True)
assert set(releases) == {'timeline', 'listening', 'inspector', 'vocal'}
print(json.dumps({'schema': 'zg242-installed-identity-v1',
  'package_version': importlib.metadata.version('zaaggenz'),
  'python_version': platform.python_version(), 'windows_version': platform.version(),
  'architecture': platform.machine(),
  'release_ids': {k: v.release_id for k,v in releases.items()},
  'backend_sha256': hashlib.sha256(pathlib.Path(backend.__file__).read_bytes()).hexdigest(),
  'timeline_html_sha256': hashlib.sha256((root/'web'/'timeline'/'index.html').read_bytes()).hexdigest()}))
'@
    $identityRaw = & $python -I -c $identityScript
    Must-Succeed 'Installed release identity'
    $identity = $identityRaw | ConvertFrom-Json
    if ($identity.schema -ne 'zg242-installed-identity-v1') { throw 'Missing installed release identity.' }
    $identityRaw | Set-Content -LiteralPath (Join-Path $work 'identity.json') -Encoding UTF8
    Write-Host ([Environment]::NewLine + "Acceptance evidence directory: $work") -ForegroundColor Yellow
    Write-Host 'Save all screenshots, project, rack preset and WAVs into that directory.'
    $one = Start-Compose $python 'first'
    Confirm-Operator 'FIRST SESSION: accepted source working copy, enabled four-band rack, upper-band spectral tune and compression, reorder, insert/band/global bypass and A/B, save project and named rack preset, preview, export before.wav/dry.wav/bypass.wav, rapid edit/cancel, screenshot.' 'FIRST-WORKFLOW-DONE'
    $project = Evidence-Path 'saved project'
    $preset = Evidence-Path 'saved named rack preset'
    $before = Evidence-Path 'before.wav (processed)'
    $dry = Evidence-Path 'dry.wav (rack disabled)'
    $bypass = Evidence-Path 'bypass.wav (all-rack bypass)'
    $screenshotOne = Evidence-Path 'first-session PNG/JPEG screenshot'
    & $python -I $helper snapshot --project $project --preset $preset --before $before --dry $dry --bypass $bypass --screenshot-first $screenshotOne --wheel $wheel --accepted-main-sha $AcceptedMain --harness-sha $harnessSha --output $snapshot
    Must-Succeed 'Initial snapshot: identity and dry/bypass PCM'
    $stageOne = Finish-Compose $one 'first'
    $two = Start-Compose $python 'second'
    Confirm-Operator 'SECOND SESSION: reopen saved project and rack preset from disk, verify controls/order/revisions and preview, export after.wav with identical recipe and range, screenshot. Do not edit saved files.' 'SECOND-WORKFLOW-DONE'
    $after = Evidence-Path 'after.wav (reopened processed export)'
    $screenshotTwo = Evidence-Path 'reopened-session PNG/JPEG screenshot'
    $stageTwo = Finish-Compose $two 'second'
    $sessions = Join-Path $work 'sessions-private.json'
    @{ schema = 'zg242-physical-session-v1'; stages = @($stageOne, $stageTwo) } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $sessions -Encoding UTF8
    & $python -I $helper finalize --snapshot $snapshot --sessions $sessions --identity (Join-Path $work 'identity.json') --project $project --preset $preset --before $before --after $after --dry $dry --bypass $bypass --screenshot-second $screenshotTwo --wheel $wheel --output $receipt
    Must-Succeed 'Final operator receipt validation'
    Write-Host ([Environment]::NewLine + "OPERATOR EVIDENCE READY (NOT ACCEPTED): $receipt") -ForegroundColor Green
} catch {
    if ($work -and (Test-Path -LiteralPath $work)) {
        $sanitized = $_.Exception.Message.Replace($Repository, '<repo>').Replace($work, '<work>')
        "First failure: $sanitized" | Set-Content -LiteralPath (Join-Path $work 'first-failure.txt') -Encoding UTF8
        Write-Warning "Acceptance NOT complete. Evidence preserved in $work"
    }
    throw
} finally {
    if ($worktreeAdded) {
        & git -C $Repository worktree remove --force $src 2>$null | Out-Null
    }
}
