param(
  [string]$Python = "python",
  [ValidateSet("cpu", "cu121", "cu124", "skip")]
  [string]$Cuda = "skip",
  [string]$Target = "$env:LOCALAPPDATA\hermes\windows-computer-use\.venv"
)

$ErrorActionPreference = "Stop"
Write-Host "Creating isolated LocateAnything worker venv at $Target"
& $Python -m venv $Target
$VenvPython = Join-Path $Target "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel

if ($Cuda -eq "cpu") {
  & $VenvPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
} elseif ($Cuda -eq "cu121") {
  & $VenvPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
} elseif ($Cuda -eq "cu124") {
  & $VenvPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
} else {
  Write-Host "Skipping torch install. Install torch/torchvision manually if needed."
}

& $VenvPython -m pip install -r (Join-Path $PSScriptRoot "..\requirements-locate.txt")

Write-Host ""
Write-Host "Set these environment variables, then restart Hermes:"
Write-Host "setx COMPUTER_USE_LOCATE_BACKEND external"
Write-Host "setx COMPUTER_USE_LOCATE_PYTHON `"$VenvPython`""
Write-Host "setx COMPUTER_USE_LOCATE_PERSISTENT true"
