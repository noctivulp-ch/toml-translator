# toml-translator

Traductor automático de archivos TOML de extracción. Agnóstico al motor de juego —
cualquier extractor que genere el formato TOML estándar puede usarlo.

## Estructura

```
toml-translator/
  toml-translator.py       ← script principal
  prompts/
    pokemon-es.toml        ← prompt para Pokémon (latam español)
    generic-game-es.toml   ← prompt genérico de juego (latam español)
    translategemma-es.toml ← formato nativo de los modelos TranslateGemma
  glossaries/
    pokemon-es.toml        ← glosario de términos canónicos
  routing/
    pokemon-es.toml        ← reglas de enrutado por contenido
  extractors/
    rpg-maker-xp/
      extract.rb           ← extrae texto de juegos RPG Maker XP / PE21.1
      inject.rb            ← inyecta traducciones de vuelta al juego
      diff.rb              ← diff entre dos versiones del juego
    pixel-game-maker-mv/
      extract.py           ← extrae texto de juegos PGMMV (cocos2d-x)
      inject.py            ← inyecta como idioma nuevo, sin pisar el original
      pgmmv.py             ← cifrado Twofish y recorrido del proyecto
  docs/                    ← arquitectura, ADRs y referencia de módulos
```

## Documentación

| Tema | Documento |
|---|---|
| Cómo encaja el pipeline completo | [`docs/arquitectura/pipeline.md`](arquitectura/pipeline.md) |
| Referencia del script Python | [`docs/funciones/traductor.md`](funciones/traductor.md) |
| Escribir prompts nuevos | [`docs/funciones/prompts.md`](funciones/prompts.md) |
| Por qué está hecho así (ADRs) | [`docs/decisiones/`](decisiones/) |
| Elegir modelo y tamaño de lote (medido) | [`docs/benchmarks.md`](benchmarks.md) |

## Uso básico

```bash
# Traducir con Ollama (menú de modelo interactivo)
python toml-translator.py \
  --api ollama \
  --prompt prompts/pokemon-es.toml \
  translation/maps.toml
# Traducir con salida separada y prefijo de idioma
python toml-translator.py \
  --api ollama \
  --prompt prompts/generic-game-es.toml \
  --output ./traducido/ \
  --prefix es \
  input/*.toml
# → ./traducido/es_maps.toml, ./traducido/es_messages_game.toml, ...
# Modo dry-run (ver los primeros 5 strings sin escribir)
python toml-translator.py \
  --api ollama \
  --prompt prompts/pokemon-es.toml \
  --dry-run \
  translation/*.toml
```

## Flags

| Flag | Default | Descripción |
|---|---|---|
| `--api` | — | `ollama` / `deepl` / `openai` / `claude` (requerido) |
| `--prompt` | — | Archivo TOML de configuración del prompt (requerido) |
| `--output` | input dir | Directorio de salida |
| `--prefix` | ninguno | Prefijo del archivo: `es` → `es_maps.toml` |
| `--model` | menú | Modelo Ollama; acepta prefijo (`qwen3` → `qwen3:4b`). Omitir = menú interactivo |
| `--batch` | 10/50 | Strings por llamada (10 Ollama, 50 cloud) |
| `--dry-run` | false | Muestra los primeros 5 sin traducir |
| `--num-gpu` | 99 | Capas del modelo en GPU (Ollama) |
| `--num-ctx` | 8192 | Ventana de contexto Ollama |
| `--refs` | `auto` | Idiomas de referencia: `auto` / `none` / `ja,fr` |
| `--glossary` | ninguno | TOML de glosario de términos; repetible |
| `--routing` | ninguno | TOML de enrutado por contenido |
| `--no-classify` | false | Ignora la etapa `[classifier]` del enrutado |

## Traducción multi-fuente (varios idiomas de referencia)

Si el juego ya viene traducido a otros idiomas, esas traducciones se pueden usar como
referencia cruzada: donde el inglés es ambiguo, el japonés o el francés suelen desambiguar.

Basta con que la entrada tenga campos `original_<lang>`:

```toml
[[entry]]
id          = "M1E1P0C0"
original    = "Welcome home, [JUGADOR]!"
original_ja = "おかえりなさい、[JUGADOR]！"
original_fr = "Bienvenue à la maison, [JUGADOR] !"
translated  = ""
```

