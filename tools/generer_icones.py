# -*- coding: utf-8 -*-
"""
Génère les icônes PNG de la PWA, sans dépendance externe.

    python tools/generer_icones.py

Pourquoi un encodeur PNG maison plutôt que Pillow : l'application n'a besoin
de ces fichiers qu'une fois. Ajouter Pillow (et ses binaires) au serveur pour
dessiner trois carrés verts serait disproportionné. Le format PNG minimal
(un seul IDAT, filtre 0) tient en quelques lignes de zlib et struct.

Le dessin : carré plein vert Nutriform, lettre « N » blanche centrée. Pas de
coins transparents — iOS arrondit lui-même l'icône de l'écran d'accueil, et
une icône « maskable » Android doit couvrir tout le carré.
"""
import struct
import sys
import zlib
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "static" / "icons"

VERT = (46, 125, 85)        # --vert de style.css
BLANC = (255, 255, 255)
TAILLES = {"icone-192.png": 192, "icone-512.png": 512, "icone-180.png": 180}


def ecrire_png(chemin: Path, largeur: int, hauteur: int, pixels: bytearray):
    """pixels = RGB, 3 octets par point, largeur*hauteur*3 au total."""
    lignes = bytearray()
    for y in range(hauteur):
        lignes.append(0)                       # filtre « aucun »
        debut = y * largeur * 3
        lignes += pixels[debut:debut + largeur * 3]

    def chunk(tag: bytes, donnees: bytes) -> bytes:
        corps = tag + donnees
        return (struct.pack(">I", len(donnees)) + corps
                + struct.pack(">I", zlib.crc32(corps) & 0xFFFFFFFF))

    entete = struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0)
    chemin.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", entete)
        + chunk(b"IDAT", zlib.compress(bytes(lignes), 9))
        + chunk(b"IEND", b""))


def dans_le_n(x: float, y: float) -> bool:
    """Le « N » est décrit dans un carré de référence [0,1]x[0,1].

    Trois traits : deux montants verticaux et une diagonale qui les relie.
    """
    haut, bas = 0.26, 0.74            # hauteur de la lettre
    gauche, droite = 0.30, 0.70       # largeur de la lettre
    epaisseur = 0.085

    if not (haut <= y <= bas):
        return False
    if gauche <= x <= gauche + epaisseur:            # montant gauche
        return True
    if droite - epaisseur <= x <= droite:            # montant droit
        return True

    # Diagonale : du haut du montant gauche vers le bas du montant droit.
    largeur_lettre = droite - gauche
    progression = (y - haut) / (bas - haut)
    centre = gauche + progression * largeur_lettre
    demi = epaisseur * 0.78
    return abs(x - centre) <= demi


def dessiner(taille: int) -> bytearray:
    pixels = bytearray(taille * taille * 3)
    # Anticrénelage simple : 3x3 sous-échantillons par pixel.
    sous = 3
    for py in range(taille):
        for px in range(taille):
            couvert = 0
            for sy in range(sous):
                for sx in range(sous):
                    x = (px + (sx + 0.5) / sous) / taille
                    y = (py + (sy + 0.5) / sous) / taille
                    if dans_le_n(x, y):
                        couvert += 1
            poids = couvert / (sous * sous)
            index = (py * taille + px) * 3
            for canal in range(3):
                pixels[index + canal] = round(
                    VERT[canal] * (1 - poids) + BLANC[canal] * poids)
    return pixels


if __name__ == "__main__":
    DOSSIER.mkdir(parents=True, exist_ok=True)
    for nom, taille in TAILLES.items():
        ecrire_png(DOSSIER / nom, taille, taille, dessiner(taille))
        print(f"[OK] {nom} ({taille}x{taille})")
    sys.exit(0)
