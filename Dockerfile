# Nutriform — image applicative.
# Tourne sous l'uid 113 / gid 121 (utilisateur "nutriform" de l'hote, defini dans
# le compose) pour que la base et les recettes bind-montees gardent leur
# proprietaire et restent lisibles par le script de sauvegarde quotidien.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Couche de dependances separee : mise en cache tant que requirements.txt
# ne bouge pas, donc les rebuilds de code sont quasi instantanes.
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Lecture pour tous, traversee des repertoires, aucun droit d'ecriture : le code
# reste non modifiable par l'application. (Lecon de demo-ncr, ou des repertoires
# en mode 700 rendaient les templates illisibles pour l'utilisateur du conteneur.)
RUN chmod -R a+rX /app

EXPOSE 5001
CMD ["python", "serve.py"]
