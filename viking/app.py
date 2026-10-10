"""Le Marché aux Guerriers — console de séance.

Saisie sur place : on ne saisit JAMAIS la composition du terrain.
Elle est déduite :  terrain(n+1) = terrain(n) − morts(n) + entrants(n+1)
"""

import sys
from . import db, noms, stats

LOADOUTS = {
    "eb": "épée + bouclier",
    "hb": "hache 1M + bouclier",
    "h2": "hache 2M (danoise)",
    "lb": "lance + bouclier",
    "l2": "lance 2M",
}


class Console:
    def __init__(self, chemin=None):
        self.con = db.connect(chemin)
        self.session = db.session_courante(self.con)
        self.terrain = {}      # fighter_id -> 'A'|'B' : qui est sur le terrain
        self.compteur = {}     # fighter_id -> nb d'assauts joués
        self._recharger_terrain()

    # ------------------------------------------------------------ outils

    def presents(self):
        if not self.session:
            return []
        return db.effectif(self.con, self.session["id"])

    def resoudre(self, saisie, pool=None):
        pool = pool if pool is not None else self.presents()
        m, alts = noms.resoudre(saisie, pool)
        if m:
            return m
        if not alts:
            print(f"  ✗ inconnu : {saisie}")
            return None
        print(f"  ? {saisie} → ambigu :")
        for i, a in enumerate(alts, 1):
            print(f"      {i}. {a['name']}")
        c = input("    numéro > ").strip()
        if c.isdigit() and 1 <= int(c) <= len(alts):
            return alts[int(c) - 1]
        return None

    def lire_liste(self, invite, pool=None):
        """Lit plusieurs noms séparés par des espaces ou des virgules."""
        brut = input(invite).replace(",", " ").split()
        out = []
        for mot in brut:
            r = self.resoudre(mot, pool)
            if r:
                out.append(r)
        return out

    def _recharger_terrain(self):
        """Reconstruit l'état du terrain depuis le dernier assaut enregistré."""
        self.terrain, self.compteur = {}, {}
        if not self.session:
            return
        for a in db.assauts(self.con, self.session["id"]):
            for e in self.con.execute(
                "SELECT * FROM engagements WHERE assaut_id = ?", (a["id"],)
            ):
                self.compteur[e["fighter_id"]] = self.compteur.get(e["fighter_id"], 0) + 1
        dernier = self.con.execute(
            "SELECT id FROM assauts WHERE session_id = ? ORDER BY numero DESC LIMIT 1",
            (self.session["id"],),
        ).fetchone()
        if dernier:
            for e in self.con.execute(
                "SELECT * FROM engagements WHERE assaut_id = ? AND survecu = 1",
                (dernier["id"],),
            ):
                self.terrain[e["fighter_id"]] = e["equipe"]

    def nom(self, fid):
        return self.con.execute(
            "SELECT name FROM fighters WHERE id = ?", (fid,)
        ).fetchone()["name"]

    def banc(self, equipe):
        return [
            p for p in db.effectif(self.con, self.session["id"], equipe)
            if p["fighter_id"] not in self.terrain
        ]

    # ------------------------------------------------------------ roster

    def cmd_ajouter(self, arg):
        if not arg:
            arg = input("  nom > ").strip()
        if not arg:
            return
        try:
            fid = db.ajouter_combattant(self.con, arg)
            print(f"  ✓ {arg} ajouté au roster (#{fid})")
        except Exception as e:
            print(f"  ✗ {e}")

    def cmd_roster(self, arg):
        rows = db.roster(self.con)
        if not rows:
            print("  roster vide — 'ajouter <nom>'")
            return
        courts = noms.raccourcis(rows)
        print(f"  {len(rows)} combattants :")
        for r in rows:
            f = stats.fiche(self.con, r["id"])
            ratio = f"{f['ratio']:.0%}" if f["ratio"] is not None else "  —"
            print(f"    {r['name']:<22} ({courts[r['id']]:<5}) "
                  f"{f['seances']:>3} séances  {f['assauts']:>3} assauts  {ratio:>5} victoires")

    # ------------------------------------------------------------ séance

    def cmd_seance(self, arg):
        if self.session:
            print(f"  séance {self.session['id']} déjà ouverte")
            return
        t = input("  terrain (5 ou 6) [6] > ").strip() or "6"
        b = input("  budget par capitaine [140] > ").strip() or "140"
        sid = db.creer_session(self.con, terrain=int(t), budget=int(b))
        self.session = db.session_courante(self.con)
        print(f"  ✓ séance {sid} ouverte — {t}v{t}, budget {b}")

    def cmd_presents(self, arg):
        """Coche les présents et propose planchers + capitaines."""
        if not self._verif_session():
            return
        print("  Tape les présents (préfixes, séparés par des espaces).")
        print("  Ligne vide pour terminer.")
        ids = []
        while True:
            ligne = input("  > ").strip()
            if not ligne:
                break
            for mot in ligne.replace(",", " ").split():
                r = self.resoudre(mot, db.roster(self.con))
                if r and r["id"] not in ids:
                    ids.append(r["id"])
                    print(f"    + {r['name']}")
        if not ids:
            return
        n = len(ids)
        print(f"\n  {n} présents → terrain {'6v6' if n >= 20 else '5v5'}, "
              f"équipes de {(n)//2}")
        print("\n  Planchers d'enchère :")
        pl = stats.planchers(self.con, ids)
        for l in stats.classement(self.con, ids):
            r = f"{l['ratio']:.0%}" if l["ratio"] is not None else "nouveau"
            print(f"    {l['nom']:<22} {pl[l['id']]:>3}   ({r})")
        print("\n  Capitaines proposés (rotation) :")
        for c in stats.rotation_capitaines(self.con, ids, 2):
            print(f"    → {c['nom']}")
        self._presents_ids = ids

    def cmd_equipe(self, arg):
        """equipe A|B <role> <nom> [prix] — inscrit quelqu'un dans une équipe."""
        if not self._verif_session():
            return
        p = arg.split()
        if len(p) < 3:
            print("  usage: equipe A capitaine kev")
            print("         equipe B achat bru 45")
            return
        eq, role, cible = p[0].upper(), p[1].lower(), p[2]
        prix = int(p[3]) if len(p) > 3 and p[3].isdigit() else None
        roles = {"capitaine", "protege", "tirage", "achat"}
        if eq not in ("A", "B") or role not in roles:
            print(f"  ✗ équipe A/B, rôle parmi {sorted(roles)}")
            return
        r = self.resoudre(cible, db.roster(self.con))
        if not r:
            return
        load = input(f"  loadout {list(LOADOUTS)} [entrée = aucun] > ").strip()
        db.inscrire(self.con, self.session["id"], r["id"], eq, role, prix,
                    LOADOUTS.get(load, load or None))
        print(f"  ✓ {r['name']} → équipe {eq} ({role}"
              + (f", {prix} pièces" if prix else "") + ")")

    def cmd_effectif(self, arg):
        if not self._verif_session():
            return
        for eq in ("A", "B"):
            rows = db.effectif(self.con, self.session["id"], eq)
            depense = sum(r["prix"] or 0 for r in rows)
            print(f"\n  ÉQUIPE {eq} — {len(rows)} joueurs, {depense} pièces dépensées")
            for r in rows:
                marque = "▶" if r["fighter_id"] in self.terrain else " "
                prix = f"{r['prix']:>3}p" if r["prix"] else "   -"
                print(f"   {marque} {r['name']:<22} {r['role']:<10} {prix}  "
                      f"{r['loadout'] or ''}")

    # ------------------------------------------------------------ combat

    def cmd_go(self, arg):
        """Le cœur : enregistre un assaut. Composition déduite."""
        if not self._verif_session():
            return
        n = self.terrain_size()
        numero = len(db.assauts(self.con, self.session["id"])) + 1

        print(f"\n  ── ASSAUT {numero} ──")
        # 1. compléter le terrain
        for eq in ("A", "B"):
            actuels = [f for f, e in self.terrain.items() if e == eq]
            manque = n - len(actuels)
            if actuels:
                print(f"  {eq} sur le terrain : "
                      + ", ".join(self.nom(f) for f in actuels))
            if manque <= 0:
                continue
            dispo = self.banc(eq)
            if not dispo:
                print(f"  ! banc {eq} vide")
                continue
            self._suggerer(dispo, manque, eq)
            entrants = self.lire_liste(f"  entrants {eq} ({manque}) > ", dispo)
            for e in entrants:
                self.terrain[e["fighter_id"]] = eq

        if not self.terrain:
            print("  ✗ terrain vide")
            return

        # 2. résultat
        surv = self.lire_liste("  survivants > ", 
                               [p for p in self.presents()
                                if p["fighter_id"] in self.terrain])
        v = input("  vainqueur (a/b/n) > ").strip().lower()
        vainqueur = {"a": "A", "b": "B", "n": "nul"}.get(v[:1] if v else "")
        if not vainqueur:
            print("  ✗ assaut annulé")
            return

        sids = {s["fighter_id"] for s in surv}
        db.enregistrer_assaut(self.con, self.session["id"], numero,
                              vainqueur, dict(self.terrain), sids)
        for f in self.terrain:
            self.compteur[f] = self.compteur.get(f, 0) + 1

        engages = len(self.terrain)
        self.terrain = {f: e for f, e in self.terrain.items() if f in sids}
        print(f"  ✓ assaut {numero} — vainqueur {vainqueur}, "
              f"{engages} engagés, {len(sids)} survivant(s)")
        self.cmd_score("")

    def _suggerer(self, dispo, combien, eq):
        """Propose les entrants : les moins joués d'abord (quota automatique)."""
        tri = sorted(dispo, key=lambda p: (self.compteur.get(p["fighter_id"], 0),
                                           p["name"]))
        apercu = ", ".join(
            f"{p['name']}({self.compteur.get(p['fighter_id'], 0)})" for p in tri[:combien + 3]
        )
        print(f"    banc {eq} par assauts joués : {apercu}")
        mini = min(self.compteur.get(p["fighter_id"], 0) for p in dispo)
        retard = [p["name"] for p in dispo if self.compteur.get(p["fighter_id"], 0) == mini]
        if mini == 0 and retard:
            print(f"    ⚠ pas encore joué : {', '.join(retard)}")

    def cmd_annuler(self, arg):
        if not self._verif_session():
            return
        n = db.supprimer_dernier_assaut(self.con, self.session["id"])
        if n:
            self._recharger_terrain()
            print(f"  ✓ assaut {n} supprimé — terrain restauré")
        else:
            print("  rien à annuler")

    def cmd_score(self, arg):
        if not self._verif_session():
            return
        a, _ = stats.bilan_session(self.con, self.session["id"])
        print(f"  SCORE  A {a['a'] or 0} — {a['b'] or 0} B"
              + (f"  ({a['n']} nul)" if a["n"] else "")
              + f"   [{a['total'] or 0} assauts]")

    def cmd_bilan(self, arg):
        if not self._verif_session():
            return
        a, detail = stats.bilan_session(self.con, self.session["id"])
        print(f"\n  ══ BILAN — {a['total'] or 0} assauts ══")
        print(f"  A {a['a'] or 0} — {a['b'] or 0} B\n")
        for eq in ("A", "B"):
            print(f"  ÉQUIPE {eq}")
            for d in detail:
                if d["equipe"] != eq:
                    continue
                ass = d["assauts"] or 0
                vic = d["victoires"] or 0
                r = f"{vic/ass:.0%}" if ass else "  —"
                print(f"    {d['name']:<22} {ass:>2} assauts  {vic:>2} vict ({r:>4})  "
                      f"{d['survies'] or 0:>2} survies"
                      + (f"  — payé {d['prix']}p" if d["prix"] else ""))
        rqp = stats.rapport_qualite_prix(self.con, self.session["id"])
        if rqp:
            print("\n  ★ MEILLEUR RAPPORT QUALITÉ-PRIX")
            for r in rqp[:3]:
                ratio = (r["victoires"] or 0) / r["prix"]
                print(f"    {r['name']:<22} {r['victoires'] or 0} victoires "
                      f"pour {r['prix']}p  ({ratio:.3f} v/p)")

    def cmd_cloturer(self, arg):
        if not self._verif_session():
            return
        self.cmd_bilan("")
        self.con.execute("UPDATE sessions SET close = 1 WHERE id = ?",
                         (self.session["id"],))
        self.con.commit()
        print(f"\n  ✓ séance {self.session['id']} clôturée")
        self.session = None
        self.terrain, self.compteur = {}, {}

    def cmd_fiche(self, arg):
        r = self.resoudre(arg or input("  qui > "), db.roster(self.con))
        if not r:
            return
        f = stats.fiche(self.con, r["id"])
        ratio, nb = stats.ratio_recent(self.con, r["id"])
        print(f"\n  {r['name']}")
        print(f"    {f['seances']} séances, {f['assauts']} assauts")
        print(f"    {f['victoires']} victoires"
              + (f" ({f['ratio']:.0%})" if f["ratio"] is not None else ""))
        print(f"    {f['survies']} survies")
        if ratio is not None:
            print(f"    forme récente ({nb} séances) : {ratio:.0%}")
        if f["prix_moyen"]:
            print(f"    prix moyen {f['prix_moyen']:.0f}p, record {f['prix_max']}p")

    def terrain_size(self):
        return self.session["terrain"] if self.session else 6

    def _verif_session(self):
        if not self.session:
            print("  ✗ pas de séance ouverte — 'seance'")
            return False
        return True

    # ------------------------------------------------------------ boucle

    COMMANDES = {
        "ajouter": "cmd_ajouter", "a": "cmd_ajouter",
        "roster": "cmd_roster", "r": "cmd_roster",
        "seance": "cmd_seance",
        "presents": "cmd_presents", "p": "cmd_presents",
        "equipe": "cmd_equipe", "e": "cmd_equipe",
        "effectif": "cmd_effectif", "f": "cmd_effectif",
        "go": "cmd_go", "g": "cmd_go", "": "cmd_go",
        "annuler": "cmd_annuler", "z": "cmd_annuler",
        "score": "cmd_score", "s": "cmd_score",
        "bilan": "cmd_bilan", "b": "cmd_bilan",
        "cloturer": "cmd_cloturer",
        "fiche": "cmd_fiche",
    }

    AIDE = """
  ENTRÉE / go      enregistrer un assaut  ← la commande principale
  z                annuler le dernier assaut
  s                score      b  bilan complet
  p                saisir les présents (+ planchers + capitaines)
  e A achat kev 45 inscrire dans une équipe
  f                afficher les effectifs
  a <nom>          ajouter au roster    r  voir le roster
  fiche <nom>      stats d'une personne
  seance           ouvrir une séance    cloturer  la fermer
  q                quitter
"""

    def run(self):
        print("\n  ⚔  LE MARCHÉ AUX GUERRIERS")
        if self.session:
            print(f"  séance {self.session['id']} en cours "
                  f"({self.session['terrain']}v{self.session['terrain']})")
        print(self.AIDE)
        while True:
            try:
                brut = input("⚔ > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if brut in ("q", "quit", "exit"):
                break
            if brut in ("?", "h", "aide"):
                print(self.AIDE)
                continue
            mot, _, reste = brut.partition(" ")
            meth = self.COMMANDES.get(mot.lower())
            if not meth:
                print("  ? commande inconnue — '?' pour l'aide")
                continue
            try:
                getattr(self, meth)(reste.strip())
            except Exception as e:
                print(f"  ✗ erreur : {e}")


def main():
    Console(sys.argv[1] if len(sys.argv) > 1 else None).run()


if __name__ == "__main__":
    main()
