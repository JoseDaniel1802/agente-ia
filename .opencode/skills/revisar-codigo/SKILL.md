---
name: revisar-codigo
description: Revisa la calidad y legibilidad de código. Úsalo cuando necesites auditar un archivo o proyecto: busca problemas de extensión, funciones largas, prints, except sin tipo, TODOs pendientes, y calidad general antes de refactorizar.
---

# Revisar Código

Útil cuando se solicita una revisión de calidad del código fuente antes de proponer mejoras.

## Procedimiento
1. Lee el código completo de los archivos relevantes.
2. Verifica indicadores de calidad:
   - Archivos demasiado extensos (ayuda a señalar responsabilidades de más).
   - Demasiadas funciones en un archivo (posible separación de responsabilidades).
   - Uso de `print()` en producción (déalo para logging).
   - `except:` sin especificar el tipo de excepción (cubre errores y dificulta depuración).
   - Marcadores pendientes como `TODO`, `FIXME`, `HACK`.
3. Complementa con checks reales de la herramienta de búsqueda del entorno (patterns, imports sin usar, código muerto, duplicación).

## Salida esperada
- Lista de hallazgos ordenados por severidad (crítico / medio / menor).
- Cantidad de líneas y funciones evaluadas.
- Recomendaciones concretas de mejora.

No apliques cambios ni tan solo de refactor sin autorización del usuario.