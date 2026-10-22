#!/usr/bin/env python3
"""
Gordito (gprdito) - Interfaz Minimalista y Limpia
Un asistente de terminal elegante, rápido y sin ruido visual.
"""

import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV = os.path.join(_DIR, "venv/bin/python3")
if not os.path.exists(_VENV):
    _VENV = os.path.join(_DIR, ".venv/bin/python3")
if not os.path.exists(_VENV):
    _VENV = os.path.expanduser("~/Documents/agente/.venv/bin/python3")

if sys.prefix == sys.base_prefix and os.path.exists(_VENV):
    os.execv(_VENV, [_VENV] + sys.argv)
import asyncio
import json

from core import (
    CONFIG_MCP_PATH,
    LOCAL_TOOL_FUNCTIONS,
    INEGI_TOOLS,
    area_mencionada,
    giro_mencionado,
    responder_capacidades_mcp,
    componer_respuesta_inegi,
    RESPUESTA_CREADOR,
    MCPManager,
    alternar_herramienta,
    ejecutar_mision_autonoma,
    ejecutar_modo_flow,
    enrutar_herramientas_para_consulta,
    es_pregunta_creador,
    es_saludo_o_charla,
    extraer_tool_calls_fallback,
    guardar_config_tools,
    generar_prompt_sintesis,
    herramienta_esta_habilitada,
    imprimir_banner_gordito,
    inferir_llamada_banxico_fallback,
    inferir_llamada_inegi_fallback,
    inferir_llamada_busqueda_fallback,
    SyntheticToolCall,
    modelo_soporta_tools,
    mostrar_tabla_herramientas,
    normalizar_nombre_herramienta,
    obtener_modelos_instalados,
    obtener_nombre_os,
    obtener_system_prompt_gordito,
    renderizar_streaming_panel,
    spotify_estado,
)
from ollama import AsyncClient
from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table

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
    "/config": "Activar o desactivar tools y módulos (ej: /config off playwright, /config on spotify)",
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
        if text.startswith("/config "):
            sub_prefix = text[8:].lower()
            sugerencias_config = [
                ("off playwright", "Desactivar navegador Playwright MCP"),
                ("on playwright", "Activar navegador Playwright MCP"),
                ("off banxico", "Desactivar consultas económicas Banxico MCP"),
                ("on banxico", "Activar consultas económicas Banxico MCP"),
                ("off inegi", "Desactivar INEGI MCP (indicadores y DENUE)"),
                ("on inegi", "Activar INEGI MCP (indicadores y DENUE)"),
                ("off spotify", "Desactivar controles de Spotify"),
                ("on spotify", "Activar controles de Spotify"),
                ("off buscar_en_internet", "Desactivar búsqueda DuckDuckGo"),
                ("on buscar_en_internet", "Activar búsqueda DuckDuckGo"),
                ("list", "Ver estado ON/OFF de todas las herramientas"),
                ("reset", "Reactivar todas las herramientas"),
            ]
            for opcion, meta in sugerencias_config:
                if opcion.lower().startswith(sub_prefix):
                    yield Completion(
                        opcion,
                        start_position=-len(sub_prefix),
                        display=f"⚙️  {opcion}",
                        display_meta=meta
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
        q = args.get("consulta") or args.get("query") or args.get("q") or args.get("busqueda") or args.get("search") or args.get("text") or ""
        return f"[bold cyan][NET_WEB][/bold cyan] Query: [italic green]'{q}'[/italic green]"
    elif nombre == "leer_pagina_web":
        u = args.get("url") or args.get("link") or args.get("uri") or args.get("target") or args.get("href") or ""
        return f"[bold cyan][NET_REQ][/bold cyan] Fetch URL: [italic]{u}[/italic]"
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
    elif nombre in INEGI_TOOLS:
        return f"[bold cyan][MCP_RPC][/bold cyan] INEGI: [italic]{nombre}[/italic]"
    elif any(k in nombre for k in ["tipo_cambio", "banxico", "inflacion", "udis", "tasa", "reserva", "sie"]):
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
    mcp_mgr: MCPManager,
    max_pasos: int = 8
) -> str:
    """Ejecuta el ciclo de herramientas de forma discreta y minimalista con límite de seguridad."""
    # Si el último mensaje del usuario es solo un saludo o charla informal,
    # no le enviamos el parámetro tools a Ollama para evitar que el modelo
    # intente invocar herramientas sin sentido (ej: browser_navigate a example.com).
    ultimo_mensaje_user = ""
    for m in reversed(mensajes):
        if m.get("role") == "user":
            ultimo_mensaje_user = m.get("content", "")
            break

    capacidades = responder_capacidades_mcp(ultimo_mensaje_user, mcp_mgr)
    if capacidades:
        mensajes.append({"role": "assistant", "content": capacidades})
        return capacidades

    es_charla = es_saludo_o_charla(ultimo_mensaje_user)
    herramientas_disponibles = [] if es_charla else enrutar_herramientas_para_consulta(ultimo_mensaje_user, mcp_mgr)

    paso = 0

    while paso < max_pasos:
        paso += 1
        with console.status("[bold green]●[/bold green] [dim cyan]gordito::neural_inference...[/dim cyan]", spinner="dots"):
            chat_kwargs = {
                "model": modelo,
                "messages": mensajes,
            }
            if herramientas_disponibles:
                chat_kwargs["tools"] = herramientas_disponibles

            respuesta = await cliente_ollama.chat(**chat_kwargs)

        mensaje_modelo = respuesta.message
        mensajes.append(mensaje_modelo)

        # Preservar bloque de razonamiento (thinking) si viene separado
        content = mensaje_modelo.content or ""
        th = getattr(mensaje_modelo, "thinking", None)
        if th and "<thought>" not in content and "<think>" not in content:
            content = f"<thought>\n{th.strip()}\n</thought>\n\n{content}"

        tool_calls = list(mensaje_modelo.tool_calls) if mensaje_modelo.tool_calls else []
        if not tool_calls:
            valid_names = set(LOCAL_TOOL_FUNCTIONS.keys()) | set(mcp_mgr.mcp_tools.keys())
            fallback_calls = extraer_tool_calls_fallback(content, valid_names)
            if fallback_calls:
                tool_calls = fallback_calls
                mensaje_modelo.tool_calls = [
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in fallback_calls
                ]

        # Comparaciones entre lugares: el modelo chico suele pedir un solo dato (nacional) en vez
        # de comparar_areas; si la pregunta es claramente una comparación, se corrige la llamada.
        if tool_calls and paso == 1 and "comparar_areas" in mcp_mgr.mcp_tools:
            fn_inf, args_inf = inferir_llamada_inegi_fallback(ultimo_mensaje_user)
            nombres_llamadas = {normalizar_nombre_herramienta(tc.function.name) for tc in tool_calls}
            if fn_inf == "comparar_areas" and nombres_llamadas <= {"consultar_indicador"}:
                tool_calls = [SyntheticToolCall(fn_inf, args_inf)]
                mensaje_modelo.tool_calls = [{"function": {"name": fn_inf, "arguments": args_inf}}]

        # Inferencia determinista de respaldo si el modelo no emitió tool_calls pero la consulta es claramente una orden directa
        if not tool_calls and paso == 1:
            fn_name, fn_args = inferir_llamada_inegi_fallback(ultimo_mensaje_user)
            if not fn_name or fn_name not in mcp_mgr.mcp_tools:
                fn_name, fn_args = inferir_llamada_banxico_fallback(ultimo_mensaje_user)
            if not fn_name:
                fn_name, fn_args = inferir_llamada_busqueda_fallback(ultimo_mensaje_user)

            if fn_name and (fn_name in mcp_mgr.mcp_tools or fn_name in LOCAL_TOOL_FUNCTIONS):
                if herramienta_esta_habilitada(fn_name):
                    tool_calls = [SyntheticToolCall(fn_name, fn_args)]
                    mensaje_modelo.tool_calls = [
                        {"function": {"name": fn_name, "arguments": fn_args}}
                    ]

        # Si no hay llamadas a herramientas, terminamos
        if not tool_calls:
            # Sanitización de alucinaciones de modelos (ej: { "name": "DialoGPT", "arguments": {} })
            content_clean = content.strip()
            if content_clean.startswith("{") and ("DialoGPT" in content_clean or '"name":' in content_clean):
                try:
                    data = json.loads(content_clean)
                    if isinstance(data, dict) and "name" in data:
                        tname = data.get("name", "")
                        if tname not in LOCAL_TOOL_FUNCTIONS and tname not in mcp_mgr.mcp_tools:
                            if es_pregunta_creador(ultimo_mensaje_user):
                                content = RESPUESTA_CREADOR
                            else:
                                content = "¡Hola Iñaki! Soy Gordito, tu asistente en Arch Linux. ¿En qué te puedo colaborar?"
                except Exception:
                    pass
            return content

        # Limpiar el texto previo del asistente para que no se repita en el siguiente paso
        mensaje_modelo.content = ""

        # Ejecutar herramientas de forma compacta (una línea limpia por acción)
        herramientas_ejecutadas: list[str] = []
        resultados_ejecutados: list[str] = []
        for tool_call in tool_calls:
            nombre = normalizar_nombre_herramienta(tool_call.function.name)
            herramientas_ejecutadas.append(nombre)
            args = tool_call.function.arguments or {}
            # Los modelos chicos a veces omiten el lugar ("habitantes de Jalisco" -> dato nacional).
            if nombre in ("consultar_indicador", "contar_negocios", "buscar_negocios") and not args.get("area"):
                area = area_mencionada(ultimo_mensaje_user)
                if area:
                    args = {**dict(args), "area": area}
            if nombre == "buscar_negocios" and not (args.get("que") or args.get("actividad")):
                giro = giro_mencionado(ultimo_mensaje_user)
                if giro:
                    args = {**dict(args), "actividad": giro}
            descripcion = describir_accion_herramienta(nombre, args)

            # Indicador compacto hacker
            console.print(f"  [bold green]⚡[/bold green] {descripcion}", end="")

            # Verificar si la herramienta fue deshabilitada por configuración
            if not herramienta_esta_habilitada(nombre):
                console.print(" [yellow]⚠ (DESACTIVADA)[/yellow]")
                resultado = f"Aviso: La herramienta '{nombre}' está actualmente desactivada por el usuario en /config. No se ejecutará."
            elif nombre in LOCAL_TOOL_FUNCTIONS:
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
            resultados_ejecutados.append(str(resultado))

        # INEGI: la respuesta sale tal cual del "resumen" del servidor, sin que el modelo la
        # reescriba (evita cifras, fuentes y negocios inventados).
        if herramientas_ejecutadas and all(h in INEGI_TOOLS for h in herramientas_ejecutadas):
            directa = componer_respuesta_inegi(resultados_ejecutados)
            if directa:
                mensajes.append({"role": "assistant", "content": directa})
                return directa

        # Síntesis final de la respuesta tras ejecutar herramientas
        prompt_sintesis = generar_prompt_sintesis(ultimo_mensaje_user, herramientas_ejecutadas)
        mensajes_sintesis = list(mensajes) + [{
            "role": "user",
            "content": prompt_sintesis
        }]
        with console.status("[bold green]●[/bold green] [dim cyan]gordito::synthesizing...[/dim cyan]", spinner="dots"):
            resp_sintesis = await cliente_ollama.chat(
                model=modelo,
                messages=mensajes_sintesis,
            )
        mensajes.append(resp_sintesis.message)
        return resp_sintesis.message.content or "Operación completada."

    return "Operación completada."


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


