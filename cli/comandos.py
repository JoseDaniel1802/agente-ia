"""
Manejador de Comandos Slash e Interacción con Menús Questionary para Muss_Code.
Procesa /help, /status, /tools, /workspace, /clear, /exit con menús interactivos por teclado.
"""

from typing import Dict, Any, List
import questionary
from questionary import Choice

import agente
import herramientas
from cli.presentacion import (
    mostrar_help,
    mostrar_status,
    mostrar_workspace_info,
    mostrar_tools,
    limpiar_pantalla,
    console,
    QUESTIONARY_STYLE,
)


def es_comando_slash(mensaje: str) -> bool:
    """Retorna True si el mensaje del usuario es un comando slash o comando de salida."""
    msg = mensaje.strip().lower()
    return msg.startswith("/") or msg in ("salir", "exit", "quit", "quit()")


def abrir_menu_interactivo(chat_session: Any) -> bool:
    """Abre un menú interactivo con flechas de teclado usando Questionary."""
    workspace_path = str(herramientas.workspace_manager.workspace_root)
    docker_activo = herramientas.sandbox_manager.is_available()

    try:
        opcion = questionary.select(
            "🐕 🌭 Menú de Acciones de Muss_Code:",
            choices=[
                Choice("📊 /status    - Ver estado del agente, sandbox y seguridad", value="/status"),
                Choice("🛠️  /tools     - Listar las 12 herramientas registradas", value="/tools"),
                Choice("📁 /workspace - Ver workspace activo y aislamiento", value="/workspace"),
                Choice("🧹 /clear     - Limpiar pantalla de la terminal", value="/clear"),
                Choice("❓ /help      - Mostrar tabla con ayuda de comandos", value="/help_table"),
                Choice("💬 Continuar  - Escribir una tarea directamente", value="continue"),
                Choice("❌ /exit      - Salir de Muss_Code", value="/exit"),
            ],
            style=QUESTIONARY_STYLE,
        ).ask()
    except (EOFError, KeyboardInterrupt):
        print("\n🐕 🌭 Muss_Code: hasta luego. 👋\n")
        return False

    if not opcion or opcion == "continue":
        return True

    if opcion == "/help_table":
        mostrar_help()
        return True

    return procesar_comando_slash(opcion, chat_session)


def procesar_comando_slash(mensaje: str, chat_session: Any) -> bool:
    """
    Procesa el comando slash.
    Retorna True si el bucle de la CLI debe continuar, o False si debe salir (/exit).
    """
    cmd = mensaje.strip().lower()

    if cmd in ("/exit", "salir", "exit", "quit", "quit()"):
        console.print("\n[bold gold3]🐕 🌭 Muss_Code: hasta luego. 👋[/bold gold3]\n")
        return False

    if cmd == "/help":
        return abrir_menu_interactivo(chat_session)

    workspace_path = str(herramientas.workspace_manager.workspace_root)
    docker_activo = herramientas.sandbox_manager.is_available()

    if cmd == "/status":
        mostrar_status(
            workspace_path=workspace_path,
            docker_activo=docker_activo,
            cant_herramientas=len(agente.tools),
            model_name=agente.MODEL_NAME,
        )
        return True

    if cmd.startswith("/workspace"):
        partes = mensaje.strip().split(maxsplit=1)
        if len(partes) == 1:
            mostrar_workspace_info(
                workspace_path=workspace_path,
                docker_activo=docker_activo,
            )
            return True

        target_dir = partes[1].strip()
        if (target_dir.startswith('"') and target_dir.endswith('"')) or (target_dir.startswith("'") and target_dir.endswith("'")):
            target_dir = target_dir[1:-1].strip()

        val = herramientas.workspace_manager.validar_nuevo_workspace_root(target_dir)
        if not val["valida"]:
            from cli.presentacion import mostrar_error
            mostrar_error(
                titulo=f"No se puede cambiar al workspace '{target_dir}'",
                detalle=val["mensaje"],
                codigo_error=val.get("codigo_error", "WORKSPACE_INVALIDO")
            )
            return True

        nueva_ruta_abs = val["ruta_absoluta"]
        from cli.presentacion import solicitar_cambio_workspace_cli
        aprobado = solicitar_cambio_workspace_cli(nueva_ruta_abs)
        if aprobado:
            try:
                res = herramientas.set_active_workspace(nueva_ruta_abs)
                if res.get("valida"):
                    console.print(f"[status.ok]✓ Workspace configurado exitosamente en: {nueva_ruta_abs}[/status.ok]")
                    console.print(f"[dim]● Docker Sandbox re-montado únicamente en: {nueva_ruta_abs}[/dim]\n")
                else:
                    from cli.presentacion import mostrar_error
                    mostrar_error(
                        titulo="Error al establecer el nuevo workspace",
                        detalle=res.get("mensaje", "Error desconocido"),
                        codigo_error=res.get("codigo_error")
                    )
            except Exception as err:
                from cli.presentacion import mostrar_error
                mostrar_error(
                    titulo="Error inesperado durante el cambio de workspace",
                    detalle=str(err),
                    codigo_error="ERROR_CAMBIO_WORKSPACE"
                )
        return True

    if cmd == "/tools":
        mostrar_tools(agente.tools)
        return True

    if cmd == "/clear":
        limpiar_pantalla()
        return True

    console.print(f"\n[status.warn]⚠️  Comando desconocido '{mensaje}'. Escribe /help para ver la lista de comandos.[/status.warn]\n")
    return True
