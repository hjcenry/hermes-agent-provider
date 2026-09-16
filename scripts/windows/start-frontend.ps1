$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
try { chcp 65001 | Out-Null } catch {}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Frontend = Join-Path $Root "frontend"
$Port = 5176

function Test-ListenPort([int]$ListenPort) {
    $pattern = "127.0.0.1:$ListenPort"
    $lines = netstat -ano -p tcp 2>$null | Select-String "LISTENING" | Select-String $pattern
    return [bool]$lines
}

function Fail([string]$Message) {
    Write-Host ""
    Write-Host $Message
    Write-Host ""
    if ($Host.Name -eq "ConsoleHost") {
        Read-Host "按回车退出"
    }
    exit 1
}

Write-Host ""
Write-Host "=== hermes-agent-provider / 设置页（Windows）==="
Write-Host "地址：http://127.0.0.1:$Port"
Write-Host ""

if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    Fail "[错误] 找不到 frontend\package.json。"
}

if (Test-ListenPort $Port) {
    Write-Host "[提示] $Port 已经在监听。"
    Write-Host ""
    if ($Host.Name -eq "ConsoleHost") { Read-Host "按回车退出" }
    exit 0
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "[错误] 未找到 Node.js。请安装 Node 18+：https://nodejs.org/"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail "[错误] 找到了 node，但没有 npm。"
}
node -e "const v=process.versions.node.split('.').map(Number); process.exit(v[0]>=18?0:1)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "[错误] Node 需要 18+。当前：$(node -v)"
}

Set-Location $Frontend
if (-not (Test-Path "node_modules")) {
    Write-Host "[信息] 正在 npm install ..."
    npm install
    if ($LASTEXITCODE -ne 0) { Fail "[错误] npm install 失败。" }
}

Write-Host "[启动] npm run dev  →  http://127.0.0.1:$Port"
Write-Host "请先开后端 8765。/api 会转到后端。"
Write-Host ""
npm run dev
if ($LASTEXITCODE -ne 0) {
    Fail "[错误] 前端退出。"
}
