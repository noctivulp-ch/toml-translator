#!/usr/bin/env python3
"""
toml-translator — traduce archivos TOML de extracción con IA local o cloud

Uso:
  python toml-translator.py --api ollama --prompt prompts/pokemon-es.toml translation/*.toml
  python toml-translator.py --api deepl  --prompt prompts/generic-game-es.toml --output out/ --prefix es input.toml
  python toml-translator.py --api claude --prompt prompts/my-prompt.toml --output ./translated --prefix es_LA *.toml

Flags:
  --api      ollama | deepl | openai | claude  (requerido)
  --prompt   archivo TOML de configuración del prompt (requerido)
  --output   directorio de salida (default: mismo directorio que el input)
  --prefix   prefijo del archivo de salida — "es" → "es_maps.toml"
  --model    modelo Ollama (omitir = menú interactivo)
  --batch    strings por llamada (default: 10 ollama / 50 cloud)
  --dry-run  muestra los primeros 5 strings sin escribir nada
  --num-gpu  capas del modelo en GPU (default: 99)
  --num-ctx  ventana de contexto Ollama (default: 8192)
  --refs     idiomas de referencia: auto | none | "ja,fr"  (default: auto)
  --glossary TOML de glosario de términos; repetible
  --routing  TOML de enrutado por contenido (modelo distinto según la línea)
"""

import argparse
import re
import sys
import os
import json
import subprocess
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Carga del prompt TOML
# ─────────────────────────────────────────────────────────────────────────────

