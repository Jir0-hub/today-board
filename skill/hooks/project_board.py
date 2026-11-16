#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project_board.py v1.2 — 作業フォルダに対応するボードの行を見せ、更新し忘れを1回だけ止める（Claude Code のフック）。

Claude Code が hooks/hooks.json の登録どおりに起動する（make_hooks.py が書く。exec 形式で、小片 BOOT が
このファイルを runpy で走らせる）。入力はフックの JSON（標準入力）。出力は標準出力に JSON 1つか、何も出さない。
どんな失敗でも何も出さずに終了コード 0 で抜ける（フェイルオープン。依頼もターンの終わりも止めない）。

対応表（~/.claude/today-board/projects.json）:
  {"projects": [{"folder": "<作業フォルダの絶対パス>", "names": ["<ボードでのプロジェクト名>", "<別名>", …]}, …]}
  - 作業フォルダ（フック入力の cwd）が folder と同じか、その下（パスの区切りの境界で前方一致）なら、その項目に当たる。
    いくつも当たるときは folder が最も長い項目（同じ長さなら先に書いた項目）を採る。Windows では大文字小文字と / \\ の
    違いを同じとみなす。folder の先頭の ~ はホームのフォルダに読み替える
  - names が空の配列（[]）の項目は「このフォルダはプロジェクトに対応させない（対応表に足すかを聞かない）」の印。
    最長一致に加わるので、その下のフォルダに別の項目があればそちらが当たる。印に当たったフォルダでは両フックとも何もしない
  - フォルダ名から名前を推測しない。対応表が無い・JSON として読めない・形が違う・どの項目にも当たらないときは、
    どちらのフックも何も出さず、止めもしない。形の違う項目（folder が絶対パスでない・names が配列でない・names に
    空でない文字列が1つも無い〔[] を除く〕など）だけを飛ばす
  - 当たった項目の names のどれかについて、タイトルがその名前で始まる行・補足にその名前を含む行・見出しがその名前で
    始まる見出しの下の行を「そのプロジェクトの行」とする

- UserPromptSubmit: 入力に agent_id（空でない文字列）があれば何もしない（サブエージェント）。プロンプトが
  `<task-notification>` で始まるもの（バックグラウンドの完了の知らせ）でも何もしない。それ以外は、同じスキルの
  scripts/board_edit.py status を .guard/python.txt の Python で実行し（無ければこのフックを動かしている Python）、
  その JSON からプロジェクトの行を選んで hookSpecificOutput.additionalContext に入れる。済の行は件数だけにし、
  済以外の行は MAX_ROWS 行まで出す
- Stop: agent_id があるか、stop_hook_active が true なら何もしない。transcript の最後のターン（ターンの始まりの行より後。
  始まりの行は下の「transcript の行の形」。ファイルの先頭まで始まりが無く要約の行があれば、最も古い要約の行より後）で、
  Bash か PowerShell の呼び出しで git commit か
  git push を実行し、board_edit.py の書く操作を実行していなければ {"decision": "block", "reason": …} を返す。
  失敗した呼び出し（tool_result が is_error: true）は数えない。同じターンでこのフックが既に止めていれば止めない
  （1ターンに1回まで）

--check [--cwd <フォルダ>] で起動すると、対応表を読んだ結果（飛ばした項目と、そのフォルダが当たる項目。
対応させない印に当たったときは match.ignored が true）を JSON で出す（フックとしてではなく、人や Claude が対応表を確かめるため。読むだけ）。

