import importlib.util
import os
from pathlib import Path

import pytest


DOCTOR_PATH = Path(__file__).parents[1] / "scripts" / "common" / "doctor.py"
SPEC = importlib.util.spec_from_file_location("wechat_doctor", DOCTOR_PATH)
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


def test_read_key_never_returns_secret(tmp_path):
    path = tmp_path / "key.txt"
    secret = "ab" * 32
    path.write_text(secret, encoding="ascii")
    ok, detail = doctor._read_key(str(path))
    assert ok is True
    assert detail == "present (64 hex chars)"
    assert secret not in detail


def test_key_check_warns_on_broad_posix_permissions(tmp_path):
    if os.name == "nt":
        return
    path = tmp_path / "key.txt"
    path.write_text("ab" * 32, encoding="ascii")
    path.chmod(0o644)
    check = doctor._key_check(str(path))
    assert check.status == "warn"
    assert "0644" in check.detail
    assert "ab" * 32 not in check.detail

    path.chmod(0o600)
    check = doctor._key_check(str(path))
    assert check.status == "ok"


@pytest.mark.parametrize("system,status", [("Linux", "fail"), ("Darwin", "warn")])
def test_non_windows_stops_before_local_discovery(monkeypatch, tmp_path, system, status):
    def unexpected_discovery():
        pytest.fail("Non-Windows diagnostics should not discover local accounts")

    monkeypatch.setattr(doctor, "_config_module", unexpected_discovery)
    checks = doctor.collect_checks(system=system, skill_dir=str(tmp_path))
    assert [item.name for item in checks] == ["platform", "python"]
    assert checks[0].status == status


@pytest.fixture
def windows_diagnostics(monkeypatch):
    monkeypatch.setattr(doctor, "_config_module", lambda: None)
    monkeypatch.setattr(doctor, "_has_module", lambda *names: True)


def test_windows_database_check_accepts_nonzero_shard(windows_diagnostics, tmp_path):
    data_dir = tmp_path / "decrypted" / "account" / "db_storage"
    message_dir = data_dir / "message"
    message_dir.mkdir(parents=True)
    (message_dir / "message_3.db").write_bytes(b"database")
    checks = {c.name: c for c in doctor.collect_checks(system="Windows", skill_dir=str(tmp_path))}
    assert checks["database"].status == "ok"
    assert checks["key"].status == "fail"


def test_windows_database_check_fails_without_shards(windows_diagnostics, tmp_path):
    checks = {c.name: c for c in doctor.collect_checks(system="Windows", skill_dir=str(tmp_path))}
    assert checks["database"].status == "fail"


def test_windows_missing_decompressor_is_reported(windows_diagnostics, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_has_module", lambda *names: names in [("frida",), ("Crypto",)])
    checks = {c.name: c for c in doctor.collect_checks(system="Windows", skill_dir=str(tmp_path))}
    assert checks["dependency:frida"].status == "ok"
    assert checks["dependency:pycryptodome"].status == "ok"
    assert checks["dependency:zstd"].status == "warn"
