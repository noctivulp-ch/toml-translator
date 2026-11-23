# Pokémon Naughty Version

Fangame adulto de Pokémon, versión 0.2.2, hecho con RPG Maker XP sobre Pokémon Essentials 21.1.

- **Wikipedia:** sin artículo propio. Contexto general:
  [Pokémon fan games](https://en.wikipedia.org/wiki/Fan-made_Pok%C3%A9mon_games) ·
  [RPG Maker](https://es.wikipedia.org/wiki/RPG_Maker)
- **Idiomas:** inglés → español latino
- **Estado:** traducido, inyectado y jugado entero. Traducción tosca pero jugable.

## Configuración usada

Usa la configuración genérica de fangames Pokémon, que nació con este juego:

```bash
python3 toml-translator.py --api ollama \
  --prompt prompts/pokemon-es.toml \
  --glossary glossaries/pokemon-es.toml \
  --routing routing/pokemon-es.toml \
  --num-ctx 8192 \
  translation/*.toml
```

Extracción e inyección: `extractors/rpg-maker-xp/`.

## Resultado

| Origen | Textos |
|---|---|
| `messages_game.dat` (UI y texto del juego) | 8 040 |
| `messages_core.dat` (motor PE 21.1) | 5 888 |
| `Map*.rxdata` (diálogos) | 2 786 |
| `CommonEvents.rxdata` | 76 |
| `PBS/*.txt` (Pokédex, objetos, habilidades) | 2 975 |

Quedan 8 entradas de mapas sin traducir (texto de depuración, no visible) y avisos por los
códigos `\GI`, `\GD`, `\GO` al inyectar.

## Pendiente

- Revisar las regex de `routing/pokemon-es.toml` cuando salga la siguiente versión del juego.
  Para ver qué cambió entre versiones: `extractors/rpg-maker-xp/diff.rb`.

## Notas

`notas/pipeline-anterior.md`: el pipeline original (scripts dentro de la carpeta del juego,
parches al motor para que quepan los textos), antes de que pasara a este repo. No se publica.
