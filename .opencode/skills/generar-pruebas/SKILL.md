---
name: generar-pruebas
description: Genera casos de prueba para una funcionalidad: caso correcto, caso incorrecto y caso límite. Úsalo siempre que se implemente un cambio y se quiera proponer cómo validarlo.
---

# Generar Pruebas

Útil cuando se implementa o modifica una funcionalidad y se quieren proponer casos de prueba.

## Procedimiento
1. Identifica la funcionalidad/entrada a validar.
2. Genera al menos tres categorías de casos:
   - **Caso correcto**: datos válidos → comportamiento esperado.
   - **Caso incorrecto**: datos inválidos → mensaje de error esperado.
   - **Caso límite**: valores mínimos/máximos, vacíos, nulos, längen de strings, fronteras numéricas.
3. Si el proyecto tiene framework de pruebas, úsalo para proponer/escribir los tests reales (jest, pytest, node --test, etc.).

## Salida esperada
- Categoría, entrada usada y resultado esperado para cada caso.
- Qué archivo de prueba (si existe) debería contener cada caso.
- Cuándo aporta valor ejecutarlo.