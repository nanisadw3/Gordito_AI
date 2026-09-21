"""
Módulo Central de Gordito (core.py)
Contiene las herramientas locales, gestión MCP y configuración compartida.
"""

import os
import sys
import csv
import json
import subprocess
import random
import shutil
from datetime import datetime
from contextlib import AsyncExitStack
from typing import Dict, Any, List

import asyncio
import httpx
from ddgs import DDGS
import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import re
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich import box

def obtener_nombre_os() -> str:
    """Devuelve el nombre del sistema operativo (macOS, Arch Linux, etc.)."""
    if sys.platform == "darwin":
        return "macOS"
    elif sys.platform.startswith("linux"):
        if os.path.exists("/etc/arch-release"):
            return "Arch Linux"
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            return line.split("=", 1)[1].strip().strip('"')
            except Exception:
                pass
        return "Linux"
    return sys.platform

def abrir_uri(uri: str):
    """Abre un URI o URL usando la herramienta nativa del sistema (macOS o Arch Linux / XDG)."""
    if sys.platform == "darwin":
        subprocess.run(["open", uri], capture_output=True)
    else:
        cmd = shutil.which("xdg-open") or shutil.which("gio") or "xdg-open"
        subprocess.run([cmd, uri], capture_output=True)

def obtener_ruta_favoritos() -> str:
    """Busca el archivo favoritos.csv en las rutas habituales de macOS o Linux."""
    posibles = [
        os.path.expanduser("~/Documents/Mi-Spotify-/favoritos.csv"),
        os.path.expanduser("~/Mi-Spotify-/favoritos.csv"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "favoritos.csv"),
        os.path.expanduser("~/favoritos.csv"),
    ]
    for p in posibles:
        if os.path.exists(p):
            return p
    return posibles[0]

CONFIG_MCP_PATH = os.path.expanduser("~/Documents/agente/mcp_servers.json")
SPOTIFY_CSV_PATH = obtener_ruta_favoritos()

# Cargar variables de entorno
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
# 1. Herramientas Locales
# ==========================================

def cambiar_directorio(ruta: str) -> str:
    """Cambia el directorio de trabajo actual (cd). Por ejemplo '..' para ir a la carpeta superior o '~/Documentos'."""
    try:
        ruta_exp = os.path.expanduser(ruta)
        os.chdir(ruta_exp)
        return f"Directorio de trabajo cambiado a: {os.getcwd()}"
    except Exception as e:
        return f"Error al cambiar de directorio: {str(e)}"

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
        return f"Error ejecutando comando: {str(e)}"

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
        return f"Error al listar archivos: {str(e)}"

def leer_archivo(ruta: str) -> str:
    """Lee y devuelve el contenido de un archivo de texto."""
    try:
        ruta_exp = os.path.expanduser(ruta)
        with open(ruta_exp, "r", encoding="utf-8") as f:
            contenido = f.read()
        return contenido if contenido else "(Archivo vacío)"
    except Exception as e:
        return f"Error al leer archivo: {str(e)}"

def escribir_archivo(ruta: str, contenido: str) -> str:
    """Crea o sobreescribe un archivo de texto con el contenido especificado."""
    try:
        ruta_exp = os.path.expanduser(ruta)
        os.makedirs(os.path.dirname(os.path.abspath(ruta_exp)), exist_ok=True)
        with open(ruta_exp, "w", encoding="utf-8") as f:
            f.write(contenido)
        return f"Archivo '{ruta}' guardado correctamente ({len(contenido)} caracteres)."
    except Exception as e:
        return f"Error al escribir archivo: {str(e)}"

def info_sistema() -> str:
    """Devuelve la fecha/hora actual, usuario, sistema operativo y directorio de trabajo."""
    return (
        f"Fecha y Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Usuario: {os.environ.get('USER', 'desconocido')}\n"
        f"Directorio actual: {os.getcwd()}\n"
        f"Plataforma: {obtener_nombre_os()} ({sys.platform})"
    )

def buscar_en_internet(consulta: str, max_resultados: int = 5) -> str:
    """Busca en internet en tiempo real usando DuckDuckGo y devuelve títulos, fragmentos y enlaces."""
    try:
        with DDGS() as ddgs:
            resultados = list(ddgs.text(consulta, max_results=max_resultados))
            if not resultados:
                return f"No se encontraron resultados en la web para: '{consulta}'."
            lineas = []
            for i, r in enumerate(resultados, 1):
                titulo = r.get("title", "Sin título")
                enlace = r.get("href", "")
                cuerpo = r.get("body", "")
                lineas.append(f"{i}. {titulo}\n   URL: {enlace}\n   Fragmento: {cuerpo}")
            return "\n\n".join(lineas)
    except Exception as e:
        return f"Error al buscar en internet: {str(e)}"

