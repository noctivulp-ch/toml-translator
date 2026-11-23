# Pokémon Reborn — diálogos de TERRA

Fangame de Pokémon hecho con RPG Maker XP sobre Pokémon Essentials. TERRA es una líder de
gimnasio que habla en leetspeak, gritos y memes.

- **Wikipedia:** sin artículo propio; aparece en
  [Pokémon fan games](https://en.wikipedia.org/wiki/Fan-made_Pok%C3%A9mon_games).
  Wiki del juego: [pokemon-reborn.fandom.com](https://pokemon-reborn.fandom.com/wiki/Home)
- **Idiomas:** inglés → español de España (castellano)
- **Estado:** 341 diálogos traducidos y validados a mano en un proyecto anterior. Aquí se
  usan como referencia humana para medir el pipeline (`docs/benchmarks.md`, resultado 10).

## Configuración

- `glossary.toml`: nombres propios que no se traducen y jerga castellana. Existe porque el
  prompt solo conseguía un 33% en tacos y un 0% en registro; un par origen → destino sí funciona.

```bash
python3 toml-translator.py --api ollama \
  --glossary traducciones/pokemon-reborn/glossary.toml \
  ...
```

Evaluación contra la referencia humana: `scripts/eval_vs_human.py` (local, no se publica).
