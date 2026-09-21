# 🤖 Gordito (gprdito) - Asistente Autónomo Local (macOS & Arch Linux)

Agente de IA local potenciado por **Ollama**, con acceso directo a herramientas del sistema, **Internet en vivo**, DJ personal de **Spotify** (vía AppleScript en macOS y MPRIS/`playerctl` en Arch Linux) y soporte para servidores **MCP** (Model Context Protocol).

---

## 🎨 Dos Interfaces Disponibles

Ahora tienes dos formas de interactuar con Gordito según lo que busques:

### 1. 🌿 Interfaz Minimalista (Uso diario, limpia y elegante)
Ideal para trabajar sin ruido visual. Cuenta con Tux reactivo con emociones en ASCII, streaming token a token en tiempo real y respuestas renderizadas en Markdown con resaltado de sintaxis.

```bash
cd ~/Documents/agente
source .venv/bin/activate
python3 gordito.py
```

### 2. 🔍 Interfaz Inspector (Para depuración y arquitectura)
Desglosa cada paso en detalle: el razonamiento interno (*Chain of Thought*), los JSON crudos generados por el modelo (`[PASO 1.A]`), la llamada física en el sistema operativo (`[PASO 1.B]`), y el payload inyectado de vuelta (`[PASO 1.C]`).

```bash
cd ~/Documents/agente
source .venv/bin/activate
python3 agente.py
```

---

## 🐧 Compatibilidad con Arch Linux

Gordito es 100% compatible con **Arch Linux** (¡el hogar natural de Tux!):
1. **Control de Audio nativo (MPRIS):**
   * En Arch Linux, Gordito utiliza `playerctl` o llamadas nativas D-Bus (`org.mpris.MediaPlayer2.spotify`), permitiendo consultar canciones, pausar, pasar pistas y fijar volumen sin configuración extra.
   * Paquete recomendado en Arch:
     ```bash
     sudo pacman -S playerctl
     ```
2. **Apertura de URIs:** Usa `xdg-open` de forma transparente.
3. **Rutas portables:** Tanto los favoritos de Spotify como la configuración de servidores MCP (`mcp_servers.json`) utilizan rutas relativas al directorio `$HOME` (`~`), funcionando sin cambios tanto en `/Users/inakisobera` como en `/home/inakisobera`.

---

## ✨ Capacidades de Gordito

* **🐧 Tux Reactivo:** Avatar ASCII simétrico con expresiones que reaccionan a la música (`|♫_♫ |`), modo nocturno (`|u_u |`) y estado normal (`|o_o |`).
* **🎧 DJ de Código:** Acceso a tu biblioteca de 440 canciones favoritas (`favoritos.csv`), ajustando volumen y ritmo según tu modo de trabajo (flow, hacker, chill, energía).
* **🌐 Internet en Tiempo Real:** Búsqueda en DuckDuckGo (`buscar_en_internet`) y lectura de páginas web (`leer_pagina_web`).
* **🎭 Navegador Web Playwright (MCP):** Control total de un navegador Chromium real (`browser_navigate`, `browser_click`, `browser_fill_form`, `browser_snapshot`, capturas de pantalla, etc.) para interactuar con páginas con JavaScript, autenticación o formularios dinámicos.
* **💻 Sistema y Archivos:** Navegar carpetas (`cd`), listar (`ls`), leer, escribir archivos y ejecutar comandos.
* **🔌 Servidores MCP:** Integración automática con servidores como `mcp-banxico` y `@playwright/mcp` (configurables en `mcp_servers.json`).

---

## ⚡ Comandos Slash (Menú flotante al teclear `/`)

| Comando | Descripción |
|---|---|
| `/flow [modo]` | **DJ Gordito:** Sintoniza una canción de tus favoritos y ajusta el volumen (ej. `/flow rock`, `/flow chill`). |
| `/mision <objetivo>` | Modo Agente Autónomo multi-paso para resolver tareas complejas paso a paso. |
| `/spotify` | Muestra qué canción está sonando en tu Mac o Arch Linux. |
| `/tools` | Muestra la lista de herramientas activas. |
| `/models` | Lista tus modelos de Ollama y permite cambiar de modelo interactivo. |
| `/model <nombre>` | Cambia directamente al modelo indicado (con autocompletado). |
| `/mcp` | Muestra el estado de los servidores MCP conectados. |
| `/clear` | Limpia la pantalla y reinicia la memoria de la conversación. |
| `/help` | Muestra los comandos disponibles. |
| `/exit` o `/salir` | Cierra la sesión con Gordito. |