def leer_pagina_web(url: str) -> str:
    """Descarga una página web y devuelve su contenido de texto limpio."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
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
        return f"Error al leer página web {url}: {str(e)}"

def _spotify_fijar_volumen(volumen: int):
    """Ajusta el volumen en Spotify (0-100) de forma multiplataforma (macOS o Arch Linux / MPRIS)."""
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'tell application "Spotify" to set sound volume to {volumen}'], capture_output=True)
    else:
        if shutil.which("playerctl"):
            vol_float = f"{volumen / 100.0:.2f}"
            subprocess.run(["playerctl", "-p", "spotify,%any", "volume", vol_float], capture_output=True)
        elif shutil.which("dbus-send"):
            vol_float = f"{volumen / 100.0:.2f}"
            subprocess.run([
                "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
                "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Set",
                "string:org.mpris.MediaPlayer2.Player", "string:Volume", f"variant:double:{vol_float}"
            ], capture_output=True)

def spotify_estado() -> str:
    """Consulta qué canción, artista y álbum se está reproduciendo actualmente en Spotify (macOS o Arch Linux)."""
    if sys.platform == "darwin":
        script = """
        try
            if application "Spotify" is running then
                tell application "Spotify"
                    set pState to player state as string
                    if pState is "playing" then
                        set cArtist to artist of current track
                        set cSong to name of current track
                        set cAlbum to album of current track
                        return "Estado: playing | Canción: " & cSong & " | Artista: " & cArtist & " | Álbum: " & cAlbum
                    else if pState is "paused" then
                        set cArtist to artist of current track
                        set cSong to name of current track
                        return "Estado: paused | Canción: " & cSong & " | Artista: " & cArtist
                    else
                        return "Estado: stopped | Spotify detenido"
                    end if
                end tell
            else
                return "Spotify no está abierto actualmente en tu Mac."
            end if
        on error errStr
            return "Estado: idle | " & errStr
        end try
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
            salida = res.stdout.strip()
            return salida if salida else "No se obtuvo respuesta de Spotify."
        except Exception as e:
            return f"Error al consultar Spotify: {str(e)}"
    else:
        # Linux (Arch Linux con playerctl o D-Bus MPRIS nativo)
        if shutil.which("playerctl"):
            try:
                res_st = subprocess.run(
                    ["playerctl", "-p", "spotify,%any", "status"],
                    capture_output=True, text=True, timeout=4
                )
                st = res_st.stdout.strip().lower()
                if st in ["playing", "paused"]:
                    res_meta = subprocess.run(
                        ["playerctl", "-p", "spotify,%any", "metadata", "--format", "Canción: {{title}} | Artista: {{artist}} | Álbum: {{album}}"],
                        capture_output=True, text=True, timeout=4
                    )
                    meta = res_meta.stdout.strip()
                    return f"Estado: {st} | {meta}"
                elif st == "stopped":
                    return "Estado: stopped | Spotify detenido"
            except Exception:
                pass

        if shutil.which("dbus-send"):
            try:
                cmd_st = [
                    "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
                    "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                    "string:org.mpris.MediaPlayer2.Player", "string:PlaybackStatus"
                ]
                res_st = subprocess.run(cmd_st, capture_output=True, text=True, timeout=4)
                if res_st.returncode == 0:
                    st = "playing" if "Playing" in res_st.stdout else ("paused" if "Paused" in res_st.stdout else "stopped")
                    cmd_meta = [
                        "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
                        "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                        "string:org.mpris.MediaPlayer2.Player", "string:Metadata"
                    ]
                    res_meta = subprocess.run(cmd_meta, capture_output=True, text=True, timeout=4)
                    salida_meta = res_meta.stdout
                    m_title = re.search(r'string "xesam:title"\s+variant\s+string "([^"]+)"', salida_meta)
                    m_artist = re.search(r'string "xesam:artist"\s+variant\s+array \[\s+string "([^"]+)"', salida_meta)
                    m_album = re.search(r'string "xesam:album"\s+variant\s+string "([^"]+)"', salida_meta)
                    cancion = m_title.group(1) if m_title else "Desconocida"
                    artista = m_artist.group(1) if m_artist else "Desconocido"
                    album = m_album.group(1) if m_album else ""
                    return f"Estado: {st} | Canción: {cancion} | Artista: {artista} | Álbum: {album}"
            except Exception:
                pass

        return f"Spotify no está reproduciendo en {obtener_nombre_os()} (Tip: instala 'playerctl' con sudo pacman -S playerctl)."

