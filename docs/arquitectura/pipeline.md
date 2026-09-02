# Arquitectura — el pipeline de traducción

## Idea central

El sistema separa **tres responsabilidades** que normalmente van juntas en los
traductores de videojuegos:

```
  extractor            traductor              inyector
 (por motor)          (agnóstico)            (por motor)
     │                     │                      │
  binarios ──► TOML ──► TOML+translated ──► binarios parcheados
     │                     │                      │
   Ruby                 Python                  Ruby
```

El TOML es el **contrato**. Cualquier extractor que emita ese formato puede usar
`toml-translator.py` sin que este sepa nada del motor de origen.

## Por qué TOML como frontera

- **Legible y editable a mano** — el traductor humano puede corregir la salida de la IA
  sin herramientas.

- **Diffeable en git** — una entrada por bloque, cambios localizados.
- **Idempotente por construcción** — `translated = ""` significa "pendiente". El estado
  del trabajo vive en el propio archivo, no en una base de datos aparte.

## Las tres etapas

### 1. Extracción (`extractors/<motor>/extract.rb`)

Lee los binarios del juego y emite `translation/*.toml`. Su trabajo más importante no es
sacar el texto, sino **normalizarlo**: los códigos de formato del motor (`\PN`, `\v[3]`,
`{1}`) se convierten en marcadores `[BRACKETS]` legibles y el mapeo inverso se guarda en
el campo `codes` de cada entrada.

Esto existe porque un LLM que ve `\c[6]\PN encontró {1}` produce basura: reordena los
códigos, los traduce, o los pierde. Viendo `[JUGADOR] encontró [1]` los respeta.

### 2. Traducción (`toml-translator.py`)

Agnóstico al motor. Lee el TOML, agrupa las entradas pendientes en lotes, las envía
numeradas al backend, parsea la respuesta numerada y rellena `translated`.

No entiende de mapas, PBS ni scripts. Solo ve `id` / `original` / `translated`.

### 3. Inyección (`extractors/<motor>/inject.rb`)

Reconstruye el texto nativo (`reconstruct`, inject.rb:173): revierte los marcadores a
códigos de motor usando `codes`, antepone `prefix`, y reescribe los binarios. Hace
backup `.bak` la primera vez que toca cada archivo.

## Por qué la numeración en el prompt

`make_user_prompt` envía:

```
1. Welcome home, [JUGADOR]!
2. The wild [1] fainted!
```

y espera de vuelta la misma numeración. Es la única forma de mapear N respuestas a N
entradas en un lote sin hacer N llamadas.

El riesgo es el desalineamiento: si el modelo devuelve 9 líneas para 10 entradas y se
asignaran por posición, todas las traducciones a partir de ahí quedarían en la entrada
equivocada — un fallo silencioso y catastrófico.

Por eso `parse_numbered_response` es estricto en el conteo:
si no devuelve exactamente `count` líneas, retorna `None` y el lote se descarta entero.

Es preferible perder 10 traducciones que corromper 10.

## Modelo de fallo

Ninguna etapa aborta ante un error individual:

| Fallo | Qué pasa |
|---|---|
| Un lote no traduce | `FAIL` en `errors.log`, `translated` queda vacío, se reintenta en la próxima corrida |
| Traducción pierde marcadores | `CODES` en `errors.log`, **se guarda igual** |
| Un archivo TOML no existe | Se avisa y se pasa al siguiente |
| Un `.rxdata` no reserializa | `inject.rb` no lo escribe (`validate_marshal`) |

La consecuencia de diseño: **`errors.log` es parte del flujo**, no un artefacto de
depuración. Una corrida "exitosa" con 300 líneas `CODES` produce un juego con texto roto.

## Elección de tamaño de lote

Los defaults (10 Ollama / 50 cloud) salen de la tensión entre dos fallos:

- Lote grande → menos llamadas, pero más probable que el modelo pierda la numeración
  o se salga de la ventana de contexto (`--num-ctx 2048` por defecto es pequeña).

- Lote pequeño → más robusto, pero N veces más lento y sin contexto de diálogo.

Los modelos locales pequeños (4B) pierden el hilo mucho antes que los cloud, de ahí la
diferencia de default.
