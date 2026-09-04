# Runs main.py or app.py using the global Python interpreter with the venv's
# packages on PYTHONPATH, instead of the venv's own copied python.exe.
#
# Some Windows security policies (e.g. Smart App Control, or a corporate
# application-control policy) block the python.exe that `python -m venv`
# copies into .venv\Scripts, even though the original interpreter it was
# copied from is allowed to run. This works around that without touching
# any security settings - it just avoids executing the blocked copy.
#
# Usage:
#   .\run.ps1          # runs main.py (CLI)
#   .\run.ps1 app      # runs app.py (website)

param(
    [ValidateSet("main", "app")]
    [string]$Target = "main"
)

$ProjectRoot = $PSScriptRoot
$env:PYTHONPATH = "$ProjectRoot\.venv\Lib\site-packages"
$env:PYTHONUTF8 = "1"

$GlobalPython = Get-Command python.exe -All -ErrorAction SilentlyContinue |
    Where-Object { $_.Source -notlike "*\.venv\*" } |
    Select-Object -First 1 -ExpandProperty Source

if (-not $GlobalPython) {
    Write-Error "Could not find a Python interpreter outside of .venv. Is Python installed and on PATH?"
    exit 1
}

& $GlobalPython "$ProjectRoot\$Target.py"
