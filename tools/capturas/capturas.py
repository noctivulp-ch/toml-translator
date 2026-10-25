#!/usr/bin/env python3
"""Regenera las imágenes del README (docs/capturas/*.png) con una traducción real.

    python3 tools/capturas/capturas.py [--model gemma4:e4b]

Traduce `tools/capturas/ejemplo.toml` (textos inventados, no de un juego) con
Ollama y el glosario de al lado, y dibuja tres imágenes: la corrida en una
terminal oscura, el archivo traducido en claro, y un corte diagonal del
original (arriba) al traducido (abajo). Necesita Ollama con el modelo, rich,
chromium y Python con Pillow y NumPy.
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text
from rich.terminal_theme import DEFAULT_TERMINAL_THEME, MONOKAI

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
SALIDA = RAIZ / "docs" / "capturas"
sys.path.insert(0, str(AQUI))

from corte_diagonal import componer  # noqa: E402

ANCHO = 112


def a_png(svg: Path, png: Path) -> None:
    # rich coloca cada tramo de color con textLength, que rsvg e Inkscape no
    # respetan (el texto sale con huecos y solapes); chromium sí.
    texto = svg.read_text().replace("Fira Code", "DejaVu Sans Mono")
    ancho, alto = (math.ceil(float(v)) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', texto).groups())
    html = svg.with_suffix(".html")
    html.write_text(f"<!doctype html><style>body{{margin:0}}</style>{texto}")
    subprocess.run(
        ["chromium", "--headless=new", "--hide-scrollbars", "--force-device-scale-factor=1.5",
         "--default-background-color=00000000", f"--window-size={ancho},{alto}",
         f"--screenshot={png}", html.as_uri()],
        check=True, capture_output=True,
    )
    html.unlink()


def dibujar(contenido, titulo: str, tema, destino: Path, resaltar: bool = True) -> None:
    consola = Console(record=True, width=ANCHO, file=open("/dev/null", "w"))
    consola.print(contenido, crop=True, highlight=resaltar)
    svg = destino.with_suffix(".svg")
    consola.save_svg(str(svg), title=titulo, theme=tema)
    a_png(svg, destino)
    svg.unlink()


def archivo(texto: str, tema_pygments: str) -> Syntax:
    return Syntax(texto, "toml", theme=tema_pygments, word_wrap=False, background_color="default")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default="gemma4:e4b")
    args = p.parse_args()
    SALIDA.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        entrada = tmp / "ejemplo.toml"
        entrada.write_text((AQUI / "ejemplo.toml").read_text())
        comando = [
            "python3", "toml-translator.py", "--api", "ollama", "--model", args.model,
            "--prompt", "prompts/generic-game-es.toml", "--glossary", "tools/capturas/glosario.toml",
            "--prefix", "es", "ejemplo.toml",
        ]
        r = subprocess.run(
            [sys.executable, str(RAIZ / "toml-translator.py"), *comando[2:-1], str(entrada)],
            cwd=RAIZ, capture_output=True, text=True, check=True,
        )
        # La ruta temporal no aporta nada en la imagen: se muestra relativa.
        salida = r.stdout.replace(str(tmp) + "/", "")
        traducido = (tmp / "es_ejemplo.toml").read_text()

        dibujar(Text.assemble((f"$ {' '.join(comando)}\n", "bold"), Text.from_ansi(salida)),
                "toml-translator", MONOKAI, SALIDA / "corrida.png", resaltar=False)
        dibujar(archivo(traducido, "friendly"), "es_ejemplo.toml", DEFAULT_TERMINAL_THEME,
                SALIDA / "traducido.png")
        original_png, traducido_png = tmp / "original.png", tmp / "traducido-oscuro.png"
        dibujar(archivo(entrada.read_text(), "friendly"), "ejemplo.toml → es_ejemplo.toml",
                DEFAULT_TERMINAL_THEME, original_png)
        dibujar(archivo(traducido, "monokai"), "ejemplo.toml → es_ejemplo.toml", MONOKAI, traducido_png)
        componer(Image.open(original_png), Image.open(traducido_png), 0.035, 3).save(
            SALIDA / "original-traducido.png", optimize=True
        )
    print("\n".join(sorted(x.name for x in SALIDA.glob("*.png"))))


if __name__ == "__main__":
    main()
