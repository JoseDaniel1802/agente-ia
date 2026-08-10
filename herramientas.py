import ast
import os
import re
import tempfile
import difflib
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

from seguridad import WorkspaceManager, CommandSanitizer
from sandbox import SandboxManager

# Instancias globales de seguridad para el aislamiento de rutas y comandos
workspace_manager = WorkspaceManager()
command_sanitizer = CommandSanitizer(workspace_manager)
sandbox_manager = SandboxManager(workspace_manager.workspace_root)

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # Límite máximo de lectura/escritura (2 MB)
MAX_SEARCH_RESULTS = 50  # Límite máximo de resultados en búsqueda


def set_active_workspace(workspace_dir: Union[str, Path]) -> Dict[str, Any]:
    """
    Configura dinámicamente el workspace activo para las herramientas y el sandbox.
    Valida la ruta solicitada con los 7 criterios de seguridad de WorkspaceManager.
    Retorna un diccionario estructurado con el estado del cambio.
    """
    global workspace_manager, command_sanitizer, sandbox_manager
    temp_wm = WorkspaceManager()
    val = temp_wm.validar_nuevo_workspace_root(workspace_dir)
    if not val["valida"]:
        return val

    new_root = val["ruta_absoluta"]
    workspace_manager = WorkspaceManager(new_root)
    command_sanitizer = CommandSanitizer(workspace_manager)
    sandbox_manager = SandboxManager(workspace_manager.workspace_root)

    return {
        "valida": True,
        "error": False,
        "codigo_error": None,
        "mensaje": f"Workspace activo configurado exitosamente en: {new_root}",
        "workspace_root": new_root
    }


# ── HELPERS DRY ──────────────────────────────────────────────────────────


def _validar_ruta_o_error(
    ruta: str,
    must_exist: bool = False,
    is_creation: bool = False
) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
    """
    Valida una ruta mediante WorkspaceManager y retorna (ruta_absoluta, None)
    si es válida, o (None, error_dict) si no lo es.
    Elimina la repetición del patrón if-not-valida-return-error en cada herramienta.
    """
    val = workspace_manager.validar_ruta(ruta, must_exist=must_exist, is_creation=is_creation)
    if not val["valida"]:
        return None, {
            "error": True,
            "codigo_error": val.get("codigo_error", "RUTA_INVALIDA"),
            "mensaje": val["mensaje"]
        }
    return Path(val["ruta_absoluta"]), val


def _is_binary_file(file_path: Path) -> bool:
    """
    Determina si un archivo es binario leyendo los primeros 1024 bytes.
    Retorna True si contiene bytes nulos (indicador de contenido binario).
    """
    try:
        with open(file_path, "rb") as bf:
            first_chunk = bf.read(1024)
            return b"\x00" in first_chunk
    except Exception:
        return False


def analizar_requisitos(texto: str) -> Dict[str, Any]:
    """
    Analiza un texto de caso de uso o requisito y extrae información estructurada.

    Args:
        texto: Texto explicativo del caso de uso, historia de usuario o requisito a analizar.
    """
    if not isinstance(texto, str) or not texto.strip():
        return {
            "error": True,
            "mensaje": "El texto del caso/requisito debe ser una cadena no vacía."
        }

    texto_clean = texto.strip()
    texto_lower = texto_clean.lower()

    lineas = [l.strip() for l in re.split(r"[\n\.]+", texto_clean) if l.strip()]

    patron_actores = r"\b(usuario|cliente|administrador|admin|empleado|profesor|estudiante|sistema|operador|gestor|desarrollador|analista|superusuario|visitante)\b"
    actores = sorted(list(set(re.findall(patron_actores, texto_lower))))

    req_funcionales = []
    req_no_funcionales = []
    restricciones = []
    ambiguedades = []

    palabras_no_funcionales = ["seguridad", "rendimiento", "latencia", "tiempo de respuesta", "disponibilidad", "encripta", "cifrad", "soporta hasta"]
    palabras_restriccion = ["debe", "obligatorio", "únicamente", "solo", "prohibido", "no puede", "exclusivamente", "límite"]
    palabras_ambiguas = ["rápido", "fácil", "eficiente", "adecuado", "mejor", "varios", "pronto", "algunos", "aproximadamente", "etc", "lo antes posible"]

    for idx, linea in enumerate(lineas, 1):
        linea_lower = linea.lower()

        if any(p in linea_lower for p in palabras_no_funcionales):
            req_no_funcionales.append(f"RF-{idx}: {linea}")
        else:
            req_funcionales.append(f"RF-{idx}: {linea}")

        for p in palabras_restriccion:
            if p in linea_lower and linea not in restricciones:
                restricciones.append(f"Restricción detectada en '{linea}' (término clave: '{p}')")

        for p in palabras_ambiguas:
            if p in linea_lower:
                ambiguedades.append(f"Término ambiguo '{p}' en la línea: '{linea}'")

    return {
        "error": False,
        "total_oraciones_analizadas": len(lineas),
        "actores_detectados": actores if actores else ["No especificado explícitamente (se asume usuario/sistema)"],
        "requisitos_funcionales": req_funcionales,
        "requisitos_no_funcionales": req_no_funcionales,
        "restricciones": restricciones,
        "ambiguedades": ambiguedades
    }


