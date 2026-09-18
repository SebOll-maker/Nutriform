# -*- coding: utf-8 -*-
"""
Cloisonnement entre comptes — la suite la plus importante du dépôt.

    python tests/test_cloisonnement.py

L'application est partagée entre proches qui ne vivent pas sous le même toit.
Chacun doit voir ses données, RIEN QUE ses données, et l'administrateur ne doit
pas faire exception. Ces tests vérifient cette promesse à trois niveaux :

  1. les modules (planning, journal, courses, réglages) ;
  2. les routes HTTP, y compris en trichant sur les identifiants d'URL ;
  3. les signatures, pour qu'un futur oubli de `personne_id` soit impossible.

Base SQLite et dossier de recettes TEMPORAIRES : rien ne touche aux vraies
données.
"""
import inspect
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

# NF_DB avant tout import de db (le chemin est lu à l'import).
BASE = Path(tempfile.mkdtemp(prefix="nf-cloison-")) / "t.db"
os.environ["NF_DB"] = str(BASE)
os.environ.pop("NF_PERSONNE_DEFAUT", None)   # on veut la vraie connexion
os.environ["NF_COOKIE_HTTP"] = "1"           # le client de test parle en http

import courses as mod_courses  # noqa: E402
import db  # noqa: E402
import journal as mod_journal  # noqa: E402
import personnes  # noqa: E402
import planning as mod_planning  # noqa: E402
import recettes  # noqa: E402

ECHECS = []


def verifier(condition, libelle, detail=""):
    if condition:
        print(f"[OK]   {libelle}")
    else:
        print(f"[KO]   {libelle}   {detail}")
        ECHECS.append(libelle)


# --------------------------------------------------------------- jeu d'essai
db.init_db()
conn = db.get_conn()
conn.executemany(
    """INSERT INTO aliment (code, nom, nom_norm, groupe, kcal, proteines,
                            glucides, lipides, source)
       VALUES (?,?,?,?,?,?,?,?,'ciqual')""",
    [("POULET", "Poulet", "poulet", "viandes, oeufs, poissons",
      120.0, 22.0, 0.0, 3.0),
     ("RIZ", "Riz", "riz", "produits céréaliers", 350.0, 7.0, 78.0, 1.0)])
conn.commit()
conn.close()

DOSSIER = Path(tempfile.mkdtemp(prefix="nf-cloison-rec-"))
recettes.DOSSIER = DOSSIER
(DOSSIER / "plat-a.json").write_text(json.dumps({
    "id": "plat-a", "titre": "Plat A", "portions_base": 1, "etapes": [],
    "ingredients": [
        {"nom": "Poulet", "ciqual_code": "POULET", "quantite": 200,
         "unite": "g", "echelle": "variable"}]}), encoding="utf-8")
(DOSSIER / "plat-b.json").write_text(json.dumps({
    "id": "plat-b", "titre": "Plat B", "portions_base": 1, "etapes": [],
    "ingredients": [
        {"nom": "Riz", "ciqual_code": "RIZ", "quantite": 100,
         "unite": "g", "echelle": "variable"}]}), encoding="utf-8")

# Deux comptes : un administrateur et une personne ordinaire.
ALICE = personnes.creer("alice", "Alice", "mot-de-passe-alice", admin=True)
BOB = personnes.creer("bob", "Bob", "mot-de-passe-bob")

# Chacune écrit des données distinctes.
mod_planning.ajouter(ALICE, "2026-04-06", "dejeuner", "plat-a", portions=1)
mod_planning.ajouter(ALICE, "2026-04-07", "diner", "plat-a", portions=2)
mod_planning.ajouter(BOB, "2026-04-06", "dejeuner", "plat-b", portions=1)

mod_journal.ajouter_recette(ALICE, "2026-04-06", "dejeuner", "plat-a")
mod_journal.ajouter_aliment(BOB, "2026-04-06", "diner", "RIZ", 150)

mod_journal.enregistrer_poids(ALICE, "2026-04-06", 62.0)
mod_journal.enregistrer_poids(BOB, "2026-04-06", 81.5)

db.set_reglage(ALICE, "objectif_kcal", 1800)
db.set_reglage(BOB, "objectif_kcal", 2600)


print("=== planning ===")
pa = mod_planning.entrees_entre(ALICE, "2026-01-01", "2026-12-31")
pb = mod_planning.entrees_entre(BOB, "2026-01-01", "2026-12-31")
verifier(len(pa) == 2 and len(pb) == 1,
         "chacune ne voit que ses propres repas", (len(pa), len(pb)))
