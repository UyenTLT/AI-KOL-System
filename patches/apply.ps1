# Re-apply the local edits to the gitignored third-party engines.
#
# GPT-SoVITS/ and LiveTalking/ are not version-controlled here (multi-GB with weights), so
# edits inside them would otherwise be lost on a fresh clone -- and without them nothing
# works: GPT-SoVITS training segfaults immediately, and the avatar loses its voice and
# persona. See README.md in this folder for what each patch does and why.
#
#   .\patches\apply.ps1            apply everything (idempotent)
#   .\patches\apply.ps1 -Check     report only

Param([switch]$Check)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

$Jobs = @(
    @{ Name = "GPT-SoVITS single-GPU / Windows fixes"
       Dir  = "GPT-SoVITS"
       Patch = "gpt-sovits-windows-single-gpu.patch" }
    @{ Name = "LiveTalking persona brain + bilingual TTS"
       Dir  = "LiveTalking"
       Patch = "livetalking-persona-and-bilingual.patch" }
)

$fail = 0
foreach ($j in $Jobs) {
    $dir = Join-Path $Repo $j.Dir
    $patch = Join-Path $PSScriptRoot $j.Patch
    Write-Host "`n== $($j.Name)" -ForegroundColor Cyan

    if (-not (Test-Path $dir)) {
        Write-Host "   SKIP - $($j.Dir) is not cloned yet" -ForegroundColor Yellow
        continue
    }
    if (-not (Test-Path (Join-Path $dir ".git"))) {
        Write-Host "   SKIP - $($j.Dir) is not a git clone, cannot apply safely" -ForegroundColor Yellow
        continue
    }

    Push-Location $dir
    try {
        # --reverse --check succeeding means the patch is already in the tree.
        & git apply --reverse --check $patch 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   already applied" -ForegroundColor Green
            continue
        }
        & git apply --check $patch 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "   CANNOT APPLY cleanly (upstream moved?). Re-create it, or apply by hand." -ForegroundColor Red
            Write-Host "   patch: $patch"
            $fail++
            continue
        }
        if ($Check) {
            Write-Host "   would apply cleanly" -ForegroundColor Yellow
            continue
        }
        & git apply $patch
        if ($LASTEXITCODE -eq 0) { Write-Host "   applied" -ForegroundColor Green }
        else { Write-Host "   FAILED" -ForegroundColor Red; $fail++ }
    } finally {
        Pop-Location
    }
}

# The filtered requirements file is a copy, not a diff.
$req = Join-Path $Repo "GPT-SoVITS\requirements-win-zhen.txt"
$src = Join-Path $PSScriptRoot "gpt-sovits-requirements-win-zhen.txt"
Write-Host "`n== GPT-SoVITS filtered requirements" -ForegroundColor Cyan
if (-not (Test-Path (Split-Path $req))) {
    Write-Host "   SKIP - GPT-SoVITS is not cloned yet" -ForegroundColor Yellow
} elseif ($Check) {
    if (Test-Path $req) { Write-Host "   present" -ForegroundColor Green }
    else { Write-Host "   would copy" -ForegroundColor Yellow }
} else {
    Copy-Item $src $req -Force
    Write-Host "   copied -> GPT-SoVITS\requirements-win-zhen.txt" -ForegroundColor Green
}

Write-Host ""
if ($fail) {
    Write-Host "$fail patch(es) need attention." -ForegroundColor Red
    exit 1
}
Write-Host "All patches accounted for." -ForegroundColor Green
Write-Host "Reminder: also run tools\voice_crawl\install_jieba_fast_shim.py in the GPT-SoVITS venv."
