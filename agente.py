#!/usr/bin/env python3
"""
Agente 'Gordito' (gprdito)
Agente de IA local con acceso al Sistema, Internet en vivo, Control de Spotify y Protocolo MCP.
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
import csv
import json
import subprocess
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any

import httpx
from core import (
    LOCAL_TOOL_FUNCTIONS,
    ejecutar_mision_autonoma,
    ejecutar_modo_flow,
    enrutar_herramientas_para_consulta,
    extraer_tool_calls_fallback,
    imprimir_banner_gordito,
    inferir_llamada_banxico_fallback,
    inferir_llamada_busqueda_fallback,
    SyntheticToolCall,
    generar_prompt_sintesis,
    modelo_soporta_tools,
    mostrar_tabla_herramientas,
    normalizar_nombre_herramienta,
    obtener_modelos_instalados,
    obtener_nombre_os,
    obtener_system_prompt_gordito,
    renderizar_streaming_panel,
)
from ddgs import DDGS
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from ollama import AsyncClient
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

console = Console()

CONFIG_MCP_PATH = os.path.join(_DIR, "mcp_servers.json")
if not os.path.exists(CONFIG_MCP_PATH):
    CONFIG_MCP_PATH = os.path.expanduser("~/Documents/agente/mcp_servers.json")

SPOTIFY_CSV_PATH = os.path.expanduser("~/Documents/Mi-Spotify-/favoritos.csv")

# Cargar variables de entorno locales si existen
DOTENV_PATH = os.path.join(_DIR, ".env")
if not os.path.exists(DOTENV_PATH):
    DOTENV_PATH = os.path.expanduser("~/Documents/agente/.env")
if os.path.exists(DOTENV_PATH):
    try:
        with open(DOTENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()
    except Exception:
        pass

# ==========================================
# 1. Herramientas del Sistema y Archivos
# ==========================================

def cambiar_directorio(ruta: str) -> str:
    """Cambia el directorio de trabajo actual (cd). Por ejemplo '..' para ir a la carpeta superior o '~/Documentos'."""
    try:
        ruta_exp = os.path.expanduser(ruta)
        os.chdir(ruta_exp)
        return f"Directorio de trabajo cambiado exitosamente a: {os.getcwd()}"
    except Exception as e:
        return f"Error al cambiar de directorio: {e!s}"

def ejecutar_comando(comando: str) -> str:
    """Ejecuta un comando en la terminal bash/zsh y devuelve la salida estándar o errores."""
    cmd_strip = comando.strip()
    if cmd_strip == "cd" or cmd_strip.startswith("cd "):
        partes = cmd_strip.split(maxsplit=1)
        target = partes[1].strip() if len(partes) > 1 else "~"
        return cambiar_directorio(target)

    try:
        resultado = subprocess.run(
            comando,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getcwd()
        )
        salida = resultado.stdout.strip()
        errores = resultado.stderr.strip()
        partes = []
        if salida:
            partes.append(f"[STDOUT]\n{salida}")
        if errores:
            partes.append(f"[STDERR]\n{errores}")
        if not partes:
            return "Comando ejecutado exitosamente sin salida."
        return "\n".join(partes)
    except subprocess.TimeoutExpired:
        return "Error: El comando tardó demasiado y expiró (timeout de 30s)."
    except Exception as e:
        return f"Error ejecutando comando: {e!s}"

def listar_archivos(ruta: str = ".") -> str:
    """Lista los archivos y carpetas en una ruta específica. Por defecto '.' para la carpeta actual."""
    try:
        ruta_exp = os.path.expanduser(ruta)
        items = os.listdir(ruta_exp)
        if not items:
            return f"La carpeta '{ruta}' está vacía."
        info = []
        for item in sorted(items):
            full_path = os.path.join(ruta_exp, item)
            tipo = "📁 Carpeta" if os.path.isdir(full_path) else "📄 Archivo"
            info.append(f"{tipo}: {item}")
        return "\n".join(info)
    except Exception as e:
        return f"Error al listar archivos: {e!s}"

def leer_archivo(ruta: str) -> str:
    """Lee y devuelve el contenido de un archivo de texto."""
    try:
        ruta_exp = os.path.expanduser(ruta)
        with open(ruta_exp, "r", encoding="utf-8") as f:
            contenido = f.read()
        return contenido if contenido else "(Archivo vacío)"
    except Exception as e:
        return f"Error al leer archivo: {e!s}"

def escribir_archivo(ruta: str, contenido: str) -> str:
    """Crea o sobreescribe un archivo de texto con el contenido especificado."""
    try:
        ruta_exp = os.path.expanduser(ruta)
        os.makedirs(os.path.dirname(os.path.abspath(ruta_exp)), exist_ok=True)
        with open(ruta_exp, "w", encoding="utf-8") as f:
            f.write(contenido)
        return f"Archivo '{ruta}' guardado correctamente ({len(contenido)} caracteres)."
    except Exception as e:
        return f"Error al escribir archivo: {e!s}"

def info_sistema() -> str:
    """Devuelve la fecha/hora actual, usuario, sistema operativo y directorio de trabajo."""
    return (
        f"Fecha y Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Usuario: {os.environ.get('USER', 'desconocido')}\n"
        f"Directorio actual: {os.getcwd()}\n"
        f"Plataforma: {sys.platform}"
    )

# ==========================================
# 2. Herramientas de Internet (Búsqueda y Navegación)
# ==========================================

def buscar_en_internet(consulta: str = "", max_resultados: int = 5, **kwargs) -> str:
    """Busca en internet en tiempo real usando DuckDuckGo y devuelve títulos, fragmentos y enlaces."""
    q = consulta or kwargs.get("query") or kwargs.get("q") or kwargs.get("busqueda") or kwargs.get("search") or kwargs.get("text") or kwargs.get("prompt") or ""
    limite = kwargs.get("max_results") or kwargs.get("limit") or kwargs.get("num_results") or max_resultados
    try:
        limite = int(limite)
    except (ValueError, TypeError):
        limite = 5

    q = str(q).strip()
    if not q:
        return "Error: No se especificó término de búsqueda."

    try:
        with DDGS() as ddgs:
            resultados = list(ddgs.text(q, max_results=limite))
            if not resultados:
                return f"No se encontraron resultados en la web para: '{q}'."
            
            lineas = []
            for i, r in enumerate(resultados, 1):
                titulo = r.get("title", "Sin título")
                enlace = r.get("href", "")
                cuerpo = r.get("body", "")
                lineas.append(f"{i}. {titulo}\n   URL: {enlace}\n   Fragmento: {cuerpo}")
            return "\n\n".join(lineas)
    except Exception as e:
        return f"Error al buscar en internet: {e!s}"

def leer_pagina_web(url: str = "", **kwargs) -> str:
    """Descarga una página web y devuelve su contenido de texto limpio (sin etiquetas HTML)."""
    u = url or kwargs.get("link") or kwargs.get("uri") or kwargs.get("target") or kwargs.get("href") or kwargs.get("page_url") or ""
    u = str(u).strip()
    if not u:
        return "Error: No se especificó la URL de la página web a leer."
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            resp = client.get(u, headers=headers)
            resp.raise_for_status()
            
            # Limpieza básica de HTML
            import re
            texto = resp.text
            texto = re.sub(r"<script.*?</script>", "", texto, flags=re.DOTALL | re.IGNORECASE)
            texto = re.sub(r"<style.*?</style>", "", texto, flags=re.DOTALL | re.IGNORECASE)
            texto = re.sub(r"<[^>]+>", " ", texto)
            texto = re.sub(r"\s+", " ", texto).strip()
            
            if len(texto) > 3000:
                texto = texto[:3000] + "... [Contenido truncado]"
            return texto if texto else "No se pudo extraer texto de la página."
    except Exception as e:
        return f"Error al leer página web {url}: {e!s}"

# ==========================================
# 3. Herramientas de Spotify (macOS & Mi-Spotify-)
# ==========================================

def spotify_estado() -> str:
    """Consulta qué canción, artista y álbum se está reproduciendo actualmente en Spotify en tu Mac, y si está pausada o sonando."""
    script = """
    if application "Spotify" is running then
        tell application "Spotify"
            set currentArtist to artist of current track
            set currentSong to name of current track
            set currentAlbum to album of current track
            set playerState to player state as string
            set songDuration to duration of current track
            set songPosition to player position
            return "Estado: " & playerState & " | Canción: " & currentSong & " | Artista: " & currentArtist & " | Álbum: " & currentAlbum & " | Posición: " & songPosition & "s / " & (songDuration / 1000) & "s"
        end tell
    else
        return "Spotify no está abierto actualmente en tu Mac."
    end if
    """
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        salida = res.stdout.strip()
        return salida if salida else "No se obtuvo respuesta de Spotify."
    except Exception as e:
        return f"Error al consultar Spotify: {e!s}"

def spotify_control(accion: str) -> str:
    """Controla la reproducción de Spotify en tu Mac. Acciones válidas: 'play', 'pause', 'toggle', 'siguiente' (next), 'anterior' (prev), 'subir_volumen', 'bajar_volumen'."""
    cmd_map = {
        "play": 'tell application "Spotify" to play',
        "reproducir": 'tell application "Spotify" to play',
        "pause": 'tell application "Spotify" to pause',
        "pausar": 'tell application "Spotify" to pause',
        "toggle": 'tell application "Spotify" to playpause',
        "siguiente": 'tell application "Spotify" to next track',
        "next": 'tell application "Spotify" to next track',
        "anterior": 'tell application "Spotify" to previous track',
        "prev": 'tell application "Spotify" to previous track',
        "subir_volumen": 'tell application "Spotify" to set sound volume to ((sound volume) + 10)',
        "bajar_volumen": 'tell application "Spotify" to set sound volume to ((sound volume) - 10)',
    }
    
    script_body = cmd_map.get(accion.lower().strip())
    if not script_body:
        return f"Acción '{accion}' no reconocida. Opciones: play, pause, toggle, siguiente, anterior, subir_volumen, bajar_volumen."
    
    script = f"""
    if application "Spotify" is running then
        {script_body}
        return "Acción '{accion}' ejecutada exitosamente en Spotify."
    else
        tell application "Spotify" to activate
        {script_body}
        return "Spotify abierto y acción '{accion}' ejecutada."
    end if
    """
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        return res.stdout.strip() or f"Acción '{accion}' completada."
    except Exception as e:
        return f"Error al controlar Spotify: {e!s}"

def spotify_reproducir(nombre_o_uri: str) -> str:
    """Reproduce una canción, artista, álbum o enlace/URI específico en la aplicación Spotify de tu Mac."""
    target = nombre_o_uri.strip()
    # Si es URI de Spotify (ej: spotify:track:...)
    if target.startswith("spotify:"):
        script = f'tell application "Spotify" to play track "{target}"'
    else:
        # Abrir búsqueda o reproducción directa
        script = f'open "spotify:search:{target}"'
    
    try:
        if target.startswith("spotify:"):
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        else:
            subprocess.run(["open", f"spotify:search:{target}"], capture_output=True, text=True)
            # Intentar darle play
            subprocess.run(["osascript", "-e", 'tell application "Spotify" to play'], capture_output=True, text=True)
        return f"Reproduciendo '{target}' en Spotify."
    except Exception as e:
        return f"Error al reproducir en Spotify: {e!s}"

def spotify_mis_favoritos(filtro: str = "") -> str:
    """Consulta la lista de canciones favoritas sincronizadas en tu proyecto ~/Documents/Mi-Spotify-/favoritos.csv."""
    if not os.path.exists(SPOTIFY_CSV_PATH):
        return f"No se encontró el archivo de favoritos en {SPOTIFY_CSV_PATH}."
    
    try:
        canciones = []
        with open(SPOTIFY_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                nombre = row.get("nombre", "")
                artista = row.get("artista", "")
                album = row.get("album", "")
                if filtro:
                    termino = filtro.lower()
                    if termino in nombre.lower() or termino in artista.lower() or termino in album.lower():
                        canciones.append(f"• {nombre} - {artista} ({album})")
                else:
                    canciones.append(f"• {nombre} - {artista} ({album})")
        
        if not canciones:
            return f"No se encontraron canciones que coincidan con '{filtro}' en tus favoritos."
        
        total = len(canciones)
        muestra = canciones[:15]
        res = "\n".join(muestra)
        if total > 15:
            res += f"\n\n... y {total - 15} canciones más en tu biblioteca ({total} en total)."
        return res
    except Exception as e:
        return f"Error al leer favoritos.csv: {e!s}"

# Registro consolidado de funciones locales
LOCAL_TOOL_FUNCTIONS = {
    "cambiar_directorio": cambiar_directorio,
    "ejecutar_comando": ejecutar_comando,
    "listar_archivos": listar_archivos,
    "leer_archivo": leer_archivo,
    "escribir_archivo": escribir_archivo,
    "info_sistema": info_sistema,
    "buscar_en_internet": buscar_en_internet,
    "leer_pagina_web": leer_pagina_web,
    "spotify_estado": spotify_estado,
    "spotify_control": spotify_control,
    "spotify_reproducir": spotify_reproducir,
    "spotify_mis_favoritos": spotify_mis_favoritos,
}

# ==========================================
# 4. Gestor de Servidores MCP (Model Context Protocol)
# ==========================================

class MCPManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.exit_stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.mcp_tools: dict[str, tuple] = {}
        self.servers_info: dict[str, dict] = {}

    def cargar_configuracion(self) -> dict:
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f).get("mcpServers", {})
        except Exception as e:
            console.print(f"[red]Error al leer {self.config_path}: {e}[/red]")
            return {}

    async def conectar_servidores(self):
        servidores = self.cargar_configuracion()
        for nombre, cfg in servidores.items():
            if not cfg.get("enabled", True):
                continue

            command = cfg.get("command")
            args = cfg.get("args", [])
            env_vars = dict(os.environ)
            if "env" in cfg:
                env_vars.update(cfg["env"])

            server_params = StdioServerParameters(command=command, args=args, env=env_vars)

            try:
                read_stream, write_stream = await self.exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                session = await self.exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()

                self.sessions[nombre] = session
                tools_res = await session.list_tools()
                
                tool_names = []
                for t in tools_res.tools:
                    self.mcp_tools[t.name] = (nombre, t)
                    tool_names.append(t.name)

                self.servers_info[nombre] = {
                    "descripcion": cfg.get("description", "Servidor MCP"),
                    "herramientas": tool_names,
                    "estado": "Conectado"
                }
            except Exception as err:
                self.servers_info[nombre] = {
                    "descripcion": cfg.get("description", "Servidor MCP"),
                    "herramientas": [],
                    "estado": f"Error: {err}"
                }

    async def ejecutar_herramienta(self, tool_name: str, arguments: dict) -> str:
        if tool_name not in self.mcp_tools:
            return f"Error: Herramienta MCP '{tool_name}' no encontrada."

        server_name, _ = self.mcp_tools[tool_name]
        session = self.sessions.get(server_name)
        if not session:
            return f"Error: Servidor '{server_name}' desconectado."

        try:
            res = await session.call_tool(tool_name, arguments=arguments)
            salidas = []
            for content in res.content:
                if hasattr(content, "text"):
                    salidas.append(content.text)
                else:
                    salidas.append(str(content))
            return "\n".join(salidas) if salidas else "Herramienta ejecutada sin salida."
        except Exception as e:
            return f"Error en herramienta MCP {tool_name}: {e!s}"

    def obtener_esquemas_ollama(self) -> list[dict]:
        esquemas = []
        for name, (_, t) in self.mcp_tools.items():
            schema = t.input_schema if hasattr(t, "input_schema") else {"type": "object", "properties": {}}
            esquemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.description or f"Herramienta provista por MCP ({name})",
                    "parameters": schema
                }
            })
        return esquemas

    async def cerrar(self):
        await self.exit_stack.aclose()


# ==========================================
# 5. Autocompletado y Comandos Slash
# ==========================================

SLASH_COMMANDS = {
    "/flow": "Activar el DJ de código de Gordito (ej: /flow, /flow hacker, /flow chill, /flow rock)",
    "/mision": "Ejecutar una misión autónoma multi-paso (ej: /mision investiga el dólar y crea reporte)",
    "/spotify": "Ver canción sonando en Spotify o pausar/reproducir",
    "/mcp": "Ver servidores MCP conectados y sus herramientas",
    "/models": "Listar modelos de Ollama y cambiar de modelo",
    "/model": "Cambiar directamente de modelo (ej: /model llama3.1:latest)",
    "/tools": "Ver lista y documentación de herramientas disponibles",
    "/raw": "Activar o desactivar inspector JSON de Tool Calling",
    "/clear": "Limpiar memoria y reiniciar historial del chat",
    "/help": "Mostrar ayuda con todos los comandos slash",
    "/exit": "Salir del programa",
    "/salir": "Salir del programa",
}

class SlashCompleter(Completer):
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
                        display_meta="Modelo Ollama"
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

PROMPT_STYLE = Style.from_dict({
    "prompt": "bold #50fa7b",
    "completion-menu": "bg:#191a21 #f8f8f2",
    "completion-menu.completion": "bg:#191a21 #6272a4",
    "completion-menu.completion.current": "bg:#282a36 #50fa7b bold",
    "completion-menu.meta": "bg:#191a21 #44475a italic",
    "completion-menu.meta.current": "bg:#282a36 #50fa7b italic",
    "scrollbar.background": "bg:#191a21",
    "scrollbar.button": "bg:#44475a",
})




def comando_help():
    tabla = Table(title="⚡ Comandos Slash de Gordito", border_style="magenta")
    tabla.add_column("Comando", style="bold yellow")
    tabla.add_column("Descripción")
    for cmd, desc in SLASH_COMMANDS.items():
        if cmd not in ["/salir", "/reset"]:
            tabla.add_row(cmd, desc)
    console.print(tabla)


def comando_mcp(mcp_mgr: MCPManager):
    tabla = Table(title="🔌 Servidores MCP Conectados", border_style="cyan")
    tabla.add_column("Servidor", style="bold green")
    tabla.add_column("Estado", style="bold")
    tabla.add_column("Herramientas provistas", style="yellow")
    tabla.add_column("Descripción", style="dim")

    for nombre, info in mcp_mgr.servers_info.items():
        estado_color = "[green]✅ Conectado[/green]" if info["estado"] == "Conectado" else f"[red]{info['estado']}[/red]"
        herramientas_str = ", ".join(info["herramientas"]) if info["herramientas"] else "(Ninguna)"
        tabla.add_row(nombre, estado_color, herramientas_str, info["descripcion"])

    console.print(tabla)


def comando_spotify():
    estado = spotify_estado()
    console.print(Panel(
        f"[bold green]🎧 Spotify Desktop ({obtener_nombre_os()}):[/bold green]\n{estado}",
        title="[bold #1DB954] Spotify Status[/bold #1DB954]",
        border_style="#1DB954"
    ))


def obtener_todas_las_herramientas(mcp_mgr: MCPManager) -> list[Any]:
    herramientas = list(LOCAL_TOOL_FUNCTIONS.values())
    esquemas_mcp = mcp_mgr.obtener_esquemas_ollama()
    herramientas.extend(esquemas_mcp)
    return herramientas


async def ejecutar_agente_loop(
    cliente_ollama: AsyncClient,
    modelo: str,
    mensajes: list,
    mcp_mgr: MCPManager,
    modo_debug: bool = True
) -> str:
    paso = 1
    max_pasos = 8
    ultimo_mensaje_user = ""
    for m in reversed(mensajes):
        if m.get("role") == "user":
            ultimo_mensaje_user = m.get("content", "")
            break
    todas_las_herramientas = enrutar_herramientas_para_consulta(ultimo_mensaje_user, mcp_mgr)

    while paso <= max_pasos:
        with console.status(f"[bold cyan]Gordito ({modelo}) pensando...[/bold cyan]", spinner="dots"):
            respuesta = await cliente_ollama.chat(
                model=modelo,
                messages=mensajes,
                tools=todas_las_herramientas,
            )

        mensaje_modelo = respuesta.message
        mensajes.append(mensaje_modelo)

        # 🧠 Razonamiento interno (Thinking)
        thinking_content = getattr(mensaje_modelo, "thinking", None)
        if thinking_content:
            console.print(Panel(
                thinking_content.strip(),
                title="[bold magenta]🧠 Razonamiento de Gordito (Chain of Thought)[/bold magenta]",
                border_style="magenta",
                subtitle="Gordito analiza la petición y elige las herramientas necesarias"
            ))

        tool_calls = list(mensaje_modelo.tool_calls) if mensaje_modelo.tool_calls else []
        if not tool_calls:
            valid_names = set(LOCAL_TOOL_FUNCTIONS.keys()) | set(mcp_mgr.mcp_tools.keys())
            fallback_calls = extraer_tool_calls_fallback(mensaje_modelo.content or "", valid_names)
            if fallback_calls:
                tool_calls = fallback_calls
                mensaje_modelo.tool_calls = [
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in fallback_calls
                ]

        if not tool_calls and paso == 1:
            fn_name, fn_args = inferir_llamada_banxico_fallback(ultimo_mensaje_user)
            if not fn_name:
                fn_name, fn_args = inferir_llamada_busqueda_fallback(ultimo_mensaje_user)

            if fn_name and (fn_name in mcp_mgr.mcp_tools or fn_name in LOCAL_TOOL_FUNCTIONS):
                tool_calls = [SyntheticToolCall(fn_name, fn_args)]
                mensaje_modelo.tool_calls = [
                    {"function": {"name": fn_name, "arguments": fn_args}}
                ]

        if not tool_calls:
            return mensaje_modelo.content or "(Respuesta vacía)"

        mensaje_modelo.content = ""

        herramientas_ejecutadas: list[str] = []
        for tool_call in tool_calls:
            nombre_funcion = normalizar_nombre_herramienta(tool_call.function.name)
            herramientas_ejecutadas.append(nombre_funcion)
            argumentos = tool_call.function.arguments or {}

            if modo_debug:
                raw_tool_call = {
                    "role": "assistant",
                    "content": mensaje_modelo.content or "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": nombre_funcion,
                                "arguments": argumentos
                            }
                        }
                    ]
                }
                console.print(Panel(
                    JSON(json.dumps(raw_tool_call, indent=2)),
                    title=f"[bold green]🔍 [PASO {paso}.A] JSON CRUDO (Tool Call)[/bold green]",
                    border_style="green",
                    subtitle="Estructura generada tras su proceso de razonamiento"
                ))

            # Ejecución según origen
            if nombre_funcion in LOCAL_TOOL_FUNCTIONS:
                origen = f"Local (Python & {obtener_nombre_os()})"
                fn = LOCAL_TOOL_FUNCTIONS[nombre_funcion]
                try:
                    resultado_tool = fn(**argumentos)
                except Exception as err:
                    resultado_tool = f"Error al ejecutar localmente {nombre_funcion}: {err}"
                
                icono = "🌐" if "internet" in nombre_funcion or "web" in nombre_funcion else ("🎧" if "spotify" in nombre_funcion else "⚙️")
                titulo_box = f"[bold blue]{icono} [PASO {paso}.B] Gordito ejecutando acción local[/bold blue]"
                desc_ejecucion = f"[bold yellow]Función:[/bold yellow] `{nombre_funcion}(**{argumentos})`"
            
            elif nombre_funcion in mcp_mgr.mcp_tools:
                server_name, _ = mcp_mgr.mcp_tools[nombre_funcion]
                origen = f"🔌 MCP ({server_name})"
                resultado_tool = await mcp_mgr.ejecutar_herramienta(nombre_funcion, argumentos)
                titulo_box = f"[bold magenta]🔌 [PASO {paso}.B] Servidor MCP [{server_name}] ejecutando herramienta[/bold magenta]"
                desc_ejecucion = f"[bold yellow]Herramienta MCP:[/bold yellow] `{nombre_funcion}(**{argumentos})`"
            
            else:
                resultado_tool = f"Error: Herramienta '{nombre_funcion}' no reconocida."
                titulo_box = f"[red][PASO {paso}.B] Error de herramienta[/red]"
                desc_ejecucion = f"Herramienta desconocida: {nombre_funcion}"

            # Resumen visual
            vista_previa = str(resultado_tool)
            if len(vista_previa) > 400:
                vista_previa = vista_previa[:400] + "... [salida truncada en pantalla]"

            console.print(Panel(
                f"{desc_ejecucion}\n\n"
                f"[bold cyan]Salida obtenida:[/bold cyan]\n{vista_previa}",
                title=titulo_box,
                border_style="blue" if "Local" in origen else "magenta",
                subtitle=f"Origen de la herramienta: {origen}"
            ))

            payload_retorno = {
                "role": "tool",
                "content": str(resultado_tool)
            }

            if modo_debug:
                console.print(Panel(
                    JSON(json.dumps(payload_retorno, indent=2)),
                    title=f"[bold purple]📦 [PASO {paso}.C] Payload inyectado de vuelta al modelo[/bold purple]",
                    border_style="purple",
                    subtitle="Gordito recibe esta observación para responderte"
                ))

            mensajes.append(payload_retorno)
            paso += 1

        prompt_sintesis = generar_prompt_sintesis(ultimo_mensaje_user, herramientas_ejecutadas)
        mensajes_sintesis = list(mensajes) + [{
            "role": "user",
            "content": prompt_sintesis
        }]
        with console.status(f"[bold cyan]Gordito ({modelo}) sintetizando respuesta...[/bold cyan]", spinner="dots"):
            resp_sintesis = await cliente_ollama.chat(
                model=modelo,
                messages=mensajes_sintesis,
            )
        mensajes.append(resp_sintesis.message)
        return resp_sintesis.message.content or "Operación completada."

    return "Operación completada."


async def main_async():
    cliente_ollama = AsyncClient()
    mcp_mgr = MCPManager(CONFIG_MCP_PATH)

    with console.status("[bold green]Conectando con servidores MCP...[/bold green]", spinner="dots"):
        await mcp_mgr.conectar_servidores()

    total_mcp = len(mcp_mgr.mcp_tools)

    modelos = obtener_modelos_instalados(solo_con_tools=True)
    if not modelos:
        console.print("[bold red]⚠ Advertencia:[/bold red] No se detectaron modelos con soporte de herramientas (tools) en Ollama.")
        todos = obtener_modelos_instalados(solo_con_tools=False)
        nombres = [m.model for m in todos] if todos else ["qwen2.5-coder:7b"]
    else:
        nombres = [m.model for m in modelos]

    modelo_actual = "qwen2.5-coder:7b" if "qwen2.5-coder:7b" in nombres else (nombres[0] if nombres else "qwen2.5-coder:7b")
    modo_debug = True

    # Banner visual con Tux Linux
    imprimir_banner_gordito(
        modelo_actual,
        total_mcp=total_mcp,
        subtitulo="Modo Inspector",
        servidores_activos=list(mcp_mgr.sessions.keys())
    )

    mensajes = [{"role": "system", "content": obtener_system_prompt_gordito()}]

    completer = SlashCompleter(lambda: [m.model for m in obtener_modelos_instalados(solo_con_tools=True)])
    session = PromptSession(
        completer=completer,
        complete_while_typing=True,
        style=PROMPT_STYLE,
        history=InMemoryHistory()
    )

    try:
        while True:
            dir_nombre = os.path.basename(os.getcwd()) or "/"
            prompt_html = HTML(f"<b><ansigreen>gordito</ansigreen></b><ansidarkgray>:</ansidarkgray><ansidarkgray>{dir_nombre}</ansidarkgray> <ansigreen>❯</ansigreen> ")

            try:
                entrada_usuario = await session.prompt_async(prompt_html)
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]¡Hasta luego, Iñaki![/dim]\n")
                break

            texto = entrada_usuario.strip()
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
                    comando_help()
                    continue

                elif cmd == "/spotify":
                    comando_spotify()
                    continue

                elif cmd == "/mcp":
                    comando_mcp(mcp_mgr)
                    continue

                elif cmd in ["/clear", "/reset"]:
                    mensajes = [{"role": "system", "content": obtener_system_prompt_gordito()}]
                    console.print("[italic cyan]🧹 Memoria reiniciada.[/italic cyan]\n")
                    continue

                elif cmd in ["/raw", "/inspector"]:
                    modo_debug = not modo_debug
                    estado = "ACTIVADO" if modo_debug else "DESACTIVADO"
                    console.print(f"[italic cyan]Inspector detallado {estado}.[/italic cyan]\n")
                    continue

                elif cmd in ["/tools", "/schema"]:
                    mostrar_tabla_herramientas(mcp_mgr, console, filtro=arg)
                    continue

                elif cmd == "/models":
                    modelos_inst = [m.model for m in obtener_modelos_instalados(solo_con_tools=True)]
                    if not modelos_inst:
                        console.print("[red]No se encontraron modelos con soporte de herramientas en Ollama.[/red]\n")
                        continue
                    tabla = Table(title="🤖 Modelos Disponibles con Soporte de Herramientas (Tools)", border_style="bright_blue")
                    tabla.add_column("Nombre", style="bold cyan")
                    tabla.add_column("Activo", justify="center")
                    for m in modelos_inst:
                        activo = "✅ [bold yellow]ACTUAL[/bold yellow]" if m == modelo_actual else ""
                        tabla.add_row(m, activo)
                    console.print(tabla)
                    sel = await session.prompt_async(HTML(f"<b>Elige modelo (Enter para {modelo_actual}): </b>"), default=modelo_actual)
                    sel_clean = sel.strip()
                    if sel_clean in modelos_inst:
                        modelo_actual = sel_clean
                        console.print(f"[bold green]Cambiado a {modelo_actual}[/bold green]\n")
                    elif sel_clean and sel_clean != modelo_actual:
                        console.print(f"[red]Error:[/red] '{sel_clean}' no soporta herramientas o no existe.\n")
                    continue

                elif cmd == "/model":
                    modelos_inst = [m.model for m in obtener_modelos_instalados(solo_con_tools=True)]
                    if not arg:
                        console.print(f"\n[bold cyan]Modelo actual:[/bold cyan] [green]{modelo_actual}[/green]")
                        console.print("[bold cyan]Modelos disponibles con soporte de herramientas (tools):[/bold cyan]")
                        for m in modelos_inst:
                            marca = " [green]← activo[/green]" if m == modelo_actual else ""
                            console.print(f"  • {m}{marca}")
                        console.print("[dim]Uso: /model <nombre_modelo>[/dim]\n")
                    elif arg in modelos_inst:
                        modelo_actual = arg
                        console.print(f"[bold green]Modelo cambiado a: {modelo_actual}[/bold green]\n")
                    else:
                        if modelo_soporta_tools(arg):
                            modelo_actual = arg
                            console.print(f"[bold green]Modelo cambiado a: {modelo_actual}[/bold green]\n")
                        else:
                            console.print(f"[bold red]Error:[/bold red] El modelo '{arg}' no soporta herramientas (tools) en Ollama o no está instalado.")
                            console.print(f"[dim]Modelos compatibles disponibles: {', '.join(modelos_inst)}[/dim]\n")
                    continue

                else:
                    console.print(f"[red]Comando desconocido: {cmd}. Escribe /help.[/red]\n")
            # Detección inteligente de consultas sobre herramientas
            texto_norm = texto.lower().replace("?", "").replace("¿", "").strip()
            es_pregunta_tools = any(p in texto_norm for p in [
                "que tools", "que herramientas", "cuales tools", "cuales herramientas",
                "tus tools", "tus herramientas", "mis tools", "ver tools", "ver herramientas",
                "lista de tools", "lista de herramientas", "listar tools", "listar herramientas"
            ]) or ("tools" in texto_norm and any(w in texto_norm for w in ["conectad", "activ", "disponib", "tien", "toen"]))

            if es_pregunta_tools:
                mostrar_tabla_herramientas(mcp_mgr, console)
                continue

            # Turno normal de conversación con Gordito
            mensajes.append({"role": "user", "content": texto})

            respuesta_final = await ejecutar_agente_loop(
                cliente_ollama=cliente_ollama,
                modelo=modelo_actual,
                mensajes=mensajes,
                mcp_mgr=mcp_mgr,
                modo_debug=modo_debug
            )

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