def revisar_codigo(codigo: str) -> Dict[str, Any]:
    """
    Realiza una revisión de calidad y sintaxis de código Python mediante análisis sintáctico (AST).

    Args:
        codigo: Fragmento o contenido completo del código fuente en Python a revisar.
    """
    if not isinstance(codigo, str) or not codigo.strip():
        return {
            "error": True,
            "mensaje": "Se debe proporcionar una cadena de código válida y no vacía."
        }

    lineas = codigo.splitlines()
    hallazgos = []
    sugerencias = []
    sintaxis_valida = True
    cantidad_funciones = 0
    cantidad_clases = 0

    try:
        tree = ast.parse(codigo)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                cantidad_funciones += 1
                if not ast.get_docstring(node):
                    hallazgos.append(f"La función '{node.name}' (línea {node.lineno}) no tiene docstring descriptivo.")
            elif isinstance(node, ast.ClassDef):
                cantidad_clases += 1
                if not ast.get_docstring(node):
                    hallazgos.append(f"La clase '{node.name}' (línea {node.lineno}) carece de docstring.")
            elif isinstance(node, ast.ImportFrom):
                if any(alias.name == '*' for alias in node.names):
                    hallazgos.append(f"Línea {node.lineno}: Uso de 'from {node.module} import *' no recomendado.")
            elif isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    hallazgos.append(f"Línea {node.lineno}: Captura de excepción genérica ('except:'). Es mejor especificar la excepción.")

    except SyntaxError as syn_err:
        sintaxis_valida = False
        hallazgos.append(f"Error de sintaxis en la línea {syn_err.lineno}, columna {syn_err.offset}: {syn_err.msg}")

    if len(lineas) > 150:
        hallazgos.append(f"El archivo es extenso ({len(lineas)} líneas). Considera modularizar.")

    if "print(" in codigo:
        sugerencias.append("Se detectaron instrucciones 'print()'. Para entornos de producción, considera utilizar el módulo 'logging'.")

    for i, line in enumerate(lineas, 1):
        if "TODO" in line or "FIXME" in line:
            hallazgos.append(f"Línea {i}: Tarea pendiente encontrada -> {line.strip()}")

    return {
        "error": False,
        "sintaxis_valida": sintaxis_valida,
        "cantidad_lineas": len(lineas),
        "cantidad_funciones": cantidad_funciones,
        "cantidad_clases": cantidad_clases,
        "hallazgos": hallazgos,
        "sugerencias": sugerencias
    }