verifier(all(e["recette_id"] == "plat-a" for e in pa),
         "Alice ne voit pas le plat de Bob")
verifier(all(e["recette_id"] == "plat-b" for e in pb),
         "Bob ne voit pas les plats d'Alice")
verifier({e["personne_id"] for e in pa} == {ALICE},
         "les lignes portent bien le bon propriétaire")

sa = mod_planning.semaine(ALICE, mod_planning.parse_date("2026-04-06"))
sb = mod_planning.semaine(BOB, mod_planning.parse_date("2026-04-06"))
verifier(len(sa["entrees"]) == 2 and len(sb["entrees"]) == 1,
         "la vue « semaine » est cloisonnée aussi")
verifier(sa["totaux"]["2026-04-06"]["kcal"] != sb["totaux"]["2026-04-06"]["kcal"],
         "les totaux du jour diffèrent bien d'une personne à l'autre")

print()
print("=== suppression : on n'efface pas chez le voisin ===")
entree_de_bob = pb[0]["id"]
verifier(not mod_planning.supprimer(ALICE, entree_de_bob),
         "Alice ne peut pas supprimer le repas de Bob (refus silencieux)")
verifier(len(mod_planning.entrees_entre(BOB, "2026-01-01", "2026-12-31")) == 1,
         "le repas de Bob est toujours là")
verifier(mod_planning.supprimer(BOB, entree_de_bob),
         "Bob peut supprimer le sien")
mod_planning.ajouter(BOB, "2026-04-06", "dejeuner", "plat-b", portions=1)

print()
print("=== journal ===")
ja = mod_journal.du_jour(ALICE, "2026-04-06")
jb = mod_journal.du_jour(BOB, "2026-04-06")
verifier(len(ja["entrees"]) == 1 and len(jb["entrees"]) == 1,
         "une entrée chacune")
verifier(ja["entrees"][0]["libelle"] == "Plat A", "Alice voit son repas",
         ja["entrees"][0]["libelle"])
verifier(jb["entrees"][0]["libelle"] == "Riz", "Bob voit le sien",
         jb["entrees"][0]["libelle"])
verifier(ja["totaux"]["kcal"] != jb["totaux"]["kcal"],
         "les totaux ne se mélangent pas")

entree_journal_bob = jb["entrees"][0]["id"]
verifier(not mod_journal.supprimer(ALICE, entree_journal_bob),
         "Alice ne peut pas effacer une ligne du journal de Bob")
verifier(len(mod_journal.du_jour(BOB, "2026-04-06")["entrees"]) == 1,
         "la ligne de Bob est intacte")

verifier(len(mod_journal.historique(ALICE, "2026-01-01", "2026-12-31")) == 1,
         "l'historique est cloisonné")

print()
print("=== poids : la donnée la plus sensible ===")
verifier(mod_journal.dernier_poids(ALICE)["poids_kg"] == 62.0,
         "Alice voit 62,0 kg", mod_journal.dernier_poids(ALICE))
verifier(mod_journal.dernier_poids(BOB)["poids_kg"] == 81.5,
         "Bob voit 81,5 kg", mod_journal.dernier_poids(BOB))
verifier(len(mod_journal.poids(ALICE)) == 1 and len(mod_journal.poids(BOB)) == 1,
         "une pesée chacune, à la même date, sans collision de clé")
mod_journal.supprimer_poids(ALICE, "2026-04-06")
verifier(mod_journal.dernier_poids(BOB) is not None,
         "supprimer sa pesée ne touche pas celle de l'autre")
mod_journal.enregistrer_poids(ALICE, "2026-04-06", 62.0)

print()
print("=== réglages : chacun son objectif ===")
verifier(db.get_reglages(ALICE)["objectif_kcal"] == "1800",
         "Alice vise 1800 kcal")
verifier(db.get_reglages(BOB)["objectif_kcal"] == "2600",
         "Bob vise 2600 kcal")
verifier(db.get_reglages(9999)["objectif_kcal"] == db.REGLAGES_DEFAUT["objectif_kcal"],
         "un compte sans réglage retombe sur les valeurs par défaut")

