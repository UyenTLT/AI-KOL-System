# Download + place the GPT-SoVITS pretrained models without conda.
#
# Mirrors what GPT-SoVITS/install.ps1 does (same URLs, same destinations) but uses
# curl.exe instead of Invoke-WebRequest (much faster on multi-GB files) and skips
# the conda step, which install.ps1 only uses for `ffmpeg cmake`.
#
#   .\tools\voice_crawl\fetch_gptsovits_models.ps1 [-Source HF|HF-Mirror|ModelScope] [-DownloadUVR5]

Param(
    [ValidateSet("HF", "HF-Mirror", "ModelScope")][string]$Source = "HF",
    [switch]$DownloadUVR5
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$GSV  = Join-Path $Repo "GPT-SoVITS"

switch ($Source) {
    "HF"          { $Base = "https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main" }
    "HF-Mirror"   { $Base = "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main" }
    "ModelScope"  { $Base = "https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master" }
}

function Get-Archive($Name, $DestDir, $MarkerPath) {
    if (Test-Path $MarkerPath) {
        Write-Host "[skip] $Name already present" -ForegroundColor DarkGray
        return
    }
    $zip = Join-Path $GSV $Name
    Write-Host "[get ] $Name" -ForegroundColor Cyan
    # pretrained_models.zip is ~4.2 GB and HF regularly drops the connection
    # mid-transfer. `--retry` alone restarts from zero, so `-C -` (resume from
    # wherever the partial file stopped) is what actually makes this finish.
    # Retry the whole curl a few times since a dropped stream exits non-zero.
    $ok = $false
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        & curl.exe -L --fail --retry 5 --retry-delay 5 --retry-connrefused `
                   -C - --speed-limit 1024 --speed-time 60 -o $zip "$Base/$Name"
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
        $have = if (Test-Path $zip) { "{0:N0} MB so far" -f ((Get-Item $zip).Length/1MB) } else { "nothing yet" }
        Write-Host "[retry] attempt $attempt failed (curl $LASTEXITCODE), $have - resuming" -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
    if (-not $ok) { throw "download failed after retries: $Name" }
    Write-Host "[unzip] -> $DestDir" -ForegroundColor Cyan
    Expand-Archive -Path $zip -DestinationPath $DestDir -Force
    Remove-Item $zip -Force
}

Set-Location $GSV

Get-Archive "pretrained_models.zip" (Join-Path $GSV "GPT_SoVITS") (Join-Path $GSV "GPT_SoVITS\pretrained_models\sv")
Get-Archive "G2PWModel.zip" (Join-Path $GSV "GPT_SoVITS\text") (Join-Path $GSV "GPT_SoVITS\text\G2PWModel")

if ($DownloadUVR5) {
    Get-Archive "uvr5_weights.zip" (Join-Path $GSV "tools") (Join-Path $GSV "tools\uvr5\uvr5_weights")
}

# NLTK data belongs inside the venv prefix so only this env sees it.
$venvPy = Join-Path $GSV ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $prefix = (& $venvPy -c "import sys; print(sys.prefix)").Trim()
    Get-Archive "nltk_data.zip" $prefix (Join-Path $prefix "nltk_data")
} else {
    Write-Host "[warn] GPT-SoVITS\.venv not found - skipping NLTK data" -ForegroundColor Yellow
}

Write-Host "`nDone. Model tree:" -ForegroundColor Green
Get-ChildItem (Join-Path $GSV "GPT_SoVITS\pretrained_models") -ErrorAction SilentlyContinue |
    Select-Object -First 20 Name, Length | Format-Table -AutoSize
