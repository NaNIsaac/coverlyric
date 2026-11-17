# Started by the .bat next to the README: installs uv on first run (no admin rights), then opens the page.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'coverlyric 가사 영상 만들기'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:COVERLYRIC_HOME = $root

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $dir = Join-Path $env:LOCALAPPDATA 'coverlyric\uv'
    $uv = Join-Path $dir 'uv.exe'
    if (-not (Test-Path $uv)) {
        Write-Host ''
        Write-Host '처음 실행이에요. 필요한 프로그램을 내려받고 있어요.'
        Write-Host '인터넷 속도에 따라 몇 분 걸릴 수 있어요. 이 창을 닫지 마세요.'
        Write-Host ''
        $env:UV_INSTALL_DIR = $dir
        $env:UV_NO_MODIFY_PATH = '1'
        try {
            Invoke-RestMethod 'https://astral.sh/uv/0.11.32/install.ps1' | Invoke-Expression
        } catch {
            Write-Host "내려받기에 실패했어요: $_"
        }
        if (-not (Test-Path $uv)) {
            Write-Host '문제가 생겼어요. 인터넷 연결을 확인하고 다시 실행해 주세요.'
            exit 1
        }
    }
}

Write-Host '프로그램을 여는 중이에요. 잠시 뒤 인터넷 창이 열려요.'
& $uv run --frozen --no-dev coverlyric
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '문제가 생겼어요. 이 창의 글을 사진으로 찍어서 물어봐 주세요.'
    exit 1
}
