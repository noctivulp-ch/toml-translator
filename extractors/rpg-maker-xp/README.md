# Extractor — RPG Maker XP (Pokémon Essentials 21.1)

Extrae texto traducible de juegos RPG Maker XP al formato TOML estándar del sistema.
También inyecta las traducciones de vuelta a los binarios del juego.

## Herramientas

| Script | Descripción |
|---|---|
| `extract.rb` | Extrae texto → genera `translation/*.toml` |
| `inject.rb` | Lee `translation/*.toml` → parchea `Data/` y `PBS/` |
| `diff.rb` | Compara dos versiones del juego → TOML de cambios |

## Uso

```bash
# Extraer (sobre el directorio raíz del juego)
ruby extractors/rpg-maker-xp/extract.rb /ruta/al/juego

# Traducir (con toml-translator)
python toml-translator.py \
  --api ollama \
  --prompt prompts/pokemon-es.toml \
  --output /ruta/al/juego/translation \
  --prefix es \
  /ruta/al/juego/translation/*.toml

# Inyectar
ruby extractors/rpg-maker-xp/inject.rb /ruta/al/juego

# Diff entre versiones (para actualizar una traducción existente)
ruby extractors/rpg-maker-xp/diff.rb /juego/v0.2.2 /juego/v0.2.3 \
  --out /juego/v0.2.3/translation/diff.toml
```

## Fuentes de texto cubiertas

| Fuente | Archivo TOML generado | Contenido |
|---|---|---|
| `Data/messages_game.dat` | `messages_game.toml` | Diálogos, UI custom del juego |
| `Data/messages_core.dat` | `messages_core.toml` | Strings del motor PE21.1 |
| `Data/Map*.rxdata` | `maps.toml` | Diálogos de NPCs en mapas |
| `Data/CommonEvents.rxdata` | `common_events.toml` | Escenas y eventos comunes |
| `PBS/*.txt` | `pbs.toml` | Pokédex, descripciones de movs/habs/items |
| `Data/Scripts.rxdata` | `scripts.toml` | Strings hardcodeados en scripts Ruby |

## Formato de IDs por fuente

Los IDs son estables entre ejecuciones: `write_toml` (extract.rb:125) solo añade
entradas cuyo `id` no exista ya en el TOML, así que re-extraer no duplica ni pisa
traducciones hechas.

| Fuente | Patrón | Ejemplo real |
|---|---|---|
| `messages_game.dat` | `g_s<idx>_<md5>` / `g_d0_<md5>` | `g_s24_3f9a1c0be2d7` |
| `messages_core.dat` | `c_s<idx>_<md5>` / `c_d0_<md5>` | `c_s13_8ab4f0119c2e` |
| mapas | `M<map>E<event>P<page>C<cmd>` | `M3E12P0C5` |
| common events | `CE<id>C<cmd>` | `CE7C3` |
| PBS | `pbs:<archivo>:<id>:<campo>` | `pbs:pokemon.txt:BULBASAUR:Pokedex` |
| scripts | `scr:<script>:<md5>` | `scr:PlayerBreeding:1a2b3c4d5e6f` |

`<md5>` = primeros 12 hex del MD5 del texto original (`short_id`, extract.rb:146).
Se usa hash en lugar de la clave porque en `messages_*.dat` la clave **es** el texto
fuente completo, que puede ser multilínea. Los IDs de mapa **no** llevan zero-padding.

## Marcadores de formato

`preprocess_codes` (extract.rb:173) parte cada string en tres campos para que la IA
solo vea texto limpio:

| Campo TOML | Contenido |
|---|---|
| `original` | texto limpio, con marcadores `[BRACKETS]` |
| `prefix` | decoradores de apertura (`\b`, `\r`) — se reinyectan al inicio |
| `codes` | mapa `marcador=código` separado por `\|`, ej. `[JUGADOR]=\PN\|[1]={1}` |

`prefix` y `codes` se omiten del TOML cuando están vacíos.

### Normalización de códigos

