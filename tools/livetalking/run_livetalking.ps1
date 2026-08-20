# Launch LiveTalking for one KOL, speaking in that KOL's fine-tuned GPT-SoVITS voice.
#
# Reads kols/<id>/profile.json -> ai_assets.voice for the reference clip + text, so the
# avatar's voice always matches whatever train_gptsovits.py produced. GPT-SoVITS's
# api_v2 must already be serving (LiveTalking calls it over HTTP for every utterance --
# api_v2 IS the cloned voice; without it the avatar falls back to a generic timbre).
#
#   .\tools\livetalking\run_livetalking.ps1 lena-chen
#   .\tools\livetalking\run_livetalking.ps1 lena-chen -Transport virtualcam
#
# Then open http://127.0.0.1:8010/webrtcapi.html and type text.

Param(
    [Parameter(Mandatory = $true)][string]$KolId,
    [string]$AvatarId = "",
    [ValidateSet("webrtc", "rtcpush", "rtmp", "virtualcam")][string]$Transport = "webrtc",
    [ValidateSet("wav2lip", "musetalk", "ultralight")][string]$Model = "wav2lip",
    [int]$ListenPort = 8010,
    [string]$TtsServer = "",
    [int]$BatchSize = 4,
    [string]$LlmModel = ""
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$LT = Join-Path $Repo "LiveTalking"
$py = Join-Path $LT ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) { throw "LiveTalking venv missing: $py" }

# ---- pull the voice config out of the KOL profile -------------------------------
$profilePath = Join-Path $Repo "kols\$KolId\profile.json"
if (-not (Test-Path $profilePath)) { throw "no profile: $profilePath" }
$profile = Get-Content $profilePath -Raw -Encoding UTF8 | ConvertFrom-Json
$voice = $profile.ai_assets.voice
if (-not $voice) { throw "$KolId has no ai_assets.voice block" }

# Which TTS plugin LiveTalking should load. It ships one per engine; "gpt-sovits" is the
# default here, and a KOL whose profile names CosyVoice 2 gets LiveTalking's own "cosyvoice"
# plugin pointed at tools/voice_eval/cosy_server.py.
#
# That plugin only knows `inference_zero_shot` — it has no field for a delivery instruction —
# so cosy_server resolves the character from the reference clip it is handed and applies
# whatever mode the profile declares. sofia-hsu is on `instruct`, so the avatar speaks in
# the same voice as the studio rather than the flatter zero-shot one. Nothing inside
# LiveTalking is patched for this.
$TtsPlugin = "gpt-sovits"
$HealthPath = "/docs"
if ($voice.engine -eq "cosyvoice2") {
    $TtsPlugin = "cosyvoice"
    $HealthPath = "/health"
    Write-Host "[note] $KolId uses CosyVoice 2 ($($voice.mode) mode) — routing the avatar through it." -ForegroundColor Cyan
} elseif ($voice.engine -and $voice.engine -ne "gpt-sovits") {
    if ($voice.gpt_sovits_previous) {
        Write-Host "[note] $KolId uses '$($voice.engine)', which LiveTalking cannot drive; " -ForegroundColor Yellow -NoNewline
        Write-Host "falling back to its GPT-SoVITS voice." -ForegroundColor Yellow
        $voice = $voice.gpt_sovits_previous
    } else {
        throw "$KolId uses engine '$($voice.engine)', which LiveTalking cannot drive, and has no gpt_sovits_previous fallback."
    }
}