El sufijo es libre (`ja`, `fr`, `pt_br`…) y se muestra al modelo en mayúsculas. **No hay
que declarar cuántos idiomas hay**: `--refs auto` (el default) los descubre por archivo, y
cada entrada puede tener un número distinto de referencias — las que falten se omiten.

Lo que recibe el modelo:

```
1. [EN] Welcome home, [JUGADOR]!
   [FR] Bienvenue à la maison, [JUGADOR] !
   [JA] おかえりなさい、[JUGADOR]！
2. [EN] It's super effective!
```

La respuesta sigue siendo **una línea numerada por entrada**. La etiqueta del campo
`original` se controla con `[meta] source_language` en el prompt (default `EN`).

| `--refs` | Efecto |
|---|---|
| `auto` (default) | Usa todos los `original_*` que encuentre. Sin campos extra, se comporta como siempre |
| `none` | Ignora las referencias aunque existan |
| `ja,fr` | Solo esos, en ese orden; avisa de los que no estén presentes |

Coste: cada referencia añade una línea al prompt. Con 3 idiomas el prompt casi se triplica,
lo que importa con `--num-ctx` bajo — ver [`docs/benchmarks.md`](benchmarks.md).

## Glosario de términos

Tabla de traducciones obligatorias, para fijar terminología que el modelo tiende a variar
entre lotes ("se debilitó" vs "se desmayó").

```toml
# glossaries/pokemon-es.toml
[[term]]
source = "fainted"
target = "se debilitó"
note   = "nunca 'se desmayó'"      # opcional
```

```bash
python toml-translator.py --api ollama   --prompt prompts/pokemon-es.toml   --glossary glossaries/pokemon-es.toml   translation/*.toml
```

**Solo se envían los términos que aparecen en el lote actual.** Un glosario de 500
entradas sigue añadiendo unas pocas líneas por llamada, así que puede crecer sin
degradar el contexto. El tope por lote es de 40 términos.

`--glossary` es repetible y el último archivo gana ante `source` duplicados, así que se
puede apilar uno general y otro específico del juego:

```bash
--glossary glossaries/pokemon-es.toml --glossary glossaries/mi-fangame.toml
```

También se puede embeber en el propio prompt con bloques `[[glossary]]`, con el mismo
formato. Los términos del prompt se cargan antes que los de `--glossary`.

El matching es case-insensitive y por palabra completa cuando el término es alfanumérico;
los términos con espacios o símbolos se buscan como subcadena.

> DeepL ignora el glosario y las referencias: su API no acepta prompt.

## Enrutado por contenido (`--routing`)

Modelos distintos fallan de formas distintas, y la diferencia **no es la calidad general
sino qué tipo de línea estropean**. Medido (ver [`docs/benchmarks.md`](benchmarks.md)):

| Modelo | Velocidad | Tokens de prompt | Suavizado en explícito |
|---|---|---|---|
| `translategemma:4b` | 4 s | 294 | **75%** |
| `gemma4:e2b-Uncensored` | 11 s | 688 | 0% |
| `gemma4:e2b` | 23 s | 688 | 0% |

`translategemma:4b` es el más rápido y el que menos contexto gasta, pero **reescribe** el
contenido explícito en vez de traducirlo: `"fucked her"` → `"la besaba"`, `"rode him"` →
`"él la besó"`. No rechaza ni deja líneas sin traducir — devuelve N líneas numeradas
perfectas. **Pasa todas las métricas automáticas mientras destroza el texto.**

`--routing` manda cada línea al modelo que no la va a estropear:

```bash
python toml-translator.py --api ollama \
  --prompt prompts/pokemon-es.toml \
  --glossary glossaries/pokemon-es.toml \
  --routing routing/pokemon-es.toml \
  --num-ctx 8192 \
  translation/*.toml
```

```
  Enrutado:
      412  explicito → Librellama/gemma4:e2b-Uncensored
      158  violento  → Librellama/gemma4:e2b-Uncensored
     3120  general   → translategemma:4b
```

### Clasificador — red de seguridad detrás de las regex

Las regex solo detectan el vocabulario que alguien listó. Un eufemismo no previsto
—*"she led him to the bedroom and closed the door"*— cae en el modelo rápido y sale
reescrito sin dejar rastro.

