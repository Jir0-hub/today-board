"""今日の側の行の実施日（due）と一度移した印（due_moved）、move・add が Deck と同じ形を作ること、create の消える行の数え方の試験。

- 今日の予定・今日中へ足し直す行も、元の行の due と due_moved を対で写せる（add・set-due・create の spec）
- 実施日のある「明日以降」の行を move で今日の側へ動かすと、Deck の日付の切り替え（deck_watcher.py の _move_due_block）と
  同じ形になる（一度移した印のある行・実施日の前の行も＝board_edit.py v1.7・Deck v2.11）。時刻付きの行は、今日の予定へは
  --after／--before が無くても時刻の順の位置へ入る
- 時刻の欄を書く操作（set-time・set-due・add・create の spec）は、時刻の欄と実施日の時刻を同じ値にする（v1.7）
- create の消える行の確かめは、「明日以降」の行の実施日の日付も比べ、同じ行の数も数える
- 足し直しの案内の文（board_edit.py のエラー文・案内・SKILL.md・deck/README.md）が、写す形になっている

すべて一時フォルダのサンドボックスで行う（test_board_edit.Sandbox）。Deck はワークツリーの deck_watcher.py を読み込んだもの（tbe.dw）。
"""
import json
import os
import re
import sys
import unittest
from datetime import date, timedelta

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_board_edit as tbe  # noqa: E402

be, dw = tbe.be, tbe.dw
TODAY = date.today()


def iso(days=0):
    return (TODAY + timedelta(days=days)).isoformat()


def blocks(text):
    """{タイトル: (見出し, ブロック)}（Deck の読み方）。"""
    lines = text.splitlines(keepends=True)
    out = {}
    for (s, e, name) in dw._scan_board(lines)[1]:
        blk = "".join(lines[s:e + 1])
        out[dw._element_text(blk, "task-title")] = (name, blk)
    return out


def titles_in(text, section):
    lines = text.splitlines(keepends=True)
    return [dw._element_text("".join(lines[s:e + 1]), "task-title")
            for (s, e, name) in dw._scan_board(lines)[1] if name == section]


class Base(tbe.Sandbox):
    def ok(self, *args):
        rc, out = self.ed(*args)
        self.assertEqual(rc, 0, (args, out))
        return out

    def ng(self, *args):
        before = self.read()
        rc, out = self.ed(*args)
        self.assertEqual(rc, 1, (args, out))
        self.assertUnchanged(before)
        return out["error"]

    def by(self, title, section=None):
        hits = [i for i in self.items() if i["title"] == title and (section is None or i["section"] == section)]
        self.assertEqual(len(hits), 1, hits)
        return hits[0]

    def put_due(self, title, value):
        """「明日以降」の行の data-due を書き換える（今日以前の実施日の行を作る。add・set-due は K13 の警告を出すが書ける）。"""
        self.ok("set-due", "--item", title, "--due", value)

    def make_conflict(self, title, due, tm, chip="none"):
        """「明日以降」に、時刻の欄（tm）が実施日の時刻（due）と違う行を作る。v1.7 の set-time・set-due・add・create はこの形を作らない（時刻の欄を書く操作は
        実施日の時刻も同じ値にする）ので、v1.6 までにできた行として、時刻の欄の時刻で実施日を付けた後に data-due を書き換える
        （v1.9 の add は今日の側の行の先の日の実施日を今日にするので、今日の側を経ずに「明日以降」で作る）。"""
        self.ok("add", "--section", "明日以降", "--title", title, "--time", tm, "--chip", chip)
        self.ok("set-due", "--item", "%s|%s" % (tm, title), "--due", due.split(" ")[0] + " " + tm)
        self.put_legacy_due(title, due, tm)
        hits = [i for i in self.items() if i["title"] == title and i["section"] == "明日以降" and i["time"] == tm]
        self.assertEqual([(i["due"], i["due_moved"]) for i in hits], [(due, None)])


# ------------------------------------------------------------------ 1. 今日の側の行の due と due_moved

