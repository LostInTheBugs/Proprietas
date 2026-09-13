#!/usr/bin/env python3
"""Génère desktop/proprietas.icns (icône macOS) depuis l'emblème du projet.

Recette (alignée sur l'icône Windows desktop/proprietas.ico) : canevas carré
transparent, emblème centré à ~95 % de la hauteur.

Usage : python3 desktop/make_icns.py
- sur macOS : passe par « iconutil » (icns natif d'Apple) ;
- ailleurs   : écrit l'icns directement via Pillow (entrées PNG, lisible par macOS).

Source : frontend/public/proprietas-icon.png (emblème du projet).
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "public" / "proprietas-icon.png"
OUT = ROOT / "desktop" / "proprietas.icns"

# (nom de fichier iconset, taille en pixels) — jeu standard macOS
ICONSET = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def render(emblem: Image.Image, size: int) -> Image.Image:
    """Emblème centré sur un canevas carré (contenu ≈ 95 % de la hauteur)."""
    ch = max(1, round(size * 0.95))
    sc = emblem.resize(
        (max(1, round(emblem.width * ch / emblem.height)), ch), Image.LANCZOS
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(sc, ((size - sc.width) // 2, (size - sc.height) // 2))
    return canvas


def main() -> None:
    emblem = Image.open(SRC).convert("RGBA")
    rendered = {size: render(emblem, size) for _, size in ICONSET}
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for name, size in ICONSET:
            rendered[size].save(iconset / name)
        if shutil.which("iconutil"):
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(OUT)], check=True
            )
        else:
            # Pillow >= 8.3 : icns avec entrées PNG (32 à 1024 px)
            images = [rendered[size] for _, size in ICONSET]
            images[-1].save(OUT, format="ICNS", append_images=images[:-1])
    print("OK —", OUT)


if __name__ == "__main__":
    main()
