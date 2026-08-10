"""
Interfaz principal e interacción de usuario para Muss_Code CLI con Rich y Questionary.
Gestiona el bucle de conversación, capturas de señales, spinners live y comunicación con el agente.
"""

import sys
from typing import Optional
import questionary

import agente
from agente import crear_chat, enviar_mensaje, ChatSession
import herramientas
from cli.presentacion import (
    mostrar_banner,
    solicitar_confirmacion_usuario_cli,
    mostrar_invocacion_herramienta,
    mostrar_respuesta_agente,
    mostrar_error,
    iniciar_spinner_agente,
    detener_spinner_agente,
    console,
    QUESTIONARY_STYLE,
)
from cli.comandos import es_comando_slash, procesar_comando_slash


def solicitar_confirmacion_usuario(comando_o_recurso: str, mensaje_explicativo: str) -> bool:
    """
    Callback para autorizaciones humanas expuesto a la API de ChatSession.
    Delega en la interfaz formateada de la CLI con Rich y Questionary.
    """
    return solicitar_confirmacion_usuario_cli(comando_o_recurso, mensaje_explicativo)


def run_cli() -> None:
    """
    Punto de entrada principal para ejecutar la interfaz interactiva CLI de Muss_Code.
    """
    workspace_path = str(herramientas.workspace_manager.workspace_root)
    docker_activo = herramientas.sandbox_manager.is_available()
    cant_herramientas = len(agente.tools)
    model_name = agente.MODEL_NAME

    mostrar_banner(
        workspace_path=workspace_path,
        docker_activo=docker_activo,
        cant_herramientas=cant_herramientas,
        model_name=model_name,
    )

    chat = crear_chat(
        confirmador_callback=solicitar_confirmacion_usuario,
        on_tool_call=mostrar_invocacion_herramienta,
    )

    while True:
        try:
            console.print("\n[brand.cyan]╭─ You[/brand.cyan]")
            mensaje = questionary.text(
                "╰─> ",
                style=QUESTIONARY_STYLE,
            ).ask()
            
            if mensaje is None:  # Ctrl+C o Ctrl+D en questionary
                console.print("\n[bold gold3]🐕 🌭 Muss_Code: hasta luego. 👋[/bold gold3]\n")
                break
                
            mensaje = mensaje.strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[bold gold3]🐕 🌭 Muss_Code: hasta luego. 👋[/bold gold3]\n")
            break

        if not mensaje:
            continue

        if es_comando_slash(mensaje):
            debe_continuar = procesar_comando_slash(mensaje, chat)
            if not debe_continuar:
                break
            continue

        iniciar_spinner_agente("Muss_Code está analizando e inspeccionando la tarea...")

        try:
            respuesta = enviar_mensaje(chat, mensaje)
            detener_spinner_agente()
            mostrar_respuesta_agente(respuesta)
        except KeyboardInterrupt:
            detener_spinner_agente()
            console.print("\n[status.warn]⚠️  Operación cancelada por el usuario.[/status.warn]\n")
        except Exception as e:
            detener_spinner_agente()
            mostrar_error(
                titulo="No fue posible completar la comunicación con el agente.",
                detalle=str(e),
                codigo_error="ERROR_INTERNO_AGENTE",
            )