def generar_pruebas(funcionalidad: str) -> Dict[str, Any]:
    """
    Genera casos de prueba dinámicos y código pytest preliminar basado en la funcionalidad especificada.

    Args:
        funcionalidad: Descripción de la función, clase o caso de uso para el cual generar pruebas.
    """
    if not isinstance(funcionalidad, str) or not funcionalidad.strip():
        return {
            "error": True,
            "mensaje": "Debe indicar una descripción de funcionalidad válida."
        }

    func_clean = funcionalidad.strip()
    palabras = re.findall(r"\w+", func_clean.lower())
    nombre_fn = "_".join(palabras[:4]) if palabras else "funcionalidad"

    casos = [
        {
            "nombre": f"test_{nombre_fn}_exito",
            "tipo": "Caso de éxito (Camino feliz)",
            "entrada": f"Datos de entrada válidos para '{func_clean}'",
            "resultado_esperado": f"Respuesta exitosa o cambio de estado correcto para {func_clean}."
        },
        {
            "nombre": f"test_{nombre_fn}_datos_nulos_o_vacios",
            "tipo": "Caso de error (Entrada vacía/nula)",
            "entrada": "Entrada None, cadena vacía o estructura vacía",
            "resultado_esperado": "Levanta ValueError o devuelve un resultado estructurado con error: True."
        },
        {
            "nombre": f"test_{nombre_fn}_valores_limite",
            "tipo": "Caso límite / Frontera",
            "entrada": "Valores numéricos extremos, cadenas de longitud máxima o caracteres especiales",
            "resultado_esperado": "El sistema maneja la frontera sin crash ni comportamiento indeterminado."
        }
    ]

    codigo_pytest = (
        f"import pytest\n\n"
        f"def test_{nombre_fn}_exito():\n"
        f"    # TODO: Implementar prueba exitosa para {func_clean}\n"
        f"    resultado = {nombre_fn}(\"entrada_valida\")\n"
        f"    assert resultado is not None\n\n"
        f"def test_{nombre_fn}_entrada_invalida():\n"
        f"    with pytest.raises(ValueError):\n"
        f"        {nombre_fn}(None)\n"
    )

    return {
        "error": False,
        "funcionalidad_analizada": func_clean,
        "casos_prueba": casos,
        "codigo_pytest_sugerido": codigo_pytest
    }


def validar_alcance(
    solicitud: str,
    archivos: List[str]
) -> Dict[str, Any]:
    """
    Valida si los archivos especificados concuerdan con el alcance de una solicitud dada.

    Args:
        solicitud: Descripción de la tarea o cambio solicitado.
        archivos: Lista de rutas o nombres de archivos que se pretenden modificar.
    """
    if not isinstance(solicitud, str) or not solicitud.strip():
        return {
            "error": True,
            "mensaje": "La solicitud debe ser una cadena de texto no vacía."
        }

    if not isinstance(archivos, list) or not all(isinstance(a, str) for a in archivos):
        return {
            "error": True,
            "mensaje": "El parámetro 'archivos' debe ser una lista de cadenas de texto."
        }

    if not archivos:
        return {
            "error": True,
            "mensaje": "No se especificaron archivos para evaluar el alcance."
        }

    solicitud_lower = solicitud.lower()
    archivos_limpios = [a.strip() for a in archivos if a.strip()]

    advertencias = []
    archivos_mencionados = []

    for arch in archivos_limpios:
        nombre_base = arch.split("/")[-1].lower()
        if nombre_base in solicitud_lower or arch.lower() in solicitud_lower:
            archivos_mencionados.append(arch)

        if any(sensible in nombre_base for sensible in [".env", "config", "settings", "schema", "database", "secret"]):
            advertencias.append(f"El archivo '{arch}' es de configuración/sensible. Verificar permisos.")

    dentro_alcance = len(archivos_mencionados) > 0 or len(archivos_limpios) <= 3

    return {
        "error": False,
        "solicitud": solicitud,
        "archivos_evaluados": archivos_limpios,
        "archivos_coincidentes_con_solicitud": archivos_mencionados,
        "dentro_del_alcance": dentro_alcance,
        "advertencias": advertencias
    }


