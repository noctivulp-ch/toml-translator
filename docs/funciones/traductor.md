# `toml-translator.py` — mapa del script

Un solo archivo, sin dependencias fuera de la stdlib. ~580 líneas en cinco bloques.

## 1. Carga del prompt (`load_prompt_toml`)

Lee el TOML de `--prompt` y devuelve un **dict de configuración** con `system`,
`language`, `source_label`, `deepl_target` y `glossary`.

Devolvía una tupla de 3; se cambió a dict al añadir campos, para no seguir alargando
una tupla posicional que ya se desempaquetaba en tres sitios distintos.

Aborta si falta `[system] text`. `[meta] language` tiene default `"español"` y
`[meta] deepl_target` es opcional (default `"ES"` en el punto de uso).

`[meta] name` se acepta en los prompts pero **el código no lo lee** — es documentación
para quien abre el archivo.

Usa `tomllib` (Python 3.11+) y cae a `tomli` si no está (`_load_toml`).

## 1b. Glosario (`_normalize_glossary`, `load_glossary`, `relevant_terms`)

`load_glossary` concatena los TOML de `--glossary`, deduplicando por `source` en
minúsculas — el último archivo gana, que es lo que permite apilar glosario general +
específico.

`_normalize_glossary` precompila una regex por término: `\b…\b` si el `source` es
alfanumérico, escape simple si lleva espacios o símbolos. Se compila una vez al cargar,
no por lote, porque `relevant_terms` se llama en cada llamada al modelo.

`relevant_terms` filtra a los términos presentes en el lote (tope 40). Es la pieza que
hace que el glosario escale — ver ADR 0006.

## 1c. Referencias multi-idioma (`discover_ref_langs`, `resolve_ref_langs`, `entry_refs`)

`REF_FIELD_RE` (`^original_(\w+)$`) detecta los campos de referencia. `discover_ref_langs`
los recolecta de todas las entradas pendientes y devuelve las etiquetas ordenadas
alfabéticamente — orden estable para que el prompt sea reproducible entre corridas.

`resolve_ref_langs` aplica el modo de `--refs`: `auto`, `none` o lista explícita
(que se filtra contra lo disponible y avisa de lo que falte).

Un campo de referencia vacío (`original_ja = ""`) **no** cuenta como presente: se
comprueba el contenido, no la existencia de la clave.

## 1d. Enrutado por contenido (`load_routing`, `route_matches`, `group_by_route`)

`load_routing` lee el TOML de `--routing` y carga **el prompt de cada ruta**, no solo su
modelo: el estilo va atado a la familia (ADR 0007). Las rutas relativas al prompt se
resuelven contra el directorio del archivo de enrutado.

`route_matches` evalúa las condiciones de una ruta (`match`, `min_chars`, `max_chars`,
`min_markers`); todas las presentes deben cumplirse. Una ruta sin condiciones casa siempre,
lo que la convierte en fallback si va la última.

`group_by_route` reparte las entradas conservando el orden dentro de cada grupo, y deja las
no enrutadas en un grupo `None` que usa la configuración de la línea de comandos.

Agrupar es deliberado frente a alternar por entrada: cambiar de modelo obliga a Ollama a
cargar y descargar pesos, así que procesar todo un grupo seguido minimiza esos intercambios.
No afecta al archivo de salida — `write_translated` indexa por `id`.

## 2. Validación de marcadores (`:81-89`)

```python
MARKER_RE = re.compile(r'\[(?:[A-Z][A-Z0-9]*|\d+|V\d+)\]')
```

Cubre `[JUGADOR]`, `[BR]`, `[GT]`, `[1]`, `[V3]`.
**No** cubre marcadores con minúsculas o guiones bajos — un extractor nuevo que emita
`[player_name]` pasaría la validación sin ser validado realmente.

`validate_markers` es asimétrico a propósito: devuelve solo los que **faltan** en la
traducción. Un marcador de más no se reporta (raramente rompe el juego; uno de menos sí).

## 3. Parser y escritor TOML (`:96-222`)