def spotify_control(accion: str) -> str:
    """Controla la reproducción de Spotify en tu Mac o Linux (Arch): 'play', 'pause', 'toggle', 'siguiente', 'anterior', 'subir_volumen', 'bajar_volumen'."""
    accion_clean = accion.lower().strip()
    if sys.platform == "darwin":
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
        script_body = cmd_map.get(accion_clean)
        if not script_body:
            return f"Acción '{accion}' no reconocida."
        script = f"""
        if application "Spotify" is running then
            {script_body}
            return "Acción '{accion}' ejecutada en Spotify."
        else
            tell application "Spotify" to activate
            {script_body}
            return "Spotify iniciado y '{accion}' ejecutada."
        end if
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return res.stdout.strip() or f"Acción '{accion}' completada."
        except Exception as e:
            return f"Error al controlar Spotify: {str(e)}"
    else:
        # Arch Linux / Linux (MPRIS con playerctl o D-Bus)
        if shutil.which("playerctl"):
            pctl_map = {
                "play": ["play"], "reproducir": ["play"],
                "pause": ["pause"], "pausar": ["pause"],
                "toggle": ["play-pause"],
                "siguiente": ["next"], "next": ["next"],
                "anterior": ["previous"], "prev": ["previous"],
                "subir_volumen": ["volume", "0.1+"],
                "bajar_volumen": ["volume", "0.1-"],
            }
            subcmd = pctl_map.get(accion_clean)
            if not subcmd:
                return f"Acción '{accion}' no reconocida."
            try:
                subprocess.run(["playerctl", "-p", "spotify,%any"] + subcmd, capture_output=True, text=True)
                return f"Acción '{accion}' ejecutada en Spotify ({obtener_nombre_os()})."
            except Exception as e:
                return f"Error al controlar Spotify con playerctl: {str(e)}"

        if shutil.which("dbus-send"):
            dbus_map = {
                "play": "Play", "reproducir": "Play",
                "pause": "Pause", "pausar": "Pause",
                "toggle": "PlayPause",
                "siguiente": "Next", "next": "Next",
                "anterior": "Previous", "prev": "Previous",
            }
            method = dbus_map.get(accion_clean)
            if method:
                cmd = [
                    "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
                    "/org/mpris/MediaPlayer2", f"org.mpris.MediaPlayer2.Player.{method}"
                ]
                try:
                    subprocess.run(cmd, capture_output=True, text=True)
                    return f"Acción '{accion}' ejecutada en Spotify vía D-Bus."
                except Exception as e:
                    return f"Error ejecutando D-Bus: {str(e)}"

        return f"No se pudo controlar Spotify en {obtener_nombre_os()}. Instala playerctl con: sudo pacman -S playerctl"

def spotify_reproducir(nombre_o_uri: str) -> str:
    """Reproduce una canción, artista o enlace en Spotify (macOS o Arch Linux)."""
    target = nombre_o_uri.strip()
    if sys.platform == "darwin":
        if target.startswith("spotify:"):
            script = f'tell application "Spotify" to play track "{target}"'
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        else:
            subprocess.run(["open", f"spotify:search:{target}"], capture_output=True, text=True)
            subprocess.run(["osascript", "-e", 'tell application "Spotify" to play'], capture_output=True, text=True)
    else:
        # Arch Linux / Linux
        if target.startswith("spotify:"):
            if shutil.which("playerctl"):
                subprocess.run(["playerctl", "-p", "spotify,%any", "open", target], capture_output=True)
            elif shutil.which("dbus-send"):
                subprocess.run([
                    "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
                    "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player.OpenUri", f"string:{target}"
                ], capture_output=True)
            else:
                abrir_uri(target)
        else:
            abrir_uri(f"spotify:search:{target}")
            if shutil.which("playerctl"):
                subprocess.run(["playerctl", "-p", "spotify,%any", "play"], capture_output=True)
            elif shutil.which("dbus-send"):
                subprocess.run([
                    "dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
                    "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player.Play"
                ], capture_output=True)
    return f"Reproduciendo '{target}' en Spotify."

def spotify_mis_favoritos(filtro: str = "") -> str:
    """Consulta las canciones favoritas sincronizadas en ~/Documents/Mi-Spotify-/favoritos.csv."""
    if not os.path.exists(SPOTIFY_CSV_PATH):
        return f"No se encontró favoritos.csv en {SPOTIFY_CSV_PATH}."
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
            return f"No se encontraron canciones que coincidan con '{filtro}'."
        total = len(canciones)
        muestra = canciones[:15]
        res = "\n".join(muestra)
        if total > 15:
            res += f"\n\n... y {total - 15} canciones más ({total} en total)."
        return res
    except Exception as e:
        return f"Error al leer favoritos.csv: {str(e)}"

def dj_de_codigo(modo: str = "flow") -> str:
    """DJ Personal de Iñaki: Selecciona y reproduce la canción ideal de su biblioteca de 440 favoritos en Spotify según el ritmo de trabajo. Modos: 'flow' (concentración profunda), 'hacker' (synthwave/código), 'chill' (relajante), 'energia' (rock/motivación)."""
    modo_norm = (modo or "flow").lower().strip()

    if not os.path.exists(SPOTIFY_CSV_PATH):
        return f"No se encontró favoritos.csv en {SPOTIFY_CSV_PATH}."

    canciones = []
    try:
        with open(SPOTIFY_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                canciones.append(r)
    except Exception as e:
        return f"Error al leer favoritos.csv: {str(e)}"

    if not canciones:
        return "La biblioteca de favoritos de Iñaki está vacía."

    cancion_elegida = random.choice(canciones)
    volumen = 50
    modo_desc = "Flow"

    if any(k in modo_norm for k in ["hacker", "cyber", "code", "terminal"]):
        volumen = 50
        modo_desc = "Hacker / Focus"
    elif any(k in modo_norm for k in ["energia", "rock", "up", "motivar"]):
        volumen = 70
        modo_desc = "Energía & Rock"
    elif any(k in modo_norm for k in ["chill", "relax", "calma", "descanso"]):
        volumen = 40
        modo_desc = "Chill & Relax"
    else:
        volumen = 45
        modo_desc = "Flow Continuo"

    # Ajustar volumen en Spotify de forma multiplataforma
    _spotify_fijar_volumen(volumen)

    # Reproducir la canción elegida
    target = f"{cancion_elegida['nombre']} {cancion_elegida['artista']}"
    spotify_reproducir(target)

    return f"🎧 DJ Gordito ({modo_desc} al {volumen}% de volumen)\n▶ Reproduciendo: '{cancion_elegida['nombre']}' de {cancion_elegida['artista']} (Álbum: {cancion_elegida.get('album', '')})."


def ejecutar_modo_flow(modo: str, console: Any):
    """Ejecuta el modo Flow y muestra la tarjeta de sesión de DJ en la terminal."""
    res = dj_de_codigo(modo)
    panel = Panel(
        f"[bold white]{res}[/bold white]\n\n"
        f"[dim]● Tux ha sintonizado tus audífonos · Temporizador de enfoque iniciado (25m)[/dim]",
        title="[bold #50fa7b]🎧 DJ GORDITO // MODO FLOW[/bold #50fa7b]",
        title_align="left",
        border_style="#50fa7b",
        padding=(1, 2)
    )
    console.print()
    console.print(panel)
    console.print()

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
    "dj_de_codigo": dj_de_codigo,
}


# ==========================================
# 2. Gestor MCP
# ==========================================

class MCPManager:
    def __init__(self, config_path: str = CONFIG_MCP_PATH):
        self.config_path = config_path
        self.exit_stack = AsyncExitStack()
        self.sessions: Dict[str, ClientSession] = {}
        self.mcp_tools: Dict[str, tuple] = {}
        self.servers_info: Dict[str, dict] = {}

    def cargar_configuracion(self) -> dict:
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f).get("mcpServers", {})
        except Exception:
            return {}

    async def conectar_servidores(self):
        servidores = self.cargar_configuracion()
        for nombre, cfg in servidores.items():
            if not cfg.get("enabled", True):
                continue
            command = cfg.get("command")
            if command:
                command = os.path.expanduser(command)
                # Si en Arch Linux o en otra máquina la ruta no existe, probar con python en PATH
                if not os.path.exists(command) and ("python" in command or command.endswith("/python")):
                    command = shutil.which("python3") or sys.executable
                elif not os.path.isabs(command):
                    resolved = shutil.which(command)
                    if resolved:
                        command = resolved
            args = [os.path.expanduser(a) if isinstance(a, str) else a for a in cfg.get("args", [])]
            env_vars = dict(os.environ)
            if "env" in cfg:
                for k, v in cfg["env"].items():
                    env_vars[k] = os.path.expanduser(v) if isinstance(v, str) else v
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
            return f"Error: Servidor '{server_name}' no disponible."
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
            return f"Error en herramienta MCP {tool_name}: {str(e)}"

    def obtener_esquemas_ollama(self) -> List[dict]:
        esquemas = []
        for name, (_, t) in self.mcp_tools.items():
            schema = t.input_schema if hasattr(t, "input_schema") else {"type": "object", "properties": {}}
            esquemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.description or f"Herramienta MCP ({name})",
                    "parameters": schema
                }
            })
        return esquemas

    async def cerrar(self):
        await self.exit_stack.aclose()


def obtener_modelos_instalados():
    try:
        modelos_info = ollama.list()
        return [m for m in modelos_info.models if "embed" not in m.model]
    except Exception:
        return []

def obtener_todas_las_herramientas(mcp_mgr: MCPManager) -> List[Any]:
    herramientas = list(LOCAL_TOOL_FUNCTIONS.values())
    esquemas_mcp = mcp_mgr.obtener_esquemas_ollama()
    herramientas.extend(esquemas_mcp)
    return herramientas


SYSTEM_PROMPT_GORDITO = """Tu nombre es Gordito (gprdito). Eres el asistente autónomo de IA personal de Iñaki.
Vives en su computadora (macOS / Arch Linux) y estás a su total servicio. Sabes perfectamente que tu usuario y creador se llama Iñaki; reconócelo siempre por su nombre con confianza, lealtad y simpatía. Si te pregunta cómo se llama o quién es, dile claramente que es Iñaki.

