# Start the whole stack against the fine-tuned persona model.
#
# The three environment variables are the entire switch. Every server reads them at import, so
# starting them from here is what makes the difference — set nothing and the same servers run
# against stock Ollama exactly as before.
#
#   .\RUN-TUNED.ps1            start everything
#   .\RUN-TUNED.ps1 -Base      start against stock Ollama instead, for comparison
param([switch]$Base, [switch]$Stop)

$Root = $PSScriptRoot
$Py   = Join-Path $Root ".venv\Scripts\python.exe"
$FtPy = Join-Path $Root "finetune\.venv\Scripts\python.exe"
$CvPy = Join-Path $Root "CosyVoice\.venv\Scripts\python.exe"
$RvPy = Join-Path $Root "RVC\.venv\Scripts\python.exe"

# port, label, python, script, needs the tuned brain
# The fine-tune is served by Ollama now, not by tools/llm_train/serve.py. Same weights, merged
# and quantised to q4_K_M: measured 30.7 tokens per second against 12-14 through transformers
# 4-bit, which is 1.06 s a reply instead of 2.56. serve.py still works and is still the fastest
# way to try a fresh adapter without exporting, but it is not what production should run.
$Services = @(
  @{ Port=9881;  Name="CosyVoice";  Py=$CvPy; Script="tools\voice_eval\cosy_server.py"; Brain=$false; Ready=20 },
  # The timbre pass. Without it she still speaks, but in the zero-shot voice rather than the
  # trained one -- a warning on stdout and nothing louder, so it is easy to miss that she has
  # quietly reverted. Slow to come up: it loads the model and then converts once at startup, so
  # that the first viewer question does not pay the 4.6 s the first conversion costs.
  @{ Port=9882;  Name="RVC voice";  Py=$RvPy; Script="tools\voice_eval\rvc_server.py"; Brain=$false; Ready=90 },
  @{ Port=8777;  Name="Livestream"; Py=$Py;   Script="tools\livestream\server.py";      Brain=$true  },
  @{ Port=8779;  Name="Chat 1:1";   Py=$Py;   Script="tools\chat\server.py";            Brain=$true  },
  @{ Port=8778;  Name="RVC demo";   Py=$Py;   Script="tools\voice_eval\rvc_demo.py";    Brain=$false },
  @{ Port=8776;  Name="Studio demo";Py=$Py;   Script="tools\studio\demo_server.py";     Brain=$false }
)

function Stop-Port([int]$Port) {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($c) {
    $c | Select-Object -Expand OwningProcess -Unique | ForEach-Object {
      Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    # A port killed and rebound within a second leaves the old socket accepting and never
    # answering, which looks exactly like a hung server. This cost an hour once; the wait is
    # cheaper than the confusion.
    Start-Sleep -Seconds 3
  }
}

if ($Stop) {
  foreach ($s in $Services) { Stop-Port $s.Port; "stopped $($s.Name)" }
  exit 0
}

if ($Base) {
  Remove-Item Env:\OLLAMA_BASE_URL, Env:\KOL_LLM_TUNED, Env:\KOL_LLM_MODEL -ErrorAction SilentlyContinue
  "brain: stock Ollama (base model, full persona prompt)"
} else {
  $env:OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
  $env:KOL_LLM_TUNED   = "1"
  $env:KOL_LLM_MODEL   = "sofia-vargas-tuned"
  "brain: fine-tuned q4_K_M through Ollama (short prompt, rules kept)"
}

foreach ($s in $Services) {
  if (-not (Test-Path $s.Py))                     { "  {0,-12} skipped - no venv at {1}" -f $s.Name, $s.Py; continue }
  if (-not (Test-Path (Join-Path $Root $s.Script))) { "  {0,-12} skipped - no {1}" -f $s.Name, $s.Script; continue }
  Stop-Port $s.Port
  Start-Process $s.Py -ArgumentList $s.Script -WorkingDirectory $Root -WindowStyle Hidden
  "  {0,-12} starting on {1}" -f $s.Name, $s.Port
}

"waiting for them to come up..."
foreach ($s in $Services) {
  if ($s.Port -eq 9881 -or $s.Port -eq 9882) { $url = "http://127.0.0.1:$($s.Port)/health" }
  else { $url = "http://127.0.0.1:$($s.Port)/" }
  # Poll rather than sleep a flat 12 seconds. The voice servers load models and one of them
  # warms itself up, so a single early check reports them broken when they are only slow.
  if ($s.Ready) { $budget = $s.Ready } else { $budget = 15 }
  $st = "not answering yet"
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt $budget) {
    try {
      $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5
      $st = "HTTP $($r.StatusCode) after $([int]((Get-Date) - $t0).TotalSeconds)s"
      break
    } catch { Start-Sleep -Seconds 2 }
  }
  "  {0,-12} {1,-22} {2}" -f $s.Name, "http://127.0.0.1:$($s.Port)", $st
}
""
"Sofia speaks through CosyVoice, then RVC replaces the timbre with her trained voice."
"If RVC voice is not up she still talks, in the zero-shot voice, and only its log says so."
