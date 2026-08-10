---
name: detectar-cambios-significativos
description: Determina si un cambio afecta a varios archivos y requiere confirmación antes de proceder. Úsalo antes de un cambio grande para decidir si se debe pedir aprobación.
---

# Detectar Cambios Significativos

Útil para evaluar si el cambio propuesto es grande y debe ser confirmado antes de aplicarlo.

## Procedimiento
1. Revisa la lista de archivos que se modificarán.
2. Evalúa la magnitud: cantidad de archivos, riesgo, impacto en módulos dependientes.
3. Si el cambio toca muchos archivos o módulos críticos, considera que **requiere confirmación** y presenta el plan completo antes de actuar.

## Salida esperada
- ¿Requiere confirmación? (sí/no).
- Cantidad de archivos afectados.
- Motivo de la decisión (cambio localizado vs. cambio amplio).

Ante un cambio significativo, presenta el plan y espera aprobación explícita del usuario antes de editar.