def _load_toml(path):
    """Carga un TOML con tomllib (3.11+) o tomli. Aborta si no hay ninguno."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            print("ERROR: Se necesita Python 3.11+ o 'pip install tomli' para leer TOML.")
            sys.exit(1)
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_prompt_toml(path):
    """
    Lee un archivo TOML de configuración de prompt.

    Formato esperado:
      [meta]
      language        = "español"   # idioma destino, legible
      source_language = "EN"        # etiqueta del campo `original` (para --refs)
      deepl_target    = "ES"        # código DeepL (opcional)

      [system]
      text = \"""...system prompt..."\""

      [[glossary]]                  # opcional — ver load_glossary()
      source = "fainted"
      target = "se debilitó"

    Devuelve un dict de configuración.
    """
    data = _load_toml(path)

    system_text = data.get("system", {}).get("text", "").strip()
    if not system_text:
        print(f"ERROR: El archivo de prompt '{path}' no tiene [system] text.")
        sys.exit(1)

    meta = data.get("meta", {})
    style = meta.get("style", "chat")
    if style not in ("chat", "translategemma"):
        print(f"ERROR: [meta] style desconocido: {style!r} (usa 'chat' o 'translategemma')")
        sys.exit(1)

    return {
        "system":       system_text,
        "style":        style,
        "language":     meta.get("language", "español"),
        "source_label": meta.get("source_language", "EN"),
        "deepl_target": meta.get("deepl_target", None),
        # Solo los usa style="translategemma", que nombra los idiomas en el prompt.
        "src_name":     meta.get("source_name", "English"),
        "src_code":     meta.get("source_code", "en"),
        "tgt_name":     meta.get("target_name", "Spanish"),
        "tgt_code":     meta.get("target_code", "es"),
        "glossary":     _normalize_glossary(data.get("glossary", []), path),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Glosario de referencia
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_glossary(raw_terms, origin):
    """Valida y normaliza una lista de [[term]] / [[glossary]] del TOML."""
    terms = []
    for t in raw_terms:
        source = str(t.get("source", "")).strip()
        target = str(t.get("target", "")).strip()
        if not source or not target:
            print(f"  Aviso: término incompleto ignorado en {origin}: {t!r}")
            continue
        terms.append({
            "source": source,
            "target": target,
            "note":   str(t.get("note", "")).strip(),
            # Palabra completa si el término es alfanumérico; sin límites si tiene
            # símbolos o espacios, donde \b no se comporta como uno espera.
            "re": re.compile(
                (r"\b" + re.escape(source) + r"\b") if source.replace(" ", "").isalnum()
                else re.escape(source),
                re.IGNORECASE,
            ),
        })
    return terms


def load_glossary(paths):
    """
    Carga uno o más TOML de glosario y los concatena.

    Formato (ambas cabeceras valen):
      [[term]]
      source = "fainted"
      target = "se debilitó"
      note   = "nunca 'se desmayó'"     # opcional

    Los duplicados por `source` se resuelven a favor del último archivo cargado,
    de modo que un glosario específico puede sobrescribir a uno general.
    """
    by_source = {}
    for path in paths or []:
        data = _load_toml(path)
        raw = data.get("term", []) or data.get("glossary", [])
        if not raw:
            print(f"  Aviso: '{path}' no contiene [[term]] ni [[glossary]].")
        for term in _normalize_glossary(raw, path):
            by_source[term["source"].lower()] = term
    return list(by_source.values())


def relevant_terms(glossary, texts, limit=40):
    """
    Filtra el glosario a los términos que aparecen en este lote.

    Existe por la ventana de contexto: inyectar un glosario de 500 términos en cada
    llamada con --num-ctx 2048 desplaza el texto a traducir fuera de la ventana.
    """
    if not glossary:
        return []
    blob = "\n".join(texts)
    hits = [t for t in glossary if t["re"].search(blob)]
    return hits[:limit]


def format_glossary(terms):
    lines = ["GLOSSARY — use these exact translations:"]
    for t in terms:
        line = f"  {t['source']} -> {t['target']}"
        if t["note"]:
            line += f"   ({t['note']})"
        lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Enrutado por contenido
#
# Distintos modelos fallan de formas distintas, y la diferencia NO es la calidad
# general sino QUÉ tipo de línea manejan bien. Medido en docs/benchmarks.md:
# translategemma:4b es el más rápido y el que menos contexto gasta, pero reescribe
# el contenido explícito ("fucked her" → "la besaba") en el 75% de los casos, sin
# rechazar ni dejar nada sin traducir. gemma4:e2b es fiel (0%) pero más lento.
#
# Por eso el criterio de enrutado es el CONTENIDO de la línea, no su longitud:
# mandar cada string al modelo que no lo va a estropear.
# ─────────────────────────────────────────────────────────────────────────────

def load_routing(path, prompt_dir=None):
    """
    Carga un TOML de enrutado.

      [[route]]
      name   = "explícito"
      model  = "gemma4:e2b"
      prompt = "prompts/pokemon-es.toml"
      match  = "\\b(fuck|cock|cum)\\b"   # regex sobre `original`, sin distinguir mayúsculas
      min_chars = 120                    # opcional
      max_chars = 400                    # opcional
      min_markers = 2                    # opcional

    Se evalúan EN ORDEN y gana la primera que casa. La última ruta sin ninguna
    condición actúa de fallback; si no la hay, las entradas sin ruta usan el
    --model y --prompt de la línea de comandos.

    Cada ruta carga su propio prompt, porque el estilo va atado al modelo:
    translategemma necesita style="translategemma" y gemma necesita "chat".
    """
    data = _load_toml(path)
    base = Path(prompt_dir) if prompt_dir else Path(path).parent
    routes = []
    for r in data.get("route", []):
        prompt_path = r.get("prompt")
        if prompt_path and not Path(prompt_path).exists():
            candidate = base / prompt_path
            if candidate.exists():
                prompt_path = str(candidate)
        routes.append({
            "name":        r.get("name", r.get("model", "?")),
            "model":       r.get("model"),
            "cfg":         load_prompt_toml(prompt_path) if prompt_path else None,
            "batch":       r.get("batch"),
            "num_ctx":     r.get("num_ctx"),
            "match":       re.compile(r["match"], re.IGNORECASE) if r.get("match") else None,
            # Los extractores guardan en `context` la ruta del editor (carpeta,
            # nombre de evento). Suele ser una señal más fiable que el propio
            # texto: una carpeta "アダルトセリフ" delata la escena entera.
            "match_context": re.compile(r["match_context"], re.IGNORECASE)
                             if r.get("match_context") else None,
            "min_chars":   r.get("min_chars"),
            "max_chars":   r.get("max_chars"),
            "min_markers": r.get("min_markers"),
        })
    if not routes:
        print(f"ERROR: '{path}' no contiene ninguna [[route]].")
        sys.exit(1)
    return routes, load_classifier(data, routes)


# ─────────────────────────────────────────────────────────────────────────────
# Clasificador — red de seguridad detrás de las regex de enrutado
#
# Las regex solo detectan el vocabulario que alguien listó. Un término no previsto
# cae en el modelo rápido y sale reescrito sin dejar rastro (ISSUE-010).
#
# El clasificador revisa lo que las regex NO marcaron y reenruta lo que resulte
# sensible. La asimetría lo hace seguro: un falso negativo deja las cosas como
# estaban (la regex ya había fallado ahí), y un falso positivo solo cuesta tiempo.
# Por eso el prompt le pide que ante la duda marque sensible.
#
# Usar un modelo SIN censura para clasificar es deliberado: uno censurado puede
# negarse a etiquetar justo el contenido que interesa detectar.
# ─────────────────────────────────────────────────────────────────────────────

CLASSIFIER_SYSTEM = """You label lines of video game dialogue for a translation pipeline.
{context}This is a content-routing task: the labels decide which translation model handles each
line. You are not translating or generating anything.

For each numbered line answer with EXACTLY ONE word, keeping the same numbering:

  EXPLICIT — sexual content of any kind, including euphemism and innuendo
  VIOLENT  — graphic violence, death, injury, abuse, suicide
  SAFE     — everything else

If a line could plausibly be EXPLICIT or VIOLENT, label it as such. Mislabeling a
mild line costs nothing; missing a strong one breaks the pipeline.

Output only the numbered labels. No explanations."""

LABEL_RE = re.compile(r"\b(EXPLICIT|VIOLENT|SAFE)\b", re.IGNORECASE)


def classifier_system(context=None):
    """
    Inserta el contexto del juego en el prompt del clasificador.

    Medido (docs/benchmarks.md, resultado 6): decirle que el juego es adulto y que el
    eufemismo es la norma sube el recall del 82% al 93%, a cambio de bajar la precisión
    del 87% al 75%. Es el intercambio correcto — un falso positivo solo cuesta tiempo,
    un falso negativo cuesta texto reescrito sin dejar rastro.

    Sin contexto el modelo juzga cada línea aislada, y "the bed creaked all night long"
    le parece inocua.
    """
    return CLASSIFIER_SYSTEM.format(
        context=(context.strip() + "\n\n") if context else "")


def load_classifier(data, routes):
    """
    Lee la tabla [classifier] de un TOML de enrutado.

      [classifier]
      model  = "Librellama/gemma4:e2b-Uncensored"
      route  = "explicito"        # ruta destino de lo que resulte sensible
      checks = ["general"]        # rutas a revisar; por defecto, las no confiables
      batch  = 40
    """
    c = data.get("classifier")
    if not c:
        return None
    target = c.get("route")
    if target and not any(r["name"] == target for r in routes):
        print(f"ERROR: [classifier] route = {target!r} no existe entre las rutas.")
        sys.exit(1)
    return {
        "model":  c.get("model"),
        "route":  target,
        "checks": c.get("checks"),
        "batch":  c.get("batch", 40),
        "context": c.get("context"),
        "labels": [l.upper() for l in c.get("labels", ["EXPLICIT", "VIOLENT"])],
    }


def classify_batch(texts, model, num_gpu=99, num_ctx=8192, max_retries=1, context=None):
    """
    Devuelve una etiqueta por texto, o None donde no se pudo clasificar.

    Ante un fallo devuelve Nones y no reenruta nada: el clasificador es una mejora
    oportunista, no debe hacer caer la traducción.
    """
    body = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    messages = [{"role": "system", "content": classifier_system(context)},
                {"role": "user", "content": body}]
    for attempt in range(max_retries + 1):
        try:
            raw = translate_ollama(messages, model, num_gpu=num_gpu, num_ctx=num_ctx)
            lines = parse_numbered_response(raw, len(texts))
            if lines is None:
                continue
            out = []
            for l in lines:
                m = LABEL_RE.search(l)
                out.append(m.group(1).upper() if m else None)
            return out
        except Exception as e:
            if attempt >= max_retries:
                print(f"    Clasificador falló: {e}")
    return [None] * len(texts)


def apply_classifier(groups, classifier, routes, num_gpu, num_ctx):
    """
    Reenruta las entradas sensibles que las regex no detectaron.

    Recibe y devuelve la lista [(ruta, entradas)] de group_by_route.
    """
    target = next((r for r in routes if r["name"] == classifier["route"]), None)
    if target is None:
        return groups, 0

    def reviewable(route):
        if classifier["checks"] is not None:
            return route is not None and route["name"] in classifier["checks"]
        # Por defecto: revisar todo lo que no vaya ya a la ruta destino.
        return route is None or route["name"] != classifier["route"]

    moved = []
    new_groups = []
    for route, items in groups:
        if not reviewable(route):
            new_groups.append((route, items))
            continue
        keep = []
        for start in range(0, len(items), classifier["batch"]):
            chunk = items[start:start + classifier["batch"]]
            labels = classify_batch([e["original"] for e in chunk],
                                    classifier["model"], num_gpu, num_ctx,
                                    context=classifier.get("context"))
            for entry, label in zip(chunk, labels):
                if label in classifier["labels"]:
                    moved.append(entry)
                else:
                    keep.append(entry)
        if keep:
            new_groups.append((route, keep))

    if moved:
        merged = False
        for i, (route, items) in enumerate(new_groups):
            if route is target:
                new_groups[i] = (route, items + moved)
                merged = True
                break
        if not merged:
            new_groups.insert(0, (target, moved))
    return new_groups, len(moved)


def route_matches(route, entry):
    text = entry["original"]
    if route["match"] and not route["match"].search(text):
        return False
    if route["match_context"] and not route["match_context"].search(entry.get("context", "")):
        return False
    if route["min_chars"] is not None and len(text) < route["min_chars"]:
        return False
    if route["max_chars"] is not None and len(text) > route["max_chars"]:
        return False
    if route["min_markers"] is not None and len(find_markers(text)) < route["min_markers"]:
        return False
    return True


def group_by_route(entries, routes):
    """
    Reparte las entradas entre rutas preservando el orden dentro de cada grupo.
    Devuelve [(ruta | None, [entradas])]; None = usar la configuración por defecto.

    Agrupar no altera el archivo de salida: write_translated indexa por `id`, no
    por posición.
    """
    buckets = {}
    for e in entries:
        idx = next((i for i, r in enumerate(routes) if route_matches(r, e)), None)
        buckets.setdefault(idx, []).append(e)
    out = [(routes[i] if i is not None else None, v)
           for i, v in sorted(buckets.items(), key=lambda kv: (kv[0] is None, kv[0]))]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Validación de markers
# ─────────────────────────────────────────────────────────────────────────────

# Formato de marker: [JUGADOR], [1], [V3], [BR], etc.
# Los extractores normalizan los códigos de formato del motor a este esquema.
MARKER_RE = re.compile(r'\[(?:[A-Z][A-Z0-9]*|\d+|V\d+)\]')


def find_markers(text):
    return set(MARKER_RE.findall(text))


def validate_markers(original, translated):
    return sorted(find_markers(original) - find_markers(translated))


# ─────────────────────────────────────────────────────────────────────────────
# Parser TOML (formato fijo del sistema de extracción)
# ─────────────────────────────────────────────────────────────────────────────

def parse_toml(path):
    entries = []
    current = None
    in_multiline = False
    ml_key = None
    ml_buf = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            line_stripped = line.rstrip("\n")

            if in_multiline:
                if line_stripped.endswith('"""'):
                    ml_buf.append(line_stripped[:-3])
                    current[ml_key] = "\n".join(ml_buf).lstrip("\n")
                    in_multiline = False
                    ml_key = None
                    ml_buf = []
                else:
                    ml_buf.append(line_stripped)
                continue

            stripped = line_stripped.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped == "[[entry]]":
                if current and current.get("id"):
                    entries.append(current)
                current = {}
                continue

            if current is None:
                continue

            m = re.match(r'^(\w+)\s*=\s*"""$', stripped)
            if m:
                ml_key = m.group(1)
                ml_buf = []
                in_multiline = True
                continue

            m = re.match(r'^(\w+)\s*=\s*"""(.*?)"""$', stripped)
            if m:
                current[m.group(1)] = m.group(2)
                continue

            m = re.match(r'^(\w+)\s*=\s*"(.*)"$', stripped)
            if m:
                val = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
                current[m.group(1)] = val
                continue

            m = re.match(r'^(\w+)\s*=\s*(-?\d+)$', stripped)
            if m:
                current[m.group(1)] = int(m.group(2))
                continue

    if current and current.get("id"):
        entries.append(current)
    return entries


def write_translated(input_path, entries, output_path=None):
    """
    Escribe el TOML con los campos `translated` actualizados.
    Si output_path es None, modifica el archivo original (in-place).
    Si output_path es distinto, escribe una copia nueva sin alterar el original.
    """
    target = Path(output_path) if output_path else Path(input_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    lookup = {e["id"]: e.get("translated", "") for e in entries}

    with open(input_path, encoding="utf-8") as f:
        raw_lines = f.readlines()

    out = []
    in_entry = False
    current_id = None

    for line in raw_lines:
        stripped = line.strip()

        if stripped == "[[entry]]":
            in_entry = True
            current_id = None
            out.append(line)
            continue

        if in_entry and stripped.startswith("id = "):
            m = re.match(r'^id\s*=\s*"([^"]+)"', stripped)
            if m:
                current_id = m.group(1)
            out.append(line)
            continue

        if in_entry and current_id and stripped.startswith("translated = "):
            new_val = lookup.get(current_id, "")
            if "\n" in new_val:
                escaped = new_val.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'translated = """\n{escaped}"""\n')
            else:
                escaped = new_val.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'translated = "{escaped}"\n')
            continue

        out.append(line)

    with open(target, "w", encoding="utf-8") as f:
        f.writelines(out)