La tabla `[classifier]` revisa lo que las regex **no** marcaron y reenruta lo sensible:

```toml
[classifier]
model   = "gemma4:e2b"       # el censurado detecta mejor; ver más abajo
route   = "explicito"        # destino de lo que resulte sensible
checks  = ["general"]        # qué rutas revisar
batch   = 40
context = """
The game is an adult fan game: sexual and violent content is FREQUENT and usually
written as euphemism or implication rather than explicit words.
"""
```

`context` describe el juego al clasificador y sube el recall del 82% al **93%**, a costa de
bajar la precisión al 75%. Es el intercambio que interesa: un falso positivo se traduce con
el modelo fiel y no pasa nada.

> `qwen3.5:4b` **no sirve** para esto: devolvió 0 etiquetas en 40 líneas y tardó 16× más.
> Es un modelo de razonamiento y gasta la ventana pensando (ISSUE-008).

Medido sobre un corpus de 40 líneas donde casi ninguna contiene términos obvios
(con un banco de pruebas de desarrollo):

| | Recall | Precisión |
|---|---|---|
| Regex sola | **15%** | — |
| Regex + clasificador | 82% | 87% |
| Regex + clasificador **con `context`** | **93%** | 75% |

Es seguro por asimetría: aplicado solo a lo que la regex no detectó, un fallo del
clasificador deja las cosas como estaban, y un falso positivo solo cuesta tiempo (la línea
se traduce con el modelo fiel). Por eso el prompt le pide marcar sensible ante la duda.

**El clasificador usa el modelo censurado, al revés que las rutas de traducción.** Medido:
`gemma4:e2b` detecta 75-90% de los eufemismos frente al 60-70% del Uncensored. No es
contradictorio — un modelo con filtros fuertes ha aprendido a *reconocer* contenido
sensible, que es justo la tarea. Que sea peor traduciéndolo da igual: aquí solo etiqueta.
El riesgo de que se negara a etiquetar no se materializó (0 líneas sin etiqueta).

Coste: una llamada por cada 40 entradas revisadas, con salida de una palabra por línea.
`--no-classify` lo desactiva sin tocar el TOML — útil para archivos de UI o PBS, donde no
hace falta red de seguridad.

> No cierra el agujero, lo reduce. Un 65% de recall sobre eufemismos deja pasar cosas; la
> regex sigue siendo la primera línea de defensa y conviene mantenerla al día.

### Formato del TOML de enrutado

```toml
[[route]]
name        = "explicito"
model       = "Librellama/gemma4:e2b-Uncensored"
prompt      = "../prompts/pokemon-es.toml"   # cada ruta lleva SU prompt
batch       = 20                             # opcional
num_ctx     = 8192                           # opcional
match       = "\\b(fuck\\w*|cock|cum)\\b"      # regex, sin distinguir mayúsculas
min_chars   = 120                            # opcional
max_chars   = 400                            # opcional
min_markers = 2                              # opcional

[[route]]
name   = "general"                            # sin condiciones = fallback
model  = "translategemma:4b"
prompt = "../prompts/translategemma-es.toml"
```

Las rutas se evalúan **en orden** y gana la primera que casa. Cada una lleva su propio
prompt porque el estilo va atado al modelo: enrutar a translategemma sin su prompt nativo
desaprovecha el fine-tune.

`--dry-run` muestra cuántas entradas caen en cada ruta y el prompt exacto de cada grupo —
úsalo para ajustar las regex antes de gastar horas de GPU.

> **Escribe las reglas con sesgo hacia el modelo fiel.** Enrutar de más al modelo fiel
> cuesta tiempo; enrutar de menos cuesta texto censurado que ninguna métrica detecta y que
> solo se descubre leyendo la traducción ya inyectada en el juego.

## Comportamiento de salida

- **Sin `--output` ni `--prefix`**: modifica el archivo de entrada in-place (mantiene compatibilidad con el extractor original)
- **Con `--output` o `--prefix`**: escribe una copia nueva sin tocar el original

El archivo de salida incluye el `original` intacto y el `translated` relleno.

Si el string ya tenía `translated`, se respeta (idempotente — se puede interrumpir y reanudar).

## Formato del prompt TOML