入力・出力の形は公式ドキュメント（https://code.claude.com/docs/en/hooks.md の UserPromptSubmit・Stop の節）による。
transcript の行の形（type が "user" で isSidechain でない行のうち、ターンの始まりとみなすもの）:
  - origin.kind が "human"（isMeta でないもの）・"peer"・"task-notification" の行（本物のユーザーの発言・他のセッションの
    メッセージ・完了の知らせ）
  - origin が無く、isMeta でも要約（isCompactSummary）でもなく、promptSource（空でない文字列）を持ち、中身が tool_result
    だけではない行（他のセッションが立てたセッションの最初の依頼・アプリが入れる依頼など。promptSource は、origin の無い行では "sdk" だけを観測。origin を持つ行には "system" などもある）
  - ターンの途中に現れる origin の無い行（tool_result・"[Request interrupted by user…]"・"Stop hook feedback:"〔isMeta〕・
    ローカルのコマンド〔<command-name> など〕・要約）は promptSource を持たず、始まりとみなさない。キューに入った依頼は
    type が "attachment" の行で、user の行ではない
  - 要約の行（isCompactSummary が true）は始まりとみなさない（自動の要約はターンの途中にも入り、同じファイルの前の行に
    そのターンの始まりがあることがある）。ファイルの先頭まで始まりが無いときだけ、最も古い要約の行を区切りに使う
  この形は 2026-11-16 に ~/.claude/projects の transcript 233 本（Claude Code 2.1.219〜2.1.325）で数えて確かめた。
  "Stop hook feedback:" の形（type が "user"・isMeta が true・origin が無い・message.content が "Stop hook feedback:" で始まる
  文字列）は、このフックが止めた実物の行で確かめた（2026-11-16。~/.claude/projects の transcript 4本〔2プロジェクト〕の
  各1行・version 2.1.325。どの行も本文に STOP_MARK を含む）。
Python 3 標準ライブラリのみ・単一ファイル。外部ネットワーク通信はしない。
"""

import json
import os
import re
import shlex
import subprocess
import sys

VERSION = "1.2"

MAP_NAME = "projects.json"
STATUS_TIMEOUT_SEC = 8   # hooks.template.json の timeout（15 秒）より短く
NOTE_MAX = 120
TITLE_MAX = 120
MAX_ROWS = 40
CHIP_LABELS = {
    "done": "済", "active": "進行中", "pending": "未", "wait": "条件待ち", "hold": "保留",
    "none": "チップなし",
}
CONTEXT_MARK = "【today-board の行の照合】"
STOP_MARK = "【today-board の更新確認】"


def _case_insensitive_paths():
    return os.name == "nt"


# ================================================================ 対応表

def data_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "today-board")


def map_file():
    return os.path.join(data_dir(), MAP_NAME)


def norm_path(path, fold_case=None):
    """比べるためのパス（区切りは /・末尾の / なし・Windows では小文字）。絶対パスでなければ None。"""
    if not isinstance(path, str) or not path.strip():
        return None
    p = os.path.expanduser(path.strip())
    p = p.replace("\\", "/")
    is_abs = p.startswith("/") or re.match(r"^[A-Za-z]:/", p) is not None
    if not is_abs:
        return None
    drive = ""
    m = re.match(r"^([A-Za-z]:)(/.*)$", p)
    if m:
        drive, p = m.group(1), m.group(2)
    parts = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    out = drive + "/" + "/".join(parts)
    if out != "/" and out.endswith("/"):
        out = out[:-1]
    if fold_case is None:
        fold_case = _case_insensitive_paths()
    return out.lower() if fold_case else out


def under(path_n, folder_n):
    """path_n が folder_n と同じか、その下か（区切りの境界で前方一致）。どちらも norm_path 済み。"""
    if path_n == folder_n:
        return True
    base = folder_n if folder_n.endswith("/") else folder_n + "/"
    return path_n.startswith(base)


def parse_map(doc, fold_case=None):
    """対応表の JSON から ([(folder_n, folder, names)], [(index, 飛ばした理由)]) を返す。全体の形が違えば ValueError。

    names が空の配列（[]）の項目は、対応させない印として names=[] のまま入れる（最長一致に加わり、当たれば何もしない）。
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("projects"), list):
        raise ValueError('一番外が {"projects": [...]} の形でない')
    entries, skipped = [], []
    for i, e in enumerate(doc["projects"]):
        if not isinstance(e, dict):
            skipped.append((i, "項目が {…} でない"))
            continue
        folder = e.get("folder")
        fn = norm_path(folder, fold_case)
        if fn is None:
            skipped.append((i, "folder が絶対パスの文字列でない"))
            continue
        names = e.get("names")
        if not isinstance(names, list):
            skipped.append((i, "names が配列でない"))
            continue
        if not names:
            entries.append((fn, folder, []))    # 空の names＝このフォルダはプロジェクトに対応させない（聞かない）印
            continue
        valid = [n.strip() for n in names if isinstance(n, str) and n.strip()]
        clean = list(dict.fromkeys(valid))      # 重なりを除く（順は保つ）
        if not clean:
            skipped.append((i, "names に空でない文字列が無い"))
            continue
        if len(valid) != len(names):
            skipped.append((i, "names に空の文字列か文字列でない値がある（その値だけ飛ばした）"))
        entries.append((fn, folder, clean))
    return entries, skipped


