$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
try { chcp 65001 | Out-Null } catch {}

Write-Host ""
Write-Host "=== hermes-agent-provider / 一键启动（Windows）==="
Write-Host "后端 http://127.0.0.1:8765  ·  设置页 http://127.0.0.1:5176"
Write-Host ""

$BackendPs1 = Join-Path $PSScriptRoot "start-backend.ps1"
$FrontendPs1 = Join-Path $PSScriptRoot "start-frontend.ps1"
if (-not (Test-Path $BackendPs1)) {
    Write-Host "[错误] 找不到 start-backend.ps1"
    Read-Host "按回车退出"
    exit 1
}

Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $BackendPs1
)
if (Test-Path $FrontendPs1) {
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $FrontendPs1
    )
}
