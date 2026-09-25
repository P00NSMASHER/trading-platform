from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from control_plane import integrity, registry, source_policy, storage


def _register(tmp_path: Path, source: Path, source_id: str = "s1"):
    control=tmp_path/"control"; snap=storage.receive_to_holding(source,control); db=control/"control.sqlite"
    row=registry.register_information(db,domain="metadata",source_id=source_id,content_sha256=snap.sha256,size_bytes=snap.size_bytes,
        source_contract_sha256="a"*64,data_classification="synthetic_fixture",record_kind="announcement_timestamp",source_family="synthetic_fixture")
    if row["created"]:
        registry.append_event(db,row["information_id"],"RECEIVED","RECEIVED"); registry.append_event(db,row["information_id"],"HELD","HOLDING")
    return control,db,snap,row


def test_same_identity_is_idempotent_and_changed_bytes_get_new_id(tmp_path: Path):
    source=tmp_path/"a.csv"; source.write_text("x\n1\n",encoding="utf-8")
    _,_,_,first=_register(tmp_path,source); _,_,_,same=_register(tmp_path,source)
    assert same["information_id"]==first["information_id"]; assert same["created"] is False
    source.write_text("x\n2\n",encoding="utf-8"); _,_,_,changed=_register(tmp_path,source)
    assert changed["information_id"]!=first["information_id"]


def test_registry_rows_and_events_are_immutable(tmp_path: Path):
    source=tmp_path/"a.csv"; source.write_text("x\n1\n",encoding="utf-8"); _,db,_,row=_register(tmp_path,source)
    with sqlite3.connect(db) as con:
        with pytest.raises(sqlite3.IntegrityError): con.execute("UPDATE information_object SET source_id='changed' WHERE information_id=?",(row["information_id"],))
        with pytest.raises(sqlite3.IntegrityError): con.execute("DELETE FROM information_event WHERE information_id=?",(row["information_id"],))


def test_source_policy_is_allow_only():
    assert source_policy.evaluate({"data_classification":"synthetic_fixture"}).decision=="ADMIT_STRUCTURED"
    assert source_policy.evaluate({"data_classification":"live_stolen_information"}).decision=="QUARANTINE"
    assert source_policy.evaluate({"data_classification":"something_new"}).decision=="REVIEW_REQUIRED"
    assert source_policy.evaluate({"data_classification":"authorized_reference_data","authorized":False,"license_reference":"x"}).decision=="REVIEW_REQUIRED"


def test_holding_tamper_is_detected(tmp_path: Path):
    source=tmp_path/"a.csv"; source.write_text("x\n1\n",encoding="utf-8"); control,db,snap,row=_register(tmp_path,source)
    registry.append_event(db,row["information_id"],"ADMITTED","ADMITTED_STRUCTURED")
    assert integrity.verify_control_plane(db,control)["ok"] is True
    snap.path.write_text("tampered",encoding="utf-8"); report=integrity.verify_control_plane(db,control)
    assert report["ok"] is False; assert report["holding_hashes_valid"] is False
