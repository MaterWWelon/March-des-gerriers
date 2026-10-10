"""Produit le fichier d'historique que la console du téléphone sait lire.

    python3 -m viking.ligue            # affiche le texte à copier
    python3 -m viking.ligue ligue.json # l'écrit aussi dans un fichier

Python connaît l'historique, pas qui sera présent ce soir. On lui envoie donc
la forme de chacun, et la console applique les règles (vivier, planchers,
capitaines) à l'effectif réellement là.

Le fichier contient les noms des membres : il ne doit JAMAIS être poussé sur
un dépôt public. Il est couvert par le .gitignore (*.json).
"""

import json
import sys
from datetime import date

from . import db, stats


def paquet(con):
    membres = []
    for f in db.roster(con):
        ratio, nb = stats.ratio_recent(con, f["id"])
        dernier = con.execute(
            """SELECT MAX(session_id) AS d FROM participations
               WHERE fighter_id = ? AND role = 'capitaine'""",
            (f["id"],),
        ).fetchone()["d"] or 0
        membres.append({
            "nom": f["name"],
            "ratio": round(ratio, 4) if ratio is not None else None,
            "seances": nb,
            "cap": dernier,
        })
    membres.sort(key=lambda m: (m["ratio"] is None, -(m["ratio"] or 0), m["nom"]))
    return {
        "v": 1,
        "genere": date.today().isoformat(),
        "fenetre": stats.SEANCES_FENETRE,
        "membres": membres,
    }


def main():
    con = db.connect()
    p = paquet(con)
    texte = json.dumps(p, ensure_ascii=False, separators=(",", ":"))

    if len(sys.argv) > 1:
        from pathlib import Path
        Path(sys.argv[1]).write_text(texte, encoding="utf-8")
        print(f"  écrit dans {sys.argv[1]} ({len(texte)} octets)\n")

    prets = sum(1 for m in p["membres"] if m["seances"] >= p["fenetre"])
    print(f"  {len(p['membres'])} membres, {prets} avec assez d'historique "
          f"pour un plancher calculé\n")
    print("  À COLLER DANS LA CONSOLE (écran du roster, bouton « Ligue ») :\n")
    print(texte)


if __name__ == "__main__":
    main()