def load_map(path=None, fold_case=None):
    """対応表を読む。(entries, skipped)。無い・読めない・形が違うときは ValueError か OSError。"""
    with open(path or map_file(), "rb") as f:
        doc = json.loads(f.read().decode("utf-8-sig"))
    return parse_map(doc, fold_case)


def match_entry(entries, cwd, fold_case=None):
    """作業フォルダが当たる項目 (folder_n, folder, names)。当たらなければ None。"""
    cn = norm_path(cwd, fold_case)
    if cn is None:
        return None
    best = None
    for e in entries:
        if under(cn, e[0]) and (best is None or len(e[0]) > len(best[0])):
            best = e
    return best


def names_for_cwd(cwd, path=None):
    """作業フォルダに対応する名前の並び。対応表が無い・壊れている・当たらない・対応させない印に当たったときは
    None（＝何もしない）。"""
    try:
        entries, _skipped = load_map(path)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    hit = match_entry(entries, cwd)
    return hit[2] if hit and hit[2] else None


# ================================================================ 行の選び方・文脈

def _clip(text, limit):
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit] + "…(以下略)"


def is_project_row(names, section_name, item):
    title = item.get("title") or ""
    note = item.get("note") or ""
    if not isinstance(title, str) or not isinstance(note, str):
        return False
    sec = section_name if isinstance(section_name, str) else ""
    return any(title.startswith(n) or n in note or sec.startswith(n) for n in names)


def select_rows(names, status):
    """status の JSON からプロジェクトの行を (見出し, item) の並びで返す。形が想定と違えば ValueError。"""
    sections = status.get("sections")
    if not isinstance(sections, list):
        raise ValueError("sections が無い")
    rows = []
    for sec in sections:
        if not isinstance(sec, dict) or not isinstance(sec.get("items"), list):
            raise ValueError("sections の形が違う")
        name = sec.get("name")
        for item in sec["items"]:
            if isinstance(item, dict) and is_project_row(names, name, item):
                rows.append((name if isinstance(name, str) else "?", item))
    return rows


def format_row(section_name, item):
    chip = item.get("chip")
    chip_label = CHIP_LABELS.get(chip, str(chip)) if chip is not None else "チップなし"
    parts = ["[{}]".format(section_name), "状態: " + chip_label]
    if item.get("time"):
        parts.append("時刻: {}".format(item["time"]))
    parts.append("タイトル: " + _clip(item.get("title") or "", TITLE_MAX))
    parts.append("実施日: {}".format(item.get("due") or "なし"))
    note = item.get("note") or ""
    parts.append("補足: " + (_clip(note, NOTE_MAX) if note else "なし"))
    return "- " + " / ".join(parts)


def label(names):
    """「A」か「A」（別名「B」「C」）。"""
    head = "「%s」" % names[0]
    if len(names) > 1:
        head += "（別名 %s）" % "".join("「%s」" % n for n in names[1:])
    return head


def build_context(names, status):
    """status の JSON から additionalContext の文を作る。作れなければ None。"""
    if not isinstance(status, dict) or status.get("ok") is not True:
        return None
    rows = select_rows(names, status)
    lines = [CONTEXT_MARK + "当日ボード（~/.claude/today-board/board.html）のうち、この作業フォルダに対応する"
             "プロジェクト%sの行です（対応表 ~/.claude/today-board/%s と board_edit.py status から作成）。"
             "この依頼に対応する行があるか確かめてください。作業で状態が変わったら（着手・完了・保留・新しい作業）、"
             "today-board の SKILL.md の手順どおり board_edit.py で更新してください"
             "（対応する行が無い作業は「今日中」に足す）。" % (label(names), MAP_NAME)]
    board_date = status.get("board_date")
    today = status.get("today")
    if board_date and today and board_date != today:
        lines.append("注意: ボードの日付は {} で、今日（{}）ではありません。".format(board_date, today))
    if not rows:
        lines.append("いまのボードに%sの行はありません。" % label(names))
        return "\n".join(lines)
    open_rows = [(n, it) for n, it in rows if it.get("chip") != "done"]
    done_count = len(rows) - len(open_rows)
    lines.append("%sの行（%d 行。うち済 %d 行）:" % (label(names), len(rows), done_count))
    for name, item in open_rows[:MAX_ROWS]:
        lines.append(format_row(name, item))
    if len(open_rows) > MAX_ROWS:
        lines.append("ほか済以外 {} 行（board_edit.py status で確かめる）".format(len(open_rows) - MAX_ROWS))
    if done_count:
        lines.append("済 {} 行（board_edit.py status で確かめる）".format(done_count))
    return "\n".join(lines)


