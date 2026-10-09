# Седмично ЛОКАЛНО опресняване на кеша (ЕВРО1, 09.10.2026).
# Пуска се от Windows Task Scheduler. Кешовете в data\ са в .gitignore и облакът
# не ги пипа; без този скрипт стоят, докато някой не пусне run.py на ръка.
# Компютърът заспива, затова задачата е с "StartWhenAvailable": ако понеделникът
# е пропуснат в сън, тръгва при събуждане. Тук чакаме мрежата и опитваме до 3 пъти.

$repo = $PSScriptRoot
Set-Location $repo  # run.py ползва относителни пътища към data
$py   = 'C:\Users\tsach\AppData\Local\Programs\Python\Python314\python.exe'
$log  = Join-Path $repo 'output\logs\refresh_local.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
function Log($m) { [IO.File]::AppendAllText($log, "$(Get-Date -Format s) $m`r`n") }

Log '==== start'
# След събуждане Wi-Fi идва след секунди до минута: чакаме до 10 минути.
for ($i = 0; $i -lt 20; $i++) {
    try { [Net.Dns]::GetHostEntry('api.stlouisfed.org') | Out-Null; break } catch { Start-Sleep 30 }
}

$code = 1
for ($try = 1; $try -le 3; $try++) {
    Log "refresh, attempt $try"
    cmd /c "`"$py`" `"$repo\run.py`" --refresh-only >> `"$log`" 2>&1"
    cmd /c "`"$py`" `"$repo\run.py`" --check-fresh >> `"$log`" 2>&1"
    $code = $LASTEXITCODE
    if ($code -eq 0) { break }
    Start-Sleep 300
}
Log "==== end, check-fresh exit $code"
exit $code
