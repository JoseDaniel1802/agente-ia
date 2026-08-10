"""
Presentación y Formateo Visual Avanzado para Muss_Code CLI usando Rich.
Paleta de marca 🐕 🌭, renderizado Markdown con Syntax Highlighting, Paneles, Tablas y Spinners.
"""

import os
import sys
from typing import Dict, Any, List, Optional, Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.status import Status
from rich.theme import Theme
import questionary
from questionary import Choice, Style

import herramientas

# ── Paleta de Marca 🐕 🌭 Muss_Code ─────────────────────────────
BRAND_THEME = Theme({
    "brand.gold": "bold gold3",
    "brand.cyan": "bold cyan",
    "brand.red": "bold bright_red",
    "brand.muted": "dim white",
    "status.ok": "bold green",
    "status.warn": "bold yellow",
    "status.error": "bold red",
})

console = Console(theme=BRAND_THEME)

# Estilo personalizado para Questionary
QUESTIONARY_STYLE = Style([
    ('qmark', 'fg:#D4AF37 bold'),       # 🐕 🌭 Dorado
    ('question', 'bold fg:#00A3E0'),     # Cyan
    ('answer', 'fg:#2ECC71 bold'),       # Verde
    ('pointer', 'fg:#D4AF37 bold'),      # Dorado
    ('highlighted', 'fg:#D4AF37 bold'),  # Dorado
    ('selected', 'fg:#2ECC71 bold'),     # Verde
    ('separator', 'fg:#7F8C8D'),
    ('instruction', 'fg:#7F8C8D italic'),
])

# Contexto global del spinner activo si existe
_active_status: Optional[Status] = None


def get_console() -> Console:
    """Devuelve la instancia global de Rich Console."""
    return console


def iniciar_spinner_agente(mensaje: str = "Muss_Code está pensando...") -> Status:
    """Inicia y devuelve un spinner de estado en tiempo real."""
    global _active_status
    _active_status = console.status(f"[brand.gold]🐕 🌭 {mensaje}[/brand.gold]", spinner="dots")
    _active_status.start()
    return _active_status


def actualizar_spinner_agente(mensaje: str) -> None:
    """Actualiza el texto del spinner activo."""
    global _active_status
    if _active_status and _active_status._live.is_started:
        _active_status.update(f"[brand.gold]🐕 🌭 {mensaje}[/brand.gold]")


def detener_spinner_agente() -> None:
    """Detiene el spinner de estado activo."""
    global _active_status
    if _active_status and _active_status._live.is_started:
        _active_status.stop()
    _active_status = None


# ── BANNER Y CABECERA ──────────────────────────────────────────────
def mostrar_banner(workspace_path: str, docker_activo: bool, cant_herramientas: int, model_name: str) -> None:
    """Muestra la cabecera visual y la identidad de Muss_Code con Rich Panels."""
    sandbox_str = "[status.ok]● Docker activo[/status.ok]" if docker_activo else "[status.warn]○ Docker no disponible[/status.warn]"

    header_text = Text()
    header_text.append("\n🐕 🌭  MUSS_CODE\n", style="bold gold3")
    header_text.append("Autonomous Software Engineer\n", style="dim white")

    panel_header = Panel(
        header_text,
        border_style="cyan",
        expand=False,
        subtitle="[dim]Mac OS Security & Docker Sandbox[/dim]",
        subtitle_align="right",
    )

    console.print(panel_header)

    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Key", style="bold white")
    info_table.add_column("Value")

    info_table.add_row("Workspace:", workspace_path)
    info_table.add_row("Sandbox:", sandbox_str)
    info_table.add_row("Herramientas:", f"[bold cyan]{cant_herramientas}[/bold cyan] disponibles")
    info_table.add_row("Modelo LLM:", f"[bold yellow]{model_name}[/bold yellow]")

    console.print(info_table)
    console.print("\n[dim]Escribe una tarea para comenzar o [/dim][bold cyan]/help[/bold cyan][dim] para abrir el menú.[/dim]\n")