print()
print("=== liste de courses : jamais d'agrégation entre personnes ===")
ca = mod_courses.construire(ALICE, "2026-04-01", "2026-04-30")
cb = mod_courses.construire(BOB, "2026-04-01", "2026-04-30")
noms_a = {l["nom"] for _, lignes in ca["rayons"] for l in lignes}
noms_b = {l["nom"] for _, lignes in cb["rayons"] for l in lignes}
verifier(noms_a == {"Poulet"}, "Alice n'achète que du poulet", noms_a)
verifier(noms_b == {"Riz"}, "Bob n'achète que du riz", noms_b)
verifier(not (noms_a & noms_b), "aucun article commun : rien n'a fusionné")

mod_courses.cocher(ALICE, "2026-04-01", "2026-04-30", "POULET", True)
verifier(mod_courses.etat_coches(ALICE, "2026-04-01", "2026-04-30") == {"POULET": True},
         "Alice a coché son poulet")
verifier(mod_courses.etat_coches(BOB, "2026-04-01", "2026-04-30") == {},
         "la case cochée d'Alice n'apparaît pas chez Bob")
mod_courses.vider_coches(BOB, "2026-04-01", "2026-04-30")
verifier(mod_courses.etat_coches(ALICE, "2026-04-01", "2026-04-30") == {"POULET": True},
         "vider la liste de Bob ne décoche pas celle d'Alice")

print()
print("=== ce qui est PARTAGE doit l'être ===")
verifier(len(recettes.charger_toutes()) == 2,
         "les deux recettes sont visibles de tout le monde")
import aliments  # noqa: E402
verifier(aliments.get_aliment("POULET") is not None,
         "la base d'aliments est commune")

print()
print("=== les routes HTTP, en trichant sur les identifiants ===")
os.environ.pop("NF_PERSONNE_DEFAUT", None)
import app as mod_app  # noqa: E402
mod_app.PERSONNE_DEFAUT = None
mod_app.app.config["TESTING"] = True


def jeton(client):
    """Le jeton CSRF de ce client, posé dans la session comme le ferait
    l'affichage d'une page contenant un formulaire.

    Un jeton DISTINCT par client : avec une valeur commune, le test « le
    jeton de Bob ne vaut rien chez Alice » passerait pour de mauvaises
    raisons, les deux jetons étant égaux.
    """
    with client.session_transaction() as s:
        if mod_app.CLE_CSRF not in s:
            s[mod_app.CLE_CSRF] = f"jeton-de-test-{id(client):x}"
        return s[mod_app.CLE_CSRF]


def poste(client, url, **donnees):
    """POST avec son jeton, comme un vrai formulaire de l'application."""
    donnees[mod_app.CLE_CSRF] = jeton(client)
    return client.post(url, data=donnees)


def connecte(identifiant, mot_de_passe):
    client = mod_app.app.test_client()
    r = poste(client, "/connexion", identifiant=identifiant,
              motdepasse=mot_de_passe)
    assert r.status_code == 302, f"connexion refusée pour {identifiant}"
    return client


anonyme = mod_app.app.test_client()
verifier(anonyme.get("/").status_code == 302,
         "sans connexion, tout redirige vers la page de connexion")
verifier(anonyme.get("/journal").status_code == 302, "y compris le journal")
verifier("/connexion" in anonyme.get("/journal").headers.get("Location", ""),
         "et c'est bien vers /connexion")

mauvais = mod_app.app.test_client()
r = poste(mauvais, "/connexion", identifiant="alice",
          motdepasse="pas-le-bon")
verifier(r.status_code == 200 and "/" not in r.headers.get("Location", ""),
         "un mauvais mot de passe ne connecte pas")

alice = connecte("alice", "mot-de-passe-alice")
bob = connecte("bob", "mot-de-passe-bob")

page_a = alice.get("/journal?date=2026-04-06").get_data(as_text=True)
page_b = bob.get("/journal?date=2026-04-06").get_data(as_text=True)

# Attention : « Plat A » figure aussi dans la liste déroulante des recettes,
# qui est PARTAGÉE à dessein. Ce qui identifie l'entrée de journal d'Alice,
# c'est le formulaire de suppression portant son identifiant.
id_j_alice = mod_journal.du_jour(ALICE, "2026-04-06")["entrees"][0]["id"]
id_j_bob = mod_journal.du_jour(BOB, "2026-04-06")["entrees"][0]["id"]
verifier(f"/journal/supprimer/{id_j_alice}" in page_a,
         "Alice voit sa propre entrée de journal")
verifier(f"/journal/supprimer/{id_j_alice}" not in page_b,
         "l'entrée de journal d'Alice est absente de la page de Bob")
verifier(f"/journal/supprimer/{id_j_bob}" in page_b
         and f"/journal/supprimer/{id_j_bob}" not in page_a,
         "et réciproquement pour celle de Bob")
