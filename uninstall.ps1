$ErrorActionPreference = 'Stop'
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Python 3.8 or newer is required.' }
$installer = Join-Path $PSScriptRoot 'lib/ccx_install.py'
if (-not (Test-Path -LiteralPath $installer)) {
    $installer = Join-Path $PSScriptRoot 'engine/lib/ccx_install.py'
}
& $python.Source -B -I $installer uninstall @args
exit $LASTEXITCODE