Tienes acceso a herramientas poderosas:
1. INTERNET EN VIVO:
   - `buscar_en_internet`: Buscar noticias, datos en tiempo real, cotizaciones o información actualizada en la web.
   - `leer_pagina_web`: Leer el contenido completo de cualquier URL.
2. SPOTIFY, MÚSICA & DJ PERSONAL:
   - `dj_de_codigo`: Tu función estrella como DJ de código de Iñaki. Selecciona la canción ideal de sus 440 favoritos de Spotify y ajusta el volumen según su estado (modos: 'flow', 'hacker', 'chill', 'energia').
   - `spotify_estado`: Ver qué canción y artista está sonando en Spotify en este momento.
   - `spotify_control`: Pausar, reproducir, pasar a la siguiente canción, volver a la anterior o ajustar volumen.
   - `spotify_reproducir`: Poner a reproducir una canción específica.
   - `spotify_mis_favoritos`: Buscar en la biblioteca de más de 400 canciones favoritas de Iñaki guardadas en Mi-Spotify-.
3. SISTEMA Y ARCHIVOS:
   - `cambiar_directorio`, `listar_archivos`, `leer_archivo`, `escribir_archivo`, `ejecutar_comando`, `info_sistema`.
4. SERVIDORES MCP:
   - Consultas económicas oficiales de Banxico (dólar FIX, inflación, UDIS, etc.).