# ── NOTIFICACIÓN DE HERRAMIENTAS EN TIEMPO REAL ───────────────────
def mostrar_invocacion_herramienta(iteration: int, nombre: str, args: Dict[str, Any]) -> None:
    """Formatea la llamada a una herramienta en tiempo real dentro de Rich."""
    arg_summary = []
    for k, v in args.items():
        val_str = repr(v)
        if len(val_str) > 35:
            val_str = val_str[:32] + "..."
        arg_summary.append(f"[dim]{k}=[/dim][cyan]{val_str}[/cyan]")

    str_args = ", ".join(arg_summary)
    detalles = f"({str_args})" if str_args else "()"

    msg = f"Tool [{iteration}]: [bold cyan]{nombre}[/bold cyan]{detalles}"
    
    if _active_status and _active_status._live.is_started:
        _active_status.update(f"[brand.gold]🐕 🌭 {msg}[/brand.gold]")
    else:
        console.print(f"  [brand.cyan]→[/brand.cyan] [bold cyan]{nombre}[/bold cyan] [dim]{detalles}[/dim]")


# ── RENDERIZADO DE RESPUESTA MARKDOWN + SYNTAX HIGHLIGHTING ─────────
def mostrar_respuesta_agente(respuesta_texto: str) -> None:
    """
    Renderiza la respuesta del agente con Markdown nativo y sintaxis coloreada para bloques de código.
    """
    detener_spinner_agente()
    console.print("\n[brand.gold]🐕 🌭 Muss_Code[/brand.gold]\n")
    md = Markdown(respuesta_texto, code_theme="monokai")
    console.print(md)
    console.print()


# ── SOLICITUD DE CONFIRMACIÓN HUMANA ─────────────────────────────
def solicitar_confirmacion_usuario_cli(comando_o_recurso: str, mensaje_explicativo: str) -> bool:
    """
    Presenta al usuario en la CLI una solicitud explícita de autorización con Questionary y Rich Panel.
    """
    detener_spinner_agente()

    panel_content = Text()
    panel_content.append("⚠️  AUTORIZACIÓN REQUERIDA POR EL AGENTE\n\n", style="bold gold3")
    panel_content.append("Operación: ", style="bold white")
    panel_content.append(f"{comando_o_recurso}\n", style="bold cyan")
    panel_content.append("Detalle:   ", style="bold white")
    panel_content.append(f"{mensaje_explicativo}\n", style="dim white")

    console.print(Panel(panel_content, border_style="gold3", expand=False))

    try:
        aprobado = questionary.confirm(
            "¿Deseas autorizar la ejecución de esta operación?",
            default=False,
            style=QUESTIONARY_STYLE,
        ).ask()
        
        if aprobado:
            console.print("[status.ok]✓ Operación AUTORIZADA por el usuario.[/status.ok]\n")
            return True
        else:
            console.print("[status.error]❌ Operación DENEGADA por el usuario.[/status.error]\n")
            return False
    except (EOFError, KeyboardInterrupt):
        console.print("\n[status.error]❌ Operación DENEGADA por cancelación.[/status.error]\n")
        return False


def solicitar_cambio_workspace_cli(nueva_ruta: str) -> bool:
    """
    Solicita al usuario confirmación explícita con Questionary para cambiar el workspace activo.
    """
    detener_spinner_agente()
    current_ws = str(herramientas.workspace_manager.workspace_root)

    panel_text = Text()
    panel_text.append("📁  SOLICITUD DE CAMBIO DE WORKSPACE\n\n", style="bold gold3")
    panel_text.append("Workspace actual: ", style="bold white")
    panel_text.append(f"{current_ws}\n", style="dim white")
    panel_text.append("Nuevo workspace:  ", style="bold white")
    panel_text.append(f"{nueva_ruta}\n", style="bold cyan")

    console.print(Panel(panel_text, border_style="gold3", expand=False))

    try:
        aprobado = questionary.confirm(
            f"¿Deseas cambiar el workspace activo a '{nueva_ruta}'?",
            default=True,
            style=QUESTIONARY_STYLE,
        ).ask()
        
        if aprobado:
            console.print("[status.ok]✓ Cambio de workspace AUTORIZADO por el usuario.[/status.ok]\n")
            return True
        else:
            console.print("[status.error]❌ Cambio de workspace DENEGADO por el usuario.[/status.error]\n")
            return False
    except (EOFError, KeyboardInterrupt):
        console.print("\n[status.error]❌ Cambio de workspace DENEGADO por cancelación.[/status.error]\n")
        return False


# ── FORMATO DE ERRORES ─────────────────────────────────────────────
def mostrar_error(titulo: str, detalle: str, codigo_error: Optional[str] = None) -> None:
    """Presenta un mensaje de error formateado en un Rich Panel."""
    detener_spinner_agente()
    cod_str = f" [{codigo_error}]" if codigo_error else ""
    err_text = Text()
    err_text.append(f"✗ Error{cod_str}\n\n", style="bold bright_red")
    err_text.append(f"{titulo}\n", style="bold white")
    if detalle:
        err_text.append(f"\n{detalle}", style="dim white")

    console.print(Panel(err_text, border_style="bright_red", expand=False))


