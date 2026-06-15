# 编译 LaTeX 报告脚本
# 运行前确保 MiKTeX 已安装且在 PATH 中
# 用法：在 report/ 目录下运行 .\compile.ps1

Set-Location $PSScriptRoot

Write-Host "Step 1: 安装所需 LaTeX 包..." -ForegroundColor Cyan
$packages = @(
    "ctex", "fontspec", "geometry", "amsmath", "amssymb",
    "graphicx", "booktabs", "caption", "fancyhdr", "titlesec",
    "indentfirst", "microtype", "cite", "hyperref", "xcolor",
    "listings", "bm", "tools", "ms", "zapfding"
)
foreach ($pkg in $packages) {
    Write-Host "  Installing $pkg..."
    miktex packages install $pkg 2>&1 | Out-Null
}

Write-Host "Step 2: 第一次编译..." -ForegroundColor Cyan
xelatex -interaction=nonstopmode main.tex

Write-Host "Step 3: 第二次编译（生成交叉引用）..." -ForegroundColor Cyan
xelatex -interaction=nonstopmode main.tex

if (Test-Path "main.pdf") {
    Write-Host "编译成功！打开 main.pdf ..." -ForegroundColor Green
    Start-Process "main.pdf"
} else {
    Write-Host "编译失败，请检查 main.log" -ForegroundColor Red
    Get-Content "main.log" | Select-Object -Last 30
}
