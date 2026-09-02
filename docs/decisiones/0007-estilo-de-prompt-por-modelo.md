# ADR 0007 — Estilo de prompt por familia de modelo

**Estado:** aceptado

## Contexto

El pipeline asumía el formato de chat universal: un mensaje `system` con las reglas y un
mensaje `user` con el texto. Vale para gemma instruct, GPT y Claude.

Los modelos **TranslateGemma** no encajan:

- Su plantilla de chat (`ollama show translategemma:4b --template`) mapea `system` y
  `user` **al mismo turno** `<start_of_turn>user`. Un system prompt separado no llega
  como tal, se concatena.

- La tarjeta oficial especifica una instrucción concreta —"You are a professional
  {SRC} ({src}) to {TGT} ({tgt}) translator…"— seguida de **dos líneas en blanco** y el
  texto. El modelo se entrenó con esa forma.

Usar el formato genérico con ellos desperdicia el fine-tuning.

## Decisión

`[meta] style` en el prompt TOML, con dos valores:

| `style` | Mensajes |
|---|---|
| `chat` (default) | `system` + `user` |
| `translategemma` | un único `user` con la plantilla oficial |

`build_messages(cfg, body)` concentra la diferencia. Los backends reciben mensajes ya
construidos y no saben nada del estilo.

`TRANSLATEGEMMA_TEMPLATE` reproduce la redacción oficial **literalmente**, incluido el
`\n\n\n` que produce las dos líneas en blanco. No se "mejora" el texto: es la forma con la
que el modelo fue entrenado, y cualquier reescritura es una apuesta a ciegas.

## Dónde van las reglas propias

Con `style = "translategemma"`, el `[system] text` se inserta **después** de la frase
canónica y **antes** de las dos líneas en blanco. Así las reglas viajan dentro del bloque
de instrucción y no contaminan la zona de texto a traducir.

El compromiso es real: cada línea que se añade aleja el prompt de la forma entrenada. Por
eso `prompts/translategemma-es.toml` lleva 4 reglas cortas en vez de las ~25 líneas de
`pokemon-es.toml`. Las preferencias de estilo largas rinden mejor con un modelo instruct
en `style = "chat"`.

## Alternativas descartadas

- **Detectar el estilo por el nombre del modelo** — mágico e imposible de forzar. Un
  modelo renombrado o un fine-tune propio rompería la heurística sin forma de corregirla.

- **Un flag `--style`** — el estilo es una propiedad del prompt, no de la invocación: un
  prompt con la plantilla de TranslateGemma no sirve para GPT. Atarlo al archivo evita
  combinaciones inválidas.

## Consecuencias

- Añadir una familia con formato propio es añadir una rama en `build_messages` y un valor
  a la validación de `style`.

- Los prompts existentes no cambian: sin `[meta] style` el default es `chat` y el
  comportamiento es idéntico byte a byte.

- Un `style` desconocido aborta al cargar, en vez de degradar en silencio a `chat`.
- Los benchmarks usan `build_messages`, así que miden el mismo formato que la ejecución
  real — comparar un modelo bajo su formato nativo frente al genérico es cambiar `--prompt`.
