# ADR 0006 — Glosario filtrado por lote

**Estado:** aceptado

## Contexto

El system prompt de `pokemon-es.toml` ya lleva un glosario incrustado, pero tiene dos
límites: hay que editar el prompt para añadir un término, y no escala — cada término
suma tokens a **todas** las llamadas.

Con `--num-ctx 2048`, un glosario de 200 términos dejaría sin espacio al texto a traducir.

Ollama trunca el contexto en silencio, así que el síntoma sería traducciones erráticas
sin ningún error visible.

## Decisión

Glosario en archivos TOML aparte (`--glossary`, repetible), y **filtrado por relevancia**:
en cada lote solo se inyectan los términos que aparecen realmente en esos textos
(`relevant_terms`), con un tope de 40.

```toml
[[term]]
source = "fainted"
target = "se debilitó"
note   = "nunca 'se desmayó'"
```

## Por qué el filtrado es lo importante

Sin él, el glosario compite con el texto por la ventana de contexto y el sistema se
degrada justo cuando más términos se añaden — el incentivo queda invertido.

Con él, el coste por llamada depende del **lote**, no del tamaño del glosario. Un glosario
de 500 términos inyecta unas 5 líneas en un lote típico. Crecerlo es gratis.

## Por qué va en el mensaje de usuario y no en el system prompt

El bloque cambia en cada lote. Dejar el system prompt fijo permite que el backend lo
cachee, y mantiene una separación clara: el system prompt define **cómo** traducir,
el glosario **qué** términos son obligatorios aquí.

## Detalles de matching

- Case-insensitive.
- Palabra completa (`\b`) cuando el término es alfanumérico, para que `HP` no case dentro
  de `SHOP`.

- Subcadena cuando el término lleva espacios o símbolos, donde `\b` no se comporta como
  uno espera (`"super effective"`, `"Poké Ball"`).

## Consecuencias

- Los glosarios se apilan: uno general y otro por juego. Ante un `source` duplicado gana
  el último archivo, así que lo específico sobrescribe a lo general.

- Un término solo se aplica si aparece **literalmente** en el original. Una conjugación no
  listada (`faints` frente a `fainted`) no lo dispara: hay que añadir las variantes.

- El tope de 40 términos por lote es una salvaguarda, no un límite de diseño. Si se
  alcanza, el lote es demasiado grande o el glosario demasiado genérico.

- No es una garantía: el modelo puede ignorar el glosario. Es un sesgo fuerte, no una
  sustitución determinista — para eso haría falta un post-proceso, que no se implementó.
