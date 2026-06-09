param(
  [string]$Python = "python",
  [ValidateSet("auto", "cpu", "default", "cu121", "cu124", "cu126", "skip")]
  [string]$Torch = "auto",
  [string]$Target = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "setup_locate_worker.py"
$Args = @($Script, "--torch", $Torch)
if ($Target -ne "") {
  $Args += @("--target", $Target)
}
if ($Force) {
  $Args += "--force"
}

Write-Host "Running THEIA LocateAnything worker setup..."
& $Python @Args

Write-Host ""
Write-Host "THEIA auto-discovers the default worker venv."
Write-Host "Only set COMPUTER_USE_LOCATE_PYTHON if you use a custom worker interpreter."
