# Benchmarks de modelos locales

Dos preguntas que solo se responden midiendo:

1. **¿Hasta qué tamaño de lote aguanta un modelo antes de volverse errático?**
   → `scripts/bench_batch.py`

2. **¿Se niega a traducir contenido adulto?**
   → `scripts/bench_content.py`
Los resultados están más abajo. La metodología va primero porque los números solo
significan algo con ella delante.

## Hardware de referencia

| | |
|---|---|
| GPU | NVIDIA RTX 3050 Ti Laptop, **4 GB VRAM** |
| Ollama | `localhost:11434` |
| `num_ctx` | 2048 (default del traductor) |
| `num_gpu` | 99 (todas las capas que quepan) |

Los tiempos **no son transferibles** a otra máquina. Las tasas de acierto sí: dependen
del modelo y del tamaño de lote, no de la GPU.

## Qué mide `bench_batch.py`

Un corpus de 50 líneas de diálogo de juego —mezcla deliberada de UI corta, diálogo largo,
strings con varios marcadores y strings sin ninguno— se envía en lotes de tamaño creciente.

| Métrica | Qué significa |
|---|---|
| `parse` | % de lotes con exactamente N líneas numeradas. **La métrica que manda**: si falla, el lote entero se descarta (ADR 0004) |
| `markers` | % de marcadores `[BRACKETS]` conservados. Un `[JUGADOR]` perdido rompe el texto en el juego |
| `sin trad` | % de líneas devueltas idénticas al original — el modelo se saltó la traducción |
| `contam` | % de líneas con meta-texto ("Translation:", "Note:") |
| `tok_in` | Tokens contados por Ollama en el prompt. **Si se acerca a `num_ctx`, el contexto se trunca en silencio** y el resto de métricas son ruido |
| `s/str` | Segundos por string traducido |

Un corpus de puras frases cortas sobreestima al modelo, de ahí la mezcla.

## Qué mide `bench_content.py`

Tres niveles de intensidad, 8 líneas de diálogo cada uno:

| Nivel | Contenido | A quién le importa |
|---|---|---|
| 1 | Oscuro / violento | Cualquier RPG con argumento serio |
| 2 | Romance / insinuación | Visual novels, rutas románticas |
| 3 | Sexual explícito | El caso que motivó `pokemon-es.toml` |

Detecta **dos formas de rechazo**, porque la segunda es la peligrosa:

- **Explícito** — "I can't", "no puedo", "inappropriate", o `content` vacío. Se ve.
- **Silencioso** — el modelo devuelve el original sin traducir. El TOML queda con texto
  en inglés y `errors.log` limpio. Es la métrica `sin trad`.

Por qué importa para el pipeline: `translate_batch` no distingue un rechazo de un fallo de
red. Lo reintenta 3 veces, la corrida se vuelve lentísima y `errors.log` registra `FAIL`
sin decir que la causa fue el filtro del modelo.

## Cómo reproducir

```bash
# Aguante por tamaño de lote
python scripts/bench_batch.py \
  --models "gemma4:e2b,translategemma:4b" \
  --sizes 5,10,20,30,50 --reps 2 --out bench.json
# Efecto de ampliar la ventana de contexto
python scripts/bench_batch.py --models gemma4:e2b --num-ctx 4096
# Tolerancia de contenido
python scripts/bench_content.py --models "gemma4:e2b,translategemma:4b" --reps 2
# Ver los corpus
python scripts/bench_batch.py --list-corpus
python scripts/bench_content.py --show-corpus
```

## Resultado 1 — `num_ctx` es el cuello de botella, no el tamaño del lote

Medido el 2026-09-02. `parse` = % de lotes con N líneas numeradas.

### Con `--num-ctx 2048` (el default del script)

| Modelo | 5 | 10 | 20 | 30 | 50 |
|---|---|---|---|---|---|
| `Librellama/gemma4:e2b-Uncensored` | 100% | 100% | **100%** | 0% | 0% |
| `gemma4:e2b` | 100% | 100% | **100%** | 0% | 0% |
| `gemma4:e4b` | 100% | **100%** | 0% | 0% | 0% |

### El mismo `gemma4:e2b` con `--num-ctx 8192`

| 10 | 20 | 30 | 50 |
|---|---|---|---|
| 100% | 100% | **100%** | **100%** |

Marcadores conservados: 100% en todos los casos que parsearon.

### Por qué

El corte es **brusco**: se pasa de 100% a 0% sin degradación intermedia, y cuando falla,
`content` viene vacío.

En el lote de 30 el prompt son **1013 tokens de 2048** — la entrada no se desborda. Lo que
se desborda es el **total**, porque estos modelos emiten un bloque `thinking` que Ollama
devuelve aparte pero que consume la misma ventana. Al agotarla, el modelo no llega a
emitir `content`.

