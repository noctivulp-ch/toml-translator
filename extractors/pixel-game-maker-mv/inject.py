#!/usr/bin/env python3
"""
inject.py — aplica las traducciones de vuelta a un juego Pixel Game Maker MV.

Uso:
  python inject.py /ruta/al/juego --locale es_ES
  python inject.py /ruta/al/juego --locale es_ES --set-default
  python inject.py /ruta/al/juego --locale es_ES --plain      # sin re-cifrar
  python inject.py /ruta/al/juego --locale es_ES --dry-run

Cómo inyecta
────────────
PGMMV guarda cada texto como {locale: cadena}. La traducción se AÑADE como un
idioma nuevo (`es_ES` por defecto) junto al original, que nunca se toca. Además:

  - añade el idioma a gameInformation.language
  - con --set-default, pone initialLocale al idioma nuevo para que el juego
    arranque traducido

Reversible: basta con volver a poner initialLocale, o restaurar el .bak.

Distribución
────────────
Pensado para repartir SOLO el TOML y este script, nunca el juego. Quien lo aplique
usa su propia copia — el project.json original ni se copia ni se comparte.

Seguridad
─────────
Crea `project.json.bak` la primera vez que toca el archivo, y verifica que lo escrito
se puede volver a leer antes de dar por buena la operación.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pgmmv

MARKER_RE = re.compile(r"\[(?:[A-Z][A-Z0-9]*|\d+)\]")


def parse_toml(path):
    """
    Parser del subconjunto TOML que emite el sistema. Mismo criterio que el
    traductor: preservar el archivo tal cual importa más que soportar TOML entero.
    """
    entries, cur = [], None
    ml_key, ml_buf, in_ml = None, [], False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if in_ml:
            if line.endswith('"""'):
                ml_buf.append(line[:-3])
                cur[ml_key] = "\n".join(ml_buf).lstrip("\n")
                in_ml, ml_key, ml_buf = False, None, []
            else:
                ml_buf.append(line)
            continue
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == "[[entry]]":
            if cur and cur.get("id"):
                entries.append(cur)
            cur = {}
            continue
        if cur is None:
            continue
        m = re.match(r'^(\w+)\s*=\s*"""$', s)
        if m:
            ml_key, ml_buf, in_ml = m.group(1), [], True
            continue
        m = re.match(r'^(\w+)\s*=\s*"(.*)"$', s)
        if m:
            cur[m.group(1)] = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
    if cur and cur.get("id"):
        entries.append(cur)
    return entries


def reconstruct(text, codes_str):
    """Revierte los marcadores a los códigos nativos y [BR] a saltos de línea."""
    out = text
    if codes_str:
        for pair in codes_str.split("|"):
            if "=" in pair:
                marker, code = pair.split("=", 1)
                out = out.replace(marker, code)
    return out.replace("[BR]", "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir", help="Carpeta raíz del juego")
    ap.add_argument("--toml", default=None,
                    help="TOML de traducción (default: <juego>/translation/texts.toml)")
    ap.add_argument("--locale", default="es_ES", help="Idioma destino (default: es_ES)")
    ap.add_argument("--set-default", action="store_true",
                    help="Arrancar el juego en el idioma nuevo")
    ap.add_argument("--plain", action="store_true",
                    help="Escribir sin cifrar (el cargador acepta ambos)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Informa de lo que haría sin escribir nada")
    args = ap.parse_args()

    candidates = list(Path(args.game_dir).glob("**/Resources/data"))
    if not candidates:
        print(f"ERROR: no encuentro Resources/data bajo {args.game_dir}")
        sys.exit(1)
    data_dir = candidates[0]

    toml_path = Path(args.toml) if args.toml else Path(args.game_dir) / "translation" / "texts.toml"
    if not toml_path.exists():
        print(f"ERROR: no existe {toml_path}")
        sys.exit(1)

    entries = parse_toml(toml_path)
    translated = {e["id"]: e for e in entries if e.get("translated", "").strip()}
    print(f"  {len(translated)} traducidos de {len(entries)} en {toml_path.name}")
    if not translated:
        print("  Nada que inyectar.")
        return

    project, key = pgmmv.read_project(data_dir=data_dir)
    print(f"  project.json {'cifrado' if key else 'sin cifrar'}")

    applied, missing, code_warn = 0, [], []
    for node, _path in pgmmv.iter_texts(project):
        e = translated.get(f"text:{node['id']}")
        if not e:
            continue
        final = reconstruct(e["translated"], e.get("codes", ""))
        src_markers = set(MARKER_RE.findall(e["original"]))
        left = set(MARKER_RE.findall(e["translated"]))
        if src_markers - left:
            code_warn.append((e["id"], sorted(src_markers - left)))
        node["text"][args.locale] = final
        applied += 1

    seen = {f"text:{n['id']}" for n, _ in pgmmv.iter_texts(project)}
    missing = [i for i in translated if i not in seen]

    info = project.setdefault("gameInformation", {})
    langs = info.setdefault("language", [])
    if args.locale not in langs:
        langs.append(args.locale)
    if args.set_default:
        project["initialLocale"] = args.locale
        info["mainLanguage"] = args.locale

    print(f"  Aplicados   : {applied}")
    if missing:
        print(f"  Sin destino : {len(missing)} ids del TOML no existen en el juego")
        for i in missing[:5]:
            print(f"      {i}")
    if code_warn:
        print(f"  AVISO: {len(code_warn)} traducciones perdieron marcadores:")
        for i, mk in code_warn[:5]:
            print(f"      {i}: falta {mk}")
    print(f"  Idiomas     : {langs}"
          + (f" | arranca en {args.locale}" if args.set_default else ""))

    if args.dry_run:
        print("\n  [DRY-RUN] no se ha escrito nada.")
        return

    target = data_dir / "project.json"
    bak = data_dir / "project.json.bak"
    if not bak.exists():
        bak.write_bytes(target.read_bytes())
        print(f"  Backup      : {bak.name}")

    write_key = None if args.plain else key
    size = pgmmv.write_project(project, target, write_key)

    # Verificar que lo escrito se vuelve a leer: un project.json corrupto deja el
    # juego sin arrancar, y el .bak solo sirve si alguien se da cuenta a tiempo.
    try:
        check, _ = pgmmv.read_project(data_dir=data_dir)
        assert check.get("initialLocale") is not None
        print(f"  Escrito     : {size:,} bytes ({'plano' if args.plain else 'cifrado'}) — verificado")
    except Exception as exc:
        target.write_bytes(bak.read_bytes())
        print(f"  ERROR al verificar ({exc}). Se restauró el backup.")
        sys.exit(1)


if __name__ == "__main__":
    main()
