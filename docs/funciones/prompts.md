# Prompts — cómo se escriben y por qué

Un prompt es un TOML que define **cómo** traducir. El glosario define **qué** términos
son obligatorios y vive aparte (ver más abajo).

```toml
[meta]
name            = "mi-prompt"   # no lo lee el código — documentación
style           = "chat"        # "chat" (default) | "translategemma"
language        = "español"     # informativo; se imprime al arrancar
source_language = "EN"          # etiqueta de `original` al usar --refs
deepl_target    = "ES"          # solo se usa con --api deepl
[system]
text = """
...
"""
[[glossary]]                    # opcional; se carga antes que --glossary
source = "fainted"
target = "se debilitó"
```

Campos que el código lee: `style`, `language`, `source_language`, `deepl_target`,
`source_name` / `source_code` / `target_name` / `target_code` (solo con
`style = "translategemma"`), `[system] text` y `[[glossary]]`.

## Los cinco requisitos del system prompt

Cualquier prompt nuevo tiene que cumplirlos o el pipeline se rompe:

1. **Salida numerada** — el parser espera `1. texto`. Sin esto no hay forma de mapear
   respuestas a entradas.

2. **Mismo número de líneas** — un desajuste descarta el lote completo.
3. **Preservar `[MARCADORES]`** — literal, misma grafía y mayúsculas.
4. **Sin explicaciones ni alternativas** — cualquier línea extra rompe el conteo.
5. **No traducir nombres propios** — se inyectan en un juego donde los nombres son claves.

Los tres primeros son requisitos **mecánicos**: si fallan, el lote se pierde.

Los dos últimos son de calidad.

## Los dos prompts incluidos

### `generic-game-es.toml`

Base reutilizable: español latino, tuteo, sin `vosotros`, pretérito simple, y las reglas
mecánicas. Punto de partida para cualquier juego.

### `pokemon-es.toml`

Extiende el genérico con dos glosarios:

- **Terminología canónica Pokémon en latino** — `fainted → se debilitó` (no "se desmayó"),
  `super effective → es muy efectivo`. Sin esto el modelo produce traducciones correctas
  pero que no suenan al juego oficial, que es exactamente lo que un jugador nota.

- **Vocabulario explícito latino** — el proyecto para el que se escribió traduce un fangame
  adulto. Sin glosario el modelo cae en variantes peninsulares ("joder", "polla", "tío")
  que rompen el registro latino del resto del texto.

Los glosarios existen porque el modelo por defecto traduce a español neutro-peninsular:
es lo más frecuente en su corpus de entrenamiento.

## Los dos estilos

`[meta] style` decide cómo se empaqueta el mensaje:

- **`chat`** (default) — `system` + `user`. Para modelos instruct. Admite system prompts
  largos: es donde rinden las ~25 líneas de `pokemon-es.toml`.

- **`translategemma`** — un único mensaje `user` con la plantilla oficial del modelo y dos
  líneas en blanco antes del texto. Ver ADR 0007.

Con `translategemma`, el `[system] text` se inserta dentro del bloque de instrucción.

Conviene que sea **corto**: cada línea aleja el prompt de la forma con la que el modelo
fue entrenado. `prompts/translategemma-es.toml` usa 4 reglas.

Regla práctica: si el prompt necesita glosarios de estilo largos, usa `chat` con un
modelo instruct. Si necesitas la calidad de traducción del fine-tune, usa `translategemma`
con reglas mínimas y pon la terminología en un `--glossary`, que se inyecta filtrado y
pesa mucho menos.

## Glosario vs. system prompt

Ambos fijan terminología, pero no son intercambiables:

| | System prompt | Glosario |
|---|---|---|
| Coste | En **todas** las llamadas | Solo si el término aparece en el lote |
| Escala | Se degrada al crecer | Crece gratis |
| Sirve para | Registro, tono, reglas de formato | Términos concretos |

Un término que aplica siempre ("usa tuteo") va en el system prompt. Uno que aplica a
líneas concretas ("fainted → se debilitó") va en el glosario.

## Escribir un prompt para otro idioma

Copiar `generic-game-es.toml`, y cambiar:

- El idioma destino y las notas de registro (formal/informal, variante regional).
- `deepl_target` al código del idioma (`FR`, `PT-BR`, `DE`…).
- Con `style = "translategemma"`, también `target_name` y `target_code`.
- La lista de marcadores en la sección `CRITICAL` — debe coincidir con los que emite
  **tu** extractor.
Mantener las cinco reglas numeradas del final tal cual; son las mecánicas.

## Probarlo

`--dry-run` **no** llama al modelo: imprime el **prompt completo** que se enviaría para
las 5 primeras entradas pendientes, con glosario filtrado y referencias incluidos.

Sirve para verificar el formato, comprobar que un glosario dispara donde se espera, y ver
qué idiomas de referencia se detectaron — todo sin gastar una llamada.

```bash
python toml-translator.py --api ollama --prompt prompts/pokemon-es.toml \
  --glossary glossaries/pokemon-es.toml --dry-run translation/maps.toml
```

Para medir la calidad de verdad: `scripts/bench_batch.py` y `scripts/bench_content.py`
(ver [`../benchmarks.md`](../benchmarks.md)).
