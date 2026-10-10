"""Statistiques, planchers d'enchère et rotation des capitaines."""

GRILLE_PLANCHERS = [
    (0.25, 20),   # top 25 %
    (0.50, 15),
    (0.75, 10),
    (1.00, 5),
]
PLANCHER_NOUVEAU = 10
SEANCES_FENETRE = 3


def fiche(con, fighter_id):
    """Stats complètes d'un combattant."""
    r = con.execute(
        """SELECT
             COUNT(*)                                            AS assauts,
             SUM(CASE WHEN a.vainqueur = e.equipe THEN 1 ELSE 0 END) AS victoires,
             SUM(e.survecu)                                      AS survies,
             COUNT(DISTINCT a.session_id)                        AS seances
           FROM engagements e
           JOIN assauts a ON a.id = e.assaut_id
           WHERE e.fighter_id = ?""",
        (fighter_id,),
    ).fetchone()
    assauts = r["assauts"] or 0
    victoires = r["victoires"] or 0
    prix = con.execute(
        "SELECT AVG(prix) AS m, MAX(prix) AS x FROM participations WHERE fighter_id = ? AND prix IS NOT NULL",
        (fighter_id,),
    ).fetchone()
    return {
        "assauts": assauts,
        "victoires": victoires,
        "survies": r["survies"] or 0,
        "seances": r["seances"] or 0,
        "ratio": victoires / assauts if assauts else None,
        "prix_moyen": prix["m"],
        "prix_max": prix["x"],
    }


def _dernieres_seances(con, fighter_id, n=SEANCES_FENETRE):
    return [
        row["session_id"]
        for row in con.execute(
            """SELECT DISTINCT a.session_id
               FROM engagements e JOIN assauts a ON a.id = e.assaut_id
               WHERE e.fighter_id = ?
               ORDER BY a.session_id DESC LIMIT ?""",
            (fighter_id, n),
        )
    ]


def ratio_recent(con, fighter_id, n=SEANCES_FENETRE):
    """Taux de victoire sur les n dernières séances JOUÉES (peu importe quand).

    C'est le choix qui rend le système insensible à l'assiduité : celui qui
    rate un mois est tarifé sur son niveau réel, pas sur une dette historique.
    """
    sids = _dernieres_seances(con, fighter_id, n)
    if not sids:
        return None, 0
    ph = ",".join("?" * len(sids))
    r = con.execute(
        f"""SELECT COUNT(*) AS n,
                   SUM(CASE WHEN a.vainqueur = e.equipe THEN 1 ELSE 0 END) AS v
            FROM engagements e JOIN assauts a ON a.id = e.assaut_id
            WHERE e.fighter_id = ? AND a.session_id IN ({ph})""",
        (fighter_id, *sids),
    ).fetchone()
    return (r["v"] / r["n"] if r["n"] else None), len(sids)


def classement(con, ids=None):
    """Classe des combattants par ratio récent. ids = présents ce soir."""
    if ids is None:
        ids = [r["id"] for r in con.execute("SELECT id FROM fighters WHERE actif = 1")]
    lignes = []
    for fid in ids:
        ratio, nb = ratio_recent(con, fid)
        nom = con.execute("SELECT name FROM fighters WHERE id = ?", (fid,)).fetchone()["name"]
        lignes.append({"id": fid, "nom": nom, "ratio": ratio, "seances": nb})
    lignes.sort(key=lambda x: (x["ratio"] is None, -(x["ratio"] or 0), x["nom"]))
    return lignes


def planchers(con, ids):
    """Grille FIXE recalculée chaque semaine : masse totale constante,
    donc inflation mathématiquement impossible."""
    cl = classement(con, ids)
    classes = [l for l in cl if l["seances"] >= SEANCES_FENETRE]
    novices = [l for l in cl if l["seances"] < SEANCES_FENETRE]

    out = {}
    total = len(classes)
    for i, l in enumerate(classes):
        q = (i + 1) / total if total else 1.0
        for seuil, val in GRILLE_PLANCHERS:
            if q <= seuil:
                out[l["id"]] = val
                break
    for l in novices:
        out[l["id"]] = PLANCHER_NOUVEAU
    return out


def rotation_capitaines(con, ids, n=2):
    """Les présents qui n'ont pas capitainé depuis le plus longtemps."""
    lignes = []
    for fid in ids:
        r = con.execute(
            """SELECT MAX(session_id) AS dernier FROM participations
               WHERE fighter_id = ? AND role = 'capitaine'""",
            (fid,),
        ).fetchone()
        nom = con.execute("SELECT name FROM fighters WHERE id = ?", (fid,)).fetchone()["name"]
        lignes.append({"id": fid, "nom": nom, "dernier": r["dernier"] or 0})
    lignes.sort(key=lambda x: (x["dernier"], x["nom"]))
    return lignes[:n]


def rapport_qualite_prix(con, session_id):
    """Victoires par pièce dépensée — l'histoire de la soirée."""
    rows = con.execute(
        """SELECT f.name, p.prix,
                  COUNT(e.assaut_id) AS assauts,
                  SUM(CASE WHEN a.vainqueur = e.equipe THEN 1 ELSE 0 END) AS victoires
           FROM participations p
           JOIN fighters f ON f.id = p.fighter_id
           LEFT JOIN engagements e ON e.fighter_id = p.fighter_id
           LEFT JOIN assauts a ON a.id = e.assaut_id AND a.session_id = p.session_id
           WHERE p.session_id = ? AND p.prix IS NOT NULL AND p.prix > 0
           GROUP BY p.fighter_id
           ORDER BY (CAST(SUM(CASE WHEN a.vainqueur = e.equipe THEN 1 ELSE 0 END) AS REAL)
                     / p.prix) DESC""",
        (session_id,),
    ).fetchall()
    return rows


def bilan_session(con, session_id):
    a = con.execute(
        """SELECT
             SUM(vainqueur = 'A') AS a, SUM(vainqueur = 'B') AS b,
             SUM(vainqueur = 'nul') AS n, COUNT(*) AS total
           FROM assauts WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    detail = con.execute(
        """SELECT f.name, p.equipe, p.role, p.prix, p.loadout,
                  COUNT(e.assaut_id) AS assauts,
                  SUM(CASE WHEN a.vainqueur = e.equipe THEN 1 ELSE 0 END) AS victoires,
                  SUM(e.survecu) AS survies
           FROM participations p
           JOIN fighters f ON f.id = p.fighter_id
           LEFT JOIN engagements e ON e.fighter_id = p.fighter_id
           LEFT JOIN assauts a ON a.id = e.assaut_id AND a.session_id = p.session_id
           WHERE p.session_id = ?
           GROUP BY p.fighter_id
           ORDER BY p.equipe, victoires DESC""",
        (session_id,),
    ).fetchall()
    return a, detail
