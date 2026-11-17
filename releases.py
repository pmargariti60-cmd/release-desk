"""SQLite persistence and release-note workflow."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


class WorkflowError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    project TEXT NOT NULL,
    body TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('draft','review','approved')),
    version INTEGER NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL REFERENCES releases(id),
    version INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT NOT NULL,
    happened TEXT NOT NULL,
    UNIQUE (release_id, version)
);
"""


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def field(data, key, limit, default=""):
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise WorkflowError(f"{key.capitalize()} must contain 1–{limit} characters.", 400)
    return value.strip()


def content(data):
    title = field(data, "title", 100)
    project = field(data, "project", 60)
    if any(not value.isprintable() for value in (title, project)):
        raise WorkflowError("Title and project must each fit on one line.", 400)
    return title, project, field(data, "body", 6000)


class Store:
    def __init__(self, path):
        self.path = path
        db = sqlite3.connect(self.path)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        finally:
            db.close()

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def record(db, release_id, version, action, actor, note, now):
        db.execute(
            "INSERT INTO history(release_id,version,action,actor,note,happened) VALUES(?,?,?,?,?,?)",
            (release_id, version, action, actor, note, now),
        )

    @staticmethod
    def read(db, release_id):
        row = db.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if row is None:
            raise WorkflowError("Release note not found.", 404)
        return dict(row)

    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,title,project,state,version,updated FROM releases ORDER BY id DESC"
            )]

    def get(self, release_id):
        with self.connect() as db:
            release = self.read(db, release_id)
            release["history"] = [dict(row) for row in db.execute(
                "SELECT version,action,actor,note,happened FROM history "
                "WHERE release_id=? ORDER BY version DESC", (release_id,)
            )]
            return release

    def create(self, data):
        title, project, body = content(data)
        now = timestamp()
        with self.connect(write=True) as db:
            release_id = db.execute(
                "INSERT INTO releases(title,project,body,state,version,updated) VALUES(?,?,?,'draft',1,?)",
                (title, project, body, now),
            ).lastrowid
            self.record(db, release_id, 1, "created", "Developer", "", now)
            return self.read(db, release_id)

    def change(self, release_id, data):
        action = data.get("action")
        if not isinstance(action, str) or action not in ("edit", "submit", "return", "approve", "reopen"):
            raise WorkflowError("Choose a valid workflow action.", 400)
        version = data.get("version")
        if type(version) is not int or version < 1:
            raise WorkflowError("A valid version is required.", 400)

        with self.connect(write=True) as db:
            current = self.read(db, release_id)
            if version != current["version"]:
                raise WorkflowError("This note changed. Reload it before trying again.")
            before, after, actor = {
                "edit": ("draft", "draft", "Developer"),
                "submit": ("draft", "review", "Developer"),
                "return": ("review", "draft", "Product"),
                "approve": ("review", "approved", "Product"),
                "reopen": ("approved", "draft", "Product"),
            }[action]
            if current["state"] != before:
                raise WorkflowError("That action is unavailable in the current state.")
            note = field(data, "note", 1000) if action in ("return", "reopen") else ""
            title, project, body = (
                content(data) if action == "edit" else
                (current["title"], current["project"], current["body"])
            )
            now = timestamp()
            db.execute(
                "UPDATE releases SET title=?,project=?,body=?,state=?,version=?,updated=? WHERE id=?",
                (title, project, body, after, version + 1, now, release_id),
            )
            self.record(db, release_id, version + 1, action, actor, note, now)
            return self.read(db, release_id)

    def export(self, release_id):
        release = self.get(release_id)
        if release["state"] != "approved":
            raise WorkflowError("Product approval is required before export.")
        return f"# {release['title']}\n\n{release['project']}\n\n{release['body']}\n"
