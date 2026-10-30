# きょうのボード — アンインストール（Windows 専用）
#
# 使い方: uninstall.bat をダブルクリック（管理者権限は不要）
#
# やること（setup.ps1 の逆順）:
#   1. Deck の常駐を停止
#   2. スタートアップのショートカットを削除
#   3. Deck の本体ファイルを削除
#   4. スキルを削除（フォルダごと消すので、scripts/・hooks/〔hooks.json を含む〕・.claude-plugin/ も消える）
#   5. ボードのデータ（board.html / state.json / sound.json / config.json / history/ /
#      ボードの保護の記録 .guard/〔python.txt・format.json を含む〕等）を
#      消すかどうかは利用者に確認する。既定は「残す」（残すときは .guard/ も残す）。
#
# -Data Keep   … 確認せずデータを残す
# -Data Remove … 確認せずデータも消す

[CmdletBinding()]
param(
    [string]$DataDir    = (Join-Path $env:USERPROFILE '.claude\today-board'),
    [string]$SkillDir   = (Join-Path $env:USERPROFILE '.claude\skills\today-board'),
    [string]$DeckDir    = '',
    [string]$StartupDir = '',
    [ValidateSet('Ask', 'Keep', 'Remove')]
    [string]$Data       = 'Ask'
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

if (-not $DeckDir)    { $DeckDir    = Join-Path $DataDir 'deck' }
if (-not $StartupDir) { $StartupDir = [Environment]::GetFolderPath('Startup') }

$ShortcutName = 'today-board-deck.lnk'
# setup.ps1 が deck/ に置いたファイル（＝アンインストールで消してよいもの）。
# state.json / sound.json は Deck が作った利用者データなので「残す」側で扱う。
$DeckInstalledFiles = @('deck_watcher.py', 'start-deck.bat', 'README.md', 'deck.lock', 'watcher.log')

function Write-Step($n, $msg) { Write-Host ("[{0}/5] {1}" -f $n, $msg) -ForegroundColor Cyan }
function Write-Ok($msg)       { Write-Host ("      OK  " + $msg) -ForegroundColor Green }
function Write-Skip($msg)     { Write-Host ("      --  " + $msg) -ForegroundColor DarkGray }

# Python install manager の起動用の別名（WindowsApps\pythonw.exe）から起動された Deck は、
# 起動役の親と実体の子の 2 プロセスになる（setup.ps1 の Get-DeckRoots の上の注記）。
# 止めるのは両方、数えるのは親子まとめて 1 個。setup.ps1 と同じ関数を複写している。
function Get-DeckRoots($procs) {
    $ids = @($procs | ForEach-Object { $_.ProcessId })
    return @($procs | Where-Object { $ids -notcontains $_.ParentProcessId })
}

function Stop-DeckProcesses($deckScript) {
    $needle = $deckScript.ToLower()
    $found = @()
    try {
        $found = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='pyw.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($needle) })
    } catch { return 0 }
    foreach ($p in $found) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { }
    }
    if ($found.Count -gt 0) { Start-Sleep -Milliseconds 700 }
    return @(Get-DeckRoots $found).Count
}

Write-Host ''
Write-Host '=== きょうのボード アンインストール ===' -ForegroundColor White
Write-Host ("  スキル : " + $SkillDir)
Write-Host ("  Deck   : " + $DeckDir)
Write-Host ("  データ : " + $DataDir)
Write-Host ''

# --- データを消すかどうかを先に決める（作業の途中で止めないため）
$removeData = $false
if ($Data -eq 'Remove') {
    $removeData = $true
} elseif ($Data -eq 'Ask') {
    Write-Host '  ボードのデータ（最後に作ったボード・日付の切り替えで残した前の日のボードと、形が崩れる前の版〔history/〕・通知音の設定・表示モード・ボードの保護の記録〔.guard/〕）をどうしますか？'
    Write-Host ("  対象: " + $DataDir)
    $ans = Read-Host '  削除しますか？ [y = 削除 / それ以外 = 残す（既定）]'
    if ($ans -match '^\s*[yY]') { $removeData = $true }
    Write-Host ''
}

# --- 1. 常駐を停止
Write-Step 1 'Deck の常駐を停止'
$deckScript = Join-Path $DeckDir 'deck_watcher.py'
$stopped = Stop-DeckProcesses $deckScript
if ($stopped -gt 0) { Write-Ok ("稼働中の Deck を停止: {0} 個" -f $stopped) } else { Write-Skip '動いていません' }

# --- 2. スタートアップのショートカット
Write-Step 2 'スタートアップ登録を解除'
$lnkPath = Join-Path $StartupDir $ShortcutName
if (Test-Path -LiteralPath $lnkPath) {
    Remove-Item -LiteralPath $lnkPath -Force
    Write-Ok $lnkPath
} else {
    Write-Skip '登録されていません'
}

# --- 3. Deck 本体
Write-Step 3 'Deck を削除'
if (Test-Path -LiteralPath $DeckDir) {
    if ($removeData) {
        Remove-Item -LiteralPath $DeckDir -Recurse -Force
        Write-Ok ($DeckDir + '（丸ごと）')
    } else {
        $n = 0
        foreach ($name in $DeckInstalledFiles) {
            $p = Join-Path $DeckDir $name
            if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force; $n++ }
        }
        $pyc = Join-Path $DeckDir '__pycache__'
        if (Test-Path -LiteralPath $pyc) { Remove-Item -LiteralPath $pyc -Recurse -Force }
        Write-Ok ("{0} ファイルを削除（state.json / sound.json は残しました）" -f $n)
        # 残りが無ければフォルダごと片付ける
        if (@(Get-ChildItem -LiteralPath $DeckDir -Force).Count -eq 0) {
            Remove-Item -LiteralPath $DeckDir -Force
            Write-Ok '空になった deck フォルダを削除'
        }
    }
} else {
    Write-Skip 'ありません'
}

# --- 4. スキル
Write-Step 4 'スキルを削除'
if (Test-Path -LiteralPath $SkillDir) {
    Remove-Item -LiteralPath $SkillDir -Recurse -Force
    Write-Ok ($SkillDir + '（board_edit.py とボードの保護のフックを含む）')
} else {
    Write-Skip 'ありません'
}

# --- 5. データ
Write-Step 5 'ボードのデータ'
if ($removeData) {
    if (Test-Path -LiteralPath $DataDir) {
        Remove-Item -LiteralPath $DataDir -Recurse -Force
        Write-Ok ('削除しました: ' + $DataDir)
    } else {
        Write-Skip 'ありません'
    }
} else {
    Write-Ok ('残しました: ' + $DataDir)
}

Write-Host ''
Write-Host '=== 完了 ===' -ForegroundColor Green
Write-Host ''
exit 0
