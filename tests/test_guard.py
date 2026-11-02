# -*- coding: utf-8 -*-
"""skill/hooks/guard.py・make_hooks.py の試験（T-G と、board_edit.py との写しの一致 T-P）。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
すべて一時フォルダのサンドボックスで行う。HOME / USERPROFILE を一時フォルダへ向けるので、guard.py が見る
「本番」（~/.claude/today-board/）も一時フォルダの中になる。本物の ~/.claude/ には触れない。
フックは make_hooks.py が書いた hooks.json の command と args で起動する（${CLAUDE_PLUGIN_ROOT} は Claude Code と同じく
\\ 区切りの実際の値に置き換え、後ろの /hooks/guard.py は / のまま）。作業フォルダには json.py を置く（-I の確かめ）。
"""

import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skill")
GUARD = os.path.join(SKILL, "hooks", "guard.py")
MAKE = os.path.join(SKILL, "hooks", "make_hooks.py")
BOARD_EDIT = os.path.join(SKILL, "scripts", "board_edit.py")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.path.insert(0, os.path.join(SKILL, "hooks"))
sys.path.insert(0, os.path.join(ROOT, "deck"))
import board_edit as be  # noqa: E402
import deck_watcher as dw  # noqa: E402
import guard as gd  # noqa: E402
import make_hooks as mh  # noqa: E402

SPEC = {
    "sections": ["今日の予定", "今日中", "ルーチンタスク", "明日以降"],
    "items": [
        {"section": "今日の予定", "time": "9:00", "title": "朝会"},
        {"section": "今日中", "title": "作業A", "chip": "active"},
        {"section": "今日中", "title": "作業B"},
        {"section": "明日以降", "title": "来週の件"},
    ],
}
NESTED = ('  <div class="item">\n    <div class="task-title">入れ子</div>\n'
          '    <div class="item">\n      <div class="task-title">中</div>\n    </div>\n')
PLANTED_JSON = "raise SystemExit('PLANTED json.py was imported')\n"

_TMP_HOOKS = tempfile.mkdtemp(prefix="tb-guard-hooks-")
with contextlib.redirect_stdout(io.StringIO()):
    _rc = mh.main(["--python", sys.executable, "--out", os.path.join(_TMP_HOOKS, "hooks.json")])
assert _rc == 0
with open(os.path.join(_TMP_HOOKS, "hooks.json"), encoding="utf-8") as _f:
    HOOKS = json.load(_f)
shutil.rmtree(_TMP_HOOKS, ignore_errors=True)


