# -*- coding: utf-8 -*-
"""skill/hooks/project_board.py の試験（対応表・行の選び方・UserPromptSubmit・Stop・実行全体）。

実行: python -m unittest discover -s tests -v   （リポジトリの直下で）
HOME / USERPROFILE を一時フォルダへ向けるので、フックが見る ~/.claude/today-board/（対応表・.guard/python.txt・
board.html）も一時フォルダの中になる。本物の ~/.claude/ には触れない。実行全体の試験は、make_hooks.py が書いた
hooks.json の command と args で起動する（${CLAUDE_PLUGIN_ROOT} はリポジトリの skill/ に置き換える）。
フォルダ名・プロジェクト名はすべて架空のもの。
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skill")
sys.path.insert(0, os.path.join(SKILL, "hooks"))
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import board_edit as be  # noqa: E402
import guard as gd  # noqa: E402
import make_hooks as mh  # noqa: E402
import project_board as pb  # noqa: E402

_TMP_HOOKS = tempfile.mkdtemp(prefix="tb-pb-hooks-")
with contextlib.redirect_stdout(io.StringIO()):
    _rc = mh.main(["--python", sys.executable, "--out", os.path.join(_TMP_HOOKS, "hooks.json")])
assert _rc == 0
with open(os.path.join(_TMP_HOOKS, "hooks.json"), encoding="utf-8") as _f:
    HOOKS = json.load(_f)
shutil.rmtree(_TMP_HOOKS, ignore_errors=True)


def pb_cmd(event):
    """hooks.json のうち、そのイベントで project_board.py を起動する登録の command と args。"""
    for g in HOOKS["hooks"][event]:
        for h in g["hooks"]:
            if h["args"][-1].endswith("/hooks/project_board.py"):
                return [h["command"]] + [a.replace("${CLAUDE_PLUGIN_ROOT}", SKILL) for a in h["args"]]
    raise AssertionError("%s に project_board.py の登録が無い" % event)


# ---------------------------------------------------------------- 部品

def item(title, note="", chip="pending", due=None, time=None):
    return {"index": 1, "key": "|" + title, "time": time, "title": title, "note": note, "chip": chip,
            "crit": False, "carried": None, "due": due, "due_moved": None, "due_from": None}


def status(sections, **extra):
    d = {"ok": True, "op": "status", "version": "1.17", "board_date": "2026-11-16", "today": "2026-11-16",
         "sections": [{"name": n, "items": its} for n, its in sections]}
    d.update(extra)
    return d


NAMES = ["ShopApp"]


# ---------------------------------------------------------------- 対応表

class NormPath(unittest.TestCase):
    def test_windows_folding(self):
        a = pb.norm_path(r"C:\Work\Shop-App\\", fold_case=True)
        self.assertEqual(a, "c:/work/shop-app")
        self.assertEqual(pb.norm_path("c:/WORK/shop-app", fold_case=True), a)
        self.assertEqual(pb.norm_path(r"C:\Work\.\x\..\Shop-App", fold_case=True), a)

    def test_case_kept_without_folding(self):
        self.assertEqual(pb.norm_path("/home/u/Shop", fold_case=False), "/home/u/Shop")

    def test_relative_and_bad_values(self):
        for v in ["work/shop", "shop", "", "  ", None, 3, ["C:/x"]]:
            self.assertIsNone(pb.norm_path(v, fold_case=True), v)

    def test_tilde(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/someone", "USERPROFILE": r"C:\Users\someone"}):
            got = pb.norm_path("~/work/shop", fold_case=False)
        self.assertTrue(got.endswith("/work/shop"))
        self.assertIsNotNone(got)


class Matching(unittest.TestCase):
    def entries(self, projects, fold=True):
        entries, skipped = pb.parse_map({"projects": projects}, fold_case=fold)
        return entries, skipped

    def test_prefix_on_separator_boundary(self):
        es, _ = self.entries([{"folder": r"C:\Work\shop", "names": ["ShopApp"]}])
        self.assertEqual(pb.match_entry(es, r"C:\Work\shop", fold_case=True)[2], ["ShopApp"])
        self.assertEqual(pb.match_entry(es, r"C:\Work\shop\src\x", fold_case=True)[2], ["ShopApp"])
        self.assertIsNone(pb.match_entry(es, r"C:\Work\shop-old", fold_case=True))
        self.assertIsNone(pb.match_entry(es, r"C:\Work\sho", fold_case=True))
        self.assertIsNone(pb.match_entry(es, r"C:\Work", fold_case=True))

    def test_worktree_under_project(self):
        es, _ = self.entries([{"folder": r"C:\Work\shop", "names": ["ShopApp"]}])
        hit = pb.match_entry(es, r"C:\Work\shop\.claude\worktrees\brave-x-1a2b3c", fold_case=True)
        self.assertEqual(hit[2], ["ShopApp"])

    def test_case_and_slash_insensitive_on_windows(self):
        es, _ = self.entries([{"folder": "c:/work/SHOP/", "names": ["ShopApp"]}])
        self.assertIsNotNone(pb.match_entry(es, r"C:\Work\Shop\src", fold_case=True))

    def test_case_sensitive_elsewhere(self):
        es, _ = self.entries([{"folder": "/home/u/Shop", "names": ["ShopApp"]}], fold=False)
        self.assertIsNone(pb.match_entry(es, "/home/u/shop", fold_case=False))
        self.assertIsNotNone(pb.match_entry(es, "/home/u/Shop/a", fold_case=False))

    def test_longest_folder_wins(self):
        es, _ = self.entries([
            {"folder": r"C:\Work", "names": ["WorkRoot"]},
            {"folder": r"C:\Work\shop\tools\label", "names": ["LabelTool"]},
            {"folder": r"C:\Work\shop", "names": ["ShopApp"]},
        ])
        self.assertEqual(pb.match_entry(es, r"C:\Work\shop\tools\label\x", fold_case=True)[2], ["LabelTool"])
        self.assertEqual(pb.match_entry(es, r"C:\Work\shop\tools", fold_case=True)[2], ["ShopApp"])
        self.assertEqual(pb.match_entry(es, r"C:\Work\blog", fold_case=True)[2], ["WorkRoot"])

    def test_same_folder_first_wins(self):
        es, _ = self.entries([{"folder": r"C:\Work\shop", "names": ["First"]},
                              {"folder": r"C:\work\shop\\", "names": ["Second"]}])
        self.assertEqual(pb.match_entry(es, r"C:\Work\shop", fold_case=True)[2], ["First"])

    def test_bad_entries_are_skipped_others_kept(self):
        es, skipped = self.entries([
            "not an object",
            {"folder": "relative/path", "names": ["A"]},
            {"folder": r"C:\Work\a", "names": "A"},
            {"folder": r"C:\Work\b", "names": ["", "  ", 3]},
            {"folder": r"C:\Work\c", "names": ["C", "", "C", "C2"]},
            {"names": ["D"]},
        ])
        self.assertEqual([e[2] for e in es], [["C", "C2"]])
        self.assertEqual([i for i, _ in skipped], [0, 1, 2, 3, 4, 5])

    def test_empty_names_is_opt_out_marker(self):
        """names が [] の項目は「対応させない」印。最長一致に加わり、子のフォルダの項目が勝つ。"""
        es, skipped = self.entries([{"folder": r"C:\Work", "names": []},
                                    {"folder": r"C:\Work\shop", "names": ["ShopApp"]}])
        self.assertEqual(skipped, [])
        self.assertEqual(pb.match_entry(es, r"C:\Work\blog", fold_case=True)[2], [])
        self.assertEqual(pb.match_entry(es, r"C:\Work\shop\src", fold_case=True)[2], ["ShopApp"])
        # 子が印で親がプロジェクトなら、子のフォルダでは何もしない
        es, _ = self.entries([{"folder": r"C:\Work\shop", "names": ["ShopApp"]},
                              {"folder": r"C:\Work\shop\vendor", "names": []}])
        self.assertEqual(pb.match_entry(es, r"C:\Work\shop\vendor\lib", fold_case=True)[2], [])

    def test_whole_file_shape(self):
        for doc in [[], {"projects": {}}, {"project": []}, "x", None]:
            with self.assertRaises(ValueError):
                pb.parse_map(doc)

    def test_cwd_missing_or_relative(self):
        es, _ = self.entries([{"folder": r"C:\Work\shop", "names": ["ShopApp"]}])
        for cwd in [None, "", "shop", 5]:
            self.assertIsNone(pb.match_entry(es, cwd, fold_case=True))


class MapFile(unittest.TestCase):
    """~/.claude/today-board/projects.json を読む経路（無い・壊れている＝何もしない）。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-pb-map-")
        self.work = os.path.join(self.dir, "work", "shop")
        os.makedirs(self.work)
        self.path = os.path.join(self.dir, "projects.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, data):
        with open(self.path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    def test_hit(self):
        self.write(json.dumps({"projects": [{"folder": self.work, "names": ["ShopApp", "ショップ"]}]},
                              ensure_ascii=False))
        self.assertEqual(pb.names_for_cwd(os.path.join(self.work, "src"), self.path), ["ShopApp", "ショップ"])

    def test_bom_is_read(self):
        self.write(b"\xef\xbb\xbf" + json.dumps({"projects": [{"folder": self.work, "names": ["A"]}]}).encode())
        self.assertEqual(pb.names_for_cwd(self.work, self.path), ["A"])

    def test_missing_broken_or_no_hit_is_none(self):
        self.assertIsNone(pb.names_for_cwd(self.work, self.path))          # 無い
        for raw in [b"{", b"\xff\xfe", b"[]", b'{"projects": 1}', b""]:
            self.write(raw)
            self.assertIsNone(pb.names_for_cwd(self.work, self.path), raw)
        self.write(json.dumps({"projects": [{"folder": self.work, "names": ["A"]}]}))
        self.assertIsNone(pb.names_for_cwd(os.path.join(self.dir, "elsewhere"), self.path))

    def test_opt_out_folder_is_none_and_check_says_ignored(self):
        self.write(json.dumps({"projects": [{"folder": self.dir, "names": []},
                                            {"folder": self.work, "names": ["ShopApp"]}]}))
        self.assertIsNone(pb.names_for_cwd(os.path.join(self.dir, "other"), self.path))
        self.assertEqual(pb.names_for_cwd(self.work, self.path), ["ShopApp"])
        res = pb.check(os.path.join(self.dir, "other"), self.path)
        self.assertEqual(res["match"], {"folder": self.dir, "names": [], "ignored": True})
        self.assertFalse(pb.check(self.work, self.path)["match"]["ignored"])

    def test_check_output(self):
        self.write(json.dumps({"projects": [{"folder": self.work, "names": ["A"]}, {"folder": "rel", "names": ["B"]}]}))
        res = pb.check(os.path.join(self.work, "x"), self.path)
        self.assertTrue(res["ok"])
        self.assertEqual(res["entries"], 1)
        self.assertEqual([s["index"] for s in res["skipped"]], [1])
        self.assertEqual(res["match"]["names"], ["A"])
        res = pb.check(self.dir, self.path)
        self.assertIsNone(res["match"])
        os.remove(self.path)
        self.assertFalse(pb.check(self.work, self.path)["ok"])

    def test_guard_does_not_protect_the_map(self):
        """ボードの保護（guard.py の L1）は対応表への Write・Edit を止めない。"""
        with mock.patch.dict(os.environ, {"HOME": self.dir, "USERPROFILE": self.dir}):
            target = os.path.join(self.dir, ".claude", "today-board", "projects.json")
            self.assertIsNone(gd.protected_kind(target, self.dir))
            self.assertEqual(gd.protected_kind(os.path.join(self.dir, ".claude", "today-board", "board.html"),
                                               self.dir), "board")
            out = gd.dispatch({"hook_event_name": "PreToolUse", "tool_name": "Write",
                               "tool_input": {"file_path": target, "content": "{}"},
                               "session_id": "s", "tool_use_id": "t", "cwd": self.dir})
            self.assertIsNone(out)


# ---------------------------------------------------------------- 行の選び方・文脈

class SelectRows(unittest.TestCase):
    def test_title_note_and_section_for_each_name(self):
        st = status([
            ("今日中", [item("ShopApp: 決済を直す"), item("BlogKit の更新"),
                        item("ログの整理", note="ショップ。経緯は .logs"),
                        item("shopapp を小文字で書いた行"),
                        item("決める: ShopApp の価格")]),
            ("ShopApp（保守）", [item("見出しの下の行")]),
            ("明日以降", [item("別件", note="BlogKit")]),
        ])
        titles = [it["title"] for _, it in pb.select_rows(["ShopApp", "ショップ"], st)]
        self.assertEqual(titles, ["ShopApp: 決済を直す", "ログの整理", "見出しの下の行"])

    def test_alias_in_title_and_note(self):
        st = status([("今日中", [item("ショップ: 在庫"), item("x", note="作業フォルダ C:\\Work\\shop")])])
        self.assertEqual(len(pb.select_rows(["ShopApp", "ショップ"], st)), 1)
        self.assertEqual(len(pb.select_rows(["ShopApp", "C:\\Work\\shop"], st)), 1)

    def test_bad_shape_raises(self):
        with self.assertRaises(ValueError):
            pb.select_rows(NAMES, {"ok": True})
        with self.assertRaises(ValueError):
            pb.select_rows(NAMES, {"ok": True, "sections": [{"name": "x"}]})


class BuildContext(unittest.TestCase):
    def test_fields_and_header(self):
        st = status([("明日以降", [item("ShopApp: 監査", note="補足の文", chip="none", due="2026-11-23")]),
                     ("今日中", [item("ShopApp: 実装", chip="active", time="9:30")])])
        ctx = pb.build_context(["ShopApp", "ショップ"], st)
        self.assertTrue(ctx.startswith(pb.CONTEXT_MARK))
        self.assertIn("「ShopApp」（別名 「ショップ」）", ctx)
        self.assertIn("projects.json", ctx)
        self.assertIn("board_edit.py", ctx)
        self.assertNotIn("FolioInk", ctx)
        self.assertIn("- [明日以降] / 状態: チップなし / タイトル: ShopApp: 監査 / 実施日: 2026-11-23 / 補足: 補足の文", ctx)
        self.assertIn("- [今日中] / 状態: 進行中 / 時刻: 9:30 / タイトル: ShopApp: 実装 / 実施日: なし / 補足: なし", ctx)
        self.assertIn("の行（2 行。うち済 0 行）", ctx)

    def test_chip_labels(self):
        for chip, lab in [("active", "進行中"), ("pending", "未"), ("wait", "条件待ち"), ("hold", "保留")]:
            ctx = pb.build_context(NAMES, status([("今日中", [item("ShopApp: a", chip=chip)])]))
            self.assertIn("状態: " + lab, ctx)

    def test_note_clipped_single_line(self):
        ctx = pb.build_context(NAMES, status([("今日中", [item("ShopApp: a", note="あ" * 300 + "\n次の行")])]))
        row = [ln for ln in ctx.split("\n") if ln.startswith("- ")][0]
        self.assertIn("あ" * pb.NOTE_MAX + "…(以下略)", row)
        self.assertNotIn("あ" * (pb.NOTE_MAX + 1), row)
        self.assertNotIn("次の行", ctx)

    def test_row_cap_and_done_counts(self):
        its = [item("ShopApp: %d" % i) for i in range(pb.MAX_ROWS + 5)]
        its += [item("ShopApp: d%d" % i, chip="done") for i in range(3)]
        ctx = pb.build_context(NAMES, status([("今日中", its)]))
        self.assertEqual(len([ln for ln in ctx.split("\n") if ln.startswith("- ")]), pb.MAX_ROWS)
        self.assertIn("ほか済以外 5 行", ctx)
        self.assertIn("済 3 行（board_edit.py status で確かめる）", ctx)
        self.assertNotIn("ShopApp: d0", ctx)

    def test_no_rows_and_old_board(self):
        ctx = pb.build_context(NAMES, status([("今日中", [item("BlogKit")])], board_date="2026-11-15"))
        self.assertIn("「ShopApp」の行はありません", ctx)
        self.assertIn("ボードの日付は 2026-11-15", ctx)

    def test_not_ok(self):
        self.assertIsNone(pb.build_context(NAMES, {"ok": False}))
        self.assertIsNone(pb.build_context(NAMES, None))


class OnPrompt(unittest.TestCase):
    def run_prompt(self, names=NAMES, st=None, **extra):
        d = {"session_id": "s", "transcript_path": "x.jsonl", "cwd": r"C:\Work\shop",
             "hook_event_name": "UserPromptSubmit", "prompt": "次の作業は？"}
        d.update(extra)
        calls = []
        st = st if st is not None else status([("今日中", [item("ShopApp: a")])])
        out = pb.dispatch(d, fetch=lambda: calls.append(1) or st, names_of=lambda cwd: names)
        return out, calls

    def test_main_session_gets_context(self):
        out, _ = self.run_prompt()
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
        self.assertIn("ShopApp: a", hso["additionalContext"])

    def test_unmapped_folder_does_nothing_and_does_not_run_status(self):
        out, calls = self.run_prompt(names=None)
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_subagent_does_nothing(self):
        out, calls = self.run_prompt(agent_id="a1", agent_type="x")
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_empty_agent_id_is_main(self):
        self.assertIsNotNone(self.run_prompt(agent_id="")[0])

    def test_task_notification_does_nothing(self):
        out, calls = self.run_prompt(prompt="  <task-notification>\n<task-id>x</task-id>")
        self.assertIsNone(out)
        self.assertEqual(calls, [])

    def test_fetch_failure_passes(self):
        d = {"hook_event_name": "UserPromptSubmit", "prompt": "x", "cwd": "C:/w"}
        self.assertIsNone(pb.dispatch(d, fetch=lambda: None, names_of=lambda c: NAMES))
        self.assertIsNone(pb.dispatch(d, fetch=lambda: {"ok": False}, names_of=lambda c: NAMES))

    def test_unknown_event(self):
        self.assertIsNone(pb.dispatch({"hook_event_name": "PreToolUse"}, names_of=lambda c: NAMES))
        self.assertIsNone(pb.dispatch(None))


class FetchStatus(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-pb-fetch-")
        os.makedirs(os.path.join(self.dir, ".claude", "today-board", ".guard"))
        self.py_txt = os.path.join(self.dir, ".claude", "today-board", ".guard", "python.txt")
        self._env = mock.patch.dict(os.environ, {"HOME": self.dir, "USERPROFILE": self.dir})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def fake_run(self, returncode=0, stdout=b"", exc=None):
        def run(*args, **kwargs):
            if exc is not None:
                raise exc
            return subprocess.CompletedProcess(args[0], returncode, stdout, b"")
        return mock.patch.object(pb.subprocess, "run", side_effect=run)

    def test_uses_python_txt_and_skill_board_edit(self):
        fake_py = os.path.join(self.dir, "py.exe")
        open(fake_py, "w").close()
        with open(self.py_txt, "w", encoding="utf-8") as f:
            f.write(fake_py + "\r\n")
        with self.fake_run(stdout=b'{"ok": true}') as m:
            self.assertEqual(pb.fetch_status(), {"ok": True})
        self.assertEqual(m.call_args[0][0], [fake_py, os.path.join(SKILL, "scripts", "board_edit.py"), "status"])

    def test_falls_back_to_running_python(self):
        for content in [None, "  \n", os.path.join(self.dir, "no-python.exe")]:
            if content is None:
                if os.path.exists(self.py_txt):
                    os.remove(self.py_txt)
            else:
                with open(self.py_txt, "w", encoding="utf-8") as f:
                    f.write(content)
            with self.fake_run(stdout=b'{"ok": true}') as m:
                pb.fetch_status()
            self.assertEqual(m.call_args[0][0][0], sys.executable, content)

    def test_failures_are_none(self):
        for kw in [dict(returncode=1, stdout=b'{"ok": false}'), dict(stdout=b"Traceback"),
                   dict(stdout=b"\xff\xfe"), dict(stdout=b""),
                   dict(exc=subprocess.TimeoutExpired(cmd="x", timeout=1)), dict(exc=OSError("x"))]:
            with self.fake_run(**kw):
                self.assertIsNone(pb.fetch_status(), kw)

    def test_board_edit_missing(self):
        with mock.patch.object(pb, "board_edit_path", return_value=os.path.join(self.dir, "none.py")):
            with self.fake_run(stdout=b'{"ok": true}') as m:
                self.assertIsNone(pb.fetch_status())
            m.assert_not_called()


# ---------------------------------------------------------------- Stop

BOARD = "C:/Tools/Python/python.exe ~/.claude/skills/today-board/scripts/board_edit.py"
PS_BOARD = '& $py "$env:USERPROFILE\\.claude\\skills\\today-board\\scripts\\board_edit.py"'


def human(text="次の作業は？"):
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": text},
            "origin": {"kind": "human"}}


def human_blocks(text):
    return {"type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}, "origin": {"kind": "human"}}


def task_notification():
    return {"type": "user", "isSidechain": False,
            "message": {"role": "user", "content": "<task-notification>\n<task-id>x</task-id>"},
            "origin": {"kind": "task-notification"}}


def peer():
    return {"type": "user", "isSidechain": False, "isMeta": True,
            "message": {"role": "user", "content": "Another session says hi"}, "origin": {"kind": "peer"}}


def compact_summary():
    return {"type": "user", "isSidechain": False, "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
            "message": {"role": "user", "content": "This session is being continued ..."}}


def compact_boundary():
    return {"type": "system", "subtype": "compact_boundary", "isSidechain": False,
            "compactMetadata": {"trigger": "auto"}}


def sdk_prompt(text="<system-reminder>\nLinked session …\n</system-reminder>\n依頼の本文"):
    # 他のセッションが立てたセッションの最初の依頼・アプリが入れる依頼の形（origin が無く promptSource がある。2.1.325 で観測）
    return {"type": "user", "isSidechain": False, "promptSource": "sdk", "turnOrigin": "host_synthetic",
            "turnPosition": {"promptIndex": 0, "turnIndex": 1},
            "message": {"role": "user", "content": text}}


def interrupted(text="[Request interrupted by user]"):
    return {"type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def local_command():
    return [{"type": "user", "isSidechain": False, "isMeta": True,
             "message": {"role": "user", "content": "<local-command-caveat>Caveat: …</local-command-caveat>"}},
            {"type": "user", "isSidechain": False,
             "message": {"role": "user", "content": "<command-name>/model</command-name>"}},
            {"type": "user", "isSidechain": False,
             "message": {"role": "user", "content": "<local-command-stdout>Set model</local-command-stdout>"}}]


_ids = iter(range(1, 10 ** 6))


def call(command, error=False, name="Bash"):
    tid = "toolu_%06d" % next(_ids)
    use = {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": {"command": command}}]}}
    res = {"type": "user", "isSidechain": False, "message": {"role": "user", "content": [
        {"tool_use_id": tid, "type": "tool_result", "content": "Exit code 1" if error else "ok", "is_error": error}]}}
    return [use, res]


def ps(command, error=False):
    return call(command, error=error, name="PowerShell")


def stop_feedback(reason):
    return {"type": "user", "isSidechain": False, "isMeta": True,
            "message": {"role": "user", "content": "Stop hook feedback:\n" + reason}}


def text(t="完了しました"):
    return {"type": "assistant", "isSidechain": False,
            "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}


def flatten(*parts):
    out = []
    for p in parts:
        out.extend(p if isinstance(p, list) else [p])
    return out


class TranscriptCase(unittest.TestCase):
    names = NAMES

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-pb-stop-")
        self.path = os.path.join(self.dir, "t.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, *parts, extra_lines=()):
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"type": "custom-title", "customTitle": "t"}) + "\n")
            for line in flatten(*parts):
                f.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
            for raw in extra_lines:
                f.write(raw + "\n")

    def decide(self, names="default", **extra):
        d = {"session_id": "s", "transcript_path": self.path, "cwd": r"C:\Work\shop",
             "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "done"}
        d.update(extra)
        ns = self.names if names == "default" else names
        return pb.dispatch(d, names_of=lambda cwd: ns)

    def assertBlocks(self, **extra):
        out = self.decide(**extra)
        self.assertIsNotNone(out, "止まるはず")
        self.assertEqual(out["decision"], "block")
        self.assertIn(pb.STOP_MARK, out["reason"])
        self.assertIn("board_edit.py", out["reason"])
        return out

    def assertPasses(self, **extra):
        self.assertIsNone(self.decide(**extra))


class Stop(TranscriptCase):
    def test_commit_without_board_update_blocks_with_names(self):
        self.write(human(), call("git add a.ts"), call("git commit -F - <<'EOF'\nfix: x\nEOF"), text())
        out = self.assertBlocks()
        self.assertIn("「ShopApp」", out["reason"])
        self.assertNotIn("FolioInk", out["reason"])

    def test_alias_in_reason(self):
        self.write(human(), call("git push origin main"))
        out = self.assertBlocks(names=["ShopApp", "ショップ"])
        self.assertIn("（別名 「ショップ」）", out["reason"])

    def test_unmapped_folder_never_blocks(self):
        self.write(human(), call("git push origin main"), text())
        self.assertPasses(names=None)

    def test_with_board_update_passes(self):
        self.write(human(), call("git commit -m x"), call(BOARD + " set-chip --item 3 --chip done"), text())
        self.assertPasses()

    def test_close_time_counts_as_write(self):
        self.write(human(), call("git push"), call(BOARD + " close-time --item 3"))
        self.assertPasses()

    def test_status_only_does_not_count(self):
        self.write(human(), call(BOARD + " status"), call("git push origin main"))
        self.assertBlocks()

    def test_no_work_passes(self):
        self.write(human(), call("git status"), call("git log --oneline -3"), text())
        self.assertPasses()

    def test_previous_turn_not_counted(self):
        self.write(human("前"), call("git push origin main"), text(), human("次"), call("git status"), text())
        self.assertPasses()

    def test_task_notification_and_peer_start_turns(self):
        for start in (task_notification, peer):
            self.write(human(), call("git push origin main"), text(), start(), text())
            self.assertPasses()
            self.write(human(), text(), start(), call("git commit -m x"), text())
            self.assertBlocks()

    def test_block_mark_not_carried_over(self):
        for start in (task_notification, peer, human):
            self.write(human(), call("git push"), stop_feedback(pb.stop_reason(NAMES)), text(),
                       start(), call("git push"), text())
            self.assertBlocks()

    def test_compact_summary_and_meta_do_not_start_turn(self):
        meta = human("画像の注記")
        meta["isMeta"] = True
        self.write(human(), call("git push"), text(), compact_summary(), meta, stop_feedback("別のフック"), text())
        self.assertBlocks()

    def test_human_text_blocks_start_turn(self):
        self.write(human(), call("git push"), human_blocks("画像付き"), text())
        self.assertPasses()

    def test_failed_calls_not_counted(self):
        self.write(human(), call("git commit -m x", error=True), text())
        self.assertPasses()
        self.write(human(), call("git push"), call(BOARD + " set-chip --item x --chip done", error=True))
        self.assertBlocks()

    def test_sidechain_lines_ignored(self):
        lines = call("git push origin main")
        for ln in lines:
            ln["isSidechain"] = True
        self.write(human(), lines, text())
        self.assertPasses()

    def test_other_tools_not_looked_at(self):
        self.write(human(), call("git push origin main", name="Monitor"), text())
        self.assertPasses()

    # --- PowerShell ---
    def test_powershell_commit_blocks(self):
        self.write(human(), ps("Set-Location C:\\Work\\shop; git commit -m 'fix: x'"), text())
        self.assertBlocks()

    def test_powershell_board_write_passes(self):
        self.write(human(), ps("git push origin main"),
                   ps('$py = (Get-Content -Raw -Encoding UTF8 "$env:USERPROFILE\\.claude\\today-board\\.guard\\python.txt").Trim()\n'
                      + PS_BOARD + " set-chip --item 3 --chip done"))
        self.assertPasses()

    def test_powershell_mixed_with_bash(self):
        self.write(human(), ps("git push origin main"), call(BOARD + " add --section 今日中 --title ShopApp:x"))
        self.assertPasses()

    def test_powershell_failed_commit_not_counted(self):
        self.write(human(), ps("git commit -m x", error=True), text())
        self.assertPasses()

    # --- 1ターン1回・対象外 ---
    def test_stop_hook_active_passes(self):
        self.write(human(), call("git push"))
        self.assertPasses(stop_hook_active=True)

    def test_blocks_once_per_turn(self):
        self.write(human(), call("git push"), text(), stop_feedback(pb.stop_reason(NAMES)), call("git status"), text())
        self.assertPasses()

    def test_mark_from_other_names_also_counts(self):
        # 印は名前に依らない（対応表を書き換えた後の同じターンでも2回目は止めない）
        self.write(human(), call("git push"), stop_feedback(pb.stop_reason(["Other"])), text())
        self.assertPasses()

    def test_subagent_passes(self):
        self.write(human(), call("git push"))
        self.assertPasses(agent_id="a1", agent_type="x")

    def test_subagent_stop_event_passes(self):
        self.write(human(), call("git push"))
        self.assertPasses(hook_event_name="SubagentStop")

    def test_missing_transcript_passes(self):
        self.assertIsNone(pb.dispatch({"hook_event_name": "Stop", "transcript_path": os.path.join(self.dir, "x")},
                                      names_of=lambda c: NAMES))
        self.assertIsNone(pb.dispatch({"hook_event_name": "Stop"}, names_of=lambda c: NAMES))

    def test_no_turn_start_passes(self):
        self.write(call("git push"), text())
        self.assertPasses()

    # --- origin の無い依頼・要約（2026-11-16 の実測による） ---
    def test_sdk_prompt_without_origin_starts_turn(self):
        # 他のセッションが立てたセッションの最初の依頼（"<system-reminder>…" / "Background (from …"）
        for t in ("<system-reminder>\nLinked session\n</system-reminder>\n依頼", "Background (from the session that started this one)\n依頼"):
            self.write(sdk_prompt(t), call("git add a"), call("git commit -m x"), text())
            self.assertBlocks()
            self.write(sdk_prompt(t), call("git commit -m x"), call(BOARD + " set-chip --item 3 --chip done"), text())
            self.assertPasses()

    def test_sdk_prompt_ends_previous_turn(self):
        self.write(human(), call("git push"), text(), sdk_prompt(), call("git status"), text())
        self.assertPasses()

    def test_sdk_prompt_meta_or_tool_result_is_not_start(self):
        meta = sdk_prompt()
        meta["isMeta"] = True
        res = call("echo x")[1]
        res["promptSource"] = "sdk"
        self.write(human(), call("git push"), meta, res, text())
        self.assertBlocks()

    def test_resume_after_summary_file_blocks(self):
        # 要約で引き継いだファイル（先頭が compact_boundary と要約）。要約の後に依頼が無いまま作業が続く
        self.write(compact_boundary(), compact_summary(), call("git commit -m x"), text())
        self.assertBlocks()
        self.write(compact_boundary(), compact_summary(), call("git commit -m x"),
                   call(BOARD + " set-chip --item 3 --chip done"), text())
        self.assertPasses()
        self.write(compact_boundary(), compact_summary(), call("git status"), text())
        self.assertPasses()

    def test_resume_uses_oldest_summary(self):
        # 始まりが無いファイルで要約が2つあるときは、最も古い要約より後をこのターンとみなす
        self.write(compact_boundary(), compact_summary(), call("git commit -m x"),
                   compact_boundary(), compact_summary(), text())
        self.assertBlocks()

    def test_resume_after_summary_then_prompt(self):
        self.write(compact_boundary(), compact_summary(), call("git push"), text(), human("次"), call("git status"), text())
        self.assertPasses()
        self.write(compact_boundary(), compact_summary(), text(), human("次"), call("git push"), text())
        self.assertBlocks()

    def test_mid_turn_summary_does_not_cut_turn(self):
        # 自動の要約はターンの途中に入る。要約より前（同じファイル）の行の更新もそのターンに数える
        self.write(human(), call(BOARD + " set-chip --item 3 --chip done"), compact_boundary(), compact_summary(),
                   call("git push"), text())
        self.assertPasses()
        self.write(human(), call("git push"), compact_boundary(), compact_summary(), text())
        self.assertBlocks()

    def test_block_mark_before_summary_counts(self):
        self.write(compact_boundary(), compact_summary(), call("git push"), stop_feedback(pb.stop_reason(NAMES)),
                   compact_boundary(), compact_summary(), call("git status"), text())
        self.assertPasses()

    def test_mid_turn_lines_without_origin_are_not_start(self):
        # ターンの途中に現れる origin の無い行（tool_result・中断・ローカルのコマンド・Stop hook feedback）
        for mid in (interrupted(), interrupted("[Request interrupted by user for tool use]"), local_command(),
                    call("echo y")[1], stop_feedback("別のフック")):
            self.write(human(), call("git push"), mid, text())
            self.assertBlocks()

    def test_prefilter_keeps_start_lines(self):
        # 高速の前ふるいが origin の無い始まりの行・要約の行を落とさない
        for start in (sdk_prompt(), compact_summary()):
            raw = json.dumps(start, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.assertTrue(b'"promptSource"' in raw or b'"isCompactSummary"' in raw)
        self.write(human(), call("git push"), text(), sdk_prompt("依頼"), text())
        self.assertPasses()

    def test_broken_lines_skipped(self):
        self.write(human(), call("git push"), extra_lines=['{"type":"assistant","tool_use"', "\xff"])
        self.assertBlocks()

    def test_too_long_turn_passes(self):
        self.write(human(), call("git push origin main"))
        with mock.patch.object(pb, "CHUNK", 16):
            with self.assertRaises(pb.TruncatedRead):
                list(pb.iter_lines_reverse(self.path, max_bytes=32))
            out = pb.dispatch({"hook_event_name": "Stop", "transcript_path": self.path, "cwd": "C:/w"},
                              scan=lambda p: pb.scan_turn(p, max_bytes=32), names_of=lambda c: NAMES)
        self.assertIsNone(out)

    def test_reverse_reader_across_chunks(self):
        self.write(human(), [call("echo %d" % i) for i in range(300)], call("git push origin main"))
        with mock.patch.object(pb, "CHUNK", 37):
            self.assertBlocks()


class CommandDetection(unittest.TestCase):
    def test_git_bash(self):
        yes = ["git commit -F - <<'EOF'\nfix: x\nEOF", "git add a && git commit -m x",
               "git -C /c/Work/shop commit -m x", "git -c core.x=y push origin main",
               "cd /c/Work/shop\ngit push origin main", "git status; git push", "/usr/bin/git push"]
        no = ["git status", "git log --oneline", 'echo "git push"',
              "cat >> a.md <<'EOF'\n- git commit と git push をした\nEOF", "git commit-tree x", "grep -n 'git push' a.md"]
        for c in yes:
            self.assertTrue(pb.is_git_commit_or_push(c), c)
        for c in no:
            self.assertFalse(pb.is_git_commit_or_push(c), c)

    def test_git_powershell(self):
        yes = ["git commit -m 'x'", "Set-Location C:\\Work\\shop; git push origin main",
               "git -C C:\\Work\\shop commit -m \"x\"", "& git.exe push",
               "git commit -F - @'\nfix: x\n'@", "$m = @\"\nbody\n\"@\ngit commit -m $m",
               "git add a\r\ngit commit -m x", "C:\\Program` Files\\Git\\cmd\\git.exe push"]
        no = ["git status", "Write-Output 'git push'", "Select-String -Pattern 'git push' a.md",
              "$m = @'\ngit commit と git push の話\n'@\nWrite-Output $m", "# git push はしない\ngit status"]
        for c in yes:
            self.assertTrue(pb.is_git_commit_or_push(c, "powershell"), c)
        for c in no:
            self.assertFalse(pb.is_git_commit_or_push(c, "powershell"), c)

    def test_board_write_ops_match_board_edit(self):
        """WRITE_OPS・CONFIRM_OPS と書かない操作で、board_edit.py の操作がすべて分かれている。"""
        parser = be.build_parser()
        sub = next(a for a in parser._actions if a.dest == "op")
        ops = set(sub.choices)
        read_only = {"status", "deck-snap", "deck-wait"}
        self.assertEqual(ops, set(pb.WRITE_OPS) | set(pb.CONFIRM_OPS) | read_only)
        self.assertFalse(set(pb.WRITE_OPS) & set(pb.CONFIRM_OPS))
        self.assertEqual(set(be.ITEM_OPS) - {"remove"}, set(pb.WRITE_OPS) - {"create"})

    def test_board_write(self):
        yes = [BOARD + " " + op for op in [
            "add --section 今日中 --title a", "set-chip --item 3 --chip done", "edit --item 3 --note x",
            "set-crit --item 3 on", "set-time --item 3 --time 9:00", "set-due --item 3 --due none",
            "move --item 3 --section 今日中", "create --spec x.json", "close-time --item 3",
            "remove --item a --confirmed", "restore --from history/x.html --confirmed",
            "--ops ~/.claude/today-board/ops/a.json", "--ops=~/.claude/today-board/ops/a.json"]]
        no = [BOARD + " " + op for op in ["status", "--help", "status --board x", "deck-snap",
                                          "deck-wait --since x", "remove --item a", "restore --from history/x.html"]]
        no += ["git commit -m 'board_edit.py set-chip'", "echo board_edit.py"]
        for c in yes:
            self.assertTrue(pb.is_board_write(c), c)
        for c in no:
            self.assertFalse(pb.is_board_write(c), c)

    def test_board_write_powershell(self):
        yes = [PS_BOARD + " set-chip --item 3 --chip done",
               PS_BOARD + ' --ops "$env:USERPROFILE\\.claude\\today-board\\ops\\a.json"',
               "& 'C:\\Tools\\Python\\python.exe' 'C:\\Users\\someone\\.claude\\skills\\today-board\\scripts\\board_edit.py' edit --item 2 --note="]
        no = [PS_BOARD + " status", PS_BOARD + " remove --item a",
              "Get-Content C:\\x\\board_edit.py", "Write-Output 'board_edit.py add'"]
        for c in yes:
            self.assertTrue(pb.is_board_write(c, "powershell"), c)
        for c in no:
            self.assertFalse(pb.is_board_write(c, "powershell"), c)

    def test_line_continuations(self):
        """行の継続で語が切れても、書く操作と git を見落とさない（レビュー W1 の4つの形）。"""
        self.assertTrue(pb.is_board_write(BOARD + " \\\n  set-chip --item 3 --chip done"))
        self.assertTrue(pb.is_git_commit_or_push("git \\\n  commit -m x"))
        self.assertTrue(pb.is_board_write(PS_BOARD + " `\n  set-chip --item 3 --chip done", "powershell"))
        self.assertTrue(pb.is_git_commit_or_push("git `\r\n  commit -m x", "powershell"))
        # 継続の後ろに続くのが読むだけの操作なら数えない
        self.assertFalse(pb.is_board_write(BOARD + " \\\n  status"))

    def test_here_string_operator_is_not_heredoc(self):
        """<<<（ヒア文字列）をヒアドキュメントと読んで、後ろの行を本文として捨てない（レビュー W2）。"""
        self.assertTrue(pb.is_git_commit_or_push('cat <<< "EOF"\ngit push origin main'))
        self.assertTrue(pb.is_board_write('grep x <<< "EOF"\n' + BOARD + " set-chip --item 3 --chip done"))
        self.assertFalse(pb.is_git_commit_or_push("cat <<EOF\ngit push\nEOF"))
        self.assertFalse(pb.is_git_commit_or_push("cat <<-EOF\n\tgit push\n\tEOF"))

    def test_hash_inside_word_is_not_comment(self):
        """語の途中の # は注釈の始まりではない（レビュー Info 1）。"""
        self.assertTrue(pb.is_git_commit_or_push("cd /c/work/a#b && git push"))
        self.assertTrue(pb.is_board_write(BOARD + " edit --item C#入門 --note x"))
        self.assertTrue(pb.is_git_commit_or_push("Set-Location C:\\work\\a#b; git push", "powershell"))
        for c in ["# git push", "echo hi # git push", "git status #; git push", "echo '#' # git push"]:
            self.assertFalse(pb.is_git_commit_or_push(c), c)
        self.assertTrue(pb.is_git_commit_or_push("echo 'a # b'; git push"))
        self.assertFalse(pb.is_git_commit_or_push("<# git push #> git status", "powershell"))
        self.assertTrue(pb.is_git_commit_or_push("<# 注釈 #>\ngit push", "powershell"))

    def test_powershell_comment_after_brace_comma_and_string(self):
        """PowerShell では { } , の直後と、語の始まりで開いたクォートの直後の # も注釈（b8461b1 のレビュー Info 1。
        読み方は PowerShell 5.1 の Parser::ParseInput の字句で確かめた）。"""
        for c in ["if ($x) {# git commit -m a\n}", "foo }# git push", "echo a,# git push", 'echo "a"# git push',
                  "echo 'a'# git push"]:
            self.assertFalse(pb.is_git_commit_or_push(c, "powershell"), c)
        self.assertFalse(pb.is_board_write("if ($x) {# " + PS_BOARD + " set-chip --item 3 --chip done\n}", "powershell"))
        # 語の途中のクォート・エスケープしたクォートの後ろの # は語のまま
        for c in ['echo a"b"# git push', 'echo `"# git push']:
            self.assertTrue(pb.is_git_commit_or_push(c, "powershell"), c)
        # 注釈の後ろの行は読む
        self.assertTrue(pb.is_git_commit_or_push("if ($x) {# 注釈\ngit push }", "powershell"))
        # bash では {# は語（注釈ではない）
        self.assertTrue(pb.is_git_commit_or_push("echo {# git commit"))

    def test_escaped_escape_before_newline_is_not_continuation(self):
        """\\\\＋改行・``＋改行はエスケープした文字と改行で、行の継続ではない（b8461b1 のレビュー Info 2）。"""
        b2, t2 = "\\" * 2, "`" * 2
        self.assertTrue(pb.is_git_commit_or_push("echo a " + b2 + "\ngit commit -m x"))
        self.assertTrue(pb.is_git_commit_or_push("echo a" + b2 + "\ngit push"))
        self.assertTrue(pb.is_git_commit_or_push("echo a " + t2 + "\ngit commit -m x", "powershell"))
        self.assertTrue(pb.is_git_commit_or_push("echo a " + t2 + "\r\ngit push", "powershell"))
        self.assertTrue(pb.is_board_write("echo " + b2 + "\n" + BOARD + " set-chip --item 3 --chip done"))
        # エスケープの文字が奇数個なら継続（\\\\\\＋改行＝エスケープした \\ と継続）
        self.assertEqual(pb.join_continuations("a " + "\\" * 3 + "\nb", "bash"), "a " + b2 + " b")
        self.assertEqual(pb.join_continuations("a " + b2 + "\nb", "bash"), "a " + b2 + "\nb")
        self.assertEqual(pb.join_continuations("a " + "`" * 3 + "\nb", "powershell"), "a " + t2 + " b")
        self.assertEqual(pb.join_continuations("a " + t2 + "\nb", "powershell"), "a " + t2 + "\nb")

    def test_heredoc_mark_in_comment_is_not_heredoc(self):
        """注釈の中の <<EOF・@' をヒアドキュメント・ヒア文字列の始まりと読んで、後ろの行を捨てない（b8461b1 のレビュー Info 3）。"""
        self.assertTrue(pb.is_git_commit_or_push("# 使い方: cat <<EOF\ngit commit -m x"))
        self.assertTrue(pb.is_git_commit_or_push("echo hi # <<EOF\ngit push"))
        self.assertTrue(pb.is_board_write("# <<'EOF'\n" + BOARD + " set-chip --item 3 --chip done"))
        self.assertTrue(pb.is_git_commit_or_push("# note @'\ngit commit -m x", "powershell"))
        self.assertTrue(pb.is_git_commit_or_push("<# @'\n#>\ngit push", "powershell"))
        # 本物の印は従来どおり本文を捨てる（$( … ) の中の <<'EOF' を含む）
        self.assertFalse(pb.is_git_commit_or_push("cat <<EOF # 注釈\ngit push\nEOF"))
        self.assertFalse(pb.is_git_commit_or_push("echo \"$(cat <<'EOF'\ngit push\nEOF\n)\""))
        self.assertTrue(pb.is_git_commit_or_push("git commit -m \"$(cat <<'EOF'\nfix: x\n\nit's git push\nEOF\n)\""))
        self.assertFalse(pb.is_git_commit_or_push("$m = @'\ngit push\n'@\nWrite-Output $m", "powershell"))
        # 注釈の中の '"' でクォートの状態を持ち越さない
        self.assertTrue(pb.is_git_commit_or_push("# it's\ngit push"))

    def test_powershell_escaped_brace_comma_is_not_comment_start(self):
        """エスケープした { } , の直後の # は語の続き（v1.2 のレビュー W1）。"""
        for c in ["echo a`,# git push", "echo a`{# git push", "echo a`}# git push", "echo a` # git push"]:
            self.assertTrue(pb.is_git_commit_or_push(c, "powershell"), c)
        self.assertTrue(pb.is_git_commit_or_push("echo a\\ # git push"))
        # エスケープしていない形は従来どおり注釈
        for c in ["echo a,# git push", "echo a{# git push"]:
            self.assertFalse(pb.is_git_commit_or_push(c, "powershell"), c)

    def test_quote_state_carried_across_lines(self):
        """行をまたぐクォートの状態を次の行へ持ち越す（v1.2 のレビュー W2。変異 M8・M9・M10 を落とす）。"""
        # 複数行の "…" の中の # は注釈ではないので、後ろの <<EOF は本物の印＝本文を捨てる
        self.assertFalse(pb.is_git_commit_or_push('echo "x\n# y" ; cat <<EOF\ngit push\nEOF'))
        self.assertFalse(pb.is_git_commit_or_push("echo 'x\n# y' ; cat <<EOF\ngit push\nEOF"))
        # クォートを閉じた後の行の # は注釈＝その中の <<EOF は印ではない
        self.assertTrue(pb.is_git_commit_or_push('echo "x\ny"\n# <<EOF\ngit push'))
        # PowerShell: 複数行の "…" の中の # の後のヒア文字列の始まりは本物
        # （本文に ' を置き、本文を捨て損ねると git push がクォートの外に出る形にする）
        self.assertFalse(pb.is_git_commit_or_push('$a = "x\n# y" ; $m = @\'\nit\'s\ngit push\n\'@\nWrite-Output $m',
                                                  "powershell"))
        self.assertTrue(pb.is_git_commit_or_push('$a = "x\ny"\n# @\'\ngit push', "powershell"))
        # ヒア文字列を閉じた後はクォートの外に戻る（開く行の前の行から持ち越したクォートの状態を残さない）
        self.assertTrue(pb.is_git_commit_or_push("$m = @'\nit's\n'@\n# @'\ngit push", "powershell"))
        self.assertTrue(pb.is_git_commit_or_push(
            '$a = "x\ny"; $m = @\'\nbody\n\'@\n# x " ; $n = @\'\ngit push\n\'@', "powershell"))

    def test_powershell_block_comment_inside_word(self):
        """a<#x#>git push の <# … #> は注釈（1つの空白）で、後ろの git push は読む（v1.2 のレビュー Info 4・M13）。"""
        self.assertTrue(pb.is_git_commit_or_push("a<#x#>git push", "powershell"))
        self.assertEqual(pb.strip_comments("a<#x#>git push", "powershell"), "a git push")

    def test_backslash_at_end_of_comment_is_not_continuation(self):
        """注釈の行末の \\ ・ ` は継続ではなく、次の行は別のコマンド（v1.2 のレビュー Info 3）。"""
        self.assertTrue(pb.is_git_commit_or_push("# 注釈 \\\ngit push"))
        self.assertTrue(pb.is_git_commit_or_push("echo a # 注釈 \\\ngit push"))
        self.assertTrue(pb.is_git_commit_or_push("# 注釈 `\ngit push", "powershell"))
        self.assertTrue(pb.is_board_write("# x \\\n" + BOARD + " set-chip --item 3 --chip done"))
        # 注釈の外の継続は従来どおり
        self.assertTrue(pb.is_git_commit_or_push("git \\\n  push"))
        self.assertFalse(pb.is_git_commit_or_push("echo \\\n# git push"))

    def test_hash_after_escaped_newline(self):
        """継続の直後の # は、継続を除いた並びで注釈かどうかを決める（v1.2 のレビュー W3・I7）。"""
        b, t = "\\", "`"
        # 継続の前が空白: #x は注釈で、注釈の行末の継続は継続ではない＝git push は別のコマンド
        self.assertTrue(pb.is_git_commit_or_push("echo a " + b + "\n#x " + b + "\ngit push"))
        self.assertTrue(pb.is_git_commit_or_push("echo a " + t + "\n#x " + t + "\ngit push", "powershell"))
        # 継続の前が語: a#x は1語で注釈ではない＝その後ろの <<EOF・@' は本物の印で、本文の git push は見ない
        # （"echo a\＋改行＋#x \＋改行＋git push" は実物では echo の引数だが、echo git push と同じく作業と数える〔SKILL.md の残る限界〕ので、
        #  この形では注釈かどうかの読み分けを試せない）
        self.assertFalse(pb.is_git_commit_or_push("echo a" + b + "\n#x <<EOF\ngit push\nEOF"))
        self.assertFalse(pb.is_git_commit_or_push("echo a" + t + "\n#x @'\ngit push\n'@", "powershell"))
        # 継続の前が空白なら #x <<EOF は注釈＝印ではなく、git push を読む
        self.assertTrue(pb.is_git_commit_or_push("echo a " + b + "\n#x <<EOF\ngit push\nEOF"))
        # a#x の後ろの ; からは別のコマンド（PowerShell 5.1 の Parser::ParseInput の字句で確かめた形）
        self.assertTrue(pb.is_git_commit_or_push("echo a" + b + "\n#x; git push"))
        self.assertTrue(pb.is_git_commit_or_push("echo a" + t + "\n#x; git push", "powershell"))
        self.assertFalse(pb.is_git_commit_or_push("echo a " + b + "\n#x; git push"))

    def test_powershell_continuation_after_closed_quote(self):
        """語の始まりで開いたクォートを閉じた直後の継続の次の行の # は注釈（v1.2 のレビュー W4。読み方は PowerShell 5.1 の
        Parser::ParseInput の字句で確かめた）。語の途中のクォートなら語の続き。"""
        t = "`"
        self.assertTrue(pb.is_git_commit_or_push('echo "a"' + t + "\n# note @'\ngit push\n'@", "powershell"))
        self.assertTrue(pb.is_git_commit_or_push("echo 'a'" + t + "\n# note @'\ngit push\n'@", "powershell"))
        self.assertFalse(pb.is_git_commit_or_push('echo a"b"' + t + "\n#x @'\ngit push\n'@", "powershell"))

    def test_powershell_continuation_prefix_with_quote_in_body(self):
        """PowerShell で継続の次の行の印を見分ける形（v1.2 のレビュー W5）。本文に ' を置き、本文を捨て損ねると
        git push がクォートの外に出る形にする。"""
        t = "`"
        self.assertFalse(pb.is_git_commit_or_push("echo a" + t + "\n#x @'\nit's\ngit push\n'@", "powershell"))
        self.assertFalse(pb.is_git_commit_or_push("echo a" + t + "\n#x @'\ngit push\n'@\nWrite-Output it's",
                                                  "powershell"))
        # 継続が2行続いても、最初の行から見分ける
        self.assertFalse(pb.is_git_commit_or_push("echo a" + t + "\nb" + t + "\n#x @'\nit's\ngit push\n'@",
                                                  "powershell"))
        # 2行目の "b" が語の始まりのクォートかどうかも1行目から決まる（a`＋改行＋"b"`＋改行＋#x は1語＝Parser::ParseInput で確かめた）
        self.assertFalse(pb.is_git_commit_or_push("echo a" + t + '\n"b"' + t + "\n#x @'\ngit push\n'@",
                                                  "powershell"))
        self.assertTrue(pb.is_git_commit_or_push('echo "a"' + t + "\nb " + t + "\n#x @'\ngit push\n'@",
                                                 "powershell"))

    def test_continuation_after_multiline_quote(self):
        """前の行から続くクォートを閉じた後の継続でも、次の行の # を正しく見分ける（v1.2 のレビュー W7）。"""
        self.assertTrue(pb.is_git_commit_or_push('echo "x\ny" a \\\n#z <<EOF\ngit push\nEOF'))
        self.assertTrue(pb.is_git_commit_or_push('echo "x\ny" a `\n#z @\'\ngit push\n\'@\nWrite-Output it\'s',
                                                 "powershell"))
        # 継続の前が語なら、次の行の #z は語の続き＝印は本物で、本文を捨てる
        self.assertFalse(pb.is_git_commit_or_push('echo "x\ny" a\\\n#z <<EOF\ngit push\nEOF'))
        self.assertFalse(pb.is_git_commit_or_push('echo "x\ny" a`\n#z @\'\nit\'s\ngit push\n\'@', "powershell"))

    def test_continuation_through_escape_only_lines(self):
        """エスケープの文字だけの行が続いても、最初の継続の位置で決まる（a`＋改行＋`＋改行＋#x は1語＝Parser::ParseInput で確かめた）。"""
        b, t = "\\", "`"
        self.assertFalse(pb.is_git_commit_or_push("echo a" + t + "\n" + t + "\n#x @'\ngit push\n'@", "powershell"))
        self.assertFalse(pb.is_git_commit_or_push("echo a" + b + "\n" + b + "\n#x <<EOF\ngit push\nEOF"))
        self.assertTrue(pb.is_git_commit_or_push("echo a " + t + "\n" + t + "\n#x @'\ngit push\n'@", "powershell"))
        self.assertTrue(pb.is_git_commit_or_push("echo a " + b + "\n" + b + "\n#x <<EOF\ngit push\nEOF"))

    def test_continuation_state_after_heredoc_body(self):
        """ヒアドキュメント・ヒア文字列の後ろの行は、開いた行の継続の続きではない。"""
        self.assertTrue(pb.is_git_commit_or_push("cat <<EOF a\\\nbody\nEOF\n#x <<END\ngit push\nEND"))
        self.assertTrue(pb.is_git_commit_or_push("echo a`\n$m = @'\nbody\n'@\n#x @'\ngit push\n'@", "powershell"))

    def test_long_continuations_are_fast(self):
        """継続を 2000 行続けても数秒で判定する（v1.2 のレビュー W6。フックの時間切れは 15 秒で、切れると何も止めない）。"""
        import time
        for shell, esc in (("bash", "\\"), ("powershell", "`")):
            for line in ("echo " + "a" * 70 + " " + esc, esc):
                cmd = "\n".join([line] * 2000) + "\ngit push"
                t0 = time.monotonic()
                self.assertTrue(pb.is_git_commit_or_push(cmd, shell), (shell, line[:6]))
                self.assertLess(time.monotonic() - t0, 3.0, (shell, line[:6]))

    def test_board_edit_through_variable_is_not_counted(self):
        """変数に入れたパスで呼んだ board_edit.py は数えない（SKILL.md の残る限界に書いた形）。"""
        self.assertFalse(pb.is_board_write('$be = "C:\\x\\board_edit.py"\n& $py $be set-chip --item 3 --chip done',
                                           "powershell"))

    def test_unparsable(self):
        self.assertTrue(pb.is_git_commit_or_push("git push origin 'main"))
        self.assertTrue(pb.is_git_commit_or_push("git push origin 'main", "powershell"))
        self.assertFalse(pb.is_board_write(BOARD + " set-chip --item 'x"))


# ---------------------------------------------------------------- 実行全体（hooks.json の登録で起動）

class WholeRun(unittest.TestCase):
    """サンドボックスの HOME で、本物の board_edit.py status と対応表を使って起動する。"""

    SPEC = {"sections": ["今日の予定", "今日中", "明日以降"],
            "items": [{"section": "今日中", "title": "ShopApp: 決済を直す", "chip": "active"},
                      {"section": "今日中", "title": "在庫の表を見直す", "note": "ショップ"},
                      {"section": "今日中", "title": "BlogKit: 記事を書く"},
                      {"section": "明日以降", "title": "ShopApp: 来週の件"}]}

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tb-pb-run-")
        self.data = os.path.join(self.dir, ".claude", "today-board")
        os.makedirs(os.path.join(self.data, ".guard"))
        self.board = os.path.join(self.data, "board.html")
        self.shop = os.path.join(self.dir, "work", "shop")
        self.blog = os.path.join(self.dir, "work", "blog")
        self.other = os.path.join(self.dir, "work", "other")
        for d in (self.shop, self.blog, self.other):
            os.makedirs(d)
        with open(os.path.join(self.data, ".guard", "python.txt"), "w", encoding="utf-8") as f:
            f.write(sys.executable + "\n")
        with open(os.path.join(self.data, "projects.json"), "w", encoding="utf-8") as f:
            json.dump({"projects": [{"folder": self.shop, "names": ["ShopApp", "ショップ"]},
                                    {"folder": self.blog, "names": ["BlogKit"]}]}, f, ensure_ascii=False)
        self._env = mock.patch.dict(os.environ, {"HOME": self.dir, "USERPROFILE": self.dir})
        self._env.start()
        self.env = dict(os.environ)
        spec = os.path.join(self.dir, "spec.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump(self.SPEC, f, ensure_ascii=False)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(be.main(["create", "--board", self.board, "--spec", spec]), 0)

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_hook(self, event, payload, raw=None):
        data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        r = subprocess.run(pb_cmd(event), input=data, capture_output=True, env=self.env, cwd=self.other, timeout=60)
        self.assertEqual((r.returncode, r.stderr), (0, b""))
        out = r.stdout.decode("ascii")
        return json.loads(out) if out.strip() else None

    def prompt(self, cwd, **extra):
        d = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": cwd, "prompt": "次へ",
             "transcript_path": os.path.join(self.dir, "t.jsonl")}
        d.update(extra)
        return self.run_hook("UserPromptSubmit", d)

    def test_registered_with_timeout(self):
        for event in ("UserPromptSubmit", "Stop"):
            cmd = pb_cmd(event)
            self.assertEqual(cmd[1:3], ["-I", "-c"])
        timeouts = [h["timeout"] for e in ("UserPromptSubmit", "Stop") for g in HOOKS["hooks"][e]
                    for h in g["hooks"] if h["args"][-1].endswith("project_board.py")]
        self.assertTrue(all(t > pb.STATUS_TIMEOUT_SEC for t in timeouts), timeouts)

    def test_two_mapped_folders_get_their_own_rows(self):
        ctx = self.prompt(os.path.join(self.shop, "src"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ShopApp: 決済を直す", ctx)
        self.assertIn("在庫の表を見直す", ctx)        # 別名を補足に含む行
        self.assertIn("ShopApp: 来週の件", ctx)
        self.assertNotIn("BlogKit: 記事を書く", ctx)
        ctx = self.prompt(self.blog)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("BlogKit: 記事を書く", ctx)
        self.assertNotIn("ShopApp", ctx)

    def test_worktree_maps_to_project(self):
        wt = os.path.join(self.shop, ".claude", "worktrees", "brave-x")
        os.makedirs(wt)
        out = self.prompt(wt)
        self.assertIn("ShopApp: 決済を直す", out["hookSpecificOutput"]["additionalContext"])

    def test_unmapped_subagent_notification_are_silent(self):
        self.assertIsNone(self.prompt(self.other))
        self.assertIsNone(self.prompt(self.shop, agent_id="a1"))
        self.assertIsNone(self.prompt(self.shop, prompt="<task-notification>\nx"))

    def test_opt_out_folder_is_silent_for_both_hooks(self):
        with open(os.path.join(self.data, "projects.json"), "w", encoding="utf-8") as f:
            json.dump({"projects": [{"folder": os.path.join(self.dir, "work"), "names": []},
                                    {"folder": self.shop, "names": ["ShopApp"]}]}, f)
        self.assertIsNone(self.prompt(self.other))
        self.assertIsNotNone(self.prompt(self.shop))
        t = os.path.join(self.dir, "t.jsonl")
        with open(t, "w", encoding="utf-8", newline="\n") as f:
            for line in flatten(human(), call("git push"), text()):
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        stop = {"hook_event_name": "Stop", "session_id": "s", "transcript_path": t, "stop_hook_active": False}
        self.assertIsNone(self.run_hook("Stop", dict(stop, cwd=self.other)))
        self.assertEqual(self.run_hook("Stop", dict(stop, cwd=self.shop))["decision"], "block")

    def test_no_or_broken_map_is_silent(self):
        mp = os.path.join(self.data, "projects.json")
        with open(mp, "wb") as f:
            f.write(b"{ broken")
        self.assertIsNone(self.prompt(self.shop))
        os.remove(mp)
        self.assertIsNone(self.prompt(self.shop))

    def test_broken_input_is_silent(self):
        for raw in [b"", b"{", b"[1,2]", b"\xff\xfe", b'"str"', b"null"]:
            self.assertIsNone(self.run_hook("UserPromptSubmit", None, raw=raw), raw)
            self.assertIsNone(self.run_hook("Stop", None, raw=raw), raw)

    def test_stop_block_then_pass(self):
        t = os.path.join(self.dir, "t.jsonl")

        def write(*parts):
            with open(t, "w", encoding="utf-8", newline="\n") as f:
                for line in flatten(*parts):
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
        stop = {"hook_event_name": "Stop", "session_id": "s", "transcript_path": t, "cwd": self.shop,
                "stop_hook_active": False}
        write(human(), ps("git commit -m x"), text())
        out = self.run_hook("Stop", stop)
        self.assertEqual(set(out), {"decision", "reason"})
        self.assertEqual(out["decision"], "block")
        self.assertIn("「ShopApp」", out["reason"])
        write(human(), ps("git commit -m x"), text(), stop_feedback(out["reason"]), text())
        self.assertIsNone(self.run_hook("Stop", stop))
        write(human(), ps("git commit -m x"), text())
        self.assertIsNone(self.run_hook("Stop", dict(stop, cwd=self.other)))


class CheckCli(unittest.TestCase):
    def test_check_runs_and_reports(self):
        d = tempfile.mkdtemp(prefix="tb-pb-cli-")
        try:
            data = os.path.join(d, ".claude", "today-board")
            os.makedirs(data)
            env = dict(os.environ, HOME=d, USERPROFILE=d)
            script = os.path.join(SKILL, "hooks", "project_board.py")
            r = subprocess.run([sys.executable, "-I", script, "--check", "--cwd", d], capture_output=True,
                               env=env, timeout=30)
            self.assertEqual(r.returncode, 1)
            self.assertFalse(json.loads(r.stdout.decode("utf-8"))["exists"])
            with open(os.path.join(data, "projects.json"), "w", encoding="utf-8") as f:
                json.dump({"projects": [{"folder": d, "names": ["ShopApp"]}]}, f)
            r = subprocess.run([sys.executable, "-I", script, "--check", "--cwd", os.path.join(d, "x")],
                               capture_output=True, env=env, timeout=30)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(json.loads(r.stdout.decode("utf-8"))["match"]["names"], ["ShopApp"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