def detectar_cambios_significativos(
    archivos: List[str]
) -> Dict[str, Any]:
    """
    Analiza la lista de archivos a modificar para determinar el nivel de riesgo y si requiere confirmación.

    Args:
        archivos: Lista de rutas o nombres de archivos a ser modificados.
    """
    if not isinstance(archivos, list) or not all(isinstance(a, str) for a in archivos):
        return {
            "error": True,
            "mensaje": "Debe proporcionar una lista válida de rutas de archivos (lista de cadenas)."
        }

    if not archivos:
        return {
            "error": True,
            "mensaje": "La lista de archivos está vacía."
        }

    archivos_limpios = [a.strip() for a in archivos if a.strip()]
    archivos_criticos = []

    patrones_criticos = [".env", "requirements.txt", "main.py", "database", "schema", "agente.py", "config"]

    for arch in archivos_limpios:
        if any(patron in arch.lower() for patron in patrones_criticos):
            archivos_criticos.append(arch)

    requiere_confirmacion = len(archivos_limpios) > 4 or len(archivos_criticos) > 0

    if len(archivos_criticos) > 0:
        nivel_riesgo = "Alto"
        motivo = f"Se modificarán archivos críticos del sistema: {', '.join(archivos_criticos)}."
    elif len(archivos_limpios) > 4:
        nivel_riesgo = "Medio"
        motivo = f"Se modificará un volumen considerable de archivos ({len(archivos_limpios)} archivos)."
    else:
        nivel_riesgo = "Bajo"
        motivo = "Cambio focalizado en archivos estándar del proyecto."

    return {
        "error": False,
        "cantidad_archivos": len(archivos_limpios),
        "archivos_criticos_detectados": archivos_criticos,
        "nivel_riesgo": nivel_riesgo,
        "requiere_confirmacion": requiere_confirmacion,
        "motivo": motivo
    }


def generar_plan_trabajo(
    requisitos: List[str]
) -> Dict[str, Any]:
    """
    Genera un plan de trabajo dinámico estructurado por fases a partir de una lista de requisitos.

    Args:
        requisitos: Lista de textos que describen cada uno de los requisitos a cumplir.
    """
    if not isinstance(requisitos, list) or not all(isinstance(r, str) for r in requisitos):
        return {
            "error": True,
            "mensaje": "Debe proporcionar una lista válida de requisitos (lista de cadenas de texto)."
        }

    requisitos_limpios = [r.strip() for r in requisitos if r.strip()]

    if not requisitos_limpios:
        return {
            "error": True,
            "mensaje": "No se encontraron requisitos válidos para planificar."
        }

    plan_fases = []

    plan_fases.append({
        "fase": "Fase 1: Análisis y Validación",
        "tareas": [f"Revisar y clarificar el requisito: '{req}'" for req in requisitos_limpios]
    })

    tareas_impl = []
    for idx, req in enumerate(requisitos_limpios, 1):
        tareas_impl.append(f"Diseñar e implementar componente/función para el requisito #{idx}: '{req}'")

    plan_fases.append({
        "fase": "Fase 2: Diseño e Implementación",
        "tareas": tareas_impl
    })

    plan_fases.append({
        "fase": "Fase 3: Pruebas y Validación",
        "tareas": [f"Ejecutar pruebas unitarias e integración para el requisito #{idx}" for idx in range(1, len(requisitos_limpios) + 1)]
    })

    plan_fases.append({
        "fase": "Fase 4: Documentación y Entrega",
        "tareas": ["Actualizar documentación del código.", "Confirmar cumplimiento de alcance con el usuario."]
    })

    return {
        "error": False,
        "cantidad_requisitos": len(requisitos_limpios),
        "fases_plan": plan_fases
    }


# ── HERRAMIENTAS DE SISTEMA DE ARCHIVOS (FASE 2) ──────────────────────────


