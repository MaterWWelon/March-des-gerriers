"""Résolution de noms — le cœur ergonomique.

On tape 'kev', le système comprend Kévin. Insensible aux accents, à la casse,
et capable de matcher sur le prénom OU le nom de famille. Un numéro de dossard
tapé tel quel fonctionne aussi.
"""

import unicodedata


def normaliser(s):
    """Minuscules, sans accents, sans ponctuation."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() else " " for c in s).strip()


def _distance(a, b, maxi=2):
    """Levenshtein plafonné — rattrape les fautes de frappe."""
    if abs(len(a) - len(b)) > maxi:
        return maxi + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > maxi:
            return maxi + 1
        prev = cur
    return prev[-1]


def resoudre(saisie, candidats):
    """candidats : lignes avec .id, .name, .dossard (ou dicts).

    Retourne (match, alternatives) :
      - (row, [])        → résolution certaine
      - (None, [rows])   → ambigu, il faut choisir
      - (None, [])       → rien trouvé
    """
    saisie = saisie.strip()
    if not saisie:
        return None, []

    def champ(c, k):
        return c[k] if isinstance(c, dict) else c[k]

    # 1. Dossard exact
    if saisie.isdigit():
        n = int(saisie)
        exact = [c for c in candidats if champ(c, "dossard") == n]
        if len(exact) == 1:
            return exact[0], []

    q = normaliser(saisie)
    if not q:
        return None, []

    # 2. Nom complet exact
    exact = [c for c in candidats if normaliser(champ(c, "name")) == q]
    if len(exact) == 1:
        return exact[0], []

    # 3. Préfixe sur le nom entier ou sur n'importe quel mot du nom
    prefixe = []
    for c in candidats:
        n = normaliser(champ(c, "name"))
        if n.startswith(q) or any(m.startswith(q) for m in n.split()):
            prefixe.append(c)
    if len(prefixe) == 1:
        return prefixe[0], []
    if len(prefixe) > 1:
        return None, prefixe

    # 4. Sous-chaîne
    sous = [c for c in candidats if q in normaliser(champ(c, "name"))]
    if len(sous) == 1:
        return sous[0], []
    if len(sous) > 1:
        return None, sous

    # 5. Faute de frappe
    flous = []
    for c in candidats:
        for mot in normaliser(champ(c, "name")).split():
            if _distance(q, mot) <= (1 if len(q) <= 4 else 2):
                flous.append(c)
                break
    if len(flous) == 1:
        return flous[0], []
    return None, flous


def raccourcis(candidats):
    """Calcule pour chaque personne le préfixe le plus court qui l'identifie
    de façon unique. Sert à afficher 'Kévin (kev)' dans les listes."""
    noms = {champ_id(c): normaliser(nom_de(c)) for c in candidats}
    out = {}
    for fid, n in noms.items():
        for taille in range(1, max(len(n), 1) + 1):
            p = n[:taille]
            if sum(1 for m in noms.values() if m.startswith(p)) == 1:
                out[fid] = p
                break
        else:
            out[fid] = n
    return out


def champ_id(c):
    return c["id"]


def nom_de(c):
    return c["name"]