class TestTodaySideDuePair(Base):
    def test_add_needs_pair_on_today_side(self):
        self.create()
        for sec in ("今日中", "今日の予定"):
            err = self.ng("add", "--section", sec, "--title", "x", "--due", iso(1))
            self.assertIn("--due には --due-moved も要ります", err)
            self.assertIn("「明日以降」へ足す", err)
        err = self.ng("add", "--section", "ルーチンタスク", "--title", "x", "--due", iso(1), "--due-moved", "none")
        self.assertIn("「明日以降」の行と、今日の予定・今日中へ足し直す行だけ", err)
        err = self.ng("add", "--section", "今日中", "--title", "x", "--due-moved", iso(0))
        self.assertIn("--due と一緒にだけ", err)
        for bad in ("2026-02-30", iso(0) + " 9:00", "昨日"):
            err = self.ng("add", "--section", "今日中", "--title", "x", "--due", iso(0), "--due-moved", bad)
            self.assertIn("一度移した印", err)

    def test_add_copies_pair_and_time_on_today_side(self):
        self.create()
        self.ok("add", "--section", "今日の予定", "--title", "印あり", "--time", "12:30",
                "--due", iso(0) + " 12:30", "--due-moved", iso(0))
        self.ok("add", "--section", "今日中", "--title", "印なし", "--due", iso(3), "--due-moved", "none")
        a, b = self.by("印あり"), self.by("印なし")
        self.assertEqual((a["section"], a["time"], a["due"], a["due_moved"]), ("今日の予定", "12:30", iso(0) + " 12:30", iso(0)))
        # 先の日の実施日を写した今日の側の行は今日の行になる（v1.8・Deck v2.12 までに前もって動かした行の写し。Deck v2.13 の引き継ぎと同じ・v1.9）
        self.assertEqual((b["section"], b["time"], b["due"], b["due_moved"], b["due_from"]), ("今日中", None, iso(0), iso(0), iso(3)))
        blk = blocks(self.text())["印あり"][1]
        self.assertIn('data-due="%s 12:30" data-due-moved="%s"' % (iso(0), iso(0)), blk)   # Deck と同じ属性の順
        self.assertEqual(self.status()["due_now"], [])
        self.assertIn("12:30|印あり", [x[0] for x in dw.read_board_alarms(self.board)])

    def test_add_mark_on_tomorrow_keeps_row_from_moving(self):
        self.create()
        self.ok("add", "--section", "明日以降", "--title", "戻した件", "--due", iso(-1), "--due-moved", iso(-2))
        it = self.by("戻した件")
        self.assertEqual((it["due"], it["due_moved"]), (iso(-1), iso(-2)))
        st = self.status()
        self.assertEqual(st["due_now"], [])
        self.assertNotIn("K13", [w["code"] for w in st["warnings"]])
        self.assertEqual(dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")[1]["due_moved"], 0)

    def test_set_due_pair_on_today_side(self):
        self.create()
        err = self.ng("set-due", "--item", "作業A", "--due", iso(2))
        self.assertIn("move --section 明日以降", err)
        self.assertIn("--due-moved", err)
        self.ok("set-due", "--item", "作業A", "--due", iso(0), "--due-moved", iso(0))
        self.assertEqual((self.by("作業A")["due"], self.by("作業A")["due_moved"]), (iso(0), iso(0)))
        self.ok("set-due", "--item", "作業A", "--due", iso(4), "--due-moved", "none")     # 先の日の実施日も今日にする（v1.9）
        self.assertEqual((self.by("作業A")["due"], self.by("作業A")["due_moved"], self.by("作業A")["due_from"]), (iso(0), iso(0), iso(4)))
        self.ng("set-due", "--item", "作業A", "--due", "none", "--due-moved", iso(0))
        self.ok("set-due", "--item", "作業A", "--due", "none")
        self.assertEqual((self.by("作業A")["due"], self.by("作業A")["due_moved"]), (None, None))
        self.ng("set-due", "--item", "ログを更新する", "--due", iso(1), "--due-moved", "none")

    def test_set_due_mark_on_tomorrow(self):
        self.create()
        self.ok("set-due", "--item", "来週の件", "--due", iso(0), "--due-moved", iso(0))
        self.assertEqual(self.status()["due_now"], [])
        self.ok("set-due", "--item", "来週の件", "--due", iso(0))             # 省くと印を外す（従来どおり）
        self.assertEqual([i["title"] for i in self.status()["due_now"]], ["来週の件"])

    def test_spec_pair(self):
        base = {"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日の予定", "time": "21:00", "title": "予定", "due": iso(0) + " 21:00", "due_moved": iso(0)},
            {"section": "今日中", "title": "先に動かした", "due": iso(2), "due_moved": None},
            {"section": "明日以降", "title": "戻した件", "due": iso(-1), "due_moved": iso(-1)},
            {"section": "明日以降", "title": "来た件", "due": iso(0)}]}
        out = self.create(base)
        self.assertEqual([m["title"] for m in out["moved_due"]], ["来た件"])     # 印のある行は今日の側へ置かない（Deck と同じ）
        got = {i["title"]: (i["section"], i["time"], i["due"], i["due_moved"]) for i in self.items()}
        self.assertEqual(got["予定"], ("今日の予定", "21:00", iso(0) + " 21:00", iso(0)))
        self.assertEqual(got["先に動かした"], ("今日中", None, iso(0), iso(0)))     # 先の日の実施日も今日にする（v1.9）
        self.assertEqual(self.by("先に動かした")["due_from"], iso(2))
        self.assertEqual(got["戻した件"], ("明日以降", None, iso(-1), iso(-1)))
        self.assertEqual(got["来た件"], ("今日中", None, iso(0), iso(0)))
        for bad in ({"section": "今日中", "title": "x", "due": iso(0)},
                    {"section": "今日中", "title": "x", "due_moved": iso(0)},
                    {"section": "ルーチンタスク", "title": "x", "due": iso(0), "due_moved": None},
                    {"section": "明日以降", "title": "x", "due": iso(1), "due_moved": "11/3"},
                    {"section": "明日以降", "title": "x", "due": iso(1), "time": "9:00"}):
            p = self.write_spec({"sections": ["今日中", "ルーチンタスク", "明日以降"], "items": [bad]})
            rc, err = tbe.run(["create", "--board", os.path.join(self.dir, "other.html"), "--spec", p])
            self.assertEqual(rc, 1, (bad, err))
            self.assertFalse(os.path.exists(os.path.join(self.dir, "other.html")))
        p = self.write_spec({"sections": ["今日中"], "items": [{"section": "今日中", "title": "x", "due": iso(0)}]})
        rc, err = tbe.run(["create", "--board", os.path.join(self.dir, "other.html"), "--spec", p])
        self.assertIn('"due_moved": null', err["error"])

    def test_readd_moved_row_keeps_due_and_mark_and_move_back_redecides_due(self):
        """Deck が移した行を restore の後に足し直すと、元の行と同じ欄になる。「明日以降」へ戻すときは実施日を決め直し、印は外れる
        （move --due・v1.9。決めた日より前には移さない）。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "夜の件"},
            {"section": "明日以降", "title": "日だけの件"}]})
        self.put_due("夜の件", iso(0) + " 21:00")
        self.put_due("日だけの件", iso(0))
        rolled, info = dw.roll_board_text(self.text(), TODAY, "0:00")
        self.assertEqual(info["due_moved"], 2)
        self.write(rolled)
        orig = {t: self.by(t) for t in ("夜の件", "日だけの件")}
        self.assertEqual((orig["夜の件"]["section"], orig["夜の件"]["due_moved"]), ("今日の予定", iso(0)))
        self.assertEqual((orig["日だけの件"]["section"], orig["日だけの件"]["due_moved"]), ("今日中", iso(0)))
        full = self.read()
        self.ok("remove", "--item", "21:00|夜の件", "--confirmed")
        self.ok("remove", "--item", "|日だけの件", "--confirmed")
        rel = "history/board-%s-lastgood-120000.html" % iso(0)
        os.makedirs(os.path.join(self.dir, "history"), exist_ok=True)
        with open(os.path.join(self.dir, rel), "wb") as f:
            f.write(self.read())
        with open(self.board, "wb") as f:
            f.write(full)
        out = self.ok("restore", "--from", rel, "--confirmed")
        now = {x["title"]: x for x in out["diff"]["only_now"]}
        self.assertEqual(sorted(now), ["夜の件", "日だけの件"])
        # 案内のとおり time・chip・note・due・due_moved・due_from を写す（due_moved が null なら --due-moved none）
        for t in ("夜の件", "日だけの件"):
            r = now[t]
            args = ["add", "--section", r["section"], "--title", r["title"], "--chip", r["chip"]]
            if r["time"]:
                args += ["--time", r["time"]]
            if r["due"]:
                args += ["--due", r["due"], "--due-moved", r["due_moved"] or "none"]
            if r["due_from"]:
                args += ["--due-from", r["due_from"]]
            self.ok(*args)
        for t in ("夜の件", "日だけの件"):
            a, b = orig[t], self.by(t)
            for k in ("section", "time", "title", "note", "chip", "crit", "due", "due_moved", "due_from"):
                self.assertEqual(a[k], b[k], (t, k))
        self.assertIn("21:00|夜の件", [x[0] for x in dw.read_board_alarms(self.board)])
        # 「明日以降」へ戻すときは実施日をユーザーが決める（v1.9）。印は外れ、決めた日より前には移さない
        self.ok("move", "--item", "21:00|夜の件", "--section", "明日以降", "--due", iso(2) + " 21:00")
        r = self.by("夜の件")
        self.assertEqual((r["time"], r["due"], r["due_moved"], r["due_from"]), ("21:00", iso(2) + " 21:00", None, None))
        self.assertEqual(self.status()["due_now"], [])
        self.assertEqual(dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")[1]["due_moved"], 0)
        self.assertEqual(dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")[1]["due_moved"], 1)

    def test_readd_keeps_time_the_user_removed(self):
        """利用者が時刻を外した行を足し直しても、時刻は戻らない（status の time をそのまま写す）。

        set-time --time none は実施日の時刻も外す（v1.7。日付と印は残す）ので、「明日以降」へ戻して今日の側へ動かし直しても時刻は戻らない。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "夜の件", "due": iso(0) + " 21:00"}]})
        self.ok("move", "--item", "夜の件", "--section", "今日の予定")
        self.ok("set-time", "--item", "夜の件", "--time", "none")          # 利用者が時刻を外した
        r = self.by("夜の件")
        self.assertEqual((r["time"], r["due"], r["due_moved"]), (None, iso(0), iso(0)))
        self.ok("move", "--item", "夜の件", "--section", "明日以降", "--due", iso(2))
        self.ok("move", "--item", "夜の件", "--section", "今日の予定")
        self.assertEqual(self.by("夜の件")["time"], None)
        self.ok("remove", "--item", "|夜の件", "--confirmed")
        self.ok("add", "--section", r["section"], "--title", r["title"], "--chip", r["chip"],
                "--due", r["due"], "--due-moved", r["due_moved"])
        it = self.by("夜の件")
        self.assertEqual((it["time"], it["due"], it["due_moved"]), (None, iso(0), iso(0)))
        self.assertNotIn("21:00|夜の件", [x[0] for x in dw.read_board_alarms(self.board)])

    def test_ops_file_due_moved(self):
        self.create()
        p = os.path.join(self.dir, "ops", "a.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"op": "add", "section": "今日中", "title": "印", "due": "%s", "due_moved": "%s"}' % (iso(0), iso(0)))
        rc, out = tbe.run(["--ops", p, "--board", self.board])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.by("印")["due_moved"], iso(0))

    def test_ops_null_due_moved_is_none_on_today_side(self):
        """ops の "due_moved": null（status の値をそのまま写したもの）は、due があれば --due-moved none として渡る（印は付かない）。
        鍵は due_moved・due-moved のどちらの綴りでもよい。due が "none" のときは --due-moved を渡さない。"""
        self.create()
        p = os.path.join(self.dir, "ops", "b.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        for key in ("due_moved", "due-moved"):
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"op": "set-due", "item": "作業A", "due": iso(0), key: None}, f, ensure_ascii=False)
            rc, out = tbe.run(["--ops", p, "--board", self.board])
            self.assertEqual(rc, 0, (key, out))
            it = self.by("作業A")
            self.assertEqual((it["section"], it["due"], it["due_moved"]), ("今日中", iso(0), None))
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"op": "set-due", "item": "作業A", "due": "none", "due_moved": None}, f, ensure_ascii=False)
        rc, out = tbe.run(["--ops", p, "--board", self.board])
        self.assertEqual(rc, 0, out)                     # --due-moved を渡していれば「--due と一緒にだけ」で断られる
        self.assertEqual(self.by("作業A")["due"], None)

    def test_spec_and_add_align_due_time_on_today_side(self):
        """今日の予定・今日中の行に time と時刻のある due を一緒に書くと、due の時刻は time になる（create の spec と add・v1.7）。
        due の日付が今日より前なら、実施日を今日にし（時刻の欄があればその時刻を含める）、元の実施日を due_from に、
        印が無ければ今日を due_moved に入れる（Deck の日付の切り替えの _carry_due_today と同じ）。due_from を渡さなかったときの
        元の実施日は、due の日付と行の時刻（time。無ければ due の時刻）＝Deck v2.12 の _carry_due_today と同じ値（v1.9）。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日の予定", "title": "今日", "time": "10:00", "due": iso(0) + " 9:30", "due_moved": iso(0)},
            {"section": "今日の予定", "title": "前の日", "time": "10:00", "due": iso(-1) + " 9:30", "due_moved": iso(-1)},
            {"section": "今日中", "title": "前の日・日だけ", "due": iso(-1), "due_moved": None, "due_from": iso(-3) + " 8:00"}]})
        get = lambda t: (self.by(t)["time"], self.by(t)["due"], self.by(t)["due_moved"], self.by(t)["due_from"])
        self.assertEqual(get("今日"), ("10:00", iso(0) + " 10:00", iso(0), None))
        self.assertEqual(get("前の日"), ("10:00", iso(0) + " 10:00", iso(-1), iso(-1) + " 10:00"))   # 元の実施日の時刻は行の時刻（v1.9）
        self.assertEqual(get("前の日・日だけ"), (None, iso(0), iso(0), iso(-3) + " 8:00"))      # 元の実施日は最初の値のまま
        self.ok("add", "--section", "今日中", "--title", "add", "--time", "12:00", "--due", iso(-1) + " 9:30", "--due-moved", "none")
        self.assertEqual(get("add"), ("12:00", iso(0) + " 12:00", iso(0), iso(-1) + " 12:00"))
        self.ok("add", "--section", "今日中", "--title", "add今日", "--time", "12:30", "--due", iso(0) + " 9:30", "--due-moved", iso(0),
                "--due-from", iso(-2) + " 9:30")
        self.assertEqual(get("add今日"), ("12:30", iso(0) + " 12:30", iso(0), iso(-2) + " 9:30"))
        # Deck の引き継ぎと同じ値になる
        text = self.text()
        lines = text.splitlines(keepends=True)
        for (s, e, name) in dw._scan_board(lines)[1]:
            blk = "".join(lines[s:e + 1])
            if name in ("今日の予定", "今日中") and "data-due=" in blk:
                self.assertEqual(dw._carry_due_today(blk, TODAY), blk)                      # 既に今日なので変わらない


# ------------------------------------------------------------------ 2. move・add が Deck と同じ形・同じ位置を作る

class TestMoveShapeMatchesDeck(Base):
    ROWS = [  # (タイトル, 実施日, 時刻の欄, チップ, 重要)
        ("昼", iso(0) + " 12:30", None, "none", False),
        ("朝", iso(0), "9:00", "hold", True),             # 実施日に時刻が無く、時刻の欄が H:MM
        ("夜", iso(0) + " 18:00", "7:40", "none", False),  # v1.6 までにできた食い違い。時刻の欄が先で、実施日の時刻もそれにする（v1.7）
        ("過去", iso(-2), "18:00", "none", False),         # 前の日＝今日中、時刻の欄は data-orig-time へ
        ("日だけ", iso(0), None, "active", False),
        ("読めない", iso(0), "午後", "none", False),        # H:MM でない時刻の欄は使わない
    ]

    def make(self):
        items = [{"section": "今日の予定", "title": "時刻なしの予定"}, {"section": "今日中", "title": "作業A"}]
        for (t, _d, _tm, chip, crit) in self.ROWS:
            if t != "夜":
                items.append({"section": "明日以降", "title": t, "chip": chip, "crit": crit})
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": items})
        for (t, d, tm, _c, _k) in self.ROWS:
            if t == "夜":                                 # 時刻の欄と実施日の時刻が違う行は操作では作れない（v1.7）
                self.make_conflict(t, d, tm)
                continue
            if tm and re.match(r"^\d{1,2}:\d{2}$", tm):
                self.ok("set-time", "--item", t, "--time", tm)
            self.put_due(t, d)
        # H:MM でない時刻の欄は set-time で書けないので、板へ直接入れる
        old = '<div class="item flat" data-due="%s">\n    <div>\n      <p class="task-title">読めない</p>' % iso(0)
        new = '<div class="item" data-due="%s">\n    <div class="time">午後</div>\n    <div>\n      <p class="task-title">読めない</p>' % iso(0)
        text = self.text()
        self.assertEqual(text.count(old), 1)
        self.write(text.replace(old, new))
        return self.text()

    def test_blocks_and_order_match_deck(self):
        start = self.make()
        deck, info = dw.roll_board_text(start, TODAY, "0:00")
        self.assertEqual(info["due_moved"], len(self.ROWS))
        # SKILL.md update モード 9 の手順: 実施日が今日で時刻があれば今日の予定へ、それ以外は今日中の先頭へ（下の行から）
        due_now = self.status()["due_now"]
        plan, rest = [], []
        for r in due_now:
            when = r["time"] if r["time"] and re.match(r"^\d{1,2}:\d{2}$", r["time"]) else (r["due"].split(" ")[1] if " " in r["due"] else None)
            (plan if when and r["due"].startswith(iso(0)) else rest).append(r)
        for r in plan:
            self.ok("move", "--item", r["key"], "--section", "今日の予定")
        for r in reversed(rest):
            self.ok("move", "--item", r["key"], "--section", "今日中", "--head")
        mine = self.text()
        bd, bm = blocks(deck), blocks(mine)
        for (t, *_x) in self.ROWS:
            self.assertEqual(bm[t], bd[t], t)          # 見出しとブロックが Deck と同じ（時刻の欄・flat・未チップ・印・data-orig-time）
        moved = [t for (t, *_x) in self.ROWS]
        for sec in ("今日の予定", "今日中"):
            self.assertEqual([t for t in titles_in(mine, sec) if t in moved or t in ("時刻なしの予定", "作業A")],
                             [t for t in titles_in(deck, sec) if t in moved or t in ("時刻なしの予定", "作業A")], sec)
        self.assertEqual(titles_in(mine, "今日の予定"), ["時刻なしの予定", "夜", "朝", "昼"])
        self.assertIn('data-due="%s 7:40"' % iso(0), bm["夜"][1])     # 実施日の時刻も時刻の欄の時刻にそろう（日付は変えない）
        self.assertEqual(titles_in(mine, "今日中")[:3], ["過去", "日だけ", "読めない"])
        self.assertNotIn("data-orig-time", bm["過去"][1] + bm["読めない"][1])     # 外した時刻の欄は data-orig-time に残さない（v1.8）
        self.assertIn('data-due-from="%s 18:00"' % iso(-2), bm["過去"][1])        # 行の時刻は data-due-from に残る
        st = self.status()
        self.assertEqual(st["due_now"], [])
        self.assertEqual(st["errors"], [])
        alarms = [a[0] for a in dw.read_board_alarms(self.board)]
        self.assertEqual(sorted(a for a in alarms if a.split("|")[1] in moved), ["12:30|昼", "7:40|夜", "9:00|朝"])

    def test_shape_function_equals_deck(self):
        start = self.make()
        lines = start.splitlines(keepends=True)
        for (s, e, name) in dw._scan_board(lines)[1]:
            if name != "明日以降":
                continue
            blk = "".join(lines[s:e + 1])
            due = dw._item_due_pending(blk, TODAY)
            new_block, dest = dw._move_due_block(blk, due, TODAY, "\n")
            self.assertEqual(be._due_moved_shape(blk, due, TODAY, "\n", dest == "今日の予定"), new_block)

    def test_scheduled_row_moved_to_today_loses_time_like_deck_unscheduled(self):
        """実施日が今日で時刻のある行を今日中へ動かすと、時刻の欄は付かず（鳴らない）、set-time は要らない。"""
        self.make()
        self.ok("move", "--item", "9:00|朝", "--section", "今日中")
        blk = blocks(self.text())["朝"][1]
        self.assertNotIn('class="time"', blk)
        self.assertNotIn("data-orig-time", blk)
        self.assertIn('data-due-from="%s 9:00"' % iso(0), blk)
        self.assertEqual(sorted(re.search(r'<div class="(item[^"]*)"', blk).group(1).split()), ["crit", "flat", "item"])
        self.assertNotIn("9:00|朝", [a[0] for a in dw.read_board_alarms(self.board)])
        # 前の日の行を今日の予定へ動かしても、前の日の時刻は今日の時刻にしない（見出しの末尾へ）
        self.ok("move", "--item", "18:00|過去", "--section", "今日の予定")
        blk = blocks(self.text())["過去"][1]
        self.assertNotIn('class="time"', blk)
        self.assertEqual(titles_in(self.text(), "今日の予定")[-1], "過去")
        self.assertNotIn("18:00|過去", [a[0] for a in dw.read_board_alarms(self.board)])

    def test_not_due_rows_are_moved_as_before(self):
        """実施日の無い行は、移すときに形を変えない（従来どおり）。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "明日以降", "title": "日付なし", "time": "8:00"}]})
        before = blocks(self.text())
        self.ok("move", "--item", "8:00|日付なし", "--section", "今日中")
        self.assertEqual(blocks(self.text())["日付なし"][1], before["日付なし"][1])

    def test_marked_and_future_rows_get_the_same_shape(self):
        """印のある行・実施日の前の行も、同じ形の規則で動かす（v1.7・Deck v2.11）。

        印のある行: 実施日が今日で時刻があれば今日の予定で時刻の欄が付き、前の日の時刻は鳴らさない。印は変えない（増やさない）。
        先の日の行: 今日の行として扱い、実施日を今日にして時刻は付けず（今日の予定へ動かしても時刻の無い行）、元の予定を data-due-from に残し、
        「未」と印を付ける（v1.9・Deck v2.13）。「明日以降」へ戻すときは実施日を決め直し、印が外れるので、その日に Deck が移す（下の終わり）。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "戻した", "due": iso(0) + " 22:05", "due_moved": iso(0)},
            {"section": "明日以降", "title": "前に戻した", "due": iso(-2) + " 22:05", "due_moved": iso(-2)},
            {"section": "明日以降", "title": "先", "due": iso(2) + " 9:00"}]})
        self.ok("move", "--item", "戻した", "--section", "今日の予定")
        self.ok("move", "--item", "前に戻した", "--section", "今日の予定")
        self.ok("move", "--item", "先", "--section", "今日の予定")
        b = blocks(self.text())
        self.assertIn('<div class="time">22:05</div>', b["戻した"][1])
        self.assertEqual(b["戻した"][1].count("data-due-moved="), 1)
        self.assertIn('data-due="%s 22:05"' % iso(0), b["戻した"][1])
        self.assertIn('data-due-from="%s 22:05"' % iso(0), b["戻した"][1])
        self.assertIn('data-due="%s"' % iso(0), b["前に戻した"][1])               # 実施日を今日にし、時刻は付けない
        self.assertIn('data-due-from="%s 22:05"' % iso(-2), b["前に戻した"][1])
        self.assertIn('data-due="%s"' % iso(0), b["先"][1])
        self.assertIn('data-due-from="%s 9:00"' % iso(2), b["先"][1])
        self.assertIn('class="item flat"', b["先"][1])
        self.assertIn('data-due-moved="%s"' % iso(0), b["戻した"][1])
        self.assertIn('<span class="chip pending">未</span>', b["戻した"][1])
        self.assertNotIn('class="time"', b["前に戻した"][1])
        self.assertIn('data-due-moved="%s"' % iso(-2), b["前に戻した"][1])
        self.assertIn('<span class="chip pending">未</span>', b["前に戻した"][1])
        self.assertNotIn('class="time"', b["先"][1])
        self.assertIn('data-due-moved="%s"' % iso(0), b["先"][1])
        self.assertEqual(titles_in(self.text(), "今日の予定")[-1], "先")   # 時刻の無い行は今日の予定の末尾（move の既定）
        self.assertNotIn("9:00|先", [a[0] for a in dw.read_board_alarms(self.board)])
        self.assertIn('<span class="chip pending">未</span>', b["先"][1])
        alarms = [a[0] for a in dw.read_board_alarms(self.board)]
        self.assertEqual(sorted(a for a in alarms if a.split("|")[1] in ("戻した", "前に戻した", "先")), ["22:05|戻した"])
        self.assertEqual(be.progress_of(self.text())["total"], 4)        # 作業A と、動かした3行（「未」が付くので進捗に入る）
        # Deck の D&D（apply_board_move）も同じ形にする（先の日の行も）。比べるのは、動かす前の同じ板から
        before = self.text().replace(b["先"][1], "", 1)
        self.write(before)
        self.ok("add", "--section", "明日以降", "--title", "先", "--due", iso(2) + " 9:00")
        back = self.text()
        self.ok("move", "--item", "先", "--section", "今日の予定")
        deck, code, msg = dw.apply_board_move(back, dw._item_key(blocks(back)["先"][1]), "今日の予定")
        self.assertEqual(code, 200, msg)
        self.assertEqual(blocks(deck)["先"][1], blocks(self.text())["先"][1])
        # 先の日の行を「明日以降」へ戻すときは実施日を決め直し（v1.9）、その日に Deck が移す（印が外れるため）
        self.ok("move", "--item", "先", "--section", "明日以降", "--due", iso(2) + " 9:00")
        self.assertEqual(dw.roll_board_text(self.text(), TODAY + timedelta(days=1), "0:00")[1]["due_moved"], 0)
        self.assertEqual(dw.roll_board_text(self.text(), TODAY + timedelta(days=2), "0:00")[1]["due_moved"], 1)

    def test_plan_time_order_without_before(self):
        self.create()
        self.ok("move", "--item", "9:00|朝会", "--section", "今日中")
        self.ok("move", "--item", "9:00|朝会", "--section", "今日の予定")        # --before 無しでも 16:00 の前へ
        self.assertEqual(titles_in(self.text(), "今日の予定"), ["朝会", "判断する"])
        self.ok("add", "--section", "今日の予定", "--title", "昼", "--time", "12:00")
        self.ok("add", "--section", "今日の予定", "--title", "夕方", "--time", "17:00")
        self.ok("add", "--section", "今日の予定", "--title", "同じ時刻", "--time", "16:00")   # 同じ時刻の後ろへ（Deck と同じ「より後」）
        self.ok("add", "--section", "今日の予定", "--title", "時刻なし")
        self.assertEqual(titles_in(self.text(), "今日の予定"), ["朝会", "昼", "判断する", "同じ時刻", "夕方", "時刻なし"])
        self.ok("add", "--section", "今日の予定", "--title", "先頭", "--time", "23:00", "--head")
        self.ok("add", "--section", "今日の予定", "--title", "直後", "--time", "1:00", "--after", "16:00|判断する")
        self.ok("move", "--item", "12:00|昼", "--section", "今日の予定", "--before", "9:00|朝会")
        self.assertEqual(titles_in(self.text(), "今日の予定"),
                         ["先頭", "昼", "朝会", "判断する", "直後", "同じ時刻", "夕方", "時刻なし"])


class TestDueToday(Base):
    """今日の側へ移した行の実施日を今日にし、元の実施日を data-due-from に残す（board_edit.py v1.7・Deck v2.11・2026-11-05 ユーザー決定）。

    移すのは日付の切り替え・move・D&D（_due_moved_shape）、引き継ぐのは日付の切り替え（_carry_due_today）。一度移した印は
    「Deck が移し直さない」の意味だけで（v1.9・Deck v2.13 からは「明日以降」へ戻すときに外れる）、日付の切り替えが移す行を決める _item_due_pending は印を見る（二重に移さない・移し損ねない）。"""

    def roll(self, text, days):
        return dw.roll_board_text(text, TODAY + timedelta(days=days), "0:00")

    def attrs(self, text, title):
        sec, blk = blocks(text)[title]
        head = blk.split(">", 1)[0]
        get = lambda n: (re.search(r'\s%s="([^"]*)"' % n, head) or [None, None])[1]
        return sec, get("data-due"), get("data-due-from"), get("data-due-moved")

    def test_rollover_moves_once_and_keeps_the_original_plan(self):
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "来る", "due": iso(1) + " 22:05"},
            {"section": "明日以降", "title": "戻す", "due": iso(1) + " 9:00"}]})
        d1, info = self.roll(self.text(), 1)
        self.assertEqual(info["due_moved"], 2)
        self.assertEqual(self.attrs(d1, "来る"), ("今日の予定", iso(1) + " 22:05", iso(1) + " 22:05", iso(1)))
        self.assertEqual(self.attrs(d1, "戻す"), ("今日の予定", iso(1) + " 9:00", iso(1) + " 9:00", iso(1)))
        # due を送らない旧経路（v2.12 と同時の board.js の D&D）で戻す。この経路は行の形を変えないので印が残る。
        # v2.13 と同時の board.js は実施日を聞いて due を送り、印が外れる（test_due.py の TestMoveBackToLater・test_marked_and_future_rows_get_the_same_shape）
        d1, code, msg = dw.apply_board_move(d1, "9:00|戻す", "明日以降", today=TODAY + timedelta(days=1))
        self.assertEqual(code, 200, msg)
        d2, info = self.roll(d1, 2)
        self.assertEqual(info["due_moved"], 0)                                    # 旧経路で戻した行は印が残るので移し直さない
        self.assertEqual(self.attrs(d2, "戻す"), ("明日以降", iso(1) + " 9:00", iso(1) + " 9:00", iso(1)))
        # 今日の側に残った行は、引き継ぐ日にも実施日を今日にする（時刻の欄は外すので日付だけ）。元の実施日と印は最初の値のまま
        self.assertEqual(self.attrs(d2, "来る"), ("今日中", iso(2), iso(1) + " 22:05", iso(1)))
        d3, info = self.roll(d2, 3)
        self.assertEqual(info["due_moved"], 0)
        self.assertEqual(self.attrs(d3, "来る"), ("今日中", iso(3), iso(1) + " 22:05", iso(1)))
        self.assertEqual(self.attrs(d3, "戻す"), ("明日以降", iso(1) + " 9:00", iso(1) + " 9:00", iso(1)))
        lines = d3.splitlines(keepends=True)
        for (s, e, name) in dw._scan_board(lines)[1]:
            if name == "明日以降":
                self.assertIsNone(dw._item_due_pending("".join(lines[s:e + 1]), TODAY + timedelta(days=3)))

    def test_v210_rows_left_on_today_side_are_fixed_on_rollover(self):
        """v2.10 までに移して、実施日が前の日のまま今日の側に残った行（印あり・元の実施日なし）は、次の日付の切り替えで直る。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "古い", "due": iso(0), "due_moved": iso(0)},
            {"section": "今日中", "title": "古い時刻つき", "time": "8:00", "due": iso(0) + " 8:00", "due_moved": iso(0)},
            {"section": "今日中", "title": "印なし", "due": iso(0), "due_moved": None}]})
        self.put_legacy_due("古い", iso(-2) + " 22:05")
        self.put_legacy_due("古い時刻つき", iso(-2) + " 8:00")
        self.put_legacy_due("印なし", iso(-2))
        self.write(self.text().replace('data-due-moved="%s"' % iso(0), 'data-due-moved="%s"' % iso(-2)))
        d1, _info = self.roll(self.text(), 1)
        self.assertEqual(self.attrs(d1, "古い"), ("今日中", iso(1), iso(-2) + " 22:05", iso(-2)))
        # 今日中の行は時刻の欄を残して引き継ぐので、その時刻を含める（行の時刻は1つ）
        self.assertEqual(self.attrs(d1, "古い時刻つき"), ("今日中", iso(1) + " 8:00", iso(-2) + " 8:00", iso(-2)))
        # 印の無い行には付ける（今日の側の行の印。旧版の経路で「明日以降」へ戻したときに、また移さないため。v1.9・v2.13 で戻すときは外れる）
        self.assertEqual(self.attrs(d1, "印なし"), ("今日中", iso(1), iso(-2), iso(1)))

    def test_set_time_on_moved_row_aligns_todays_due(self):
        """前の日の行を今日の側へ移すと実施日は今日になるので、set-time は他の行と同じく実施日の時刻をそろえるだけになる。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "前の日", "due": iso(-1) + " 22:05", "due_moved": iso(-1)}]})
        self.ok("move", "--item", "前の日", "--section", "今日中")
        self.assertEqual(self.attrs(self.text(), "前の日"), ("今日中", iso(0), iso(-1) + " 22:05", iso(-1)))
        self.ok("set-time", "--item", "前の日", "--time", "9:00")
        self.assertEqual(self.attrs(self.text(), "前の日"), ("今日中", iso(0) + " 9:00", iso(-1) + " 22:05", iso(-1)))
        self.assertEqual(self.by("前の日")["due_from"], iso(-1) + " 22:05")

    def test_time_none_without_field_keeps_due_time(self):
        """時刻の欄の無い行に --time none を当てても、実施日の時刻を消さない（何もしない）。"""
        self.create()
        self.ok("add", "--section", "明日以降", "--title", "欄なし", "--due", iso(3) + " 9:30")
        self.ok("set-time", "--item", "欄なし", "--time", "none")
        self.assertEqual((self.by("欄なし")["time"], self.by("欄なし")["due"]), (None, iso(3) + " 9:30"))

    def test_out_of_range_time_field_is_not_used(self):
        """時刻の欄が範囲外（25:00）なら使わず、実施日の時刻を使う（Deck・board_edit・board.js の _valid_hm）。K12 が知らせる。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "範囲外", "due": iso(0) + " 22:05", "due_moved": iso(-1)}]})
        self.write(self.text().replace('<p class="task-title">範囲外</p>', '<div class="time">25:00</div><p class="task-title">範囲外</p>', 1))
        self.assertIn("範囲外", [w["message"] for w in self.status()["warnings"] if w["code"] == "K12"][0])
        self.assertEqual(self.k14(), [])
        start = self.text()
        self.ok("move", "--item", "25:00|範囲外", "--section", "今日の予定")
        deck, code, msg = dw.apply_board_move(start, "25:00|範囲外", "今日の予定")
        self.assertEqual(code, 200, msg)
        self.assertEqual(blocks(deck)["範囲外"], blocks(self.text())["範囲外"])
        self.assertEqual((self.by("範囲外")["time"], self.by("範囲外")["due"]), ("22:05", iso(0) + " 22:05"))
        self.assertEqual(dw._valid_hm("25:00"), None)
        self.assertEqual(dw._valid_hm("23:60"), None)
        self.assertEqual(dw._valid_hm("09:05"), "9:05")

    def k14(self):
        return [w["message"] for w in self.status()["warnings"] if w["code"] == "K14"]

    def test_due_from_arguments(self):
        """--due-from は --due と一緒にだけ受け、読めない値は書かない。status に due_from が出て、set-due で省くと外れる。"""
        self.create()
        err = self.ng("add", "--section", "明日以降", "--title", "x", "--due-from", iso(-1))
        self.assertIn("--due-from（元の実施日）は --due と一緒にだけ使えます", err)
        err = self.ng("add", "--section", "明日以降", "--title", "x", "--due", iso(2), "--due-from", "あした")
        self.assertIn("元の実施日（--due-from・spec の due_from）「あした」は使えません", err)
        self.ok("add", "--section", "明日以降", "--title", "x", "--due", iso(2), "--due-moved", iso(-1), "--due-from", iso(-1) + " 9:00")
        self.assertEqual((self.by("x")["due"], self.by("x")["due_moved"], self.by("x")["due_from"]), (iso(2), iso(-1), iso(-1) + " 9:00"))
        self.ok("set-due", "--item", "x", "--due", iso(3), "--due-moved", iso(-1), "--due-from", iso(-1) + " 9:00")
        self.assertEqual(self.by("x")["due_from"], iso(-1) + " 9:00")
        self.ok("set-due", "--item", "x", "--due", iso(4))
        self.assertEqual((self.by("x")["due_moved"], self.by("x")["due_from"]), (None, None))
        p = self.write_spec({"sections": ["明日以降"], "items": [{"section": "明日以降", "title": "y", "due_from": iso(-1)}]})
        rc, out = tbe.run(["create", "--board", self.board, "--spec", p, "--confirmed"])
        self.assertEqual(rc, 1, out)
        self.assertIn("due_from（元の実施日）は due と一緒にだけ書けます", out["error"])

    def test_keeps_existing_due_from_and_puts_time_into_future_due(self):
        """元の実施日が既にある行は変えない（move・D&D とも）。先の日の、日付だけの実施日の行を前もって動かすと、今日の行になり、
        外した時刻の欄の時刻を元の予定（data-due-from）に入れる（v1.9・Deck v2.13）。create が「明日以降」から置く今日の行にも元の実施日が残る。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "二度目", "due": iso(-1), "due_moved": iso(-1), "due_from": iso(-3) + " 8:00"},
            {"section": "明日以降", "title": "先", "due": iso(3)},
            {"section": "明日以降", "title": "当日", "due": iso(0) + " 23:50"}]})
        self.assertEqual(self.attrs(self.text(), "当日"), ("今日の予定", iso(0) + " 23:50", iso(0) + " 23:50", iso(0)))
        self.ok("set-time", "--item", "先", "--time", "10:00")
        self.put_legacy_due("先", iso(3))                        # v1.6 までの set-time でできた、日付だけの実施日と時刻の欄の行
        start = self.text()
        self.ok("move", "--item", "二度目", "--section", "今日中")
        self.ok("move", "--item", "10:00|先", "--section", "今日中")
        self.assertEqual(self.attrs(self.text(), "二度目"), ("今日中", iso(0), iso(-3) + " 8:00", iso(-1)))
        self.assertEqual(self.attrs(self.text(), "先"), ("今日中", iso(0), iso(3) + " 10:00", iso(0)))
        deck = start
        for k in ("|二度目", "10:00|先"):
            deck, code, msg = dw.apply_board_move(deck, k, "今日中")
            self.assertEqual(code, 200, msg)
        for t in ("二度目", "先"):
            self.assertEqual(self.attrs(deck, t), self.attrs(self.text(), t), t)

    def test_existing_due_from_survives_move_and_dnd(self):
        """印と data-due-from を持つ「明日以降」の行を、move と D&D（apply_board_move）で今日の側へ動かしても、元の値が残る。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "明日以降", "title": "元あり", "due": iso(0) + " 21:00", "due_moved": iso(-1), "due_from": iso(-4) + " 7:00"}]})
        start = self.text()
        self.ok("move", "--item", "元あり", "--section", "今日の予定")
        self.assertEqual(self.attrs(self.text(), "元あり"), ("今日の予定", iso(0) + " 21:00", iso(-4) + " 7:00", iso(-1)))
        deck, code, msg = dw.apply_board_move(start, "|元あり", "今日の予定")
        self.assertEqual(code, 200, msg)
        self.assertEqual(self.attrs(deck, "元あり"), ("今日の予定", iso(0) + " 21:00", iso(-4) + " 7:00", iso(-1)))
        self.assertEqual(blocks(deck)["元あり"][1].count("data-due-from="), 1)

    def test_roll_due_today_matches_deck_carry(self):
        """足し直し（add・create の roll_due_today）と Deck の引き継ぎ（_carry_due_today）は、同じ行から同じ実施日・元の実施日を作る
        （時刻の欄と実施日の時刻が違う行・時刻の欄が H:MM でない行・時刻の欄の無い行を含む＝v1.9・Deck v2.12）。"""
        cases = [("10:00", iso(-1) + " 9:30"), ("10:00", iso(-1)), (None, iso(-1) + " 9:30"), (None, iso(-2)),
                 ("午後", iso(-1) + " 9:30"), ("9:30", iso(-1) + " 9:30"), ("10:00", iso(0) + " 9:30"), ("10:00", iso(1) + " 9:30")]
        for tm, due in cases:
            blk = ('  <div class="item" data-due="%s">\n' % due
                   + ('    <div class="time">%s</div>\n' % tm if tm else "")
                   + '    <div>\n      <p class="task-title">t</p>\n    </div>\n  </div>\n')
            head = dw._carry_due_today(blk, TODAY).split(">", 1)[0]
            get = lambda n: (re.search(r'\s%s="([^"]*)"' % n, head) or [None, None])[1]
            mine = be.roll_due_today(due, be._valid_hm(tm or ""), None, None, TODAY)
            self.assertEqual((mine[0], mine[2]), (get("data-due"), get("data-due-from")), (tm, due))

    def test_set_due_with_past_date_on_today_side(self):
        """今日の側の行に過去の実施日で set-due を当てると、実施日は今日になり、data-due-from に元の実施日が入る（印が無ければ今日）。
        行の時刻は、渡した実施日に時刻があれば時刻の欄もその時刻にそろえる（今日より後の set-due と同じ）ので、その時刻。
        日付だけを渡したら、行の時刻は時刻の欄のまま、元の実施日はその日付と時刻の欄の時刻（Deck v2.12 の _carry_due_today と同じ・v1.9）。"""
        self.create({"sections": ["今日の予定", "今日中", "明日以降"], "items": [
            {"section": "今日中", "title": "作業A"},
            {"section": "今日中", "title": "足し直し", "time": "10:00"},
            {"section": "今日中", "title": "日だけ", "time": "11:00"},
            {"section": "今日中", "title": "欄なし"}]})
        self.ok("set-due", "--item", "10:00|足し直し", "--due", iso(-2) + " 9:30", "--due-moved", "none")
        self.assertEqual(self.attrs(self.text(), "足し直し"), ("今日中", iso(0) + " 9:30", iso(-2) + " 9:30", iso(0)))
        self.assertEqual(self.by("足し直し")["time"], "9:30")
        self.ok("set-due", "--item", "11:00|日だけ", "--due", iso(-2), "--due-moved", "none")
        self.assertEqual(self.attrs(self.text(), "日だけ"), ("今日中", iso(0) + " 11:00", iso(-2) + " 11:00", iso(0)))
        self.assertEqual(self.by("日だけ")["time"], "11:00")
        self.ok("set-due", "--item", "欄なし", "--due", iso(-2) + " 8:15", "--due-moved", "none")
        self.assertEqual(self.attrs(self.text(), "欄なし"), ("今日中", iso(0), iso(-2) + " 8:15", iso(0)))   # 前の日の時刻は今日の時刻にしない
        self.assertEqual(self.by("欄なし")["time"], None)


