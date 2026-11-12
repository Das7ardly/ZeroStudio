"""Finished jobs log in SQLite."""
import sqlite3
import time

from .paths import data_dir


class History:
    def __init__(self, path=None):
        self.db = sqlite3.connect(str(path or data_dir() / "history.db"))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT,"
            " output TEXT, status TEXT, message TEXT, finished REAL)")
        for col in ("log TEXT", "command TEXT"):
            try:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        self.db.commit()

    def add(self, kind, title, output, status, message, log="", command=""):
        self.db.execute(
            "INSERT INTO jobs(kind,title,output,status,message,finished,log,command) VALUES (?,?,?,?,?,?,?,?)",
            (kind, title, output, status, message, time.time(), log, command))
        self.db.commit()

    def rows(self, limit=1000):
        cur = self.db.execute(
            "SELECT id,kind,title,output,status,message,finished,log,command FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,))
        keys = ("id", "kind", "title", "output", "status", "message", "finished", "log", "command")
        return [dict(zip(keys, r)) for r in cur.fetchall()]

    def clear(self):
        self.db.execute("DELETE FROM jobs")
        self.db.commit()
