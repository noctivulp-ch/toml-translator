# Traducciones

Una carpeta por juego traducido con toml-translator. Cada una lleva su `README.md` y la
configuración propia del juego (glosario, enrutado o prompt) cuando la tiene. Lo genérico
—prompts por idioma o modelo, glosarios de UI— sigue en `prompts/`, `glossaries/` y `routing/`.

Las subcarpetas `notas/` guardan apuntes locales (rutas del disco, pipelines antiguos) y no
se publican: están en `.git/info/exclude`.

| Juego | Motor | Idiomas | Estado | Carpeta |
|---|---|---|---|---|
| Pokémon Naughty Version 0.2.2 | RPG Maker XP (Pokémon Essentials 21.1) | en → es (latino) | Traducido, inyectado y jugado entero | [`pokemon-naughty/`](pokemon-naughty/) |
| Pokémon Reborn (diálogos de TERRA) | RPG Maker XP (Pokémon Essentials) | en → es (castellano) | Referencia humana, usada para medir | [`pokemon-reborn/`](pokemon-reborn/) |
| NITO | Pixel Game Maker MV | ja → es (latino) | Traducido e inyectado: 124/124 | [`nito/`](nito/) |

## Juego nuevo

1. Crear `traducciones/<juego>/` con un `README.md` (plantilla: cualquiera de las existentes).
2. Si el juego necesita términos propios, `glossary.toml`; si necesita repartir líneas entre
   modelos, `routing.toml` (las rutas a prompts son relativas a este archivo: `../../prompts/…`).
3. Apuntes con rutas locales, en `notas/`.
