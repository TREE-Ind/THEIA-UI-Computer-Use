param([string]$Python = "python")
$ErrorActionPreference = "Stop"
& $Python -m pip install -r (Join-Path $PSScriptRoot "..\requirements-basic.txt")
& $Python (Join-Path $PSScriptRoot "doctor.py")