def hook_cmd(event, matcher_tool=None):
    """hooks.json から、そのイベント（と tool）に当たる登録の command と args（置き換え済み）。"""
    for g in HOOKS["hooks"][event]:
        m = g.get("matcher")
        if m and matcher_tool and not re.fullmatch(m, matcher_tool):
            continue
        h = g["hooks"][0]
        return [h["command"]] + [a.replace("${CLAUDE_PLUGIN_ROOT}", SKILL) for a in h["args"]]
    # matcher の外（Claude Code は呼ばないが、過去の登録から呼ばれた場合を確かめる）: 最初の登録で起動する
    h = HOOKS["hooks"][event][0]["hooks"][0]
    return [h["command"]] + [a.replace("${CLAUDE_PLUGIN_ROOT}", SKILL) for a in h["args"]]


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-guard-test-")
        self.data = os.path.join(self.dir, ".claude", "today-board")
        os.makedirs(self.data)
        self.board = os.path.join(self.data, "board.html")
        self.gdir = os.path.join(self.data, ".guard")
        self.cwd = os.path.join(self.dir, "work")
        os.makedirs(self.cwd)
        with open(os.path.join(self.cwd, "json.py"), "w", encoding="utf-8") as f:
            f.write(PLANTED_JSON)
        self._env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.dir
        self.env = dict(os.environ)
        self.saved_hooks = (gd._HOOK_AFTER_READ, gd._HOOK_BEFORE_REREAD, gd.observe, be._HOOK_BEFORE_REREAD)
        self.n = 0

    def tearDown(self):
        gd._HOOK_AFTER_READ, gd._HOOK_BEFORE_REREAD, gd.observe, be._HOOK_BEFORE_REREAD = self.saved_hooks
        gd.__dict__.pop("open", None)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---- 板
    def create(self, spec=SPEC):
        p = os.path.join(self.dir, "spec.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        rc, out = self.be("create", "--spec", p)
        self.assertEqual(rc, 0, out)
        return out

    def be(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = be.main([args[0], "--board", self.board] + list(args[1:]))
        t = out.getvalue()
        return rc, (json.loads(t) if t.strip().startswith("{") else t)

    def read(self):
        with open(self.board, "rb") as f:
            return f.read()

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        with open(self.board, "wb") as f:
            f.write(data)

    def foreign(self, transform=None):
        """Bash が board_edit.py を通さずに書いた、とみなす書き込み。"""
        t = self.read().decode("utf-8")
        t = transform(t) if transform else t.replace("作業B", "作業B（勝手に）")
        self.write(t)
        return t.encode("utf-8")

    def history(self, kind=None):
        h = os.path.join(self.data, "history")
        names = sorted(os.listdir(h)) if os.path.isdir(h) else []
        return [n for n in names if kind is None or ("-%s-" % kind) in n]

    def pres(self, sid="s1"):
        p = os.path.join(self.gdir, "pre", sid)
        return sorted(os.listdir(p)) if os.path.isdir(p) else []

    def records(self, writer=None):
        adir = os.path.join(self.gdir, "auth")
        out = []
        for n in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
            if n.endswith(".json"):
                with open(os.path.join(adir, n), encoding="utf-8") as f:
                    r = json.load(f)
                if writer is None or r["writer"] == writer:
                    out.append(r)
        return out

    def hooklog(self):
        p = os.path.join(self.gdir, "hook.log")
        if not os.path.exists(p):
            return ""
        with open(p, encoding="utf-8") as f:
            return f.read()

    # ---- フック（Claude Code と同じ形の JSON を標準入力で）
    def run_hook(self, payload, raw=None):
        event = payload.get("hook_event_name") if isinstance(payload, dict) else "PreToolUse"
        cmd = hook_cmd(event if event in HOOKS["hooks"] else "UserPromptSubmit",
                       payload.get("tool_name") if isinstance(payload, dict) else None)
        data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        r = subprocess.run(cmd, input=data, capture_output=True, env=self.env, cwd=self.cwd, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, b"")
        out = r.stdout.decode("ascii")
        if not out.strip():
            self.assertEqual(out, "")
            return None
        obj = json.loads(out)              # stdout は JSON 1つだけ
        self.assertIsInstance(obj, dict)
        return obj

    def pre(self, tool="Bash", tuid=None, sid="s1", **ti):
        self.n += 1
        self.tuid = tuid or "toolu_%02d" % self.n
        return self.run_hook({"hook_event_name": "PreToolUse", "session_id": sid, "tool_use_id": self.tuid,
                              "tool_name": tool, "tool_input": ti or {"command": "echo"}, "cwd": self.cwd,
                              "transcript_path": os.path.join(self.dir, "t.jsonl")})

    def post(self, tool="Bash", tuid=None, sid="s1", event="PostToolUse"):
        return self.run_hook({"hook_event_name": event, "session_id": sid, "tool_use_id": tuid or self.tuid,
                              "tool_name": tool, "tool_input": {"command": "echo"}, "cwd": self.cwd,
                              "tool_response": {"stdout": ""}})

    def prompt(self, sid="s1", event="UserPromptSubmit"):
        d = {"hook_event_name": event, "session_id": sid, "cwd": self.cwd,
             "transcript_path": os.path.join(self.dir, "t.jsonl")}
        d.update({"prompt": "次へ"} if event == "UserPromptSubmit" else {"source": "resume"})
        return self.run_hook(d)

    def age_snapshot(self, seconds, sid="s1", tuid=None):
        p = os.path.join(self.gdir, "pre", sid, (tuid or self.tuid) + ".json")
        with open(p, encoding="utf-8") as f:
            info = json.load(f)
        info["time_ns"] -= int(seconds * 1e9)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(info, f)

    def assertReverted(self, out, before):
        self.assertEqual(self.read(), before)
        self.assertEqual(out["decision"], "block")
        self.assertIn("元に戻しました", out["reason"])

    def assertRestored(self, before):
        """restore の後の板が before と同じか。restore も #upd-time を今の時刻にする（分をまたぐと差が出る）ので、その中身だけを外して比べる。"""
        def blank(raw):
            return gd._UPD_TIME_RE.sub(r"\1\3", raw.decode("utf-8"), count=1)
        self.assertEqual(blank(self.read()), blank(before))


# ================================================================ 小片と make_hooks.py

class TestBoot(Sandbox):
    def boot(self, script_body=None, name="guard.py"):
        root = os.path.join(self.dir, "plug")
        os.makedirs(os.path.join(root, "hooks"), exist_ok=True)
        path = os.path.join(root, "hooks", name)
        if script_body is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(script_body)
        cmd = hook_cmd("PreToolUse", "Bash")
        cmd[-1] = root + "/hooks/" + name          # \ と / の混ざった形（${CLAUDE_PLUGIN_ROOT} の置き換えと同じ）
        r = subprocess.run(cmd, input=b'{"hook_event_name":"PreToolUse"}', capture_output=True,
                           env=self.env, cwd=self.cwd, timeout=60)
        return r

    def test_missing(self):
        r = self.boot(None)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_syntax_error(self):
        r = self.boot("def (:\n  nope\n")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_exception(self):
        r = self.boot("raise RuntimeError('x')\n")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_exit2(self):
        r = self.boot("import sys\nsys.stderr.write('e')\nsys.exit(2)\n")
        self.assertEqual((r.returncode, r.stdout), (0, b""))

    def test_runs_script_with_stdin(self):
        r = self.boot("import sys\nsys.stdout.write(sys.stdin.read()[:5])\n")
        self.assertEqual((r.returncode, r.stdout), (0, b'{"hoo'))

    def test_isolated_mode_ignores_planted_json(self):
        """作業フォルダの json.py は -I で読まれない。対照として -I を外すと読まれる（試験が効いていることを示す）。"""
        r = self.boot("import json,sys\nsys.stdout.write(json.dumps({'ok':1}))\n")
        self.assertEqual(r.stdout, b'{"ok": 1}')
        cmd = hook_cmd("PreToolUse", "Bash")
        self.assertEqual(cmd[1:3], ["-I", "-c"])
        cmd = [cmd[0]] + cmd[2:]
        cmd[-1] = os.path.join(self.dir, "plug", "hooks", "guard.py")
        r2 = subprocess.run(cmd, input=b"{}", capture_output=True, env=self.env, cwd=self.cwd, timeout=60)
        self.assertEqual(r2.stdout, b"")         # 置いた json.py が読まれ、guard.py は動かなかった


class TestMakeHooks(Sandbox):
    def test_shape(self):
        events = HOOKS["hooks"]
        self.assertEqual(sorted(events), ["PostToolUse", "PostToolUseFailure", "PreToolUse", "SessionStart",
                                          "UserPromptSubmit"])
        self.assertEqual([g["matcher"] for g in events["PreToolUse"]],
                         ["Write|Edit|MultiEdit|NotebookEdit", "Bash|PowerShell"])
        for g in events["PostToolUse"] + events["PostToolUseFailure"]:
            self.assertEqual(g["matcher"], "Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell")
        for ev in ("UserPromptSubmit", "SessionStart"):
            self.assertNotIn("matcher", events[ev][0])
        for groups in events.values():
            for g in groups:
                h = g["hooks"][0]
                self.assertEqual(h["command"], sys.executable)
                self.assertEqual(h["args"], ["-I", "-c", mh.BOOT, "${CLAUDE_PLUGIN_ROOT}/hooks/guard.py"])
                self.assertNotIn("onFailure", h)

    def test_atomic_replace(self):
        out = os.path.join(self.dir, "hooks.json")
        with open(out, "w") as f:
            f.write("old")
        seen = []
        real = os.replace

        def spy(a, b):
            seen.append((os.path.dirname(os.path.abspath(a)), os.path.basename(a), b))
            with open(b) as f:
                self.assertEqual(f.read(), "old")      # 置き換えの直前まで元のまま
            return real(a, b)
        mh.os.replace = spy
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mh.main(["--python", sys.executable, "--out", out]), 0)
        finally:
            mh.os.replace = real
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], os.path.dirname(os.path.abspath(out)))
        self.assertTrue(seen[0][1].endswith(".tmp"))
        with open(out, encoding="utf-8") as f:
            self.assertIn("hooks", json.load(f))
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(["hooks.json", ".claude", "work"]))

    def test_rejects_bad_python(self):
        out = os.path.join(self.dir, "hooks.json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mh.main(["--python", "python", "--out", out]), 1)
            self.assertEqual(mh.main(["--python", os.path.join(self.dir, "nope.exe"), "--out", out]), 1)
        self.assertFalse(os.path.exists(out))

    def test_rejects_partial_token(self):
        tpl = os.path.join(self.dir, "t.json")
        with open(tpl, "w", encoding="utf-8") as f:
            json.dump({"hooks": {"X": [{"hooks": [{"command": "@PYTHON@", "args": ["x@BOOT@"]}]}]}}, f)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mh.main(["--python", sys.executable, "--template", tpl,
                                      "--out", os.path.join(self.dir, "o.json")]), 1)


