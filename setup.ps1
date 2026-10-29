# きょうのボード — セットアップ（Windows 専用）
#
# 使い方: setup.bat をダブルクリック（管理者権限は不要）
#
# やること:
#   1. Python 3 の有無を確認（無ければ入手先を案内して中断する。勝手に入れない）
#   2. スキルを ~/.claude/skills/today-board/ に配置し、ボードが読むアセット
#      （board.css / board.js / cat.png）を ~/.claude/today-board/ にも配置
#   3. Deck（常駐ウォッチャー）を ~/.claude/today-board/deck/ に配置
#   4. スタートアップフォルダに Deck のショートカットを作成（pythonw = コンソール非表示）
#   5. Deck を即時起動（4 のショートカットを explorer.exe で開く。setup を走らせたプロセスから切り離すため）
#
# 冪等: 何度実行しても安全。既にインストール済みなら「更新」として振る舞う。
#       利用者データ（board.html / state.json / sound.json / config.json）は上書きしない。
#
# 配置先はパラメータで差し替えられる（テスト用。既定は本番パス）。

[CmdletBinding()]
param(
    [string]$DataDir    = (Join-Path $env:USERPROFILE '.claude\today-board'),
    [string]$SkillDir   = (Join-Path $env:USERPROFILE '.claude\skills\today-board'),
    [string]$DeckDir    = '',
    [string]$StartupDir = '',
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

if (-not $DeckDir)    { $DeckDir    = Join-Path $DataDir 'deck' }
if (-not $StartupDir) { $StartupDir = [Environment]::GetFolderPath('Startup') }

$SrcDir      = $PSScriptRoot
$SrcSkill    = Join-Path $SrcDir 'skill'
$SrcDeck     = Join-Path $SrcDir 'deck'
$ShortcutName = 'today-board-deck.lnk'
# Deck が自分で作る実行時データ。配布物から上書きコピーしない。
$DeckRuntimeFiles = @('state.json', 'sound.json', 'deck.lock', 'watcher.log')

function Write-Step($n, $msg) { Write-Host ("[{0}/5] {1}" -f $n, $msg) -ForegroundColor Cyan }
function Write-Ok($msg)       { Write-Host ("      OK  " + $msg) -ForegroundColor Green }
function Write-Warn2($msg)    { Write-Host ("      !   " + $msg) -ForegroundColor Yellow }
function Write-Info2($msg)    { Write-Host ("      -   " + $msg) }

# ---------------------------------------------------------------- Python 検出

function Find-Python3 {
    $cands = New-Object System.Collections.Generic.List[string]
    foreach ($n in @('python.exe', 'python3.exe', 'py.exe')) {
        foreach ($c in (Get-Command $n -All -ErrorAction SilentlyContinue)) {
            if ($c.Source) { $cands.Add($c.Source) }
        }
    }
    foreach ($exe in ($cands | Select-Object -Unique)) {
        # 実際に起動して確かめる。Microsoft Store のエイリアス（未インストールの
        # プレースホルダ）は終了コードが 0 にならないのでここで落ちる。
        $out = $null
        try { $out = & $exe -c "import sys;print(sys.version_info[0])" 2>$null } catch { continue }
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq '3') { return $exe }
    }
    return $null
}

function Get-PythonwFor($pythonExe) {
    $dir  = Split-Path -Parent $pythonExe
    $leaf = Split-Path -Leaf $pythonExe
    if ($leaf -ieq 'py.exe') { $w = Join-Path $dir 'pyw.exe' }
    else                     { $w = Join-Path $dir 'pythonw.exe' }
    if (Test-Path -LiteralPath $w) { return $w }
    return $pythonExe   # 最後の手段（コンソールが出る）
}

# ---------------------------------------------------------------- Deck プロセス

function Get-DeckProcesses($deckScript) {
    $needle = $deckScript.ToLower()
    $procs = @()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='pyw.exe'" -ErrorAction Stop
    } catch { return @() }
    return @($procs | Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($needle) })
}

