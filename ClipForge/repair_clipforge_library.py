"""Repair ClipForge source/clip paths after moving its data folder.
Place this file next to app.py, close ClipForge, and run with its .venv Python.
"""
from pathlib import Path
import sqlite3
from datetime import datetime
import sys

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DB = DATA / 'library.sqlite3'
DRY_RUN = '--dry-run' in sys.argv


def main():
    print('ClipForge library path repair')
    print('Installation:', ROOT)
    if not DB.is_file():
        print('ERROR: Database not found:', DB)
        return 1
    if not (DATA / 'media').is_dir() or not (DATA / 'clips').is_dir():
        print('ERROR: Expected data/media and data/clips alongside the database.')
        return 1

    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        for table in ('sources', 'clips'):
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                print('ERROR: Missing table', table)
                return 1
        updates = []
        missing = []
        already = 0
        for table, folder in (('sources', 'media'), ('clips', 'clips')):
            for record in db.execute(f'SELECT id, path FROM {table}').fetchall():
                old = record['path'] or ''
                if old and Path(old).is_file():
                    already += 1
                    continue
                # Match exact stored filename only; never guess a different recording.
                filename = old.replace('\\', '/').rsplit('/', 1)[-1]
                if not filename or filename in ('.', '..'):
                    missing.append((table, record['id'], filename))
                    continue
                new = DATA / folder / filename
                if new.is_file():
                    updates.append((table, record['id'], old, str(new.resolve())))
                else:
                    missing.append((table, record['id'], filename))

        print(f'Already accessible: {already}; repairable: {len(updates)}; unresolved: {len(missing)}')
        for table, _, old, new in updates[:8]:
            print(f'  {table}: {old} -> {new}')
        if len(updates) > 8:
            print(f'  ...and {len(updates) - 8} more')
        for table, rid, filename in missing[:12]:
            print(f'  MISSING {table} id={rid}: {filename}')
        if len(missing) > 12:
            print(f'  ...and {len(missing) - 12} more unresolved')
        if DRY_RUN:
            print('Dry run: no database changes made.')
            return 0
        if not updates:
            print('No paths changed.')
            return 0
        backup = DATA / ('library_before_path_repair_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.sqlite3')
        with sqlite3.connect(backup) as dest:
            db.backup(dest)
        print('Database backup:', backup)
        try:
            with db:
                for table, rid, old, new in updates:
                    db.execute(f'UPDATE {table} SET path=? WHERE id=? AND path=?', (new, rid, old))
        except Exception:
            print('ERROR: Repair failed; database transaction rolled back. Backup preserved.')
            raise
        print(f'Success: repaired {len(updates)} paths. Unresolved entries were not changed.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (sqlite3.Error, OSError) as exc:
        print('ERROR:', exc)
        raise SystemExit(1)
