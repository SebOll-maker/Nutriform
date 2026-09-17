# -*- coding: utf-8 -*-
"""
Comptes utilisateurs.

L'application est partagée entre proches qui ne vivent pas sous le même toit :
chaque personne est un locataire indépendant. Le cloisonnement des données
repose sur `personne_id`, propagé depuis la session par app.py ; ce module ne
s'occupe que des comptes eux-mêmes.

Mots de passe : hachés avec `werkzeug.security` (scrypt), qui est déjà une
dépendance de Flask. Un mot de passe n'est JAMAIS stocké, journalisé ni
renvoyé en clair — les fonctions de ce module ne le reçoivent que pour le
hacher ou le vérifier.

Deux garde-fous volontaires :
  - `authentifier()` refuse un compte désactivé, et ne dit pas à l'appelant
    si c'est l'identifiant ou le mot de passe qui est faux ;
  - on ne peut pas retirer le dernier compte administrateur, sinon plus
    personne ne pourrait gérer les comptes.
"""
import re
import unicodedata
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

import db

LONGUEUR_MINI_MOT_DE_PASSE = 8


def normaliser_identifiant(texte: str) -> str:
    """Identifiant canonique : minuscules, sans accent, sans espace.

    « Marie-Claude » et « marieclaude » doivent désigner le même compte, sinon
    on se connecte en tâtonnant.
    """
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", texte or "")
        if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9._-]+", "", sans_accent.strip().lower())


def verifier_mot_de_passe_acceptable(mot_de_passe: str):
    """Lève ValueError si le mot de passe est trop faible. Volontairement
    minimal : une longueur. Des règles de complexité poussent aux post-it."""
    if not mot_de_passe or len(mot_de_passe) < LONGUEUR_MINI_MOT_DE_PASSE:
        raise ValueError(
            f"Le mot de passe doit faire au moins "
            f"{LONGUEUR_MINI_MOT_DE_PASSE} caractères.")


# ------------------------------------------------------------------- écritures
def donnees_orphelines() -> bool:
    """Existe-t-il des données rattachées à une personne qui n'existe pas ?

    C'est le cas juste après la migration V2 : le planning, le journal et les
    pesées saisis en mono-utilisateur ont été attribués à la personne 1, mais
    aucun compte n'a encore été créé. `creer()` doit alors reprendre cet
    identifiant, sinon ces données deviendraient inaccessibles.
    """
    conn = db.get_conn()
    orphelines = any(
        conn.execute(
            f"SELECT 1 FROM {table} WHERE personne_id NOT IN "
            f"(SELECT id FROM personne) LIMIT 1").fetchone()
        for table in ("planning", "journal", "poids", "reglage"))
    conn.close()
    return bool(orphelines)


