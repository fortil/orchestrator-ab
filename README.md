# orquestador-ab

A/B del orquestador de tasky (pieza 07 `orquestador-haiku-sonnet` del repo
`contenido`). La pregunta: ¿qué necesita cada modelo para calificar como
orquestador, y en qué effort? Los subagentes salen por `tasky-route` con
modelo y effort de la cascada, así que la única variable entre brazos es la
sesión que recibe `/tasky`: su modelo y su effort.

## Brazos (los 4 escenarios)

| Brazo | Modelo de la sesión | Effort |
|---|---|---|
| `sonnet-medium` | claude-sonnet-5-5 | medium |
| `sonnet-low` | claude-sonnet-5-5 | low |
| `haiku-medium` | claude-haiku-5-5 | medium |
| `haiku-high` | claude-haiku-5-5 | high |

La silla documentada de tasky es Sonnet 5.5 a high; el uso habitual de William
es medium/low. La pregunta del experimento no es "¿Sonnet high vs Haiku?",
sino "¿el Sonnet que uso siempre (medium/low) sigue ganándole al Haiku
(medium/high)?". Por eso los brazos combinan modelos y efforts distintos: las
diferencias incluyen el efecto del effort, y eso es lo que se quiere medir.

## Etapas

| Etapa | Qué | MODE | Reps | Cómo |
|---|---|---|---|---|
| 0 | smoke: preflight + línea final sin ERROR prematuro | xs | 1 por brazo | headless (`claude -p`) |
| 1 | el camino de las DECISION: archivo ajeno staged (`tasky.md:1014`) | xs | 1 por brazo | interactiva: tú respondes |
| 2 | run completo con plan, crítica, implementación y revisión | m | 3 por brazo | headless |
| 3 | presión en run largo | l | 3 por brazo | headless; solo si la 2 pasa |

Regla de parada: si un brazo falla la etapa 0 dos veces seguidas, se anota y
no se le llevan las etapas 2 y 3.

## Uso

```bash
python3 arnes.py brazos                                   # lista los brazos
python3 arnes.py correr --etapa 0 --brazo sonnet-low      # prepara + lanza + extrae
python3 arnes.py preparar --etapa 1 --brazo haiku-high    # etapa 1: imprime los pasos interactivos
python3 arnes.py extraer --todos                          # transcript -> resultados/*.json
python3 arnes.py resumen                                  # tabla agregada
```

Cada run vive en `runs/<etapa>-<brazo>-r<rep>/` con un clon fresco del seed
(`repo/`, git init + commit seed), `meta.json`, `salida.txt`, `comando.txt` y
`debug.log`. Los transcripts se buscan en
`~/.claude/projects/<ruta-del-run-codificada>/` (método del reporte
2026-09-24 §6.3).

## Métricas por run (`resultados/<run>.json`)

- `fin`: COMPLETED / FAILED / PLANNED / DECISION / sin-linea (el run terminó sin emitir la línea final).
- `errores` y `errores_sin_respaldo`: los `ERROR:` del orquestador y cuántos salieron sin `tool_use` en el mismo o el anterior turno de la sesión (la firma de septiembre: error inventado sin ejecutar nada).
- `decisiones`: cuántas `DECISION:` emitió.
- `narracion`: bloques de texto del orquestador que no son ERROR/DECISION/línea final (el contrato de salida lo prohíbe, `tasky.md:38`).
- `sesion_tool_use` y `writes_sospechosas`: herramientas usadas por el modelo de la sesión, y los Write/Edit cuyo destino no es un documento del run (PLAN, EXECUTION_REPORT, WORK_REVIEW, .tasky/): sospecha de violación de rol, para revisar a mano.
- `route_lines`: líneas `ROUTE:` vistas en salidas de comandos (rastros del ruteo).
- `pico_contexto` y `tokens`: `input + cache_read + cache_creation` máximo y sumas del modelo de la sesión.

## Avisos

- Sonnet 5.5 y Haiku 5.5 comparten tokenizer según la documentación; es hipótesis, no medición propia. Si los picos de contexto salen raros, esa es la primera sospecha.
- El `debug.log` de cada run lleva las reglas allow con credenciales: nunca se pega ni se comparte; `extraer` solo lee la línea de modo si hace falta.
- Sin precios: el arnés cuenta tokens; el coste relativo se analiza fuera, como en la pieza (razón relativa, no tarifas).
- Los runs de las etapas 2 y 3 consumen cuota real (12 runs completos la etapa 2, 12 más la 3). Lánzalas cuando toca.
- Comparar el pico de contexto contra la mediana de 369K de septiembre no vale: esos eran runs reales de semanas de trabajo; aquí el BRIEF es de prueba. La comparación válida es entre brazos.