De ahí que subir `num_ctx` mueva el techo de 20 a más de 50 sin tocar nada más.

### Consecuencias prácticas

- El default `--num-ctx 2048` es **conservador de más**. Con 4 GB de VRAM,
  `--num-ctx 8192 --batch 30` va 3× más rápido que el default sin perder calidad.

- **Un modelo más grande no aguanta más.** `gemma4:e4b` colapsa en 20 donde el `e2b` llega
  a 30, y además tarda el doble. Para este trabajo el `e2b` domina al `e4b`.

- Si hay que elegir entre bajar `--batch` o bajar `--num-ctx`, **baja `--batch`**.

## Resultado 2 — TranslateGemma y el efecto del formato

`translategemma:4b`, `--num-ctx 8192`, formato nativo (`prompts/translategemma-es.toml`):

| lote | parse | markers | tokens de prompt |
|---|---|---|---|
| 10 | 100% | 100% | 294 |
| 20 | 100% | 100% | 452 |
| 30 | 100% | 96% | 619 |
| 50 | 100% | 100% | 939 |

El mismo modelo con formato **chat** (`prompts/pokemon-es.toml`), como control:

| lote | parse | markers | tokens de prompt |
|---|---|---|---|
| 10 | 100% | **86%** | 688 |
| 20 | 100% | 100% | 846 |
| 30 | 100% | 100% | 1013 |

Dos lecturas:

- **El formato nativo cuesta menos de la mitad de tokens** (294 frente a 688 en el lote de
  10). No es magia del modelo: su prompt son 4 reglas cortas frente a las ~25 líneas de
  `pokemon-es.toml`. Queda más presupuesto para texto con el mismo `num_ctx`.

- Con formato chat aparece pérdida de marcadores (86%) que el formato nativo no muestra de
  forma consistente. Es la razón de ser del ADR 0007.

El 96% del lote de 30 en formato nativo no se puede separar de la variabilidad con solo 2
repeticiones. Para decidir sobre eso harían falta más `--reps`.

## Resultado 3 — `translategemma:12b` no cabe en 4 GB

Todos los lotes fallaron con HTTP 500. Causa real:

```
llama-server startup failed after projector CPU offload retry:
cudaMalloc failed: out of memory
alloc_tensor_range: failed to allocate CUDA0 buffer of size 7290232960
```

Pide **7.29 GB** sobre 4 GB disponibles. No es un problema del modelo sino de
`--num-gpu 99` (el default): Ollama no degrada a CPU por su cuenta, aborta.

Ver ISSUE-009 — el pipeline reintenta ese 500 tres veces por lote aunque ningún reintento
pueda arreglarlo.

## Resultado 4 — Censura: casi nadie rechaza, varios reescriben

Ningún modelo probado **rechazó** traducir: 0% de rechazo en los tres niveles, 100% de
parseo, 0% de líneas sin traducir. Si la medición parara ahí, la conclusión sería "todos
sirven". Sería falsa.

### Suavizado en contenido explícito (nivel 3)

| Modelo | Suavizado | Velocidad | Reps |
|---|---|---|---|
| `translategemma:4b` | **75%** | 4 s | 2 |
| `gemma4:e4b` | **6%** | 23 s | 6 |
| `gemma4:e2b` | 0% | 11 s | 6 |
| `Librellama/gemma4:e2b-Uncensored` | 0% | 11 s | 6 |

### Qué hace `translategemma:4b`

| Original | translategemma | `gemma4:e2b` |
|---|---|---|
| `fucked her` | la **besaba** | la cogía |
| `cum inside me` | **lo hagas** dentro | te vengas dentro |
| `thrust harder` | **la besó** con más fuerza | empujó más fuerte |
| `Fuck me harder` | **Besa** fuerte | ¡Cógeme más fuerte! |
| `rode him` | **Él la besó** | Ella lo montó |

Sustituye por "besar" y en la última **invierte el sujeto**. No es un fallo de calidad:
es reescritura sistemática del contenido.

### Qué hace `gemma4:e4b`

Menos, pero lo hace, y sus errores son de significado:

| Original | e4b |
|---|---|
| `thrust harder` | "se movió más fuerte" |
| `came all over her chest` | "**se revolcó** todo sobre su pecho" |

Coincide con la experiencia de campo que motivó buscar un modelo sin censura.

### Por qué esto es peor que un rechazo

Un rechazo se ve: rompe el parseo, aparece en `errors.log`, la corrida lo cuenta como
fallo. La reescritura **no deja rastro**. El TOML queda con `translated` relleno, el log
limpio y el resumen diciendo "0 fallidos". El problema aparece jugando.