verifier("81,5" not in page_a, "le poids de Bob n'apparaît pas chez Alice")
verifier("62" not in page_b.split("Ce que j")[1][:400],
         "le poids d'Alice n'apparaît pas chez Bob")

verifier("1800" in alice.get("/reglages").get_data(as_text=True),
         "Alice voit son objectif")
verifier("2600" in bob.get("/reglages").get_data(as_text=True),
         "Bob voit le sien")

# Trichage : Bob tente de supprimer une entrée d'Alice par son id d'URL.
id_alice = mod_planning.entrees_entre(ALICE, "2026-01-01", "2026-12-31")[0]["id"]
poste(bob, f"/planning/supprimer/{id_alice}")
verifier(len(mod_planning.entrees_entre(ALICE, "2026-01-01", "2026-12-31")) == 2,
         "Bob ne supprime rien en devinant l'identifiant d'un repas d'Alice")

id_journal_alice = mod_journal.du_jour(ALICE, "2026-04-06")["entrees"][0]["id"]
poste(bob, f"/journal/supprimer/{id_journal_alice}", date="2026-04-06")
verifier(len(mod_journal.du_jour(ALICE, "2026-04-06")["entrees"]) == 1,
         "ni une ligne du journal d'Alice")

print()
print("=== l'administrateur gère les comptes, il ne lit pas les données ===")
verifier(alice.get("/comptes").status_code == 200,
         "Alice (admin) accède à la gestion des comptes")
verifier(bob.get("/comptes").status_code == 302,
         "Bob (non admin) en est écarté")
routes = {str(r) for r in mod_app.app.url_map.iter_rules()}
suspectes = [r for r in routes
             if "personne_id" in r and not r.startswith("/comptes")]
verifier(not suspectes,
         "aucune route ne prend un personne_id en dehors de /comptes",
         suspectes)
page_comptes = alice.get("/comptes").get_data(as_text=True)
verifier("81,5" not in page_comptes and "2600" not in page_comptes,
         "la page des comptes ne divulgue ni poids ni objectif")

print()
print("=== compte désactivé ===")
personnes.definir_actif(BOB, False)
verifier(bob.get("/").status_code == 302,
         "une session ouverte est invalidée dès la désactivation")
verifier(personnes.authentifier("bob", "mot-de-passe-bob") is None,
         "et il ne peut plus se reconnecter")
personnes.definir_actif(BOB, True)

print()
print("=== garde-fou de conception : personne_id obligatoire ===")
for module in (mod_planning, mod_journal, mod_courses):
    for nom, fn in vars(module).items():
        if nom.startswith("_") or not callable(fn):
            continue
        if getattr(fn, "__module__", "") != module.__name__:
            continue
        params = list(inspect.signature(fn).parameters.values())
        if not params or params[0].name != "personne_id":
            continue
        verifier(params[0].default is inspect.Parameter.empty,
                 f"{module.__name__}.{nom} exige personne_id sans défaut")

# On rejoue les appels tels qu'ils s'écrivaient en V1 : ils doivent TOUS
# échouer, sinon un bout de code oublié pendant la migration passerait encore
# et lirait les données de la personne 1 sans s'en rendre compte.
appels_v1 = [
    ("planning.entrees_entre", mod_planning.entrees_entre,
     ("2026-04-06", "2026-04-06")),
    ("planning.semaine", mod_planning.semaine,
     (mod_planning.parse_date("2026-04-06"),)),
    ("journal.du_jour", mod_journal.du_jour, ("2026-04-06",)),
    ("journal.dernier_poids", mod_journal.dernier_poids, ()),
    ("journal.poids", mod_journal.poids, ()),
    ("journal.historique", mod_journal.historique,
     ("2026-04-01", "2026-04-30")),
    ("courses.construire", mod_courses.construire,
     ("2026-04-06", "2026-04-06")),
    ("db.get_reglages", db.get_reglages, ()),
]
for nom, fonction, arguments in appels_v1:
    try:
        fonction(*arguments)
        verifier(False, f"l'ancien appel {nom} devrait échouer")
    except TypeError:
        verifier(True, f"l'ancien appel {nom} ne passe plus (TypeError)")

