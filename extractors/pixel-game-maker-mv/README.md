# Extractor — Pixel Game Maker MV

Extrae e inyecta texto en juegos hechos con **Pixel Game Maker MV**
(アクションゲームツクールMV), el motor de Gotcha Gotcha Games basado en cocos2d-x.

Cómo reconocerlo: la carpeta del juego tiene `libcocos2d.dll`, `mozjs-33.dll` y
`Game/Resources/data/project.json`.

## Herramientas

| Script | Descripción |
|---|---|
| `extract.py` | Extrae texto → `translation/texts.toml` |
| `inject.py` | Lee el TOML → añade el idioma traducido al juego |
| `pgmmv.py` | Módulo compartido: cifrado, lectura y recorrido del proyecto |

## Uso

```bash
# 1. Extraer
python extractors/pixel-game-maker-mv/extract.py /ruta/al/juego

# 2. Traducir
python toml-translator.py --api ollama \
  --prompt prompts/pokemon-es.toml \
  --num-ctx 8192 \
  /ruta/al/juego/translation/texts.toml

# 3. Inyectar como idioma nuevo, y arrancar el juego en él
python extractors/pixel-game-maker-mv/inject.py /ruta/al/juego \
  --locale es_ES --set-default
```

`inject.py --dry-run` informa de lo que haría —cuántos textos, qué idiomas quedarían,
qué traducciones perdieron marcadores— sin escribir nada.

## Lo que hace especial a este motor: localización nativa

PGMMV guarda cada texto como un diccionario por idioma:

```json
{"id": 15, "name": "OPTION", "text": {"ja_JP": "OPTION\n設定", "en_US": "OPTION\nConfig"}}
```

Así que **traducir es añadir una clave**, no reemplazar nada. El inyector:

1. Añade `text[es_ES]` a cada entrada traducida — el japonés original queda intacto.
2. Añade `es_ES` a `gameInformation.language`.
3. Con `--set-default`, pone `initialLocale` y `mainLanguage` al idioma nuevo.

Consecuencia práctica: **es reversible sin backup**. Volver al japonés es cambiar
`initialLocale`; el texto original nunca se pierde. Es la diferencia con RPG Maker XP,
donde inyectar sí pisa el texto fuente.

## El cifrado

`project.json` viene cifrado: cabecera `enc` + 1 byte de relleno + **Twofish en CBC**
con un IV fijo del motor. Es lo que hace PGMMV al exportar — los tres juegos analizados
de tres autores distintos venían igual, así que no es una decisión de cada desarrollador.

**La clave viaja junto al archivo**, en `data/info.json`:

```json
{"title": "...", "key": "KeeWntiW0Ulwok3RLhBQPsR9ojRuZCE1hKLHZyiv3umix2eE6Siv3n2iNOQ1bmQh"}
```

Es base64 de la clave cifrada con "weakfish", y se descifra con `decrypt_pgmm_key`.
No hay nada oculto en el ejecutable.

Requiere el paquete de la comunidad:

```bash
pip install git+https://github.com/blluv/pgmm_decrypt.git
```

Sin él, ambos scripts siguen sirviendo con un `project.json` ya descifrado (`--json`).

### Gotcha: claves de 48 bytes

Twofish acepta claves de 16, 24 o 32 bytes, pero PGMMV entrega la clave en un buffer
con relleno de ceros que en un juego de 2026 medía **48**. `normalize_key` la recorta a
la longitud válida más grande. Sin ese recorte, la librería falla con
`TypeError: invalid key length`.

### Escribir cifrado o en plano

`inject.py` re-cifra por defecto con la misma clave. Con `--plain` escribe JSON legible:
el cargador trata como texto plano cualquier archivo que no empiece por `enc`, así que
ambas formas deberían arrancar. **No verificado ejecutando el juego** — si el plano no
carga, repite sin `--plain`.

## Qué se extrae y qué no

Solo `textList`, que es donde vive el texto que ve el jugador. El resto de strings
japoneses del proyecto **no** son texto de juego:

| Campo | Cantidad (juego de ejemplo) | Qué es |
|---|---|---|
| `textList` → `text` | **124** | El texto real. Se extrae |
| `name` | 26.823 | Etiquetas del editor. Internas |
| `memo` | 246 | Notas del desarrollador |
| `databaseList` | — | Tablas de balance numérico (HP por nivel) |

Extraer los `name` llenaría el TOML de ruido intraducible y arriesgaría romper el
proyecto: son identificadores que la lógica del juego usa por nombre.

## Formato de IDs

`text:<id>`, donde `<id>` es el campo `id` del nodo de `textList`. Es estable entre
versiones del juego, a diferencia de la posición en el árbol.

El campo `context` lleva la ruta de carpetas del editor
(`"OPTION＿ / OPTION1"`), útil para el traductor humano.

## Marcadores de formato

| Código PGMMV | Marcador TOML |
|---|---|
| `\C[#RRGGBB]` | `[C1]`, `[C2]`… |
| `\C[]` | idem, numerados por orden |
| salto de línea | `[BR]` |

Los colores se numeran **por texto** y el mapa inverso viaja en el campo `codes` de la
entrada (`"[C1]=\\C[#FF0000]|[C2]=\\C[]"`), igual que en el extractor de RPG Maker XP.

Los saltos de línea pasan a `[BR]` por una razón mecánica: el traductor mapea **una
línea de respuesta por entrada**, así que un salto real partiría la entrada en dos y
descuadraría el lote completo (ver ADR 0004).

## Distribuir una traducción

Reparte **el TOML y estos scripts**, nunca el juego:

```
mi-traduccion/
├── texts.toml          ← tus traducciones
├── inject.py
├── pgmmv.py
└── LEEME.txt           ← "aplica esto a tu copia del juego"
```

Quien la aplique usa su propia copia. El `project.json` original no se copia ni se
comparte en ningún momento: `inject.py` lee el del usuario, le añade el idioma y lo
reescribe en su sitio.

## Seguridad

- `inject.py` crea `project.json.bak` la primera vez que toca el archivo, y no lo
  regenera después: el `.bak` conserva siempre el estado original.
- Tras escribir, **relee y valida** el resultado. Si no se puede volver a cargar,
  restaura el backup automáticamente y sale con error.
- Avisa por pantalla de las traducciones que perdieron marcadores, sin abortar.

Para revertir a mano: `mv project.json.bak project.json`.

## Dependencias

- Python 3.11+
- `pgmm_decrypt` (solo si el juego está cifrado, que es lo normal)
- No requiere el motor ni el editor de PGMMV

## Verificado / no verificado

Probado sobre un juego real (extraer → inyectar → releer con la clave del juego):
descifrado, extracción de 124 textos, inyección de `es_ES`, re-cifrado y re-lectura
correctos, con el japonés original intacto.

**No probado ejecutando el juego** (binario de Windows). El paso que queda por
confirmar en la práctica es que el motor cargue el `project.json` reescrito y muestre
el idioma nuevo.
