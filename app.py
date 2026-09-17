# -*- coding: utf-8 -*-
"""Nutriform — application web (Flask).

Mono-utilisateur. L'authentification ne s'active que si NF_PASSWORD est définie
(donc jamais en développement local, toujours sur le VPS).

Les routes restent volontairement minces : toute la logique vit dans
nutrition.py (calculs), recettes.py (fichiers), planning.py, courses.py et
journal.py (base). Une route lit la requête, appelle un module, rend un gabarit.
"""
import os
from datetime import date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify)

import aliments
import courses as mod_courses
import db
import journal as mod_journal
import nutrition
import planning as mod_planning
import recettes

app = Flask(__name__)
app.secret_key = os.environ.get("NF_SECRET", "dev-nutriform-cle-locale")
app.permanent_session_lifetime = timedelta(days=90)

MOT_DE_PASSE = os.environ.get("NF_PASSWORD")  # None en local -> pas d'auth


def login_required(vue):
    """Protège une vue. Inactif tant que NF_PASSWORD n'est pas définie."""
    @wraps(vue)
    def wrapper(*args, **kwargs):
        if MOT_DE_PASSE and not session.get("connecte"):
            return redirect(url_for("login", suivant=request.path))
        return vue(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------- gabarits
@app.template_filter("nombre")
def filtre_nombre(valeur, decimales: int = 1):
    """Affichage lisible d'une valeur nutritionnelle.

    None -> « — » : une donnée ABSENTE de Ciqual ne doit jamais s'afficher
    comme un zéro, ce serait une information fausse.
    """
    if valeur is None:
        return "—"
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    if abs(v) >= 100 or abs(v - round(v)) < 0.05:
        return f"{v:.0f}".replace("-0", "0")
    return f"{v:.{decimales}f}".replace(".", ",")


JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


@app.template_filter("jour_fr")
def filtre_jour_fr(valeur, court: bool = False):
    jour = valeur if isinstance(valeur, date) else date.fromisoformat(str(valeur))
    nom = JOURS_FR[jour.weekday()]
    if court:
        return f"{nom[:3]}. {jour.day}"
    return f"{nom} {jour.day} {MOIS_FR[jour.month - 1]}"


@app.context_processor
def injecter_commun():
    return {
        "auth_active": bool(MOT_DE_PASSE),
        "creneaux": db.CRENEAUX,
        "creneau_libelle": db.CRENEAU_LIBELLE,
        "aujourdhui": date.today().isoformat(),
    }


def _nombre(valeur, defaut=None):
    """Lit un nombre venant d'un formulaire. Accepte la virgule décimale."""
    texte = (valeur or "").strip().replace(",", ".")
    if not texte:
        return defaut
    try:
        return float(texte)
    except ValueError:
        return defaut


def _nombre_positif(valeur):
    nombre = _nombre(valeur)
    return nombre if nombre and nombre > 0 else None


def cibles_par_creneau(reglages: dict | None = None) -> dict[str, int]:
    """Répartit l'objectif calorique du jour sur les créneaux."""
    reglages = reglages if reglages is not None else db.get_reglages()
    objectif = _nombre(reglages.get("objectif_kcal"), 0) or 0
    cibles = {}
    for creneau in db.CRENEAUX:
        part = _nombre(reglages.get(f"part_{creneau}"), 0) or 0
        cibles[creneau] = round(objectif * part / 100)
    return cibles


# ------------------------------------------------------------------ connexion
@app.route("/connexion", methods=["GET", "POST"])
def login():
    if not MOT_DE_PASSE:
        return redirect(url_for("accueil"))
    if request.method == "POST":
        if request.form.get("motdepasse") == MOT_DE_PASSE:
            session["connecte"] = True
            session.permanent = True
            return redirect(request.args.get("suivant") or url_for("accueil"))
        flash("Mot de passe incorrect.", "erreur")
    return render_template("connexion.html")


@app.route("/deconnexion")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------------------- aujourd'hui
@app.route("/")
@login_required
def accueil():
    jour = mod_planning.parse_date(request.args.get("date")).isoformat()
    reglages = db.get_reglages()
    jour_journal = mod_journal.du_jour(jour)
    prevu = mod_planning.detailler(mod_planning.entrees_entre(jour, jour))

    objectifs = {
        "kcal": _nombre(reglages.get("objectif_kcal"), 0) or 0,
        "proteines": _nombre(reglages.get("objectif_proteines_g"), 0) or 0,
        "glucides": _nombre(reglages.get("objectif_glucides_g"), 0) or 0,
        "lipides": _nombre(reglages.get("objectif_lipides_g"), 0) or 0,
    }
    conn = db.get_conn()
    n_aliments = conn.execute("SELECT COUNT(*) FROM aliment").fetchone()[0]
    conn.close()

    return render_template(
        "accueil.html", jour=jour, reglages=reglages, objectifs=objectifs,
        journal=jour_journal, prevu=prevu, n_aliments=n_aliments,
        n_recettes=len(recettes.charger_toutes()),
        dernier_poids=mod_journal.dernier_poids(),
        tendance=mod_journal.tendance_poids(30),
        cibles=cibles_par_creneau(reglages))


# -------------------------------------------------------------------- recettes
@app.route("/recettes")
@login_required
def page_recettes():
    liste = recettes.charger_toutes()
    codes = {c for r in liste for c in nutrition.codes_recette(r)}
    table = aliments.get_aliments(codes)
    apercus = [{"recette": r, "calcul": nutrition.calculer(r, table)}
               for r in liste]
    return render_template("recettes.html", apercus=apercus)


@app.route("/recettes/<recette_id>")
@login_required
def page_recette(recette_id):
    recette = recettes.charger(recette_id)
    if not recette:
        flash("Recette introuvable.", "erreur")
        return redirect(url_for("page_recettes"))

    kcal_cible = _nombre_positif(request.args.get("kcal"))
    portions = _nombre_positif(request.args.get("portions"))
    table = aliments.get_aliments(nutrition.codes_recette(recette))
    calcul = nutrition.calculer(recette, table, kcal_cible=kcal_cible,
                                portions=portions)
    return render_template("recette.html", recette=recette, calcul=calcul,
                           erreurs=recettes.valider(recette),
                           cibles=cibles_par_creneau(),
                           jour=date.today().isoformat())


# -------------------------------------------------------------------- planning
@app.route("/planning")
@login_required
def page_planning():
    lundi = mod_planning.lundi_de(mod_planning.parse_date(request.args.get("semaine")))
    semaine = mod_planning.semaine(lundi)
    return render_template(
        "planning.html", semaine=semaine,
        precedente=(lundi - timedelta(days=7)).isoformat(),
        suivante=(lundi + timedelta(days=7)).isoformat(),
        recettes_dispo=recettes.charger_toutes(),
        cibles=cibles_par_creneau(),
        objectif_kcal=_nombre(db.get_reglages().get("objectif_kcal"), 0) or 0)


@app.route("/planning/ajouter", methods=["POST"])
@login_required
def planning_ajouter():
    jour = request.form.get("date") or date.today().isoformat()
    creneau = request.form.get("creneau") or db.CRENEAUX[0]
    recette_id = request.form.get("recette_id")
    if not recette_id:
        flash("Choisir une recette.", "erreur")
    elif not recettes.charger(recette_id):
        flash("Recette introuvable.", "erreur")
    else:
        mod_planning.ajouter(
            jour, creneau, recette_id,
            kcal_cible=_nombre_positif(request.form.get("kcal_cible")),
            portions=_nombre_positif(request.form.get("portions")) or 1)
    return redirect(request.form.get("retour")
                    or url_for("page_planning", semaine=jour))


@app.route("/planning/supprimer/<int:entree_id>", methods=["POST"])
@login_required
def planning_supprimer(entree_id):
    mod_planning.supprimer(entree_id)
    return redirect(request.form.get("retour") or url_for("page_planning"))


@app.route("/planning/dupliquer", methods=["POST"])
@login_required
def planning_dupliquer():
    source = mod_planning.lundi_de(mod_planning.parse_date(request.form.get("semaine")))
    cible = source + timedelta(days=7)
    n = mod_planning.dupliquer_semaine(source, cible)
    flash(f"{n} repas recopiés sur la semaine du {cible.isoformat()}."
          if n else "Rien à recopier : cette semaine est vide.")
    return redirect(url_for("page_planning", semaine=cible.isoformat()))


# --------------------------------------------------------------------- courses
@app.route("/courses")
@login_required
def page_courses():
    aujourdhui = date.today()
    debut = mod_planning.parse_date(request.args.get("debut"), aujourdhui)
    fin = mod_planning.parse_date(request.args.get("fin"),
                                  aujourdhui + timedelta(days=6))
    if fin < debut:
        debut, fin = fin, debut
    liste = mod_courses.construire(debut.isoformat(), fin.isoformat())
    return render_template("courses.html", liste=liste,
                           debut=debut.isoformat(), fin=fin.isoformat())


@app.route("/courses/cocher", methods=["POST"])
@login_required
def courses_cocher():
    debut = request.form.get("debut")
    fin = request.form.get("fin")
    cle = request.form.get("cle")
    coche = request.form.get("coche") == "1"
    if debut and fin and cle:
        mod_courses.cocher(debut, fin, cle, coche)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True)
    return redirect(url_for("page_courses", debut=debut, fin=fin))


