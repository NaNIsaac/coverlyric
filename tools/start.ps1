# Started by the .bat next to the README: installs uv on first run (no admin rights), then opens the page.

# uv's virtual environment names Python by a minor-version junction (python 3.14 -> 3.14.x). Some
# sessions, such as an elevated or sandboxed shell, may not follow a junction (os error 448), and
# Python cannot start. The environment then names the full-version folder the junction points to.
function Repair-VenvHome([string]$venv) {
    $cfg = Join-Path $venv 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $cfg)) { return $false }
    $changed = $false
    $lines = foreach ($line in [IO.File]::ReadAllLines($cfg)) {
        if ($line -match '^home\s*=\s*(.+)$') {
            $path = $Matches[1].Trim()
            for ($dir = $path; $dir; $dir = Split-Path -Parent $dir) {
                $item = Get-Item -LiteralPath $dir -Force -ErrorAction SilentlyContinue
                if ($item -and $item.LinkType -eq 'Junction') {
                    $target = @($item.Target)[0]
                    if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path (Split-Path -Parent $dir) $target }
                    $line = 'home = ' + $target + $path.Substring($dir.Length)
                    $changed = $true
                    break
                }
            }
        }
        $line
    }
    if ($changed) { [IO.File]::WriteAllLines($cfg, [string[]]$lines, (New-Object Text.UTF8Encoding $false)) }
    return $changed
}

# The newest stable Python in uv's Python folder from `least` on, by its full-version folder, which is
# a real folder and not one of the minor-version junctions; $null when there is none.
function Find-ManagedPython([string]$dir, [version]$least) {
    if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { return $null }
    $found = foreach ($item in Get-ChildItem -LiteralPath $dir -Directory -Force) {
        if ($item.LinkType -or $item.Name -notmatch '^cpython-(\d+\.\d+\.\d+)-windows-') { continue }
        $version = [version]$Matches[1]
        $exe = Join-Path $item.FullName 'python.exe'
        if ($version -ge $least -and (Test-Path -LiteralPath $exe)) {
            [pscustomobject]@{ Version = $version; Path = $exe }
        }
    }
    @($found | Sort-Object Version -Descending)[0].Path
}

function Test-VenvPython([string]$venv) {
    $python = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { return $false }
    try {
        & $python --version *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false  # not a program Windows can start
    }
}

# uv's environments start Python through its own trampoline, which carries the base Python's path,
# a minor-version junction, inside the executable and does not read pyvenv.cfg (#19).
function Test-UvTrampoline([string]$venv) {
    $python = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { return $false }
    $text = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($python))
    return $text.Contains('uv trampoline')
}

# Makes the environment again with Python's own venv, whose launcher reads home from pyvenv.cfg, so
# it names the full-version folder and never a junction; uv then installs into it (#19). Only the
# program's own .venv folder is removed.
function Reset-Venv([string]$venv, [string]$python) {
    if ((Split-Path -Leaf $venv) -ne '.venv') { return $false }
    if (Test-Path -LiteralPath $venv) { Remove-Item -LiteralPath $venv -Recurse -Force }
    & $python -m venv --without-pip $venv
    return $LASTEXITCODE -eq 0
}

# Runs the program. When it fails and the environment's Python cannot start, it repairs the
# environment's home and runs once more (#17). When Python still cannot start, the environment is a
# uv trampoline, or uv failed before making one (it queries every junction in its Python folder), it
# makes the environment again with a full-version Python from `least` (requires-python in
# pyproject.toml) on and runs once more with UV_PYTHON naming it (#18, #19). A failure of the
# program itself is not retried.
function Start-Program([string]$uv, [string]$venv, [version]$least = '3.12') {
    # Windows PowerShell 5.1 turns a native command's stderr into an error, which the script's 'Stop'
    # would make end the launcher before the repair (#18).
    $ErrorActionPreference = 'Continue'
    & $uv run --frozen --no-dev coverlyric
    $code = $LASTEXITCODE
    if ($code -eq 0 -or (Test-VenvPython $venv)) { $global:LASTEXITCODE = $code; return }
    if (-not (Test-UvTrampoline $venv) -and (Repair-VenvHome $venv)) {
        Write-Host 'Python 경로를 고쳐 다시 시작합니다.'
        & $uv run --frozen --no-dev coverlyric
        $code = $LASTEXITCODE
        if ($code -eq 0 -or (Test-VenvPython $venv)) { $global:LASTEXITCODE = $code; return }
    }
    $python = Find-ManagedPython (& $uv python dir 2>$null | Select-Object -First 1) $least
    if ($python) {
        Write-Host 'Python 환경을 다시 만들어 시작합니다.'
        if (Reset-Venv $venv $python) {
            $env:UV_PYTHON = $python
            & $uv run --frozen --no-dev coverlyric
            $code = $LASTEXITCODE
        }
    }
    $global:LASTEXITCODE = $code
}

# Where the user's data lives (videos, the project in progress, settings, the log): COVERLYRIC_HOME
# when set, else the folder chosen in the installer or the page (one line in data-folder.txt), else
# coverlyric in the user's Documents. Documents comes from the shell, which follows a OneDrive move.
function Get-DataFolder([string]$saved) {
    if ($env:COVERLYRIC_HOME) { return $env:COVERLYRIC_HOME }
    if ($saved -and (Test-Path -LiteralPath $saved)) {
        $line = @(Get-Content -LiteralPath $saved -Encoding UTF8 | Where-Object { $_.Trim() })[0]
        if ($line) { return $line.Trim() }
    }
    Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'coverlyric'
}