```toml
[meta]
name         = "mi-prompt"
style        = "chat"        # "chat" (default) o "translategemma"
language     = "español"     # nombre legible para el prompt de IA
deepl_target = "ES"          # código DeepL (solo si usas --api deepl)
[system]
text = """
You are a translator...
[MARKER] placeholders must be preserved as-is.
Rules: 1. Return numbered lines only. 2. ...
"""
[[glossary]]                 # opcional — mismo formato que --glossary
source = "fainted"
target = "se debilitó"
```

### `style` — formato del mensaje

| `style` | Mensajes | Para qué modelos |
|---|---|---|
| `chat` (default) | `system` + `user` | Cualquier modelo instruct: gemma, GPT, Claude |
| `translategemma` | un solo `user` | Los modelos `translategemma:*` |

Los **TranslateGemma no usan system prompt**: su plantilla de chat fusiona `system` y
`user` en el mismo turno, así que un system prompt separado se diluye. La tarjeta oficial
del modelo especifica una instrucción concreta seguida de **dos líneas en blanco** antes
del texto, y el modelo se entrenó con esa redacción exacta.

Con `style = "translategemma"` el script la reproduce literalmente e inserta las reglas de
`[system] text` como líneas extra antes de las dos líneas en blanco:

```
You are a professional English (en) to Spanish (es) translator. Your goal is to
accurately convey the meaning and nuances of the original English text while adhering
to Spanish grammar, vocabulary, and cultural sensitivities.
Produce only the Spanish translation, without any additional explanations or
commentary. Please translate the following English text into Spanish:
<tus reglas de [system] text>
1. Welcome home, [JUGADOR]!
2. It's super effective!
```

Los idiomas se declaran en `[meta]`:

```toml
style       = "translategemma"
source_name = "English"      # nombre en el prompt
source_code = "en"           # código ISO en el prompt
target_name = "Spanish"
target_code = "es"
```

Ver `prompts/translategemma-es.toml`. Cuanto más se aleje el `[system] text` de la
plantilla entrenada, menos fiable es el modelo — con este estilo conviene un bloque de
reglas corto y dejar las preferencias largas de estilo para un prompt `chat`.

## Formato TOML de entrada/salida

```toml
[[entry]]
id         = "M3E12P0C5"
original   = "Welcome home, [JUGADOR]!"
translated = ""              # ← vacío = pendiente; relleno = ya traducido
context    = "Casa del jugador | NPC_Mom | Pag.0"
prefix     = "\\b"             # opcional — decoradores de apertura
codes      = "[JUGADOR]=\\PN"   # opcional — mapa marcador → código nativo
```

Campos que el traductor usa: `id` (clave), `original` (fuente), `translated` (destino).

El resto (`context`, `prefix`, `codes`, `section`, `map`, `file`…) los genera y consume el
extractor; el traductor los preserva sin tocarlos porque `write_translated` reescribe el
archivo línea a línea y solo sustituye la línea `translated = …`.

Valores multilínea usan `"""` con la primera línea vacía:

```toml
original = """
Primera línea
Segunda línea"""
```

## Backends de traducción

| `--api` | Endpoint | Modelo | Usa el system prompt |
|---|---|---|---|
| `ollama` | `http://localhost:11434/api/chat` | elegido en el menú | sí |
| `openai` | `api.openai.com/v1/chat/completions` | `gpt-4o-mini` (fijo) | sí |
| `claude` | `api.anthropic.com/v1/messages` | fijo en el código | sí |
| `deepl` | `api-free.deepl.com` o `api.deepl.com` | — | **no** |

Los modelos cloud están **hardcodeados** en `toml-translator.py` (`translate_openai``,
`translate_claude``). No hay flag para cambiarlos: editar la constante.

`deepl` es distinto de los demás: no acepta system prompt, traduce string por string
(una petición HTTP por entrada, `translate_deepl``) y usa `[meta] deepl_target` en vez
de `[system] text`. Con DeepL el estilo del prompt (tuteo latino, glosario Pokémon,
preservación de marcadores) **no se aplica** — solo sirve como traducción base rápida.

El `--batch` con DeepL no reduce las peticiones, solo el tamaño del lote reensamblado.

La URL DeepL se elige por el sufijo de la clave: `:fx` → plan free.

## Resiliencia

- **Reintentos**: cada lote se intenta hasta 3 veces (`max_retries=2`,
  `translate_batch``). Reintenta tanto ante excepción de red como cuando la respuesta
  no se puede parsear.

