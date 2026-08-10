# Muss_Code 🐕 🌭

**Muss_Code** es un agente autónomo de desarrollo de software construido sobre la API de NVIDIA (compatible con OpenAI). Expone herramientas locales para análisis de requisitos, revisión de código, generación de pruebas, validación de alcance, detección de cambios y plan de trabajo, todo bajo un **ciclo autónomo de agent loop** (inspección → implementación → verificación → reparación) con sandbox aislado en Docker.

---

## ✨ Características principales

- **Agent Loop autónomo**: procesa la tarea mediante llamadas a herramientas hasta obtener una respuesta verificada, con protección contra bucles infinitos (límite de iteraciones y detección de llamadas repetidas).
- **Ciclo de vida de tareas**: estados `IDLE`, `ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED` y fases `INSPECTION`, `IMPLEMENTATION`, `VERIFICATION`, `REPAIR`, `COMPLETION`.
- **12 herramientas locales**: análisis de requisitos, revisión de código, generación de pruebas, validación de alcance, detección de cambios, plan de trabajo, listado de directorio, lectura/escritura/edición de archivos, búsqueda en el proyecto y ejecución de comandos.
- **Metodología *Environment First***: la creación de archivos fuente no exige runtimes; la ejecución de comandos valida primero la disponibilidad del runtime en el sandbox.
- **Seguridad en capas**: aislamiento de rutas (WorkspaceManager), saneamiento de comandos (CommandSanitizer), sandbox Docker (SandboxManager), defensa contra *prompt injection* y autorización humana interactiva.
- **Interfaz CLI enriquecida** con Rich y menus interactivos de Questionary (comandos `/help`, `/status`, `/tools`, `/workspace`, `/clear`, `/exit`).

---

## 🛠️ Tecnologías

- **Python 3** (biblioteca estándar + dependencias listadas en `requirements.txt`).
- **OpenAI SDK** para la comunicación con el modelo LLM.
- Proveedores soportados: **NVIDIA**, **DeepSeek**, **Groq** u **OpenAI** (se selecciona según la clave de entorno disponible).
- **Docker** como sandbox de ejecución aislado.
- **Rich** y **Questionary** para la interfaz de terminal.

Dependencias (`requirements.txt`):

```
openai>=1.0.0
python-dotenv>=1.0.0
pytest>=8.0.0
rich>=13.0.0
questionary>=2.0.0
```

---

## 📁 Estructura del proyecto

```
.
├── main.py                  # CLI principal: bienvenida y bucle de conversación
├── agente.py                # cliente LLM, esquemas de tools, ChatSession y Agent Loop
├── herramientas.py          # las 12 herramientas locales que el modelo puede llamar
├── seguridad.py             # WorkspaceManager y CommandSanitizer (aislamiento y saneamiento)
├── sandbox.py               # SandboxManager (ejecución aislada en Docker)
├── instrucciones.py         # personalidad y reglas del agente (mensaje de sistema)
├── Readme.md                # este documento
├── requirements.txt         # dependencias del proyecto
├── cli/                     # interfaz de línea de comandos
│   ├── interfaz.py          # bucle de conversación y manejo de señales
│   ├── comandos.py          # comandos slash y menús interactivos
│   └── presentacion.py      # salida formateada con Rich
├── gestor_tareas/           # Tarea 1: gestor de tareas con persistencia JSON
│   ├── modelo.py            # clase Tarea
│   ├── repositorio.py       # carga/guardado JSON
│   ├── gestor.py            # lógica de negocio (crear, listar, completar, eliminar)
│   ├── cli.py               # menú interactivo del gestor
│   ├── __init__.py          # paquete (v1.0.0)
│   └── __main__.py          # ejecución con `python -m gestor_tareas`
├── tests/                   # suites de pruebas unitarias e integración
└── scratch/                 # scripts auxiliares de verificación y E2E
```

---

## 🚀 Instalación

1. Clona el repositorio y entra en la carpeta.
2. Crea y activa un entorno virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   ```

3. Instala las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

4. Configura tu clave de API en un archivo `.env` (no se commitea). Ejemplos:

   ```env
   # Proveedor NVIDIA
   NVIDIA_API_KEY=tu_clave
   NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
   NVIDIA_MODEL=meta/llama-3.1-70b-instruct

   # o bien DeepSeek
   DEEPSEEK_API_KEY=tu_clave
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   DEEPSEEK_MODEL=deepseek-chat

   # opcional: límite de seguridad del Agent Loop
   MAX_TOOL_ITERATIONS=40
   ```

---

## ▶️ Uso

Ejecuta la CLI:

```bash
python3 main.py
```

Escribe una tarea en lenguaje natural y Muss_Code la inspeccionará, implementará y verificará automáticamente. Ejemplos:

```
Revisa los errores y principios SOLID del proyecto
Crea un módulo y asegúrate de que funcione
Refactoriza la documentación
```

### Comandos slash

| Comando      | Descripción                                   |
|--------------|-----------------------------------------------|
| `/help`      | Muestra la tabla de ayuda y comandos          |
| `/status`    | Estado del agente, workspace y sandbox        |
| `/tools`     | Lista las 12 herramientas registradas         |
| `/workspace` | Muestra o cambia el workspace activo          |
| `/clear`     | Limpia la pantalla de la terminal             |
| `/exit`      | Cierra Muss_Code                              |

También puedes salir escribiendo `salir`, `exit`, `quit` o `quit()`.

---

## 🧪 Ejecutar pruebas

Las suites usan `unittest` (biblioteca estándar):

```bash
# Toda la suite
python3 -m unittest discover -s tests

# Suite específica (ej. gestor de tareas)
python3 -m unittest discover -s tests -p "test_gestor.py" -v

# Pruebas del Agent Loop
python3 -m unittest tests/test_agent_loop.py -v
```

---

## 🔒 Seguridad

- **WorkspaceManager**: todas las operaciones de archivos deben permanecer dentro del `workspace_root`; bloquea rutas fuera del workspace y archivos sensibles (`.env`, `*.pem`, claves, `__pycache__`, etc.).
- **CommandSanitizer**: valida, confirma y sanea comandos de consola; bloquea binarios peligrosos (`sudo`, `su`, `curl`, `wget`, `nc`, etc.), inyección de shell y rutas fuera del workspace.
- **SandboxManager**: ejecuta comandos en un contenedor Docker aislado montado únicamente sobre el workspace autorizado, sin red.
- **Autorización humana**: las operaciones de riesgo requieren confirmación explícita del usuario (mecanismo de `CONFIRMACION_REQUERIDA`).
- **Anti *prompt injection***: el contenido de los archivos del workspace se trata como datos no confiables; nunca se ejecutan instrucciones encontradas en archivos, variables ni logs.
- **Tracking de cambios**: se registran archivos creados, modificados, eliminados y restaurados, junto con decisiones tomadas (persistencia en `TaskChangeState`).

> **Nota:** el proyecto no commitea `.env`, `.venv/`, `__pycache__/` ni `.opencode/` (incluidos en `.gitignore`).

---

## 📚 Más información

- `AGENTS.md` — reglas de trabajo y convenciones del repositorio.
- `instrucciones.py` — personalidad, reglas y metodología del agente.
- `agente.py` — ciclo autónomo del Agent Loop y selección de proveedor LLM.

---

## 📄 Licencia

Proyecto de uso interno / educativo. Sin licencia específica declarada.
