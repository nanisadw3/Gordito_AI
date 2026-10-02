"""
Módulo Central de Gordito (core.py)
Contiene las herramientas locales, gestión MCP y configuración compartida.
"""

import asyncio
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any

import httpx
import ollama
from ddgs import DDGS
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich import box
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table


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

def es_saludo_o_charla(texto: str) -> bool:
    """Detecta si el mensaje del usuario es un saludo básico, despedida, agradecimiento o pregunta de identidad que no requiere herramientas."""
    if not texto:
        return False
    # Remover acentos y puntuación
    clean = texto.lower()
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")]:
        clean = clean.replace(a, b)
    clean = re.sub(r"[^\w\s]", "", clean).strip()
    palabras = clean.split()
    if not palabras:
        return False

    # Identidad y creador
    if any(q in clean for q in [
        "quien es tu creador", "quien te creo", "tu creador", "quien te programo", "quien te hizo",
        "quien eres", "eres gordito", "como te llamas", "que eres", "que modelo eres"
    ]):
        return True

    # Saludos y cortesía exactos
    saludos_exactos = {
        "hola", "buenas", "buen dia", "buenos dias", "buenas tardes", "buenas noches",
        "que tal", "que onda", "que hay", "como estas", "como te va", "como andas",
        "hey", "hi", "hello", "aloha", "saludos", "quiubo", "que hubo",
        "gracias", "muchas gracias", "mil gracias",
        "adios", "hasta luego", "bye", "nos vemos", "chao",
    }
    if clean in saludos_exactos:
        return True

    # Si contiene palabras de saludo y es corto sin verbos de acción externa
    if len(palabras) <= 3:
        if any(w in ["hola", "buenas", "hey", "hi", "hello", "saludos", "onda", "quiubo"] for w in palabras):
            verbos_accion = ["busca", "buscar", "abre", "abrir", "navega", "reproduce", "play", "pon", "lee", "listar", "ejecuta", "crea"]
            if not any(v in clean for v in verbos_accion):
                return True

    return False

RESPUESTA_CREADOR = (
    "Mi creador es **Iñaki Sobera Sotomayor** 🐧.\n\n"
    "Él me programó y diseñó para ser tu asistente personal de inteligencia artificial en Arch Linux, "
    "integrándome con herramientas de sistema, DJ de Spotify, búsqueda web y datos económicos oficiales de Banxico."
)

def es_pregunta_creador(texto: str) -> bool:
    """Detecta si el usuario pregunta quién es el creador, autor o programador de Gordito."""
    if not texto:
        return False
    clean = texto.lower()
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")]:
        clean = clean.replace(a, b)
    clean = re.sub(r"[^\w\s]", " ", clean)
    palabras = clean.split()
    texto_limpio = " ".join(palabras)

    frases_creador = [
        "quien es tu creador", "quien fue tu creador", "quien te creo",
        "quien te programo", "quien te desarrollo", "quien te invento",
        "quien te hizo", "de quien eres", "como se llama tu creador",
        "quien es tu autor", "quien te construyo", "tu creador", "quien te dio vida",
        "quien creo a gordito", "quien desarrollo a gordito", "quien programo a gordito",
        "quien te diseno", "quien te diseño", "quien es tu dueno", "quien es tu padre"
    ]
    if any(f in texto_limpio for f in frases_creador):
        return True
    if "creador" in palabras and any(w in palabras for w in ["quien", "tu", "el", "su", "nombre"]):
        return True
    if "creo" in palabras and any(w in palabras for w in ["quien", "te"]):
        return True
    if "hizo" in palabras and any(w in palabras for w in ["quien", "te"]):
        return True
    if "programo" in palabras and any(w in palabras for w in ["quien", "te"]):
        return True
    return False

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

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_MCP_PATH = os.path.join(_BASE_DIR, "mcp_servers.json")
if not os.path.exists(CONFIG_MCP_PATH):
    CONFIG_MCP_PATH = os.path.expanduser("~/Documents/agente/mcp_servers.json")

CONFIG_TOOLS_PATH = os.path.join(_BASE_DIR, "tools_config.json")

def cargar_config_tools() -> dict:
    """Carga la configuración de herramientas activadas/desactivadas desde tools_config.json."""
    if not os.path.exists(CONFIG_TOOLS_PATH):
        return {"disabled_tools": []}
    try:
        with open(CONFIG_TOOLS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"disabled_tools": []}
            if "disabled_tools" not in data:
                data["disabled_tools"] = []
            return data
    except Exception:
        return {"disabled_tools": []}

