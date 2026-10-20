# 물모아 스냅샷 백업 스케줄 — Windows 작업 스케줄러 등록 (매일 07:00, venv 파이썬)
# 사용: PowerShell 에서  .\scripts\register_mulmoa_task.ps1   (관리자 권한 불필요, 현재 사용자 계정으로 등록)
# 해제: Unregister-ScheduledTask -TaskName "AlgaeCast-MulmoaSnapshot" -Confirm:$false
# 확인: Get-ScheduledTaskInfo -TaskName "AlgaeCast-MulmoaSnapshot" ; 로그 logs\mulmoa_snapshot.log
$ErrorActionPreference = "Stop"

$TaskName = "AlgaeCast-MulmoaSnapshot"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python   = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script   = Join-Path $RepoRoot "scripts\snapshot_mulmoa_forecast.py"
$LogDir   = Join-Path $RepoRoot "logs"
$Log      = Join-Path $LogDir "mulmoa_snapshot.log"

if (-not (Test-Path $Python)) { throw "venv 파이썬이 없습니다: $Python  (먼저 make setup)" }
if (-not (Test-Path $Script)) { throw "스크립트가 없습니다: $Script" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# cmd.exe 를 통해 실행해 stdout/stderr 를 로그에 덧붙인다. 한글 경로는 따옴표로 감싼다.
# 결과 형태: /c ""<python>" "<script>" >> "<log>" 2>&1"   (cmd 의 바깥 따옴표 규칙)
$Cmd = '/c ""' + $Python + '" "' + $Script + '" >> "' + $Log + '" 2>&1"'
$Action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $Cmd -WorkingDirectory $RepoRoot
$Trigger  = New-ScheduledTaskTrigger -Daily -At 07:00
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
            -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal `
    -Description "AlgaeCast-7: 물모아 AI 녹조 예측 스냅샷 (매일 07:00, GitHub Actions 백업)" -Force | Out-Null

Write-Host "등록 완료: $TaskName  (매일 07:00, $Python)"
Write-Host "즉시 1회 실행하려면: Start-ScheduledTask -TaskName $TaskName ; 로그: $Log"