# Python install manager の起動用の別名（%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe）から
# 起動すると、起動役の親（PythonManager パッケージ内の pythonw.exe）が実体の pythonw.exe を子として
# 起動し、Deck 1 つが 2 プロセスになる。どちらも CommandLine に deck_watcher.py のパスを含む。
# 実測（2026-10-25・PythonManager 26.4・子は PythonCore 3.13）: 親を止めると子も消え、
# 子を止めると親も終わる。Deck のコードを動かす（ポートとロックを持つ）のは子だけ。

function Get-DeckRoots($procs) {
    # 親子で 1 組＝Deck 1 個。集合の中に親がいないものだけを数える
    $ids = @($procs | ForEach-Object { $_.ProcessId })
    return @($procs | Where-Object { $ids -notcontains $_.ParentProcessId })
}

function Get-DeckWorkers($procs) {
    # Deck を実際に動かしている側＝集合の中に子を持たないもの
    $parents = @($procs | ForEach-Object { $_.ParentProcessId })
    return @($procs | Where-Object { $parents -notcontains $_.ProcessId })
}

function Test-PyManagerLauncher($proc) {
    # 起動役の親か（子をまだ起動していない瞬間は、親が「子を持たないもの」に見える）
    return ($proc.ExecutablePath -and $proc.ExecutablePath -like '*\PythonSoftwareFoundation.PythonManager_*')
}

function Stop-DeckProcesses($deckScript) {
    # @() で包む: PowerShell は return の際に 1 要素配列をスカラーへ開いてしまうため
    $found = @(Get-DeckProcesses $deckScript)
    foreach ($p in $found) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { }
    }
    if ($found.Count -gt 0) { Start-Sleep -Milliseconds 700 }
    return @(Get-DeckRoots $found).Count   # 止めたのは全プロセス、数えるのは Deck の個数
}

function Get-OtherDeckProcesses($deckScript) {
    # インストール先以外の場所から動いている deck_watcher.py（勝手に止めない）
    $needle = $deckScript.ToLower()
    $procs = @()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='pyw.exe'" -ErrorAction Stop
    } catch { return @() }
    return @($procs | Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains('deck_watcher.py') -and
                                     -not $_.CommandLine.ToLower().Contains($needle) })
}

function Get-DeckShownProcesses($procs) {
    # 利用者に見せるプロセス: 起動用の別名経由の親子なら実体（子）の側。Deck のログが書く pid と揃う
    $w = @(Get-DeckWorkers $procs | Where-Object { -not (Test-PyManagerLauncher $_) })
    if ($w.Count -gt 0) { return $w }
    return @($procs)
}

function Test-PathMayAlias($path) {
    # 文字列の比較では同じ場所かを決められないパスか（Deck は realpath＋normcase で比べる）。
    # 祖先にジャンクション・シンボリックリンク等（reparse point）がある、または
    # 8.3 形式の短い名前（~ を含む要素）があるなら、別名で同じ場所を指しうる
    foreach ($seg in ($path -split '\\')) { if ($seg -like '*~*') { return $true } }
    $p = Split-Path -Parent $path
    while ($p) {
        try {
            $it = Get-Item -LiteralPath $p -Force -ErrorAction Stop
            if ($it.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return $true }
        } catch { }
        $up = Split-Path -Parent $p
        if ($up -eq $p) { break }
        $p = $up
    }
    return $false
}

