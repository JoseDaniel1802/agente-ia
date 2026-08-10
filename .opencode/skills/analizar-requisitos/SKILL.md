---
name: analizar-requisitos
description: Analiza un caso de uso o solicitud para extraer actores, restricciones, ambigüedades y datos. Úsalo cuando necesites desglosar los requisitos funcionales y no funcionales de una petición antes de proponer código o un plan.
---

# Analizar Requisitos

Útil cuando el usuario entrega un caso de uso, historia o solicitud y se necesita identificar su esencia antes de trabajar.

## Procedimiento
1. Lee el texto completo de la solicitud/caso.
2. Identifica los **actores** que intervienen (usuario, cliente, administrador, empleado, profesor, estudiante, sistema, etc.).
3. Extrae las **restricciones** y reglas indicadas por palabras como: debe, obligatorio, únicamente, solo, prohibido, no puede.
4. Detecta **ambigüedades** en términos vagos (rápido, fácil, eficiente, adecuado, mejor) y explica por qué son ambiguos.
5. Enlista los **datos** e información que el sistema maneja.

## Salida esperada
Entrega un resumen estructurado con:
- Requisitos identificados.
- Actores involucrados.
- Restricciones y supuestos.
- Ambigüedades detectadas, con su explicación.
- Datos manejados y qué falta aclarar.

Si falta información para continuar, detente y formula preguntas concretas al usuario.