from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def find_zotero_db() -> Path | None:
    home = Path.home()
    candidates = [home / "Zotero" / "zotero.sqlite"]
    if sys.platform == "win32":
        import os

        if os.getenv("APPDATA"):
            candidates.append(Path(os.environ["APPDATA"]) / "Zotero" / "Zotero" / "zotero.sqlite")
    return next((path for path in candidates if path.exists()), None)


class ZoteroLibrary:
    def __init__(self, path: Path):
        self.path = path

    def missing_pdfs(self, limit: int | None = None) -> list[dict[str, str | None]]:
        query = """
        SELECT items.key AS itemKey,
          (SELECT idv.value FROM itemDataValues idv JOIN itemData d ON idv.valueID=d.valueID
           WHERE d.itemID=items.itemID AND d.fieldID=(SELECT fieldID FROM fields WHERE fieldName='title')) AS title,
          (SELECT idv.value FROM itemDataValues idv JOIN itemData d ON idv.valueID=d.valueID
           WHERE d.itemID=items.itemID AND d.fieldID=(SELECT fieldID FROM fields WHERE fieldName='DOI')) AS DOI,
          (SELECT SUBSTR(idv.value,1,4) FROM itemDataValues idv JOIN itemData d ON idv.valueID=d.valueID
           WHERE d.itemID=items.itemID AND d.fieldID=(SELECT fieldID FROM fields WHERE fieldName='date')) AS year,
          (SELECT c.lastName FROM creators c JOIN itemCreators ic ON c.creatorID=ic.creatorID
           WHERE ic.itemID=items.itemID AND ic.creatorTypeID=(SELECT creatorTypeID FROM creatorTypes WHERE creatorType='author')
           ORDER BY ic.orderIndex LIMIT 1) AS author
        FROM items
        WHERE items.itemTypeID NOT IN (SELECT itemTypeID FROM itemTypes WHERE typeName IN ('note','attachment'))
          AND items.itemID NOT IN (SELECT itemID FROM deletedItems)
          AND items.itemID NOT IN (
            SELECT ia.parentItemID FROM itemAttachments ia JOIN items a ON ia.itemID=a.itemID
            WHERE ia.contentType LIKE '%pdf%' AND ia.parentItemID IS NOT NULL
              AND a.itemID NOT IN (SELECT itemID FROM deletedItems))
        ORDER BY items.dateAdded DESC
        """
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query).fetchmany(limit) if limit else connection.execute(query).fetchall()
        return [
            {"key": row["itemKey"], "title": row["title"], "doi": row["DOI"],
             "author": row["author"], "year": row["year"]}
            for row in rows if row["title"]
        ]
