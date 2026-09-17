# -*- coding: utf-8 -*-
"""Lance Nutriform via waitress (stable, sans reloader).

Variables d'environnement :
  NF_HOST  (def. 127.0.0.1)  -- mettre 0.0.0.0 pour tester depuis l'iPhone
                                sur le réseau local ; derrière nginx, garder 127.0.0.1
  NF_PORT  (def. 5001)       -- 5001 pour ne pas entrer en conflit avec l'intranet (5000)
  NF_DB    (def. data/nutriform.db)
  NF_PASSWORD (non défini en local = pas d'authentification)
  NF_SECRET   (clé de session Flask)
"""
import os
from waitress import serve
import db
from app import app

if __name__ == "__main__":
    db.init_db()
    host = os.environ.get("NF_HOST", "127.0.0.1")
    port = int(os.environ.get("NF_PORT", "5001"))
    print(f"Nutriform sur http://{host}:{port}  (Ctrl+C pour arreter)")
    serve(app, host=host, port=port)
