# Start the stack with the BRAIN on Gemini and everything else local.
#
# Only the language model moves. CosyVoice, RVC, the guards, life.json, the room UI and every
# piece of post-processing stay on this machine, so her voice never leaves it -- which matters,
# because that voice is a real person's and the consent note in profile.json is written on that
# basis. What leaves the machine is the text of a viewer's comment.
#
# Why this is worth doing, measured on this box:
#
#   * The 7B holds 4.7 GB of VRAM, and that makes the VOICE 2.2x slower and erratic:
#     RTF 1.93 (0.84-2.81) with it resident, 0.87 (0.83-0.94) without. Moving the brain off
#     frees the card permanently. That is worth ~8-10 s a reply -- far more than the ~0.45 s
#     the local model spends thinking.
#   * Long Traditional-Chinese replies still degrade on a 7B. Two retrains and 105 targeted
#     pairs did not fix it. That is the actual reason to move, not the latency.
#
# What it costs: the fine-tune does not come along. KOL_LLM_TUNED is therefore set to 0 below,
# which is the single most important line in this file -- see the note there.
#
#   .\RUN-GEMINI.ps1                 start against Gemini
#   .\RUN-TUNED.ps1                  start against the local fine-tune (unchanged)
param([switch]$Stop)

$Root = $PSScriptRoot

# Load the key from the gitignored secrets file, if it is there. Dot-sourced rather than
# parsed, so it can also set the model or anything else without this script knowing about it.
$secrets = Join-Path $Root "secrets.local.ps1"
if (Test-Path $secrets) { . $secrets }

if ($env:GEMINI_API_KEY -eq "PASTE_YOUR_KEY_HERE") {
  Write-Host "secrets.local.ps1 still has the placeholder in it." -ForegroundColor Yellow
  Write-Host "  Open it, paste the real key, save, and run this again."
  exit 1
}

if (-not $env:GEMINI_API_KEY) {
  Write-Host "GEMINI_API_KEY is not set." -ForegroundColor Yellow
  Write-Host "  `$env:GEMINI_API_KEY = 'your-key'   then run this again."
  Write-Host "  The key is read from the environment and never written to disk by this script."
  exit 1
}

$env:KOL_LLM_API_KEY = $env:GEMINI_API_KEY
$env:OLLAMA_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
if (-not $env:KOL_LLM_MODEL) { $env:KOL_LLM_MODEL = "gemini-2.0-flash" }

# THE LINE THAT MATTERS.
#
# KOL_LLM_TUNED=1 tells build_system_prompt to send the SHORT prompt -- name, languages, rules --
# because with the local adapter the character is in the weights. Gemini has no adapter. Leaving
# this at 1 would ship a model that has never heard of Sofia Hsu and is told almost nothing about
# her, and the replies would be a generic assistant wearing her name.
#
# 0 sends the full character sheet built from profile.json instead. Larger models follow a long
# persona prompt far better than a 7B does, which is what makes this trade viable at all.
$env:KOL_LLM_TUNED = "0"

# Let the local model fall out of VRAM. This is where the latency win actually comes from.
& ollama stop sofia-hsu-tuned 2>&1 | Out-Null

Write-Host "brain:  Gemini ($env:KOL_LLM_MODEL), full persona prompt" -ForegroundColor Cyan
Write-Host "voice:  local (CosyVoice + RVC), unchanged"
Write-Host "guards: local (prices, links, address, AI denial, privacy, assistant tone)"
Write-Host ""

& (Join-Path $Root "RUN-TUNED.ps1") -KeepEnv @PSBoundParameters
