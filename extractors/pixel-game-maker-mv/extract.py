#!/usr/bin/env python3
"""
extract.py — extrae el texto traducible de un juego Pixel Game Maker MV.

Uso:
  python extract.py /ruta/al/juego                    # descifra y extrae
  python extract.py /ruta/al/juego --locale en_US     # extrae otro idioma origen
  python extract.py --json project.json --out ./out   # sobre un JSON ya descifrado

Genera `<juego>/translation/texts.toml` con el formato TOML estándar del sistema.

Qué se extrae y qué no
──────────────────────
Solo `textList`, que es donde PGMMV guarda el texto que ve el jugador. El resto de
strings japoneses del proyecto NO son texto de juego:

  - `name`   — etiquetas del editor (26.823 en el juego analizado). Internas.
  - `memo`   — notas del desarrollador.
  - `databaseList` — tablas de balance numérico (HP por nivel, costes).

Extraerlos llenaría el TOML de ruido intraducible y arriesgaría romper el proyecto.

Localización nativa
───────────────────
PGMMV guarda cada texto como {locale: cadena}, así que traducir es AÑADIR un idioma
sin tocar el original. El inyector se apoya en eso: no sobreescribe nada.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pgmmv


# Códigos de formato de PGMMV. Se convierten a marcadores [BRACKETS] para que el
# modelo no los reordene ni los traduzca (ver docs/decisiones/0003).
#
# \C[#RRGGBB] abre color y \C[] lo cierra. Se numeran por orden de aparición
# dentro de cada texto, y el mapa inverso viaja en el campo `codes`.
COLOR_RE = re.compile(r"\\C\[[^\]]*\]")


def preprocess(text):
    """
    Devuelve (texto_limpio, codes) listos para el TOML.

    Los saltos de línea pasan a [BR] porque el traductor mapea UNA línea de
    respuesta por entrada: un salto real partiría la entrada en dos y descuadraría
    el lote entero.
    """
    codes = {}
    def repl(m):
        marker = f"[C{len(codes) + 1}]"
        codes[marker] = m.group(0)
        return marker
    clean = COLOR_RE.sub(repl, text)
    clean = clean.replace("\r\n", "\n").replace("\n", "[BR]")
    codes_str = "|".join(f"{k}={v}" for k, v in codes.items())
    return clean, codes_str


def toml_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir", nargs="?", help="Carpeta raíz del juego")
    ap.add_argument("--json", help="project.json ya descifrado")
    ap.add_argument("--locale", default=None,
                    help="Idioma de origen (default: mainLanguage del juego)")
    ap.add_argument("--out", default=None,
                    help="Directorio de salida (default: <juego>/translation)")
    args = ap.parse_args()

    if not args.game_dir and not args.json:
        ap.error("indica la carpeta del juego o --json")

    data_dir = None
    if args.game_dir:
        candidates = list(Path(args.game_dir).glob("**/Resources/data"))
        if not candidates:
            print(f"ERROR: no encuentro Resources/data bajo {args.game_dir}")
            print("  ¿Es un juego de Pixel Game Maker MV?")
            sys.exit(1)
        data_dir = candidates[0]
        print(f"  Datos: {data_dir}")

    project, key = pgmmv.read_project(data_dir=data_dir, json_path=args.json)
    print(f"  {'Descifrado' if key else 'Sin cifrar'}")

    langs, main_lang = pgmmv.game_locales(project)
    src = args.locale or main_lang or "ja_JP"
    print(f"  Idiomas del juego: {langs or '(ninguno declarado)'} | origen: {src}")

    entries = []
    skipped = 0
    for node, path in pgmmv.iter_texts(project):
        text = node["text"].get(src)
        if not text or not text.strip():
            skipped += 1
            continue
        clean, codes = preprocess(text)
        entries.append({
            "id": f"text:{node['id']}",
            "original": clean,
            "codes": codes,
            "context": " / ".join(path + [node.get("name", "")]).strip(" /"),
        })

    if not entries:
        print(f"ERROR: ningún texto en el idioma '{src}'. Prueba --locale con uno de {langs}")
        sys.exit(1)

    out_dir = Path(args.out) if args.out else Path(args.game_dir) / "translation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "texts.toml"

    # Preserva las traducciones ya hechas: solo añade ids nuevos, como el extractor
    # de RPG Maker XP.
    existing = {}
    if out_path.exists():
        prev = out_path.read_text(encoding="utf-8")
        for m in re.finditer(r'id = "([^"]+)"\n(?:.*\n)*?translated = "((?:[^"\\]|\\.)*)"',
                             prev):
            if m.group(2):
                existing[m.group(1)] = m.group(2)

    lines = [
        f"# Textos de {project.get('gameInformation', {}).get('title', '?')}"
        f" — Pixel Game Maker MV",
        f"# Idioma origen: {src} | Generado por extractors/pixel-game-maker-mv/extract.py",
        "# original = texto fuente | translated = dejar vacío para no traducir",
        "",
    ]
    for e in entries:
        lines.append("[[entry]]")
        lines.append(f'id = "{toml_escape(e["id"])}"')
        lines.append(f'original = "{toml_escape(e["original"])}"')
        lines.append(f'translated = "{existing.get(e["id"], "")}"')
        if e["codes"]:
            lines.append(f'codes = "{toml_escape(e["codes"])}"')
        if e["context"]:
            lines.append(f'context = "{toml_escape(e["context"])}"')
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    chars = sum(len(e["original"]) for e in entries)
    print(f"\n━━━ Extracción completa ━━━")
    print(f"  Textos      : {len(entries)}  ({chars:,} caracteres)")
    print(f"  Vacíos      : {skipped} omitidos")
    print(f"  Reutilizados: {len(existing)} ya traducidos")
    print(f"  Salida      : {out_path}")


if __name__ == "__main__":
    main()
