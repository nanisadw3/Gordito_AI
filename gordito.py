#!/usr/bin/env python3
"""
Gordito (gprdito) - Interfaz Minimalista y Limpia
Un asistente de terminal elegante, rápido y sin ruido visual.
"""

import os
import sys

_VENV = os.path.expanduser("~/Documents/agente/.venv/bin/python3")
if sys.prefix == sys.base_prefix and os.path.exists(_VENV):
    os.execv(_VENV, [_VENV] + sys.argv)
import asyncio
from typing import List

from ollama import AsyncClient
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from core import (
    LOCAL_TOOL_FUNCTIONS,
    MCPManager,
    obtener_modelos_instalados,
    obtener_todas_las_herramientas,
    SYSTEM_PROMPT_GORDITO,
    spotify_estado,
    CONFIG_MCP_PATH,
    imprimir_banner_gordito,
    renderizar_respuesta_gordito,
    renderizar_streaming_panel,
    ejecutar_mision_autonoma,
    ejecutar_modo_flow,
    obtener_nombre_os,
    mostrar_tabla_herramientas,
)

console = Console()

# ==========================================
# 1. Comandos Slash y Autocompletado
# ==========================================

SLASH_COMMANDS = {
    "/flow": "Activar el DJ de código de Gordito (ej: /flow, /flow hacker, /flow chill, /flow rock)",
    "/mision": "Ejecutar una misión autónoma multi-paso (ej: /mision investiga el dólar y crea reporte)",
    "/spotify": "Ver o pausar tu música en Spotify",
    "/mcp": "Ver servidores MCP conectados",
    "/models": "Cambiar de modelo de lenguaje",
    "/model": "Cambiar directamente de modelo (ej: /model llama3.1:latest)",
    "/tools": "Ver y explorar todas las herramientas conectadas (ej: /tools, /tools browser, /tools spotify)",
    "/clear": "Limpiar la pantalla y reiniciar memoria",
    "/help": "Ver comandos disponibles",
    "/exit": "Salir de Gordito",
    "/salir": "Salir de Gordito",
}

class MinimalCompleter(Completer):
    def __init__(self, get_models_callback):
        self.get_models_callback = get_models_callback

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/model "):
            prefix = text[7:]
            for m in self.get_models_callback():
                if m.lower().startswith(prefix.lower()):
                    yield Completion(
                        m,
                        start_position=-len(prefix),
                        display=f"🤖 {m}",
                        display_meta="Modelo"
                    )
            return

        if text.startswith("/"):
            for cmd, desc in SLASH_COMMANDS.items():
                if cmd.lower().startswith(text.lower()):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=f"⚡ {cmd}",
                        display_meta=desc
                    )

MINIMAL_STYLE = Style.from_dict({
    "prompt": "bold #50fa7b",
    "completion-menu": "bg:#1e1f29 #f8f8f2",
    "completion-menu.completion": "bg:#191a21 #6272a4",
    "completion-menu.completion.current": "bg:#282a36 #50fa7b bold",
    "completion-menu.meta": "bg:#191a21 #44475a italic",
    "completion-menu.meta.current": "bg:#282a36 #f1fa8c italic",
})