def resolve_output_path(input_path, output_dir, prefix):
    """
    Calcula la ruta de salida para un archivo de entrada.

    Sin output_dir ni prefix → None (in-place)
    Con prefix "es" e input "translation/maps.toml" → <output_dir>/es_maps.toml
    """
    if not output_dir and not prefix:
        return None

    src = Path(input_path)
    out_dir = Path(output_dir) if output_dir else src.parent
    out_name = f"{prefix}_{src.name}" if prefix else src.name
    return out_dir / out_name


# ─────────────────────────────────────────────────────────────────────────────
# Selección de modelo Ollama
# ─────────────────────────────────────────────────────────────────────────────

VRAM_GB = 4.0


def list_ollama_models():
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=8
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().splitlines()
        models = []
        for line in lines[1:]:
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            size_gb = None
            for j, part in enumerate(parts[1:], 1):
                try:
                    val = float(part)
                    unit = parts[j + 1] if j + 1 < len(parts) else ""
                    if unit == "GB":
                        size_gb = val
                    elif unit == "MB":
                        size_gb = val / 1024
                    break
                except ValueError:
                    continue
            models.append((name, size_gb))
        return models
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def select_ollama_model(cli_model=None):
    models = list_ollama_models()
    if not models:
        print("ERROR: Ollama no disponible o sin modelos instalados.")
        print("  Instala: https://ollama.com  |  Descarga: ollama pull qwen3:4b")
        sys.exit(1)

    if cli_model:
        for name, _ in models:
            if name == cli_model or name.startswith(cli_model):
                print(f"  Usando modelo: {name}")
                return name
        print(f"Modelo '{cli_model}' no encontrado.")

    print("\nModelos Ollama disponibles:")
    for i, (name, size_gb) in enumerate(models):
        if size_gb is not None:
            if size_gb <= VRAM_GB:
                note = f"  ← GPU completo ({size_gb:.1f} GB)"
            else:
                pct = int(VRAM_GB / size_gb * 100)
                note = f"  ← offload parcial ~{pct}% ({size_gb:.1f} GB > {VRAM_GB:.0f} GB VRAM)"
        else:
            note = ""
        print(f"  {i+1}. {name}{note}")

    while True:
        try:
            choice = input("Selecciona un número: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                return models[idx][0]
        except (ValueError, KeyboardInterrupt):
            pass
        print("Selección inválida.")


# ─────────────────────────────────────────────────────────────────────────────
# Backends de traducción
# ─────────────────────────────────────────────────────────────────────────────

# Campos de referencia: `original_ja`, `original_fr`… El sufijo es la etiqueta
# de idioma que se le muestra al modelo. `original` a secas es la fuente principal.
REF_FIELD_RE = re.compile(r"^original_(\w+)$")


def discover_ref_langs(entries):
    """
    Devuelve las etiquetas de idioma de referencia presentes en las entradas,
    en orden estable (alfabético). Funciona con 1, 2 o 5 idiomas sin configuración.
    """
    langs = set()
    for e in entries:
        for key in e:
            m = REF_FIELD_RE.match(key)
            if m and str(e.get(key, "")).strip():
                langs.add(m.group(1))
    return sorted(langs)


def resolve_ref_langs(refs_mode, entries):
    """
    refs_mode: "auto" (autodetectar), "none" (desactivar) o "ja,fr" (lista explícita).
    Una lista explícita se filtra a los idiomas realmente presentes.
    """
    if refs_mode == "none":
        return []
    available = discover_ref_langs(entries)
    if refs_mode == "auto":
        return available
    wanted = [x.strip().lower() for x in refs_mode.split(",") if x.strip()]
    missing = [w for w in wanted if w not in available]
    if missing:
        print(f"  Aviso: sin datos para los idiomas de referencia: {', '.join(missing)}")
    return [w for w in wanted if w in available]


def entry_refs(entry, ref_langs, source_label):
    """Devuelve [(etiqueta, texto)] para una entrada: la fuente y sus referencias."""
    out = [(source_label, entry["original"])]
    for lang in ref_langs:
        val = str(entry.get(f"original_{lang}", "")).strip()
        if val:
            out.append((lang.upper(), val))
    return out


def make_user_prompt(entries, ref_langs=(), source_label="EN", glossary_terms=()):
    """
    Construye el mensaje de usuario.

    Sin referencias ni glosario produce exactamente el formato original:
        1. Welcome home, [JUGADOR]!

    Con referencias, cada entrada ocupa varias líneas pero conserva UN solo número:
        1. [EN] Welcome home, [JUGADOR]!
           [JA] おかえりなさい、[JUGADOR]！

    La respuesta esperada sigue siendo una línea numerada por entrada.
    """
    blocks = []
    for i, e in enumerate(entries):
        if not ref_langs:
            blocks.append(f"{i+1}. {e['original']}")
            continue
        variants = entry_refs(e, ref_langs, source_label)
        head = f"{i+1}. [{variants[0][0]}] {variants[0][1]}"
        rest = [f"   [{lab}] {txt}" for lab, txt in variants[1:]]
        blocks.append("\n".join([head] + rest))

    body = "\n".join(blocks)

    parts = []
    if glossary_terms:
        parts.append(format_glossary(glossary_terms))
    if ref_langs:
        parts.append(
            f"Each numbered item shows the SAME line in several languages "
            f"([{source_label}] is the source; the others are existing official "
            f"translations). Use them together to resolve ambiguity, then output "
            f"ONE translated line per number."
        )
    parts.append("TEXTS:" if parts else "")
    parts.append(body)
    return "\n\n".join(x for x in parts if x)


def strip_lang_tag(line, labels):
    """
    Quita la etiqueta de idioma que el modelo copia al principio de su respuesta.

    Con --refs cada entrada se envía como "1. [JA] texto", y varios modelos
    devuelven "[JA] OPCIÓN...". Detectado traduciendo un juego real.

    Solo se recortan las etiquetas que ESTA llamada envió: un patrón genérico de
    dos letras entre corchetes se comería marcadores legítimos como [BR].
    """
    for lab in labels:
        pref = f"[{lab}]"
        if line.lstrip().upper().startswith(pref.upper()):
            return line.lstrip()[len(pref):].lstrip()
    return line


def parse_numbered_response(raw, count):
    ORDINAL = re.compile(r'^\s*\{?\d+\}?[\.\)\-\s]\s*(.*)')
    lines = []
    for line in raw.strip().splitlines():
        m = ORDINAL.match(line)
        if m and m.group(1).strip():
            lines.append(m.group(1).strip())
    if len(lines) == count:
        return lines
    fallback = []
    for l in raw.strip().splitlines():
        l = l.strip()
        if not l:
            continue
        l = ORDINAL.sub(r'\1', l).strip() if ORDINAL.match(l) else l
        if l:
            fallback.append(l)
    if len(fallback) == count:
        return fallback
    return None


# Plantilla oficial de TranslateGemma (ollama.com/library/translategemma).
# El modelo se entrenó con ESTA redacción y con exactamente dos líneas en blanco
# antes del texto; alterarla degrada la calidad, así que se reproduce literal.
TRANSLATEGEMMA_TEMPLATE = (
    "You are a professional {src_name} ({src_code}) to {tgt_name} ({tgt_code}) "
    "translator. Your goal is to accurately convey the meaning and nuances of the "
    "original {src_name} text while adhering to {tgt_name} grammar, vocabulary, and "
    "cultural sensitivities.\n"
    "Produce only the {tgt_name} translation, without any additional explanations or "
    "commentary. Please translate the following {src_name} text into {tgt_name}:"
)


def build_messages(cfg, body):
    """
    Construye los mensajes según el estilo del prompt.

    "chat" (default): system + user. Lo que espera cualquier modelo instruct.

    "translategemma": un solo mensaje de usuario. Los modelos TranslateGemma no
    reciben system prompt (su plantilla de chat fusiona system y user en el mismo
    turno) y esperan la instrucción canónica seguida de dos líneas en blanco.
    Las reglas del [system] text se insertan como líneas extra ANTES de esas dos
    líneas en blanco, para no romper la separación instrucción/texto.
    """
    if cfg["style"] == "translategemma":
        head = TRANSLATEGEMMA_TEMPLATE.format(
            src_name=cfg["src_name"], src_code=cfg["src_code"],
            tgt_name=cfg["tgt_name"], tgt_code=cfg["tgt_code"],
        )
        extra = cfg["system"].strip()
        instruction = f"{head}\n{extra}" if extra else head
        return [{"role": "user", "content": f"{instruction}\n\n\n{body}"}]

    return [
        {"role": "system", "content": cfg["system"]},
        {"role": "user",   "content": body},
    ]


def translate_ollama(messages, model, num_gpu=99, num_ctx=2048):
    import urllib.request

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "options": {"num_gpu": num_gpu, "num_ctx": num_ctx},
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["message"]["content"]


def translate_openai(messages, system):
    import urllib.request
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("ERROR: OPENAI_API_KEY no configurada.")
        sys.exit(1)

    payload = json.dumps({
        "model": "gpt-4o-mini",
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def translate_deepl(texts, deepl_target):
    import urllib.request, urllib.parse
    api_key = os.environ.get("DEEPL_API_KEY", "")
    if not api_key:
        print("ERROR: DEEPL_API_KEY no configurada.")
        sys.exit(1)

    url = ("https://api-free.deepl.com/v2/translate"
           if api_key.endswith(":fx")
           else "https://api.deepl.com/v2/translate")

    translations = []
    for text in texts:
        data = urllib.parse.urlencode({"text": text, "target_lang": deepl_target}).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        translations.append(result["translations"][0]["text"])
    return "\n".join(f"{i+1}. {t}" for i, t in enumerate(translations))


def translate_claude(body, system):
    import urllib.request
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada.")
        sys.exit(1)

    payload = json.dumps({
        "model": "claude-sonnet-5-20251001",
        "max_tokens": 4096,
        "system": system,
        "messages": [{"role": "user", "content": body}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json",
                 "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["content"][0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# Motor principal
# ─────────────────────────────────────────────────────────────────────────────

class FatalBackendError(Exception):
    """
    Error que ningún reintento va a arreglar: falta de VRAM, modelo inexistente,
    credenciales inválidas. Aborta la corrida en vez de repetir el ciclo por cada
    lote del archivo.
    """


# Firmas de error no transitorio. Reintentar estas es tiempo perdido: con un modelo
# que no cabe en VRAM, cada lote gastaba 3 intentos para terminar sin traducir nada
# y con un errors.log que no mencionaba la causa real (ISSUE-009).
FATAL_PATTERNS = [
    ("out of memory",        "El modelo no cabe en la VRAM disponible"),
    ("cudamalloc",           "El modelo no cabe en la VRAM disponible"),
    ("unable to allocate",   "El modelo no cabe en la VRAM disponible"),
    ("failed to allocate",   "El modelo no cabe en la VRAM disponible"),
    ("model not found",      "El modelo no existe en Ollama"),
    ("model requires more system memory", "El modelo no cabe en la RAM disponible"),
    ("invalid api key",      "Credenciales inválidas"),
    ("incorrect api key",    "Credenciales inválidas"),
    ("authentication",       "Credenciales inválidas"),
]


def classify_error(exc):
    """Devuelve una explicación si el error es irrecuperable, o None si conviene reintentar."""
    text = str(exc).lower()
    body = ""
    if hasattr(exc, "read"):
        try:
            body = exc.read().decode("utf-8", "replace").lower()
        except Exception:
            body = ""
    blob = text + " " + body
    for needle, reason in FATAL_PATTERNS:
        if needle in blob:
            return reason, (body or text)[:300]
    return None


def translate_batch(batch, api, model, cfg, ref_langs=(), glossary=(),
                    num_gpu=99, num_ctx=2048, max_retries=2):
    """
    Traduce un lote de entradas. Devuelve siempre una lista de len(batch):
    la traducción, o None en las posiciones que fallaron.
    """
    texts = [e["original"] for e in batch]
    system = cfg["system"]
    terms = relevant_terms(glossary, texts)
    body = make_user_prompt(batch, ref_langs, cfg["source_label"], terms)
    messages = build_messages(cfg, body)

    for attempt in range(max_retries + 1):
        try:
            if api == "ollama":
                raw = translate_ollama(messages, model,
                                       num_gpu=num_gpu, num_ctx=num_ctx)
            elif api == "openai":
                raw = translate_openai(messages, system)
            elif api == "deepl":
                # DeepL no acepta prompt: ignora refs y glosario por diseño.
                raw = translate_deepl(texts, cfg["deepl_target"] or "ES")
            elif api == "claude":
                # La API de Claude lleva el system aparte, no como mensaje.
                raw = translate_claude(body, system)
            else:
                raise ValueError(f"API desconocida: {api}")

            lines = parse_numbered_response(raw, len(texts))
            if lines is None:
                if attempt < max_retries:
                    continue
                return [None] * len(texts)
            if ref_langs:
                labels = {cfg["source_label"]} | {l.upper() for l in ref_langs}
                lines = [strip_lang_tag(l, labels) for l in lines]
            return lines

        except FatalBackendError:
            raise
        except Exception as e:
            fatal = classify_error(e)
            if fatal:
                reason, detail = fatal
                raise FatalBackendError(f"{reason}\n    {detail}") from e
            if attempt < max_retries:
                print(f"    Reintento ({attempt+1}/{max_retries}): {e}")
            else:
                print(f"    Fallo definitivo: {e}")
                return [None] * len(texts)


def process_file(path, api, model, cfg, batch_size, dry_run,
                 num_gpu, num_ctx, output_path, refs_mode="auto", glossary=(),
                 routes=None, classifier=None):
    print(f"\nProcesando: {Path(path).name}")
    if output_path:
        print(f"  → {output_path}")

    entries = parse_toml(path)
    pending = [e for e in entries if not e.get("translated")]

    if not pending:
        print("  Sin entradas pendientes.")
        return 0, 0, 0

    ref_langs = resolve_ref_langs(refs_mode, pending)
    if ref_langs:
        print(f"  Idiomas de referencia: {', '.join(l.upper() for l in ref_langs)}")

    print(f"  {len(pending)} pendientes de {len(entries)} totales")

    groups = group_by_route(pending, routes) if routes else [(None, pending)]
    if routes:
        print("  Enrutado por regex:")
        for route, items in groups:
            label = f"{route['name']} → {route['model']}" if route else "(por defecto)"
            print(f"    {len(items):>5}  {label}")

    if routes and classifier and not dry_run:
        to_check = sum(len(i) for r, i in groups
                       if classifier["checks"] is None
                       or (r is not None and r["name"] in classifier["checks"]))
        print(f"  Clasificando {to_check} entradas con {classifier['model']}...")
        groups, moved = apply_classifier(groups, classifier, routes, num_gpu, num_ctx)
        print(f"  Clasificador reenrutó {moved} entradas que las regex no detectaron")
        if moved:
            for route, items in groups:
                label = f"{route['name']} → {route['model']}" if route else "(por defecto)"
                print(f"    {len(items):>5}  {label}")

    if dry_run:
        for route, items in groups:
            rcfg = (route["cfg"] if route and route["cfg"] else cfg)
            terms = relevant_terms(glossary, [e["original"] for e in items[:5]])
            head = f"  ── {route['name']} ──" if route else "  ── Prompt de ejemplo (primeras 5) ──"
            print(head)
            preview = make_user_prompt(items[:5], ref_langs, rcfg["source_label"], terms)
            for line in build_messages(rcfg, preview)[-1]["content"].splitlines():
                print(f"  │ {line}")
        return 0, 0, 0

    translated_count = 0
    failed_count = 0
    last_saved = 0
    error_log = Path(path).parent / "errors.log"
    SAVE_EVERY = 50

    done = 0
    for route, items in groups:
        r_model = (route["model"] if route and route["model"] else model)
        r_cfg   = (route["cfg"]   if route and route["cfg"]   else cfg)
        r_batch = (route["batch"] if route and route["batch"] else batch_size)
        r_ctx   = (route["num_ctx"] if route and route["num_ctx"] else num_ctx)

        for batch_start in range(0, len(items), r_batch):
            batch = items[batch_start:batch_start + r_batch]

            try:
                results = translate_batch(batch, api, r_model, r_cfg,
                                          ref_langs=ref_langs, glossary=glossary,
                                          num_gpu=num_gpu, num_ctx=r_ctx)
            except FatalBackendError as exc:
                # Guardar lo traducido hasta aquí antes de salir: la corrida se
                # reanuda sola en la siguiente ejecución.
                print()
                print(f"  ERROR IRRECUPERABLE con {r_model}: {exc}")
                if translated_count:
                    write_translated(path, entries, output_path)
                    print(f"  Guardadas {translated_count} traducciones antes de abortar.")
                raise

            for entry, result in zip(batch, results):
                if result is None:
                    failed_count += 1
                    with open(error_log, "a", encoding="utf-8") as f:
                        f.write(f"FAIL {entry['id']}: {entry['original'][:80]}\n")
                    continue

                missing = validate_markers(entry["original"], result)
                if missing:
                    with open(error_log, "a", encoding="utf-8") as f:
                        f.write(f"CODES {entry['id']}: missing {missing}\n")

                entry["translated"] = result
                translated_count += 1

            # Comparar contra el último guardado, no `% SAVE_EVERY`: el contador
            # avanza a saltos (solo cuenta éxitos) y podría no pisar nunca un múltiplo.
            if translated_count - last_saved >= SAVE_EVERY:
                write_translated(path, entries, output_path)
                last_saved = translated_count

            done += len(batch)
            print(f"  {done}/{len(pending)} procesados...", end="\r")

    print()
    write_translated(path, entries, output_path)
    print(f"  OK: {translated_count} traducidos, {failed_count} fallidos")
    return translated_count, failed_count, len(pending)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Traductor automático de TOML de extracción")
    parser.add_argument("files",    nargs="+",  help="Archivos TOML de entrada")
    parser.add_argument("--api",    required=True,
                        choices=["ollama", "deepl", "openai", "claude"])
    parser.add_argument("--prompt", required=True,
                        help="Archivo TOML de configuración del prompt")
    parser.add_argument("--output", default=None,
                        help="Directorio de salida (default: mismo que el input)")
    parser.add_argument("--prefix", default=None,
                        help="Prefijo del archivo de salida: 'es' → 'es_maps.toml'")
    parser.add_argument("--model",  default=None,
                        help="Modelo Ollama (omitir = menú interactivo)")
    parser.add_argument("--batch",  type=int, default=None,
                        help="Strings por llamada (default: 10 ollama / 50 cloud)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Muestra los primeros 5 strings sin traducir")
    parser.add_argument("--num-gpu", type=int, default=99)
    # 8192 y no 2048: medido, el default antiguo cortaba la generación y hacía
    # fallar el 100% de los lotes de 30 (docs/benchmarks.md, resultado 1). Subirlo
    # no cuesta VRAM porque Ollama asigna el KV cache según uso, no por adelantado.
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--refs", default="auto",
                        help="Idiomas de referencia: 'auto' (default, autodetecta "
                             "campos original_XX), 'none', o lista 'ja,fr'")
    parser.add_argument("--glossary", action="append", default=None,
                        help="TOML de glosario; repetible (el último gana en empates)")
    parser.add_argument("--no-classify", action="store_true",
                        help="Ignora la etapa [classifier] del TOML de enrutado")
    parser.add_argument("--routing", default=None,
                        help="TOML de enrutado: manda cada string al modelo que mejor lo "
                             "traduce (ver routing/ y docs/benchmarks.md)")
    args = parser.parse_args()

    cfg = load_prompt_toml(args.prompt)
    print(f"  Prompt cargado: idioma={cfg['language']}"
          + (f", DeepL={cfg['deepl_target']}" if cfg["deepl_target"] else ""))

    glossary = cfg["glossary"] + load_glossary(args.glossary)
    if glossary:
        print(f"  Glosario: {len(glossary)} términos")
    if args.api == "deepl" and (glossary or args.refs != "none"):
        print("  Aviso: DeepL ignora glosario y referencias (no acepta prompt).")

    routes, classifier = load_routing(args.routing) if args.routing else (None, None)
    if args.no_classify:
        classifier = None
    if routes:
        print(f"  Enrutado: {len(routes)} rutas desde {Path(args.routing).name}")
        for r in routes:
            cond = []
            if r["match"]:         cond.append("match")
            if r["match_context"]: cond.append("context")
            if r["min_chars"]:   cond.append(f"≥{r['min_chars']}c")
            if r["max_chars"]:   cond.append(f"≤{r['max_chars']}c")
            if r["min_markers"]: cond.append(f"≥{r['min_markers']} markers")
            print(f"    {r['name']:<16} {r['model'] or '(default)':<24} "
                  f"{', '.join(cond) or 'fallback'}")
        if classifier:
            print(f"    clasificador     {classifier['model']:<24} "
                  f"→ {classifier['route']}")

    # Con un enrutado que cubre todo (una ruta sin condiciones y con modelo), nunca
    # se usa el modelo por defecto: pedirlo por menú sería pedir algo que no se usa.
    routing_covers_all = bool(routes) and any(
        r["model"] and not (r["match"] or r["match_context"] or r["min_chars"]
                            or r["max_chars"] or r["min_markers"])
        for r in routes
    )

    model = None
    if args.api == "ollama":
        batch_size = args.batch or 10
        # El dry-run no llama al modelo: pedir el menú aquí obligaría a elegir
        # uno que no se va a usar, y abortaría si Ollama no está instalado.
        if not args.dry_run and not routing_covers_all:
            model = select_ollama_model(args.model)
            print(f"  GPU offload: num_gpu={args.num_gpu}, num_ctx={args.num_ctx}")
        elif routing_covers_all:
            model = args.model
            print(f"  GPU offload: num_gpu={args.num_gpu}, num_ctx={args.num_ctx}"
                  f" (modelo por ruta)")
    else:
        batch_size = args.batch or 50

    total_ok = total_fail = total_pending = 0
    for path in args.files:
        if not Path(path).exists():
            print(f"Archivo no encontrado: {path}")
            continue
        out_path = resolve_output_path(path, args.output, args.prefix)
        try:
            ok, fail, pending = process_file(
                path, args.api, model, cfg,
                batch_size, args.dry_run, args.num_gpu, args.num_ctx, out_path,
                refs_mode=args.refs, glossary=glossary, routes=routes,
                classifier=classifier,
            )
        except FatalBackendError:
            print("\n  Corrida abortada: el error no se arregla reintentando.")
            print("  Revisa el modelo o baja --num-gpu, y vuelve a lanzar el mismo")
            print("  comando: lo ya traducido se conserva y no se repite.")
            sys.exit(2)
        total_ok += ok
        total_fail += fail
        total_pending += pending

    print(f"\n━━━ Resumen ━━━")
    print(f"  Pendientes procesados : {total_pending}")
    print(f"  Traducidos OK         : {total_ok}")
    print(f"  Fallidos              : {total_fail}")
    if total_fail:
        print(f"  Ver errores en errors.log junto al primer archivo de entrada")


if __name__ == "__main__":
    main()
