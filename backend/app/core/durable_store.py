"""Encrypted single-volume SQLite storage; never silently falls back on errors.

Enable with ASHLAR_DB_PATH on a persistent volume and ASHLAR_STORAGE_KEY (Fernet).
The key must be backed up separately from the database. Multiple processes on
one volume are supported; independent services need a shared database adapter.
"""
from __future__ import annotations

import base64
from collections.abc import MutableMapping
from contextlib import contextmanager
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import BaseModel, TypeAdapter


def _encode(value):
    if isinstance(value, bytes):
        return {"__ashlar_bytes__": base64.b64encode(value).decode()}
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    raise TypeError(type(value).__name__)


def _decode(value):
    if set(value) == {"__ashlar_bytes__"}:
        return base64.b64decode(value["__ashlar_bytes__"])
    return value


class EncryptedRecords(MutableMapping):
    def __init__(self, path, key, namespace, record_type, key_type=str):
        self.path = str(path)
        self.cipher = Fernet(key)
        self.namespace = namespace
        self.adapter = TypeAdapter(record_type)
        self.key_type = key_type
        self.local = threading.local()
        self.lock = threading.RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS records (namespace TEXT, id TEXT, payload BLOB NOT NULL, PRIMARY KEY(namespace,id))")
        os.chmod(self.path, 0o600)

    @contextmanager
    def transaction(self):
        with self.lock:
            if getattr(self.local, "db", None) is not None:
                yield
                return
            db = sqlite3.connect(self.path, timeout=30)
            self.local.db = db
            try:
                db.execute("BEGIN IMMEDIATE")
                yield
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                self.local.db = None
                db.close()

    def _id(self, key):
        return hashlib.sha256(str(key).encode()).hexdigest()

    def __getitem__(self, key):
        with self.transaction():
            row = self.local.db.execute("SELECT payload FROM records WHERE namespace=? AND id=?", (self.namespace, self._id(key))).fetchone()
            if row is None:
                raise KeyError(key)
            data = json.loads(self.cipher.decrypt(row[0]), object_hook=_decode)
            return self.adapter.validate_python(data["record"])

    def __setitem__(self, key, value):
        raw = json.dumps({"key": str(key), "record": self.adapter.dump_python(value)}, default=_encode).encode()
        with self.transaction():
            self.local.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (self.namespace, self._id(key), self.cipher.encrypt(raw)))

    def __delitem__(self, key):
        with self.transaction():
            cursor = self.local.db.execute("DELETE FROM records WHERE namespace=? AND id=?", (self.namespace, self._id(key)))
            if not cursor.rowcount:
                raise KeyError(key)

    def __iter__(self):
        with self.transaction():
            rows = self.local.db.execute("SELECT payload FROM records WHERE namespace=?", (self.namespace,)).fetchall()
            keys = [self.key_type(json.loads(self.cipher.decrypt(row[0]))["key"]) for row in rows]
        return iter(keys)

    def __len__(self):
        with self.transaction():
            return self.local.db.execute("SELECT COUNT(*) FROM records WHERE namespace=?", (self.namespace,)).fetchone()[0]


class TransactionLock:
    def __init__(self, records):
        self.records = records
        self.local = threading.local()

    def __enter__(self):
        self.local.context = self.records.transaction()
        return self.local.context.__enter__()

    def __exit__(self, *args):
        return self.local.context.__exit__(*args)


def configure_store(store, *, attribute, namespace, record_type, key_type=str):
    path = os.environ.get("ASHLAR_DB_PATH")
    if not path:
        return store
    key = os.environ.get("ASHLAR_STORAGE_KEY")
    if not key:
        raise RuntimeError("ASHLAR_DB_PATH requires ASHLAR_STORAGE_KEY; refusing unencrypted storage")
    records = EncryptedRecords(path, key, namespace, record_type, key_type)
    setattr(store, attribute, records)
    store._lock = TransactionLock(records)
    store.durable = True
    # Retention is explicit and independent of the browser session.
    from datetime import timedelta
    store.ttl = timedelta(days=int(os.environ.get("ASHLAR_RETENTION_DAYS", "365")))
    return store


def storage_status():
    return "encrypted_sqlite" if os.environ.get("ASHLAR_DB_PATH") else "process_local"
