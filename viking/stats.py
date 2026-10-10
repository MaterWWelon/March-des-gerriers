"""Statistiques, planchers d'enchère et rotation des capitaines."""

# Grille des planchers, appliquée par quartile À L'INTÉRIEUR DU VIVIER.
# Calibrée par simulation : les quartiles calculés sur tous les présents
# concentraient les 8 vendus dans le haut de la grille et absorbaient 54 %
# du budget avant la première surenchère. Ici on tombe à 25 %.
GRILLE_PLANCHERS = [
    (0.25, 15),   # top 25 % du vivier
    (0.50, 10),
    (0.75, 5),
    (1.00, 5),
]
PLANCHER_NOUVEAU = 10
# Deux séances suffisent pour classer quelqu'un. À trois, un membre qui vient
# une semaine sur trois attendait dix semaines avant d'exister dans le système ;
# à deux, sept. Avec un effectif qui tourne, c'est ce réglage qui décide
# combien de présents sont réellement classables chaque soir (13 contre 9).
SEANCES_FENETRE = 2
TAILLE_VIVIER = 8
# En dessous de quatre classés dans le vivier, les quartiles n'ont plus de sens
# (un seul classé tomberait seul dans le dernier quartile, donc au plancher le
# plus bas, moins cher qu'un inconnu). On met alors tout le monde à plat.
MIN_CLASSES = 4


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


def vivier(con, ids, taille=TAILLE_VIVIER):
    """Les mieux classés parmi les présents : ce sont eux qu'on met aux enchères."""
    return [l["id"] for l in classement(con, ids)[:taille]]


def planchers(con, ids, vivier_ids=None):
    """Grille FIXE recalculée chaque séance : masse totale constante,
    donc inflation mathématiquement impossible.

    Les quartiles s'appliquent AU VIVIER, pas à tous les présents : les 8 mis
    en vente sont déjà les mieux classés, les tarifer sur le classement global
    les collerait tous dans le haut de la grille.
    """
    if vivier_ids is None:
        vivier_ids = vivier(con, ids)
    cl = [l for l in classement(con, ids) if l["id"] in set(vivier_ids)]
    classes = [l for l in cl if l["seances"] >= SEANCES_FENETRE]
    novices = [l for l in cl if l["seances"] < SEANCES_FENETRE]

    out = {}
    if len(classes) < MIN_CLASSES:
        return {l["id"]: PLANCHER_NOUVEAU for l in cl}
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