def describir_accion_herramienta(nombre: str, args: dict) -> str:
    """Genera una línea compacta y hacker describiendo la acción."""
    if nombre == "buscar_en_internet":
        return f"[bold cyan][NET_WEB][/bold cyan] Query: [italic green]'{args.get('consulta', '')}'[/italic green]"
    elif nombre == "leer_pagina_web":
        return f"[bold cyan][NET_REQ][/bold cyan] Fetch URL: [italic]{args.get('url', '')}[/italic]"
    elif nombre == "spotify_estado":
        return f"[bold green][SPOTIFY][/bold green] Querying {obtener_nombre_os()} track info..."
    elif nombre == "spotify_control":
        return f"[bold green][SPOTIFY][/bold green] Action: [italic]{args.get('accion', '')}[/italic]"
    elif nombre == "spotify_reproducir":
        return f"[bold green][SPOTIFY][/bold green] Play: [italic]{args.get('nombre_o_uri', '')}[/italic]"
    elif nombre == "spotify_mis_favoritos":
        return "[bold green][SPOTIFY][/bold green] Scanning 440 library tracks..."
    elif nombre == "listar_archivos":
        return f"[bold yellow][FS_LIST][/bold yellow] Path: [dim]{args.get('ruta', '.')}[/dim]"
    elif nombre == "cambiar_directorio":
        return f"[bold yellow][FS_CHDIR][/bold yellow] Navigate: [dim]{args.get('ruta', '')}[/dim]"
    elif nombre == "leer_archivo":
        return f"[bold yellow][FS_READ][/bold yellow] File: [dim]{args.get('ruta', '')}[/dim]"
    elif nombre == "escribir_archivo":
        return f"[bold yellow][FS_WRITE][/bold yellow] File: [dim]{args.get('ruta', '')}[/dim]"
    elif nombre == "ejecutar_comando":
        return f"[bold magenta][SYS_EXEC][/bold magenta] Exec: [dim]${args.get('comando', '')}[/dim]"
    elif nombre == "info_sistema":
        return "[bold magenta][SYS_INFO][/bold magenta] Querying host clock & system..."
    elif "tipo_cambio" in nombre or "banxico" in nombre or "inflacion" in nombre or "udis" in nombre:
        return f"[bold cyan][MCP_RPC][/bold cyan] Banxico: [italic]{nombre}[/italic]"
    elif nombre.startswith("browser_"):
        sub = nombre.replace("browser_", "")
        if sub == "navigate":
            return f"[bold cyan][PLAYWRIGHT][/bold cyan] Navigate: [italic]{args.get('url', '')}[/italic]"
        elif sub == "click":
            return f"[bold cyan][PLAYWRIGHT][/bold cyan] Click: [dim]{args.get('selector', args.get('text', ''))}[/dim]"
        elif sub in ["type", "fill_form"]:
            return f"[bold cyan][PLAYWRIGHT][/bold cyan] Input: [dim]{args.get('text', '')}[/dim]"
        elif sub == "take_screenshot":
            return "[bold cyan][PLAYWRIGHT][/bold cyan] Capturing browser screenshot..."
        elif sub == "snapshot":
            return "[bold cyan][PLAYWRIGHT][/bold cyan] Inspecting DOM accessibility tree..."
        return f"[bold cyan][PLAYWRIGHT][/bold cyan] Action: [italic]{nombre}[/italic]"
    return f"[bold cyan][ACT_TOOL][/bold cyan] [dim]{nombre}[/dim]"


async def ejecutar_turno_minimal(
    cliente_ollama: AsyncClient,
    modelo: str,
    mensajes: list,
    mcp_mgr: MCPManager
) -> str:
    """Ejecuta el ciclo de herramientas de forma discreta y minimalista."""
    todas_las_herramientas = obtener_todas_las_herramientas(mcp_mgr)

    while True:
        with console.status("[bold green]●[/bold green] [dim cyan]gordito::neural_inference...[/dim cyan]", spinner="dots"):
            respuesta = await cliente_ollama.chat(
                model=modelo,
                messages=mensajes,
                tools=todas_las_herramientas,
            )

        mensaje_modelo = respuesta.message
        mensajes.append(mensaje_modelo)

        # Preservar bloque de razonamiento (thinking) si viene separado
        content = mensaje_modelo.content or ""
        th = getattr(mensaje_modelo, "thinking", None)
        if th and "<thought>" not in content and "<think>" not in content:
            content = f"<thought>\n{th.strip()}\n</thought>\n\n{content}"

        # Si no hay llamadas a herramientas, terminamos
        if not mensaje_modelo.tool_calls:
            return content

        # Ejecutar herramientas de forma compacta (una línea limpia por acción)
        for tool_call in mensaje_modelo.tool_calls:
            nombre = tool_call.function.name
            args = tool_call.function.arguments or {}
            descripcion = describir_accion_herramienta(nombre, args)

            # Indicador compacto hacker
            console.print(f"  [bold green]⚡[/bold green] {descripcion}", end="")

            if nombre in LOCAL_TOOL_FUNCTIONS:
                fn = LOCAL_TOOL_FUNCTIONS[nombre]
                try:
                    resultado = fn(**args)
                    console.print(" [green]✓[/green]")
                except Exception as err:
                    resultado = f"Error: {err}"
                    console.print(" [red]✗[/red]")

            elif nombre in mcp_mgr.mcp_tools:
                try:
                    resultado = await mcp_mgr.ejecutar_herramienta(nombre, args)
                    console.print(" [green]✓[/green]")
                except Exception as err:
                    resultado = f"Error: {err}"
                    console.print(" [red]✗[/red]")

            else:
                resultado = f"Herramienta '{nombre}' no encontrada."
                console.print(" [red]✗[/red]")

            mensajes.append({
                "role": "tool",
                "content": str(resultado)
            })


def comando_spotify_clean():
    estado = spotify_estado()
    console.print(f"\n  [bold #1DB954] Spotify:[/bold #1DB954] [dim]{estado}[/dim]\n")


def comando_help_clean():
    tabla = Table(box=None, padding=(0, 2), show_header=False)
    for cmd, desc in SLASH_COMMANDS.items():
        if cmd not in ["/salir"]:
            tabla.add_row(f"[bold yellow]{cmd}[/bold yellow]", f"[dim]{desc}[/dim]")
    console.print("\n[bold cyan]Comandos rápidos:[/bold cyan]")
    console.print(tabla)
    console.print()


def comando_tools_clean(mcp_mgr: MCPManager, filtro: str = ""):
    mostrar_tabla_herramientas(mcp_mgr, console, filtro=filtro)