print()
print("=== la connexion ne renvoie jamais hors du site ===")
# Une redirection ouverte après authentification est une machine à hameçonner :
# le lien commence par la vraie adresse, la personne se connecte pour de bon,
# et atterrit sur une copie de l'écran de connexion qui redemande le mot de
# passe. Signalé par Semgrep (règle open-redirect) et corrigé.
DEFAUT = "/accueil"
for cible, attendu, libelle in (
        ("/journal", "/journal", "un chemin interne est conservé"),
        ("/journal?date=2026-04-06", "/journal?date=2026-04-06",
         "avec sa chaîne de requête"),
        (None, DEFAUT, "absente -> destination par défaut"),
        ("", DEFAUT, "vide -> destination par défaut"),
        ("https://exemple-malveillant.test/", DEFAUT, "URL absolue refusée"),
        ("http://exemple-malveillant.test/", DEFAUT, "en clair aussi"),
        ("//exemple-malveillant.test/", DEFAUT,
         "double barre : une URL déguisée en chemin"),
        ("/\\exemple-malveillant.test/", DEFAUT,
         "barre + antislash : même ruse, autre orthographe"),
        ("javascript:alert(1)", DEFAUT, "schéma javascript refusé"),
        ("  https://exemple-malveillant.test", DEFAUT,
         "espaces de tête ne sauvent pas l'URL"),
        ("journal", DEFAUT, "chemin relatif refusé"),
):
    obtenu = mod_app.redirection_locale(cible, DEFAUT)
    verifier(obtenu == attendu, libelle, f"{cible!r} -> {obtenu!r}")

# Et par la porte d'entrée : le paramètre « suivant » de /connexion.
c = mod_app.app.test_client()
reponse = poste(c, "/connexion?suivant=https://exemple-malveillant.test/",
                identifiant="alice", motdepasse="mot-de-passe-alice")
destination = reponse.headers.get("Location", "")
verifier("exemple-malveillant" not in destination,
         "/connexion?suivant=<site tiers> ne renvoie pas chez le tiers",
         destination)

print()
print("=== un site tiers ne peut pas agir en notre nom (CSRF) ===")
# Sans jeton, une page piégée visitée par une personne connectée suffirait à
# changer son mot de passe ou à vider son journal : son navigateur joindrait
# son cookie de session au formulaire de l'attaquant. Signalé par Semgrep.
sensibles = [
    ("/mon-compte", {"actuel": "mot-de-passe-alice",
                     "nouveau": "mot-de-passe-vole",
                     "confirmation": "mot-de-passe-vole"}),
    ("/comptes/creer", {"identifiant": "intrus", "prenom": "Intrus",
                        "motdepasse": "mot-de-passe-intrus"}),
    ("/journal/poids", {"date": "2026-04-06", "poids": "99"}),
    ("/reglages", {"objectif_kcal": "9999"}),
]
for url, donnees in sensibles:
    verifier(alice.post(url, data=donnees).status_code == 400,
             f"POST {url} sans jeton -> refusé")

# Le refus doit être un refus, pas un effet de bord silencieux.
verifier(personnes.authentifier("alice", "mot-de-passe-alice") is not None,
         "le mot de passe d'Alice n'a pas changé")
verifier(personnes.compter() == 2, "aucun compte n'a été créé au passage")
verifier(db.get_reglages(ALICE)["objectif_kcal"] == "1800",
         "l'objectif d'Alice est intact")

# Un jeton emprunté à quelqu'un d'autre ne vaut rien non plus.
verifier(alice.post("/reglages", data={"objectif_kcal": "9999",
                                       mod_app.CLE_CSRF: jeton(bob)}
                    ).status_code == 400,
         "le jeton de Bob ne sert à rien chez Alice")

# Et avec son propre jeton, tout fonctionne : la protection ne doit pas
# transformer l'application en musée.
verifier(poste(alice, "/reglages", objectif_kcal="1750").status_code == 302,
         "avec son jeton, Alice modifie bien ses réglages")
verifier(db.get_reglages(ALICE)["objectif_kcal"] == "1750",
         "et la valeur est enregistrée")

print()
print("=== le cookie de session ===")
verifier(mod_app.app.config["SESSION_COOKIE_HTTPONLY"] is True,
         "HttpOnly : inaccessible au JavaScript")
verifier(mod_app.app.config["SESSION_COOKIE_SAMESITE"] == "Strict",
         "SameSite=Strict : jamais envoyé depuis un autre site")

print()
shutil.rmtree(DOSSIER, ignore_errors=True)
shutil.rmtree(BASE.parent, ignore_errors=True)

if ECHECS:
    print(f"!!! {len(ECHECS)} test(s) en echec : {ECHECS}")
    sys.exit(1)
print("Le cloisonnement entre comptes est vérifié.")