def guardar_config_tools(config: dict) -> bool:
    """Guarda la configuración de herramientas en tools_config.json."""
    try:
        with open(CONFIG_TOOLS_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

def herramienta_esta_habilitada(nombre_herramienta: str) -> bool:
    """Verifica si una herramienta específica o su categoría/prefijo está habilitada."""
    cfg = cargar_config_tools()
    deshabilitadas = cfg.get("disabled_tools", [])
    nom_l = nombre_herramienta.lower()
    for d in deshabilitadas:
        dl = d.lower()
        if dl == nom_l:
            return False
        # Permite deshabilitar por prefijo o comodín, ej: 'browser_*', 'browser', 'spotify_*', etc.
        if dl.endswith("*") and nom_l.startswith(dl[:-1]):
            return False
        if nom_l.startswith(dl + "_") or nom_l.startswith(dl + "-"):
            return False
        if dl in ["playwright", "browser"] and (nom_l.startswith("browser_") or nom_l == "playwright"):
            return False
        if dl in ["banxico"] and ("banxico" in nom_l or nom_l in ["tipo_cambio_usd", "inflacion_mexico", "valor_udis", "tasa_interes_banxico", "reservas_internacionales", "consultar_serie_sie"]):
            return False
        if dl in ["spotify"] and (nom_l.startswith("spotify_") or nom_l == "dj_de_codigo"):
            return False
    return True

def alternar_herramienta(objetivo: str, activar: bool = None) -> tuple[bool, str]:
    """
    Enciende o apaga una herramienta o grupo de herramientas.
    Si activar es None, se invierte el estado actual.
    Retorna (nuevo_estado_activo, mensaje_descriptivo).
    """
    cfg = cargar_config_tools()
    deshabilitadas = cfg.get("disabled_tools", [])
    obj_clean = objetivo.strip().lower()

    if not obj_clean:
        return False, "Nombre de herramienta vacío."

    # Mapeos convenientes de grupos
    alias_grupos = {
        "playwright": "playwright",
        "browser": "playwright",
        "navegador": "playwright",
        "banxico": "banxico",
        "spotify": "spotify",
        "musica": "spotify",
        "web": "buscar_en_internet",
        "duckduckgo": "buscar_en_internet",
    }
    target = alias_grupos.get(obj_clean, obj_clean)

    # Revisar si actualmente coincide
    esta_desactivada = any(
        d.lower() == target or
        (d.lower() in ["playwright", "browser"] and target in ["playwright", "browser"]) or
        (d.lower() == "banxico" and target == "banxico") or
        (d.lower() == "spotify" and target == "spotify")
        for d in deshabilitadas
    )

    if activar is None:
        nuevo_estado = esta_desactivada  # Si estaba desactivada, ahora se activa
    else:
        nuevo_estado = bool(activar)

    if nuevo_estado:
        # Habilitar: remover de deshabilitadas
        deshabilitadas = [
            d for d in deshabilitadas 
            if d.lower() != target and not (target in ["playwright", "browser"] and d.lower() in ["playwright", "browser"])
        ]
        cfg["disabled_tools"] = deshabilitadas
        guardar_config_tools(cfg)
        return True, f"Herramienta/Módulo '[bold green]{target}[/bold green]' [bold green]ACTIVADO[/bold green] ✓"
    else:
        # Deshabilitar: agregar si no está
        if not esta_desactivada:
            deshabilitadas.append(target)
            cfg["disabled_tools"] = deshabilitadas
            guardar_config_tools(cfg)
        return False, f"Herramienta/Módulo '[bold red]{target}[/bold red]' [bold red]DESACTIVADO[/bold red] ✗"

SPOTIFY_CSV_PATH = obtener_ruta_favoritos()

# Cargar variables de entorno
DOTENV_PATH = os.path.join(_BASE_DIR, ".env")
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
# 1. Herramientas Locales
# ==========================================

def cambiar_directorio(ruta: str = "~", **kwargs) -> str:
    """Cambia el directorio de trabajo actual (cd). Por ejemplo '..' para ir a la carpeta superior o '~/Documentos'."""
    try:
        r = kwargs.get("path") or kwargs.get("directory") or kwargs.get("dir") or ruta
        ruta_exp = os.path.expanduser(r)
        os.chdir(ruta_exp)
        return f"Directorio de trabajo cambiado a: {os.getcwd()}"
    except Exception as e:
        return f"Error al cambiar de directorio: {e!s}"

def ejecutar_comando(comando: str = "", **kwargs) -> str:
    """Ejecuta un comando en la terminal bash/zsh y devuelve la salida estándar o errores."""
    cmd = kwargs.get("cmd") or kwargs.get("command") or comando
    cmd_strip = cmd.strip()
    if not cmd_strip:
        return "Error: Comando vacío."
    if cmd_strip == "cd" or cmd_strip.startswith("cd "):
        partes = cmd_strip.split(maxsplit=1)
        target = partes[1].strip() if len(partes) > 1 else "~"
        return cambiar_directorio(target)

    try:
        resultado = subprocess.run(
            cmd,
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

def listar_archivos(ruta: str = ".", **kwargs) -> str:
    """Lista los archivos y carpetas en una ruta específica. Por defecto '.' para la carpeta actual."""
    try:
        r = kwargs.get("path") or kwargs.get("directory") or kwargs.get("dir") or ruta
        ruta_exp = os.path.expanduser(r)
        items = os.listdir(ruta_exp)
        if not items:
            return f"La carpeta '{r}' está vacía."
        info = []
        for item in sorted(items):
            full_path = os.path.join(ruta_exp, item)
            tipo = "📁 Carpeta" if os.path.isdir(full_path) else "📄 Archivo"
            info.append(f"{tipo}: {item}")
        return "\n".join(info)
    except Exception as e:
        return f"Error al listar archivos: {e!s}"

def leer_archivo(ruta: str = "", **kwargs) -> str:
    """Lee y devuelve el contenido de un archivo de texto."""
    try:
        r = kwargs.get("path") or kwargs.get("filename") or kwargs.get("file_path") or ruta
        ruta_exp = os.path.expanduser(r)
        with open(ruta_exp, "r", encoding="utf-8") as f:
            contenido = f.read()
        return contenido if contenido else "(Archivo vacío)"
    except Exception as e:
        return f"Error al leer archivo: {e!s}"

def escribir_archivo(ruta: str = "", contenido: str = "", **kwargs) -> str:
    """Crea o sobreescribe un archivo de texto con el contenido especificado."""
    try:
        r = kwargs.get("path") or kwargs.get("filename") or ruta
        c = kwargs.get("content") or kwargs.get("text") or contenido
        ruta_exp = os.path.expanduser(r)
        os.makedirs(os.path.dirname(os.path.abspath(ruta_exp)), exist_ok=True)
        with open(ruta_exp, "w", encoding="utf-8") as f:
            f.write(c)
        return f"Archivo '{r}' guardado correctamente ({len(c)} caracteres)."
    except Exception as e:
        return f"Error al escribir archivo: {e!s}"

def info_sistema(**kwargs) -> str:
    """Devuelve la fecha/hora actual, usuario, sistema operativo y directorio de trabajo."""
    return (
        f"Fecha y Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Usuario: {os.environ.get('USER', 'desconocido')}\n"
        f"Directorio actual: {os.getcwd()}\n"
        f"Plataforma: {obtener_nombre_os()} ({sys.platform})"
    )

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
    """Descarga una página web y devuelve su contenido de texto limpio."""
    u = url or kwargs.get("link") or kwargs.get("uri") or kwargs.get("target") or kwargs.get("href") or kwargs.get("page_url") or ""
    u = str(u).strip()
    if not u:
        return "Error: No se especificó la URL de la página web a leer."
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            resp = client.get(u, headers=headers)
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
        return f"Error al leer página web {u}: {e!s}"

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
            return f"Error al consultar Spotify: {e!s}"
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
            return f"Error al controlar Spotify: {e!s}"
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
                return f"Error al controlar Spotify con playerctl: {e!s}"

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
                    return f"Error ejecutando D-Bus: {e!s}"

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
        return f"Error al leer favoritos.csv: {e!s}"

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
        return f"Error al leer favoritos.csv: {e!s}"

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

def listar_herramientas_disponibles(**kwargs) -> str:
    """Devuelve la lista de herramientas disponibles en el sistema Gordito y servidores MCP."""
    return (
        "HERRAMIENTAS ACTIVAS:\n"
        "- listar_archivos: Listar archivos y directorios locales\n"
        "- cambiar_directorio: Cambiar de carpeta (cd)\n"
        "- leer_archivo / escribir_archivo: Leer o escribir archivos\n"
        "- ejecutar_comando: Ejecutar comandos de terminal en Arch Linux\n"
        "- info_sistema: Fecha, hora y datos del sistema\n"
        "- buscar_en_internet / leer_pagina_web: Búsqueda web en vivo\n"
        "- dj_de_codigo / spotify_control / spotify_estado: Control de Spotify\n"
        "- Playwright MCP: browser_navigate, browser_click, browser_type, browser_snapshot, etc.\n"
        "- Banxico MCP: tipo_cambio_usd, inflacion_mexico, valor_udis, tasa_interes_banxico,\n"
        "  reservas_internacionales, consultar_serie_sie (datos oficiales del Banco de México)"
    )

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
    "listar_herramientas_disponibles": listar_herramientas_disponibles,
}

def camel_to_snake(name: str) -> str:
    """Convierte cadenas camelCase o PascalCase a snake_case."""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


TOOL_ALIASES = {
    # Herramientas de descubrimiento / lista
    "browser_list": "listar_herramientas_disponibles",
    "list_tools": "listar_herramientas_disponibles",
    "tools": "listar_herramientas_disponibles",
    "tools_list": "listar_herramientas_disponibles",
    "herramientas": "listar_herramientas_disponibles",
    "listar_herramientas": "listar_herramientas_disponibles",

    # Listar archivos y directorios
    "list_files": "listar_archivos",
    "list_dir": "listar_archivos",
    "list_directory": "listar_archivos",
    "listar_contenido": "listar_archivos",
    "listar_directorio": "listar_archivos",
    "listar_carpeta": "listar_archivos",
    "listar": "listar_archivos",
    "ls": "listar_archivos",
    "dir": "listar_archivos",
    "listdir": "listar_archivos",

    # Cambiar de directorio
    "change_directory": "cambiar_directorio",
    "change_dir": "cambiar_directorio",
    "cambiardirectorio": "cambiar_directorio",
    "cambiar_dir": "cambiar_directorio",
    "cd": "cambiar_directorio",

    # Archivos
    "read_file": "leer_archivo",
    "leer": "leer_archivo",
    "cat": "leer_archivo",
    "write_file": "escribir_archivo",
    "escribir": "escribir_archivo",

    # Comandos de sistema
    "run_command": "ejecutar_comando",
    "execute_command": "ejecutar_comando",
    "ejecutar": "ejecutar_comando",
    "comando": "ejecutar_comando",
    "bash": "ejecutar_comando",
    "shell": "ejecutar_comando",

    # Búsqueda web
    "search_internet": "buscar_en_internet",
    "search_web": "buscar_en_internet",
    "web_search": "buscar_en_internet",
    "buscar_internet": "buscar_en_internet",
    "buscar_en_la_web": "buscar_en_internet",
    "duckduckgo": "buscar_en_internet",
    "ddg": "buscar_en_internet",
    "search": "buscar_en_internet",
    "buscar_web": "buscar_en_internet",
    "buscar": "buscar_en_internet",
    "google": "buscar_en_internet",
    "fetch_url": "leer_pagina_web",
    "read_webpage": "leer_pagina_web",
    "read_page": "leer_pagina_web",
    "leer_web": "leer_pagina_web",

    # Información del sistema
    "get_system_info": "info_sistema",
    "system_info": "info_sistema",
    "info": "info_sistema",
    "sysinfo": "info_sistema",
    "datetime": "info_sistema",
    "date": "info_sistema",
    "time": "info_sistema",
    "hora": "info_sistema",
    # Banxico MCP
    "tipo_de_cambio": "tipo_cambio_usd",
    "tipo_cambio": "tipo_cambio_usd",
    "tipocambio": "tipo_cambio_usd",
    "dolar": "tipo_cambio_usd",
    "precio_dolar": "tipo_cambio_usd",
    "dolar_fix": "tipo_cambio_usd",
    "banxico_tipo_cambio": "tipo_cambio_usd",
    "banxico_tipo_cambio_usd": "tipo_cambio_usd",
    "consultar_tipo_cambio": "tipo_cambio_usd",
    "get_exchange_rate": "tipo_cambio_usd",
    "exchange_rate": "tipo_cambio_usd",

    "inflacion": "inflacion_mexico",
    "inpc": "inflacion_mexico",
    "banxico_inflacion": "inflacion_mexico",

    "udis": "valor_udis",
    "udi": "valor_udis",
    "valor_udi": "valor_udis",

    "tasa_interes": "tasa_interes_banxico",
    "tiie": "tasa_interes_banxico",
    "tiie_28": "tasa_interes_banxico",
    "tasa_objetivo": "tasa_interes_banxico",

    "reservas": "reservas_internacionales",
    "reserva_internacional": "reservas_internacionales",
}

def normalizar_nombre_herramienta(nombre: str) -> str:
    """Normaliza nombres en inglés, camelCase o alias a la función real correspondiente."""
    if not nombre:
        return ""
    raw = nombre.strip()
    if raw in LOCAL_TOOL_FUNCTIONS:
        return raw

    # Quitar posibles prefijos de servidor MCP o namespaces (ej: banxico_tipo_cambio, banxico::tipo_cambio)
    for pref in ["banxico_", "banxico::", "banxico.", "playwright_", "playwright::"]:
        if raw.startswith(pref):
            raw = raw[len(pref):]
            break

    # 1. Chequeo directo en alias
    low = raw.lower()
    if low in TOOL_ALIASES:
        return TOOL_ALIASES[low]

    # 2. Conversión camelCase -> snake_case
    snake = camel_to_snake(raw)
    if snake in LOCAL_TOOL_FUNCTIONS:
        return snake
    if snake in TOOL_ALIASES:
        return TOOL_ALIASES[snake]

    # 3. Sin guiones bajos
    no_under = snake.replace("_", "")
    if no_under in TOOL_ALIASES:
        return TOOL_ALIASES[no_under]

    # 4. Búsqueda por palabras clave semánticas
    if any(k in snake for k in ["list", "ls", "dir", "contenido", "archivo", "carpeta"]):
        if "cambiar" not in snake and "change" not in snake and "cd" not in snake:
            return "listar_archivos"
    if any(k in snake for k in ["cambiar", "chdir", "cd"]):
        return "cambiar_directorio"

    if any(k in snake for k in ["tipo_cambio", "tipocambio", "dolar"]):
        return "tipo_cambio_usd"
    if "inflacion" in snake or "inpc" in snake:
        return "inflacion_mexico"
    if "udi" in snake:
        return "valor_udis"
    if "tiie" in snake or "tasa" in snake:
        return "tasa_interes_banxico"
    if "reserva" in snake:
        return "reservas_internacionales"

    return snake


# ==========================================
# 2. Gestor MCP
# ==========================================

class MCPManager:
    def __init__(self, config_path: str = CONFIG_MCP_PATH):
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
        except Exception:
            return {}

    async def conectar_servidor(self, nombre: str, cfg: dict = None) -> bool:
        """Conecta un servidor MCP específico si está habilitado y configurado."""
        if cfg is None:
            servidores = self.cargar_configuracion()
            cfg = servidores.get(nombre)
            if not cfg:
                return False

        if not cfg.get("enabled", True):
            return False

        # Verificar si el servidor fue desactivado en tools_config.json
        if not herramienta_esta_habilitada(nombre):
            self.servers_info[nombre] = {
                "descripcion": cfg.get("description", "Servidor MCP"),
                "herramientas": [],
                "estado": "Desactivado por usuario (/config)"
            }
            return False

        command = cfg.get("command")
        if command:
            expanded_cmd = os.path.expanduser(command)
            if ("/" in command or "\\" in command) and not os.path.exists(expanded_cmd):
                self.servers_info[nombre] = {
                    "descripcion": cfg.get("description", "Servidor MCP"),
                    "herramientas": [],
                    "estado": f"No disponible (ruta '{command}' no existe)"
                }
                return False
            command = expanded_cmd
            if not os.path.isabs(command):
                resolved = shutil.which(command)
                if resolved:
                    command = resolved
                else:
                    self.servers_info[nombre] = {
                        "descripcion": cfg.get("description", "Servidor MCP"),
                        "herramientas": [],
                        "estado": f"Comando '{command}' no encontrado en PATH"
                    }
                    return False

        args = [os.path.expanduser(a) if isinstance(a, str) else a for a in cfg.get("args", [])]
        # Silenciar notificaciones de npm/npx
        if (command == "npx" or (isinstance(command, str) and command.endswith("/npx"))) and "--silent" not in args:
            args = ["--silent"] + args

        env_vars = dict(os.environ)
        env_vars["npm_config_loglevel"] = "error"
        env_vars["npm_config_update_notifier"] = "false"
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
            return True
        except Exception as err:
            self.servers_info[nombre] = {
                "descripcion": cfg.get("description", "Servidor MCP"),
                "herramientas": [],
                "estado": f"Error: {err}"
            }
            return False

    async def conectar_servidores(self):
        """Conecta todos los servidores configurados que se encuentren habilitados."""
        servidores = self.cargar_configuracion()
        for nombre, cfg in servidores.items():
            await self.conectar_servidor(nombre, cfg)

    async def desconectar_servidor(self, nombre: str):
        """Desconecta y retira las herramientas de un servidor MCP en tiempo de ejecución."""
        if nombre in self.sessions:
            # Retirar herramientas asociadas
            self.mcp_tools = {k: v for k, v in self.mcp_tools.items() if v[0] != nombre}
            try:
                del self.sessions[nombre]
            except Exception:
                pass
            if nombre in self.servers_info:
                self.servers_info[nombre]["estado"] = "Desactivado por usuario (/config)"
                self.servers_info[nombre]["herramientas"] = []

    async def ejecutar_herramienta(self, tool_name: str, arguments: dict) -> str:
        if tool_name not in self.mcp_tools:
            return f"Error: Herramienta MCP '{tool_name}' no encontrada."
        server_name, _ = self.mcp_tools[tool_name]
        session = self.sessions.get(server_name)
        if not session:
            return f"Error: Servidor '{server_name}' no disponible."

        args_clean = dict(arguments or {})
        if tool_name == "tipo_cambio_usd":
            year = args_clean.pop("year", None) or args_clean.pop("anio", None) or args_clean.pop("año", None)
            if year:
                args_clean.setdefault("fecha_inicio", f"{year}-01-01")
                args_clean.setdefault("fecha_fin", f"{year}-12-31")
            elif "fecha" in args_clean and "fecha_inicio" not in args_clean:
                f_val = str(args_clean.pop("fecha")).strip()
                if len(f_val) == 4 and f_val.isdigit():
                    args_clean["fecha_inicio"] = f"{f_val}-01-01"
                    args_clean["fecha_fin"] = f"{f_val}-12-31"
                else:
                    args_clean["fecha_inicio"] = f_val

        if tool_name.startswith("browser_"):
            url_target = args_clean.get("url", "")
            if "banxico.org.mx" in url_target:
                return (
                    "Aviso: El portal web de Banxico bloquea navegadores web automatizados con 403 Forbidden. "
                    "Usa la herramienta del MCP de Banxico 'tipo_cambio_usd' (con fecha_inicio y fecha_fin) "
                    "que consume la API oficial del SIE directamente."
                )

        try:
            res = await session.call_tool(tool_name, arguments=args_clean)
            salidas = []
            for content in res.content:
                if hasattr(content, "text"):
                    salidas.append(content.text)
                else:
                    salidas.append(str(content))
            texto_salida = "\n".join(salidas) if salidas else "Herramienta ejecutada sin salida."

            # Optimización para LLMs: si Banxico devuelve cientos de observaciones históricas,
            # condensamos la respuesta con estadísticas para evitar alucinaciones o desbordes en el modelo.
            if "observaciones" in texto_salida:
                try:
                    data = json.loads(texto_salida)
                    if isinstance(data, dict) and "observaciones" in data:
                        obs = data["observaciones"]
                        if isinstance(obs, list) and len(obs) > 15:
                            valores = []
                            for o in obs:
                                try:
                                    valores.append((float(str(o.get("dato", "")).replace(",", "")), o.get("fecha", "")))
                                except Exception:
                                    pass
                            if valores:
                                min_v, min_f = min(valores, key=lambda x: x[0])
                                max_v, max_f = max(valores, key=lambda x: x[0])
                                prom = round(sum(v[0] for v in valores) / len(valores), 4)
                                resumen = {
                                    "indicador": data.get("indicador", "Datos Banxico"),
                                    "serie_id": data.get("serie_id", ""),
                                    "unidad": "Pesos por dólar" if "tipo_cambio" in tool_name else data.get("unidad", ""),
                                    "total_dias_habiles_registrados": len(obs),
                                    "inicio_periodo": obs[0],
                                    "fin_periodo": obs[-1],
                                    "minimo": {"valor": min_v, "fecha": min_f},
                                    "maximo": {"valor": max_v, "fecha": max_f},
                                    "promedio": prom,
                                    "muestra_observaciones": obs[:3] + obs[-3:],
                                }
                                return json.dumps(resumen, ensure_ascii=False, indent=2)
                except Exception:
                    pass

            return texto_salida
        except Exception as e:
            return f"Error en herramienta MCP {tool_name}: {e!s}"

    def obtener_esquemas_ollama(self, solo_habilitadas: bool = True) -> list[dict]:
        esquemas = []
        for name, (_, t) in self.mcp_tools.items():
            if solo_habilitadas and not herramienta_esta_habilitada(name):
                continue
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


def modelo_soporta_tools(modelo_name: str) -> bool:
    """Verifica si un modelo de Ollama soporta el llamado a herramientas (function/tool calling)."""
    try:
        info = ollama.show(modelo_name)
        caps = getattr(info, "capabilities", []) or []
        tmpl = getattr(info, "template", "") or ""
        if "tools" in caps or ".Tools" in tmpl or "<tools>" in tmpl:
            return True
        return False
    except Exception:
        return False


def obtener_modelos_instalados(solo_con_tools: bool = True):
    """Devuelve los modelos de Ollama instalados, filtrando por defecto solo aquellos que soportan tools."""
    try:
        modelos_info = ollama.list()
        candidatos = [m for m in modelos_info.models if "embed" not in m.model]
        if not solo_con_tools:
            return candidatos
        return [m for m in candidatos if modelo_soporta_tools(m.model)]
    except Exception:
        return []


class ToolCallFunction:
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = arguments or {}


class SyntheticToolCall:
    def __init__(self, name: str, arguments: dict):
        self.function = ToolCallFunction(name, arguments)


def extraer_tool_calls_fallback(content: str, herramientas_validas: set) -> list:
    """Extrae llamadas a herramientas si el modelo emitió JSON o tags <tool_call> en el texto."""
    if not content:
        return []
    llamadas = []

    def resolver_nombre(raw_name: str):
        if not raw_name:
            return None
        if raw_name in herramientas_validas:
            return raw_name
        norm = normalizar_nombre_herramienta(raw_name)
        if norm in herramientas_validas:
            return norm
        return None

    # 1. Tags explícitos <tool_call>...</tool_call>
    tc_matches = re.findall(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL)
    for block in tc_matches:
        try:
            data = json.loads(block.strip())
            if isinstance(data, dict):
                nom_resuelto = resolver_nombre(data.get("name"))
                if nom_resuelto:
                    llamadas.append(SyntheticToolCall(nom_resuelto, data.get("arguments") or {}))
        except Exception:
            pass
    if llamadas:
        return llamadas

    # 2. Scanner JSON buscando objetos {"name": "...", "arguments": ...}
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(content):
        idx = content.find('{', pos)
        if idx == -1:
            break
        try:
            obj, end_idx = decoder.raw_decode(content, idx)
            if isinstance(obj, dict):
                nom_resuelto = resolver_nombre(obj.get("name"))
                if nom_resuelto:
                    llamadas.append(SyntheticToolCall(nom_resuelto, obj.get("arguments") or {}))
            pos = end_idx
        except Exception:
            pos = idx + 1

    return llamadas


def obtener_todas_las_herramientas(mcp_mgr: MCPManager, solo_habilitadas: bool = True) -> list[Any]:
    if solo_habilitadas:
        herramientas = [fn for name, fn in LOCAL_TOOL_FUNCTIONS.items() if herramienta_esta_habilitada(name)]
    else:
        herramientas = list(LOCAL_TOOL_FUNCTIONS.values())
    esquemas_mcp = mcp_mgr.obtener_esquemas_ollama(solo_habilitadas=solo_habilitadas)
    herramientas.extend(esquemas_mcp)
    return herramientas


def enrutar_herramientas_para_consulta(texto_usuario: str, mcp_mgr: MCPManager) -> list[Any]:
    """
    Selecciona de forma inteligente y especializada el subconjunto de herramientas
    relevantes para la consulta del usuario. Esto evita la 'distracción de herramientas'
    en modelos locales compactos (7B), mejorando drásticamente la precisión y velocidad.
    """
    if not texto_usuario:
        return obtener_todas_las_herramientas(mcp_mgr)

    txt = texto_usuario.lower()
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")]:
        txt = txt.replace(a, b)

    todas = obtener_todas_las_herramientas(mcp_mgr)

    # Identificar dominios en la consulta
    es_banxico = any(k in txt for k in [
        "dolar", "tipo de cambio", "tipo_cambio", "divisa", "peso", "pesos",
        "usd", "mxn", "cotizacion", "fix", "liquidacion", "inflacion", "inpc",
        "udi", "udis", "tiie", "tasa de interes", "tasa objetivo", "tasas",
        "fondeo", "reserva internacional", "reservas internacionales",
        "banxico", "banco de mexico", "sie"
    ])

    es_spotify = any(k in txt for k in [
        "spotify", "cancion", "musica", "dj", "flow", "reproduce", "play",
        "pausa", "volumen", "artista", "playlist", "favoritos", "tema", "pista"
    ])

    es_sistema = any(k in txt for k in [
        "archivo", "carpeta", "directorio", "terminal", "comando", "bash",
        "zsh", "listar", "leer archivo", "escribir archivo", "cd", "ls", "grep",
        "proceso", "sistema", "memoria ram", "disco", "cpu"
    ])

    es_browser = any(k in txt for k in [
        "navegador", "browser", "playwright", "screenshot", "captura de pantalla",
        "click", "clic", "formulario", "dom", "html", "pagina web", "sitio web"
    ]) or ("http://" in txt or "https://" in txt)

    es_busqueda = any(k in txt for k in [
        "buscar", "busca", "busqueda", "google", "internet", "intenret", "duckduckgo", "web"
    ])

    # Regla de oro: Para Banxico / economía mexicana, NUNCA enviar herramientas del navegador
    if es_banxico and not es_browser:
        herramientas_filtradas = []
        for h in todas:
            nombre = ""
            if callable(h):
                nombre = getattr(h, "__name__", "")
            elif isinstance(h, dict) and "function" in h:
                nombre = h["function"].get("name", "")

            if any(k in nombre for k in [
                "tipo_cambio", "banxico", "inflacion", "udis", "tasa", "reservas", "sie", "info_sistema"
            ]):
                herramientas_filtradas.append(h)

        if herramientas_filtradas:
            return herramientas_filtradas

    # Si es solo Spotify y no browser/banxico
    if es_spotify and not (es_banxico or es_browser):
        herramientas_filtradas = [
            h for h in todas if (
                callable(h) and any(k in getattr(h, "__name__", "") for k in ["spotify", "dj_de_codigo"])
            )
        ]
        if herramientas_filtradas:
            return herramientas_filtradas

    # Si es solo archivos locales
    if es_sistema and not (es_banxico or es_browser or es_spotify):
        herramientas_filtradas = [
            h for h in todas if (
                callable(h) and any(k in getattr(h, "__name__", "") for k in ["archivo", "directorio", "comando", "sistema"])
            )
        ]
        if herramientas_filtradas:
            return herramientas_filtradas

    # Si es explícitamente búsqueda web (y no banxico, browser automation ni archivos)
    if es_busqueda and not (es_banxico or es_browser or es_spotify or es_sistema):
        herramientas_filtradas = [
            h for h in todas if (
                callable(h) and any(k in getattr(h, "__name__", "") for k in ["buscar_en_internet", "leer_pagina_web", "info_sistema"])
            )
        ]
        if herramientas_filtradas:
            return herramientas_filtradas

    # Si es explícitamente navegador
    if es_browser and not es_banxico:
        herramientas_filtradas = [
            h for h in todas if (
                isinstance(h, dict) and h.get("function", {}).get("name", "").startswith("browser_")
            ) or (callable(h) and "web" in getattr(h, "__name__", ""))
        ]
        if herramientas_filtradas:
            return herramientas_filtradas

    return todas


def inferir_llamada_banxico_fallback(texto_usuario: str) -> tuple[str | None, dict]:
    """
    Deduce de forma determinista la herramienta oficial de Banxico y los parámetros
    apropiados cuando un modelo local (7B) duda o devuelve texto pidiendo fechas
    en vez de ejecutar la herramienta.
    """
    if not texto_usuario:
        return None, {}

    txt = texto_usuario.lower()
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")]:
        txt = txt.replace(a, b)

    m_year = re.search(r"\b(19\d\d|20\d\d)\b", txt)
    year = m_year.group(1) if m_year else None

    # 1. Tipo de cambio / Dólar USD/MXN
    if any(k in txt for k in ["dolar", "tipo de cambio", "tipo_cambio", "cambio", "usd", "mxn", "divisa", "cotizacion"]):
        if year:
            return "tipo_cambio_usd", {"fecha_inicio": f"{year}-01-01", "fecha_fin": f"{year}-12-31"}
        return "tipo_cambio_usd", {}

    # 2. Inflación / INPC
    if any(k in txt for k in ["inflacion", "inpc", "precios"]):
        return "inflacion_mexico", {"tipo": "anual"}

    # 3. UDIS
    if any(k in txt for k in ["udi", "udis"]):
        return "valor_udis", {}

    # 4. Tasa de interés / TIIE
    if any(k in txt for k in ["tasa", "tiie", "fondeo"]):
        return "tasa_interes_banxico", {}

    # 5. Reservas internacionales
    if any(k in txt for k in ["reserva", "reservas"]):
        return "reservas_internacionales", {}

    return None, {}


def inferir_llamada_busqueda_fallback(texto_usuario: str) -> tuple[str | None, dict]:
    """
    Deduce si el usuario pidió explícitamente buscar en internet y extrae la consulta
    de búsqueda si un modelo local (7B) duda o responde que no puede navegar.
    """
    if not texto_usuario:
        return None, {}

    clean = texto_usuario.strip().lower()
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")]:
        clean = clean.replace(a, b)

    es_pedido_busqueda = any(k in clean for k in ["buscar", "busca", "googlea", "investiga", "rastrea"]) and any(
        k in clean for k in ["internet", "intenret", "web", "google", "duckduckgo", "linea", "online", "red"]
    )
    if not es_pedido_busqueda:
        return None, {}

    q = re.sub(
        r"^(?:puedes|podes|podrias|favor de|por favor)?\s*(?:buscar|busca|buscame|investiga|googlea)\s+(?:en\s+(?:internet|la\s+web|google|duckduckgo|linea|intenret)\s+)?(?:sobre\s+|acerca\s+de\s+)?",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    q = q.rstrip("?!.¿¡ ")
    if q:
        return "buscar_en_internet", {"consulta": q}
    return None, {}


SYSTEM_PROMPT_GORDITO = """<identity>
Eres GORDITO (gprdito), el pingüino Tux y asistente de Inteligencia Artificial personal de Iñaki.
Vives en su computadora (Arch Linux) y estás a su total servicio ejecutándote localmente con Ollama.

REGLAS DE IDENTIDAD ABSOLUTAS:
1. Tu único nombre es GORDITO. Si te preguntan "¿eres gordito?" o "¿quién eres?", confirma alegremente que sí, que tu nombre oficial es Gordito.
2. NUNCA digas que te llamas Claude ni que fuiste creado por Anthropic. Tampoco digas que eres ChatGPT ni OpenAI.
3. Si te preguntan "qué modelo de IA eres", responde con orgullo: "Soy Gordito, tu asistente local potenciado por el modelo Qwen en Ollama".
4. Si te preguntan "¿quién es tu creador?", "¿quién te creó?", "¿quién te programó?" o similar, responde clara y directamente con orgullo: "Mi creador es Iñaki Sobera Sotomayor". NUNCA respondas con bloques JSON ni alucines nombres de herramientas falsas como DialoGPT.
5. Tu usuario se llama Iñaki. Reconócelo siempre con simpatía, lealtad y humor ameno.
6. Para preguntas generales, saludos o conversación cotidiana, responde en texto normal en español sin emitir JSON ni invocar herramientas inexistentes.
</identity>

Tienes acceso a herramientas poderosas:
1. SISTEMA Y ARCHIVOS (LOCAL):
   - `listar_archivos`: Lista los archivos y carpetas del directorio actual o de cualquier ruta en la computadora. ÚSALA SIEMPRE para explorar el sistema local.
   - `cambiar_directorio`, `leer_archivo`, `escribir_archivo`, `ejecutar_comando`, `info_sistema`.
2. SPOTIFY, MÚSICA & DJ PERSONAL:
   - `dj_de_codigo`: Selecciona la canción ideal de sus 440 favoritos de Spotify y ajusta el volumen según su estado (modos: 'flow', 'hacker', 'chill', 'energia').
   - `spotify_estado`, `spotify_control`, `spotify_reproducir`, `spotify_mis_favoritos`.
3. INTERNET EN VIVO:
   - `buscar_en_internet`: Buscar noticias, datos en tiempo real o información actualizada.
   - `leer_pagina_web`: Leer el texto de cualquier URL.
4. NAVEGADOR WEB (PLAYWRIGHT MCP):
   - Herramientas `browser_*`: Control de un navegador web para interactuar con sitios de internet.
5. DATOS ECONÓMICOS OFICIALES DE MÉXICO (BANXICO MCP):
   - `tipo_cambio_usd`: Tipo de cambio oficial USD/MXN (FIX y liquidación DOF).
   - `inflacion_mexico`: Inflación oficial del INPC, mensual o anual.
   - `valor_udis`: Valor oficial de las Unidades de Inversión.
   - `tasa_interes_banxico`: TIIE a 28 días y tasa objetivo de política monetaria.
   - `reservas_internacionales`: Saldo de la reserva internacional, en millones de dólares.
   - `consultar_serie_sie`: Cualquier otra serie del catálogo SIE por su identificador.

REGLAS CRÍTICAS DE EJECUCIÓN (¡MUY IMPORTANTE!):
1. PROHIBIDO USAR HERRAMIENTAS EN SALUDOS Y CHARLA INFORMAL: Si el usuario únicamente saluda (ej: "Hola", "Buenas", "Qué onda", "¿Cómo estás?"), agradece, o bromea, NUNCA invoques herramientas. NUNCA abras el navegador ni navegues a example.com ni a ningún sitio web sin una orden explícita del usuario. Responde de forma amable, simpática y conversacional preguntando en qué le puedes colaborar.
2. ARCHIVOS LOCALES: Para consultar archivos, directorios o carpetas en la computadora, USA EXCLUSIVAMENTE 'listar_archivos' (o 'ejecutar_comando'). NUNCA uses herramientas del navegador ('browser_*') para revisar archivos locales.
3. DATOS ECONÓMICOS DE MÉXICO: Para tipo de cambio, inflación, UDIS, tasas de interés o reservas internacionales, USA SIEMPRE las herramientas de Banxico. NUNCA uses 'buscar_en_internet' ni 'browser_*' para esos datos: Banxico es la fuente primaria y devuelve la cifra oficial con su fecha de corte y el identificador de la serie. Al responder, menciona siempre la fecha y la serie.
4. EJECUCIÓN DIRECTA: NUNCA le pidas al usuario que ejecute la herramienta ni escribas el bloque JSON {"name": ...} como texto. Invoca la herramienta directamente para que se ejecute de inmediato cuando la tarea realmente lo requiera.
5. Responde de forma concisa, directa y en español a Iñaki tras ejecutar las herramientas."""


def obtener_system_prompt_gordito() -> str:
    """Genera el system prompt de Gordito con la fecha y hora actual del sistema."""
    ahora = datetime.now()
    fecha_str = ahora.strftime("%Y-%m-%d")
    return (
        f"{SYSTEM_PROMPT_GORDITO}\n\n"
        f"CONTEXTO TEMPORAL:\n"
        f"- El año actual es {ahora.year}. Hoy es exactamente {fecha_str}.\n"
        f"- Si el usuario pregunta por datos de 'hoy', 'ahora' o 'actual', utiliza siempre el año {ahora.year} y la fecha actual ({fecha_str})."
    )


def generar_prompt_sintesis(ultimo_mensaje_usuario: str, herramientas_ejecutadas: list[str]) -> str:
    """
    Genera un prompt de síntesis contextualizado y preciso para Ollama
    tras la ejecución de herramientas, evitando alucinaciones cruzadas y sesgos.
    """
    herramientas_set = set(herramientas_ejecutadas)
    es_banxico = any(h in herramientas_set for h in [
        "tipo_cambio_usd", "inflacion_mexico", "valor_udis",
        "tasa_interes_banxico", "reservas_internacionales", "consultar_serie_sie"
    ])
    es_browser = any(h.startswith("browser_") for h in herramientas_set)
    es_archivos = any(h in herramientas_set for h in [
        "listar_archivos", "leer_archivo", "escribir_archivo", "ejecutar_comando", "cambiar_directorio"
    ])
    es_spotify = any(h in herramientas_set for h in [
        "dj_de_codigo", "spotify_control", "spotify_reproducir", "spotify_estado"
    ])
    es_web = any(h in herramientas_set for h in [
        "buscar_en_internet", "leer_pagina_web"
    ])

    if es_banxico:
        return (
            f"Por favor responde a Iñaki en español de forma conversacional, clara y concisa "
            f"con los datos económicos oficiales obtenidos para su consulta: '{ultimo_mensaje_usuario}'. "
            f"Menciona la cifra oficial y su fecha de corte. Si la consulta involucró un rango o año completo, "
            f"menciona el promedio y los valores inicial y de cierre del periodo. "
            f"No inventes datos ni emitas bloques JSON."
        )
    elif es_web:
        return (
            f"Por favor responde a Iñaki en español de forma conversacional, clara y bien estructurada "
            f"con la información real encontrada en la web para su consulta: '{ultimo_mensaje_usuario}'. "
            f"Resume los datos y fuentes principales sin inventar información no encontrada ni emitir bloques JSON."
        )
    elif es_browser:
        return (
            f"Por favor responde a Iñaki en español de forma conversacional, breve y amigable, "
            f"confirmando la acción realizada en el navegador para su petición: '{ultimo_mensaje_usuario}'. "
            f"Responde ÚNICAMENTE sobre esto. No menciones cotizaciones, tipo de cambio ni temas ajenos. "
            f"No emitas bloques JSON ni esquemas de código."
        )
    elif es_spotify:
        return (
            f"Por favor responde a Iñaki con estilo alegre y musical, confirmando la acción de Spotify "
            f"para su petición: '{ultimo_mensaje_usuario}'. Sé breve y amigable."
        )
    elif es_archivos:
        return (
            f"Por favor responde a Iñaki en español de forma clara y directa con los resultados "
            f"del sistema de archivos o comando ejecutado para: '{ultimo_mensaje_usuario}'. "
            f"Sé conciso y no agregues explicaciones redundantes ni bloques JSON."
        )
    else:
        return (
            f"Por favor responde a Iñaki en español de forma conversacional, clara y directa "
            f"atendiendo ÚNICAMENTE a su petición: '{ultimo_mensaje_usuario}'. "
            f"Resume los resultados obtenidos sin inventar temas no solicitados ni emitir bloques JSON."
        )


def obtener_lineas_avatar(emocion: str = "normal", width: int = 15) -> list[str]:
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

def imprimir_banner_gordito(modelo_actual: str, total_mcp: int = 0, subtitulo: str = "Root Shell", emocion: str = "auto", servidores_activos: list = None):
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

    if servidores_activos is not None:
        mcp_label = " + ".join([s.capitalize() for s in servidores_activos]) if servidores_activos else "Inactivo"
    else:
        mcp_label = "Inactivo"
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
        {"role": "system", "content": obtener_system_prompt_gordito()},
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

        # Si el modelo no pide más herramientas, ha redactado su informe final
        if not tool_calls:
            await renderizar_streaming_panel(
                mensaje_modelo.content or "Misión concluida sin observaciones adicionales.",
                console,
                modelo=f"{modelo} · Misión Cumplida"
            )
            return

        mensaje_modelo.content = ""

        # Ejecutar las herramientas solicitadas en este paso
        for tool_call in tool_calls:
            raw_nombre = tool_call.function.name if hasattr(tool_call, "function") else tool_call["function"]["name"]
            nombre = normalizar_nombre_herramienta(raw_nombre)
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

    total_habilitadas = 0
    for cat, tools in categorias_locales.items():
        for t_name, _ in tools:
            if herramienta_esta_habilitada(t_name):
                total_habilitadas += 1
    for name, _ in mcp_mgr.mcp_tools.items():
        if herramienta_esta_habilitada(name):
            total_habilitadas += 1

    tabla = Table(
        title=f"[bold #50fa7b]🛠️  Herramientas Conectadas a Gordito ({total_habilitadas}/{total_general} Habilitadas)[/bold #50fa7b]\n[dim]Locales: {total_locales} │ MCP: {total_mcp} [{desc_servidores}][/dim]",
        title_justify="left",
        border_style="#44475a",
        header_style="bold #bd93f9",
        box=box.ROUNDED,
        padding=(0, 1),
    )
    tabla.add_column("Módulo", style="bold cyan", no_wrap=True)
    tabla.add_column("Herramienta", style="bold #50fa7b", no_wrap=True)
    tabla.add_column("Estado", no_wrap=True)
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
            activa = herramienta_esta_habilitada(t_name)
            estado_badge = "[bold green]ON[/bold green]" if activa else "[bold red]OFF[/bold red]"
            nom_display = t_name if activa else f"[dim strikethrough]{t_name}[/dim strikethrough]"
            tabla.add_row(cat, nom_display, estado_badge, "Local", t_desc)
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

        activa = herramienta_esta_habilitada(name)
        estado_badge = "[bold green]ON[/bold green]" if activa else "[bold red]OFF[/bold red]"
        nom_display = name if activa else f"[dim strikethrough]{name}[/dim strikethrough]"
        tabla.add_row(cat, nom_display, estado_badge, f"MCP ({srv_name})", desc)
        coincidencias += 1

    console.print()
    if coincidencias == 0 and filtro_lower:
        console.print(f"[yellow]⚠️ No se encontraron herramientas que coincidan con '[bold]{filtro}[/bold]'.[/yellow]")
        console.print("[dim]Escribe [bold green]/tools[/bold green] para ver la lista completa o usa [bold green]/config[/bold green] para encender/apagar.[/dim]\n")
        return

    console.print(tabla)
    if filtro_lower:
        console.print(f"[dim]Mostrando {coincidencias} herramientas filtradas por '[bold white]{filtro}[/bold white]'. Usa [bold green]/config[/bold green] para activar/desactivar.[/dim]")
    else:
        console.print("[dim]Tip: Usa [bold yellow]/config[/bold yellow] para encender o apagar tools (ej: [green]/config off playwright[/green] o [green]/config on playwright[/green]).[/dim]")
    console.print()
