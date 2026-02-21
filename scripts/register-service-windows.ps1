# ================================================================
# OnPrem SQL Bridge - Windows サービス登録スクリプト
# ================================================================
# 用途: オンプレミス Python エージェントを Windows サービスとして登録
# 実行: PowerShell (管理者権限で実行)
# 例: PS> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#    PS> .\register-service-windows.ps1 -ServiceName "OnPremSqlBridge" -AgentPath "C:\path\to\oracle_conector\onprem"

param(
    [string]$ServiceName = "OnPremSqlBridge",
    [string]$AgentPath = "C:\path\to\oracle_conector\onprem",
    [ValidateSet("Install", "Uninstall", "Start", "Stop", "Restart")]
    [string]$Action = "Install"
)

# 管理者権限チェック
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "エラー: 管理者権限で実行してください。" -ForegroundColor Red
    exit 1
}

# Python 実行ファイルのパス
$pythonExe = "python"
$pythonPath = (Get-Command $pythonExe -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) {
    Write-Host "エラー: Python が見つかりません。PATH に Python を追加してください。" -ForegroundColor Red
    exit 1
}

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "OnPrem SQL Bridge - Windows サービス管理ツール" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "設定:" -ForegroundColor Yellow
Write-Host "  サービス名: $ServiceName"
Write-Host "  エージェント PATH: $AgentPath"
Write-Host "  Python: $pythonPath"
Write-Host ""

# VBScript ラッパーを作成（サービスとして Python を実行するため）
$vbsPath = Join-Path (Split-Path $AgentPath) "run-agent.vbs"

$vbsScript = @"
' Run Python agent as Windows Service
Dim shell, pythonExe, agentPath, envFile

Set shell = CreateObject("WScript.Shell")
pythonExe = "$pythonPath"
agentPath = "$AgentPath"
envFile = agentPath & "\.env"

' .env ファイルの存在確認
If Not CreateObject("Scripting.FileSystemObject").FileExists(envFile) Then
    WScript.Echo "エラー: .env ファイルが見つかりません: " & envFile
    WScript.Quit 1
End If

' Python エージェント実行
WScript.Echo "OnPrem SQL Bridge エージェントを起動します..."
WScript.Echo "Path: " & agentPath
WScript.Echo "Time: " & Now()

' 無限ループで再起動対応
Do While True
    shell.CurrentDirectory = agentPath
    Dim exitCode
    exitCode = shell.Run(pythonExe & " main.py", 0, True)
    WScript.Echo "[" & Now() & "] エージェント停止 (Exit Code: " & exitCode & ")"
    WScript.Sleep 5000  ' 5 秒待機して再起動
Loop
"@

# ファイルに保存
Write-Host "VBS ラッパースクリプトを作成中..." -ForegroundColor Yellow
$vbsScript | Out-File -Encoding Default -FilePath $vbsPath
Write-Host "  作成: $vbsPath" -ForegroundColor Green

switch ($Action) {
    "Install" {
        Write-Host ""
        Write-Host "サービスをインストール中..." -ForegroundColor Yellow
        
        # 既存サービスを削除
        $existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($existingService) {
            Write-Host "  既存サービス '$ServiceName' を削除中..."
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Remove-Service -Name $ServiceName -Force 2>$null
            Start-Sleep -Seconds 2
        }
        
        # 新規サービス作成（cscript で VBS を実行）
        New-Service -Name $ServiceName `
            -DisplayName "OnPrem SQL Bridge Agent" `
            -Description "Oracle SQL Bridge - On-Premises Agent for AWS Integration" `
            -BinaryPathName "cscript.exe //B `"$vbsPath`"" `
            -StartupType Automatic | Out-Null
        
        Write-Host "  ✓ サービス中止。構成調整後、手動で開始してください。" -ForegroundColor Green
        Write-Host ""
        Write-Host "次のステップ:" -ForegroundColor Cyan
        Write-Host "  1. $AgentPath\.env ファイルを確認・更新"
        Write-Host "  2. 以下コマンドでサービスを開始:"
        Write-Host "     PS> .\register-service-windows.ps1 -ServiceName '$ServiceName' -Action Start"
        Write-Host ""
    }
    
    "Uninstall" {
        Write-Host ""
        Write-Host "サービスをアンインストール中..." -ForegroundColor Yellow
        
        $existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($existingService) {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Remove-Service -Name $ServiceName -Force 2>$null
            Write-Host "  ✓ サービスを削除しました。" -ForegroundColor Green
        }
        else {
            Write-Host "  サービス '$ServiceName' は見つかりません。" -ForegroundColor Yellow
        }
        
        if (Test-Path $vbsPath) {
            Remove-Item $vbsPath -Force
            Write-Host "  ✓ VBS ラッパーを削除しました。" -ForegroundColor Green
        }
    }
    
    "Start" {
        Write-Host ""
        Write-Host "サービスを開始中..." -ForegroundColor Yellow
        
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($svc) {
            Start-Service -Name $ServiceName
            Write-Host "  ✓ サービスを開始しました。" -ForegroundColor Green
            Write-Host ""
            Write-Host "ステータス確認コマンド:" -ForegroundColor Cyan
            Write-Host "  PS> Get-Service $ServiceName"
            Write-Host "  PS> Get-EventLog -LogName Application | Where-Object {`$_.Source -like '*$ServiceName*'}"
        }
        else {
            Write-Host "  エラー: サービス '$ServiceName' が見つかりません。" -ForegroundColor Red
            exit 1
        }
    }
    
    "Stop" {
        Write-Host ""
        Write-Host "サービスを停止中..." -ForegroundColor Yellow
        
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($svc) {
            Stop-Service -Name $ServiceName -Force
            Write-Host "  ✓ サービスを停止しました。" -ForegroundColor Green
        }
        else {
            Write-Host "  エラー: サービス '$ServiceName' が見つかりません。" -ForegroundColor Red
            exit 1
        }
    }
    
    "Restart" {
        Write-Host ""
        Write-Host "サービスを再起動中..." -ForegroundColor Yellow
        
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($svc) {
            Restart-Service -Name $ServiceName
            Write-Host "  ✓ サービスを再起動しました。" -ForegroundColor Green
        }
        else {
            Write-Host "  エラー: サービス '$ServiceName' が見つかりません。" -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host ""
Write-Host "完了。" -ForegroundColor Green
