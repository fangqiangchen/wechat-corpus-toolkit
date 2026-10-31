import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from wxlocal import build_db21
from wxlocal.analyze import turn_window


def make_rows(tmp_path, target, quote_at, quote_id=True):
    path = tmp_path / "turns.db"
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript(build_db21.SQL_SCHEMA)
        for i in range(quote_at + 1):
            text = "原文证据" if i == target else "ordinary message"
            if i == quote_at:
                text = "[引用消息]回复 [↩ 原作者: 原文证据]"
            con.execute(
                "INSERT INTO wx_messages(chat_raw, sender_full, text, ts_iso, ts_ms, "
                "sid, sq, quote_svrid) VALUES(?,?,?,?,?,?,?,?)",
                ("demo", "reader" if i == quote_at else "author", text,
                 "2026-01-01T00:00:00", i * 1000, str(100 + i), i,
                 str(100 + target) if i == quote_at and quote_id else None))
    return path, turn_window.load(str(path), "demo")


@pytest.mark.parametrize("target,quote_at", [(1, 21), (0, 21), (0, 35), (5, 40)])
def test_quote_id_expands_window_to_original(tmp_path, target, quote_at):
    _, rows = make_rows(tmp_path, target, quote_at)
    assert turn_window.quote_anchor_dist(rows, quote_at) == quote_at - target
    assert turn_window.window_of(rows, [quote_at, quote_at]) == (target, quote_at + 1)


def test_quote_expansion_keeps_35_message_limit(tmp_path):
    _, rows = make_rows(tmp_path, 0, 36)
    assert turn_window.quote_anchor_dist(rows, 36) is None
    assert turn_window.window_of(rows, [36, 36]) == (26, 37)


def test_missing_quote_id_uses_existing_text_fallback(tmp_path):
    _, rows = make_rows(tmp_path, 0, 21, quote_id=False)
    rows[0] = ("author", "abcdefghijklmnop original", *rows[0][2:])
    rows[21] = ("reader", "[引用消息]<title>abcdefghijklmnop</title>", *rows[21][2:])
    assert turn_window.quote_anchor_dist(rows, 21) == 21


def test_cli_and_dump_accept_loaded_quote_metadata(tmp_path):
    path, _ = make_rows(tmp_path, 1, 21)
    scripts = Path(turn_window.__file__).parent
    result = subprocess.run(
        [sys.executable, str(scripts / "turn_window.py"), "reader", "demo",
         "--turn", "1", "--db", str(path)], capture_output=True, text=True,
        encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    assert result.returncode == 0, result.stderr
    assert "窗口[1..21]" in result.stdout and "原文证据" in result.stdout
    output = tmp_path / "turns.md"
    result = subprocess.run(
        [sys.executable, str(scripts / "dump_turn_windows.py"), "reader", "demo",
         str(output), "--db", str(path)], capture_output=True, text=True,
        encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    assert result.returncode == 0, result.stderr
    assert "消息[1..21]" in output.read_text(encoding="utf-8")
