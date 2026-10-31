import json
import sqlite3
from contextlib import closing

import pytest

from wxlocal import build_db21 as builder


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    exports = tmp_path / "exports21"
    exports.mkdir()
    monkeypatch.setattr(builder, "HERE", str(tmp_path))
    monkeypatch.setattr(builder, "OUT_DIR", str(exports))
    monkeypatch.setattr(builder, "DB_PATH", str(tmp_path / "wxbase.db"))
    (exports / "cards.json").write_text("{}", encoding="utf-8")
    (exports / "membership.json").write_text("{}", encoding="utf-8")
    payload = {"chats": [{"kind": "group", "participants": {}, "messages": [
        {"s": "me", "c": "new message", "t": 1, "sid": "new"},
    ]}]}
    (exports / "wx_demo.json").write_text(json.dumps(payload), encoding="utf-8")
    with closing(sqlite3.connect(builder.DB_PATH)) as con, con:
        con.executescript(builder.SQL_SCHEMA)
        con.execute("INSERT INTO wx_messages(chat_raw, text) VALUES('old', 'old message')")
        con.execute("INSERT INTO wx_coref(person, alias) VALUES('old', 'alias')")
        con.execute("INSERT INTO wx_edges(src, dst, etype) VALUES('old', 'other', 'reply')")
        con.execute("INSERT INTO wx_profile_features(person) VALUES('old')")
        con.execute("INSERT INTO wx_membership(room, wxid) VALUES('old', 'wxid_old')")
        con.execute("INSERT INTO wx_verify(entity, status, evidence) "
                    "VALUES('example.org', 'VERIFIED', 'manual evidence')")
    return exports


def snapshot():
    with closing(sqlite3.connect(builder.DB_PATH)) as con:
        return list(con.iterdump())


@pytest.mark.parametrize("mode", [{}, {"rebuild": True}, {"append": True}])
@pytest.mark.parametrize("failure", ["missing", "malformed", "late"])
def test_failed_build_preserves_entire_database(corpus, mode, failure):
    before = snapshot()
    if failure == "missing":
        (corpus / "cards.json").unlink()
        error = FileNotFoundError
    elif failure == "malformed":
        # Sorted after a valid export, so some messages have already been inserted.
        (corpus / "wx_zbroken.json").write_text("{", encoding="utf-8")
        error = json.JSONDecodeError
    else:
        # Failure after messages and membership have been imported.
        (corpus.parent / "identities.json").write_text(
            '{"aliases": ["invalid mapping"]}', encoding="utf-8")
        error = AttributeError
    with pytest.raises(error):
        builder.main(**mode)
    assert snapshot() == before
    # Also check that the failed build released its write lock.
    with closing(sqlite3.connect(builder.DB_PATH, timeout=0)) as con:
        con.execute("BEGIN IMMEDIATE")
        con.rollback()


def test_default_build_is_idempotent_and_preserves_verification(corpus):
    builder.main()
    first = snapshot()
    builder.main()
    assert snapshot() == first
    with closing(sqlite3.connect(builder.DB_PATH)) as con:
        assert con.execute("SELECT text FROM wx_messages").fetchall() == [("new message",)]
        assert con.execute("SELECT entity, status, evidence FROM wx_verify").fetchall() == [
            ("example.org", "VERIFIED", "manual evidence"),
        ]
        assert con.execute("SELECT COUNT(*) FROM wx_edges").fetchone()[0] == 0


def test_explicit_rebuild_resets_verification(corpus):
    builder.main(rebuild=True)
    with closing(sqlite3.connect(builder.DB_PATH)) as con:
        assert con.execute("SELECT text FROM wx_messages").fetchall() == [("new message",)]
        assert con.execute("SELECT COUNT(*) FROM wx_verify").fetchone()[0] == 0


def test_append_preserves_old_messages_and_verification(corpus):
    builder.main(append=True)
    with closing(sqlite3.connect(builder.DB_PATH)) as con:
        assert con.execute("SELECT text FROM wx_messages ORDER BY id").fetchall() == [
            ("old message",), ("new message",),
        ]
        assert con.execute("SELECT status FROM wx_verify").fetchall() == [("VERIFIED",)]