@app.route("/courses/vider", methods=["POST"])
@login_required
def courses_vider():
    debut, fin = request.form.get("debut"), request.form.get("fin")
    if debut and fin:
        mod_courses.vider_coches(debut, fin)
    return redirect(url_for("page_courses", debut=debut, fin=fin))


# --------------------------------------------------------------------- journal
@app.route("/journal")
@login_required
def page_journal():
    jour = mod_planning.parse_date(request.args.get("date")).isoformat()
    recherche = (request.args.get("q") or "").strip()
    trouves = aliments.rechercher(recherche, limite=12) if recherche else []
    return render_template(
        "journal.html", jour=jour, journal=mod_journal.du_jour(jour),
        prevu=mod_planning.detailler(mod_planning.entrees_entre(jour, jour)),
        recettes_dispo=recettes.charger_toutes(),
        recherche=recherche, trouves=trouves,
        cibles=cibles_par_creneau(),
        objectif_kcal=_nombre(db.get_reglages().get("objectif_kcal"), 0) or 0,
        poids=mod_journal.poids(60), dernier_poids=mod_journal.dernier_poids(),
        veille=(date.fromisoformat(jour) - timedelta(days=1)).isoformat(),
        lendemain=(date.fromisoformat(jour) + timedelta(days=1)).isoformat())


