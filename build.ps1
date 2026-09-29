param(
    [Parameter(Mandatory = $true)]
    [string] $WorkRoot,
    [string] $PackageIndex
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$work = [System.IO.Path]::GetFullPath($WorkRoot)
if ($work -eq $root -or $work.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Choose a dedicated build directory outside the source tree.'
}

$venv = Join-Path $work '.venv'
$temp = Join-Path $work 'temp'
$dist = Join-Path $work 'dist'
$build = Join-Path $work 'build'
$spec = Join-Path $work 'spec'
$cache = Join-Path $work 'pyinstaller-cache'
$exe = Join-Path $dist 'CodexBrowserUnlocker.exe'
if (Test-Path -LiteralPath $exe) {
    throw "Existing EXE will not be overwritten: $exe"
}
foreach ($dir in @($work, $temp, $dist, $build, $spec, $cache)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$oldCache = $env:PYINSTALLER_CONFIG_DIR
try {
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:PYINSTALLER_CONFIG_DIR = $cache
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    $python = Join-Path $venv 'Scripts\python.exe'
    $pipArgs = @('-m', 'pip', 'install', '--no-cache-dir', '--disable-pip-version-check',
        '--no-input', '--report', (Join-Path $work 'pip-report.json'))
    if ($PackageIndex) {
        $pipArgs += @('--index-url', $PackageIndex)
    }
    $pipArgs += @('-r', (Join-Path $root 'requirements-build.txt'))
    & $python @pipArgs
    if ($LASTEXITCODE -ne 0) { throw 'Isolated PyInstaller installation failed.' }
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name CodexBrowserUnlocker `
        --add-data "$root\require-identification.mjs;." `
        --distpath $dist --workpath $build --specpath $spec `
        (Join-Path $root 'browser_unlocker_gui.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
}
finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    $env:PYINSTALLER_CONFIG_DIR = $oldCache
}
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Expected executable is missing: $exe"
}
Write-Output $exe