function Get-DeckBoardRelation($commandLine, $boardPath, $defaultBoard) {
    # CommandLine の --board で、見ているボードが $boardPath と同じかを判定する。
    # 戻り値: 'same' / 'different' / 'unknown'（判定できない）
    # --board が無ければ既定のボード。相対パスの --board は起動時の作業フォルダが
    # 分からないので判定できない側に倒す。文字列としては違っても、ジャンクション・
    # 短い名前などで同じ場所を指しうるものも判定できない側に倒す
    $b = $null
    if ($commandLine -match '--board(\s+|=)') {
        if ($commandLine -match '--board\s+(?:"([^"]+)"|([^\s"]+))') {
            $b = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
        } else { return 'unknown' }   # --board=… や空の値など、読み取れない書き方
    }
    if (-not $b) { $b = $defaultBoard }
    # ドライブ文字から始まる絶対パスだけを比べる（相対・ドライブなしの \… ・UNC は判定できない）
    if ($b -notmatch '^[A-Za-z]:[\\/]') { return 'unknown' }
    try {
        $x = [System.IO.Path]::GetFullPath($b.Replace('/', '\')).TrimEnd('\')
        $y = [System.IO.Path]::GetFullPath($boardPath).TrimEnd('\')
    } catch { return 'unknown' }
    if ($x -ieq $y) { return 'same' }
    if ((Test-PathMayAlias $x) -or (Test-PathMayAlias $y)) { return 'unknown' }
    return 'different'
}

function Get-DeckLogLength($logPath) {
    # 起動前の watcher.log の大きさ（無ければ 0）。起動後に読む位置の目安にする
    try { return (Get-Item -LiteralPath $logPath -ErrorAction Stop).Length } catch { return 0 }
}

function Find-DeckDuplicateExit($logPath, $since, $offset) {
    # watcher.log のうち、起動後に書かれた行に「多重起動を検出したため終了します」
    # （多重起動ガード・ロックを置けないときの両方）があれば、その行を返す（無ければ $null）。
    # 起動後に書かれた行＝起動前の大きさ $offset より後ろ、かつ時刻が $since（Deck のログと
    # 同じ 'yyyy-MM-dd HH:mm:ss'）以降。watcher.log は 1MB を超えると切り詰められるので、
    # 大きさが $offset より小さくなっていたら先頭から読み、時刻だけで区切る
    if (-not (Test-Path -LiteralPath $logPath)) { return $null }
    $text = $null
    try {
        $fs = [System.IO.File]::Open($logPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            if ($offset -gt 0 -and $fs.Length -ge $offset) { [void]$fs.Seek($offset, [System.IO.SeekOrigin]::Begin) }
            $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
            $text = $sr.ReadToEnd()
        } finally { $fs.Dispose() }
    } catch { return $null }
    $hit = $null
    foreach ($line in ($text -split "`r?`n")) {
        if ($line.Length -lt 20) { continue }
        $stamp = $line.Substring(0, 19)
        if ($stamp -notmatch '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$') { continue }
        if ([string]::CompareOrdinal($stamp, $since) -lt 0) { continue }
        if ($line.Contains('多重起動を検出したため終了します')) { $hit = $line }
    }
    return $hit
}

function Write-DeckList($procs) {
    foreach ($o in $procs) { Write-Host ("            PID {0}: {1}" -f $o.ProcessId, $o.CommandLine) }
}

function Invoke-DeckLaunch($lnkPath, $deckScript, $deckDir, $boardPath, $defaultBoard) {
    # Deck を起動し、常駐したか・同じボードを見る別の場所の Deck がいてすぐ終わったかを判定して知らせる。
    # 戻り値: 'running' / 'duplicate' / 'lockfail' / 'unconfirmed' / 'nolnk'（ショートカットが無く起動しなかった）
    #
    # 起動は手順4 のショートカットを explorer.exe で開いて行う（Start-Process で pythonw を直接
    # 起動しない）。直接起動すると Deck は setup を走らせたプロセスの子孫になり、そのプロセスが
    # 入っているジョブにも入る。Claude Code が setup を代わりに走らせた場合、Deck は Claude の
    # セッションのジョブに入り、Claude アプリが更新・再起動されたときに一緒に止まりうる
    # （2026-10-28 に本番で起きた停止の推定原因。ジョブに入ることは実測、止まった機構は未確認）。
    # 実測（2026-10-28・Windows 11 Home・Claude デスクトップアプリ 4.29 のセッションのシェルから・n=1）:
    #   Start-Process で起動した Deck はシェルと同じジョブに入り、祖先に claude.exe が並んだ。
    #   explorer.exe でショートカットを開いた Deck は、DcomLaunch（svchost）が起こした explorer.exe の
    #   子になり、シェルのジョブに入らなかった（その explorer.exe は約 60 秒で終わり、Deck は残った）。
    # 起動の引数はショートカットだけが持つ（ログオン時の起動と同じ形になる）。setup.ps1 の実行からは
    # 別の引数を渡せない（手順4 が毎回ショートカットを作り直す）。試験では -NoLaunch で配置し、
    # 引数を持たせた試験用のショートカットを作って Invoke-DeckLaunch を直接呼ぶ。
    $logPath = Join-Path $deckDir 'watcher.log'
    if (-not (Test-Path -LiteralPath $lnkPath)) {
        Write-Warn2 ("ショートカットが見つからないため、Deck を起動しませんでした: {0}" -f $lnkPath)
        return 'nolnk'
    }
    $since = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')   # 秒未満は切り捨て（Deck のログと同じ粒度）
    $offset = Get-DeckLogLength $logPath
    # PowerShell は explorer.exe（窓のプログラム）の終わりを待たず、終了コードも残らない
    # （実測で $LASTEXITCODE が空）。起動できたかは下のプロセスとログで判定する
    & (Join-Path $env:WINDIR 'explorer.exe') $lnkPath
    # プロセスが WMI に現れるまで待つ（最大 15 秒・fail-closed）。
    # 実測（2026-08-05・サンドボックス検証）: ショートカット起動から Deck が検出されるまで
    # 6 秒では未検出・9 秒以内に検出。5 秒待ちでは成功時にも警告が出ると考えられる（推定。
    # このループ自体は当該検証では未実行）。
    # すぐ終わる 2 本目は WMI に一度も現れないことがあるので、watcher.log も毎回見る。
    $dupLine = $null
    $running = @()
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        $running = @(Get-DeckProcesses $deckScript)
        if ($running.Count -gt 0) { break }
        $dupLine = Find-DeckDuplicateExit $logPath $since $offset
        if ($dupLine) { break }
    }
    # 起動用の別名経由なら、先に現れるのは起動役の親。子（実体）が現れるまで追加で待つ
    # （最大 10 秒・fail-closed。現れなければ見つかったものの PID を出す）。
    if ($running.Count -gt 0) {
        for ($i = 0; $i -lt 20; $i++) {
            $workers = @(Get-DeckWorkers $running | Where-Object { -not (Test-PyManagerLauncher $_) })
            if ($workers.Count -gt 0) { break }
            Start-Sleep -Milliseconds 500
            $running = @(Get-DeckProcesses $deckScript)
            if ($running.Count -eq 0) { break }
        }
    }
    # v1.9 以降の Deck は、同じボードを見る 2 本目が起動直後に終わる。最初に見えただけで
    # 「常駐開始」としないよう、約 3 秒後にもう一度探してまだ動いているかを確かめる。
    # 境界: 3 秒たっても Deck が多重起動ガードの判定まで届かない（極端に遅い）環境では、
    # 終わる前の 2 本目を「常駐開始」と出しうる。直後にログを読み直すので、その時点までに
    # 記録が出ていれば常駐とはみなさない（下の判定）。
    if ($running.Count -gt 0) {
        Start-Sleep -Seconds 3
        $running = @(Get-DeckProcesses $deckScript)
    }
    if (-not $dupLine) { $dupLine = Find-DeckDuplicateExit $logPath $since $offset }
    # ロックファイルを置けないとき（fail-closed）も Deck は同じ「多重起動を検出したため終了します」の
    # 行を書き、保持者の欄が「ロックファイルを開けません（…）」になる。これは 2 本目ではないので分ける
    $lockFail = [bool]($dupLine -and $dupLine.Contains('稼働中の1本目 → ロックファイルを開けません'))
    $workers = @(Get-DeckWorkers $running | Where-Object { -not (Test-PyManagerLauncher $_) })
    $others = @(Get-OtherDeckProcesses $deckScript)
    $same = @(); $diff = @(); $unknown = @()
    foreach ($o in $others) {
        switch (Get-DeckBoardRelation $o.CommandLine $boardPath $defaultBoard) {
            'same'      { $same    += $o }
            'different' { $diff    += $o }
            default     { $unknown += $o }
        }
    }

    # 起動後の watcher.log を書くのは、いま起動した Deck（起動用の別名経由ならその親子）だけ
    # （同じインストール先から、ほぼ同時に別の起動が無い限り。重なったときは、常駐していても
    # 「動いていない」と言う側に誤る）。そこに終了の記録（多重起動・ロックを置けない）が出ていれば、プロセスが見えていても
    # 終わる途中とみなし、常駐とはしない
    if ($running.Count -gt 0 -and -not $dupLine) {
        $shown = if ($workers.Count -gt 0) { $workers[0] } else { $running[0] }
        Write-Ok ("常駐開始（PID {0}）" -f $shown.ProcessId)
        if ($same.Count -gt 0) {
            # v1.9 以降どうしなら同じボードの 2 本目はすぐ終わる。両方が残るのはロックの基準が違う v1.8 以前
            Write-Warn2 '別の場所の Deck も同じ board.html を見ています（両方が動き続けているので、v1.8 以前の Deck と考えられます）。'
            Write-Warn2 '二重に board.html を書き換えるので、その Deck を止めてください:'
            Write-DeckList (Get-DeckShownProcesses $same)
        }
        if ($diff.Count -gt 0) {
            Write-Info2 '別の場所の Deck も動いていますが、別のボードを見ているので止めなくてかまいません:'
            Write-DeckList (Get-DeckShownProcesses $diff)
        }
        if ($unknown.Count -gt 0) {
            Write-Warn2 '別の場所の Deck も動いていますが、同じボードを見ているかどうか判定できません（--board の書き方や、フォルダの別名〔ジャンクション・短い名前〕のため）。'
            Write-Warn2 '同じ board.html を見ているなら、二重に書き換えるので止めてください:'
            Write-DeckList (Get-DeckShownProcesses $unknown)
        }
        return 'running'
    }
    if ($lockFail) {
        Write-Warn2 'ロックファイルを置けないため、Deck は起動しませんでした（同じボードへの二重書き込みを防ぐため、置けないときは起動しません）。'
        Write-Warn2 ("%TEMP%（{0}）に書き込めるか確かめてください。詳細は {1} にあります。" -f [System.IO.Path]::GetTempPath(), $logPath)
        return 'lockfail'
    }
    if ($dupLine) {
        $holder = $null
        $holderProcs = @()
        if ($dupLine -match '稼働中の1本目 → pid=(\d+)') {
            $holder = $Matches[1]
            $holderProcs = @($others | Where-Object { "$($_.ProcessId)" -eq $holder })
        }
        # 保持者の pid が分かっているのに一致するプロセスが無いときは、推測で一覧を出さず
        # ログの最後の行（保持者のスクリプトの場所が書かれている）へ案内する
        if (-not $holder) { $holderProcs = @(Get-DeckShownProcesses @($same + $unknown)) }
        if (-not $holder -and $holderProcs.Count -gt 0) { $holder = ($holderProcs | ForEach-Object { $_.ProcessId }) -join ', ' }
        $pidPart = if ($holder) { "（動いているのは PID $holder）" } else { '' }
        Write-Warn2 ('同じボードを見る Deck が別の場所で動いているため、インストールした Deck は起動しませんでした' + $pidPart + '。')
        Write-Warn2 'ボードはこのまま使えます。インストール先の Deck に切り替えるなら、その Deck を止めてから setup.bat をもう一度実行してください。'
        if ($holderProcs.Count -gt 0) { Write-DeckList $holderProcs }
        else { Write-Warn2 ("動いている Deck の場所は {0} の最後の行に書かれています。" -f $logPath) }
        return 'duplicate'
    }
    Write-Warn2 ("起動を確認できませんでした。{0}\watcher.log を見てください。" -f $deckDir)
    return 'unconfirmed'
}

# ---------------------------------------------------------------- 本体

Write-Host ''
Write-Host '=== きょうのボード セットアップ ===' -ForegroundColor White
Write-Host ("  スキル : " + $SkillDir)
Write-Host ("  Deck   : " + $DeckDir)
Write-Host ''

if (-not (Test-Path -LiteralPath (Join-Path $SrcSkill 'SKILL.md'))) {
    throw "配布物が不完全です: $SrcSkill\SKILL.md が見つかりません"
}
if (-not (Test-Path -LiteralPath (Join-Path $SrcDeck 'deck_watcher.py'))) {
    throw "配布物が不完全です: $SrcDeck\deck_watcher.py が見つかりません"
}

# --- 1. Python 3
Write-Step 1 'Python 3 を確認'
$python = Find-Python3
if (-not $python) {
    Write-Host ''
    Write-Host '  Python 3 が見つかりませんでした。' -ForegroundColor Red
    Write-Host '  Deck（常駐ウォッチャー）は Python 3 で動きます。先に入れてください。'
    Write-Host ''
    Write-Host '    入手先: https://www.python.org/downloads/windows/'
    Write-Host '    入れ方は README.md の「インストール」を参照してください。'
    Write-Host '    （従来のインストーラーなら、最初の画面で「Add python.exe to PATH」にチェック。'
    Write-Host '      Python install manager なら、入れた後に黒い窓で質問されます。確認したときの答え方は README にあります）'
    Write-Host ''
    Write-Host '  入れ終わったら、この setup.bat をもう一度ダブルクリックしてください。'
    Write-Host ''
    exit 1
}
$pythonw = Get-PythonwFor $python
Write-Ok $python
if ($pythonw -eq $python) {
    Write-Warn2 'pythonw.exe が見つかりません。起動時に黒いコンソールが出ます。'
}

# --- 2. スキル配置
Write-Step 2 'スキルを配置'
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $SkillDir 'assets') | Out-Null
Copy-Item -LiteralPath (Join-Path $SrcSkill 'SKILL.md') -Destination $SkillDir -Force
Copy-Item -Path (Join-Path $SrcSkill 'assets\*') -Destination (Join-Path $SkillDir 'assets') -Force -Recurse
# ライセンスの文面。setup で入れたスキルのフォルダにも skill/LICENSE を写す（Claude は読まない。
# board.html の隣へは写さない）。正本はリポジトリ直下の LICENSE で、skill/LICENSE はその写し
$skillLicense = ''
if (Test-Path -LiteralPath (Join-Path $SrcSkill 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $SrcSkill 'LICENSE') -Destination $SkillDir -Force
    $skillLicense = ' / LICENSE'
}

# ボードが実際に読むのは board.html と同じフォルダのアセット（board-template.html の
# <script src="board.js"> / <link href="board.css"> / <img src="cat.png"> はすべて相対参照）。
# スキル側だけを更新すると、既存インストールの実行系には古い board.js が残り続け、
# 修正が届かない。ここで毎回上書きする（$DataDir 側のこの3つは生成物であって
# 利用者データではない。board.html / *.json には触らない）。
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
foreach ($a in @('board.css', 'board.js', 'cat.png')) {
    $src = Join-Path $SrcSkill ('assets\' + $a)
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $DataDir -Force }
}
Write-Ok ('SKILL.md' + $skillLicense + ' / assets（ボードが読む board.css / board.js / cat.png も更新）')

# --- 3. Deck 配置
Write-Step 3 'Deck を配置'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $DeckDir | Out-Null

$deckScript = Join-Path $DeckDir 'deck_watcher.py'
$stopped = Stop-DeckProcesses $deckScript
if ($stopped -gt 0) { Write-Ok ("稼働中の Deck を停止（更新のため）: {0} 個" -f $stopped) }

$copied = 0
foreach ($f in (Get-ChildItem -LiteralPath $SrcDeck -File)) {
    if ($DeckRuntimeFiles -contains $f.Name) { continue }   # 利用者データを上書きしない
    Copy-Item -LiteralPath $f.FullName -Destination $DeckDir -Force
    $copied++
}
Write-Ok ("{0} ファイル（deck_watcher.py ほか。state.json / sound.json は保持）" -f $copied)

# 別の場所で動いている Deck は、ここでは知らせない（勝手に止めもしない）。止めるべきかは
# インストールした Deck が常駐できたかで変わるので、手順5 の起動の後で判定する
# （v1.9 以降は同じボードを見る 2 本目がすぐ終わるため、ここで「止めて」と案内すると
# 案内どおりに止めた結果 Deck が1つも動かなくなる）。

# --- 4. スタートアップ登録
Write-Step 4 'スタートアップに登録'
New-Item -ItemType Directory -Force -Path $StartupDir | Out-Null
$lnkPath = Join-Path $StartupDir $ShortcutName
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($lnkPath)
$lnk.TargetPath       = $pythonw
$lnk.Arguments        = '"' + $deckScript + '"'
$lnk.WorkingDirectory = $DeckDir
$lnk.WindowStyle      = 7          # 最小化（pythonw ならそもそも窓は出ない）
$lnk.Description      = 'today-board Deck watcher'
$lnk.Save()
Write-Ok $lnkPath

# 旧・手動登録のショートカットが残っていると二重起動になるので知らせる（勝手に消さない）
foreach ($other in (Get-ChildItem -LiteralPath $StartupDir -Filter '*.lnk' -File -ErrorAction SilentlyContinue)) {
    if ($other.Name -ieq $ShortcutName) { continue }
    try { $o = $wsh.CreateShortcut($other.FullName) } catch { continue }
    if (("$($o.TargetPath) $($o.Arguments)").ToLower().Contains('deck_watcher')) {
        Write-Warn2 ("古い Deck のショートカットが残っています。削除してください: " + $other.FullName)
    }
}

# --- 5. 起動
Write-Step 5 'Deck を起動'
# 起動した Deck が見るボード。起動に --board を渡さないので、deck_watcher.py の既定
# （DEFAULT_BOARD_PATH＝~/.claude/today-board/board.html）になる
$DefaultBoard = Join-Path $env:USERPROFILE '.claude\today-board\board.html'
$launchResult = 'nolaunch'
if ($NoLaunch) {
    Write-Warn2 '-NoLaunch 指定のため起動しません'
    $others = @(Get-OtherDeckProcesses $deckScript)
    if ($others.Count -gt 0) {
        Write-Info2 '別の場所で Deck が動いています（起動していないので、インストールした Deck との関係は判定していません）:'
        Write-DeckList (Get-DeckShownProcesses $others)
    }
} else {
    $launchResult = Invoke-DeckLaunch $lnkPath $deckScript $DeckDir $DefaultBoard $DefaultBoard
}

Write-Host ''
Write-Host '=== 完了 ===' -ForegroundColor Green
Write-Host '  Claude Code に「今日のタスクをボードにして」と言うとボードが出ます。'
switch ($launchResult) {
    'duplicate' {
        Write-Host '  スタートアップに登録したので、次回からは Windows のログオン時に Deck が起動します'
        Write-Host '  （別の場所の Deck が先に起動すると、インストールした Deck はすぐ終わります）。'
    }
    'lockfail' {
        Write-Host '  スタートアップに登録しましたが、今回は Deck が起動していません。上の案内を確かめてください'
        Write-Host '  （ロックファイルを置けないままだと、次回のログオン時も Deck は起動しません）。'
    }
    'nolnk' {
        Write-Host '  スタートアップのショートカットが見つからないため、今回は Deck を起動していません。上の案内を確かめてください'
        Write-Host '  （ショートカットが無いままだと、次回のログオン時も Deck は起動しません。setup.bat をもう一度実行してください）。'
    }
    'unconfirmed' {
        Write-Host '  スタートアップに登録しましたが、今回は Deck の起動を確認できていません。上の案内を確かめてください。'
    }
    default {
        Write-Host '  スタートアップに登録したので、次回からは Windows のログオン時に Deck が起動します。'
    }
}
Write-Host '  アンインストールは uninstall.bat です。'
Write-Host ''
exit 0