def listar_directorio(ruta: str = ".") -> Dict[str, Any]:
    """
    Lista los archivos y subdirectorios dentro de una ruta permitida del workspace.

    Args:
        ruta: Ruta relativa o absoluta del directorio a listar (por defecto '.' para la raíz).
    """
    abs_path, val = _validar_ruta_o_error(ruta, must_exist=True)
    if abs_path is None:
        return val

    if not abs_path.is_dir():
        return {
            "error": True,
            "codigo_error": "NO_ES_UN_DIRECTORIO",
            "mensaje": f"La ruta '{ruta}' no es un directorio."
        }

    try:
        elementos = []
        for entry in os.scandir(abs_path):
            entry_path = Path(entry.path)
            item_val = workspace_manager.validar_ruta(entry_path)
            if not item_val["valida"]:
                continue

            tipo = "directorio" if entry.is_dir() else "archivo"
            elem_info = {
                "nombre": entry.name,
                "tipo": tipo,
                "ruta_relativa": item_val["ruta_relativa"]
            }
            if entry.is_file():
                try:
                    elem_info["tamaño_bytes"] = entry.stat().st_size
                except Exception:
                    elem_info["tamaño_bytes"] = 0

            elementos.append(elem_info)

        elementos.sort(key=lambda x: (0 if x["tipo"] == "directorio" else 1, x["nombre"].lower()))

        return {
            "error": False,
            "ruta_relativa": val["ruta_relativa"],
            "total_elementos": len(elementos),
            "elementos": elementos
        }
    except PermissionError:
        return {
            "error": True,
            "codigo_error": "PERMISO_DENEGADO",
            "mensaje": f"Permisos insuficientes para acceder al directorio '{ruta}'."
        }
    except Exception as e:
        return {
            "error": True,
            "codigo_error": "ERROR_LECTURA_DIRECTORIO",
            "mensaje": f"Error al acceder o listar el directorio '{ruta}': {str(e)}"
        }


def leer_archivo(
    ruta: str,
    linea_inicio: Optional[int] = None,
    linea_fin: Optional[int] = None
) -> Dict[str, Any]:
    """
    Lee el contenido de un archivo de texto permitido dentro del workspace, con soporte opcional de rango de líneas.

    Args:
        ruta: Ruta del archivo de texto a leer dentro del workspace.
        linea_inicio: Número de línea inicial (1-indexed, opcional).
        linea_fin: Número de línea final (inclusive, opcional).
    """
    abs_path, val = _validar_ruta_o_error(ruta, must_exist=True)
    if abs_path is None:
        return val

    if abs_path.is_dir():
        return {
            "error": True,
            "codigo_error": "ES_UN_DIRECTORIO",
            "mensaje": f"La ruta '{ruta}' es un directorio, no un archivo."
        }

    try:
        file_size = abs_path.stat().st_size
    except Exception as e:
        return {
            "error": True,
            "codigo_error": "ERROR_LECTURA_ARCHIVO",
            "mensaje": f"No se pudieron obtener metadatos del archivo '{ruta}': {str(e)}"
        }

    if file_size > MAX_FILE_SIZE_BYTES:
        return {
            "error": True,
            "codigo_error": "ARCHIVO_DEMASIADO_GRANDE",
            "mensaje": f"El archivo '{ruta}' excede el límite máximo permitido de {MAX_FILE_SIZE_BYTES} bytes ({file_size} bytes)."
        }

    if _is_binary_file(abs_path):
        return {
            "error": True,
            "codigo_error": "ARCHIVO_BINARIO_O_ENCODING_INVALIDO",
            "mensaje": f"El archivo '{ruta}' es binario y no puede ser leído como texto plano."
        }

    try:
        with open(abs_path, "r", encoding="utf-8", errors="strict") as f:
            lineas = f.readlines()
    except UnicodeDecodeError:
        return {
            "error": True,
            "codigo_error": "ARCHIVO_BINARIO_O_ENCODING_INVALIDO",
            "mensaje": f"El archivo '{ruta}' contiene secuencias de bytes inválidas para codificación UTF-8."
        }
    except PermissionError:
        return {
            "error": True,
            "codigo_error": "PERMISO_DENEGADO",
            "mensaje": f"Permisos insuficientes para leer el archivo '{ruta}'."
        }
    except Exception as e:
        return {
            "error": True,
            "codigo_error": "ERROR_LECTURA_ARCHIVO",
            "mensaje": f"Error al abrir o leer el archivo '{ruta}': {str(e)}"
        }

    total_lineas = len(lineas)
    start_idx = 0
    end_idx = total_lineas

    if linea_inicio is not None:
        try:
            linea_inicio_int = int(linea_inicio)
            if linea_inicio_int > 0:
                start_idx = max(0, linea_inicio_int - 1)
            else:
                return {
                    "error": True,
                    "codigo_error": "PARAMETRO_INVALIDO",
                    "mensaje": "El parámetro 'linea_inicio' debe ser un entero positivo mayor o igual a 1."
                }
        except (ValueError, TypeError):
            return {
                "error": True,
                "codigo_error": "PARAMETRO_INVALIDO",
                "mensaje": "El parámetro 'linea_inicio' debe ser un número entero."
            }

    if linea_fin is not None:
        try:
            linea_fin_int = int(linea_fin)
            if linea_fin_int >= (start_idx + 1):
                end_idx = min(total_lineas, linea_fin_int)
            else:
                return {
                    "error": True,
                    "codigo_error": "PARAMETRO_INVALIDO",
                    "mensaje": "El parámetro 'linea_fin' debe ser un entero mayor o igual a 'linea_inicio'."
                }
        except (ValueError, TypeError):
            return {
                "error": True,
                "codigo_error": "PARAMETRO_INVALIDO",
                "mensaje": "El parámetro 'linea_fin' debe ser un número entero."
            }

    lineas_seleccionadas = lineas[start_idx:end_idx]
    contenido_texto = "".join(lineas_seleccionadas)

    return {
        "error": False,
        "ruta_relativa": val["ruta_relativa"],
        "tamaño_bytes": file_size,
        "total_lineas": total_lineas,
        "linea_inicio": start_idx + 1 if total_lineas > 0 else 0,
        "linea_fin": end_idx if total_lineas > 0 else 0,
        "contenido": contenido_texto
    }


