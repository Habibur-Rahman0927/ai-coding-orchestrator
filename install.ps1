$ErrorActionPreference = 'Stop'
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Python 3.8 or newer is required; install Python and add it to PATH.' }
& $python.Source -B -I (Join-Path $PSScriptRoot 'engine/lib/ccx_install.py') install @args
exit $LASTEXITCODE