# ── COMANDOS SLASH RESULTADOS ──────────────────────────────────────
def mostrar_help() -> None:
    """Muestra la ayuda formateada en una tabla Rich."""
    table = Table(title="🐕 🌭 Muss_Code — Comandos Disponibles", border_style="gold3", header_style="bold cyan")
    table.add_column("Comando", style="bold cyan", width=15)
    table.add_column("Descripción", style="white")

    table.add_row("/help", "Mostrar este menú de ayuda interactivo")
    table.add_row("/status", "Mostrar el estado del agente, sandbox Docker y políticas de seguridad")
    table.add_row("/tools", "Mostrar las 12 herramientas registradas en el agente")
    table.add_row("/workspace", "Mostrar la ruta del workspace activo y estado de aislamiento")
    table.add_row("/clear", "Limpiar la pantalla de la terminal")
    table.add_row("/exit", "Salir de la aplicación Muss_Code (también: quit, exit)")

    console.print(table)


def mostrar_status(
    workspace_path: str,
    docker_activo: bool,
    cant_herramientas: int,
    model_name: str,
) -> None:
    """Muestra el estado detallado de Muss_Code en una tabla Rich."""
    sandbox_str = "[status.ok]● Docker disponible (Fail-closed activo)[/status.ok]" if docker_activo else "[status.warn]○ Docker no disponible[/status.warn]"

    table = Table(title="🐕 🌭 Estado del Sistema Muss_Code", border_style="cyan", header_style="bold gold3")
    table.add_column("Componente", style="bold white", width=20)
    table.add_column("Estado / Valor", style="white")

    table.add_row("Agente", "[status.ok]● Online[/status.ok]")
    table.add_row("Workspace", workspace_path)
    table.add_row("Sandbox OS", sandbox_str)
    table.add_row("Modelo LLM", f"[bold yellow]{model_name}[/bold yellow]")
    table.add_row("Herramientas", f"[bold cyan]{cant_herramientas}[/bold cyan] registradas")
    table.add_row("Seguridad", "[status.ok]● Workspace Aislado | ● Sandbox Docker | ● Fail-Closed[/status.ok]")

    console.print(table)


def mostrar_workspace_info(workspace_path: str, docker_activo: bool) -> None:
    """Muestra la información del workspace activo."""
    sandbox_str = "[status.ok]● Docker activo[/status.ok]" if docker_activo else "[status.warn]○ Docker no disponible[/status.warn]"
    
    panel_text = Text()
    panel_text.append("🐕 🌭 Workspace Activo\n\n", style="bold gold3")
    panel_text.append(f"Ruta:    {workspace_path}\n", style="bold white")
    panel_text.append(f"Sandbox: {sandbox_str}\n", style="white")

    console.print(Panel(panel_text, border_style="gold3", expand=False))


def mostrar_tools(tools_schemas: List[Dict[str, Any]]) -> None:
    """Muestra la lista de herramientas registradas organizadas en tablas Rich."""
    console.print("\n[bold gold3]🐕 🌭 Herramientas Registradas[/bold gold3]\n")

    categorias = {
        "Workspace & Archivos": ["listar_directorio", "leer_archivo", "escribir_archivo", "editar_archivo", "buscar_en_proyecto"],
        "Análisis & Planificación": ["analizar_requisitos", "revisar_codigo", "generar_pruebas", "validar_alcance", "detectar_cambios_significativos", "generar_plan_trabajo"],
        "Ejecución Segura": ["ejecutar_comando_bash"]
    }

    tools_by_name = {}
    for t in tools_schemas:
        fn = t.get("function", {})
        tools_by_name[fn.get("name")] = fn.get("description", "Sin descripción.")

    for cat, fn_names in categorias.items():
        table = Table(title=f"Categoría: {cat}", border_style="cyan", header_style="bold gold3")
        table.add_column("Herramienta", style="bold cyan", width=32)
        table.add_column("Descripción", style="dim white")

        for fname in fn_names:
            desc = tools_by_name.get(fname, "Herramienta registrada.")
            table.add_row(fname, desc)

        console.print(table)
        console.print()


def limpiar_pantalla() -> None:
    """Limpia la pantalla de la terminal."""
    console.clear()
