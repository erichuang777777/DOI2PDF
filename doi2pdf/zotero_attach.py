"""Guarded linked-PDF attachment writer retained from Zotero PDF Hunter."""

from __future__ import annotations

import csv
import os
import random
import re
import shutil
import sqlite3
import string
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .http import MAX_PDF_BYTES, looks_like_pdf


def zotero_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
        output = subprocess.check_output([str(tasklist), "/FI", "IMAGENAME eq zotero.exe"], text=True)
        return "zotero.exe" in output.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def successful_csv_entries(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("status") == "success" and row.get("filepath")]


def _attachment_title(path: Path) -> str:
    match = re.match(r"^[A-Z0-9]{8}_(.+)$", path.stem)
    return match.group(1) if match else path.stem


def _new_key(connection: sqlite3.Connection, library_id: int) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        key = "".join(random.SystemRandom().choices(alphabet, k=8))
        if not connection.execute("select 1 from items where key=? and libraryID=?", (key, library_id)).fetchone():
            return key


def attach_linked_pdfs(database: Path, entries: list[dict[str, Any]], *, write: bool = False) -> dict[str, Any]:
    if not database.is_file():
        raise FileNotFoundError(database)
    if write and zotero_running():
        raise RuntimeError("Close Zotero before writing linked attachments.")
    normalized = []
    for entry in entries:
        path = Path(entry["filepath"]).expanduser().resolve()
        valid_pdf = False
        if path.is_file() and path.stat().st_size <= MAX_PDF_BYTES:
            valid_pdf = looks_like_pdf(path.read_bytes())
        if not valid_pdf:
            normalized.append({"item_key": entry.get("key"), "file": str(path), "status": "missing_or_not_pdf"})
        else:
            normalized.append({"item_key": str(entry.get("key") or "").strip(), "file": str(path), "status": "pending", "path": path})
    backup = None
    if write:
        backup = database.with_name(f"{database.name}.doi2pdf-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(database, backup)
    uri = f"file:{database.resolve().as_posix()}?mode={'rw' if write else 'ro'}"
    with sqlite3.connect(uri, uri=True, timeout=10) as connection:
        connection.row_factory = sqlite3.Row
        attachment_type = connection.execute("select itemTypeID from itemTypes where typeName='attachment'").fetchone()
        title_field = connection.execute("select fieldID from fields where fieldName='title'").fetchone()
        if not attachment_type:
            raise RuntimeError("Zotero attachment item type is missing.")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for row in normalized:
            if row["status"] != "pending":
                continue
            parent = connection.execute("select itemID,libraryID from items where key=?", (row["item_key"],)).fetchone()
            if not parent:
                row["status"] = "item_not_found"
                continue
            existing = connection.execute(
                "select 1 from itemAttachments where parentItemID=? and contentType='application/pdf' and linkMode in (0,2)",
                (parent["itemID"],),
            ).fetchone()
            if existing:
                row["status"] = "already_has_pdf"
                continue
            if not write:
                row["status"] = "would_attach"
                continue
            key = _new_key(connection, parent["libraryID"])
            connection.execute(
                "insert into items(itemTypeID,dateAdded,dateModified,clientDateModified,libraryID,key,version,synced) values(?,?,?,?,?,?,0,0)",
                (attachment_type[0], now, now, now, parent["libraryID"], key),
            )
            item_id = connection.execute("select last_insert_rowid()").fetchone()[0]
            connection.execute(
                "insert into itemAttachments(itemID,parentItemID,linkMode,contentType,path,syncState) values(?,?,2,'application/pdf',?,0)",
                (item_id, parent["itemID"], str(row["path"])),
            )
            if title_field:
                title = _attachment_title(row["path"])
                existing_value = connection.execute("select valueID from itemDataValues where value=?", (title,)).fetchone()
                if existing_value:
                    value_id = existing_value[0]
                else:
                    connection.execute("insert into itemDataValues(value) values(?)", (title,))
                    value_id = connection.execute("select last_insert_rowid()").fetchone()[0]
                connection.execute("insert or ignore into itemData(itemID,fieldID,valueID) values(?,?,?)", (item_id, title_field[0], value_id))
            row["status"] = "attached"
        if write:
            connection.commit()
    for row in normalized:
        row.pop("path", None)
    return {"write": write, "backup": str(backup) if backup else None, "results": normalized}