# ------------------------------------------------------------------ 3. create の消える行の確かめ

class TestCreateMissingCounts(Base):
    def test_duplicates_are_counted(self):
        self.create()
        self.ok("add", "--section", "今日中", "--title", "作業B")       # 同じタイトル・同じ見出しの2行目
        self.ok("add", "--section", "明日以降", "--title", "来週の件")
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(tbe.SPEC)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(sorted((r["section"], r["title"]) for r in out["missing"]),
                         [("今日中", "作業B"), ("明日以降", "来週の件")])

    def test_later_rows_compare_due_date(self):
        self.create()
        self.ok("set-due", "--item", "来週の件", "--due", iso(7))
        for spec_due in (None, iso(8)):
            item = {"section": "明日以降", "title": "来週の件"}
            if spec_due:
                item["due"] = spec_due
            spec = {"sections": tbe.SPEC["sections"], "items": [i for i in tbe.SPEC["items"] if i["title"] != "来週の件"] + [item]}
            rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
            self.assertEqual(rc, 1, (spec_due, out))
            self.assertEqual([(r["title"], r["due"]) for r in out["missing"]], [("来週の件", iso(7))])
        spec = {"sections": tbe.SPEC["sections"], "items": [i for i in tbe.SPEC["items"] if i["title"] != "来週の件"]
                + [{"section": "明日以降", "title": "来週の件", "due": iso(7)}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])

    def test_non_hm_time_on_due_row_is_not_compared(self):
        """H:MM でない時刻の欄は Deck が使わないので、実施日だけを写した spec の行と同じ行とみなす（消える行に出ない）。
        ただしその時刻は作り直した板から消えるので dropped_times に出し、--confirmed が無ければ書かない。
        時刻を確かめて実施日に含めれば（"<due> H:MM"）時刻は消えない。"""
        self.create()
        self.ok("set-due", "--item", "来週の件", "--due", iso(3))
        self.write(self.text().replace('<div class="item flat" data-due="%s">' % iso(3),
                                       '<div class="item" data-due="%s">\n    <div class="time">午後</div>' % iso(3)))
        self.assertEqual(self.by("来週の件")["time"], "午後")
        spec = {"sections": tbe.SPEC["sections"], "items": [i for i in tbe.SPEC["items"] if i["title"] != "来週の件"]
                + [{"section": "明日以降", "title": "来週の件", "due": iso(3)}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["section"], r["title"], r["time"], r["new_time"]) for r in out["dropped_times"]],
                         [("明日以降", "来週の件", "午後", None)])
        spec_hm = json.loads(json.dumps(spec))
        spec_hm["items"][-1]["due"] = iso(3) + " 15:00"
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec_hm)])
        self.assertEqual(rc, 1, out)                                                # 実施日に含めた時刻も、元の「午後」からの変更
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", "15:00")])
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec_hm), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", "15:00")])

    def put_afternoon(self, title):
        """「明日以降」の行の先頭に、H:MM でない時刻の欄（「午後」）を入れる。"""
        t = self.text()
        i = t.index(title)
        j = t.rfind('<div class="item', 0, i)
        k = t.index(">", j) + 1
        self.write(t[:k] + '\n    <div class="time">午後</div>' + t[k:])
        self.assertEqual(self.by(title)["time"], "午後")

    def test_non_hm_time_with_timed_due_is_listed(self):
        """「明日以降」の行で実施日に時刻があっても、時刻の欄が H:MM でなければ dropped_times に出す（その文字は板に表示されていて、
        作り直すと消える）。new_time は実施日の時刻（Deck が今日の側へ移すときに使う時刻）。"""
        self.create()
        self.ok("set-due", "--item", "来週の件", "--due", iso(3) + " 9:30")
        self.put_afternoon("来週の件")
        spec = {"sections": tbe.SPEC["sections"], "items": [i for i in tbe.SPEC["items"] if i["title"] != "来週の件"]
                + [{"section": "明日以降", "title": "来週の件", "due": iso(3) + " 9:30"}]}
        before = self.read()
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["section"], r["time"], r["new_time"]) for r in out["dropped_times"]], [("明日以降", "午後", "9:30")])
        self.assertEqual(self.read(), before)
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", "9:30")])

    def test_non_hm_time_on_later_row_without_due_uses_time(self):
        """実施日の無い「明日以降」の行で時刻の欄が「午後」のとき、spec の time を 15:00 にすると new_time は "15:00"
        （実施日の無い「明日以降」の行の時刻は時刻の欄に書く）。"""
        self.create()
        self.assertIsNone(self.by("来週の件")["due"])
        self.put_afternoon("来週の件")
        spec = {"sections": tbe.SPEC["sections"], "items": [i for i in tbe.SPEC["items"] if i["title"] != "来週の件"]
                + [{"section": "明日以降", "title": "来週の件", "time": "15:00"}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["section"], r["time"], r["new_time"]) for r in out["dropped_times"]], [("明日以降", "午後", "15:00")])

    def test_non_hm_time_with_other_due_date_is_missing(self):
        """「午後」の行の実施日が D1 で、spec に同じタイトルの行が実施日 D2 でしか無ければ、その行は消える行に出る
        （時刻を問わない組でも実施日の日付は比べる）。dropped_times には出ない（組になっていないため）。"""
        self.create()
        self.ok("set-due", "--item", "来週の件", "--due", iso(3))
        self.put_afternoon("来週の件")
        spec = {"sections": tbe.SPEC["sections"], "items": [i for i in tbe.SPEC["items"] if i["title"] != "来週の件"]
                + [{"section": "明日以降", "title": "来週の件", "due": iso(4)}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual([(r["title"], r["time"], r["due"]) for r in out["missing"]], [("来週の件", "午後", iso(3))])
        self.assertEqual(out["dropped_times"], [])


class TestLaterTimeField(Base):
    """「明日以降」の行で、時刻の欄（H:MM）が実施日の時刻と違う形（v1.5）と、set-due・set-time が時刻をそろえること（v1.7）。

    create は spec が「明日以降」の行で time と due を一緒に受けないので、作り直すと時刻の欄の時刻か実施日の時刻のどちらかが消える。
    確かめずに消さないよう dropped_times に出す（同じ時刻なら出さない）。v1.7 の set-time・set-due・add・create はこの形を作らない（時刻の欄と実施日の時刻を
    同じ値にする）ので、食い違う行は v1.6 までにできた行として make_conflict で作る。"""
    D = iso(3)

    def spec_with(self, item):
        return {"sections": tbe.SPEC["sections"], "items": list(tbe.SPEC["items"]) + [item]}

    def test_create_lists_time_field_differing_from_due_time(self):
        self.create()
        self.make_conflict("食い違い", self.D + " 9:30", "10:00")
        spec = self.spec_with({"section": "明日以降", "title": "食い違い", "due": self.D + " 9:30"})
        before = self.read()
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["section"], r["title"], r["time"], r["new_time"], r["due"]) for r in out["dropped_times"]],
                         [("明日以降", "食い違い", "10:00", "9:30", self.D + " 9:30")])
        self.assertIn("実施日の時刻と違う", out["error"])
        self.assertIn("元の時刻と実施日の時刻のどちらにするか", out["error"])
        self.assertUnchanged(before)
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("10:00", "9:30")])
        it = self.by("食い違い")
        self.assertEqual((it["time"], it["due"]), (None, self.D + " 9:30"))

    def test_create_pairs_with_time_field_time_and_lists_due_time(self):
        """時刻の欄の時刻を選んで due に含めても、同じ行とみなす（消える行に出ない）。実施日の時刻（9:30）が消えるので、やはり確かめる。"""
        self.create()
        self.make_conflict("食い違い", self.D + " 9:30", "10:00")
        spec = self.spec_with({"section": "明日以降", "title": "食い違い", "due": self.D + " 10:00"})
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["time"], r["new_time"], r["due"]) for r in out["dropped_times"]], [("10:00", "10:00", self.D + " 9:30")])
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])
        self.assertEqual(self.by("食い違い")["due"], self.D + " 10:00")
        # どちらでもない時刻・違う日付は、組にしない（消える行に出る）
        self.create(tbe.SPEC, "--confirmed")
        self.make_conflict("食い違い", self.D + " 9:30", "10:00")
        for due in (self.D + " 11:00", iso(4) + " 10:00"):
            rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(
                self.spec_with({"section": "明日以降", "title": "食い違い", "due": due}))])
            self.assertEqual(rc, 1, out)
            self.assertEqual([r["title"] for r in out["missing"]], ["食い違い"], due)
            self.assertEqual(out["dropped_times"], [], due)

    def test_create_pairs_with_date_only_due_and_drops_both_times(self):
        """ユーザーが「どちらの時刻も消す」を選び、spec の due を日付だけにしても同じ行とみなす（消える行に出ない）。new_time は None。"""
        self.create()
        self.make_conflict("食い違い", self.D + " 9:30", "10:00")
        spec = self.spec_with({"section": "明日以降", "title": "食い違い", "due": self.D})
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertNotIn("spec に入っていないため", out["error"])
        self.assertEqual([(r["time"], r["new_time"], r["due"]) for r in out["dropped_times"]], [("10:00", None, self.D + " 9:30")])
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec), "--confirmed"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["removed"], [])
        self.assertEqual(len([i for i in self.items() if i["title"] == "食い違い"]), 1)
        self.assertEqual((self.by("食い違い")["time"], self.by("食い違い")["due"]), (None, self.D))

    def test_time_field_pair_comes_before_any_time_rows(self):
        """同じタイトル・同じ実施日の日付の「午後」の行（ANY_TIME）が先に並んでいても、時刻の欄 10:00 の食い違う行が spec の 10:00 の行を取る
        （「午後」の行は残りの 15:00 の行と組になる）。"""
        self.create()
        self.make_conflict("同名", self.D + " 9:30", "8:00")
        self.write(self.text().replace('<div class="time">8:00</div>', '<div class="time">午後</div>', 1))
        self.make_conflict("同名", self.D + " 9:30", "10:00")
        self.assertEqual([i["time"] for i in self.items() if i["title"] == "同名"], ["午後", "10:00"])
        spec = {"sections": tbe.SPEC["sections"], "items": list(tbe.SPEC["items"]) + [
            {"section": "明日以降", "title": "同名", "due": self.D + " 10:00"},
            {"section": "明日以降", "title": "同名", "due": self.D + " 15:00"}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", "15:00"), ("10:00", "10:00")])

    def test_time_field_time_comes_before_date_only(self):
        """食い違う行が2つ（時刻の欄 7:40・9:00、実施日はどちらも D 22:05）で、spec が日付だけと 7:40 なら、
        時刻の欄の時刻で組にする段が先に走り、7:40 の行が 7:40 の spec の行を取る（9:00 の行は日付だけの行と組になる）。"""
        self.create()
        self.make_conflict("同名", self.D + " 22:05", "7:40")
        self.make_conflict("同名", self.D + " 22:05", "9:00")
        spec = {"sections": tbe.SPEC["sections"], "items": list(tbe.SPEC["items"]) + [
            {"section": "明日以降", "title": "同名", "due": self.D},
            {"section": "明日以降", "title": "同名", "due": self.D + " 7:40"}]}
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("7:40", "7:40"), ("9:00", None)])

    def test_k12_and_restore_guidance(self):
        """K12 と restore の足し直しの案内が、set-time・set-due が時刻をそろえる形（v1.7）の手順を言い、印のある行の手順を足さない。"""
        self.create()
        self.ok("add", "--section", "明日以降", "--title", "午後の件", "--due", self.D + " 9:30")
        self.write(self.text().replace('<p class="task-title">午後の件</p>', '<div class="time">午後</div><p class="task-title">午後の件</p>', 1))
        out = self.ok("add", "--section", "今日中", "--title", "x")
        k12 = [w["message"] for w in out["warnings"] if w["code"] == "K12"][0]
        self.assertIn("実施日のある行では、set-time は実施日の時刻も同じ値にし、--time none なら実施日の時刻も外します（日付と一度移した印は変えない・v1.7）。", k12)
        for old in ("set-time は実施日の時刻と違う時刻を書かない", "--due-moved で印を残す行は", "時刻が無くなる"):
            self.assertNotIn(old, k12)
        text = be.restore_readd_text("x")
        self.assertIn("time は due より先に当てる〔set-time は実施日の時刻も同じ値にし〈--time none なら外す〉、set-due は時刻の欄を実施日の時刻にそろえるので、後に当てた due の時刻が残る＝v1.7〕。", text)
        for old in ("「明日以降」の行では due を time より先に当てる", "set-time --time none で外してから set-due を当て", "時刻が無くなる", "時刻は due に残る"):
            self.assertNotIn(old, text)
        with open(os.path.join(tbe.ROOT, "skill", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        self.assertIn("`time` は `due` より先に当てる〔`set-time` は実施日の時刻も同じ値にし〈`--time none` なら外す〉、", skill)
        self.assertNotIn("「明日以降」の行では `due` を `time` より先に当てる", skill)
        # K12 の案内どおり set-time で直すと、実施日の時刻もその値になる
        self.ok("set-time", "--item", "午後|午後の件", "--time", "10:00")
        self.assertEqual((self.by("午後の件")["time"], self.by("午後の件")["due"]), ("10:00", self.D + " 10:00"))

    def test_same_time_is_not_listed(self):
        """時刻の欄と実施日の時刻が同じなら確かめない（書く）。作り直すと時刻の欄は無くなるが、同じ時刻が実施日に残り、
        今日の側へ動かすときはそれが使われる（一度移した印の有無によらない＝v1.7。v1.6 までは、印のある行を move・D&D で
        今日の側へ動かすと時刻の欄が使われたので、作り直した後は時刻が無くなった）。"""
        self.create()
        self.ok("add", "--section", "明日以降", "--title", "同じ", "--time", "9:30")
        self.ok("set-due", "--item", "同じ", "--due", self.D + " 9:30")          # 同じ時刻なら set-due は書く
        self.assertEqual((self.by("同じ")["time"], self.by("同じ")["due"]), ("9:30", self.D + " 9:30"))
        spec = self.spec_with({"section": "明日以降", "title": "同じ", "due": self.D + " 9:30"})
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 0, out)
        self.assertEqual((out["removed"], out["dropped_times"]), ([], []))

    def test_non_hm_time_with_timed_due_pairs_with_other_time(self):
        """時刻の欄が「午後」で実施日に時刻（9:30）がある行は、ユーザーに確かめた別の H:MM を due に含めても同じ行とみなす。"""
        self.create()
        self.make_conflict("午後の件", self.D + " 9:30", "10:00")
        self.write(self.text().replace('<div class="time">10:00</div>', '<div class="time">午後</div>', 1))
        self.assertEqual(self.by("午後の件")["time"], "午後")
        spec = self.spec_with({"section": "明日以降", "title": "午後の件", "due": self.D + " 15:00"})
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(spec)])
        self.assertEqual(rc, 1, out)
        self.assertEqual(out["missing"], [])
        self.assertEqual([(r["time"], r["new_time"]) for r in out["dropped_times"]], [("午後", "15:00")])



    def test_guidance(self):
        """足し直し・create の案内と SKILL.md が、時刻の欄と実施日の時刻が違う行の扱いを言う（v1.5・v1.7）。"""
        fields = be.readd_fields("x")
        self.assertIn("due に時刻があり、time がそれと違う行は（H:MM でも）、time が消えるので、due の時刻と time をユーザーに見せてどちらの時刻にするかを確かめ", fields)
        self.assertIn("同じ時刻なら確かめない", fields)
        self.assertIn("今日の予定・今日中へ足す行は time と due を写す（due に時刻があれば、add が due の時刻を time と同じ値にする＝行の時刻は1つ・v1.7。", fields)
        self.assertNotIn("set-time --item <項目> --time <写した due の時刻>", fields)
        self.assertNotIn("Deck も実施日の時刻を先に使い", fields)
        self.assertIn("「明日以降」の行で実施日の時刻と違うため", be.DROPPED_TIMES_HEAD)
        self.assertIn("作り直した板に残るのは実施日の時刻だけ", be.DROPPED_TIMES_RULE)
        with open(os.path.join(tbe.ROOT, "skill", "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        for s in ("**`version` が 1.10 より前なら書かずに",
                  "行の時刻は1つにする（`version` 1.7 から）。実施日のある行で `set-time` を当てると実施日の時刻も同じ値になり",
                  "「明日以降」の行で時刻の欄が実施日の時刻と違う行（`H:MM` でも。`version` 1.5 から）",
                  "`title`・`due`〔元の行の実施日。`version` 1.5 から〕",
                  "時刻の欄と実施日の時刻が同じ行は出ない（作り直した板に時刻の欄は無くなるが、同じ時刻が実施日に残り、今日の側へ動かすときはそれが使われる。"):
            self.assertIn(s, text)
        for s in ("`set-due`・`set-time` が書かずに返す", "時刻の欄は外さず `set-time --time <実施日の時刻>` で揃える",
                  "時刻の欄の時刻を使うため）ので、元の時刻の欄が `H:MM` だった行は", "Deck も実施日の時刻を先に使い",
                  "`set-time` は実施日の時刻と違う時刻を書かない"):
            self.assertNotIn(s, text)
        self.assertEqual(text.count("`due` に時刻があり `time` がそれと違う行は（`H:MM` でも）"), 3)   # restore・create モード 2・6
        self.assertIn("`due` に時刻があり時刻がそれと違う項目は（`H:MM` でも）", text)                    # 見出しの名前を直す手順

    def test_set_due_aligns_time_field(self):
        """時刻を含めて set-due を当てると、時刻の欄があればそれも同じ時刻にする（v1.7。食い違いで断るのはやめた）。"""
        self.create()
        self.ok("add", "--section", "明日以降", "--title", "欄", "--time", "10:00")
        self.ok("set-due", "--item", "欄", "--due", self.D + " 9:30")
        self.assertEqual((self.by("欄")["time"], self.by("欄")["due"]), ("9:30", self.D + " 9:30"))
        self.ok("set-due", "--item", "9:30|欄", "--due", iso(4))                    # 日付だけなら時刻の欄はそのまま（それが行の時刻）
        self.assertEqual((self.by("欄")["time"], self.by("欄")["due"]), ("9:30", iso(4)))
        # 時刻の欄の無い行には足さない
        self.ok("add", "--section", "明日以降", "--title", "欄なし", "--due", self.D)
        self.ok("set-due", "--item", "欄なし", "--due", self.D + " 9:30")
        self.assertEqual((self.by("欄なし")["time"], self.by("欄なし")["due"]), (None, self.D + " 9:30"))
        # H:MM でない時刻の欄も、実施日の時刻にそろえる
        self.ok("add", "--section", "明日以降", "--title", "午後", "--time", "15:00")
        self.write(self.text().replace('<div class="time">15:00</div>', '<div class="time">午後</div>', 1))
        self.ok("set-due", "--item", "午後", "--due", self.D + " 9:30")
        self.assertEqual((self.by("午後")["time"], self.by("午後")["due"]), ("9:30", self.D + " 9:30"))
        self.assertEqual(self.k14(), [])

    def test_set_time_aligns_due(self):
        """set-time は、実施日に時刻のある行では実施日の時刻も同じ値にする（v1.7）。日付と一度移した印は変えない。
        --time none は実施日の時刻も外し、日付だけの実施日には時刻を含める（v1.7 第2版）。今日の側の行も同じ（今日の側で 23:00 にした行は 23:00 に鳴る）。"""
        self.create()
        self.ok("add", "--section", "明日以降", "--title", "実施日", "--due", self.D + " 9:30")
        self.ok("set-time", "--item", "実施日", "--time", "10:00")
        self.assertEqual((self.by("実施日")["time"], self.by("実施日")["due"], self.by("実施日")["due_moved"]), ("10:00", self.D + " 10:00", None))
        self.ok("set-time", "--item", "10:00|実施日", "--time", "none")
        self.assertEqual((self.by("実施日")["time"], self.by("実施日")["due"]), (None, self.D))
        self.ok("add", "--section", "明日以降", "--title", "日だけ", "--due", self.D)
        self.ok("set-time", "--item", "日だけ", "--time", "10:00")
        self.assertEqual((self.by("日だけ")["time"], self.by("日だけ")["due"]), ("10:00", self.D + " 10:00"))
        # 今日の側の行（Deck が移した行と同じ形）: 日付と印は変えない
        self.ok("add", "--section", "明日以降", "--title", "今日の側", "--due", iso(0) + " 22:05")
        self.ok("move", "--item", "今日の側", "--section", "今日の予定")
        self.ok("set-time", "--item", "22:05|今日の側", "--time", "23:00")
        it = self.by("今日の側")
        self.assertEqual((it["section"], it["time"], it["due"], it["due_moved"]), ("今日の予定", "23:00", iso(0) + " 23:00", iso(0)))
        self.assertIn("23:00|今日の側", [a[0] for a in dw.read_board_alarms(self.board)])
        # 「明日以降」へ戻すと、決めた実施日の時刻に時刻の欄もそろうので食い違わない（v1.9）
        self.ok("move", "--item", "23:00|今日の側", "--section", "明日以降", "--due", iso(1) + " 22:30")
        self.assertEqual(self.k14(), [])
        it = self.by("今日の側")
        self.assertEqual((it["time"], it["due"], it["due_moved"], it["due_from"]), ("22:30", iso(1) + " 22:30", None, None))

    def k14(self):
        return [w["message"] for w in self.status()["warnings"] if w["code"] == "K14"]


# ------------------------------------------------------------------ 4. 案内の文

OLD_PHRASES = (
    "今日の側へ足すなら due・due_moved は写さない", "add は付けられない", "元の実施日の表示が消える",
    "due が今日の日付で時刻を持つなら", "due_moved のある行は --due を付けずに足し", "--before でその時刻より後の最初の行の前へ置く",
    "重要タスクだった項目は消した後に set-crit", "due に時刻が無く time がある行はその時刻を",
)
NEW_FIELDS = (
    "time・chip・note・due・due_moved・due_from を写す", "due_moved は --due-moved で写す",
    "今日の予定・今日中へ足す行で due があれば due_moved も対で写し、null なら --due-moved none",
    "due に時刻が無く time が H:MM ならその時刻を --due に含め（--due \"<due> <time>\"）、それ以外は time を写さない",
    "due の無い行の time は、「明日以降」へ足すときも --time で写す",
)
ORDER = ("remove で元の行を先に消し（--confirmed を付ける前に、消す行をユーザーに確かめる）、",
         "重要タスクだった項目は足した後に set-crit で付け直してください")


class TestMessages(Base):

    def check(self, msg, extra=()):
        for s in NEW_FIELDS + tuple(extra):
            self.assertIn(s, msg)
        for s in OLD_PHRASES:
            self.assertNotIn(s, msg)

    def test_k11_and_move_errors(self):
        self.create()
        out = self.ok("add", "--section", "本日中", "--create-section", "--title", "x")
        k11 = [w["message"] for w in out["warnings"] if w["code"] == "K11"][0]
        self.check(k11, ORDER + ("正式名の見出しへ add で足し直し",))
        self.check(self.ng("move", "--item", "x", "--section", "明日以降"), ORDER)
        self.create({"sections": ["今日中", "明日以降"], "items": [{"section": "明日以降", "title": "y"}]}, "--confirmed")
        self.put_due("y", iso(0))
        err = self.ng("move", "--item", "y", "--section", "今日の予定")
        self.assertIn("見出しごと作って動かすなら --create-section を付けてください", err)   # 足し直しの回り道は要らない
        self.assertNotIn("remove で元の行を先に消し", err)
        self.ok("move", "--item", "y", "--section", "今日の予定", "--create-section")
        it = [i for i in self.status()["sections"][0]["items"] if i["title"] == "y"][0]
        self.assertEqual((self.status()["sections"][0]["name"], it["chip"], it["due_moved"]), ("今日の予定", "pending", iso(0)))

    def test_restore_and_require_sound(self):
        self.create()
        os.makedirs(os.path.join(self.dir, "history"), exist_ok=True)
        rel = "history/board-%s-lastgood-120000.html" % iso(0)
        with open(os.path.join(self.dir, rel), "wb") as f:
            f.write(self.read())
        out = self.ok("restore", "--from", rel, "--confirmed")
        restore_extra = ("今日の予定へは、時刻のある行は時刻の順の位置へ入る", "動かした後は status でその行を読み直して only_now と違う欄を当てる",
                         "set-due --due <only_now の due> --due-moved <only_now の due_moved>",
                         "今日の予定・今日中の行では --due-moved none、「明日以降」の行では省く")
        self.check(out["message"], restore_extra)
        label = '<div class="section-label">今日中</div>\n'
        self.write(self.text().replace(label, label + tbe.NESTED))
        self.check(self.ng("add", "--section", "今日中", "--title", "z"), restore_extra)

    def test_create_missing(self):
        self.create()
        self.ok("add", "--section", "今日中", "--title", "足した行")
        rc, out = tbe.run(["create", "--board", self.board, "--spec", self.write_spec(tbe.SPEC)])
        self.assertEqual(rc, 1, out)
        msg = out["error"]
        for s in ("missing の time・chip・note・crit・due・due_moved・due_from を写し", "今日の予定・今日中の行で due があれば、due_moved も対で書く（null のままでよい）",
                  "due に時刻が無く time が H:MM ならその時刻を due に含め", "due の無い行の time は time に書く"):
            self.assertIn(s, msg)
        for s in ("今日の側の行の due は写さない", "作った板から元の実施日の表示が消える", "due_moved のある行は due を写さず", "due に時刻が無く time がある行は"):
            self.assertNotIn(s, msg)

    def test_help(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                be.build_parser().parse_args(["add", "--help"])
            except SystemExit:
                pass
        self.assertIn("--due-moved", buf.getvalue())


class TestLaterTimeNotice(Base):
    """v1.6 までの操作でできた食い違う行（「明日以降」で時刻の欄が実施日の時刻と違う）を、警告 K14 で知らせる（v1.6）。

    v1.7 の set-time・set-due・add・create は時刻の欄と実施日の時刻を同じ値にするので、食い違う行は put_legacy_due で作る。move・D&D は今日の側の行を
    形を変えずに戻す。知らせは status と書き込みの出力の warnings と、board.js の「ボードの点検」（tests/test_board_browser.py の TestLaterTime）。"""
    D = iso(3)

    def k14(self, warns):
        return [w["message"] for w in warns if w["code"] == "K14"]

    def back(self, title, tm, due, moved="none", chip="pending"):
        """「明日以降」に時刻の欄 tm・印 moved の行を作り、v1.6 までにできた行として data-due を due にする
        （v1.9 の add は今日の側の行の先の日の実施日を今日にするので、今日の側を経ずに「明日以降」で作る）。"""
        self.ok("add", "--section", "明日以降", "--title", title, "--time", tm, "--chip", chip)
        self.ok("set-due", "--item", "%s|%s" % (tm, title), "--due", due.split(" ")[0] + " " + tm,
                *(("--due-moved", moved) if moved != "none" else ()))
        self.put_legacy_due(title, due, tm)

    def test_move_back_warns_and_status_lists(self):
        self.create()
        self.back("食い違い", "10:00", self.D + " 9:30")
        w = self.k14(self.status()["warnings"])
        self.assertEqual(len(w), 1)
        self.assertIn("「明日以降」に、時刻の欄が実施日の時刻と違う行があります（10:00|食い違い〔時刻の欄 10:00・実施日 %s 9:30〕）。" % self.D, w[0])
        for s in ("v1.6 までの操作（今日の側で set-time した行を move・D&D で戻す等）でできた形です（v1.7 の set-time・set-due・add・create は、時刻の欄と実施日の時刻を同じ値にする）。",
                  "このままだと、今日の側へ動かすとき（move・D&D。一度移した印の無い行は Deck の日付の切り替えも＝Deck v2.11 から）は時刻の欄の時刻が使われ、create で作り直すと実施日の時刻だけが残ります。",
                  "どちらの時刻にするかを確かめ（確かめずにどちらかを消さない）、",
                  "set-time --item <項目> --time <決めた時刻> で揃えてください（実施日の時刻も同じ値になる。日付と一度移した印は変えない）。"):
            self.assertIn(s, w[0])
        for s in ("印のある行", "時刻が無くなる", "--due-moved"):
            self.assertNotIn(s, w[0])
        # ほかの書き込みの出力にも出る
        self.assertEqual(len(self.k14(self.ok("add", "--section", "今日中", "--title", "別")["warnings"])), 1)

    def test_move_back_of_v17_row_does_not_conflict(self):
        """v1.7 の操作でできた行は、今日の側で時刻を変えてから move・D&D で戻しても食い違わない（K14 が出ない）。"""
        self.create()
        self.ok("add", "--section", "今日中", "--title", "揃う", "--time", "10:00", "--due", self.D + " 9:30", "--due-moved", "none")
        self.assertEqual(self.by("揃う")["due"], iso(0) + " 10:00")         # 今日の行になり、実施日の時刻は時刻の欄にそろう（v1.9）
        out = self.ok("move", "--item", "10:00|揃う", "--section", "明日以降", "--due", self.D + " 10:00")
        self.assertEqual(self.k14(out["warnings"]), [])
        self.ok("add", "--section", "今日中", "--title", "D&D", "--time", "11:00", "--due", self.D + " 11:00", "--due-moved", "none")
        self.ok("set-time", "--item", "11:00|D&D", "--time", "11:30")
        new, code, msg = dw.apply_board_move(self.text(), "11:30|D&D", "明日以降", due=self.D + " 11:30", set_due=True)
        self.assertEqual(code, 200, msg)
        self.write(new)
        self.assertEqual(self.k14(self.status()["warnings"]), [])
        self.assertEqual(self.by("D&D")["due"], self.D + " 11:30")

    def test_resolved_by_either_time(self):
        """K14 の案内どおり set-time で決めた時刻に揃えると、どちらの時刻でも K14 が消える（印は残る）。"""
        self.create()
        self.back("実施日の時刻", "10:00", self.D + " 9:30")
        self.back("欄の時刻", "11:00", self.D + " 9:30", moved=iso(0))
        self.assertEqual(len(self.k14(self.status()["warnings"])), 1)
        self.ok("set-time", "--item", "10:00|実施日の時刻", "--time", "9:30")
        self.ok("set-time", "--item", "11:00|欄の時刻", "--time", "11:00")
        self.assertEqual(self.k14(self.status()["warnings"]), [])
        self.assertEqual((self.by("実施日の時刻")["time"], self.by("実施日の時刻")["due"]), ("9:30", self.D + " 9:30"))
        it = self.by("欄の時刻")
        self.assertEqual((it["time"], it["due"], it["due_moved"]), ("11:00", self.D + " 11:00", iso(0)))


    def test_legacy_rows_move_with_time_field(self):
        """食い違う行（印あり・印なし）を今日の側へ動かすと、時刻の欄の時刻が使われ、実施日の時刻もその値になる（v1.7・Deck v2.11）。
        前の日の行は時刻の欄を外して鳴らさない。印は変えない。D&D（apply_board_move）と move は同じ形になる。"""
        self.create()
        self.back("印あり", "10:00", iso(0) + " 9:30", moved=iso(0))
        self.back("印なし", "10:05", iso(0) + " 9:30")
        self.back("前の日", "10:10", iso(-1) + " 9:30", moved=iso(-1))
        start = self.text()
        for key in ("10:00|印あり", "10:05|印なし", "10:10|前の日"):
            self.ok("move", "--item", key, "--section", "今日の予定")
        mine = blocks(self.text())
        deck = start
        for key in ("10:00|印あり", "10:05|印なし", "10:10|前の日"):
            deck, code, msg = dw.apply_board_move(deck, key, "今日の予定")
            self.assertEqual(code, 200, msg)
        bd = blocks(deck)
        for t in ("印あり", "印なし", "前の日"):
            self.assertEqual(mine[t], bd[t], t)
        self.assertEqual((self.by("印あり")["time"], self.by("印あり")["due"], self.by("印あり")["due_moved"], self.by("印あり")["due_from"]),
                         ("10:00", iso(0) + " 10:00", iso(0), iso(0) + " 10:00"))
        self.assertEqual((self.by("印なし")["time"], self.by("印なし")["due"], self.by("印なし")["due_moved"], self.by("印なし")["due_from"]),
                         ("10:05", iso(0) + " 10:05", iso(0), iso(0) + " 10:05"))
        # 元の実施日の時刻は行の時刻（時刻の欄。食い違う行では時刻の欄を使う＝2026-11-05 ユーザー決定・v1.8）。
        # 「前の日」の元の実施日は、前の日の日付と行の時刻（時刻の欄 10:10＝v1.8）
        it = self.by("前の日")
        self.assertEqual((it["time"], it["due"], it["due_moved"], it["due_from"]), (None, iso(0), iso(-1), iso(-1) + " 10:10"))
        self.assertNotIn("data-orig-time", mine["前の日"][1])
        alarms = [a[0] for a in dw.read_board_alarms(self.board)]
        self.assertEqual(sorted(a for a in alarms if a.split("|")[1] in ("印あり", "印なし", "前の日")), ["10:00|印あり", "10:05|印なし"])

    def test_done_is_judged_by_chip_only(self):
        """済の判定はチップだけ（done-item だけが付いて済チップの無い行は数える。K12 も同じ）。"""
        self.create()
        self.back("淡色だけ", "10:00", self.D + " 9:30")
        self.ok("add", "--section", "明日以降", "--title", "淡色の午後", "--due", self.D + " 9:30")
        t = self.text()
        t = t.replace('<p class="task-title">淡色の午後</p>', '<div class="time">午後</div><p class="task-title">淡色の午後</p>', 1)
        t = re.sub(r'class="item([^"]*)"((?:(?!class="item).)*?淡色だけ</p>)', r'class="item\1 done-item"\2', t, count=1, flags=re.S)
        t = re.sub(r'class="item([^"]*)"((?:(?!class="item).)*?淡色の午後</p>)', r'class="item\1 done-item"\2', t, count=1, flags=re.S)
        self.assertEqual(t.count("done-item"), 2)
        self.write(t)
        warns = self.status()["warnings"]
        self.assertEqual(len(self.k14(warns)), 1)
        self.assertIn("淡色だけ", self.k14(warns)[0])
        self.assertIn("淡色の午後", [w["message"] for w in warns if w["code"] == "K12"][0])

    def test_no_marked_row_steps_in_guidance(self):
        """K12・K14・足し直しの案内から、印のある行で時刻の欄も揃える手順が無くなっている（v1.7）。"""
        self.create()
        self.ok("add", "--section", "明日以降", "--title", "午後の件", "--due", self.D + " 9:30")
        self.write(self.text().replace('<p class="task-title">午後の件</p>', '<div class="time">午後</div><p class="task-title">午後の件</p>', 1))
        self.back("食い違い", "10:00", self.D + " 9:30")
        warns = self.ok("add", "--section", "今日中", "--title", "x")["warnings"]
        texts = [w["message"] for w in warns if w["code"] in ("K12", "K14")] + [be.readd_fields("x"), be.restore_readd_text("x")]
        self.assertEqual(len(texts), 4)
        for t in texts:
            for old in ("時刻の欄も揃える", "時刻の欄も足す", "時刻が無くなる", "印のある行", "時刻は due に残る", "時刻は実施日に残る"):
                self.assertNotIn(old, t)
        self.assertFalse(hasattr(be, "LATER_TIME_RULE"))

    def test_dnd_back_warns(self):
        """Deck の D&D（apply_board_move）で食い違う行を戻しても形を変えず、status が知らせる。"""
        self.create()
        self.ok("add", "--section", "今日中", "--title", "D&D", "--time", "10:00", "--due", self.D + " 10:00", "--due-moved", "none")
        self.put_legacy_due("D&D", self.D + " 9:30")
        self.assertEqual(self.k14(self.status()["warnings"]), [])          # 今日の側の行は K14 の対象でない
        new, code, msg = dw.apply_board_move(self.text(), "10:00|D&D", "明日以降")
        self.assertEqual(code, 200, msg)
        self.write(new)
        w = self.k14(self.status()["warnings"])
        self.assertEqual(len(w), 1)
        self.assertIn("10:00|D&D〔時刻の欄 10:00・実施日 %s 9:30〕" % self.D, w[0])

    def test_not_listed(self):
        self.create()
        self.back("同じ時刻", "9:30", self.D + " 09:30")
        self.back("済", "10:00", self.D + " 9:30", chip="done")
        self.ok("add", "--section", "明日以降", "--title", "日付だけ", "--due", self.D)
        self.ok("set-time", "--item", "日付だけ", "--time", "10:00")
        self.ok("add", "--section", "明日以降", "--title", "実施日なし", "--time", "10:00")
        self.ok("add", "--section", "今日中", "--title", "今日の側", "--time", "10:00", "--due", self.D + " 9:30", "--due-moved", "none")
        self.back("午後", "10:07", self.D + " 9:30")
        self.assertEqual(self.text().count('<div class="time">10:07</div>'), 1)
        self.write(self.text().replace('<div class="time">10:07</div>', '<div class="time">午後</div>'))
        self.assertEqual(self.by("午後")["time"], "午後")
        warns = self.status()["warnings"]
        self.assertEqual(self.k14(warns), [])
        self.assertEqual([w["code"] for w in warns], ["K12"])          # H:MM でない時刻の欄は K12 が知らせる

    def test_help(self):
        import io
        import contextlib
        self.assertEqual(be.VERSION, "1.17")
        outs = {}
        for op in ("move", "set-time", "set-due"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    be.build_parser().parse_args([op, "--help"])
                except SystemExit:
                    pass
            outs[op] = re.sub(r"\s+", "", buf.getvalue())
        self.assertIn("今日の予定・今日中の行を「明日以降」へ動かすときは--dueが要る", outs["move"])
        self.assertIn("印のある行・実施日の前の行も同じ形にする＝v1.7", outs["move"])
        self.assertIn("実施日のある行では、実施日の時刻も同じ値にする", outs["set-time"])
        self.assertIn("時刻の欄があればそれも同じ時刻にする", outs["set-due"])
        self.assertNotIn("v1.5", outs["set-time"] + outs["set-due"])

    def test_docs(self):
        """SKILL.md（行の時刻は1つ・K14 の扱い・ボードの点検の⑤・✎ は「明日以降」の行で受けない）と deck/README.md が実装と合っている。"""
        def flat(*p):
            with open(os.path.join(tbe.ROOT, *p), encoding="utf-8") as f:
                return re.sub(r"\s+", "", f.read())
        skill = flat("skill", "SKILL.md")
        for s in ("`version`1.6までの操作でできた、「明日以降」の行で時刻の欄が実施日の時刻と違う行は、",
                  "K14として出る（`version`1.6から）",
                  "`set-time--time<決めた時刻>`で揃える。",
                  "⑤「明日以降」の未完了の行で、実施日（`data-due`）に時刻があり、`H:MM`（時0〜23・分0〜59）の時刻の欄がそれと違うもの",
                  "⑤は`status`の`warnings`のK14に出た行を、その文のとおりに直す",
                  "`set-time--time<決めた時刻>`で揃える（実施日の時刻も同じ値になる。確かめずにどちらかを消さない）。",
                  "印のある行と実施日の前の行も同じ形にする〔`version`1.7・Deckv2.11から。前の日・先の日の時刻は今日の時刻にしない〕",
                  "**実施日の前に動かした行（先の日の行を前もって今日の側へ動かした行）も今日の行として扱う**",
                  "「明日以降」の行の時刻は✎で変えられない",
                  "「明日以降」の行には✎の変更を出さず、元の時刻を出す"):
            self.assertIn(s, skill)
        for s in ("印（`due_moved`）のある行はDeckが移し直さず", "時刻の欄は外さず`set-time--time<実施日の時刻>`で揃える",
                  "`set-time--time<当てたdueの時刻>`で時刻の欄も揃える",
                  # 版の下限（`version` 1.10 より前なら書かない）より古い版の、書く操作の場合分けは、通らない枝なので置かない（読むだけの `deck-snap`・`deck-wait` の枝は通る＝SKILL.md の生死表示の項）
                  "`version`1.6より前の`board_edit.py`はK14を出さないので",
                  "⑥はその版では直さずにユーザーに伝える"):
            self.assertNotIn(s, skill)
        readme = flat("deck", "README.md")
        self.assertIn("「明日以降」の行も✎は操作できず", readme)
        self.assertIn("#Deckv2.21—全セッション自動収集ウォッチャー", readme)
        self.assertNotIn("実施日の前の行は`data-due`の日付も印も変えない", readme)
        self.assertNotIn("実施日の前に動かした行には付けない", readme)
        self.assertNotIn("実施日の前の行には付けない〕", readme)
        self.assertIn("v2.11からは、一度移した印のある行と実施日の前の行も対象にする", readme)




class TestDocs(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(tbe.ROOT, *p), encoding="utf-8") as f:
            return f.read()

    def test_skill(self):
        text = self.read("skill", "SKILL.md")
        for s in ("[--due-moved <日付>\|none]", "`time`・`chip`・`note`・`due`・`due_moved`・`due_from` を写す",
                  "今日の予定・今日中へ足す行で `due` があれば `due_moved` も対で写し、`null` なら `--due-moved none`",
                  "`due` に時刻が無く `time` が `H:MM` ならその時刻を `--due` に含め",
                  "`due` の無い行の `time` は、「明日以降」へ足すときも `--time` で写す",
                  "`move` は Deck の日付の切り替えと同じ形にする",
                  "`--head` で移す行が複数あるときは、下の行から移すと Deck と同じ並びになる",
                  "行き先の見出しが無い板では、同じ `move` に `--create-section` を付ける",
                  "`set-due --due <only_now の due> --due-moved <only_now の due_moved> --due-from <only_now の due_from>`",
                  "項目のキーは `section`・`time`・`title`・`note`・`chip`・`crit`・`due`・`due_moved`・`due_from` だけ"):
            self.assertIn(s, text)
        for s in ("今日の側の行の `due`・`due_moved` は写さない", "`add` は付けられない", "元の実施日の表示が消える",
                  "続けて `set-time --item <タイトル> --time <時刻", "続けて `set-time --item <タイトル> --time none` で外す",
                  "続けて `set-chip --chip pending`", "`due_moved` のある行は `--due` を付けずに足し",
                  "`due_moved` のある「明日以降」の行（移した後に\n   ユーザーが戻した行）は `due` を写さず",
                  "`--before` でその時刻より後の最初の行の前へ置く", "`due` に時刻が無く `time` がある行は",
                  "今日の側の行の `due` は写さない"):
            self.assertNotIn(s, text)

    def test_readme(self):
        text = self.read("deck", "README.md")
        self.assertIn("D&D〔v2.10 から〕と `board_edit.py` の `move` は、時刻の要素・状態チップも Deck の切り替えと同じ規則で形にする", text)
        self.assertIn("Deck は今日の側の行の `data-due`・`data-due-moved`・`data-due-from` を、移す判定にも通知にも使わない", text)
        self.assertIn("v2.9 までの D&D は印だけを付けた", text)       # 印だけは旧版の話として残る
        self.assertNotIn("D&D は印だけを付け、", text)                 # v2.9 までの記述（いまの D&D の話として）は残さない
        self.assertNotIn("動かしたときも同じ印を付ける（実施日の前に動かした行には付けない）。", text)


if __name__ == "__main__":
    unittest.main()
