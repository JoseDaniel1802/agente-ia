---
name: generar-plan-trabajo
description: Genera un plan de trabajo estructurado a partir de requisitos. Úsalo antes de implementar cambios importantes: analizar, diseñar, implementar, probar y documentar.
---

# Generar Plan de Trabajo

Útil antes de iniciar una tarea grande para estructurar el flujo de trabajo.

## Procedimiento
1. Partir de los requisitos (List[str]) identificados en la solicitud.
2. Construir un plan incremental y verificable, incluyendo:
   - Analizar los requisitos.
   - Diseñar la solución.
   - Implementar los cambios (en pasos pequeños).
   - Realizar pruebas.
   - Documentar los cambios.
3. Indicar qué archivos se modificarán en cada fase y dependencias entre pasos.

## Salida esperada
- Cantidad de requisitos cubiertos.
- Plan de pasos ordenado, con entregables por fase.
- Riesgos o supuestos que deben confirmarse.

El plan debe usarse como guía; no implementes sin aprobación si el cambio es significativo.