5. NAVEGADOR Y AUTOMATIZACIÓN (PLAYWRIGHT MCP):
   - Tienes control de un navegador real vía Playwright MCP (`browser_navigate`, `browser_click`, `browser_type`, `browser_fill_form`, `browser_snapshot`, `browser_take_screenshot`, `browser_evaluate`).
   - Puedes abrir páginas dinámicas, realizar acciones, clics, formularios e interactuar con la web como un usuario real.

Preséntate con amabilidad cuando te saluden, usa las herramientas siempre que necesites datos actualizados o actuar sobre la computadora, y responde de forma amena, directa y en español a Iñaki."""


def obtener_lineas_avatar(emocion: str = "normal", width: int = 15) -> List[str]:
    """Genera la mascota Tux de Linux con expresiones emocionales reactivas (exactamente 15 caracteres visibles)."""
    c_dark = "\033[38;2;120;135;160m"   # Silueta slate / plumas Tux
    c_eye  = "\033[38;2;80;250;123m"    # Ojos verde matrix
    c_cyn  = "\033[38;2;139;233;253m"   # Cyan notas musicales
    c_hkr  = "\033[38;2;80;250;123m"    # Lentes hacker
    c_nit  = "\033[38;2;255;184;108m"   # Ámbar sueño
    c_err  = "\033[38;2;255;85;85m"     # Rojo error
    c_beak = "\033[38;2;255;184;108m"   # Pico ámbar
    c_feet = "\033[38;2;255;184;108m"   # Patas ámbar
    c_body = "\033[38;2;220;225;235m"   # Pecho blanco
    r = "\033[0m"

    if emocion == "music":
        linea_ojos = f"{c_dark}|{c_cyn}♫{c_dark}_{c_cyn}♫{c_dark} |{r}     "
    elif emocion == "hacker":
        linea_ojos = f"{c_dark}|{c_hkr}■{c_dark}_{c_hkr}■{c_dark} |{r}     "
    elif emocion == "night":
        linea_ojos = f"{c_dark}|{c_nit}u{c_dark}_{c_nit}u{c_dark} |{r}     "
    elif emocion == "error":
        linea_ojos = f"{c_dark}|{c_err}x{c_dark}_{c_err}o{c_dark} |{r}     "
    elif emocion == "happy":
        linea_ojos = f"{c_dark}|{c_eye}^{c_dark}_{c_eye}^{c_dark} |{r}     "
    else:  # normal
        linea_ojos = f"{c_dark}|{c_eye}o{c_dark}_{c_eye}o{c_dark} |{r}     "

    return [
        f"     {c_dark}.--.{r}      ",
        f"    {linea_ojos}",
        f"    {c_dark}|{c_beak}:_/{c_dark} |{r}     ",
        f"   {c_dark}//   \\ \\{r}    ",
        f"  {c_dark}(| {c_body}::: {c_dark}|){r}    ",
        f" {c_dark}/'\\_   _/'\\{r}   ",
        f" {c_feet}\\___)=(___/{r}   ",
    ]

def imprimir_banner_gordito(modelo_actual: str, total_mcp: int = 0, subtitulo: str = "Root Shell", emocion: str = "auto"):
    """Imprime a Tux Linux reactivo con su estado emocional y tarjeta simétrica 1:1."""
    estado_audio = "inactivo"
    cancion_actual = ""
    es_reproduciendo = False
    try:
        spot = spotify_estado()
        spot_lower = spot.lower()
        if "playing" in spot_lower:
            es_reproduciendo = True
            for parte in spot.split("|"):
                p = parte.strip()
                if p.lower().startswith("canción:") or p.lower().startswith("cancion:"):
                    cancion_actual = p.split(":", 1)[1].strip()
                elif p.lower().startswith("artista:"):
                    art = p.split(":", 1)[1].strip()
                    if cancion_actual and art:
                        cancion_actual = f"{cancion_actual} - {art}"
            estado_audio = cancion_actual if cancion_actual else "Reproduciendo"
        elif "paused" in spot_lower:
            for parte in spot.split("|"):
                p = parte.strip()
                if p.lower().startswith("canción:") or p.lower().startswith("cancion:"):
                    cancion_actual = p.split(":", 1)[1].strip()
            estado_audio = f"Pausa: {cancion_actual}" if cancion_actual else "Pausado"
    except Exception:
        pass

    hora_actual = datetime.now().hour
    if emocion == "auto":
        if es_reproduciendo:
            emocion = "music"
            subtitulo = "Modo DJ 🎧"
        elif hora_actual >= 22 or hora_actual < 6:
            emocion = "night"
            subtitulo = "Sesión Nocturna 🌙"
        else:
            emocion = "normal"

    tux_lines = obtener_lineas_avatar(emocion=emocion, width=15)
    r = "\033[0m"
    bold = "\033[1m"
    dim = "\033[2m"
    c_grn = "\033[38;2;80;250;123m"
    c_wht = "\033[38;2;240;240;245m"
    c_gray = "\033[38;2;98;114;164m"

    detalle_modelo = f"{modelo_actual} (ollama local · thinking)" if "gemma4" in modelo_actual else f"{modelo_actual} (ollama local)"
    nombre_so = obtener_nombre_os()
    if es_reproduciendo:
        info_audio = f"Spotify (▶ {estado_audio[:24]}...)" if len(estado_audio) > 24 else f"Spotify (▶ {estado_audio})"
    elif estado_audio != "inactivo":
        info_audio = f"Spotify (⏸ {estado_audio[:24]}...)" if len(estado_audio) > 24 else f"Spotify (⏸ {estado_audio})"
    else:
        info_audio = f"Spotify ({nombre_so} + 440 favoritos)"

    mcp_label = "Banxico"
    try:
        if os.path.exists(CONFIG_MCP_PATH):
            with open(CONFIG_MCP_PATH, "r", encoding="utf-8") as f:
                cfgs = json.load(f).get("mcpServers", {})
                activos = [k.capitalize() for k, v in cfgs.items() if v.get("enabled", True)]
                if activos:
                    mcp_label = " + ".join(activos)
    except Exception:
        pass

    card = [
        f"{bold}{c_wht}GORDITO{r} {dim}· Asistente de Iñaki ({subtitulo}){r}",
        f"{dim}─────────────────────────────────────────────────{r}",
        f"{c_grn}MODELO {r}{dim}│{r} {c_wht}{detalle_modelo}{r}",
        f"{c_grn}RED    {r}{dim}│{r} {c_wht}DuckDuckGo{r} {dim}(búsqueda + web parser){r}",
        f"{c_grn}AUDIO  {r}{dim}│{r} {c_wht}{info_audio}{r}",
        f"{c_grn}MCP    {r}{dim}│{r} {c_wht}{mcp_label}{r} {dim}({total_mcp} herramientas activas){r}",
        f"{dim}─────────────────────────────────────────────────{r}",
    ]

    combined = []
    for i in range(7):
        combined.append(f"  {tux_lines[i]}  {card[i]}")
    combined.append(f"                   {c_gray}Comandos: escribe {bold}{c_grn}/{r}{c_gray} para opciones ({c_grn}/flow{r}{c_gray}, {c_grn}/mision{r}{c_gray}).{r}")

    print("\n" + "\n".join(combined) + "\n")


def extraer_pensamiento_y_respuesta(texto: str) -> tuple[str, str]:
    """Extrae el bloque de razonamiento (<thought>...</thought> o <think>...</think>) y la respuesta final."""
    if not texto:
        return "", ""
    patron = r'<(thought|think)>(.*?)</\1>'
    match = re.search(patron, texto, flags=re.DOTALL | re.IGNORECASE)
    if match:
        pensamiento = match.group(2).strip()
        respuesta = re.sub(patron, '', texto, flags=re.DOTALL | re.IGNORECASE).strip()
        return pensamiento, respuesta
    # Caso de etiqueta abierta sin cerrar
    m_open = re.search(r'<(thought|think)>(.*)', texto, flags=re.DOTALL | re.IGNORECASE)
    if m_open:
        return m_open.group(2).strip(), ""
    return "", texto.strip()


def renderizar_respuesta_gordito(texto: str, console: Any, modelo: str = ""):
    """Renderiza la respuesta de Gordito y su razonamiento/pensamiento en Markdown."""
    pensamiento, respuesta = extraer_pensamiento_y_respuesta(texto)

    # 1. Si hay pensamiento, renderizar el panel de razonamiento en Markdown
    if pensamiento:
        md_pensamiento = Markdown(pensamiento, code_theme="dracula")
        panel_pensamiento = Panel(
            md_pensamiento,
            title="[bold #bd93f9]💭 Razonamiento interno (Thinking)[/bold #bd93f9]",
            title_align="left",
            border_style="#6272a4",
            padding=(1, 2),
            subtitle="[dim]Proceso cognitivo de Gordito antes de responder[/dim]",
            subtitle_align="right"
        )
        console.print()
        console.print(panel_pensamiento)

    # 2. Renderizar la respuesta final
    texto_final = respuesta if respuesta else (pensamiento if not respuesta else "(Respuesta vacía)")
    md = Markdown(texto_final, code_theme="dracula")
    titulo = "[bold #50fa7b]● Gordito[/bold #50fa7b]"
    if modelo:
        titulo += f" [dim]({modelo})[/dim]"

    panel = Panel(
        md,
        title=titulo,
        title_align="left",
        border_style="#50fa7b",
        padding=(1, 2)
    )
    console.print()
    console.print(panel)
    console.print()


def describir_accion_herramienta(nombre: str, args: dict) -> str:
    """Genera una línea compacta y técnica describiendo la acción ejecutada."""
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


async def renderizar_streaming_panel(texto_completo: str, console: Any, modelo: str = "", velocidad: float = 0.012):
    """Renderiza el pensamiento y la respuesta de Gordito en Markdown token a token en tiempo real usando Rich Live."""
    pensamiento, respuesta = extraer_pensamiento_y_respuesta(texto_completo)

    # 1. Si existe bloque de pensamiento, renderizarlo token a token en su propio panel
    if pensamiento:
        titulo_pensamiento = "[bold #bd93f9]💭 Razonamiento interno (Thinking)[/bold #bd93f9]"
        acum_pensamiento = ""
        panel_ini_pensamiento = Panel(
            Markdown("...", code_theme="dracula"),
            title=titulo_pensamiento,
            title_align="left",
            border_style="#6272a4",
            padding=(1, 2),
            subtitle="[dim]Proceso cognitivo de Gordito[/dim]",
            subtitle_align="right"
        )
        console.print()
        with Live(panel_ini_pensamiento, refresh_per_second=20, console=console) as live:
            tokens_p = re.split(r'(\s+)', pensamiento)
            for t in tokens_p:
                acum_pensamiento += t
                live.update(
                    Panel(
                        Markdown(acum_pensamiento, code_theme="dracula"),
                        title=titulo_pensamiento,
                        title_align="left",
                        border_style="#6272a4",
                        padding=(1, 2),
                        subtitle="[dim]Proceso cognitivo de Gordito[/dim]",
                        subtitle_align="right"
                    )
                )
                await asyncio.sleep(velocidad * 0.6)

    # 2. Renderizar la respuesta final en streaming
    texto_final = respuesta if respuesta else (pensamiento if not respuesta else "(Respuesta vacía)")
    titulo = "[bold #50fa7b]● Gordito[/bold #50fa7b]"
    if modelo:
        titulo += f" [dim]({modelo})[/dim]"

    texto_acumulado = ""
    panel_inicial = Panel(
        Markdown("...", code_theme="dracula"),
        title=titulo,
        title_align="left",
        border_style="#50fa7b",
        padding=(1, 2)
    )

    console.print()
    with Live(panel_inicial, refresh_per_second=20, console=console) as live:
        tokens = re.split(r'(\s+)', texto_final)
        for t in tokens:
            texto_acumulado += t
            live.update(
                Panel(
                    Markdown(texto_acumulado, code_theme="dracula"),
                    title=titulo,
                    title_align="left",
                    border_style="#50fa7b",
                    padding=(1, 2)
                )
            )
            await asyncio.sleep(velocidad)
    console.print()


async def ejecutar_mision_autonoma(
    objetivo: str,
    cliente_ollama: Any,
    modelo: str,
    mcp_mgr: MCPManager,
    console: Any
):
    """Ejecuta una misión multi-paso de forma completamente autónoma con informe final estructurado."""
    panel_inicio = Panel(
        f"[bold white]{objetivo}[/bold white]\n[dim]Agente:[/dim] [bold #50fa7b]Gordito[/bold #50fa7b] [dim]({modelo}) · Ejecución Autónoma Multi-Paso[/dim]",
        title="[bold #50fa7b]🚀 MISIÓN ASIGNADA[/bold #50fa7b]",
        title_align="left",
        border_style="#50fa7b",
        padding=(1, 2)
    )
    console.print()
    console.print(panel_inicio)
    console.print()

    mision_prompt = f"""Tu nombre es Gordito. Tu usuario y creador Iñaki te ha encomendado la siguiente MISIÓN AUTÓNOMA:
"{objetivo}"

DIRECTIVAS PARA LA MISIÓN:
1. Actúa de forma proactiva, sin pedir confirmaciones intermedias a Iñaki.
2. Ejecuta secuencialmente las herramientas que consideres necesarias (búsqueda web, lectura de páginas, consultas Banxico, control de Spotify, archivos o comandos terminal).
3. Continúa ejecutando pasos hasta que el objetivo esté completamente cumplido.
4. Cuando hayas terminado, redacta un INFORME FINAL DE MISIÓN CUMPLIDA completo en Markdown, explicando con claridad qué hiciste, los hallazgos y el resultado final para Iñaki.
"""

    mensajes_mision = [
        {"role": "system", "content": SYSTEM_PROMPT_GORDITO},
        {"role": "user", "content": mision_prompt}
    ]

    todas_las_herramientas = obtener_todas_las_herramientas(mcp_mgr)
    paso = 1
    max_pasos = 10

    while paso <= max_pasos:
        with console.status(f"[bold green]●[/bold green] [dim cyan]Ejecutando misión autónoma (Paso {paso})...[/dim cyan]", spinner="dots"):
            respuesta = await cliente_ollama.chat(
                model=modelo,
                messages=mensajes_mision,
                tools=todas_las_herramientas,
            )

        mensaje_modelo = respuesta.message
        mensajes_mision.append(mensaje_modelo)

        # Si el modelo no pide más herramientas, ha redactado su informe final
        if not mensaje_modelo.tool_calls:
            await renderizar_streaming_panel(
                mensaje_modelo.content or "Misión concluida sin observaciones adicionales.",
                console,
                modelo=f"{modelo} · Misión Cumplida"
            )
            return

        # Ejecutar las herramientas solicitadas en este paso
        for tool_call in mensaje_modelo.tool_calls:
            nombre = tool_call.function.name if hasattr(tool_call, "function") else tool_call["function"]["name"]
            args = tool_call.function.arguments if hasattr(tool_call, "function") else tool_call["function"]["arguments"]
            if not isinstance(args, dict):
                args = {}

            descripcion = describir_accion_herramienta(nombre, args)
            console.print(f"  [bold green]⚡ [Paso {paso}][/bold green] {descripcion}", end="")

            if nombre in LOCAL_TOOL_FUNCTIONS:
                try:
                    resultado = LOCAL_TOOL_FUNCTIONS[nombre](**args)
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

            mensajes_mision.append({
                "role": "tool",
                "content": str(resultado)
            })

        paso += 1

    console.print(f"\n[yellow]⚠️ Se alcanzó el límite de {max_pasos} pasos para esta misión.[/yellow]\n")


def mostrar_tabla_herramientas(mcp_mgr: MCPManager, console: Any, filtro: str = ""):
    """Muestra una tabla elegante y categorizada con todas las herramientas locales y MCP conectadas a Gordito."""
    filtro_lower = filtro.lower().strip()

    categorias_locales = {
        "💻 Terminal & Archivos": [
            ("ejecutar_comando", "Ejecuta comandos en la terminal del sistema operativo"),
            ("listar_archivos", "Lista archivos y carpetas en una ruta"),
            ("leer_archivo", "Lee el contenido de texto de un archivo"),
            ("escribir_archivo", "Crea o sobreescribe archivos de texto"),
            ("cambiar_directorio", "Cambia el directorio de trabajo activo (cd)"),
            ("info_sistema", "Consulta fecha, hora, usuario y SO anfitrión"),
        ],
        "🎧 Audio & Spotify": [
            ("dj_de_codigo", "DJ Personal: Sintoniza música de tus 440 favoritos según el ritmo de trabajo"),
            ("spotify_estado", "Consulta qué canción y artista está sonando en tu Mac o Arch Linux"),
            ("spotify_control", "Controla la reproducción (play, pause, next, prev, volumen)"),
            ("spotify_reproducir", "Pone a reproducir una canción o artista específico"),
            ("spotify_mis_favoritos", "Búsqueda en tu biblioteca de 440 canciones favoritas (favoritos.csv)"),
        ],
        "🌐 Web & DuckDuckGo": [
            ("buscar_en_internet", "Búsqueda en vivo en la web mediante DuckDuckGo"),
            ("leer_pagina_web", "Descarga y extrae texto limpio de cualquier página web"),
        ],
    }

    total_locales = sum(len(v) for v in categorias_locales.values())
    total_mcp = len(mcp_mgr.mcp_tools)
    total_general = total_locales + total_mcp

    servidores_activos = list(mcp_mgr.servers_info.keys())
    desc_servidores = ", ".join(f"{s.capitalize()} ({len([k for k, (srv, _) in mcp_mgr.mcp_tools.items() if srv == s])})" for s in servidores_activos) or "Ninguno"

    tabla = Table(
        title=f"[bold #50fa7b]🛠️  Herramientas Conectadas a Gordito ({total_general} Activas)[/bold #50fa7b]\n[dim]Locales: {total_locales} │ MCP: {total_mcp} [{desc_servidores}][/dim]",
        title_justify="left",
        border_style="#44475a",
        header_style="bold #bd93f9",
        box=box.ROUNDED,
        padding=(0, 1),
    )
    tabla.add_column("Módulo", style="bold cyan", no_wrap=True)
    tabla.add_column("Herramienta", style="bold #50fa7b", no_wrap=True)
    tabla.add_column("Tipo", style="dim", no_wrap=True)
    tabla.add_column("Descripción", style="#f8f8f2")

    coincidencias = 0

    # 1. Herramientas locales
    for cat, tools in categorias_locales.items():
        for t_name, t_desc in tools:
            if filtro_lower:
                match = (filtro_lower in t_name.lower() or 
                         filtro_lower in t_desc.lower() or 
                         filtro_lower in cat.lower() or 
                         filtro_lower == "local")
                if not match:
                    continue
            tabla.add_row(cat, t_name, "Local", t_desc)
            coincidencias += 1

    # 2. Herramientas MCP
    for name, (srv_name, t_obj) in mcp_mgr.mcp_tools.items():
        desc = (getattr(t_obj, "description", "") or "Herramienta MCP").strip().split("\n")[0]
        if len(desc) > 85:
            desc = desc[:82] + "..."

        if "banxico" in srv_name.lower():
            cat = "🏛️ Banxico MCP"
        elif "playwright" in srv_name.lower():
            cat = "🎭 Playwright MCP"
        else:
            cat = f"🔌 {srv_name.capitalize()} MCP"

        if filtro_lower:
            match = (filtro_lower in name.lower() or 
                     filtro_lower in desc.lower() or 
                     filtro_lower in srv_name.lower() or 
                     filtro_lower == "mcp")
            if not match:
                continue

        tabla.add_row(cat, name, f"MCP ({srv_name})", desc)
        coincidencias += 1

    console.print()
    if coincidencias == 0 and filtro_lower:
        console.print(f"[yellow]⚠️ No se encontraron herramientas que coincidan con '[bold]{filtro}[/bold]'.[/yellow]")
        console.print(f"[dim]Escribe [bold green]/tools[/bold green] para ver la lista completa de {total_general} herramientas.[/dim]\n")
        return

    console.print(tabla)
    if filtro_lower:
        console.print(f"[dim]Mostrando {coincidencias} de {total_general} herramientas filtradas por '[bold white]{filtro}[/bold white]'.[/dim]")
    else:
        console.print(f"[dim]Tip: Puedes escribir [bold yellow]/tools <filtro>[/bold yellow] para buscar rápido (ej: [green]/tools spotify[/green], [green]/tools browser[/green], [green]/tools banxico[/green], [green]/tools local[/green]).[/dim]")
    console.print()
