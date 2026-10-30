#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_hooks.py v1.0 — hooks.template.json から hooks.json を作る（きょうのボードの保護のフック）。

使い方: python make_hooks.py --python <Python 3 の実行ファイルの絶対パス> [--template <雛形>] [--out <書き出し先>]
  既定の雛形・書き出し先は、このファイルと同じフォルダの hooks.template.json・hooks.json。

雛形の文字列の値 "@PYTHON@" を --python のパスに、"@BOOT@" を下の小片（BOOT）に置き換える。
JSON は Python が作る（PowerShell の ConvertTo-Json は使わない）。書き出しは同じフォルダの一時ファイルに書いてから
os.replace で置き換える（書きかけの hooks.json を、その時に始まったセッションが読まないため）。
書けたら、command と各フックの args の要素数を標準出力に出す。失敗は終了コード 1 と理由（標準エラー）。

小片（BOOT）の正本はこのファイル。exec 形式で `<python> -I -c <BOOT> <プラグインのフォルダ>/hooks/guard.py` と起動され、
guard.py があれば runpy で走らせ、無い・構文エラー・例外・sys.exit(2) のどれでも何も出さずに終了コード 0 で抜ける
（PreToolUse の終了コード 2 は「止める」合図で、guard.py が消えている間に全ツールが止まるのを防ぐため）。
Python 3 標準ライブラリのみ。
"""

import argparse
import json
import os
import sys
import tempfile

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
PY_TOKEN = "@PYTHON@"
BOOT_TOKEN = "@BOOT@"

BOOT = ("import os,sys,runpy\n"
        "try:\n"
        " p=sys.argv[1]\n"
        " if os.path.isfile(p):\n"
        "  sys.argv=sys.argv[1:]\n"
        "  runpy.run_path(p,run_name='__main__')\n"
        "except BaseException:\n"
        " pass\n"
        "try:\n"
        " sys.stdout.flush()\n"
        "except BaseException:\n"
        " pass\n"
        "os._exit(0)")


def fill(node, python):
    """雛形の木を辿り、置き換えた写しと置き換えた数 [python, boot] を返す。"""
    count = [0, 0]

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if x == PY_TOKEN:
            count[0] += 1
            return python
        if x == BOOT_TOKEN:
            count[1] += 1
            return BOOT
        if isinstance(x, str) and (PY_TOKEN in x or BOOT_TOKEN in x):
            raise ValueError("雛形の文字列の一部に %s か %s があります（値の全体でなければ置き換えません）: %r"
                             % (PY_TOKEN, BOOT_TOKEN, x))
        return x

    return walk(node), count


def summary(hooks):
    """(command の集合, [(イベント, matcher, args の要素数)])。"""
    cmds = set()
    rows = []
    for event, groups in sorted((hooks.get("hooks") or {}).items()):
        for g in groups:
            for h in g.get("hooks") or []:
                cmds.add(h.get("command"))
                rows.append((event, g.get("matcher", ""), len(h.get("args") or [])))
    return cmds, rows


def write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".hooks-", suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="hooks.template.json から hooks.json を作る")
    ap.add_argument("--python", required=True, help="フックを起動する Python 3 の実行ファイルの絶対パス")
    ap.add_argument("--template", default=os.path.join(HERE, "hooks.template.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "hooks.json"))
    ap.add_argument("--version", action="version", version=VERSION)
    a = ap.parse_args(argv)
    py = a.python.strip().strip('"')
    if not py or not os.path.isabs(py):
        sys.stderr.write("make_hooks.py: --python には絶対パスを渡してください（%r）。hooks.json は書いていません。\n" % a.python)
        return 1
    if not os.path.isfile(py):
        sys.stderr.write("make_hooks.py: --python のファイルがありません（%s）。hooks.json は書いていません。\n" % py)
        return 1
    try:
        with open(a.template, "rb") as f:
            tpl = json.loads(f.read().decode("utf-8-sig"))
        out, count = fill(tpl, py)
    except (OSError, ValueError) as e:
        sys.stderr.write("make_hooks.py: 雛形を読めません（%s）。hooks.json は書いていません。\n" % e)
        return 1
    cmds, rows = summary(out)
    if not rows or count[0] != len(rows) or count[1] != len(rows) or cmds != {py}:
        sys.stderr.write("make_hooks.py: 雛形の形が想定と違います（フック %d 件・@PYTHON@ %d 件・@BOOT@ %d 件）。"
                         "hooks.json は書いていません。\n" % (len(rows), count[0], count[1]))
        return 1
    data = (json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        write_atomic(a.out, data)
    except OSError as e:
        sys.stderr.write("make_hooks.py: hooks.json を書けません（%s）。\n" % e)
        return 1
    sys.stdout.write("hooks.json: %s\ncommand: %s\n" % (a.out, py))
    for event, matcher, n in rows:
        sys.stdout.write("  %s [%s] args %d\n" % (event, matcher or "-", n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
