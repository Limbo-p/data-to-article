# data-to-article 总控面板启动脚本（Windows）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_panel.ps1
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$env:PYTHONPATH = Join-Path $root 'src'
$env:PYTHONIOENCODING = 'utf-8'

# 优先用本地 venv（本目录上一级 .venv），否则用 PATH 上的 python
$venv = Join-Path (Split-Path -Parent $root) '.venv\Scripts\python.exe'
$py = "python"
if (Test-Path -LiteralPath $venv) { $py = $venv }

$port = 8765
$busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Start-Process "http://127.0.0.1:$port"
    exit 0
}
& $py -m data_to_article.web.server --host 127.0.0.1 --port $port