async def menu_config_interactivo(mcp_mgr: MCPManager, console: Console):
    """Muestra un menú interactivo TUI navegable con teclado para activar/desactivar tools."""
    items = [
        {"id": "playwright", "titulo": "🎭 Playwright MCP (Navegador Web)", "desc": "Automatización y navegación web completa (browser_*)", "tipo": "modulo"},
        {"id": "banxico", "titulo": "🏛️ Banxico MCP (Datos Oficiales México)", "desc": "Tipo de cambio FIX, inflación INPC, UDIS, TIIE, reservas", "tipo": "modulo"},
        {"id": "inegi", "titulo": "📊 INEGI MCP (Indicadores y DENUE)", "desc": "Población, inflación, empleo, PIB, IGAE y directorio de negocios", "tipo": "modulo"},
        {"id": "spotify", "titulo": "🎧 Spotify & DJ de Código", "desc": "Control de música, DJ inteligente y favoritos", "tipo": "modulo"},
        {"id": "buscar_en_internet", "titulo": "🌐 DuckDuckGo (Búsqueda Web)", "desc": "Búsqueda en tiempo real en la web", "tipo": "tool"},
        {"id": "leer_pagina_web", "titulo": "📄 Lector de Páginas Web", "desc": "Descarga y lectura del texto de páginas web", "tipo": "tool"},
        {"id": "ejecutar_comando", "titulo": "💻 Ejecutar Comandos Terminal", "desc": "Ejecución de comandos bash en Arch Linux", "tipo": "tool"},
        {"id": "listar_archivos", "titulo": "📁 Listar Archivos y Carpetas", "desc": "Exploración del sistema de archivos local", "tipo": "tool"},
        {"id": "leer_archivo", "titulo": "📖 Leer Archivos Locales", "desc": "Lectura de archivos y scripts del sistema", "tipo": "tool"},
        {"id": "escribir_archivo", "titulo": "✍️ Escribir Archivos Locales", "desc": "Creación y edición de archivos locales", "tipo": "tool"},
        {"id": "cambiar_directorio", "titulo": "📂 Cambiar Directorio (cd)", "desc": "Navegar entre carpetas de trabajo", "tipo": "tool"},
        {"id": "info_sistema", "titulo": "ℹ️ Info del Sistema", "desc": "Consultar reloj, fecha y SO anfitrión", "tipo": "tool"},
    ]

    # Servidores MCP adicionales detectados que no estén en la lista previa
    conocidos_ids = {it["id"] for it in items}
    for srv_name, srv_info in mcp_mgr.servers_info.items():
        if srv_name not in conocidos_ids and srv_name not in ["playwright", "banxico", "inegi"]:
            items.append({
                "id": srv_name,
                "titulo": f"🔌 {srv_name.capitalize()} MCP",
                "desc": srv_info.get("descripcion", "Servidor MCP"),
                "tipo": "modulo"
            })

    # Acciones finales (DONE y Cancelar)
    items.append({
        "id": "__DONE__",
        "titulo": "💾 [DONE] Guardar y Salir",
        "desc": "Guarda los cambios en tools_config.json y regresa al chat",
        "tipo": "action"
    })
    items.append({
        "id": "__CANCEL__",
        "titulo": "❌ Cancelar",
        "desc": "Descartar cambios y salir sin modificar nada",
        "tipo": "action"
    })

    # Cargar estado actual
    states = {it["id"]: herramienta_esta_habilitada(it["id"]) for it in items if it["tipo"] != "action"}
    selected = 0
    visible_count = 7

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _arriba(event):
        nonlocal selected
        selected = max(0, selected - 1)

    @kb.add("down")
    @kb.add("j")
    def _abajo(event):
        nonlocal selected
        selected = min(len(items) - 1, selected + 1)

    @kb.add("space")
    @kb.add("enter")
    def _accion(event):
        nonlocal selected
        it = items[selected]
        if it["id"] == "__DONE__":
            event.app.exit(result=states)
        elif it["id"] == "__CANCEL__":
            event.app.exit(result=None)
        else:
            states[it["id"]] = not states.get(it["id"], True)

    @kb.add("q")
    @kb.add("escape")
    @kb.add("c-c")
    def _salir(event):
        event.app.exit(result=None)

    def get_formatted_text():
        lines = []
        lines.append(('bold #bd93f9', '╭─ ⚙️  GORDITO · Configuración de Herramientas y Módulos ──────────────────────╮\n'))
        lines.append(('dim cyan', '│ Usa [↑/↓] Navegar  •  [Espacio/Enter] Activar/Desactivar  •  Baja a [DONE]   │\n'))
        lines.append(('bold #bd93f9', '╰─────────────────────────────────────────────────────────────────────────────╯\n'))

        total = len(items)
        if total <= visible_count:
            start_idx, end_idx = 0, total
        else:
            start_idx = max(0, min(selected - visible_count // 2, total - visible_count))
            end_idx = start_idx + visible_count

        if start_idx > 0:
            lines.append(('dim #6272a4', f'    ▲ ... {start_idx} opciones más arriba (sube con ↑) ...\n'))
        else:
            lines.append(('', '\n'))

        for idx in range(start_idx, end_idx):
            it = items[idx]
            is_sel = (idx == selected)
            prefix = ' ❯ ' if is_sel else '   '
            titulo = it["titulo"]
            desc = it["desc"]

            if it['tipo'] == 'action':
                if it['id'] == '__DONE__':
                    lines.append(('', '  ' + '─'*65 + '\n'))
                style = 'bold #50fa7b reverse' if is_sel else ('bold #50fa7b' if it['id'] == '__DONE__' else 'dim')
                lines.append(('', prefix))
                lines.append((style, f'{titulo}\n'))
                lines.append(('dim', f'       {desc}\n'))
            else:
                act = states.get(it['id'], True)
                badge = '[✓ ON ] ' if act else '[  OFF] '
                b_style = 'bold #50fa7b' if act else 'bold #ff5555'
                t_style = 'bold #f8f8f2' if is_sel else ('#f8f8f2' if act else 'dim strike #6272a4')
                p_style = 'bold #50fa7b' if is_sel else ''
                lines.append((p_style, prefix))
                lines.append((b_style, badge))
                lines.append((t_style, f'{titulo}\n'))
                lines.append(('dim', f'          {desc}\n'))

        if end_idx < total:
            lines.append(('dim #6272a4', f'    ▼ ... {total - end_idx} opciones más abajo (baja con ↓) ...\n'))
        else:
            lines.append(('', '\n'))

        lines.append(('dim', ' Presiona [Enter] en [DONE] para guardar  •  [q] para cancelar\n'))
        return FormattedText(lines)

    control = FormattedTextControl(get_formatted_text)
    window = Window(content=control, wrap_lines=True)
    app = Application(layout=Layout(HSplit([window])), key_bindings=kb, full_screen=False)

    resultado = await app.run_async()

    if resultado is not None:
        nuevas_deshabilitadas = [
            it["id"] for it in items 
            if it["tipo"] != "action" and not resultado.get(it["id"], True)
        ]
        guardar_config_tools({"disabled_tools": nuevas_deshabilitadas})

        # Sincronizar servidores MCP en tiempo real
        if "playwright" in nuevas_deshabilitadas and "playwright" in mcp_mgr.sessions:
            await mcp_mgr.desconectar_servidor("playwright")
        elif "playwright" not in nuevas_deshabilitadas and "playwright" not in mcp_mgr.sessions:
            await mcp_mgr.conectar_servidor("playwright")

        for modulo in MODULOS_MCP_DATOS:
            if modulo in nuevas_deshabilitadas and modulo in mcp_mgr.sessions:
                await mcp_mgr.desconectar_servidor(modulo)
            elif modulo not in nuevas_deshabilitadas and modulo not in mcp_mgr.sessions:
                await mcp_mgr.conectar_servidor(modulo)

        console.print("\n[bold green]✓ Configuración actualizada y guardada exitosamente en tools_config.json[/bold green]")
        if nuevas_deshabilitadas:
            console.print(f"[dim]Desactivadas (OFF):[/dim] [bold red]{', '.join(nuevas_deshabilitadas)}[/bold red]\n")
        else:
            console.print("[dim]Todas las herramientas y módulos están [bold green]ACTIVADOS (ON)[/bold green].[/dim]\n")
    else:
        console.print("\n[dim]Configuración sin cambios.[/dim]\n")


# Servidores MCP de datos de México (Itzamná) que se prenden y apagan con /config.
MODULOS_MCP_DATOS = ("banxico", "inegi")
_ALIAS_MODULOS = {"banxico": "banxico", "inegi": "inegi", "denue": "inegi"}


def _modulo_datos(nombre: str) -> str | None:
    return _ALIAS_MODULOS.get(nombre.strip().lower())


async def comando_config_clean(mcp_mgr: MCPManager, arg: str = ""):
    """Gestiona la activación o desactivación de herramientas y módulos."""
    arg_clean = arg.strip()
    if not arg_clean or arg_clean.lower() in ["menu", "interactivo", "ui"]:
        await menu_config_interactivo(mcp_mgr, console)
        return

    partes = arg_clean.split(maxsplit=1)
    sub = partes[0].lower()
    resto = partes[1].strip() if len(partes) > 1 else ""

    if sub in ["list", "tabla", "ver"]:
        mostrar_tabla_herramientas(mcp_mgr, console, filtro=resto)
    elif sub in ["reset", "activar_todo", "on_all"]:
        guardar_config_tools({"disabled_tools": []})
        console.print("\n[bold green]✓ Todas las herramientas han sido reactivadas exitosamente.[/bold green]\n")
    elif sub in ["off", "disable", "apagar", "desactivar"]:
        if not resto:
            console.print("[red]Especifica la herramienta o módulo a desactivar (ej: /config off playwright).[/red]\n")
            return
        _, msg = alternar_herramienta(resto, activar=False)
        if resto.lower() in ["playwright", "browser"] and "playwright" in mcp_mgr.sessions:
            await mcp_mgr.desconectar_servidor("playwright")
        elif _modulo_datos(resto) in mcp_mgr.sessions:
            await mcp_mgr.desconectar_servidor(_modulo_datos(resto))
        console.print(f"\n  {msg}\n")
    elif sub in ["on", "enable", "prender", "activar"]:
        if not resto:
            console.print("[red]Especifica la herramienta o módulo a activar (ej: /config on playwright).[/red]\n")
            return
        _, msg = alternar_herramienta(resto, activar=True)
        if resto.lower() in ["playwright", "browser"] and "playwright" not in mcp_mgr.sessions:
            await mcp_mgr.conectar_servidor("playwright")
        elif _modulo_datos(resto) and _modulo_datos(resto) not in mcp_mgr.sessions:
            await mcp_mgr.conectar_servidor(_modulo_datos(resto))
        console.print(f"\n  {msg}\n")
    elif sub in ["toggle", "switch"]:
        if not resto:
            console.print("[red]Especifica la herramienta o módulo (ej: /config toggle playwright).[/red]\n")
            return
        nuevo_st, msg = alternar_herramienta(resto, activar=None)
        if resto.lower() in ["playwright", "browser"]:
            if not nuevo_st and "playwright" in mcp_mgr.sessions:
                await mcp_mgr.desconectar_servidor("playwright")
            elif nuevo_st and "playwright" not in mcp_mgr.sessions:
                await mcp_mgr.conectar_servidor("playwright")
        elif _modulo_datos(resto):
            modulo = _modulo_datos(resto)
            if not nuevo_st and modulo in mcp_mgr.sessions:
                await mcp_mgr.desconectar_servidor(modulo)
            elif nuevo_st and modulo not in mcp_mgr.sessions:
                await mcp_mgr.conectar_servidor(modulo)
        console.print(f"\n  {msg}\n")
    else:
        # Por defecto, alternar lo que el usuario escribió si no especificó on/off
        nuevo_st, msg = alternar_herramienta(arg_clean, activar=None)
        if arg_clean.lower() in ["playwright", "browser"]:
            if not nuevo_st and "playwright" in mcp_mgr.sessions:
                await mcp_mgr.desconectar_servidor("playwright")
            elif nuevo_st and "playwright" not in mcp_mgr.sessions:
                await mcp_mgr.conectar_servidor("playwright")
        elif _modulo_datos(arg_clean):
            modulo = _modulo_datos(arg_clean)
            if not nuevo_st and modulo in mcp_mgr.sessions:
                await mcp_mgr.desconectar_servidor(modulo)
            elif nuevo_st and modulo not in mcp_mgr.sessions:
                await mcp_mgr.conectar_servidor(modulo)
        console.print(f"\n  {msg}\n")


async def main_async():
    cliente_ollama = AsyncClient()
    mcp_mgr = MCPManager(CONFIG_MCP_PATH)
    await mcp_mgr.conectar_servidores()

    try:
        modelos = obtener_modelos_instalados(solo_con_tools=True)
        if not modelos:
            console.print("[bold red]⚠ Advertencia:[/bold red] No se detectaron modelos con soporte de herramientas (tools) en Ollama.")
            console.print("[dim]Puedes descargar uno compatible con: ollama pull qwen2.5-coder:7b[/dim]\n")
            todos = obtener_modelos_instalados(solo_con_tools=False)
            nombres = [m.model for m in todos] if todos else ["qwen2.5-coder:7b"]
        else:
            nombres = [m.model for m in modelos]

        modelo_actual = "qwen2.5-coder:7b" if "qwen2.5-coder:7b" in nombres else (nombres[0] if nombres else "qwen2.5-coder:7b")

        # Mostrar la mascota Tux y la tarjeta de bienvenida
        imprimir_banner_gordito(
            modelo_actual,
            total_mcp=len(mcp_mgr.mcp_tools),
            subtitulo="Interfaz Minimalista",
            servidores_activos=list(mcp_mgr.sessions.keys())
        )

        mensajes = [{"role": "system", "content": obtener_system_prompt_gordito()}]

        completer = MinimalCompleter(lambda: [m.model for m in obtener_modelos_instalados(solo_con_tools=True)])
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
                elif cmd == "/config":
                    await comando_config_clean(mcp_mgr, arg=arg)
                    continue
                elif cmd == "/clear":
                    console.clear()
                    mensajes = [{"role": "system", "content": obtener_system_prompt_gordito()}]
                    console.print("[dim]Memoria reiniciada y pantalla limpia.[/dim]\n")
                    continue
                elif cmd == "/models":
                    modelos_validos = [m.model for m in obtener_modelos_instalados(solo_con_tools=True)]
                    if not modelos_validos:
                        console.print("\n[red]No se encontraron modelos con soporte de herramientas en Ollama.[/red]\n")
                        continue
                    console.print("\n[bold cyan]Modelos con soporte de herramientas (tools):[/bold cyan]")
                    for m in modelos_validos:
                        marca = " [green]← activo[/green]" if m == modelo_actual else ""
                        console.print(f"  • {m}{marca}")
                    sel = await session.prompt_async(HTML(f"<b>Cambiar a ({modelo_actual}): </b>"), default=modelo_actual)
                    sel_clean = sel.strip()
                    if sel_clean in modelos_validos:
                        modelo_actual = sel_clean
                        console.print(f"[green]Activo: {modelo_actual}[/green]\n")
                    elif sel_clean and sel_clean != modelo_actual:
                        console.print(f"[red]Error:[/red] '{sel_clean}' no soporta herramientas o no existe.\n")
                    continue
                elif cmd == "/model":
                    modelos_validos = [m.model for m in obtener_modelos_instalados(solo_con_tools=True)]
                    if not arg:
                        console.print(f"\n[bold cyan]Modelo actual:[/bold cyan] [green]{modelo_actual}[/green]")
                        console.print("[bold cyan]Modelos disponibles con soporte de herramientas (tools):[/bold cyan]")
                        for m in modelos_validos:
                            marca = " [green]← activo[/green]" if m == modelo_actual else ""
                            console.print(f"  • {m}{marca}")
                        console.print("[dim]Uso: /model <nombre_modelo>[/dim]\n")
                    elif arg in modelos_validos:
                        modelo_actual = arg
                        console.print(f"[green]Activo: {modelo_actual}[/green]\n")
                    else:
                        if modelo_soporta_tools(arg):
                            modelo_actual = arg
                            console.print(f"[green]Activo: {modelo_actual}[/green]\n")
                        else:
                            console.print(f"[bold red]Error:[/bold red] El modelo '{arg}' no soporta herramientas (tools) en Ollama o no está instalado.")
                            console.print(f"[dim]Modelos compatibles disponibles: {', '.join(modelos_validos)}[/dim]\n")
                    continue
                else:
                    console.print("[dim red]Comando no reconocido. Escribe /help[/dim red]\n")
                    continue

            # Detección de pregunta sobre su creador / autor (Iñaki Sobera Sotomayor)
            if es_pregunta_creador(texto):
                resp_creador = RESPUESTA_CREADOR
                mensajes.append({"role": "user", "content": texto})
                mensajes.append({"role": "assistant", "content": resp_creador})
                await renderizar_streaming_panel(resp_creador, console, modelo=modelo_actual)
                continue

            # Detección inteligente de consultas sobre herramientas
            texto_norm = texto.lower().replace("?", "").replace("¿", "").strip()
            es_pregunta_tools = any(p in texto_norm for p in [
                "que tools", "que herramientas", "cuales tools", "cuales herramientas",
                "tus tools", "tus herramientas", "mis tools", "ver tools", "ver herramientas",
                "lista de tools", "lista de herramientas", "listar tools", "listar herramientas"
            ]) or ("tools" in texto_norm and any(w in texto_norm for w in ["conectad", "activ", "disponib", "tien", "toen"]))

            if es_pregunta_tools:
                comando_tools_clean(mcp_mgr)
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