async def main_async():
    cliente_ollama = AsyncClient()
    mcp_mgr = MCPManager(CONFIG_MCP_PATH)
    await mcp_mgr.conectar_servidores()

    try:
        modelos = obtener_modelos_instalados()
        if not modelos:
            nombres = ["gemma4:e4b", "llama3.1:latest"]
        else:
            nombres = [m.model for m in modelos]

        modelo_actual = "gemma4:e4b" if "gemma4:e4b" in nombres else ("llama3.1:latest" if "llama3.1:latest" in nombres else nombres[0])

        # Mostrar la mascota Tux y la tarjeta de bienvenida
        imprimir_banner_gordito(modelo_actual, total_mcp=len(mcp_mgr.mcp_tools), subtitulo="Interfaz Minimalista")

        mensajes = [{"role": "system", "content": SYSTEM_PROMPT_GORDITO}]

        completer = MinimalCompleter(lambda: [m.model for m in obtener_modelos_instalados()] or ["gemma4:e4b", "llama3.1:latest"])
        session = PromptSession(
            completer=completer,
            complete_while_typing=True,
            style=MINIMAL_STYLE,
            history=InMemoryHistory()
        )
        while True:
            dir_nombre = os.path.basename(os.getcwd()) or "/"
            prompt_html = HTML(f"<b><ansigreen>gordito</ansigreen></b><ansidarkgray>:</ansidarkgray><ansidarkgray>{dir_nombre}</ansidarkgray> <ansigreen>❯</ansigreen> ")

            try:
                entrada = await session.prompt_async(prompt_html)
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]¡Hasta luego![/dim]\n")
                break

            texto = entrada.strip()
            if not texto:
                continue

            # Comandos Slash
            if texto.startswith("/"):
                partes = texto.split(maxsplit=1)
                cmd = partes[0].lower()
                arg = partes[1].strip() if len(partes) > 1 else ""

                if cmd in ["/exit", "/salir", "/quit"]:
                    console.print("\n[dim]¡Hasta luego, Iñaki![/dim]\n")
                    break
                elif cmd == "/flow":
                    ejecutar_modo_flow(arg or "flow", console)
                    continue
                elif cmd == "/mision":
                    objetivo = arg
                    if not objetivo:
                        try:
                            objetivo = await session.prompt_async(HTML("<b><ansigreen>🎯 ¿Cuál es la misión para Gordito?</ansigreen> ❯ "))
                        except (KeyboardInterrupt, EOFError):
                            continue
                    objetivo = objetivo.strip()
                    if objetivo:
                        await ejecutar_mision_autonoma(
                            objetivo=objetivo,
                            cliente_ollama=cliente_ollama,
                            modelo=modelo_actual,
                            mcp_mgr=mcp_mgr,
                            console=console
                        )
                    continue
                elif cmd in ["/help", "/ayuda"]:
                    comando_help_clean()
                    continue
                elif cmd == "/spotify":
                    comando_spotify_clean()
                    continue
                elif cmd == "/tools":
                    comando_tools_clean(mcp_mgr, filtro=arg)
                    continue
                elif cmd == "/clear":
                    console.clear()
                    mensajes = [{"role": "system", "content": SYSTEM_PROMPT_GORDITO}]
                    console.print("[dim]Memoria reiniciada y pantalla limpia.[/dim]\n")
                    continue
                elif cmd == "/models":
                    console.print("\n[bold cyan]Modelos disponibles en Ollama:[/bold cyan]")
                    for m in nombres:
                        marca = " [green]← activo[/green]" if m == modelo_actual else ""
                        console.print(f"  • {m}{marca}")
                    sel = await session.prompt_async(HTML(f"<b>Cambiar a ({modelo_actual}): </b>"), default=modelo_actual)
                    if sel.strip() in nombres:
                        modelo_actual = sel.strip()
                        console.print(f"[green]Activo: {modelo_actual}[/green]\n")
                    continue
                elif cmd == "/model":
                    if arg in nombres:
                        modelo_actual = arg
                        console.print(f"[green]Activo: {modelo_actual}[/green]\n")
                    else:
                        console.print(f"[red]Modelo '{arg}' no encontrado.[/red]\n")
                    continue
                else:
                    console.print(f"[dim red]Comando no reconocido. Escribe /help[/dim red]\n")
                    continue

            # Consulta normal
            mensajes.append({"role": "user", "content": texto})

            respuesta_final = await ejecutar_turno_minimal(
                cliente_ollama=cliente_ollama,
                modelo=modelo_actual,
                mensajes=mensajes,
                mcp_mgr=mcp_mgr
            )

            # Renderizado con streaming en tiempo real (token a token)
            await renderizar_streaming_panel(respuesta_final, console, modelo=modelo_actual)

    finally:
        await mcp_mgr.cerrar()


def main():
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