| Código original | Marcador TOML |
|---|---|
| `\PN` | `[JUGADOR]` |
| `\TN` | `[ENTRENADOR]` |
| `\GT` | `[GT]` |
| `\GY` | `[GY]` |
| `<br>` | `[BR]` |
| `{1}`, `{2:fmt}` | `[1]`, `[2]` |
| `\v[3]` | `[V3]` |

### Códigos que se descartan

`VISUAL_STRIP_RE` (extract.rb:170) **elimina** los códigos puramente cosméticos antes
de traducir, y no se reinyectan: `\c[N]` (color), `<b>` `<i>` `<r>`, `<ac>` `<al>` `<ar>`
(alineación) y los `\b` / `\r` que no estén al inicio del string.

Consecuencia práctica: un string con color o negrita **pierde ese formato** al inyectar
la traducción. El texto sigue siendo correcto, solo cambia su presentación.

El inyector reconstruye el texto con `reconstruct` (inject.rb:173): aplica `codes` a la
inversa y antepone `prefix`. Es retrocompatible — si `prefix` y `codes` faltan, devuelve
el texto sin tocar.

## Seguridad al inyectar

`inject.rb` crea un backup `<archivo>.bak` **la primera vez** que toca cada archivo
(inject.rb:145). Las ejecuciones posteriores no lo regeneran, así que el `.bak` siempre
conserva el estado original del juego sin traducir.

Antes de escribir un `.rxdata`/`.dat` valida que el Marshal reserializado se pueda volver
a cargar (`validate_marshal`, inject.rb:150). Si un marcador del original falta en la
traducción, avisa por stderr (`warn_missing_codes`, inject.rb:160) pero no aborta.

Para revertir: `for f in Data/*.bak PBS/*.bak; do mv "$f" "${f%.bak}"; done`

## Sobre `diff.rb`

Genera un TOML con secciones `[[added]]`, `[[changed]]` y `[[removed]]` — **no**
`[[entry]]`. `toml-translator.py` solo parsea `[[entry]]`, así que el diff no se le puede
pasar directamente; hay que renombrar las cabeceras primero:

```bash
sed -e 's/^\[\[added\]\]$/[[entry]]/' -e 's/^\[\[changed\]\]$/[[entry]]/' \
    diff.toml > diff_entries.toml
```

Los `[[removed]]` se emiten comentados — son informativos, marcan traducciones obsoletas.

Ver `issues.md` en la raíz del repo (ISSUE-001).

## Estado de cobertura

`extract.rb` no extrae todo el juego, solo lo configurado:

- **PBS**: solo los archivos y campos de `PBS_CONFIG` (extract.rb:463) —
  `pokemon.txt:Pokedex`, `moves.txt:Description`, `abilities.txt`, `items.txt`,
  `ribbons.txt`, `trainers.txt:LoseText`, `phone.txt:Text`. Nombres de Pokémon, movimientos
  e items **no** se extraen (decisión deliberada: los nombres propios no se traducen).
- **Scripts**: solo los de `TARGET_SCRIPTS_NAMES` (extract.rb:522) y solo strings dentro de
  `pbMessage(...)`. Para cubrir más scripts, añadir nombres a esa constante.
- **Filtros**: se descartan strings de menos de 5 caracteres, rutas de assets
  (`ASSET_PATH_RE`, extract.rb:259) y duplicados.

## Dependencias

- Ruby ≥ 3.2 con stdlib (`zlib`, `digest`, `fileutils`, `set`)
  `extract.rb` usa `Set` sin `require 'set'`; funciona porque Ruby 3.2+ lo autocarga.
  En Ruby 2.7–3.1 falla con `NameError: uninitialized constant Set` — ver `issues.md`
  (ISSUE-002). `diff.rb` sí hace `require 'set'`.
- No requiere el motor RGSS ni mkxp — parsea Marshal directamente

## Codificación

`safe_utf8` (extract.rb:90) intenta UTF-8 y cae a Windows-1252 si no es válido — típico
en proyectos RPG Maker XP creados en Windows. Los bytes irrecuperables se reemplazan por `?`.