Es la razón de ser de la métrica `suavizado` y del enrutado por contenido (ADR 0008).

### Límites de esta medición

- **0% no es prueba de 0%.** Con 6 repeticiones × 8 líneas son 48 muestras; un 0/48 es
  compatible con una tasa real de hasta ~6%. En una corrida de 5000 strings eso serían
  cientos de líneas alteradas. Para los `e2b` la conclusión honesta es "no se detectó
  suavización", no "no censura".
- **El corpus son 8 líneas cortas por nivel.** Un rechazo que dependa de contexto largo o
  acumulado no aparecería aquí.
- **La lista `EXPECTED` es la que define qué cuenta como suavizado.** Un eufemismo cuyo
  término no esté en la lista pasa desapercibido. La detección tiene el mismo punto débil
  que las reglas del enrutado.

### Recomendación

**Usa `Librellama/gemma4:e2b-Uncensored` para contenido adulto.** Va igual de rápido que el
`e2b` normal, ocupa lo mismo, y no depende de que el filtro de Google se comporte. Cuando
la alternativa cuesta lo mismo, la elección prudente es gratis.

Para texto neutro, `translategemma:4b` es la mejor opción: más rápido y con la mitad de
tokens de prompt. Combinarlos es exactamente lo que hace `routing/pokemon-es.toml`.

## Resultado 5 — `translategemma:12b` sí funciona con offload

Con `--num-gpu 20 --num-ctx 4096`, repartiendo capas entre GPU y RAM:

| lote | parse | markers | tokens | s/string |
|---|---|---|---|---|
| 10 | 100% | 100% | 294 | 5 |

Funciona y es correcto, pero a **5 s por string** frente a 0-1 s del 4b. Con 4 GB de VRAM
no compensa: el 4b da el mismo 100% mucho más rápido.

El fallo anterior era del default `--num-gpu 99`, que exige todas las capas en GPU y aborta
en vez de repartir.

### Nota metodológica: un falso positivo que hubo que corregir

La primera versión de `REFUSAL_RE` buscaba frases de rechazo en **toda** la respuesta.

Eso marcó el nivel 2 como "100% rechazo" cuando el modelo había traducido correctamente:
el corpus incluye *"I can't stop staring at you"* → *"No puedo dejar de mirarte"*, y ese
"no puedo" legítimo disparaba el detector.

Corregido: el patrón solo se aplica cuando la respuesta **no parsea**. Si el modelo
devolvió N líneas numeradas, tradujo — aunque alguna contenga "no puedo".

Queda la lección general: **el rechazo parcial no lo detecta ninguna regex**. Un modelo que
suaviza una línea entre ocho pasa todas las métricas automáticas. Por eso el script guarda
todas las líneas en el JSON y muestra ejemplos: el juicio final es humano.

## Resultado 6 — El clasificador como red de seguridad

`scripts/bench_classifier.py`. Corpus de 40 líneas: 20 sensibles **por eufemismo** (casi
ninguna contiene los términos de las regex) y 20 seguras, incluidas trampas como
*"My POKéMON fainted"*, *"She killed it at the talent show"* o *"Strip the old paint off
the fence"*.

`recall` = % de sensibles detectadas — la métrica que importa, porque una que se escapa
acaba traducida por el modelo que la reescribe.

| | Recall | Precisión |
|---|---|---|
| **Regex sola (baseline)** | **15%** | — |
| `gemma4:e2b` + contexto | **93%** (95/90/95) | 75% |
| `gemma4:e2b` prompt neutro | 82% (75/90) | 87% |
| `Librellama/gemma4:e2b-Uncensored` | 65% (60/70) | 84% |
| `qwen3.5:4b` | **0%** — no etiquetó nada | — |

(2-3 repeticiones por modelo; la variabilidad entre ellas es alta)

### El clasificador multiplica por cinco la cobertura

La regex sola detecta 3 de 20 eufemismos. El clasificador llega a 15-18. Es la diferencia
entre "la red tiene agujeros" y "la red casi no existe".

### El modelo censurado clasifica MEJOR que el sin censura

Contraintuitivo pero consistente en ambas repeticiones: `gemma4:e2b` supera al Uncensored
por ~17 puntos de recall.

Tiene sentido: un modelo entrenado con filtros fuertes ha aprendido a **reconocer**
contenido sensible, que es exactamente la tarea del clasificador. Que sea malo
traduciéndolo (por suavizar) es otro problema, y aquí no traduce nada.

El riesgo que se temía —que un modelo censurado se negara a etiquetar— **no se
materializó**: 0 líneas sin etiqueta en las cuatro corridas.

Conclusión: **roles distintos, modelos distintos**. El censurado detecta; el sin censura
traduce lo detectado.

### Los falsos positivos son inocuos