$refRel = $voice.reference_audio
if (-not $refRel) { throw "$KolId has no ai_assets.voice.reference_audio - run bootstrap_timbre.py" }
$refFile = Join-Path $Repo ($refRel -replace '/', '\')
if (-not (Test-Path $refFile)) { throw "reference audio missing: $refFile" }
$refText = $voice.reference_text
if (-not $refText) { throw "$KolId has no ai_assets.voice.reference_text" }
if (-not $TtsServer) {
    $TtsServer = if ($voice.api) { $voice.api } else { "http://127.0.0.1:9880" }
}

# A zero-shot CosyVoice voice is the intended configuration, not a degraded one, so only
# warn about status when the engine actually expects fine-tuned weights.
if ($TtsPlugin -eq "gpt-sovits" -and $voice.status -ne "finetuned") {
    Write-Host "[warn] ai_assets.voice.status = '$($voice.status)' (expected 'finetuned'); " -ForegroundColor Yellow -NoNewline
    Write-Host "the avatar may not use a cloned voice." -ForegroundColor Yellow
}

# ---- the TTS server must be up: it is where the cloned voice lives --------------
try {
    $null = Invoke-WebRequest -Uri "$TtsServer$HealthPath" -TimeoutSec 5 -UseBasicParsing
    Write-Host "[ok]  $TtsPlugin reachable at $TtsServer" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] $TtsPlugin is NOT reachable at $TtsServer" -ForegroundColor Red
    Write-Host "       LiveTalking calls it per utterance; without it you get a generic voice." -ForegroundColor Red
    Write-Host "       Start it with:" -ForegroundColor Red
    if ($TtsPlugin -eq "cosyvoice") {
        Write-Host "         CosyVoice\.venv\Scripts\python.exe tools\voice_eval\cosy_server.py"
    } else {
        Write-Host "         cd GPT-SoVITS; .\.venv\Scripts\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml"
    }
    throw "$TtsPlugin not reachable"
}

# ---- model + avatar assets -----------------------------------------------------
$modelFile = Join-Path $LT "models\wav2lip.pth"
if ($Model -eq "wav2lip" -and -not (Test-Path $modelFile)) {
    throw "missing $modelFile (copy wav2lip256.pth there and rename it)"
}
# The avatar comes from the KOL's own profile unless one is named on the command line. It used
# to default to `wav2lip256_avatar1`, the sample shipped with LiveTalking — which meant the
# obvious invocation (`run_livetalking.ps1 sofia-hsu`) started her voice behind a stranger's
# face, and did so silently. The profile already records which avatar is hers; the sample has
# been deleted, and nothing should point at it by default.
if (-not $AvatarId) {
    $AvatarId = $profile.ai_assets.avatar.avatar_id
    if (-not $AvatarId) {
        throw "$KolId has no ai_assets.avatar.avatar_id - build one with tools\livetalking\build_avatar.py, or pass -AvatarId"
    }
}
$avatarDir = Join-Path $LT "data\avatars\$AvatarId"
if (-not (Test-Path $avatarDir)) {
    throw "missing avatar: $avatarDir (build it with: LiveTalking\.venv\Scripts\python.exe tools\livetalking\build_avatar.py $KolId)"
}

# ---- environment ---------------------------------------------------------------
# torchaudio 2.11 decodes via torchcodec, which needs the FFmpeg *shared* DLLs;
# the static Gyan build satisfies CLI callers but not this one.
$shared = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter "avcodec*.dll" -ErrorAction SilentlyContinue |
          Select-Object -First 1
if ($shared) { $env:PATH = "$($shared.DirectoryName);$env:PATH" }

# Send text as "auto" so GPT-SoVITS detects language per segment -- required for a
# bilingual KOL. prompt_lang must match the language spoken in the reference clip.
$env:GSV_TEXT_LANG = "auto"
$env:GSV_PROMPT_LANG = if ($voice.reference_lang) { $voice.reference_lang } else { "zh" }

# Which persona the LLM should answer as (used by /human type=chat -> llm.py ->
# tools/livetalking/persona_brain.py, which builds the prompt from profile.json).
$env:KOL_ID = $KolId
if ($LlmModel) { $env:KOL_LLM_MODEL = $LlmModel }

Write-Host ""
Write-Host "KOL        : $KolId" -ForegroundColor Cyan
Write-Host "avatar     : $AvatarId ($Model)" -ForegroundColor Cyan
Write-Host "TTS        : $TtsPlugin @ $TtsServer" -ForegroundColor Cyan
Write-Host "ref clip   : $refFile" -ForegroundColor Cyan
Write-Host "ref text   : $refText" -ForegroundColor Cyan
Write-Host "text lang  : $($env:GSV_TEXT_LANG)  (prompt: $($env:GSV_PROMPT_LANG))" -ForegroundColor Cyan
Write-Host "transport  : $Transport  ->  http://127.0.0.1:$ListenPort/webrtcapi.html" -ForegroundColor Cyan
Write-Host ""

Push-Location $LT
try {
    & $py app.py `
        --transport $Transport `
        --model $Model `
        --avatar_id $AvatarId `
        --tts $TtsPlugin `
        --REF_FILE $refFile `
        --REF_TEXT $refText `
        --TTS_SERVER $TtsServer `
        --listenport $ListenPort `
        --batch_size $BatchSize
} finally {
    Pop-Location
}