# The user's data from the program folder, where versions before the data folder kept it.
$OldData = @('작업 중', '만든 영상', 'settings.json', 'coverlyric.log', 'coverlyric.log.1')

# Moves the user's data out of the program folder once. A name already in the data folder is left
# where it is and reported, never merged or overwritten. A video folder chosen inside the program
# folder follows the move in settings.json. Writes one line per item for the console.
function Move-OldData([string]$root, [string]$data) {
    if ([IO.Path]::GetFullPath($root).TrimEnd('\') -eq [IO.Path]::GetFullPath($data).TrimEnd('\')) {
        return
    }
    New-Item -ItemType Directory -Force -Path $data | Out-Null
    foreach ($name in $OldData) {
        $from = Join-Path $root $name
        if (-not (Test-Path -LiteralPath $from)) { continue }
        $to = Join-Path $data $name
        if (Test-Path -LiteralPath $to) {
            "$name 은 두 곳에 있어 옮기지 않았습니다: $from"
            continue
        }
        if ([IO.Path]::GetPathRoot($from) -eq [IO.Path]::GetPathRoot($to)) {
            Move-Item -LiteralPath $from -Destination $to
        } else {
            # Move-Item cannot take a folder to another drive: copy, and delete only once copied.
            Copy-Item -LiteralPath $from -Destination $to -Recurse
            Remove-Item -LiteralPath $from -Recurse -Force
        }
        "$name 을 $data 로 옮겼습니다."
    }
    $settings = Join-Path $data 'settings.json'
    if (Test-Path -LiteralPath $settings) {
        $text = [IO.File]::ReadAllText($settings)
        $saved = $text | ConvertFrom-Json
        $folder = [string]$saved.output
        if ($folder -and $folder.StartsWith($root.TrimEnd('\') + '\', 'OrdinalIgnoreCase')) {
            $moved = Join-Path $data $folder.Substring($root.TrimEnd('\').Length + 1)
            if (Test-Path -LiteralPath $moved) {
                $saved.output = $moved
                [IO.File]::WriteAllText($settings, ($saved | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
            }
        }
    }
}

# Dot-sourced by the tests for the functions above.
if ($MyInvocation.InvocationName -eq '.') { return }

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'coverlyric 가사 영상 만들기'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$data = Get-DataFolder (Join-Path $env:LOCALAPPDATA 'coverlyric\data-folder.txt')
Move-OldData $root $data | ForEach-Object { Write-Host $_ }
$env:COVERLYRIC_HOME = $data
# numpy fails to start on PCs with many cores and little free memory otherwise (issue #1).
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'

# Free space on the drive of each folder the first run writes to. A path whose drive cannot be read
# (a network share) is left out.
function Short-Disks([long]$need, [string[]]$paths) {
    foreach ($p in $paths) {
        try { $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($p)) } catch { continue }
        if ($drive.IsReady -and $drive.AvailableFreeSpace -lt $need) {
            '{0} 드라이브 (남은 공간 {1:N0} MB)' -f $drive.Name, ($drive.AvailableFreeSpace / 1MB)
        }
    }
}

$first = -not (Test-Path (Join-Path $root '.venv'))
$need = if ($first) { 500MB } else { 200MB }
$short = @(Short-Disks $need @($root, $data, $env:LOCALAPPDATA) | Select-Object -Unique)
if ($short) {
    Write-Host ''
    Write-Host ('디스크 공간 부족: 아래 드라이브에 {0} MB 이상의 여유 공간이 필요합니다.' -f ($need / 1MB))
    $short | ForEach-Object { Write-Host "  $_" }
    Write-Host '공간을 확보한 뒤 다시 실행합니다.'
    exit 1
}
if ($first) {
    Write-Host ''
    Write-Host '첫 실행: 필요한 프로그램을 내려받아 설치합니다.'
    Write-Host '내려받기 약 150 MB, 디스크 사용 약 300 MB.'
    Write-Host '보통 1~3분 걸립니다. 끝날 때까지 이 창은 열어 둡니다.'
    Write-Host ''
}

# The installer ships uv, so an installed copy never fetches the install script from the web.
$uv = Join-Path $root 'uv\uv.exe'
if (-not (Test-Path -LiteralPath $uv)) { $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source }
if (-not $uv) {
    $dir = Join-Path $env:LOCALAPPDATA 'coverlyric\uv'
    $uv = Join-Path $dir 'uv.exe'
    if (-not (Test-Path $uv)) {
        $env:UV_INSTALL_DIR = $dir
        $env:UV_NO_MODIFY_PATH = '1'
        try {
            Invoke-RestMethod 'https://astral.sh/uv/0.11.32/install.ps1' | Invoke-Expression
        } catch {
            Write-Host "내려받기 실패: $_"
        }
        if (-not (Test-Path $uv)) {
            Write-Host '설치 실패. 인터넷 연결을 확인하고 다시 실행합니다.'
            exit 1
        }
    }
}

$env:COVERLYRIC_UV = $uv
Write-Host '프로그램을 시작합니다. 잠시 뒤 브라우저에 페이지가 열립니다.'
Write-Host '사용하는 동안 이 창은 열어 둡니다. 끝내려면 페이지의 [끝내기]를 누릅니다.'
Start-Program $uv (Join-Path $root '.venv')
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host "프로그램이 오류로 끝났습니다 (종료 코드 $LASTEXITCODE). 위 메시지를 확인합니다."
    Write-Host '해결되지 않으면 이 창의 내용을 https://github.com/NaNIsaac/coverlyric/issues 에 올립니다.'
    exit 1
}