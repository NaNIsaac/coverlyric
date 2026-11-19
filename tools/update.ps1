# Started by 업데이트.bat: replaces the program files with the newest version from GitHub and keeps
# everything the user made. Only Windows' own tools are used (Invoke-WebRequest, .NET's ZipFile).

# Never touched by an update: videos, the project being worked on, the chosen video folder, the log,
# the Python environment and earlier backups. Downloaded models and uv's cache live outside the
# program folder.
$KeepPaths = @(
    '만든 영상', '작업 중', 'settings.json', 'coverlyric.log', 'coverlyric.log.1', '.venv',
    '업데이트 백업'
)

# The program files: what the ZIP from GitHub holds at its top. A name a newer version adds is a
# program file too, so the list is the one below together with the new version's top-level names.
$ProgramPaths = @(
    '가사영상 만들기.bat', '업데이트.bat', 'README.md', 'README.en.md', 'LICENSE', 'pyproject.toml',
    'uv.lock', 'src', 'tools', 'docs', 'tests', '.github', '.gitattributes', '.gitignore',
    '.conventions.toml'
)

# The top-level names an update replaces: the program files above and those of the new version,
# never one of $KeepPaths.
function Get-ProgramPaths([string]$new) {
    $names = @($ProgramPaths) + @(Get-ChildItem -LiteralPath $new -Force | ForEach-Object Name)
    $names | Where-Object { $_ -and $KeepPaths -notcontains $_ } | Select-Object -Unique
}

# The version in a program folder's pyproject.toml, or '?' when it has none.
function Get-ProgramVersion([string]$root) {
    $file = Join-Path $root 'pyproject.toml'
    if (-not (Test-Path -LiteralPath $file)) { return '?' }
    foreach ($line in [IO.File]::ReadAllLines($file)) {
        if ($line -match '^version\s*=\s*"([^"]+)"') { return $Matches[1] }
    }
    '?'
}

# Moves the program files of $root into $backup, then copies those of $new into $root, adding each
# name to $copied once it is copied, so a failure part way can be undone by Restore-Program.
function Install-Program([string]$root, [string]$new, [string]$backup, $copied) {
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach ($name in Get-ProgramPaths $new) {
        $path = Join-Path $root $name
        if (Test-Path -LiteralPath $path) {
            Move-Item -LiteralPath $path -Destination (Join-Path $backup $name)
        }
    }
    foreach ($item in Get-ChildItem -LiteralPath $new -Force) {
        if ($KeepPaths -contains $item.Name) { continue }
        $copied.Add($item.Name)
        Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $root $item.Name) -Recurse
    }
}

# Undoes a failed Install-Program: the new files copied so far go, and everything moved into $backup
# returns. Files never moved stay where they are.
function Restore-Program([string]$root, [string]$backup, $copied) {
    foreach ($name in $copied) {
        $path = Join-Path $root $name
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
    foreach ($item in Get-ChildItem -LiteralPath $backup -Force) {
        $path = Join-Path $root $item.Name
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
        Move-Item -LiteralPath $item.FullName -Destination $path
    }
}

# A Python started from this folder's environment: the page is running.
function Test-ProgramRunning([string]$root) {
    $venv = (Join-Path $root '.venv') + '\'
    $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv, 'OrdinalIgnoreCase') }
    [bool]$running
}

# Dot-sourced by the tests for the functions above.
if ($MyInvocation.InvocationName -eq '.') { return }

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'coverlyric 업데이트'
$root = Split-Path -Parent $PSScriptRoot
# A local ZIP instead of the download, for a test of the whole update.
$zip = $env:COVERLYRIC_UPDATE_ZIP
$url = 'https://github.com/NaNIsaac/coverlyric/archive/refs/heads/main.zip'

if (Test-ProgramRunning $root) {
    Write-Host '프로그램이 실행 중입니다. 페이지의 [끝내기]를 누르거나 터미널 창을 닫은 뒤 다시 실행합니다.'
    exit 1
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$temp = Join-Path ([IO.Path]::GetTempPath()) "coverlyric-update-$stamp"
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$old = Get-ProgramVersion $root
Write-Host "지금 버전: $old"
try {
    if (-not $zip) {
        Write-Host '새 버전을 내려받습니다.'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $zip = Join-Path $temp 'main.zip'
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    }
    Write-Host '압축을 풉니다.'
    # .NET's own ZipFile, not Expand-Archive: started from PowerShell 7, Windows PowerShell can load
    # 7's Archive module, which fails there.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, (Join-Path $temp 'new'))
    $new = @(Get-ChildItem -LiteralPath (Join-Path $temp 'new') -Directory)[0].FullName
    if (-not (Test-Path -LiteralPath (Join-Path $new 'pyproject.toml')) -or
        -not (Test-Path -LiteralPath (Join-Path $new 'src\coverlyric'))) {
        throw '내려받은 파일이 coverlyric 이 아닙니다.'
    }
} catch {
    Write-Host "내려받기 실패: $_"
    Write-Host '인터넷 연결을 확인하고 다시 실행합니다. 프로그램은 바뀌지 않았습니다.'
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

$backup = Join-Path $root "업데이트 백업\$stamp"
Write-Host "지금 프로그램 파일을 '업데이트 백업\$stamp' 에 옮겨 둡니다."
$copied = [Collections.Generic.List[string]]::new()
try {
    Install-Program $root $new $backup $copied
} catch {
    Write-Host "업데이트 실패: $_"
    Write-Host '백업에서 되돌립니다.'
    try {
        Restore-Program $root $backup $copied
        Write-Host '되돌렸습니다. 프로그램은 업데이트 전과 같습니다.'
    } catch {
        Write-Host "되돌리기 실패: $_"
        Write-Host "'업데이트 백업\$stamp' 의 파일을 프로그램 폴더로 옮겨 놓습니다."
    }
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}
Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "새 버전: $(Get-ProgramVersion $root) (이전 $old)"
Write-Host '만든 영상, 작업 중인 노래, 설정, 기록은 그대로입니다.'
Write-Host '업데이트 끝'