`parse_toml`` — parser propio de subconjunto, no `tomllib`. Reconoce `[[entry]]`,
strings con comillas simples, multilínea `"""` y enteros. Descarta comentarios y
entradas sin `id`.
**Por qué un parser propio** en vez de `tomllib`: la escritura debe preservar el archivo
carácter a carácter salvo la línea `translated`. Un round-trip por `tomllib` +
serializador reordenaría claves, normalizaría el escapado y destruiría los comentarios
de cabecera que pone el extractor.

`write_translated`` — reescribe línea a línea sobre el **archivo de entrada** como
plantilla, sustituyendo solo `translated = …`. Por eso funciona con `--output`: la
plantilla es siempre el input, el destino puede ser otro.

Efecto secundario a tener presente: si una entrada existe en el TOML pero no está en
`entries` (p. ej. porque le faltaba `id`), su `translated` se reescribe a `""`.

`resolve_output_path`` — `None` (in-place) si no hay `--output` ni `--prefix`;
si no, `<output_dir o dir del input>/<prefix>_<nombre>`.

## 3b. Construcción del prompt (`make_user_prompt`)

Recibe **entradas**, no textos sueltos, porque necesita los campos de referencia.

Sin refs ni glosario produce exactamente el formato histórico (`1. texto`), byte a byte:
es lo que garantiza que `--refs none` sin glosario se comporte como la versión anterior.

Con refs, cada entrada ocupa varias líneas pero **un solo número**; las variantes van
indentadas tres espacios. Esa indentación es lo que impide que el modelo las lea como
entradas nuevas y devuelva de más.

Orden de las secciones: glosario, instrucción de refs, `TEXTS:`, cuerpo.

## 4. Backends

Los backends LLM reciben el `user_prompt` **ya construido** y devuelven **texto crudo
numerado**, que `parse_numbered_response` desmonta.

`translate_deepl` es la excepción: recibe la lista de textos, porque su API no acepta
prompt. Por eso ignora refs y glosario, y `main` lo avisa al arrancar.

- `translate_ollama`` — POST a `/api/chat` con `options.num_gpu` / `options.num_ctx`.
- `translate_openai`` — modelo fijo `gpt-4o-mini`.
- `translate_claude`` — modelo fijo; `system` va como parámetro top-level, no como mensaje.
- `translate_deepl`` — N peticiones, una por string; reensambla la numeración a mano
  para cumplir el mismo contrato. Ignora `system`.

## 5. Motor y CLI (`:433-578`)

`translate_batch` — construye el prompt (glosario filtrado + refs) y envuelve al backend
con reintentos. Devuelve `[None] * len(batch)` cuando agota los intentos, nunca una lista
de longitud distinta.

`process_file`` — el bucle real: filtra pendientes, lotea, valida marcadores,
escribe cada 50, y escribe una vez al final. Devuelve `(ok, fail, pending)`.

`main` — argparse, selección de modelo, bucle sobre archivos, resumen.

El `--batch` default se resuelve aquí, no en argparse: `args.batch or 10` para Ollama,
`args.batch or 50` para el resto .

`process_file` — resuelve los idiomas de referencia una vez por archivo (no por lote),
reparte las entradas entre rutas, y por cada grupo lotea con **su** modelo, prompt, batch y
`num_ctx`. Valida marcadores y guarda cada 50 traducciones.

Sin `--routing` hay un solo grupo y el flujo es el de siempre.

Con `--dry-run` imprime el **prompt completo** que se enviaría para las 5 primeras
entradas, glosario y referencias incluidos. Es la forma de verificar que un glosario
nuevo dispara donde se espera sin gastar una llamada.

## Cómo añadir un backend

1. Escribir `translate_<nombre>(user_prompt, system)` que devuelva el texto crudo numerado.
2. Añadir la rama en `translate_batch`.
3. Añadir el valor a `choices` en el argparse.

No hay que tocar nada más — el parseo, los reintentos, el glosario, las referencias y la
validación son comunes.
