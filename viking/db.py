"""Couche base de données — SQLite, un seul fichier, zéro dépendance."""

import sqlite3
from pathlib import Path
from datetime import date

DEFAULT_PATH = Path.home() / ".viking" / "ligue.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

-- Le roster permanent du club. On y écrit un nom UNE fois.
CREATE TABLE IF NOT EXISTS fighters (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    dossard INTEGER UNIQUE,          -- numéro fixe, optionnel
    actif   INTEGER NOT NULL DEFAULT 1,
    cree_le TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id       INTEGER PRIMARY KEY,
    date     TEXT NOT NULL,
    terrain  INTEGER NOT NULL DEFAULT 6,   -- 5v5 ou 6v6
    budget   INTEGER NOT NULL DEFAULT 140,
    close    INTEGER NOT NULL DEFAULT 0,
    notes    TEXT
);

-- Qui a participé à quelle séance, dans quelle équipe, à quel prix.
CREATE TABLE IF NOT EXISTS participations (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    fighter_id INTEGER NOT NULL REFERENCES fighters(id),
    equipe     TEXT NOT NULL CHECK (equipe IN ('A','B')),
    role       TEXT NOT NULL CHECK (role IN ('capitaine','protege','tirage','achat')),
    prix       INTEGER,                     -- NULL sauf pour les achats
    loadout    TEXT,
    PRIMARY KEY (session_id, fighter_id)
);

CREATE TABLE IF NOT EXISTS assauts (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    numero     INTEGER NOT NULL,
    vainqueur  TEXT CHECK (vainqueur IN ('A','B','nul')),
    horodatage TEXT,
    UNIQUE (session_id, numero)
);

-- LA table centrale : une ligne = une personne engagée dans un assaut.
-- C'est elle qui permet "victoires pendant que tu étais sur le terrain".
CREATE TABLE IF NOT EXISTS engagements (
    assaut_id  INTEGER NOT NULL REFERENCES assauts(id) ON DELETE CASCADE,
    fighter_id INTEGER NOT NULL REFERENCES fighters(id),
    equipe     TEXT NOT NULL CHECK (equipe IN ('A','B')),
    survecu    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (assaut_id, fighter_id)
);

CREATE INDEX IF NOT EXISTS idx_eng_fighter ON engagements(fighter_id);
CREATE INDEX IF NOT EXISTS idx_part_fighter ON participations(fighter_id);

-- Journal brut de toutes les saisies : permet d'annuler et d'auditer.
CREATE TABLE IF NOT EXISTS journal (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER,
    horodatage TEXT NOT NULL,
    action     TEXT NOT NULL,
    payload    TEXT
);
"""


def connect(path=None):
    path = Path(path) if path else DEFAULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# ---------------------------------------------------------------- roster

def ajouter_combattant(con, nom, dossard=None):
    cur = con.execute(
        "INSERT INTO fighters (name, dossard, cree_le) VALUES (?,?,?)",
        (nom.strip(), dossard, date.today().isoformat()),
    )
    con.commit()
    return cur.lastrowid


def roster(con, actifs_only=True):
    q = "SELECT * FROM fighters"
    if actifs_only:
        q += " WHERE actif = 1"
    return con.execute(q + " ORDER BY name").fetchall()


def desactiver(con, fighter_id):
    con.execute("UPDATE fighters SET actif = 0 WHERE id = ?", (fighter_id,))
    con.commit()


# ---------------------------------------------------------------- séances

def creer_session(con, terrain=6, budget=140, jour=None):
    cur = con.execute(
        "INSERT INTO sessions (date, terrain, budget) VALUES (?,?,?)",
        (jour or date.today().isoformat(), terrain, budget),
    )
    con.commit()
    return cur.lastrowid


def session_courante(con):
    return con.execute(
        "SELECT * FROM sessions WHERE close = 0 ORDER BY id DESC LIMIT 1"
    ).fetchone()


def inscrire(con, session_id, fighter_id, equipe, role, prix=None, loadout=None):
    con.execute(
        """INSERT OR REPLACE INTO participations
           (session_id, fighter_id, equipe, role, prix, loadout)
           VALUES (?,?,?,?,?,?)""",
        (session_id, fighter_id, equipe, role, prix, loadout),
    )
    con.commit()


def effectif(con, session_id, equipe=None):
    q = """SELECT p.*, f.name, f.dossard FROM participations p
           JOIN fighters f ON f.id = p.fighter_id
           WHERE p.session_id = ?"""
    args = [session_id]
    if equipe:
        q += " AND p.equipe = ?"
        args.append(equipe)
    return con.execute(q + " ORDER BY f.name", args).fetchall()


# ---------------------------------------------------------------- assauts

def enregistrer_assaut(con, session_id, numero, vainqueur, compo, survivants):
    """compo : {fighter_id: 'A'|'B'} — la composition complète du terrain.
    survivants : set d'ids."""
    from datetime import datetime

    cur = con.execute(
        "INSERT INTO assauts (session_id, numero, vainqueur, horodatage) VALUES (?,?,?,?)",
        (session_id, numero, vainqueur, datetime.now().isoformat(timespec="seconds")),
    )
    aid = cur.lastrowid
    con.executemany(
        "INSERT INTO engagements (assaut_id, fighter_id, equipe, survecu) VALUES (?,?,?,?)",
        [(aid, fid, eq, 1 if fid in survivants else 0) for fid, eq in compo.items()],
    )
    con.commit()
    return aid


def supprimer_dernier_assaut(con, session_id):
    row = con.execute(
        "SELECT id, numero FROM assauts WHERE session_id = ? ORDER BY numero DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        return None
    con.execute("DELETE FROM assauts WHERE id = ?", (row["id"],))
    con.commit()
    return row["numero"]


def assauts(con, session_id):
    return con.execute(
        "SELECT * FROM assauts WHERE session_id = ? ORDER BY numero", (session_id,)
    ).fetchall()


def log(con, session_id, action, payload=""):
    from datetime import datetime

    con.execute(
        "INSERT INTO journal (session_id, horodatage, action, payload) VALUES (?,?,?,?)",
        (session_id, datetime.now().isoformat(timespec="seconds"), action, str(payload)),
    )
    con.commit()