def escribir_archivo(
    ruta: str,
    contenido: str,
    sobrescribir: bool = False
) -> Dict[str, Any]:
    """
    Crea o modifica de forma segura un archivo dentro del workspace.

    Args:
        ruta: Ruta del archivo a escribir.
        contenido: Contenido completo de texto a escribir en el archivo.
        sobrescribir: Si es True, permite reemplazar el contenido si el archivo ya existe. Por defecto es False.
    """
    if not isinstance(contenido, str):
        return {
            "error": True,
            "codigo_error": "TIPO_INVALIDO",
            "mensaje": "El contenido a escribir debe ser una cadena de texto."
        }

    if len(contenido.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
        return {
            "error": True,
            "codigo_error": "CONTENIDO_DEMASIADO_GRANDE",
            "mensaje": f"El contenido excede el límite máximo permitido de {MAX_FILE_SIZE_BYTES} bytes."
        }

    abs_path, val = _validar_ruta_o_error(ruta, is_creation=True)
    if abs_path is None:
        return val
    existe_previamente = abs_path.exists()

    if existe_previamente and not sobrescribir:
        return {
            "error": True,
            "codigo_error": "ARCHIVO_YA_EXISTE",
            "mensaje": f"El archivo '{ruta}' ya existe. Debe especificar 'sobrescribir=True' para reemplazarlo."
        }

    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile("w", dir=abs_path.parent, delete=False, encoding="utf-8") as tmp:
            tmp.write(contenido)
            tmp_path = Path(tmp.name)

        tmp_path.replace(abs_path)
        bytes_escritos = abs_path.stat().st_size

        return {
            "error": False,
            "operacion": "modificado" if existe_previamente else "creado",
            "ruta_relativa": val["ruta_relativa"],
            "bytes_escritos": bytes_escritos
        }
    except PermissionError:
        return {
            "error": True,
            "codigo_error": "PERMISO_DENEGADO",
            "mensaje": f"Permisos insuficientes para escribir en la ruta '{ruta}'."
        }
    except Exception as e:
        return {
            "error": True,
            "codigo_error": "ERROR_ESCRITURA_ARCHIVO",
            "mensaje": f"Error durante la escritura en el archivo '{ruta}': {str(e)}"
        }


def editar_archivo(
    ruta: str,
    texto_buscar: str,
    texto_reemplazar: str,
    reemplazar_todas: bool = False
) -> Dict[str, Any]:
    """
    Realiza una edición localizada en un archivo existente reemplazando un bloque de texto exacto.

    Args:
        ruta: Ruta del archivo a editar dentro del workspace.
        texto_buscar: Bloque exacto de texto que se desea reemplazar dentro del archivo.
        texto_reemplazar: Nuevo bloque de texto que sustituirá a texto_buscar.
        reemplazar_todas: Si es True, reemplaza todas las apariciones de texto_buscar. Por defecto es False (exige coincidencia única).
    """
    if not isinstance(texto_buscar, str) or not texto_buscar:
        return {
            "error": True,
            "codigo_error": "PARAMETRO_INVALIDO",
            "mensaje": "El parámetro 'texto_buscar' debe ser una cadena de texto no vacía."
        }

    if not isinstance(texto_reemplazar, str):
        return {
            "error": True,
            "codigo_error": "PARAMETRO_INVALIDO",
            "mensaje": "El parámetro 'texto_reemplazar' debe ser una cadena de texto."
        }

    # Normalizar saltos de línea escapados si se recibieron como literales
    if "\\n" in texto_buscar and "\n" not in texto_buscar:
        texto_buscar = texto_buscar.replace("\\n", "\n")
    if "\\n" in texto_reemplazar and "\n" not in texto_reemplazar:
        texto_reemplazar = texto_reemplazar.replace("\\n", "\n")

    abs_path, val = _validar_ruta_o_error(ruta, must_exist=True)
    if abs_path is None:
        return val

    if abs_path.is_dir():
        return {
            "error": True,
            "codigo_error": "ES_UN_DIRECTORIO",
            "mensaje": f"La ruta '{ruta}' es un directorio, no un archivo."
        }

    try:
        with open(abs_path, "r", encoding="utf-8", errors="strict") as f:
            contenido_original = f.read()
    except UnicodeDecodeError:
        return {
            "error": True,
            "codigo_error": "ARCHIVO_BINARIO_O_ENCODING_INVALIDO",
            "mensaje": f"El archivo '{ruta}' contiene caracteres binarios o una codificación no UTF-8."
        }
    except PermissionError:
        return {
            "error": True,
            "codigo_error": "PERMISO_DENEGADO",
            "mensaje": f"Permisos insuficientes para leer el archivo '{ruta}'."
        }
    except Exception as e:
        return {
            "error": True,
            "codigo_error": "ERROR_LECTURA_ARCHIVO",
            "mensaje": f"Error al leer el archivo para edición '{ruta}': {str(e)}"
        }

    coincidencias = contenido_original.count(texto_buscar)

    if coincidencias == 0:
        return {
            "error": True,
            "codigo_error": "TEXTO_NO_ENCONTRADO",
            "mensaje": f"El texto a buscar no fue encontrado en el archivo '{ruta}'."
        }

    if coincidencias > 1 and not reemplazar_todas:
        return {
            "error": True,
            "codigo_error": "TEXTO_AMBIGUO_MULTIPLE",
            "mensaje": f"El texto a buscar aparece {coincidencias} veces en '{ruta}'. Para reemplazar todas las apariciones, use 'reemplazar_todas=True' o proporcione un fragmento de texto único."
        }

    if reemplazar_todas:
        nuevo_contenido = contenido_original.replace(texto_buscar, texto_reemplazar)
        reemplazos_hechos = coincidencias
    else:
        nuevo_contenido = contenido_original.replace(texto_buscar, texto_reemplazar, 1)
        reemplazos_hechos = 1

    diff_lines = list(difflib.unified_diff(
        contenido_original.splitlines(keepends=True),
        nuevo_contenido.splitlines(keepends=True),
        fromfile=f"a/{val['ruta_relativa']}",
        tofile=f"b/{val['ruta_relativa']}",
        n=2
    ))
    diff_resumen = "".join(diff_lines[:30])

    try:
        with tempfile.NamedTemporaryFile("w", dir=abs_path.parent, delete=False, encoding="utf-8") as tmp:
            tmp.write(nuevo_contenido)
            tmp_path = Path(tmp.name)

        tmp_path.replace(abs_path)

        return {
            "error": False,
            "operacion": "editado",
            "ruta_relativa": val["ruta_relativa"],
            "coincidencias_reemplazadas": reemplazos_hechos,
            "tamaño_anterior_bytes": len(contenido_original.encode("utf-8")),
            "tamaño_nuevo_bytes": len(nuevo_contenido.encode("utf-8")),
            "diff_resumen": diff_resumen
        }
    except PermissionError:
        return {
            "error": True,
            "codigo_error": "PERMISO_DENEGADO",
            "mensaje": f"Permisos insuficientes para modificar el archivo '{ruta}'."
        }
    except Exception as e:
        return {
            "error": True,
            "codigo_error": "ERROR_ESCRITURA_ARCHIVO",
            "mensaje": f"Error durante la escritura al editar '{ruta}': {str(e)}"
        }


def buscar_en_proyecto(
    patron: str,
    ruta_base: str = "."
) -> Dict[str, Any]:
    """
    Busca coincidencias de texto dentro de los archivos autorizados del proyecto workspace.

    Args:
        patron: Texto o palabra a buscar dentro de los archivos del proyecto.
        ruta_base: Subdirectorio inicial desde el cual buscar (por defecto '.' para todo el workspace).
    """
    if not isinstance(patron, str) or not patron.strip():
        return {
            "error": True,
            "codigo_error": "PARAMETRO_INVALIDO",
            "mensaje": "El patrón de búsqueda debe ser una cadena de texto no vacía."
        }

    abs_base, val = _validar_ruta_o_error(ruta_base, must_exist=True)
    if abs_base is None:
        return val
    patron_lower = patron.strip().lower()
    coincidencias = []
    limite_alcanzado = False

    try:
        for root, dirs, files in os.walk(abs_base):
            root_path = Path(root)

            dirs[:] = [
                d for d in dirs
                if workspace_manager.validar_ruta(root_path / d)["valida"]
            ]

            for file in files:
                file_path = root_path / file
                val_file = workspace_manager.validar_ruta(file_path)
                if not val_file["valida"]:
                    continue

                try:
                    if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                        continue

                    if _is_binary_file(file_path):
                        continue

                    with open(file_path, "r", encoding="utf-8", errors="strict") as f:
                        for line_num, line in enumerate(f, 1):
                            if patron_lower in line.lower():
                                coincidencias.append({
                                    "archivo": val_file["ruta_relativa"],
                                    "linea": line_num,
                                    "contenido": line.strip()[:200]
                                })
                                if len(coincidencias) >= MAX_SEARCH_RESULTS:
                                    limite_alcanzado = True
                                    break
                except Exception:
                    continue

                if limite_alcanzado:
                    break
            if limite_alcanzado:
                break

        return {
            "error": False,
            "patron_buscado": patron,
            "total_coincidencias": len(coincidencias),
            "limite_alcanzado": limite_alcanzado,
            "coincidencias": coincidencias
        }
    except Exception as e:
        return {
            "error": True,
            "codigo_error": "ERROR_BUSQUEDA",
            "mensaje": f"Error durante la búsqueda en el proyecto: {str(e)}"
        }


# ── HERRAMIENTAS DE EJECUCIÓN BASH SEGURO (FASE 3) ──────────────────────────


def ejecutar_comando_bash(
    comando: str,
    timeout_sec: int = 15
) -> Dict[str, Any]:
    """
    Ejecuta de forma aislada y segura un comando de consola Bash dentro del workspace.

    Args:
        comando: Comando de consola a ejecutar (ej. 'pytest', 'git status', 'ls').
        timeout_sec: Tiempo límite de ejecución en segundos (por defecto 15s, máximo 30s).
    """
    return command_sanitizer.ejecutar_comando(
        raw_command=comando,
        timeout_sec=timeout_sec,
        aprobar_confirmacion=False
    )