# ================================================================ L1

class TestL1(Sandbox):
    def setUp(self):
        Sandbox.setUp(self)
        self.create()

    def denied(self, out):
        return bool(out) and out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_deny_variants(self):
        b = self.board
        variants = [b, b.replace("\\", "/"), b.upper(), os.path.join(self.data, "history", "..", "board.html"),
                    os.path.join(self.data, "board.new.html"), os.path.join(self.data, "history", "x.html"),
                    os.path.join(self.data, "history", "board-2026-01-01-before-interrupt-000000.html"),
                    os.path.join(self.data, ".guard", "format.json"), os.path.join(self.data, ".guard", "auth", "x.json"),
                    "~/.claude/today-board/board.html", os.path.join(self.data, "HISTORY", "y.html")]
        for tool in ("Write", "Edit", "MultiEdit"):
            for v in variants:
                out = self.pre(tool, file_path=v)
                self.assertTrue(self.denied(out), (tool, v))
                self.assertIn("board_edit.py", out["hookSpecificOutput"]["permissionDecisionReason"])
        out = self.pre("NotebookEdit", notebook_path=os.path.join(self.data, "history", "n.ipynb"))
        self.assertTrue(self.denied(out))

    def test_relative_path_uses_cwd(self):
        rel = os.path.relpath(self.board, self.cwd)
        self.assertTrue(self.denied(self.pre("Write", file_path=rel)))

    def test_short_name(self):
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(self.board, buf, 1024)
        if not n or buf.value.lower() == self.board.lower():
            self.skipTest("8.3 の短い名前が無い")
        self.assertTrue(self.denied(self.pre("Edit", file_path=buf.value)))

    def test_state_file_path(self):
        other = os.path.join(self.dir, "elsewhere", "b.html")
        for mode, deny in (("local", True), ("artifact", False)):
            with open(os.path.join(self.data, "state.json"), "w", encoding="utf-8") as f:
                json.dump({"date": "2026-10-30", "mode": mode, "file_path": other}, f)
            self.assertEqual(self.denied(self.pre("Write", file_path=other)), deny, mode)

    def test_allows_sandbox_and_others(self):
        sandbox = os.path.join(self.dir, "sandbox", "board.html")
        for v in (sandbox, os.path.join(self.data, "config.json"), os.path.join(self.data, "board.css"),
                  os.path.join(self.data, "historyx.html")):
            self.assertIsNone(self.pre("Write", file_path=v), v)
        self.assertIsNone(self.pre("Bash", command="echo > %s" % self.board))     # Bash は止めない（L3 が戻す）
        self.assertIsNone(self.pre("PowerShell", command="Set-Content %s x" % self.board))
        self.assertIsNone(self.pre("Read", file_path=self.board))

    def test_no_snapshot_when_denied(self):
        self.pre("Write", file_path=self.board)
        self.assertEqual(self.pres(), [])
        self.pre("Write", file_path=os.path.join(self.dir, "other.txt"))
        self.assertEqual(self.pres(), [self.tuid + ".html", self.tuid + ".json"])
        self.pre("Read", file_path=self.board)
        self.assertEqual(len(self.pres()), 2)     # matcher の外のツールは控えない


# ================================================================ L3（Post）

