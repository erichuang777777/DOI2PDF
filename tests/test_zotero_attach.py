import csv
import sqlite3
from pathlib import Path

from doi2pdf.zotero_attach import attach_linked_pdfs, successful_csv_entries


def _database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript("""
        create table itemTypes(itemTypeID integer primary key, typeName text);
        create table fields(fieldID integer primary key, fieldName text);
        create table items(itemID integer primary key, itemTypeID integer, dateAdded text,
          dateModified text, clientDateModified text, libraryID integer, key text,
          version integer, synced integer);
        create table itemAttachments(itemID integer primary key, parentItemID integer,
          linkMode integer, contentType text, path text, syncState integer);
        create table itemDataValues(valueID integer primary key, value text unique);
        create table itemData(itemID integer, fieldID integer, valueID integer,
          unique(itemID,fieldID));
        insert into itemTypes values(1,'journalArticle');
        insert into itemTypes values(14,'attachment');
        insert into fields values(1,'title');
        insert into items values(1,1,'','','',1,'ABCDEFGH',0,0);
        """)


def _pdf(path):
    path.write_bytes(b"%PDF-1.7\n" + b"x" * 1200)


def test_attach_is_dry_run_by_default(tmp_path):
    db = tmp_path / "zotero.sqlite"
    pdf = tmp_path / "paper.pdf"
    _database(db)
    _pdf(pdf)
    result = attach_linked_pdfs(db, [{"key": "ABCDEFGH", "filepath": str(pdf)}])
    assert result["backup"] is None
    assert result["results"][0]["status"] == "would_attach"
    with sqlite3.connect(db) as connection:
        assert connection.execute("select count(*) from itemAttachments").fetchone()[0] == 0


def test_attach_writes_linked_pdf_and_backup(tmp_path, monkeypatch):
    db = tmp_path / "zotero.sqlite"
    pdf = tmp_path / "ABCDEFGH_Smith_2024_Paper.pdf"
    _database(db)
    _pdf(pdf)
    monkeypatch.setattr("doi2pdf.zotero_attach.zotero_running", lambda: False)
    result = attach_linked_pdfs(db, [{"key": "ABCDEFGH", "filepath": str(pdf)}], write=True)
    assert result["results"][0]["status"] == "attached"
    assert result["backup"] and Path(result["backup"]).exists()
    with sqlite3.connect(db) as connection:
        row = connection.execute("select parentItemID,linkMode,contentType,path from itemAttachments").fetchone()
    assert row == (1, 2, "application/pdf", str(pdf.resolve()))


def test_successful_csv_entries_filters_failures(tmp_path):
    path = tmp_path / "run_log.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["key", "status", "filepath"])
        writer.writeheader()
        writer.writerow({"key": "GOODKEY1", "status": "success", "filepath": "paper.pdf"})
        writer.writerow({"key": "BADKEY01", "status": "failed", "filepath": "bad.pdf"})
    assert successful_csv_entries(path) == [{"key": "GOODKEY1", "status": "success", "filepath": "paper.pdf"}]
