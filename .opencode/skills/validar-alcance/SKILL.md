---
name: validar-alcance
description: Verifica si una solicitud y los archivos propuestos están dentro del alcance del trabajo. Úsalo antes de iniciar cambios para confirmar qué archivos se tocan y si la petición es realizable.
---

# Validar Alcance

Útil antes de modificar archivos: confirma que la solicitud es clara y que los archivos a tocar existen.

## Procedimiento
1. Verifica que la solicitud del usuario no esté vacía y sea accionable.
2. Revisa que los archivos mencionados (List[str]) existan realmente usando las herramientas del entorno (read, glob).
3. Determina si el cambio está **dentro del alcance** de la petición o si se expande a otros archivos.
4. Detecta archivos que se proponen tocar pero no existen o no están relacionados.

## Salida esperada
- Solicitud validada o motivo por el que no procede.
- Lista de archivos afectados y su estado (existe/no existe).
- Si el cambio está dentro del alcance (true/false).
- Advertencias de impacto o archivos fuera de alcance.

No modifiques nada durante esta validación; solo reporta.