- **Parseo tolerante**: `parse_numbered_response`` acepta `1.`, `1)`, `1-`, `{1}`.
  Si el número de líneas no coincide, reintenta sin numeración. Si aun así no cuadra el
  conteo, el lote entero se marca como fallido — nunca se desalinean traducciones.

- **Guardado incremental**: escribe el TOML cada 50 traducciones (`SAVE_EVERY`),
  no solo al final. Un `Ctrl-C` a mitad pierde como mucho 49 strings.

- **Idempotencia**: solo procesa entradas con `translated` vacío. Reanudar es volver a
  lanzar el mismo comando.

- **Timeouts**: 180 s Ollama, 60 s OpenAI/Claude, 30 s DeepL.

## Validación de markers

`MARKER_RE` reconoce `[MAYUSCULAS]`, `[123]` y `[V12]`.

Tras cada traducción compara los marcadores del `original` con los del resultado y
registra los que faltan en `errors.log`, junto al **archivo de entrada** (no al de salida).

Nunca cancela la operación: una traducción con marcadores perdidos se guarda igual.

Revisar `errors.log` es parte del flujo, no algo opcional — un `[JUGADOR]` perdido rompe
el texto en el juego.

Dos tipos de línea en `errors.log`:

```
FAIL  <id>: <primeros 80 chars>   ← el lote no se pudo traducir; translated queda vacío
CODES <id>: missing ['[JUGADOR]'] ← se tradujo pero perdió marcadores; translated SÍ se escribió
```

El log se **acumula** entre ejecuciones (modo append). Borrarlo antes de una corrida
limpia si se quiere leer solo los errores nuevos.

## Elegir `--num-ctx` y `--batch`

**El default `--num-ctx 2048` es el factor que más limita el rendimiento**, y no por la
razón que parece. Medido en [`docs/benchmarks.md`](benchmarks.md):

| `num_ctx` | `gemma4:e2b` aguanta hasta |
|---|---|
| 2048 (antiguo default) | lote de **20** — a partir de 30 falla el 100% de los lotes |
| 8192 (default actual) | lote de **50** sin un solo fallo |

El fallo no viene de que el prompt no quepa: en el lote de 30 el prompt son 1013 tokens de

2048. Lo que se desborda es el **total**, porque estos modelos emiten un bloque de

razonamiento interno que también consume la ventana. Al quedarse sin presupuesto devuelven
contenido vacío, y el lote entero se descarta.

Recomendación con 4 GB de VRAM:

```bash
python toml-translator.py --api ollama --model gemma4:e2b \
  --prompt prompts/pokemon-es.toml \
  --num-ctx 8192 --batch 30 \
  translation/*.toml
```

Subir `num_ctx` cuesta VRAM en KV cache, pero mucho menos de lo que se gana: con lote 30
en vez de 10 son 3× menos llamadas. Si el modelo empieza a hacer offload a CPU, baja
`--batch` antes que `--num-ctx`.

## Menú de modelos Ollama

Sin `--model`, lista los modelos de `ollama list` y anota cuáles caben en VRAM.

El umbral está **fijo en 4.0 GB** (`VRAM_GB`, `toml-translator.py:327`) — es una
constante del script, no se detecta la GPU. Editarla si la máquina tiene otra VRAM.

Para modelos que no caben, bajar `--num-gpu` (menos capas en GPU) o `--num-ctx`
(menos KV cache) antes que cambiar de modelo.

## Variables de entorno para APIs cloud

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export DEEPL_API_KEY="xxxx:fx"   # :fx = plan free
```

## Dependencias

- Python 3.11+ (stdlib: `tomllib`, `urllib`, `argparse`, `json`, `re`)
- Ollama (si `--api ollama`): instalado y corriendo en `localhost:11434`
- Para cada extractor en `extractors/`: ver su propio README

## Añadir un extractor nuevo

Crear `extractors/<motor>/` con al menos:

- `extract.<ext>` — genera TOML estándar desde el proyecto
- `inject.<ext>` — lee TOML y aplica traducciones al proyecto
- `README.md` — documenta fuentes, IDs, marcadores y dependencias

El extractor debe emitir marcadores `[BRACKETS]` para todo código de formato del
motor original, y el inyector debe revertirlos al formato nativo antes de escribir.