@app.route("/journal/recette", methods=["POST"])
@login_required
def journal_recette():
    jour = request.form.get("date") or date.today().isoformat()
    try:
        mod_journal.ajouter_recette(
            jour, request.form.get("creneau") or db.CRENEAUX[0],
            request.form.get("recette_id"),
            portions=_nombre_positif(request.form.get("portions")) or 1,
            kcal_cible=_nombre_positif(request.form.get("kcal_cible")))
    except ValueError as erreur:
        flash(str(erreur), "erreur")
    return redirect(url_for("page_journal", date=jour))


@app.route("/journal/aliment", methods=["POST"])
@login_required
def journal_aliment():
    jour = request.form.get("date") or date.today().isoformat()
    grammes = _nombre_positif(request.form.get("grammes"))
    if not grammes:
        flash("Indiquer une quantité en grammes.", "erreur")
    else:
        try:
            mod_journal.ajouter_aliment(
                jour, request.form.get("creneau") or db.CRENEAUX[0],
                request.form.get("aliment_code"), grammes)
        except ValueError as erreur:
            flash(str(erreur), "erreur")
    return redirect(url_for("page_journal", date=jour))


@app.route("/journal/depuis-planning", methods=["POST"])
@login_required
def journal_depuis_planning():
    jour = request.form.get("date") or date.today().isoformat()
    n = mod_journal.copier_planning(jour)
    flash(f"{n} repas repris du planning." if n
          else "Rien à reprendre : le planning du jour est vide "
               "ou déjà reporté.")
    return redirect(url_for("page_journal", date=jour))


@app.route("/journal/supprimer/<int:entree_id>", methods=["POST"])
@login_required
def journal_supprimer(entree_id):
    jour = request.form.get("date") or date.today().isoformat()
    mod_journal.supprimer(entree_id)
    return redirect(url_for("page_journal", date=jour))


@app.route("/journal/poids", methods=["POST"])
@login_required
def journal_poids():
    jour = request.form.get("date") or date.today().isoformat()
    valeur = _nombre_positif(request.form.get("poids_kg"))
    if not valeur:
        flash("Poids invalide.", "erreur")
    else:
        mod_journal.enregistrer_poids(jour, valeur,
                                      request.form.get("commentaire"))
    return redirect(url_for("page_journal", date=jour))


# -------------------------------------------------------------------- aliments
@app.route("/aliments")
@login_required
def page_aliments():
    terme = (request.args.get("q") or "").strip()
    groupe = (request.args.get("groupe") or "").strip() or None
    resultats = (aliments.rechercher(terme, limite=50, groupe=groupe)
                 if (terme or groupe) else [])
    return render_template("aliments.html", terme=terme, groupe=groupe,
                           resultats=resultats, groupes=aliments.groupes())