def creer(identifiant: str, prenom: str, mot_de_passe: str,
          admin: bool = False, personne_id: int | None = None) -> int:
    """Crée un compte et ses objectifs par défaut. Renvoie son id.

    `personne_id` permet de forcer l'identifiant. Laissé à None, le tout
    premier compte créé sur une base fraîchement migrée REPREND
    automatiquement l'identifiant des données d'avant la V2 (voir
    `donnees_orphelines`). Cette reprise est faite ici, et non dans le script
    en ligne de commande, pour qu'aucun chemin de création ne puisse créer par
    mégarde un compte qui écraserait ces données via un ON CONFLICT.
    """
    identifiant = normaliser_identifiant(identifiant)
    if not identifiant:
        raise ValueError("Identifiant vide ou composé de caractères refusés.")
    if not (prenom or "").strip():
        raise ValueError("Le prénom est obligatoire : il sert à l'affichage.")
    verifier_mot_de_passe_acceptable(mot_de_passe)

    if personne_id is None and compter() == 0 and donnees_orphelines():
        personne_id = db.PERSONNE_ORIGINE

    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM personne WHERE identifiant = ?",
                    (identifiant,)).fetchone():
        conn.close()
        raise ValueError(f"L'identifiant « {identifiant} » est déjà pris.")
    if personne_id is not None and conn.execute(
            "SELECT 1 FROM personne WHERE id = ?", (personne_id,)).fetchone():
        conn.close()
        raise ValueError(f"L'identifiant numérique {personne_id} est déjà pris.")

    curseur = conn.execute(
        """INSERT INTO personne (id, identifiant, prenom, mot_de_passe_hash,
                                 admin, actif, cree_le)
           VALUES (?,?,?,?,?,1,?)""",
        (personne_id, identifiant, prenom.strip(),
         generate_password_hash(mot_de_passe), 1 if admin else 0,
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    nouvel_id = curseur.lastrowid
    conn.close()

    db.creer_reglages_defaut(nouvel_id)
    return nouvel_id


def changer_mot_de_passe(personne_id: int, nouveau: str):
    verifier_mot_de_passe_acceptable(nouveau)
    conn = db.get_conn()
    conn.execute("UPDATE personne SET mot_de_passe_hash = ? WHERE id = ?",
                 (generate_password_hash(nouveau), personne_id))
    conn.commit()
    conn.close()


def definir_actif(personne_id: int, actif: bool):
    """Active ou désactive un compte. Les données sont conservées : on ne
    supprime pas l'historique alimentaire de quelqu'un sur un clic."""
    if not actif and _compte_admins_actifs_hors(personne_id) == 0:
        raise ValueError("Impossible de désactiver le dernier administrateur "
                         "actif : plus personne ne pourrait gérer les comptes.")
    conn = db.get_conn()
    conn.execute("UPDATE personne SET actif = ? WHERE id = ?",
                 (1 if actif else 0, personne_id))
    conn.commit()
    conn.close()


def definir_admin(personne_id: int, admin: bool):
    if not admin and _compte_admins_actifs_hors(personne_id) == 0:
        raise ValueError("Impossible de retirer le dernier administrateur.")
    conn = db.get_conn()
    conn.execute("UPDATE personne SET admin = ? WHERE id = ?",
                 (1 if admin else 0, personne_id))
    conn.commit()
    conn.close()


def _compte_admins_actifs_hors(personne_id: int) -> int:
    conn = db.get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM personne "
        "WHERE admin = 1 AND actif = 1 AND id != ?", (personne_id,)).fetchone()[0]
    conn.close()
    return n


# -------------------------------------------------------------------- lectures
def authentifier(identifiant: str, mot_de_passe: str) -> dict | None:
    """Renvoie la personne si le couple est valide et le compte actif, sinon None.

    Le hachage est vérifié même quand l'identifiant est inconnu, avec un
    condensat factice : sans cela, le temps de réponse révélerait quels
    identifiants existent.
    """
    conn = db.get_conn()
    ligne = conn.execute(
        "SELECT * FROM personne WHERE identifiant = ?",
        (normaliser_identifiant(identifiant),)).fetchone()
    conn.close()

    if ligne is None:
        check_password_hash(generate_password_hash("comparaison-a-vide"),
                            mot_de_passe or "")
        return None
    if not check_password_hash(ligne["mot_de_passe_hash"], mot_de_passe or ""):
        return None
    if not ligne["actif"]:
        return None
    return _sans_hash(ligne)


def get(personne_id: int) -> dict | None:
    conn = db.get_conn()
    ligne = conn.execute("SELECT * FROM personne WHERE id = ?",
                         (personne_id,)).fetchone()
    conn.close()
    return _sans_hash(ligne) if ligne else None


def lister(inclure_inactifs: bool = True) -> list[dict]:
    conn = db.get_conn()
    sql = "SELECT * FROM personne"
    if not inclure_inactifs:
        sql += " WHERE actif = 1"
    lignes = conn.execute(sql + " ORDER BY prenom").fetchall()
    conn.close()
    return [_sans_hash(l) for l in lignes]


def compter() -> int:
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM personne").fetchone()[0]
    conn.close()
    return n


def _sans_hash(ligne) -> dict:
    """Le condensat du mot de passe ne sort jamais de ce module."""
    personne = dict(ligne)
    personne.pop("mot_de_passe_hash", None)
    personne["admin"] = bool(personne.get("admin"))
    personne["actif"] = bool(personne.get("actif"))
    return personne