class TestPost(Sandbox):
    def setUp(self):
        Sandbox.setUp(self)
        self.create()

    def test_unchanged(self):
        self.pre()
        self.assertIsNone(self.post())
        self.assertEqual(self.pres(), [])

    def test_board_edit_is_legit(self):
        self.pre()
        rc, _ = self.be("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0)
        after = self.read()
        self.assertIsNone(self.post())
        self.assertEqual(self.read(), after)

    def test_old_chip_board_is_legit(self):
        """古い表示名のチップ（class は同じ crit）が残った板でも、board_edit.py の書き込みは戻されない。"""
        self.write(self.read().decode("utf-8").replace("重要タスク", "判断ゲート"))
        self.pre()
        rc, _ = self.be("set-chip", "--item", "作業B", "--chip", "done")
        self.assertEqual(rc, 0)
        after = self.read()
        self.assertIn("判断ゲート".encode("utf-8"), after)
        self.assertIsNone(self.post())
        self.assertEqual(self.read(), after)

    def test_deck_record_is_legit(self):
        self.pre()
        rc, _ = self.be("add", "--section", "今日中", "--title", "足した")
        new = self.read().decode("utf-8")
        moved = new.replace("作業A", "作業A2")       # Deck の D&D（記録を書く）
        dw.guard_write_record(self.board, moved.encode("utf-8"), dw.hand_fingerprint(moved),
                              dw.hand_fingerprint(new), "deck")
        self.write(moved)
        self.assertIsNone(self.post())
        self.assertEqual(self.read(), moved.encode("utf-8"))

    def test_foreign_reverted(self):
        before = self.read()
        self.pre()
        fb = self.foreign()
        out = self.post()
        self.assertReverted(out, before)
        foreign = self.history("foreign")
        self.assertEqual(len(foreign), 1)
        with open(os.path.join(self.data, "history", foreign[0]), "rb") as f:
            self.assertEqual(f.read(), fb)
        self.assertIn("history/" + foreign[0], out["reason"])
        g = self.records("guard")
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["fp"], be.hand_fingerprint(before.decode("utf-8")))
        self.assertEqual(g[0]["base_fp"], be.hand_fingerprint(fb.decode("utf-8")))
        self.assertEqual(self.pres(), [])
        self.assertIn("正規でない書き換えを戻しました", self.hooklog())
        # 戻した後のツールでは、戻した版は正規（鎖に入る）
        self.pre()
        self.assertIsNone(self.post())

    def test_post_failure_event(self):
        before = self.read()
        self.pre()
        self.foreign()
        self.assertReverted(self.post(event="PostToolUseFailure"), before)

    def test_shape_worse_same_fingerprint(self):
        before = self.read()
        self.pre()
        self.foreign(lambda t: t.replace("<!-- DECK:AUTO:END -->", ""))     # 指紋は同じ・K3 が悪くなる
        self.assertReverted(self.post(), before)

    def test_already_broken_stays(self):
        t = self.read().decode("utf-8").replace('<div class="section-label">今日中</div>\n',
                                                 '<div class="section-label">今日中</div>\n' + NESTED)
        self.write(t)
        self.pre()
        t2 = t.replace('<span id="upd-time">', '<span id="upd-time" data-x="1">')   # 指紋の外・崩れは同じ
        self.write(t2)
        self.assertIsNone(self.post())
        self.assertEqual(self.read(), t2.encode("utf-8"))

    def test_board_removed_with_guard(self):
        before = self.read()
        self.pre()
        os.remove(self.board)
        out = self.post()
        self.assertReverted(out, before)
        self.assertIn("消えていました", out["reason"])
        self.assertEqual(self.history("foreign"), [])

    def test_guard_dir_removed(self):
        self.pre()
        shutil.rmtree(self.data)
        os.makedirs(self.data)
        self.assertIsNone(self.post())
        self.assertFalse(os.path.exists(self.board))

    def test_old_snapshot_notifies(self):
        before = self.read()
        self.pre()
        self.age_snapshot(25 * 3600)
        fb = self.foreign()
        out = self.post()
        self.assertEqual(out["decision"], "block")
        self.assertIn("24時間より古い", out["reason"])
        self.assertEqual(self.read(), fb)
        bt = self.history("before-tool")
        self.assertEqual(len(bt), 1)
        with open(os.path.join(self.data, "history", bt[0]), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertIn("restore --from history/" + bt[0], out["reason"])
        self.assertEqual(self.pres(), [])
        rc, res = self.be("restore", "--from", "history/" + bt[0], "--confirmed")     # T-R と通しで
        self.assertEqual(rc, 0, res)
        self.assertRestored(before)

    def test_old_deck_notifies(self):
        os.makedirs(os.path.join(self.data, "deck"))
        for head, revert in (('"""Deck v2.5 — x', False), ('"""Deck v2.6 — x', True), ('"""Deck v3.0 — x', True),
                             ('"""no version', False)):
            with open(os.path.join(self.data, "deck", "deck_watcher.py"), "w", encoding="utf-8") as f:
                f.write(head + '\n"""\n')
            before = self.read()
            self.pre()
            fb = self.foreign(lambda t: t.replace("作業A", "作業A" + head[9:12]))
            out = self.post()
            if revert:
                self.assertReverted(out, before)
            else:
                self.assertIn("v2.6 未満", out["reason"])
                self.assertEqual(self.read(), fb)
                self.assertTrue(self.history("before-tool"))

    def test_unknown_format_version(self):
        with open(os.path.join(self.gdir, "format.json"), "w") as f:
            json.dump({"v": 2}, f)
        self.pre()
        fb = self.foreign()
        out = self.post()
        self.assertIn("ガードの版が古い", out["reason"])
        self.assertEqual(self.read(), fb)
        self.assertEqual(len(self.history("before-tool")), 1)

    def test_unknown_record_version(self):
        self.pre()
        fb = self.foreign()
        rec = self.records()[-1]
        adir = os.path.join(self.gdir, "auth")
        name = "%020d-1.json" % time.time_ns()
        with open(os.path.join(adir, name), "w") as f:
            json.dump(dict(rec, v=2), f)
        out = self.post()
        self.assertIn("ガードの版が古い", out["reason"])
        self.assertEqual(self.read(), fb)

    def test_unknown_snapshot_version(self):
        self.pre()
        p = os.path.join(self.gdir, "pre", "s1", self.tuid + ".json")
        with open(p, encoding="utf-8") as f:
            info = json.load(f)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(dict(info, v=2), f)
        fb = self.foreign()
        out = self.post()
        self.assertIn("ガードの版が古い", out["reason"])
        self.assertIn("控えの形式を知らないため", out["reason"])
        self.assertEqual(self.read(), fb)
        self.assertEqual(self.history(), [])
        self.assertEqual(self.pres(), [self.tuid + ".html"])     # 本文は24時間の掃除に任せる（推奨2）

    def test_corrupt_format(self):
        with open(os.path.join(self.gdir, "format.json"), "w") as f:
            f.write("{broken")
        self.pre()
        fb = self.foreign()
        out = self.post()
        self.assertIn("format.json が読めない", out["reason"])
        self.assertEqual(self.read(), fb)
        self.assertEqual(len(self.history("before-tool")), 1)

    def test_backup_failure_keeps_snapshot(self):
        self.pre()
        self.age_snapshot(25 * 3600)
        self.foreign()
        with open(os.path.join(self.data, "history"), "w") as f:     # history/ を作れない
            f.write("x")
        out = self.post()
        self.assertIn("残せませんでした", out["reason"])
        self.assertEqual(len(self.pres()), 2)
        self.assertIn("退避できませんでした", self.hooklog())

    def test_restore_hint_when_dates_differ(self):
        before = self.read()
        self.pre()
        self.age_snapshot(25 * 3600)
        self.foreign(lambda t: t.replace(be.board_header_date_text(t), "2020-01-01（水）"))
        out = self.post()
        self.assertIn("restore では戻せません", out["reason"])
        self.assertIn("日付", out["reason"])
        self.assertNotEqual(self.read(), before)

    def test_undecodable_snapshot_then_create(self):
        self.write(b"\xff\xfe broken")
        self.pre()
        p = os.path.join(self.dir, "spec2.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(SPEC, f, ensure_ascii=False)
        rc, out = self.be("create", "--spec", p, "--confirmed")
        self.assertEqual(rc, 0, out)
        self.assertIsNone(self.records()[-1]["base_fp"])
        after = self.read()
        self.assertIsNone(self.post())         # base_fp null の記録は、読めない板の控えと突き合う
        self.assertEqual(self.read(), after)

    def test_undecodable_foreign_reverted(self):
        before = self.read()
        self.pre()
        self.write(b"\xff\xfe broken")
        self.assertReverted(self.post(), before)

    def deck_only(self, t):
        return t.replace("<!-- DECK:AUTO:START -->", "<!-- DECK:AUTO:START -->" + chr(10) + "<span>Deck のふだんの書き込み</span>")

    def test_deck_region_only_change_is_silent(self):
        """M1: 指紋も形も控えと同じなら、format.json が読めない・版を知らないときでも何もしない。"""
        for case in ("corrupt", "unknown", "snapshot-unknown", "normal"):
            fpath = os.path.join(self.gdir, "format.json")
            with open(fpath, "w") as f:
                f.write({"corrupt": "{broken", "unknown": '{"v": 2}'}.get(case, '{"v": 1}'))
            self.pre()
            if case == "snapshot-unknown":
                p = os.path.join(self.gdir, "pre", "s1", self.tuid + ".json")
                with open(p, encoding="utf-8") as f:
                    info = json.load(f)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(dict(info, v=2), f)
            after = self.foreign(self.deck_only)
            self.assertIsNone(self.post(), case)
            self.assertEqual(self.read(), after, case)
            self.assertEqual(self.history(), [], case)

    def test_unreadable_snapshot_json(self):
        self.pre()
        p = os.path.join(self.gdir, "pre", "s1", self.tuid + ".json")
        with open(p, "w") as f:
            f.write("{broken")
        self.foreign()
        self.assertIsNone(self.post())
        self.assertEqual(self.pres(), [self.tuid + ".html"])     # .json だけを消し、本文は24時間の掃除に任せる
        self.assertIn("読めないため消しました", self.hooklog())
        old = time.time() - 25 * 3600
        os.utime(os.path.join(self.gdir, "pre", "s1", self.tuid + ".html"), (old, old))
        self.pre(tuid="later")
        self.assertEqual(self.pres(), ["later.html", "later.json"])

    def test_sandbox_board_ignored(self):
        sb = os.path.join(self.dir, "sandbox", "board.html")
        os.makedirs(os.path.dirname(sb))
        shutil.copy(self.board, sb)
        self.pre()
        with open(sb, "ab") as f:
            f.write(b"<!-- x -->")
        self.assertIsNone(self.post())
        with open(sb, "rb") as f:
            self.assertTrue(f.read().endswith(b"<!-- x -->"))

    def test_no_board_no_snapshot(self):
        os.remove(self.board)
        self.pre()
        self.assertEqual(self.pres(), [])
        self.assertIsNone(self.post())


# ================================================================ 鎖・猶予

class TestChain(Sandbox):
    def setUp(self):
        Sandbox.setUp(self)
        self.create()

    def test_two_step_chain(self):
        self.pre()
        self.be("set-chip", "--item", "作業B", "--chip", "done")
        a = self.read().decode("utf-8")
        b = a.replace("作業A", "作業A移動")
        dw.guard_write_record(self.board, b.encode("utf-8"), dw.hand_fingerprint(b), dw.hand_fingerprint(a), "deck")
        self.write(b)
        self.be("edit", "--item", "作業B", "--note", "メモ")
        c = self.read()
        self.assertIsNone(self.post())
        self.assertEqual(self.read(), c)

    def test_writer_on_foreign_is_not_legit(self):
        self.pre()
        self.be("set-chip", "--item", "作業B", "--chip", "done")
        a = self.read()                                        # 鎖の最後の正規の版
        self.foreign()
        rc, _ = self.be("add", "--section", "今日中", "--title", "上に書いた")      # 正規でない版の上の board_edit
        self.assertEqual(rc, 0)
        f2 = self.read().decode("utf-8")
        f3 = f2.replace("作業A", "作業A'")                     # その上の Deck の D&D
        dw.guard_write_record(self.board, f3.encode("utf-8"), dw.hand_fingerprint(f3), dw.hand_fingerprint(f2), "deck")
        self.write(f3)
        out = self.post()
        self.assertReverted(out, a)

    def _record_at(self, ns, body_text, base_fp):
        adir = os.path.join(self.gdir, "auth")
        base = "%020d-%d" % (ns, 99999)
        with open(os.path.join(adir, base + ".html"), "wb") as f:
            f.write(body_text.encode("utf-8"))
        with open(os.path.join(adir, base + ".json"), "w", encoding="utf-8") as f:
            json.dump({"v": 1, "fp": be.hand_fingerprint(body_text), "base_fp": base_fp, "writer": "board_edit",
                       "body": base + ".html"}, f)

    def snap_ns(self):
        with open(os.path.join(self.gdir, "pre", "s1", self.tuid + ".json"), encoding="utf-8") as f:
            return json.load(f)["time_ns"]

    def test_grace_window(self):
        for back, legit in ((5, True), (15, False)):
            before = self.read()
            t = before.decode("utf-8")
            self.pre()
            new = t.replace("作業B", "作業B%d" % back)
            self._record_at(self.snap_ns() - back * 10 ** 9, new, be.hand_fingerprint(t))
            self.write(new)
            out = self.post()
            if legit:
                self.assertIsNone(out)
                self.assertEqual(self.read(), new.encode("utf-8"))
            else:
                self.assertReverted(out, before)

    def test_old_legit_copied_back_is_not_legit(self):
        old = self.read()
        self.be("set-chip", "--item", "作業B", "--chip", "done")
        # それまでの記録を猶予より古くする（20秒前へ）
        adir = os.path.join(self.gdir, "auth")
        for n in os.listdir(adir):
            m = re.match(r"^(\d{20})-(\d+)\.(json|html)$", n)
            os.rename(os.path.join(adir, n), os.path.join(adir, "%020d-%s.%s" % (
                int(m.group(1)) - 20 * 10 ** 9, m.group(2), m.group(3))))
        cur = self.read()
        self.pre()
        self.write(old)                     # history/ から Bash で写し戻した
        self.assertReverted(self.post(), cur)

    def test_two_records_same_base(self):
        t = self.read().decode("utf-8")
        self.pre()
        x = t.replace("作業A", "作業X")
        y = t.replace("作業A", "作業Y")
        base = be.hand_fingerprint(t)
        r1 = be.guard_write_record(self.board, x.encode("utf-8"), be.hand_fingerprint(x), base, "board_edit")
        r2 = dw.guard_write_record(self.board, y.encode("utf-8"), dw.hand_fingerprint(y), base, "deck")
        self.assertTrue(os.path.exists(r1[0]) and os.path.exists(r2[0]))
        self.write(y)
        self.assertIsNone(self.post())
        self.assertEqual(self.read(), y.encode("utf-8"))

    def test_orphan_html_is_not_a_record(self):
        before = self.read()
        t = before.decode("utf-8")
        self.pre()
        new = t.replace("作業B", "作業Z")
        adir = os.path.join(self.gdir, "auth")
        with open(os.path.join(adir, "%020d-1.html" % time.time_ns()), "wb") as f:
            f.write(new.encode("utf-8"))           # .json（確定の印）の無い記録
        self.write(new)
        self.assertReverted(self.post(), before)

    def test_target_skips_record_without_body(self):
        self.pre()
        self.be("set-chip", "--item", "作業B", "--chip", "done")
        a = self.read()
        self.be("set-chip", "--item", "作業A", "--chip", "done")
        last = sorted(n for n in os.listdir(os.path.join(self.gdir, "auth")) if n.endswith(".html"))[-1]
        os.remove(os.path.join(self.gdir, "auth", last))       # 最後の記録の本文が無い
        self.foreign()
        self.assertReverted(self.post(), a)


# ================================================================ 競合・順序（同じプロセスで）

class TestRaces(Sandbox):
    def setUp(self):
        Sandbox.setUp(self)
        self.create()

    def d(self, event, tuid="t1", sid="s1"):
        return {"hook_event_name": event, "session_id": sid, "tool_use_id": tuid, "tool_name": "Bash",
                "tool_input": {"command": "x"}, "cwd": self.cwd}

    def test_post_between_record_and_replace(self):
        gd.dispatch(self.d("PreToolUse"))
        outs = []

        def mid(attempt, record):
            self.assertTrue(record and os.path.exists(record[0]))       # 記録は置き換えより前に見える
            outs.append(gd.dispatch(self.d("PostToolUse")))
        be._HOOK_BEFORE_REREAD = mid
        rc, _ = self.be("set-chip", "--item", "作業B", "--chip", "done")
        be._HOOK_BEFORE_REREAD = None
        self.assertEqual(rc, 0)
        self.assertEqual(outs, [None])
        after = self.read()
        gd.dispatch(self.d("PreToolUse", "t2"))
        self.assertIsNone(gd.dispatch(self.d("PostToolUse", "t2")))
        self.assertEqual(self.read(), after)

    def test_post_after_replace_sees_record(self):
        gd.dispatch(self.d("PreToolUse"))
        self.be("set-chip", "--item", "作業B", "--chip", "done")
        after = self.read()
        self.assertIsNone(gd.dispatch(self.d("PostToolUse")))
        self.assertEqual(self.read(), after)

    def _order_case(self):
        gd.dispatch(self.d("PreToolUse"))
        self.be("set-chip", "--item", "作業B", "--chip", "done")      # B1（記録 r1）

        def writer():
            gd._HOOK_AFTER_READ = None
            self.be("set-chip", "--item", "作業A", "--chip", "done")  # B2（記録 r2）
            self.b2 = self.read()
        return writer

    def test_read_then_list(self):
        writer = self._order_case()
        gd._HOOK_AFTER_READ = writer
        self.assertIsNone(gd.dispatch(self.d("PostToolUse")))
        self.assertEqual(self.read(), self.b2)                 # 書き手の版（B2）がそのまま残る
        self.assertEqual(self.history("foreign"), [])
        self.assertEqual(self.records("guard"), [])

    def test_list_then_read_would_revert(self):
        """逆の順（記録を列挙してから板を読む）の写しでは、正規の書き込みを戻してしまう＝試験が順序の誤りを捕まえる。"""
        writer = self._order_case()
        orig = gd.observe

        def wrong(since_ns):
            recs = gd.list_records(since_ns)
            writer()
            return gd.read_bytes(gd.board_file()), recs
        gd.observe = wrong
        out = gd.dispatch(self.d("PostToolUse"))
        gd.observe = orig
        self.assertIsNotNone(out)
        self.assertEqual(out["decision"], "block")
        self.assertEqual(len(self.history("foreign")), 1)

    def test_reread_detects_change_and_retries(self):
        before = self.read()
        gd.dispatch(self.d("PreToolUse"))
        self.foreign()
        calls = []

        def mid():
            calls.append(1)
            if len(calls) == 1:
                self.foreign(lambda t: t.replace("作業A", "作業A（さらに）"))
        gd._HOOK_BEFORE_REREAD = mid
        out = gd.dispatch(self.d("PostToolUse"))
        self.assertEqual(len(calls), 2)
        self.assertReverted(out, before)
        self.assertEqual(len(self.history("foreign")), 2)       # 1巡目の退避も残す（推奨1）
        self.assertEqual(len(self.records("guard")), 1)

    def assertFailedSaved(self, out, before, kind="before-tool"):
        self.assertEqual(out["decision"], "block")
        self.assertIn("元に戻せませんでした", out["reason"])
        saved = self.history(kind)
        self.assertEqual(len(saved), 1)
        with open(os.path.join(self.data, "history", saved[0]), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertIn("を history/%s に残しました。" % saved[0], out["reason"])
        self.assertIn("restore --from history/" + saved[0], out["reason"])
        self.assertEqual(self.pres(), [])
        rc, res = self.be("restore", "--from", "history/" + saved[0], "--confirmed")
        self.assertEqual(rc, 0, res)
        self.assertRestored(before)

    def test_failed_replace_saves_snapshot(self):
        """M2: os.replace を使い切って戻せなかったときも、控えの本文を before-tool へ退避して restore で戻せる。"""
        before = self.read()
        gd.dispatch(self.d("PreToolUse"))
        fb = self.foreign()
        real = os.replace

        def busy(a, b):
            if os.path.abspath(b) == os.path.abspath(self.board):
                raise PermissionError(5, "busy")
            return real(a, b)
        gd.os.replace = busy
        try:
            out = gd.dispatch(self.d("PostToolUse"))
        finally:
            gd.os.replace = real
        self.assertEqual(self.read(), fb)
        self.assertIn("書き込みに失敗したため", out["reason"])
        self.assertEqual(self.records("guard"), [])
        self.assertFailedSaved(out, before)

    def test_changed_three_times_saves_snapshot(self):
        """M2: 戻す間に3回続けて板が変わったときも、控えの本文を before-tool へ退避する。"""
        before = self.read()
        gd.dispatch(self.d("PreToolUse"))
        self.foreign()
        n = [0]

        def mid():
            n[0] += 1
            self.foreign(lambda t: t.replace("作業A", "作業A%d" % n[0]))
        gd._HOOK_BEFORE_REREAD = mid
        out = gd.dispatch(self.d("PostToolUse"))
        gd._HOOK_BEFORE_REREAD = None
        self.assertEqual(n[0], 3)
        self.assertIn("書き込み続けたため", out["reason"])
        self.assertEqual(len(self.history("foreign")), 3)       # 各巡の foreign の退避は残す
        self.assertEqual(self.records("guard"), [])
        self.assertFailedSaved(out, before)

    def test_failed_rescan_saves_before_interrupt(self):
        before = self.read()
        gd.dispatch(self.d("PreToolUse"))
        self.foreign(lambda t: t.replace("<!-- DECK:AUTO:END -->", ""))
        real = os.replace

        def busy(a, b):
            if os.path.abspath(b) == os.path.abspath(self.board):
                raise PermissionError(5, "busy")
            return real(a, b)
        gd.os.replace = busy
        try:
            out = gd.dispatch({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": self.cwd})
        finally:
            gd.os.replace = real
        ctx = out["hookSpecificOutput"]["additionalContext"]
        saved = self.history("before-interrupt")
        self.assertEqual(len(saved), 1)
        self.assertIn("中断の前の版を history/%s に残しました。" % saved[0], ctx)
        self.assertEqual(self.pres(), [])

    def test_failed_backup_failure_keeps_snapshot(self):
        gd.dispatch(self.d("PreToolUse"))
        self.foreign()
        real = os.replace

        def busy(a, b):
            if os.path.abspath(b) == os.path.abspath(self.board):
                raise PermissionError(5, "busy")
            return real(a, b)
        gd.os.replace = busy
        hist = os.path.join(self.data, "history")
        orig = gd.save_snapshot_body
        gd.save_snapshot_body = lambda *a: None
        try:
            out = gd.dispatch(self.d("PostToolUse"))
        finally:
            gd.os.replace = real
            gd.save_snapshot_body = orig
        self.assertIn("ツールの前の版を history/ に残せませんでした。", out["reason"])
        self.assertEqual(len(self.pres()), 2)                   # 控えは残す（次の拾い直しに回す）
        self.assertTrue(os.path.isdir(hist))

    def test_parallel_posts(self):
        before = self.read()
        for t in ("ta", "tb"):
            self.n += 1
            self.pre(tuid=t)
        self.foreign()
        res = {}

        def go(t):
            res[t] = self.post(tuid=t)
        th = [threading.Thread(target=go, args=(t,)) for t in ("ta", "tb")]
        for x in th:
            x.start()
        for x in th:
            x.join()
        self.assertEqual(self.read(), before)
        self.assertTrue(any(v and "元に戻しました" in v["reason"] for v in res.values()), res)
        self.assertEqual(self.pres(), [])

    def test_pre_read_retry(self):
        real = open
        fails = [0]

        def flaky(path, *a, **k):
            if os.path.abspath(str(path)) == os.path.abspath(self.board) and fails[0] > 0:
                fails[0] -= 1
                raise PermissionError(13, "locked")
            return real(path, *a, **k)
        gd.open = flaky
        fails[0] = 2
        gd.dispatch(self.d("PreToolUse", "r1"))
        self.assertEqual(len(self.pres()), 2)
        fails[0] = 10
        gd.dispatch(self.d("PreToolUse", "r2"))
        self.assertEqual(len(self.pres()), 2)              # 使い切ったら控えを取らない
        self.assertIn("控えを取りませんでした", self.hooklog())
        del gd.open

    def test_replace_permission_retry(self):
        before = self.read()
        gd.dispatch(self.d("PreToolUse"))
        self.foreign()
        real = os.replace
        n = [0]

        def flaky(a, b):
            if os.path.abspath(b) == os.path.abspath(self.board) and n[0] < 2:
                n[0] += 1
                raise PermissionError(5, "busy")
            return real(a, b)
        gd.os.replace = flaky
        try:
            out = gd.dispatch(self.d("PostToolUse"))
        finally:
            gd.os.replace = real
        self.assertEqual(n[0], 2)
        self.assertReverted(out, before)


# ================================================================ 拾い直し（中断）

class TestRescan(Sandbox):
    def setUp(self):
        Sandbox.setUp(self)
        self.create()

    def test_legit_within_and_after(self):
        for age in (0, 11 * 60):
            self.pre()
            self.age_snapshot(age)
            self.be("edit", "--item", "作業B", "--note", "n%d" % age)
            after = self.read()
            self.assertIsNone(self.prompt())
            self.assertEqual(self.read(), after)
            self.assertEqual(self.pres(), [])

    def test_broken_within_10min_reverted(self):
        before = self.read()
        self.pre()
        self.age_snapshot(60)
        self.foreign(lambda t: t.replace('<div class="section-label">今日中</div>\n',
                                         '<div class="section-label">今日中</div>\n' + NESTED))
        out = self.prompt()
        ctx = out["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "UserPromptSubmit")
        self.assertIn("中断の前の版へ戻しました", ctx["additionalContext"])
        self.assertNotIn("decision", out)
        self.assertEqual(self.read(), before)
        self.assertEqual(len(self.history("foreign")), 1)
        self.assertEqual(self.pres(), [])

    def _notify_case(self, age, broken):
        before = self.read()
        self.pre()
        self.age_snapshot(age)
        if broken:
            fb = self.foreign(lambda t: t.replace('<div class="section-label">今日中</div>\n',
                                                  '<div class="section-label">今日中</div>\n' + NESTED))
        else:
            fb = self.foreign()
        out = self.prompt()
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("利用者が自分で編集したものかもしれません", ctx)
        self.assertEqual(self.read(), fb)
        bi = self.history("before-interrupt")
        self.assertEqual(len(bi), 1)
        with open(os.path.join(self.data, "history", bi[0]), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.pres(), [])
        return ctx, bi[0], before

    def test_broken_after_10min_notifies(self):
        ctx, name, _b = self._notify_case(11 * 60, True)
        self.assertIn("restore --from history/" + name, ctx)

    def test_content_within_10min_notifies_and_restore(self):
        ctx, name, before = self._notify_case(30, False)
        self.assertIn("--confirmed なしで実行して差分を利用者に見せ", ctx)
        rc, res = self.be("restore", "--from", "history/" + name)
        self.assertEqual(rc, 0, res)
        self.assertEqual(self.read() != before, True)
        rc, res = self.be("restore", "--from", "history/" + name, "--confirmed")
        self.assertEqual(rc, 0, res)
        self.assertRestored(before)

    def test_content_after_10min_notifies(self):
        self._notify_case(11 * 60, False)

    def test_backup_failure_keeps_snapshot(self):
        self.pre()
        self.foreign()
        with open(os.path.join(self.data, "history"), "w") as f:
            f.write("x")
        out = self.prompt()
        self.assertIn("残せませんでした", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(len(self.pres()), 2)

    def test_other_session_untouched(self):
        self.pre(sid="other")
        self.foreign()
        self.assertIsNone(self.prompt(sid="s1"))
        self.assertEqual(len(self.pres("other")), 2)

    def test_session_start(self):
        before = self.read()
        self.pre()
        self.foreign(lambda t: t.replace("<!-- DECK:AUTO:END -->", ""))
        out = self.prompt(event="SessionStart")
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertEqual(self.read(), before)

    def test_oldest_first(self):
        before = self.read()
        self.pre(tuid="a1")
        self.age_snapshot(120, tuid="a1")
        self.be("edit", "--item", "作業B", "--note", "正規")
        mid = self.read()
        self.pre(tuid="a2")
        self.foreign(lambda t: t.replace("<!-- DECK:AUTO:END -->", ""))
        out = self.prompt()
        self.assertEqual(self.read(), mid)              # 新しい方の控え（正規の版）へ戻る
        self.assertNotEqual(mid, before)
        self.assertIn("戻しました", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.pres(), [])


# ================================================================ その他

class TestMisc(Sandbox):
    def setUp(self):
        Sandbox.setUp(self)
        self.create()

    def test_unknown_inputs(self):
        cmd = hook_cmd("UserPromptSubmit")
        for raw in (b"", b"garbage", b"[]", b'{"hook_event_name":"Stop"}', b'{"hook_event_name":"FutureEvent","x":1}',
                    b'{"hook_event_name":"PreToolUse","tool_name":"Write"}', b'{"hook_event_name":"PostToolUse"}',
                    "﻿{}".encode("utf-8"), b"\xff\xfe"):
            r = subprocess.run(cmd, input=raw, capture_output=True, env=self.env, cwd=self.cwd, timeout=60)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""), raw)
        self.assertEqual(self.pres(), [])
        out = self.pre("Bash", extra_field={"a": 1})      # 知らない欄があっても普通に動く
        self.assertIsNone(out)

    def test_old_guard_snapshot_shape(self):
        """旧い guard.py（同じ v1）の控え: 最小の欄だけでも新しい guard.py が比べられる。"""
        before = self.read()
        sdir = os.path.join(self.gdir, "pre", "s1")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "old1.html"), "wb") as f:
            f.write(before)
        with open(os.path.join(sdir, "old1.json"), "w") as f:
            json.dump({"v": 1, "time_ns": time.time_ns()}, f)
        self.foreign()
        self.assertReverted(self.post(tuid="old1"), before)

    def test_prune(self):
        self.pre()
        self.age_snapshot(25 * 3600)
        p = os.path.join(self.gdir, "pre", "s1", self.tuid)
        old = time.time() - 25 * 3600
        for ext in (".json", ".html"):
            os.utime(p + ext, (old, old))
        adir = os.path.join(self.gdir, "auth")
        n_before = len(os.listdir(adir))
        with open(os.path.join(adir, "%020d-1.json" % (time.time_ns() - 49 * 3600 * 10 ** 9)), "w") as f:
            f.write("{}")
        self.pre(tuid="new1")
        self.assertEqual(self.pres(), ["new1.html", "new1.json"])
        self.assertEqual(len(os.listdir(adir)), n_before)

    def test_log_truncation(self):
        p = os.path.join(self.gdir, "hook.log")
        with open(p, "wb") as f:
            f.write((b"x" * 99 + b"\n") * 11000)
        gd.log("test", "末尾")
        size = os.path.getsize(p)
        self.assertLess(size, gd.LOG_MAX_BYTES)
        with open(p, encoding="utf-8") as f:
            data = f.read()
        self.assertTrue(data.startswith("x"))
        self.assertTrue(data.rstrip().endswith("末尾"))

    def test_stdout_is_ascii_json(self):
        self.pre()
        self.foreign()
        cmd = hook_cmd("PostToolUse", "Bash")
        d = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_use_id": self.tuid, "tool_name": "Bash"}
        r = subprocess.run(cmd, input=json.dumps(d).encode(), capture_output=True, env=self.env, cwd=self.cwd,
                           timeout=60)
        r.stdout.decode("ascii")
        self.assertEqual(len(json.loads(r.stdout)), 2)


# ================================================================ T-P（board_edit.py との写しの一致）

COPIED = ["_blank_comments", "_canon_section", "_scan_board", "_element_text", "_toggle_class_token",
          "_normalize_item_block", "board_header_date_text", "parse_board_date", "_marker_counts", "_item_start_lines",
          "board_structure_ok", "_div_balance", "hand_fingerprint", "_region_text", "placeholder_regions",
          "strict_date_ok", "structure_errors", "_guard_atomic_write", "guard_format_ok", "guard_write_record",
          "guard_remove_record", "guard_prune_records", "_write_tmp", "_rm", "history_dir", "create_history_file"]
COPIED_CONSTS = ["MARKER_START", "MARKER_END", "MOVABLE_SECTIONS", "_SECTION_LABEL_RE", "_CLASS_TAG_RE",
                 "_STRIP_TAGS_RE", "_ITEM_CLASS_RE", "_ANY_CLASS_TAG_RE", "WEEKDAY_JA", "_HEADER_RE", "_TITLE_RE",
                 "_UPD_TIME_RE", "HISTORY_DIRNAME", "PLACEHOLDER_RE", "STRICT_DATE_RE", "GUARD_DIRNAME", "GUARD_FORMAT_V",
                 "GUARD_RECORD_MAX_AGE_SEC", "_guard_last_ns"]


def _sources(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    lines = src.splitlines()
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = "\n".join(lines[node.lineno - 1:node.end_lineno])
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = "\n".join(lines[node.lineno - 1:node.end_lineno])
    return out


class TestCopy(Sandbox):
    def test_source_identical(self):
        a = _sources(BOARD_EDIT)
        b = _sources(GUARD)
        for name in COPIED + COPIED_CONSTS:
            self.assertIsNotNone(b.get(name), name)
            self.assertEqual(a.get(name), b.get(name), name)

    def test_behaviour_matches(self):
        self.create()
        good = self.read().decode("utf-8")
        variants = [good, good.replace("\n", "\r\n"), good.replace("<!-- DECK:AUTO:END -->", ""),
                    good.replace('<div class="section-label">今日中</div>\n',
                                 '<div class="section-label">今日中</div>\n' + NESTED),
                    good.replace("作業A", "作業A &amp; <b>x</b>"), good.replace("<title>", "<title>{{X}}")]
        for t in variants:
            self.assertEqual(gd.hand_fingerprint(t), be.hand_fingerprint(t))
            self.assertEqual(gd.hand_fingerprint(t), dw.hand_fingerprint(t))
            self.assertEqual(gd.structure_errors(t), be.structure_errors(t))
            self.assertEqual(gd.placeholder_regions(t), be.placeholder_regions(t))
            raw = t.encode("utf-8")
            fp, codes = gd.describe(b"\xef\xbb\xbf" + raw)
            self.assertEqual(fp, be.hand_fingerprint(be.decode_board(b"\xef\xbb\xbf" + raw)[0]))
            want = {e["code"] for e in be.structure_errors(t) if e["code"] in ("K1", "K3")}
            if be.PLACEHOLDER_RE.search(be.placeholder_regions(t)):
                want.add("K5")
            self.assertEqual(codes, want)

    def test_reads_records_written_by_writers(self):
        self.create()
        t = self.read().decode("utf-8")
        r1 = be.guard_write_record(self.board, b"x", "f1", "b1", "board_edit")
        r2 = dw.guard_write_record(self.board, b"y", "f2", "b2", "deck")
        r3 = gd.guard_write_record(self.board, b"z", "f3", "b3", "guard")
        recs = {r["writer"]: r for r in gd.list_records(0)}
        self.assertEqual((recs["board_edit"]["fp"], recs["deck"]["fp"], recs["guard"]["fp"]), ("f1", "f2", "f3"))
        self.assertEqual(recs["deck"]["body"], r2[1])
        self.assertTrue(r1 and r3 and t)


if __name__ == "__main__":
    unittest.main()
