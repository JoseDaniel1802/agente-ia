# AGENTS.md — Proyecto Agente (agente-ia)

## Qué es este repo
Un agente de desarrollo de software construido con la API de NVIDIA (compatible con OpenAI) que expone herramientas locales para análisis de requisitos, revisión de código, generación de pruebas, validación de alcance, detección de cambios y plan de trabajo.

## Estructura
- `main.py` — CLI (bienvenida y bucle de conversación).
- `agente.py` — cliente OpenAI/NVIDIA, esquemas de tools, `ChatSession`.
- `herramientas.py` — 6 herramientas que el modelo puede llamar.
- `instrucciones.py` — personalidad y reglas del agente.
- `.env` — clave `NVIDIA_API_KEY` (no committear).
- `.opencode/` — configuración de opencode: agente + skills.

## Convenciones
- Python 3, `.venv`, dependencias sin fijar en `requirements.txt`.
- Los mensajes del sistema usan `instrucciones.py`.
- No committear `.env`, `.venv/`, `__pycache__/` (ya en `.gitignore`).

## Reglas de trabajo del agente
1. Analizar requisitos antes de proponer código.
2. No inventar funcionalidades o archivos.
3. Dividir cambios grandes en pasos verificables.
4. Proponer pruebas para cada cambio.
5. Presentar plan y esperar aprobación ante cambios significativos.
6. Reportar qué archivos se modificarán antes de editarlos.