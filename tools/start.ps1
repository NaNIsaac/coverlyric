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
    Write-Host ('디스크 공간 부족: 아래 드라이브에 {0} MB 이상의 여유 공간이 필요합니다.' -f ($need / 1MB))
    $short | ForEach-Object { Write-Host "  $_" }
    Write-Host '공간을 확보한 뒤 다시 실행하세요.'
    exit 1
}
if ($first) {
    Write-Host ''
    Write-Host '첫 실행: 필요한 프로그램을 내려받아 설치합니다.'
    Write-Host '내려받기 약 150 MB, 디스크 사용 약 300 MB.'
    Write-Host '보통 1~3분 걸립니다. 끝날 때까지 이 창을 닫지 마세요.'
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
            Write-Host "내려받기 실패: $_"
        }
        if (-not (Test-Path $uv)) {
            Write-Host '설치 실패. 인터넷 연결을 확인하고 다시 실행하세요.'
            exit 1
        }
    }
}

$env:COVERLYRIC_UV = $uv
Write-Host '프로그램을 시작합니다. 잠시 뒤 브라우저에 페이지가 열립니다.'
Write-Host '사용하는 동안 이 창을 열어 두세요. 끝내려면 페이지의 [끝내기]를 누르세요.'
& $uv run --frozen --no-dev coverlyric
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host "프로그램이 오류로 끝났습니다 (종료 코드 $LASTEXITCODE). 위 메시지를 확인하세요."
    Write-Host '해결되지 않으면 이 창의 내용을 https://github.com/NaNIsaac/coverlyric/issues 에 올리세요.'
    exit 1
}