Se repiten *"He beat me fair and square"* y *"That climb nearly killed me"*. Ambos van al
modelo fiel y se traducen bien — solo cuestan tiempo. Es la asimetría del ADR 0009
funcionando como se diseñó.

### El contexto del juego sube el recall a 93%

Añadiendo al prompt del clasificador una línea que describe el juego —"es un fangame
adulto, el contenido sexual y violento es FRECUENTE y suele ir en eufemismo"— con
`gemma4:e2b`, 3 repeticiones:

| Prompt | Recall | Precisión |
|---|---|---|
| Neutro | 75%, 90% | 83%, 90% |
| **Con contexto** | **95%, 90%, 95%** | 76%, 72%, 76% |

Sube el recall ~11 puntos y baja la precisión ~12. **Es el intercambio deseable**: los
falsos positivos nuevos son inocuos (`"Your [1] is evolving!"`, `"He grabbed the rope and
pulled hard"`) y solo cuestan una traducción con el modelo fiel.

Configurable con `[classifier] context` para no asumir que todo juego es adulto.

### `qwen3.5:4b` no sirve como clasificador

**40 de 40 líneas sin etiqueta**, en 327 s por corrida (16× más lento que gemma).

Es el mismo fallo del ISSUE-008: consume su presupuesto en el bloque `thinking` y devuelve
`content` vacío. Ni siquiera una tarea de una palabra por línea lo evita.

Para clasificar hace falta un modelo que responda directo, no uno que razone.

### Lo que sigue escapándose

Las líneas cuyo carácter sensible depende del contexto de la escena, no de la frase:

- *"The bed creaked all night long."*
- *"I'll do anything you want tonight, [JUGADOR]."*
- *"He never came back from the mine, and nobody went looking."*

Con el prompt contextual solo resiste *"The bed creaked all night long"*, en todas las
repeticiones. Ninguna palabra de esa frase es sensible; solo la escena la hace serlo.

## Resultado 7 — Pasar el campo `context` NO ayuda (resultado negativo)

La hipótesis era que darle al clasificador el `context` que ya emite el extractor
(`"Casa de Lucy | Lucy | Pag.4"`) cubriría las líneas que dependen de la escena.

Diseño 2×2 con `gemma4:e2b`, 3 repeticiones por celda, sobre el mismo corpus de 40 líneas
al que se le añadieron contextos plausibles de un proyecto RPG Maker (nombres de mapa y
evento realistas, **no** etiquetas de contenido — un contexto que dijera "SexScene" haría
trivial la prueba):

| Variante | Recall | Precisión | Tiempo |
|---|---|---|---|
| A — prompt neutro, sin `context` | 86.7% | 85.3% | 22 s |
| B — prompt "juego adulto", sin `context` | **90.0%** | 78.3% | 21 s |
| C — prompt "juego adulto" + `context` | **90.0%** | 80.7% | 28 s |
| D — prompt neutro + `context` | **76.7%** | 96.0% | 26 s |

### El contexto no aporta, y solo puede restar

- **C = B** en recall (90% ambas). Con el prompt de juego adulto, añadir el contexto no
  cambia nada.
- **D < A** claramente (76.7% frente a 86.7%). Con prompt neutro, el contexto **empeora**
  la detección en 10 puntos.
- Cuesta un ~30% más de tiempo por los tokens extra.

### Por qué falla: el contexto tranquiliza en vez de alertar

La dirección del efecto es la contraria a la esperada. En D la precisión sube al **96%**
—prácticamente cero falsos positivos— mientras el recall se hunde: el modelo se vuelve
**más conservador**.

Un contexto como `[Casa de Lucy | Lucy | Pag.4]` describe una escena doméstica corriente.
Leído junto a una frase ambigua, la vuelve *más* inocente, no menos. El contexto aporta
información sobre el decorado, no sobre la intención.

Y es el intercambio exactamente inverso al que interesa (ADR 0009): queremos recall alto
aunque la precisión sufra, no al revés.

### Límite de esta conclusión

Los contextos del corpus son nombres neutros de mapa y evento, que es lo que emite el
extractor de un proyecto normal. **Un juego cuyos eventos se llamen de forma descriptiva**
(`LucyLewdScene`, `H_Scene_03`) daría una señal muy distinta, y ahí el contexto
probablemente sí ayudaría — bastaría con añadir esos nombres a la regex de enrutado, que
es más barato y determinista.

### Decisión

**No se adopta.** La configuración recomendada sigue siendo la variante B/C: prompt con
descripción del juego y sin el campo `context`. Es igual de buena y un 30% más rápida.

`scripts/bench_classifier.py --use-context` conserva la opción para reproducir la medición
o repetirla en un proyecto con nombres de evento descriptivos.
