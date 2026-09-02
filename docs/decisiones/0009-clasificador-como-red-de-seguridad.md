# ADR 0009 — Clasificador como segunda etapa, no como reemplazo

**Estado:** aceptado

## Contexto

El ADR 0008 enruta por regex sobre el contenido de la línea, y deja un agujero conocido
(ISSUE-010): **las regex solo detectan el vocabulario que alguien listó**. Un eufemismo no
previsto —"she led him to the bedroom and closed the door"— cae en el modelo rápido, sale
reescrito y no deja rastro en ningún log.

El ADR 0008 descartó clasificar con un modelo. Ese descarte era correcto para lo que
evaluaba —clasificador **en lugar de** regex— e incorrecto para lo que aquí se propone.

## La asimetría que cambia la decisión

Aplicado **solo a lo que las regex no marcaron**, el baseline deja de ser "enrutado
perfecto" y pasa a ser "esas líneas ya iban al modelo que las reescribe":

| Caso | Consecuencia |
|---|---|
| Falso negativo (no detecta algo sensible) | Igual que sin clasificador — la regex ya había fallado ahí |
| Falso positivo (marca neutro como sensible) | Se traduce con el modelo fiel: solo cuesta tiempo |

**Ningún error del clasificador empeora el resultado.** Como reemplazo de la regex sí lo
haría: un falso negativo desviaría una línea que la regex habría acertado.

Por eso el prompt le pide explícitamente que ante la duda marque sensible: el error barato
es el falso positivo.

## Decisión

Tabla `[classifier]` en el TOML de enrutado:

```toml
[classifier]
model  = "Librellama/gemma4:e2b-Uncensored"
route  = "explicito"        # destino de lo que resulte sensible
checks = ["general"]        # rutas a revisar
batch  = 40
```

Corre después del enrutado por regex, en lotes, pidiendo **una palabra por línea**
(`EXPLICIT` / `VIOLENT` / `SAFE`). Reutiliza `parse_numbered_response`, así que hereda la
garantía del ADR 0004: si el conteo no cuadra, no se reenruta nada.

Se desactiva con `--no-classify` sin tocar el TOML.

## Qué modelo clasifica: el censurado

La intuición inicial fue usar el modelo **sin** censura, por miedo a que uno censurado se
negara a etiquetar. Los datos dijeron lo contrario (benchmarks, resultado 6):

| Clasificador | Recall |
|---|---|
| `gemma4:e2b` (censurado) | 75%, 90% |
| `gemma4:e2b-Uncensored` | 60%, 70% |

Un modelo con filtros fuertes ha aprendido a **reconocer** contenido sensible — que es
exactamente la tarea. Que sea peor traduciéndolo (lo suaviza) es irrelevante aquí: no
traduce, solo emite una etiqueta.

El riesgo temido no se materializó: 0 líneas sin etiqueta en cuatro corridas.

Resultado: **roles separados**. El censurado detecta, el sin censura traduce lo detectado.
Cuesta un intercambio de pesos más en la GPU, a cambio de ~17 puntos de recall.

## Coste

Se paga sobre las líneas que las regex **no** marcaron, que son la mayoría del corpus. Se
mitiga con lotes grandes y salida de una palabra: la generación es de ~1 token por línea,
mucho más barata que traducir.

`--no-classify` existe para cuando ese coste no compensa: un archivo de UI o de descripciones
PBS no necesita red de seguridad.

## Consecuencias

- El clasificador nunca aborta la traducción: ante un fallo devuelve etiquetas vacías y las
  entradas siguen su ruta original. Es una mejora oportunista.
- Añade una llamada por cada 40 entradas revisadas.
- No cierra ISSUE-010, lo reduce. Sigue sin haber forma de detectar en producción que una
  traducción válida dice algo distinto del original.

## Alternativa medida y descartada: pasar el campo `context`

La idea era darle al clasificador el `context` que ya emite el extractor
(`"Casa de Lucy | Lucy | Pag.4"`) para resolver las líneas que dependen de la escena.

Medido en un 2×2 con 3 repeticiones (benchmarks, resultado 7): **no aporta recall** (90%
con y sin) y con el prompt neutro lo **empeora** 10 puntos, además de costar un 30% más de
tiempo.

La causa es que el efecto va en la dirección contraria a la esperada: un contexto como
"Casa de Lucy" describe una escena doméstica y hace la línea ambigua *más* inocente. Sube
la precisión al 96% y hunde el recall — justo el intercambio inverso al que esta etapa
necesita.

Excepción plausible no medida: un proyecto cuyos eventos tengan nombres descriptivos
(`LucyLewdScene`). Pero en ese caso lo barato y determinista es meter esos nombres en la
regex de enrutado, no pagar una inferencia.