@app.route("/aliments/nouveau", methods=["POST"])
@login_required
def aliment_nouveau():
    nom = (request.form.get("nom") or "").strip()
    kcal = _nombre(request.form.get("kcal"))
    if not nom or kcal is None:
        flash("Un aliment perso exige au moins un nom et des kcal/100 g.",
              "erreur")
        return redirect(url_for("page_aliments"))
    code = aliments.creer_aliment_perso(
        nom, kcal,
        _nombre(request.form.get("proteines"), 0) or 0,
        _nombre(request.form.get("glucides"), 0) or 0,
        _nombre(request.form.get("lipides"), 0) or 0)
    flash(f"Aliment « {nom} » créé (code {code}).")
    return redirect(url_for("page_aliment", code=code))


@app.route("/aliments/<code>")
@login_required
def page_aliment(code):
    aliment = aliments.get_aliment(code)
    if not aliment:
        flash("Aliment introuvable.", "erreur")
        return redirect(url_for("page_aliments"))
    return render_template("aliment.html", aliment=aliment,
                           unites=aliments.unites_de(code))


@app.route("/aliments/<code>/modifier", methods=["POST"])
@login_required
def aliment_modifier(code):
    champs = {"nom": (request.form.get("nom") or "").strip() or None}
    for cle in ("kcal", "proteines", "glucides", "lipides",
                "fibres", "sucres", "sel"):
        champs[cle] = _nombre(request.form.get(cle))
    try:
        if aliments.modifier_aliment_perso(code, **champs):
            flash("Aliment mis à jour.")
        else:
            flash("Rien à modifier.", "erreur")
    except ValueError as erreur:
        flash(str(erreur), "erreur")
    return redirect(url_for("page_aliment", code=code))


@app.route("/aliments/<code>/unite", methods=["POST"])
@login_required
def aliment_unite(code):
    unite = (request.form.get("unite") or "").strip()
    grammes = _nombre_positif(request.form.get("grammes"))
    if not unite or not grammes:
        flash("Indiquer une unité et son poids en grammes.", "erreur")
    else:
        aliments.definir_unite(code, unite, grammes)
    return redirect(url_for("page_aliment", code=code))


# -------------------------------------------------------------------- réglages
@app.route("/reglages", methods=["GET", "POST"])
@login_required
def page_reglages():
    if request.method == "POST":
        for cle in ("objectif_kcal", "objectif_proteines_g",
                    "objectif_glucides_g", "objectif_lipides_g"):
            valeur = _nombre(request.form.get(cle))
            if valeur is not None and valeur >= 0:
                db.set_reglage(cle, round(valeur))
        parts = {c: _nombre(request.form.get(f"part_{c}"), 0) or 0
                 for c in db.CRENEAUX}
        somme = sum(parts.values())
        if abs(somme - 100) > 0.5:
            flash(f"La répartition par créneau fait {somme:.0f} % au lieu de "
                  f"100 % : elle est enregistrée telle quelle, mais les cibles "
                  f"par repas ne couvriront pas l'objectif du jour.", "erreur")
        for creneau, part in parts.items():
            db.set_reglage(f"part_{creneau}", round(part))
        flash("Réglages enregistrés.")
        return redirect(url_for("page_reglages"))

    reglages = db.get_reglages()
    return render_template("reglages.html", reglages=reglages,
                           cibles=cibles_par_creneau(reglages))


# ------------------------------------------------------------------------ PWA
# Ces deux fichiers doivent être servis depuis la RACINE, pas depuis /static :
# le périmètre d'un service worker est limité à son propre dossier, et un
# sw.js servi sous /static/ ne pourrait pas mettre les pages en cache.
@app.route("/manifest.webmanifest")
def manifeste():
    return jsonify({
        "name": "Nutriform",
        "short_name": "Nutriform",
        "description": "Suivi nutritionnel : recettes calibrées, planning, "
                       "liste de courses et journal.",
        "lang": "fr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f6f7f5",
        "theme_color": "#2e7d55",
        "icons": [
            {"src": "/static/icons/icone-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icons/icone-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any maskable"},
        ],
    }), 200, {"Content-Type": "application/manifest+json"}


@app.route("/sw.js")
def service_worker():
    reponse = app.send_static_file("sw.js")
    reponse.headers["Content-Type"] = "application/javascript; charset=utf-8"
    reponse.headers["Service-Worker-Allowed"] = "/"
    reponse.headers["Cache-Control"] = "no-cache"
    return reponse


@app.route("/sante")
def sante():
    """Sonde simple (utile derrière nginx / systemd)."""
    return jsonify(statut="ok")


if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, port=int(os.environ.get("NF_PORT", "5001")))
