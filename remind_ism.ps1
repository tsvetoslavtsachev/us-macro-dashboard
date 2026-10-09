# Месечно напомняне за ISM услугите (ЕВРО1, 09.10.2026).
# Пуска се от Task Scheduler (macro-us-ism-reminder, 5-о число, StartWhenAvailable).
# Само ЧЕТЕ: git fetch + data/ism_cache.json локално и в origin/main; нищо не пише.
# -DryRun печата съобщението вместо прозорец (за проверка).
param([switch]$DryRun)

$repo = $PSScriptRoot
Set-Location $repo
$expected = (Get-Date).AddMonths(-1).ToString('MMMM yyyy', [Globalization.CultureInfo]::InvariantCulture)

function Months($json) {
    try {
        $d = $json | ConvertFrom-Json
        return "производство $($d.manufacturing_pmi.current.month), услуги $($d.services_pmi.current.month)", $d.services_pmi.current.month
    } catch { return 'не се чете', '' }
}

git fetch -q origin 2>$null
$remote = Months ((git show origin/main:data/ism_cache.json 2>$null) -join "`n")
$local  = Months (Get-Content data\ism_cache.json -Raw -Encoding UTF8)

if ($local[1] -eq $expected) {
    $msg = "ISM услугите за $expected вече са в таблото. Нищо не трябва да правиш.`n`nЛокално: $($local[0])"
    $icon = 64
} elseif ($remote[1] -eq $expected) {
    $msg = "ISM услугите за $expected са в GitHub (ботът ги е взел), но не и локално.`n`nПусни в us-macro-dashboard:`n  git pull`n`nЛокално: $($local[0])`nGitHub: $($remote[0])"
    $icon = 48
} else {
    $msg = "ISM услугите още са за $($local[1]); чакаме $expected.`n`nВ us-macro-dashboard:`n  1. git pull`n  2. python run.py --fetch-ism`n  3. git push`n`nЛокално: $($local[0])`nGitHub: $($remote[0])"
    $icon = 48
}

if ($DryRun) { $msg; exit 0 }
# 4096 = над всички прозорци; 0 = без таймаут
(New-Object -ComObject WScript.Shell).Popup($msg, 0, 'ISM напомняне', $icon + 4096) | Out-Null
exit 0
