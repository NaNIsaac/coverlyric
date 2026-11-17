# Started by the .bat next to the README: installs uv on first run (no admin rights), then opens the page.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'coverlyric 가사 영상 만들기'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:COVERLYRIC_HOME = $root
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
$short = @(Short-Disks $need @($root, $env:LOCALAPPDATA) | Select-Object -Unique)
if ($short) {
    Write-Host ''
    Write-Host ('디스크 공간이 부족해요. {0} MB 이상 비워 주세요:' -f ($need / 1MB))
    $short | ForEach-Object { Write-Host "  $_" }
    Write-Host '공간을 비운 뒤 다시 실행해 주세요.'
    Read-Host '창을 닫으려면 Enter를 누르세요'
    exit 1
}
if ($first) {
    Write-Host ''
    Write-Host '처음 실행이에요. 필요한 프로그램을 내려받아 설치해요.'
    Write-Host '내려받는 양은 약 150 MB, 쓰는 디스크 공간은 약 300 MB예요.'
    Write-Host '보통 1~3분, 인터넷이 느리면 더 걸려요. 이 창을 닫지 마세요.'
    Write-Host ''
}

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $dir = Join-Path $env:LOCALAPPDATA 'coverlyric\uv'
    $uv = Join-Path $dir 'uv.exe'
    if (-not (Test-Path $uv)) {
        $env:UV_INSTALL_DIR = $dir
        $env:UV_NO_MODIFY_PATH = '1'
        try {
            Invoke-RestMethod 'https://astral.sh/uv/0.11.32/install.ps1' | Invoke-Expression
        } catch {
            Write-Host "내려받기에 실패했어요: $_"
        }
        if (-not (Test-Path $uv)) {
            Write-Host '설치하지 못했어요. 인터넷 연결을 확인하고 다시 실행해 주세요.'
            exit 1
        }
    }
}

$env:COVERLYRIC_UV = $uv
Write-Host '프로그램을 여는 중이에요. 잠시 뒤 브라우저에 페이지가 열려요.'
Write-Host '쓰는 동안 이 터미널 창은 열어 두세요. 끝낼 때는 페이지의 [끝내기]를 누르세요.'
& $uv run --frozen --no-dev coverlyric
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '문제가 생겼어요. 이 창의 글을 사진으로 찍어서 물어봐 주세요.'
    exit 1
}