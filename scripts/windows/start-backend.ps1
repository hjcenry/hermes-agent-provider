$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
try { chcp 65001 | Out-Null } catch {}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $Root "backend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
$Req = Join-Path $Backend "requirements.txt"
$Port = 8765

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
Write-Host "=== hermes-agent-provider / 后端（Windows）==="
Write-Host "仓库：$Root"
Write-Host "地址：http://127.0.0.1:$Port/healthz"
Write-Host ""

if (-not (Test-Path (Join-Path $Backend "app\main.py"))) {
    Fail "[错误] 找不到 backend\app\main.py，请从仓库的 scripts\windows 运行本脚本。"
}

if (Test-ListenPort $Port) {
    Write-Host "[提示] $Port 已经在监听，不再重复启动。"
    Write-Host ""
    if ($Host.Name -eq "ConsoleHost") {
        Read-Host "按回车退出"
    }
    exit 0
}

$ConfigDir = Join-Path $Root "config"
$Secrets = Join-Path $ConfigDir "secrets.env"
$SecretsExample = Join-Path $ConfigDir "secrets.env.example"
$Local = Join-Path $ConfigDir "local.yaml"
$LocalExample = Join-Path $ConfigDir "local.yaml.example"
if (-not (Test-Path $Secrets)) {
    if (-not (Test-Path $SecretsExample)) {
        Fail "[错误] 找不到 config\secrets.env.example，无法创建 secrets.env。"
    }
    Copy-Item $SecretsExample $Secrets
    Write-Host "[信息] 已从 example 创建 config\secrets.env，请尽快改 PROXY_API_KEY。"
}
if (-not (Test-Path $Local) -and (Test-Path $LocalExample)) {
    Copy-Item $LocalExample $Local
    Write-Host "[信息] 已从 example 创建 config\local.yaml。"
}

$Workspace = Join-Path $Root "data\workspace"
if (-not (Test-Path $Workspace)) {
    New-Item -ItemType Directory -Path $Workspace | Out-Null
}

$pyCmd = $null
$pyArgs = @()
foreach ($item in @(
        @{ Cmd = "py"; Args = @("-3") },
        @{ Cmd = "python"; Args = @() },
        @{ Cmd = "python3"; Args = @() }
    )) {
    if (-not (Get-Command $item.Cmd -ErrorAction SilentlyContinue)) { continue }
    & $item.Cmd @($item.Args + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) 2>$null
    if ($LASTEXITCODE -eq 0) {
        $pyCmd = $item.Cmd
        $pyArgs = $item.Args
        break
    }
}

if (-not $pyCmd) {
    Fail @"
[错误] 未找到 Python 3.11+。请先安装：
       https://www.python.org/downloads/
       安装时勾选 Add python.exe to PATH，然后重新打开终端再运行。
       也可用：winget install Python.Python.3.12
"@
}

Write-Host "[检查] 系统 Python：$pyCmd $($pyArgs -join ' ')"

if (-not (Test-Path $VenvPy)) {
    Write-Host "[信息] 未找到虚拟环境，正在创建 backend\.venv ..."
    & $pyCmd @($pyArgs + @("-m", "venv", (Join-Path $Backend ".venv")))
    if ($LASTEXITCODE -ne 0) {
        Fail "[错误] 创建虚拟环境失败。请确认已安装 Python 3.11+ 后重试。"
    }
}

Write-Host "[检查] Python 包..."
& $VenvPy -c "import fastapi, uvicorn, yaml, pydantic, httpx, dotenv, qoder_agent_sdk, cursor_sdk" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[信息] 依赖不完整，正在 pip install -r backend\requirements.txt"
    & $VenvPy -m pip install -U pip
    & $VenvPy -m pip install -r $Req
    if ($LASTEXITCODE -ne 0) {
        Fail "[错误] pip 安装失败。请检查网络后手动执行：`n       cd backend`n       .venv\Scripts\python -m pip install -r requirements.txt"
    }
}

Write-Host ""
Write-Host "[启动] uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port"
Write-Host "改 Python 后必须关掉本窗口再重新运行本脚本（未开 --reload）。"
Write-Host ""
Set-Location $Backend
& $VenvPy -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) {
    Fail "[错误] 后端退出。若提示未配置 PROXY_API_KEY，请检查 config\secrets.env。若端口占用，先关掉已有的 $Port 进程。"
}
