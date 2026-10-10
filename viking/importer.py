"""Ingère l'export JSON du téléphone dans la base de la ligue.

    python3 -m viking.importer seance-2026-10-11.json [ligue.db]

Idempotent : relancer le même fichier ne crée pas de doublon.
Les noms sont appariés sur le roster existant ; les inconnus sont créés.
"""

import json
import sys
from pathlib import Path

from . import db, noms, stats


def apparier(con, roster_json):
    """nom du téléphone -> fighter_id en base. Crée ce qui manque."""
    existants = db.roster(con, actifs_only=False)
    table = {}
    crees = []
    for p in roster_json:
        m, _ = noms.resoudre(p["nom"], existants)
        if m and noms.normaliser(m["name"]) == noms.normaliser(p["nom"]):
            table[p["id"]] = m["id"]
        else:
            fid = db.ajouter_combattant(con, p["nom"])
            table[p["id"]] = fid
            crees.append(p["nom"])
            existants = db.roster(con, actifs_only=False)
    return table, crees


def importer(chemin, base=None):
    data = json.loads(Path(chemin).read_text(encoding="utf-8"))
    con = db.connect(base)

    jour = data.get("debut", "")[:10] or None
    deja = con.execute(
        "SELECT id FROM sessions WHERE date = ? AND close = 1", (jour,)
    ).fetchone()
    if deja:
        n = con.execute(
            "SELECT COUNT(*) c FROM assauts WHERE session_id = ?", (deja["id"],)
        ).fetchone()["c"]
        if n == len(data["assauts"]):
            print(f"  séance du {jour} déjà importée ({n} assauts) — rien à faire")
            return con, deja["id"]
        print(f"  ! une séance du {jour} existe ({n} assauts), import quand même")

    table, crees = apparier(con, data["roster"])
    for c in crees:
        print(f"  + nouveau au roster : {c}")

    sid = db.creer_session(
        con, terrain=data.get("terrain", 6), budget=data.get("budget", 140), jour=jour
    )

    for tel_id_s, equipe in data["equipes"].items():
        tel_id = int(tel_id_s)
        if tel_id not in table:
            continue
        db.inscrire(
            con, sid, table[tel_id], equipe,
            data["roles"].get(tel_id_s, "tirage"),
            data["prix"].get(tel_id_s),
            data["loadouts"].get(tel_id_s),
        )

    for a in data["assauts"]:
        compo = {table[int(k)]: v for k, v in a["compo"].items() if int(k) in table}
        surv = {table[i] for i in a["surv"] if i in table}
        db.enregistrer_assaut(con, sid, a["n"], a["v"], compo, surv)

    con.execute("UPDATE sessions SET close = 1 WHERE id = ?", (sid,))
    db.log(con, sid, "import", Path(chemin).name)
    con.commit()

    a, _ = stats.bilan_session(con, sid)
    print(f"  ✓ séance {sid} du {jour} — A {a['a']} — {a['b']} B sur {a['total']} assauts")
    return con, sid


def prochaine_seance(con):
    """Ce qu'il faut savoir avant la semaine suivante."""
    actifs = [r["id"] for r in db.roster(con)]
    print("\n  PLANCHERS (si tout le monde est là)")
    pl = stats.planchers(con, actifs)
    for l in stats.classement(con, actifs):
        r = f"{l['ratio']:.0%}" if l["ratio"] is not None else "nouveau"
        print(f"    {l['nom']:<24} {pl[l['id']]:>3}   {r}")
    print("\n  CAPITAINES (rotation)")
    for c in stats.rotation_capitaines(con, actifs, 4):
        print(f"    {c['nom']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    con, _ = importer(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    prochaine_seance(con)


if __name__ == "__main__":
    main()