def board_edit_path():
    """同じスキルの scripts/board_edit.py（このファイルは <スキル>/hooks/ にある）。"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "board_edit.py")


def python_for_board_edit():
    """.guard/python.txt の Python（SKILL.md「呼び方」）。無ければ・実在しなければ、このフックを動かしている Python。"""
    try:
        with open(os.path.join(data_dir(), ".guard", "python.txt"), "r", encoding="utf-8-sig") as f:
            py = f.read().strip()
        if py and os.path.isfile(py):
            return py
    except (OSError, UnicodeDecodeError):
        pass
    return sys.executable


def fetch_status():
    """board_edit.py status を実行して JSON を返す。できなければ None。"""
    script = board_edit_path()
    python = python_for_board_edit()
    if not os.path.isfile(script) or not python:
        return None
    try:
        p = subprocess.run([python, script, "status"], capture_output=True,
                           timeout=STATUS_TIMEOUT_SEC, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _is_subagent(data):
    aid = data.get("agent_id")
    return isinstance(aid, str) and aid != ""


def on_prompt(data, fetch=fetch_status, names_of=names_for_cwd):
    prompt = data.get("prompt")
    if isinstance(prompt, str) and prompt.lstrip().startswith("<task-notification>"):
        return None
    names = names_of(data.get("cwd"))
    if not names:
        return None
    status = fetch()
    if status is None:
        return None
    context = build_context(names, status)
    if not context:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}


# ================================================================ コマンドの判定（Stop）

# board_edit.py の操作のうち、板を書くもの（remove・restore は --confirmed のときだけ書く）。
# 書かないもの＝status・deck-snap・deck-wait（と、操作の無い --help・--version）。
WRITE_OPS = frozenset({"create", "add", "set-chip", "edit", "set-crit", "set-time", "set-due", "move", "close-time"})
CONFIRM_OPS = frozenset({"remove", "restore"})
SEP_CHARS = ";&|()\n"
GIT_OPTS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_PS_HERE_OPEN_RE = re.compile(r"@(['\"])\s*$")


def _word_start(text, i, shell, quote_closes, escaped=frozenset(), start_ws=True):
    """text[i] が語の始まりか（# が注釈を始める位置か）。

    bash: 先頭・空白・区切り（SEP_CHARS）の直後。PowerShell ではさらに {・}・, の直後と、語の始まりで開いた
    クォートを閉じた直後（"a"#x の # は注釈。a"b"#x の # は語のまま）。PowerShell の読み方は 2026-11-16 に
    Windows PowerShell 5.1 の [System.Management.Automation.Language.Parser]::ParseInput の字句で確かめた。
    = や + の直後（$a=#x は注釈・echo =#x は語）のように、読み方が文脈で変わる形は語のままとみなす。
    直前の文字がエスケープした文字（escaped に入っている位置。`, や `{ など）なら語の続きで、語の始まりではない。
    ただしエスケープした改行（行の継続）は、継続を除いた後の並びで見る（エスケープの文字の前の文字で決める）。"""
    # エスケープした改行（行の継続）の直後は、継続を除いた並びで見る＝エスケープの文字の位置が語の始まりかで決める。
    # 継続が何行続いても深さが増えないよう、再帰でなく繰り返しで戻る。text の先頭（i == 0）は start_ws で決める
    # （行ごとに見分けるとき、前の行が継続で終わっていれば、その継続の位置が語の始まりだったか＝_classify の状態の4つ目）
    while i >= 2 and (i - 1) in escaped and text[i - 1] == "\n":
        i -= 2
    if i == 0:
        return start_ws
    prev = text[i - 1]
    if (i - 1) in escaped:
        return False
    if prev in " \t\r" or prev in SEP_CHARS:
        return True
    if shell == "powershell":
        if prev in "{},":
            return True
        if (i - 1) in quote_closes:
            return True
    return False


def _classify(text, shell, state=None):
    """text の各文字の種類の並び（"c"＝コード・"q"＝クォートの中・"x"＝# の注釈・"B"/"b"＝<# … #> の始まり/続き）と、
    末尾の状態を返す。state は前の行から持ち越す (クォートの文字, そのクォートが語の始まりで開いたか, <# の中か)。"""
    ps = shell == "powershell"
    esc = "`" if ps else "\\"
    # state の4つ目＝前の行が行の継続（クォート・注釈の外の、対にならないエスケープの文字）で終わったとき、その位置が
    # 語の始まりだったか（True / False）。継続で終わっていなければ None（行の先頭は語の始まり）
    quote, q_word, in_block, cont_ws = (tuple(state) + (None,) * 4)[:4] if state else (None, False, False, None)
    start_ws = True if cont_ws is None else cont_ws
    end_cont_ws = None
    n = len(text)
    kinds = ["c"] * n
    quote_closes = set()
    escaped = set()
    i = 0
    while i < n:
        c = text[i]
        if in_block:
            j = text.find("#>", i)
            end = n if j == -1 else j + 2
            for k in range(i, end):
                kinds[k] = "b"
            if j != -1:
                in_block = False
            i = end
            continue
        if quote:
            kinds[i] = "q"
            if c == esc and quote == '"' and i + 1 < n:
                kinds[i + 1] = "q"
                i += 2
                continue
            if c == quote:
                quote = None
                if q_word:
                    quote_closes.add(i)
            i += 1
            continue
        if c == esc and i + 1 < n:
            escaped.add(i + 1)
            i += 2
            continue
        if c == esc:
            # 末尾の対にならないエスケープの文字＝行の継続。次の行の先頭の # が注釈かは、この位置が語の始まりかで決まる
            end_cont_ws = _word_start(text, i, shell, quote_closes, escaped, start_ws)
            i += 1
            continue
        if c in "'\"":
            q_word = _word_start(text, i, shell, quote_closes, escaped, start_ws)
            quote = c
            kinds[i] = "q"
            i += 1
            continue
        if ps and text.startswith("<#", i):
            kinds[i] = "B"
            in_block = True
            i += 1
            j = text.find("#>", i + 1)
            end = n if j == -1 else j + 2
            for k in range(i, end):
                kinds[k] = "b"
            if j != -1:
                in_block = False
            i = end
            continue
        if c == "#" and _word_start(text, i, shell, quote_closes, escaped, start_ws):
            j = text.find("\n", i)
            end = n if j == -1 else j
            for k in range(i, end):
                kinds[k] = "x"
            i = end
            continue
        i += 1
    return kinds, (quote, q_word, in_block, end_cont_ws)


def _in_comment(kinds, pos):
    return kinds[pos] in ("x", "B", "b")


def _drop_cont(state):
    # 状態から「前の行が継続で終わった」を外す（ヒアドキュメントの本文・ヒア文字列の後ろの行のため）
    return tuple(state[:3]) + (None,) if state else state


def strip_heredoc_bodies(command):
    """bash のヒアドキュメントの本文の行を取り除く（コミットメッセージの中の語で誤判定しないため）。
    注釈の中の <<EOF はヒアドキュメントの印とみなさない（後ろの行を本文として捨てない）。"""
    out = []
    pending = []
    state = None
    for line in command.split("\n"):
        if pending:
            delim, strip_tabs = pending[0]
            cmp = line.lstrip("\t") if strip_tabs else line
            if cmp.rstrip("\r") == delim:
                pending.pop(0)
            state = _drop_cont(state)       # 本文の後ろの行は、開いた行の継続の続きではない
            continue
        out.append(line)
        # 状態は1行ずつ持ち越す（前の行の継続の位置が語の始まりかも状態に入る＝前の行たちを並べ直さない）
        kinds, state = _classify(line, "bash", state)
        for m in _HEREDOC_RE.finditer(line):
            if not _in_comment(kinds, m.start()):
                pending.append((m.group(3), m.group(1) == "-"))
    return "\n".join(out)


def strip_ps_herestrings(command):
    """PowerShell のヒア文字列（@' … '@・@" … "@）の本文の行を取り除く。開く記号は語 @HERE に置き換える。
    注釈の中の @' はヒア文字列の始まりとみなさない。"""
    out = []
    closer = None
    state = None
    for line in command.split("\n"):
        line_r = line.rstrip("\r")
        if closer:
            if line_r.startswith(closer):
                out.append(line_r[len(closer):])
                closer = None
                state = None
            continue
        kinds, new_state = _classify(line_r, "powershell", state)
        m = _PS_HERE_OPEN_RE.search(line_r)
        if m and not _in_comment(kinds, m.start()):
            out.append(line_r[:m.start()] + "@HERE")
            closer = m.group(1) + "@"
            state = _drop_cont(state)       # 閉じた後の行は、開いた行の前の継続の続きではない
            continue
        state = new_state
        out.append(line_r)
    return "\n".join(out)


# 行の継続は、改行の直前のエスケープの文字が奇数個のときだけ（\\＋改行・``＋改行はエスケープした文字と改行）
_CONT_RE = {"bash": re.compile(r"(?<!\\)((?:\\\\)*)\\\r?\n"),
            "powershell": re.compile(r"(?<!`)((?:``)*)`\r?\n")}


def join_continuations(text, shell):
    """行の継続（bash の \\＋改行、PowerShell の `＋改行）を空白に置き換える（継続で語が切れて操作を見落とさないため）。
    エスケープした \\・` の後ろの改行（\\\\＋改行・``＋改行）は継続ではないので残す。
    注釈の中の行末の \\・` も継続ではない（注釈は改行で終わり、次の行は別のコマンド）ので残す。"""
    shell = "powershell" if shell == "powershell" else "bash"
    kinds, _state = _classify(text, shell)

    def _join(m):
        if _in_comment(kinds, m.start() + len(m.group(1))):
            return m.group(0)
        # 継続の後ろが # なら、継続を除いた並び（a\＋改行＋#x は a#x の1語）のまま残す。空白に置き換えると
        # # が語の始まりになり、注釈と読んでその後ろ（; git push など）を見落とす。継続の前が空白・区切りなら
        # どちらでも # は注釈の始まり（_word_start がエスケープの文字の前の文字で決める）
        if text.startswith("#", m.end()):
            return m.group(1)
        return m.group(1) + " "
    return _CONT_RE[shell].sub(_join, text)


def strip_comments(text, shell):
    """注釈を除く。# は語の始まり（_word_start）でクォートの外のときだけ注釈とみなす（a#b は語のまま）。
    PowerShell では <# … #> も除く（1つの空白に置き換える）。注釈の後ろの改行は残す（次の行は別のコマンド）。"""
    kinds, _state = _classify(text, shell)
    out = []
    for ch, k in zip(text, kinds):
        if k in ("x", "b"):
            continue
        out.append(" " if k == "B" else ch)
    return "".join(out)


def _tokens(command, shell):
    """シェルの語の並び（区切りは独立した語）。読めなければ None。shell は "bash" か "powershell"。"""
    if shell == "powershell":
        text = strip_ps_herestrings(command)
    else:
        text = strip_heredoc_bodies(command)
    text = strip_comments(join_continuations(text, shell), shell)
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=SEP_CHARS)
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        lex.commenters = ""            # 注釈は strip_comments で除いた（語の途中の # は語のまま）
        if shell == "powershell":
            lex.escape = "`"          # PowerShell のエスケープは ` （\ はパスの区切りのまま残す）
        return list(lex)
    except ValueError:
        return None


def _segments(toks):
    seg = []
    for t in toks:
        if t and set(t) <= set(SEP_CHARS):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(t)
    if seg:
        yield seg


def _basename(word):
    return re.split(r"[\\/]", word)[-1].lower()


def is_git_commit_or_push(command, shell="bash"):
    toks = _tokens(command, shell)
    if toks is None:
        body = strip_ps_herestrings(command) if shell == "powershell" else strip_heredoc_bodies(command)
        return re.search(r"(?:^|[\s;&|(])git(?:\.exe)?\s+(?:-\S+\s+)*(?:commit|push)\b", body) is not None
    for seg in _segments(toks):
        for i, w in enumerate(seg):
            if _basename(w) not in ("git", "git.exe"):
                continue
            j = i + 1
            while j < len(seg) and seg[j].startswith("-"):
                opt = seg[j].split("=", 1)[0]
                j += 2 if (opt in GIT_OPTS_WITH_VALUE and "=" not in seg[j]) else 1
            if j < len(seg) and seg[j] in ("commit", "push"):
                return True
    return False


def is_board_write(command, shell="bash"):
    toks = _tokens(command, shell)
    if toks is None:
        return False
    for seg in _segments(toks):
        for i, w in enumerate(seg):
            if not w.lower().endswith("board_edit.py"):
                continue
            args = seg[i + 1:]
            if any(a == "--ops" or a.startswith("--ops=") for a in args):
                return True
            op = next((a for a in args if not a.startswith("-")), None)
            if op in WRITE_OPS:
                return True
            if op in CONFIRM_OPS and "--confirmed" in args:
                return True
    return False


SHELL_TOOLS = {"Bash": "bash", "PowerShell": "powershell"}


# ================================================================ transcript（Stop）

CHUNK = 1 << 20
MAX_READ_BYTES = 64 << 20


class TruncatedRead(Exception):
    pass


def iter_lines_reverse(path, max_bytes=MAX_READ_BYTES):
    """ファイルの行を末尾から返す（bytes）。max_bytes を超えて読んだら TruncatedRead を出す。"""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        buf = b""
        read = 0
        while pos > 0:
            if read >= max_bytes:
                raise TruncatedRead()
            size = min(CHUNK, pos)
            pos -= size
            f.seek(pos)
            buf = f.read(size) + buf
            read += size
            parts = buf.split(b"\n")
            buf = parts[0]
            for line in reversed(parts[1:]):
                if line.strip():
                    yield line
        if buf.strip():
            yield buf


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(x.get("text", "") for x in content
                       if isinstance(x, dict) and isinstance(x.get("text"), str))
    return ""


TURN_START_KINDS = ("human", "peer", "task-notification")


def _only_tool_results(content):
    return (isinstance(content, list) and bool(content)
            and all(isinstance(x, dict) and x.get("type") == "tool_result" for x in content))


def _is_turn_start(d):
    if d.get("type") != "user" or d.get("isSidechain"):
        return False
    origin = d.get("origin")
    if isinstance(origin, dict):
        kind = origin.get("kind")
        if kind == "human":
            return not d.get("isMeta")
        return kind in TURN_START_KINDS
    # origin の無い依頼（他のセッションが立てたセッションの最初の依頼・アプリが入れる依頼など）は
    # promptSource を持つ。ターンの途中の行（tool_result・中断・Stop hook feedback・要約・ローカルのコマンド）は持たない
    if d.get("isMeta") or d.get("isCompactSummary"):
        return False
    ps = d.get("promptSource")
    if not (isinstance(ps, str) and ps):
        return False
    msg = d.get("message")
    return not (isinstance(msg, dict) and _only_tool_results(msg.get("content")))


def _is_compact_summary(d):
    return d.get("type") == "user" and not d.get("isSidechain") and d.get("isCompactSummary") is True


def scan_turn(path, max_bytes=None):
    """このターンの Bash・PowerShell の呼び出しを調べる。

    返り値: {"worked": bool, "board_updated": bool, "already_blocked": bool}。ターンの始まりが見つからなければ None。
    ファイルの先頭まで始まりが無く、途中に要約の行（isCompactSummary）があったときは、最も古い要約の行より後を
    このターンとみなす（要約で引き継いだファイルは、ターンの始まりが前のファイルにある）。
    """
    error_ids = set()
    worked = board = blocked = False
    since_summary = None
    for raw in iter_lines_reverse(path, MAX_READ_BYTES if max_bytes is None else max_bytes):
        if (b'"human"' not in raw and b'"peer"' not in raw and b'"task-notification"' not in raw
                and b'"promptSource"' not in raw and b'"isCompactSummary"' not in raw
                and b'"tool_use"' not in raw and b'"tool_result"' not in raw
                and b"Stop hook feedback" not in raw):
            continue
        try:
            d = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("isSidechain"):
            continue
        if _is_turn_start(d):
            return {"worked": worked, "board_updated": board, "already_blocked": blocked}
        if _is_compact_summary(d):
            since_summary = {"worked": worked, "board_updated": board, "already_blocked": blocked}
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if d.get("type") == "user":
            if d.get("isMeta"):
                text = _content_text(content)
                if text.startswith("Stop hook feedback") and STOP_MARK in text:
                    blocked = True
                continue
            if isinstance(content, list):
                for x in content:
                    if isinstance(x, dict) and x.get("type") == "tool_result" and x.get("is_error") is True:
                        error_ids.add(x.get("tool_use_id"))
        elif d.get("type") == "assistant" and isinstance(content, list):
            for x in content:
                if not (isinstance(x, dict) and x.get("type") == "tool_use"):
                    continue
                shell = SHELL_TOOLS.get(x.get("name"))
                if shell is None or x.get("id") in error_ids:
                    continue
                inp = x.get("input")
                cmd = inp.get("command") if isinstance(inp, dict) else None
                if not isinstance(cmd, str):
                    continue
                if is_git_commit_or_push(cmd, shell):
                    worked = True
                if is_board_write(cmd, shell):
                    board = True
    return since_summary


def stop_reason(names):
    return (STOP_MARK + "このターンでコミットか push をしたが、当日ボードの行を更新していない。"
            "この作業フォルダのプロジェクト%sの該当する行を board_edit.py で更新してから終えること"
            "（today-board の SKILL.md の手順。対応する行が無い作業なら「今日中」に足す）。"
            "行の更新も追加も要らない作業なら、その理由を最後の返答に書いて終えること。"
            "このフックが止めるのは1ターンに1回だけで、次はそのまま終えられる。" % label(names))


def on_stop(data, scan=scan_turn, names_of=names_for_cwd):
    if data.get("stop_hook_active") is True:
        return None
    path = data.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None
    names = names_of(data.get("cwd"))
    if not names:
        return None
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return None
    try:
        result = scan(path)
    except TruncatedRead:
        return None
    if not result or result["already_blocked"]:
        return None
    if result["worked"] and not result["board_updated"]:
        return {"decision": "block", "reason": stop_reason(names)}
    return None


# ================================================================ 入口

def dispatch(data, **kw):
    if not isinstance(data, dict) or _is_subagent(data):
        return None
    event = data.get("hook_event_name")
    if event == "UserPromptSubmit":
        return on_prompt(data, **{k: v for k, v in kw.items() if k in ("fetch", "names_of")})
    if event == "Stop":
        return on_stop(data, **{k: v for k, v in kw.items() if k in ("scan", "names_of")})
    return None


def check(cwd, path=None):
    """--check の出力（dict）。"""
    path = path or map_file()
    out = {"ok": True, "version": VERSION, "file": path, "exists": os.path.isfile(path), "error": None,
           "entries": 0, "skipped": [], "cwd": cwd, "match": None}
    if not out["exists"]:
        out["ok"] = False
        out["error"] = "対応表がありません（フックは何もしません）"
        return out
    try:
        entries, skipped = load_map(path)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        out["ok"] = False
        out["error"] = "対応表を読めません（フックは何もしません）: %s" % e
        return out
    out["entries"] = len(entries)
    out["skipped"] = [{"index": i, "why": why} for i, why in skipped]
    hit = match_entry(entries, cwd) if cwd else None
    if hit:
        out["match"] = {"folder": hit[1], "names": hit[2], "ignored": not hit[2]}
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--check":
        cwd = os.getcwd()
        if len(argv) >= 3 and argv[1] == "--cwd":
            cwd = argv[2]
        res = check(cwd)
        sys.stdout.buffer.write((json.dumps(res, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0 if res["ok"] else 1
    out = None
    try:
        raw = sys.stdin.buffer.read()
        data = json.loads(raw.decode("utf-8-sig")) if raw.strip() else None
        out = dispatch(data)
    except BaseException:  # noqa: BLE001 - フェイルオープン: 依頼もターンの終わりも止めない
        out = None
    if out is not None:
        try:
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=True).encode("ascii"))
            sys.stdout.buffer.flush()
        except BaseException:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
