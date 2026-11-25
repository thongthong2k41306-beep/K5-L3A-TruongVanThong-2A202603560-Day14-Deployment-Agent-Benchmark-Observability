param(
    [ValidateSet('core', 'gateway', 'observability')]
    [string]$Profile = 'core'
)
$projectRoot = Split-Path -Parent $PSScriptRoot
$wslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'
& $wslPath -d Ubuntu-24.04 --cd $projectRoot --exec env "DAY14_PROFILE=$Profile" bash --rcfile scripts/lab-shell.bash -i
exit $LASTEXITCODE
