#!/usr/bin/env python3
# YT-DLP Interface Server - v3.1.0 com auto‑fallback, gestão de Python, filtros UI e associação link-ficheiro

import hashlib
import json
import mimetypes
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
import webbrowser
import zipfile
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

# ========== CONFIGURAÇÕES GLOBAIS ==========
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
BIN_DIR = os.path.join(APP_DIR, "bin")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
HISTORY_FILE = os.path.join(APP_DIR, "history.json")
DEFAULT_DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")
PAUSE_FILE = os.path.join(APP_DIR, ".pause")
CANCEL_FILE = os.path.join(APP_DIR, ".cancel")
QUEUE_FILE = os.path.join(APP_DIR, "download_queue.json")
COOKIES_FILE = os.path.join(APP_DIR, "cookies.txt")
PYTHON_PREF_FILE = os.path.join(APP_DIR, "python_pref.txt")
VERSION_FILE = os.path.join(APP_DIR, "version.json")
LICENSES_JSON = os.path.join(APP_DIR, "licenses.json")
LICENSES_DIR = os.path.join(APP_DIR, "licenses")
CHECKSUMS_FILE = os.path.join(APP_DIR, "checksums.json")

FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

clients = []
current_process = None
server_instance = None
download_paused = False
download_cancel_requested = False
_queue_lock = threading.RLock()
_queue_wakeup = threading.Event()
_queue_jobs = []
_queue_worker_running = False
_active_download_id = None
APP_VERSION = "3.9.0"  # gerado por tools/sync_version.ps1

os.makedirs(BIN_DIR, exist_ok=True)

# Tipos MIME
mimetypes.init()
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/x-msvideo", ".avi")
mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/opus", ".opus")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")

# Limpar ficheiros de controlo antigos
for f in [PAUSE_FILE, CANCEL_FILE]:
    if os.path.exists(f):
        try:
            os.remove(f)
        except:
            pass


# ========== UTILITÁRIOS ==========
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ========== LICENÇAS DE TERCEIROS ==========
_LICENSE_FALLBACK = {
    "pasta": "licenses",
    "componentes": [
        {"nome": "yt-dlp", "licenca": "Unlicense", "descricao": "Motor de downloads (domínio público).", "url": "https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE"},
        {"nome": "FFmpeg", "licenca": "GPL-3.0-or-later", "descricao": "Junção e conversão de media (build GPL — BtbN/FFmpeg-Builds).", "url": "https://github.com/BtbN/FFmpeg-Builds"},
        {"nome": "Python", "licenca": "PSF-2.0", "descricao": "Interpretador embebido (Python Software Foundation License).", "url": "https://docs.python.org/3/license.html"},
        {"nome": "Deno", "licenca": "MIT", "descricao": "Runtime JavaScript usado pelo yt-dlp para resolver desafios.", "url": "https://github.com/denoland/deno/blob/main/LICENSE.md"},
        {"nome": "Microsoft Edge WebView2", "licenca": "Microsoft", "descricao": "Componente de apresentação web redistribuível.", "url": "https://developer.microsoft.com/microsoft-edge/webview2/"},
        {"nome": ".NET", "licenca": "MIT", "descricao": "Runtime do launcher (dotnet/runtime).", "url": "https://github.com/dotnet/runtime/blob/main/LICENSE.TXT"},
    ],
}


def load_licenses():
    """Devolve o manifesto de licenças (licenses.json) ou o fallback interno."""
    data = load_json(LICENSES_JSON, None)
    if isinstance(data, dict) and data.get("componentes"):
        return data
    return _LICENSE_FALLBACK


# ========== INTEGRIDADE (HASHES EM SEGUNDO PLANO) ==========
_integrity_lock = threading.Lock()
_integrity_state = {"status": "pendente", "verificados": 0, "total": 0, "ficheiros": {}, "alterados": [], "quando": None}


def get_integrity_status():
    with _integrity_lock:
        return dict(_integrity_state)


def _sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def integrity_worker():
    """Verifica em segundo plano os hashes definidos em checksums.json."""
    manifest = load_json(CHECKSUMS_FILE, None)
    if not isinstance(manifest, dict) or not manifest.get("ficheiros"):
        with _integrity_lock:
            _integrity_state.update({"status": "pendente", "total": 0, "verificados": 0})
        return
    ficheiros = manifest["ficheiros"]
    total = len(ficheiros)
    with _integrity_lock:
        _integrity_state["total"] = total
        _integrity_state["status"] = "pendente"
    ok = 0
    alterados = []
    estados = {}
    for rel, expected in ficheiros.items():
        full = os.path.join(APP_DIR, rel.replace("/", os.sep))
        try:
            if not os.path.isfile(full):
                alterados.append({"ficheiro": rel, "motivo": "ausente"})
                estados[rel] = "ausente"
            elif _sha256_file(full).lower() == str(expected).lower():
                ok += 1
                estados[rel] = "ok"
            else:
                alterados.append({"ficheiro": rel, "motivo": "hash diferente"})
                estados[rel] = "alterado"
        except Exception as e:
            alterados.append({"ficheiro": rel, "motivo": str(e)})
            estados[rel] = "erro"
        with _integrity_lock:
            _integrity_state["verificados"] = ok + len(alterados)
    with _integrity_lock:
        _integrity_state.update({
            "status": "ok" if not alterados else "alterado",
            "verificados": ok + len(alterados),
            "total": total,
            "ficheiros": estados,
            "alterados": alterados,
            "quando": datetime.now().isoformat(timespec="seconds"),
        })
    try:
        if alterados:
            broadcast_log(f"[AVISO] Integridade: {len(alterados)} ficheiro(s) com hash diferente.")
        else:
            broadcast_log(f"[OK] Integridade verificada ({ok}/{total} ficheiros).")
    except Exception:
        pass


default_config = {
    "theme": "system",
    "language": "pt",
    "use_cookies": False,
    "use_po_token": False,
    "po_token": "",
    "visitor_data": "",
    "cookies_method": "none",
    "cookies_browser": "chrome",
    "server_port": 8181,
    "custom_ffmpeg_path": "",
    "downloads_mode": "internal",
    "downloads_custom_dir": "",
    "group_by_uploader": False,
    "download_delay": 8,
    "download_retries": 2,
    "auto_quality_recommendation": True,
    "sub_mode": "none",
    "sub_langs": "pt,en",
    "sub_auto": True,
    "library_filter": "all",
    "categories_per_row": 3,
    "categories": [],
    "app_version": APP_VERSION,
    "theme_palette": "indigo",
    "changelog": [
        {
            "version": "3.4.0",
            "date": "2026-10-11",
            "changes": [
                "Opcao (Configuracao) para agrupar os downloads por canal/uploader numa pasta propria",
                "Pacote portatil auto-extraivel revisto para distribuicao",
            ],
        },
        {
            "version": "3.3.0",
            "date": "2026-10-11",
            "changes": [
                "Versão portátil auto-extraível: um único executável, sem dependências externas",
                "Níveis de notificação completos: erro, aviso, informação e interação",
                "Switches de seleção permanecem visíveis nos itens escolhidos",
                "Tooltips em estilo balão, com seta a apontar para o elemento",
                "Fechar a aplicação encerra o servidor e processos associados",
            ],
        },
        {
            "version": "3.2.0",
            "date": "2026-10-10",
            "changes": [
                "Aplicação instalável (PWA) com suporte offline",
                "Modo kiosk: janela sem barra nativa com controlos próprios",
                "6 paletas de tema, cada uma com variante clara e escura",
                "Notificações (toasts) e diálogos de confirmação",
                "Tooltips contextuais em toda a interface",
                "Ícones monocromáticos",
            ],
        },
        {
            "version": "3.1.0",
            "date": "2026-05-10",
            "changes": [
                "Filtros laterais: Vídeo / Áudio / Todos",
                "Switches elegantes de seleção",
                "Interface mais moderna e responsiva",
                "Pesquisa condicionada aos filtros selecionados",
                "Seleção múltipla e remoção em lote",
                "Remoção seletiva (arquivo/histórico/link)",
                "Associação link-ficheiro no histórico",
            ],
        },
        {
            "version": "3.0.0",
            "date": "2026-05-08",
            "changes": [
                "Auto-fallback para múltiplas estratégias de autenticação",
                "Extração automática de cookies do navegador",
                "Suporte a PO Token e Visitor Data",
                "Mudança automática de cliente",
                "Impersonate Chrome",
                "Log detalhado de cada tentativa",
                "Escolha do interpretador Python",
            ],
        }
    ],
}
config = load_json(CONFIG_FILE, default_config)
if not isinstance(config.get("categories"), list):
    config["categories"] = []


def get_downloads_dir():
    """Resolve a pasta de downloads conforme a configuracao do utilizador.

    Modos: 'internal' (pasta downloads dentro da app, por omissao),
    'system' (pasta Downloads do sistema) ou 'custom' (caminho personalizado).
    """
    mode = config.get("downloads_mode", "internal")
    if mode == "system":
        base = os.path.join(os.path.expanduser("~"), "Downloads")
    elif mode == "custom":
        base = config.get("downloads_custom_dir", "").strip() or DEFAULT_DOWNLOADS_DIR
    else:
        base = DEFAULT_DOWNLOADS_DIR
    if not os.path.isabs(base):
        base = os.path.join(APP_DIR, base)
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    return base


# ========== GAVETAS (CATEGORIAS) ==========
_WIN_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10)
}
_INVALID_FOLDER_CHARS = '<>:"/\\|?*'

# Areas de contexto das gavetas: um video (filmes, series, tutoriais)
# nao partilha o mesmo vocabulario que um audio (pop, metal, classica).
_VALID_MEDIA = ("video", "audio")
_LEGACY_MEDIA = "video"
_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov")
_AUDIO_EXTS = (".mp3", ".m4a", ".opus", ".wav", ".flac", ".ogg")

# Paleta de cores das gavetas (o utilizador pode trocar nas Definicoes).
_CAT_PALETTE = (
    "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
    "#06b6d4", "#ef4444", "#84cc16", "#14b8a6", "#f97316",
)


def sanitize_category_color(value):
    """Valida a cor de uma gaveta (#rgb ou #rrggbb) e devolve #rrggbb."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        v = "#" + "".join(ch * 2 for ch in v[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        return v
    return None


def default_category_color(name):
    """Cor estavel para uma gaveta sem cor definida (hash do nome)."""
    base = (name or "").strip().lower()
    if not base:
        return _CAT_PALETTE[0]
    return _CAT_PALETTE[sum(ord(ch) for ch in base) % len(_CAT_PALETTE)]


def sanitize_category_name(name):
    """Valida e normaliza o nome de uma gaveta (tem de ser nome de pasta seguro).

    Devolve o nome limpo ou None se for invalido.
    """
    if not isinstance(name, str):
        return None
    clean = re.sub(r"\s+", " ", name).strip()
    if len(clean) > 64:
        clean = clean[:64].strip()
    if not clean or clean in (".", ".."):
        return None
    if any(ch in _INVALID_FOLDER_CHARS for ch in clean):
        return None
    if clean.lower() in _WIN_RESERVED:
        return None
    if clean.endswith("."):
        return None
    return clean


def get_categories_full():
    """Gavetas definidos pelo utilizador: lista de {"name","media","color"}.

    Cada gaveta pertence a uma area (video ou audio), porque o contexto
    de um video (filmes, series, tutoriais) e diferente do de um audio (pop,
    metal, classica). Entradas antigas (apenas o nome, em texto) sao aceites e
    ficam como video, para nao invalidar configuracoes ja existentes. Cada
    gaveta tem tambem uma cor (usada no "distivo" das cartas).
    """
    cats = config.get("categories")
    if not isinstance(cats, list):
        return []
    out = []
    seen = set()
    for c in cats:
        if isinstance(c, dict):
            clean = sanitize_category_name(c.get("name"))
            media = c.get("media")
            color = sanitize_category_color(c.get("color"))
        else:
            clean = sanitize_category_name(c)
            media = _LEGACY_MEDIA
            color = None
        if not clean or clean.lower() in seen:
            continue
        seen.add(clean.lower())
        out.append({
            "name": clean,
            "media": media if media in _VALID_MEDIA else _LEGACY_MEDIA,
            "color": color or default_category_color(clean),
        })
    return out


def get_categories():
    """Apenas os nomes das gavetas (uso interno/compatibilidade)."""
    return [c["name"] for c in get_categories_full()]


def get_category_media(name):
    """Area (video/audio) de uma gaveta, ou None se nao existir."""
    clean = sanitize_category_name(name) if name else None
    if not clean:
        return None
    for c in get_categories_full():
        if c["name"].lower() == clean.lower():
            return c["media"]
    return None


def media_of_file(rel_path):
    """Area de um ficheiro a partir da extensao, ou None se desconhecida."""
    ext = os.path.splitext(rel_path or "")[1].lower()
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    return None


def category_dir(name):
    """Pasta no disco de uma gaveta (dentro da pasta de downloads)."""
    return os.path.join(get_downloads_dir(), name)


def ensure_category_dir(name):
    """Cria a pasta da gaveta, se ainda nao existir."""
    path = category_dir(name)
    os.makedirs(path, exist_ok=True)
    return path


def pick_folder_native(title="Escolha a pasta de downloads"):
    """Dialogo nativo Windows para escolher uma pasta.

    Usa SHBrowseForFolderW via ctypes (stdlib puro, sem tkinter),
    portanto funciona no python empacotado e em qualquer navegador
    a apontar para o servidor local. Devolve o caminho escolhido ou
    None se o utilizador cancelar / nao for possivel abrir o dialogo.
    """
    try:
        import ctypes
        from ctypes import wintypes

        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040
        MAX_PATH = 32767

        class BROWSEINFO(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", wintypes.LPARAM),
                ("iImage", ctypes.c_int),
            ]

        shell32 = ctypes.windll.shell32
        shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFO)]
        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
        shell32.SHGetPathFromIDListW.restype = wintypes.BOOL

        ole32 = ctypes.windll.ole32
        ole32.OleInitialize.argtypes = [wintypes.LPVOID]
        ole32.OleInitialize.restype = ctypes.c_long  # HRESULT
        ole32.OleUninitialize.argtypes = []
        ole32.OleUninitialize.restype = None

        display = ctypes.create_unicode_buffer(MAX_PATH)
        bi = BROWSEINFO()
        bi.pszDisplayName = ctypes.cast(display, ctypes.c_wchar_p)
        bi.lpszTitle = title
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

        # O SHBrowseForFolder (estilo novo) requer COM na thread.
        hr = ole32.OleInitialize(None)
        try:
            pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
            if not pidl:
                return None
            path = ctypes.create_unicode_buffer(MAX_PATH)
            if not shell32.SHGetPathFromIDListW(pidl, path):
                return None
            return path.value
        finally:
            if hr == 0:  # S_OK — fomos nos que inicializamos o COM
                ole32.OleUninitialize()
    except Exception:
        return None


def resolve_download_file(url_path):
    """Converte um caminho de download ("/downloads/<rel>") no caminho absoluto.

    Aceita o formato usado na UI (URL com /downloads/) e devolve o caminho no
    disco dentro da pasta de downloads. Devolve None se for invalido ou tentar
    sair da pasta de downloads (protecao contra path traversal).
    """
    if not url_path:
        return None
    rel = unquote(str(url_path))
    for prefix in ("/downloads/", "downloads/", "downloads\\"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    rel = rel.strip("/\\")
    if not rel:
        return None
    parts = re.split(r"[\\/]+", rel)
    if any(p in ("..", "") for p in parts):
        return None
    base = os.path.normpath(get_downloads_dir())
    full = os.path.normpath(os.path.join(base, *parts))
    if full != base and not full.startswith(base + os.sep):
        return None
    return full


def show_in_folder(path):
    """Abre o Explorador de Ficheiros com o ficheiro selecionado (ou a pasta).

    Windows: explorer /select. macOS: open -R. Outros: abre a pasta.
    Devolve (ok, erro).
    """
    try:
        if not path or not os.path.exists(path):
            return False, "not_found"
        is_dir = os.path.isdir(path)
        if os.name == "nt":
            # Atencao: "/select," e o caminho TEM de ser argumentos separados.
            # Se forem um so argumento ("/select," + path), o Python coloca
            # aspas em volta de tudo ("/select,C:\...") e o Explorador nao
            # reconhece a opcao, abrindo a pasta errada (sem selecionar o
            # ficheiro). Com dois argumentos o caminho fica devidamente
            # entre aspas e o ficheiro e realçado.
            if is_dir:
                subprocess.Popen(["explorer", path])
            else:
                subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", path if is_dir else os.path.dirname(path)])
        return True, None
    except Exception as e:
        return False, str(e)


def detect_platform(url):
    host = urlparse(url).netloc.lower().replace("www.", "")
    if "youtu" in host: return "youtube"
    if "tiktok" in host: return "tiktok"
    if "instagram" in host: return "instagram"
    if "facebook" in host or "fb.watch" in host: return "facebook"
    if "twitter" in host or "x.com" in host: return "x"
    if "vimeo" in host: return "vimeo"
    if "twitch" in host: return "twitch"
    return host.split(".")[0] if host else "web"

def clean_media_title(file_path):
    if not file_path:
        return None
    name = os.path.basename(file_path)
    return os.path.splitext(name)[0]

def save_history_entry(url, download_type, status="success", file_path=None, title=None, platform=None, media_type=None):
    """Regista uma entrada no histórico com associação ao ficheiro."""
    history = load_json(HISTORY_FILE, [])
    entry = {
        "url": url,
        "date": datetime.now().isoformat(),
        "type": download_type,
        "status": status,
        "file_path": file_path,
        "title": title,
        "platform": platform or detect_platform(url),
        "media_type": media_type
    }
    history.insert(0, entry)
    if len(history) > 1000:
        history = history[:1000]
    save_json(HISTORY_FILE, history)


def get_folder_size(path):
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total


def broadcast(message):
    msg = f"data: {message}\n\n"
    for client in clients[:]:
        try:
            client.write(msg.encode("utf-8"))
            client.flush()
        except:
            if client in clients:
                clients.remove(client)


def broadcast_log(msg):
    print(msg, flush=True)
    broadcast(f"LOG: {msg}")


# ========== PREFERÊNCIA DO PYTHON ==========
def get_python_pref():
    if os.path.exists(PYTHON_PREF_FILE):
        try:
            with open(PYTHON_PREF_FILE, "r") as f:
                return int(f.read().strip())
        except:
            return 1
    return 1


def set_python_pref(mode):
    with open(PYTHON_PREF_FILE, "w") as f:
        f.write(str(mode))


def _normalize_name(text):
    text = (text or "").lower()
    try:
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    return re.sub(r"[^a-z0-9]+", "", text)


# ========== VARREDURA DA BIBLIOTECA ==========
def scan_downloads():
    library = {"video": [], "audio": []}
    video_exts = (".mp4", ".mkv", ".webm", ".avi", ".mov")
    audio_exts = (".mp3", ".m4a", ".opus", ".wav", ".flac", ".ogg")
    ddir = get_downloads_dir()
    if not os.path.exists(ddir):
        return library

    cats_lower = {c.lower(): c for c in get_categories()}

    history = load_json(HISTORY_FILE, [])
    by_path = {}
    titled = []
    timed = []
    for h in history:
        fp = h.get("file_path")
        if fp:
            by_path[fp] = h
        t = _normalize_name(h.get("title"))
        if t and len(t) >= 4:
            titled.append((t, h))
        d = h.get("date")
        if d:
            try:
                dt = datetime.fromisoformat(d)
                # Normaliza para hora local sem fuso: o historico pode conter
                # datas com fuso (ex.: "...Z" ou "+00:00") e nao e possivel
                # subtrair datas aware a datas naive do sistema de ficheiros.
                if dt.tzinfo is not None:
                    dt = dt.astimezone().replace(tzinfo=None)
                timed.append((dt, h))
            except Exception:
                pass

    def resolve_platform(url_path, folder, stem, mtime):
        """Associa uma plataforma a um ficheiro usando histórico por caminho, título ou data."""
        def entry_platform(h):
            return h.get("platform") or (detect_platform(h.get("url")) if h.get("url") else "local")

        hit = by_path.get(url_path)
        if hit:
            return entry_platform(hit)
        nstem = _normalize_name(stem)
        nfolder = _normalize_name(folder)
        best = None
        best_score = 0
        for t, h in titled:
            if len(t) < 5:
                continue
            score = 0
            if nstem and (t in nstem or nstem in t):
                score = len(t)
            if nfolder and (t in nfolder or nfolder in t):
                score = max(score, len(t))
            if score > best_score:
                best_score = score
                best = h
        if best:
            return entry_platform(best)
        if timed:
            try:
                file_dt = datetime.fromtimestamp(mtime)
            except Exception:
                file_dt = None
            if file_dt:
                cand = min(timed, key=lambda x: abs((x[0] - file_dt).total_seconds()))
                if abs((cand[0] - file_dt).total_seconds()) <= 900:
                    return entry_platform(cand[1])
        return "local"

    for root, _, files in os.walk(ddir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in video_exts and ext not in audio_exts:
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, ddir).replace("\\", "/")
            url_path = f"/downloads/{rel}"
            parts = rel.split("/")
            # O primeiro nivel pode ser uma gaveta: nesse caso a origem
            # (uploader) passa a ser o nivel seguinte.
            category = None
            if len(parts) >= 2 and parts[0].lower() in cats_lower:
                category = cats_lower[parts[0].lower()]
                parts = parts[1:]
            folder = parts[0] if len(parts) >= 2 else "Raiz"
            timestamp = os.path.getmtime(full)
            item = {
                "name": f,
                "path": url_path,
                "size": os.path.getsize(full),
                "uploader": folder,
                "category": category,
                "timestamp": timestamp,
                "platform": resolve_platform(url_path, folder, os.path.splitext(f)[0], timestamp),
            }
            if ext in video_exts:
                library["video"].append(item)
            else:
                library["audio"].append(item)
    library["video"].sort(key=lambda x: x["name"], reverse=True)
    library["audio"].sort(key=lambda x: x["name"], reverse=True)
    return library


# ========== MOVIMENTACAO DE FICHEIROS ==========
def unique_destination(dest_path):
    """Devolve um caminho livre, acrescentando ' (2)', ' (3)'... antes da extensao."""
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def _split_category(rel):
    """Separa a gaveta (1.o nivel) do resto do caminho relativo."""
    parts = [p for p in rel.split("/") if p]
    cats = {c.lower() for c in get_categories()}
    if len(parts) > 1 and parts[0].lower() in cats:
        return parts[0], parts[1:]
    return None, parts


def get_recorded_move_paths():
    """Caminhos absolutos registados no historico (para poder revelar ficheiros ja movidos)."""
    recorded = set()
    for entry in load_json(HISTORY_FILE, []):
        moved = entry.get("moved_to")
        path = moved.get("path") if isinstance(moved, dict) else moved
        if path:
            recorded.add(os.path.normcase(os.path.normpath(str(path))))
    return recorded


def _update_history_after_move(old_url, info, destination):
    """Reflete a movimentacao no historico: novo caminho e nota do destino."""
    history = load_json(HISTORY_FILE, [])
    kind = (destination or {}).get("kind")
    name = (destination or {}).get("name")
    changed = False
    for entry in history:
        if entry.get("file_path") != old_url:
            continue
        changed = True
        entry["file_path"] = info["new_path"]
        note = {
            "kind": "external" if kind == "external" else "internal",
            "path": info["new_abs"],
            "date": datetime.now().isoformat(),
        }
        if kind != "external":
            note["name"] = name or ""
        entry["moved_to"] = note
    if changed:
        save_json(HISTORY_FILE, history)
    return changed


def _prune_empty_dirs(start_dir, stop_dir):
    """Remove pastas vazias acima de start_dir.

    Para em stop_dir (a pasta de downloads) e nas pastas de gavetas, que
    devem sobreviver mesmo quando ficam vazias.
    """
    stop = os.path.normcase(os.path.normpath(stop_dir))
    cats = {os.path.normcase(os.path.normpath(category_dir(c))) for c in get_categories()}
    parent = os.path.normpath(start_dir) if start_dir else None
    while parent:
        key = os.path.normcase(parent)
        if key == stop or key in cats:
            break
        if not key.startswith(stop + os.sep):
            break
        try:
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
            else:
                break
        except Exception:
            break
        parent = os.path.dirname(parent)


def move_file(url_path, destination):
    """Move um ficheiro descarregado para uma gaveta ou para uma pasta externa.

    destination:
      {"kind": "category", "name": <str|None>}  -> interno (None = sem gaveta)
      {"kind": "external", "dir": <caminho>}    -> externo (o ficheiro sai da app)

    Devolve (ok, info, erro).
    """
    src = resolve_download_file(url_path)
    if not src:
        return False, None, "invalid_path"
    if not os.path.exists(src):
        return False, None, "not_found"
    if os.path.isdir(src):
        return False, None, "is_directory"

    ddir = os.path.normpath(get_downloads_dir())
    rel = os.path.relpath(src, ddir).replace("\\", "/")
    kind = (destination or {}).get("kind")

    if kind == "external":
        target_dir = str(destination.get("dir") or "").strip()
        if not target_dir or not os.path.isabs(target_dir):
            return False, None, "invalid_target"
        target_dir = os.path.normpath(target_dir)
        if not os.path.isdir(target_dir):
            return False, None, "target_missing"
        dest = os.path.join(target_dir, os.path.basename(src))
    elif kind == "category":
        name = destination.get("name")
        clean = None
        if name:
            clean = sanitize_category_name(name)
            if not clean or clean not in get_categories():
                return False, None, "unknown_category"
            # Um video so entra em gavetas de video e um audio em
            # gavetas de audio (a interface ja filtra; isto e a defesa).
            cat_media = get_category_media(clean)
            file_media = media_of_file(rel)
            if cat_media and file_media and cat_media != file_media:
                return False, None, "media_mismatch"
        _, rest = _split_category(rel)
        if not rest:
            return False, None, "invalid_path"
        dest_dir = ddir if not clean else os.path.join(ddir, clean)
        dest = os.path.join(dest_dir, *rest)
    else:
        return False, None, "invalid_target"

    if os.path.normcase(os.path.normpath(dest)) == os.path.normcase(os.path.normpath(src)):
        return False, None, "same_place"

    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        dest = unique_destination(dest)
        shutil.move(src, dest)
    except Exception as e:
        return False, None, str(e)

    _prune_empty_dirs(os.path.dirname(src), ddir)

    new_abs = os.path.normpath(dest)
    if os.path.normcase(new_abs).startswith(os.path.normcase(ddir + os.sep)):
        new_rel = os.path.relpath(new_abs, ddir).replace("\\", "/")
        new_url = "/downloads/" + new_rel
    else:
        new_url = None

    info = {"new_path": new_url, "new_abs": new_abs, "old_path": url_path}
    _update_history_after_move(url_path, info, destination)
    return True, info, None


def move_files(url_paths, destination):
    """Move varios ficheiros. Devolve (resultados, numero movidos)."""
    results = []
    moved = 0
    for p in url_paths or []:
        ok, info, err = move_file(p, destination)
        results.append({
            "path": p,
            "ok": ok,
            "error": err,
            "new_path": info["new_path"] if info else None,
            "new_abs": info["new_abs"] if info else None,
        })
        if ok:
            moved += 1
    return results, moved


def remove_category(name, dissolve=True):
    """Remove uma gaveta da configuracao.

    Com dissolve=True devolve os ficheiros que estavam dentro dele a raiz da
    pasta de downloads, para nao ficarem presos numa pasta orfa.
    Devolve (ok, erro, numero_de_ficheiros_devolvidos).
    """
    clean = sanitize_category_name(name)
    cats = get_categories()
    if not clean or clean not in cats:
        return False, "unknown_category", 0

    ddir = os.path.normpath(get_downloads_dir())
    cdir = category_dir(clean)
    moved = 0

    if dissolve and os.path.isdir(cdir):
        for root, _, files in os.walk(cdir):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, cdir)
                dest = unique_destination(os.path.join(ddir, rel))
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(src, dest)
                except Exception:
                    continue
                moved += 1
                old_rel = os.path.relpath(src, ddir).replace("\\", "/")
                new_rel = os.path.relpath(dest, ddir).replace("\\", "/")
                _update_history_after_move(
                    "/downloads/" + old_rel,
                    {"new_path": "/downloads/" + new_rel, "new_abs": os.path.normpath(dest)},
                    {"kind": "category", "name": None},
                )
        # remover as pastas que ficaram vazias
        for root, _, _ in os.walk(cdir, topdown=False):
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except Exception:
                pass

    config["categories"] = [c for c in get_categories_full() if c["name"] != clean]
    save_json(CONFIG_FILE, config)
    return True, None, moved


# ========== DEPENDÊNCIAS ==========
def download_file(url, dest):
    print(f"Downloading {os.path.basename(dest)}...")
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=300) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
        return True
    except Exception as e:
        print(f"Erro: {e}")
        return False


def check_dependencies():
    ytdlp_path = os.path.join(BIN_DIR, "yt-dlp.exe")
    ffmpeg_path = os.path.join(BIN_DIR, "ffmpeg.exe")
    for f in ["yt-dlp.exe", "ffmpeg.exe"]:
        old = os.path.join(APP_DIR, f)
        new = os.path.join(BIN_DIR, f)
        if os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.move(old, new)
            except:
                pass
    if not os.path.exists(ytdlp_path):
        broadcast_log("[SETUP] A descarregar yt-dlp...")
        download_file(YTDLP_URL, ytdlp_path)
    if not config.get("custom_ffmpeg_path") and not os.path.exists(ffmpeg_path):
        broadcast_log("[SETUP] A descarregar FFmpeg...")
        zip_path = os.path.join(BIN_DIR, "ffmpeg.zip")
        if download_file(FFMPEG_URL, zip_path):
            try:
                with zipfile.ZipFile(zip_path, "r") as z:
                    for file in z.namelist():
                        if file.endswith("ffmpeg.exe"):
                            with z.open(file) as src, open(ffmpeg_path, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            break
                os.remove(zip_path)
            except Exception as e:
                broadcast_log(f"[ERRO] FFmpeg: {e}")


# ========== ESTRATÉGIAS DE AUTENTICAÇÃO ==========
def build_command_with_fallback(
    url, base_cmd, mode, quality, vformat, subtitles, sub_mode, sub_langs, sub_auto
):
    alternatives = []

    if config.get("use_cookies") and os.path.exists(COOKIES_FILE):
        cmd0 = base_cmd.copy()
        cmd0.extend(["--cookies", COOKIES_FILE])
        alternatives.append(("Cookies (ficheiro)", cmd0))

    if config.get("use_po_token"):
        pt = config.get("po_token", "").strip()
        vd = config.get("visitor_data", "").strip()
        if pt:
            cmd1 = base_cmd.copy()
            if vd:
                cmd1.extend(
                    ["--extractor-args", f"youtube:po_token={pt}+visitor_data={vd}"]
                )
            else:
                cmd1.extend(["--extractor-args", f"youtube:po_token={pt}"])
            alternatives.append(("PO Token estático", cmd1))

    cmd2 = base_cmd.copy()
    cmd2.extend(["--extractor-args", "youtube:player_client=web_embedded"])
    alternatives.append(("Cliente web_embedded", cmd2))

    browser = config.get("cookies_browser", "chrome")
    cmd3 = base_cmd.copy()
    cmd3.extend(["--cookies-from-browser", browser])
    alternatives.append((f"Cookies ({browser})", cmd3))

    for client in ["android", "tv", "web_safari", "ios"]:
        cmd4 = base_cmd.copy()
        cmd4.extend(["--extractor-args", f"youtube:player_client={client},default"])
        alternatives.append((f"Cliente {client}", cmd4))

    cmd5 = base_cmd.copy()
    cmd5.extend(["--impersonate", "chrome"])
    alternatives.append(("Impersonate Chrome", cmd5))

    alternatives.append(("Tentativa padrão (sem extras)", base_cmd))

    return alternatives


MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".mp3", ".m4a", ".opus", ".wav", ".flac", ".ogg")


def pick_final_file(path):
    """Resolve o ficheiro final de um download (o caminho capturado pode ser um fragmento temporário)."""
    path = (path or "").strip().strip('"')
    if not path:
        return None
    if os.path.exists(path) and os.path.isfile(path):
        return path
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        return path or None
    stem = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"\.f\d+$", "", stem)
    best = None
    best_mtime = -1
    for name in os.listdir(folder):
        fp = os.path.join(folder, name)
        if not os.path.isfile(fp):
            continue
        if os.path.splitext(name)[1].lower() not in MEDIA_EXTS:
            continue
        if name == base or name.startswith(base + "."):
            mt = os.path.getmtime(fp)
            if mt > best_mtime:
                best_mtime = mt
                best = fp
    if best:
        return best
    for name in os.listdir(folder):
        fp = os.path.join(folder, name)
        if not os.path.isfile(fp):
            continue
        if os.path.splitext(name)[1].lower() not in MEDIA_EXTS:
            continue
        mt = os.path.getmtime(fp)
        if mt > best_mtime:
            best_mtime = mt
            best = fp
    return best or path


def execute_cmd_and_check(cmd):
    global current_process, download_paused
    broadcast("STATUS: A processar...")
    broadcast("LOG_CLEAR: true")
    # Cada tentativa/estratégia recomeça a barra do zero. O reset NO FIM deste
    # processo (que existia no finally) apagava o progresso logo a seguir a
    # terminar e, em downloads com várias estratégias de fallback, repunha a
    # barra a 0% entre tentativas — parecia que a barra "não avançava".
    broadcast("PROGRESS: 0")
    broadcast("PHASE: info")

    my_env = os.environ.copy()
    ffmpeg_locs = []
    custom = config.get("custom_ffmpeg_path", "").strip()
    if custom and os.path.exists(custom):
        ffmpeg_locs.append(custom)
    if os.path.exists(BIN_DIR):
        ffmpeg_locs.append(BIN_DIR)
    if ffmpeg_locs:
        my_env["PATH"] = os.pathsep.join(ffmpeg_locs) + os.pathsep + my_env["PATH"]
        cmd.extend(["--ffmpeg-location", ffmpeg_locs[0]])

    process = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            # Descodificacao defensiva: o grosso da saida e UTF-8 (--encoding
            # utf-8), mas a saida do ffmpeg (que partilha o mesmo pipe) pode ter
            # bytes fora de UTF-8; 'replace' evita rebentar o download por causa
            # de um byte perdido num log.
            encoding="utf-8",
            errors="replace",
            cwd=get_downloads_dir(),
            env=my_env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        current_process = process
        regex_progress = re.compile(r"\[download\]\s+([0-9.]+)%")
        regex_final = re.compile(r'\[Merger\] Merging formats into "(.*?)"')
        regex_audio = re.compile(r"\[ExtractAudio\] Destination: (.*)")
        regex_dest = re.compile(r"\[download\] Destination: (.*)")
        regex_exists = re.compile(r"\[download\] (.*) has already been downloaded")
        # O yt-dlp junta video e audio na mesma linha de formatos ("...: 137+140").
        # Dividimos a barra pelo numero de transferencias para nao a encher logo
        # na primeira (video) e recomecar na segunda (audio).
        regex_formats = re.compile(r"Downloading \d+ format\(s\): (.+)")
        n_formats = 1
        format_index = 0
        progress_floor = 0.0
        error_detected = False
        downloaded_file_path = None

        def remember(path):
            nonlocal downloaded_file_path
            path = (path or "").strip().strip('"')
            if path:
                downloaded_file_path = path
                broadcast(f"FILENAME: {os.path.basename(path)}")

        output_lines = queue.Queue(maxsize=1)
        stop_reader = threading.Event()

        def read_output():
            try:
                for output_line in process.stdout:
                    while not stop_reader.is_set():
                        try:
                            output_lines.put(output_line, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                    if stop_reader.is_set():
                        break
            finally:
                try:
                    output_lines.put_nowait(None)
                except queue.Full:
                    pass

        output_reader = threading.Thread(target=read_output, daemon=True)
        output_reader.start()
        while True:
            if download_cancel_requested or os.path.exists(CANCEL_FILE):
                broadcast_log("Cancelado pelo utilizador")
                stop_reader.set()
                if process.poll() is None:
                    process.terminate()
                while True:
                    try:
                        output_lines.get_nowait()
                    except queue.Empty:
                        break
                break
            if os.path.exists(PAUSE_FILE):
                download_paused = True
                time.sleep(0.1)
                continue
            download_paused = False

            try:
                line = output_lines.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if line is None:
                break

            if "Sign in to confirm" in line or "HTTP Error 403" in line:
                error_detected = True
                broadcast_log("[AVISO] Erro de autenticação detectado")
                stop_reader.set()
                if process.poll() is None:
                    process.terminate()
                while True:
                    try:
                        output_lines.get_nowait()
                    except queue.Empty:
                        break
                break

            fm = regex_final.search(line) or regex_audio.search(line)
            if fm:
                remember(fm.group(1))

            fmts = regex_formats.search(line)
            if fmts:
                n_formats = max(1, fmts.group(1).count("+") + 1)
                format_index = 0
                progress_floor = 0.0

            fd = regex_dest.search(line) or regex_exists.search(line)
            if fd:
                if regex_dest.search(line):
                    format_index += 1
                remember(fd.group(1))

            # Estados de fase: explicam a barra quando nao ha progresso de bytes
            # (a aguardar entre descargas, a juntar audio/video, a incorporar...).
            if "Sleeping" in line and "[download]" in line:
                broadcast("PHASE: wait")
            elif "[download] Destination:" in line:
                broadcast("PHASE: download")
            elif "[Merger]" in line:
                broadcast("PHASE: merge")
            elif "[ExtractAudio]" in line:
                broadcast("PHASE: extract")
            elif "EmbedThumbnail" in line:
                broadcast("PHASE: thumbnail")
            elif "[Metadata]" in line:
                broadcast("PHASE: metadata")
            elif "[FixupM3u8]" in line or "[VideoConvertor]" in line or "[Fixup" in line:
                broadcast("PHASE: finalize")

            p = regex_progress.search(line)
            if p:
                # Progresso agregado: cada transferencia (video/audio) ocupa uma
                # fatia da barra e nunca recua. A faixa 95-100% fica reservada
                # para o fim real do trabalho, para a barra nao mostrar
                # "concluido" enquanto o download ainda decorre.
                value = float(p.group(1))
                if n_formats > 1:
                    idx = min(max(format_index, 1), n_formats)
                    value = ((idx - 1) + value / 100.0) / n_formats * 100.0
                progress_floor = max(progress_floor, value)
                broadcast(f"PROGRESS: {min(progress_floor, 95):.1f}")
            else:
                clean = line.strip()
                if clean:
                    broadcast(f"LOG: {clean}")

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output_reader.join(timeout=1)
        if error_detected or process.returncode != 0:
            return False, None
        final_path = pick_final_file(downloaded_file_path)
        # Garante que a barra fica cheia quando o download termina com sucesso
        # (mesmo em casos em que o yt-dlp não emite a última linha de progresso,
        # como ficheiros já descarregados, junções ou extração de áudio).
        broadcast("PROGRESS: 100")
        broadcast("STATUS: Download concluído")
        broadcast("UPDATE_LIBRARY: true")
        return True, final_path

    except Exception as e:
        broadcast_log(f"Erro inesperado: {e}")
        return False, None
    finally:
        for f in [PAUSE_FILE, CANCEL_FILE]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        if process is not None and process.stdout is not None:
            try:
                process.stdout.close()
            except OSError as e:
                broadcast_log(f"[AVISO] Não foi possível fechar a saída do processo: {e}")
        current_process = None


# O Windows limita o caminho a MAX_PATH (260). Como o template usa o titulo duas
# vezes (pasta + ficheiro), titulos muito longos (ex.: Facebook, ~600 caracteres)
# fazem o yt-dlp falhar com "Unable to create directory" (WinError 3). Truncamos
# cada campo de texto para manter o caminho final com margem segura. Titulos
# curtos NAO sao alterados: em Python/yt-dlp '%.Ns' so trunca quando excede N.
WIN_PATH_BUDGET = 240       # MAX_PATH (260) com margem
WIN_PATH_RESERVED = 24      # separadores, extensao e sufixos temporarios (.fNNN/.part)
MIN_FIELD_LEN = 48


def _title_field_len(base_dir, fields=2):
    """Comprimento maximo seguro (em caracteres) para cada campo de texto do -o."""
    free = WIN_PATH_BUDGET - len(base_dir) - WIN_PATH_RESERVED
    return max(MIN_FIELD_LEN, free // max(1, fields))


def run_download_with_fallback(
    url, mode, quality, vformat, subtitles, sub_mode, sub_langs, sub_auto, options=None
):
    options = options or {}
    broadcast_log(f"[INFO] Iniciando download: {url}")
    broadcast(f"PLATFORM: {detect_platform(url)}")
    ytdlp = os.path.join(BIN_DIR, "yt-dlp.exe")
    # Agrupamento opcional por uploader/canal: downloads/<canal>/<titulo>.<ext>
    # Caso contrario: downloads/<titulo>/<titulo>.<ext>
    # Os campos de texto sao truncados (_title_field_len) para o caminho final
    # nao exceder o MAX_PATH do Windows mesmo com titulos muito longos.
    out_dir = get_downloads_dir()
    tlen = _title_field_len(out_dir, 2)
    title_fmt = f"%(title).{tlen}s"
    if config.get("group_by_uploader"):
        output_template = os.path.join(
            out_dir, f"%(uploader,channel).{tlen}s", f"{title_fmt}.%(ext)s"
        )
    else:
        output_template = os.path.join(out_dir, title_fmt, f"{title_fmt}.%(ext)s")

    base_cmd = [ytdlp, "-o", output_template]
    base_cmd.extend(
        [
            "--no-mtime",
            "--newline",
            # Forca a saida do yt-dlp em UTF-8. Sem isto o yt-dlp escreve na
            # codepage ANSI do Windows (cp1252/...): o server descodifica em
            # UTF-8 (modo UTF-8 do launcher) e rebentava com
            # "'utf-8' codec can't decode byte 0xb7"; alem disso os acentos e
            # emoji dos titulos chegavam corrompidos ('?').
            "--encoding",
            "utf-8",
            "--extractor-retries",
            "3",
            "--retries",
            "0",
            "--fragment-retries",
            "0",
            "--force-ipv4",
            "--geo-bypass",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
    )
    delay = config.get("download_delay", 8)
    if delay > 0:
        base_cmd.extend(
            ["--sleep-interval", str(delay), "--max-sleep-interval", str(delay + 2)]
        )

    if mode == "audio":
        base_cmd.extend(
            [
                "-x",
                "--audio-format",
                options.get("audio_format", "mp3"),
                "--audio-quality",
                str(quality),
            ]
        )
    else:
        if quality == "best" or quality == "0":
            fmt = "bestvideo+bestaudio/best"
        else:
            fmt = f"bestvideo[height<={quality}][ext={vformat}]+bestaudio[ext=m4a]/best[height<={quality}][ext={vformat}]/best"
        base_cmd.extend(["-f", fmt, "--merge-output-format", vformat])

    if options.get("proxy"):
        base_cmd.extend(["--proxy", options["proxy"]])
    if options.get("embed_metadata"):
        base_cmd.append("--embed-metadata")
    if options.get("embed_thumbnail"):
        base_cmd.append("--embed-thumbnail")
        # O contentor decide o formato de imagem aceite: webm quer webp; mp4/mkv
        # e o áudio aceitam jpg/png. Sem esta conversão, capas em webp não
        # conseguiam ser incorporadas (ex.: em mp4) e a opção falhava em silêncio.
        thumb_fmt = "webp" if (mode != "audio" and vformat == "webm") else "jpg"
        base_cmd.extend(["--convert-thumbnails", thumb_fmt])
    if options.get("embed_chapters"):
        base_cmd.append("--embed-chapters")
    if options.get("write_info_json"):
        base_cmd.append("--write-info-json")
    if options.get("playlist_items"):
        base_cmd.extend(["--playlist-items", options["playlist_items"]])
    if options.get("playlist_reverse"):
        base_cmd.append("--playlist-reverse")
    clip_start = options.get("clip_start", "")
    clip_end = options.get("clip_end", "")
    if clip_start or clip_end:
        base_cmd.extend(["--download-sections", f"*{clip_start}-{clip_end}"])
        base_cmd.append("--force-keyframes-at-cuts")

    if subtitles and sub_mode != "none":
        base_cmd.extend(["--sub-langs", sub_langs])
        if sub_mode == "separate":
            base_cmd.extend(["--write-subs"])
            if sub_auto:
                base_cmd.extend(["--write-auto-subs"])
        elif sub_mode == "embedded":
            base_cmd.extend(["--write-subs", "--embed-subs"])
            if sub_auto:
                base_cmd.extend(["--write-auto-subs", "--embed-auto-subs"])

    base_cmd.append(url)

    strategies = build_command_with_fallback(
        url, base_cmd, mode, quality, vformat, subtitles, sub_mode, sub_langs, sub_auto
    )
    
    for name, cmd in strategies:
        if download_cancel_requested:
            return False, None
        broadcast_log(f"[INFO] A tentar: {name}")
        success, file_path = execute_cmd_and_check(cmd)
        if success:
            broadcast_log(f"[OK] Sucesso com {name}")
            return True, file_path
        else:
            broadcast_log(f"[ERRO] Falha na estratégia: {name}")

    broadcast_log("[ERRO] Todas as estratégias falharam.")
    return False, None


_QUEUE_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_QUEUE_MAX_JOBS = 200
_QUEUE_MAX_URLS = 100
_TIME_VALUE = re.compile(r"^\d{1,6}(?::[0-5]?\d)?(?::[0-5]?\d(?:\.\d{1,3})?)?$")


def _valid_time_value(value):
    return not value or bool(_TIME_VALUE.fullmatch(value))


def _time_value_seconds(value):
    parts = value.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _parse_playlist_item_indexes(value, entry_count):
    if not value:
        return None
    indexes = set()
    for item in value.split(","):
        separator = "-" if "-" in item else ":" if ":" in item else None
        if separator:
            start, end = (int(part) for part in item.split(separator, 1))
            indexes.update(range(max(1, start), min(entry_count, end) + 1))
        else:
            index = int(item)
            if 1 <= index <= entry_count:
                indexes.add(index)
    return indexes


def _playlist_entry_quality(entry):
    heights = [entry.get("height")]
    bitrates = [entry.get("abr"), entry.get("tbr")]
    for media_format in entry.get("formats", []):
        if isinstance(media_format, dict):
            heights.append(media_format.get("height"))
            bitrates.extend((media_format.get("abr"), media_format.get("tbr")))
    valid_heights = [value for value in heights if isinstance(value, (int, float)) and value > 0]
    if valid_heights:
        return max(valid_heights)
    valid_bitrates = [value for value in bitrates if isinstance(value, (int, float)) and value > 0]
    return max(valid_bitrates) if valid_bitrates else None


def _playlist_entry_duration(entry):
    duration = entry.get("duration")
    return duration if isinstance(duration, (int, float)) and duration >= 0 else None


def _sort_playlist_entries(entries, sort_mode, playlist_items="", reverse=False):
    selected_indexes = _parse_playlist_item_indexes(playlist_items, len(entries))
    selected = [
        (index, entry)
        for index, entry in enumerate(entries, start=1)
        if isinstance(entry, dict) and (selected_indexes is None or index in selected_indexes)
    ]
    if sort_mode.startswith("duration-"):
        selected.sort(
            key=lambda item: (
                _playlist_entry_duration(item[1]) is None,
                _playlist_entry_duration(item[1]) or 0,
            ),
            reverse=sort_mode == "duration-longest",
        )
        known = [item for item in selected if _playlist_entry_duration(item[1]) is not None]
        missing = [item for item in selected if _playlist_entry_duration(item[1]) is None]
        selected = known + missing
    elif sort_mode.startswith("quality-"):
        selected.sort(
            key=lambda item: (
                _playlist_entry_quality(item[1]) is None,
                _playlist_entry_quality(item[1]) or 0,
            ),
            reverse=sort_mode == "quality-highest",
        )
        known = [item for item in selected if _playlist_entry_quality(item[1]) is not None]
        missing = [item for item in selected if _playlist_entry_quality(item[1]) is None]
        selected = known + missing
    if reverse:
        if sort_mode.startswith("duration-"):
            known = [item for item in selected if _playlist_entry_duration(item[1]) is not None]
            missing = [item for item in selected if _playlist_entry_duration(item[1]) is None]
            known.reverse()
            selected = known + missing
        elif sort_mode.startswith("quality-"):
            known = [item for item in selected if _playlist_entry_quality(item[1]) is not None]
            missing = [item for item in selected if _playlist_entry_quality(item[1]) is None]
            known.reverse()
            selected = known + missing
        else:
            selected.reverse()
    return selected


def _extract_sorted_playlist_urls(url, options):
    global current_process
    ytdlp = os.path.join(BIN_DIR, "yt-dlp.exe")
    base_cmd = [
        ytdlp,
        "--dump-single-json",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        "--encoding",
        "utf-8",
    ]
    if options.get("proxy"):
        base_cmd.extend(["--proxy", options["proxy"]])

    auth_commands = []
    if config.get("use_cookies") and os.path.exists(COOKIES_FILE):
        auth_commands.append(base_cmd + ["--cookies", COOKIES_FILE])
    if config.get("use_po_token") and config.get("po_token", "").strip():
        token_args = config["po_token"].strip()
        visitor_data = config.get("visitor_data", "").strip()
        if visitor_data:
            token_args += f"+visitor_data={visitor_data}"
        auth_commands.append(base_cmd + ["--extractor-args", f"youtube:po_token={token_args}"])
    if config.get("use_cookies"):
        auth_commands.append(
            base_cmd + ["--cookies-from-browser", config.get("cookies_browser", "chrome")]
        )
    auth_commands.append(base_cmd)

    last_error = ""
    for command in auth_commands:
        process = None
        try:
            env = os.environ.copy()
            env["PATH"] = os.pathsep.join([BIN_DIR, env.get("PATH", "")])
            process = subprocess.Popen(
                command + [url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=get_downloads_dir(),
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            current_process = process
            deadline = time.monotonic() + 180
            while True:
                if download_cancel_requested or os.path.exists(CANCEL_FILE):
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise RuntimeError("Cancelado pelo utilizador.")
                if time.monotonic() >= deadline:
                    process.kill()
                    _, stderr = process.communicate()
                    last_error = stderr.strip() or "A leitura da lista excedeu o limite de 3 minutos."
                    break
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    if process.returncode == 0 or stdout.strip():
                        try:
                            info = json.loads(stdout)
                        except json.JSONDecodeError:
                            info = None
                        if isinstance(info, dict):
                            entries = info.get("entries")
                            if not isinstance(entries, list):
                                return None
                            unavailable = sum(not isinstance(entry, dict) for entry in entries)
                            if unavailable:
                                raise RuntimeError(
                                    f"Não foi possível ler os metadados de {unavailable} item(ns); "
                                    "a ordenação foi interrompida para não omitir conteúdo."
                                )
                            indexed_entries = _sort_playlist_entries(
                                entries,
                                options["playlist_sort"],
                                options.get("playlist_items", ""),
                                options.get("playlist_reverse", False),
                            )
                            if not indexed_entries:
                                raise RuntimeError("A seleção não contém itens disponíveis na lista.")
                            ordered_urls = []
                            for original_index, entry in indexed_entries:
                                item_url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
                                if not isinstance(item_url, str) or not item_url.startswith(("http://", "https://")):
                                    raise RuntimeError(
                                        f"Não foi possível obter o endereço do item {original_index} da lista."
                                    )
                                ordered_urls.append(item_url)
                            broadcast_log(
                                f"[INFO] Lista ordenada; {len(ordered_urls)} item(ns) segundo "
                                f"{options['playlist_sort']}."
                            )
                            return ordered_urls
                        last_error = stderr.strip() or "O yt-dlp devolveu metadados da lista inválidos."
                    else:
                        last_error = stderr.strip() or f"yt-dlp terminou com código {process.returncode}."
                    break
                except subprocess.TimeoutExpired:
                    continue
        except RuntimeError:
            raise
        except OSError as e:
            last_error = str(e)
        finally:
            current_process = None
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
    raise RuntimeError(f"Não foi possível ordenar a lista: {last_error}")


def _queue_persisted_copy(job):
    saved = dict(job)
    saved["options"] = dict(job.get("options", {}))
    proxy = saved["options"].pop("proxy", "")
    if proxy:
        saved["proxy_requires_reentry"] = True
    return saved


def _persist_queue_locked():
    temp_path = QUEUE_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(
            [_queue_persisted_copy(job) for job in _queue_jobs[-_QUEUE_MAX_JOBS:]],
            f,
            indent=2,
            ensure_ascii=False,
        )
    os.replace(temp_path, QUEUE_FILE)


def _load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        broadcast_log(f"[ERRO] Não foi possível carregar a fila persistida: {e}")
        return []
    if not isinstance(raw, list):
        broadcast_log("[ERRO] A fila persistida tem um formato inválido.")
        return []
    jobs = []
    for job in raw[-_QUEUE_MAX_JOBS:]:
        if not isinstance(job, dict) or not isinstance(job.get("id"), str):
            continue
        if job.get("status") == "running":
            job["status"] = "queued"
            job["error"] = "Retomado após reinício da aplicação."
        if job.get("proxy_requires_reentry") and job.get("status") == "queued":
            job["status"] = "failed"
            job["error"] = "O proxy não foi guardado por segurança. Recrie o download para o introduzir novamente."
        jobs.append(job)
    return jobs


def _public_queue_job(job):
    return {
        "id": job["id"],
        "urls": job.get("urls", []),
        "status": job.get("status", "queued"),
        "created_at": job.get("created_at"),
        "scheduled_at": job.get("scheduled_at"),
        "priority": job.get("priority", 0),
        "attempt": job.get("attempt", 0),
        "error": job.get("error", ""),
        "completed": job.get("completed", 0),
        "total": len(job.get("urls", [])),
    }


def _queue_snapshot():
    with _queue_lock:
        return [_public_queue_job(job) for job in _queue_jobs]


def _broadcast_queue():
    snapshot = _queue_snapshot()
    broadcast("QUEUE_UPDATED: true")
    return snapshot


def _validate_download_request(req):
    if not isinstance(req, dict):
        raise ValueError("Os dados do download são inválidos.")
    urls = req.get("urls")
    if not isinstance(urls, list):
        raise ValueError("A lista de URLs é inválida.")
    urls = [url.strip() for url in urls if isinstance(url, str) and url.strip()]
    if not urls or len(urls) > _QUEUE_MAX_URLS:
        raise ValueError(f"Introduza entre 1 e {_QUEUE_MAX_URLS} endereços.")

    mode = req.get("mode", "video")
    if not isinstance(mode, str) or mode not in {"video", "audio"}:
        raise ValueError("Tipo de download inválido.")
    quality = str(req.get("quality", "best"))
    valid_quality = {"best", "0", "2160", "1080", "720", "480"} if mode == "video" else {"0", "3", "5"}
    if quality not in valid_quality:
        raise ValueError("Qualidade inválida.")

    vformat = req.get("vformat", "mp4")
    if not isinstance(vformat, str) or vformat not in {"mp4", "mkv", "webm"}:
        raise ValueError("Formato de vídeo inválido.")
    audio_format = req.get("audio_format", "mp3")
    if not isinstance(audio_format, str) or audio_format not in {"mp3", "m4a", "opus", "wav", "flac", "vorbis"}:
        raise ValueError("Formato de áudio inválido.")

    clip_start = str(req.get("clip_start") or "").strip()
    clip_end = str(req.get("clip_end") or "").strip()
    if not _valid_time_value(clip_start) or not _valid_time_value(clip_end):
        raise ValueError("Use tempos de recorte em segundos ou HH:MM:SS.")
    if clip_end and not clip_start:
        raise ValueError("Indique também o início do recorte.")
    if clip_end and _time_value_seconds(clip_end) <= _time_value_seconds(clip_start):
        raise ValueError("O fim do recorte tem de ser posterior ao início.")

    playlist_value = req.get("playlist_items", "")
    if not isinstance(playlist_value, str):
        raise ValueError("A seleção de itens da lista é inválida.")
    playlist_items = playlist_value.strip()
    if playlist_items and (
        len(playlist_items) > 100
        or not re.fullmatch(r"\d+(?:(?:-|:)\d+)?(?:,\d+(?:(?:-|:)\d+)?)*", playlist_items)
    ):
        raise ValueError("A seleção de itens da lista contém caracteres inválidos.")
    playlist_sort = req.get("playlist_sort", "none")
    if not isinstance(playlist_sort, str) or playlist_sort not in {
        "none",
        "duration-shortest",
        "duration-longest",
        "quality-lowest",
        "quality-highest",
    }:
        raise ValueError("A ordenação da lista é inválida.")

    proxy_value = req.get("proxy", "")
    if not isinstance(proxy_value, str):
        raise ValueError("O proxy tem de ser um endereço de texto.")
    proxy = proxy_value.strip()
    if proxy:
        parsed_proxy = urlparse(proxy)
        if parsed_proxy.scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"} or not parsed_proxy.hostname:
            raise ValueError("O proxy deve ser um endereço HTTP(S) ou SOCKS válido.")

    scheduled_value = req.get("scheduled_at", "")
    if not isinstance(scheduled_value, str):
        raise ValueError("Data de agendamento inválida.")
    scheduled_at = scheduled_value.strip()
    if scheduled_at:
        try:
            scheduled_time = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            if scheduled_time.tzinfo is None:
                scheduled_time = scheduled_time.astimezone()
            scheduled_at = scheduled_time.isoformat()
        except ValueError as e:
            raise ValueError("Data de agendamento inválida.") from e

    priority = req.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int) or priority not in {-1, 0, 1}:
        raise ValueError("Prioridade inválida.")
    retry_count = req.get("retry_count", config.get("download_retries", 2))
    if isinstance(retry_count, bool) or not isinstance(retry_count, int) or not 0 <= retry_count <= 5:
        raise ValueError("O número de novas tentativas deve estar entre 0 e 5.")

    for key in ("subtitles", "embed_metadata", "embed_thumbnail", "embed_chapters", "write_info_json", "playlist_reverse"):
        if key in req and not isinstance(req[key], bool):
            raise ValueError(f"A opção '{key}' tem de ser booleana.")
    options = {
        "audio_format": audio_format,
        "embed_metadata": bool(req.get("embed_metadata")),
        "embed_thumbnail": bool(req.get("embed_thumbnail")),
        "embed_chapters": bool(req.get("embed_chapters")),
        "write_info_json": bool(req.get("write_info_json")),
        "playlist_items": playlist_items,
        "playlist_reverse": bool(req.get("playlist_reverse")),
        "playlist_sort": playlist_sort,
        "clip_start": clip_start,
        "clip_end": clip_end,
        "proxy": proxy,
        "retry_count": retry_count,
    }
    return {
        "urls": urls,
        "mode": mode,
        "quality": quality,
        "vformat": vformat,
        "subtitles": bool(req.get("subtitles")),
        "sub_mode": config.get("sub_mode", "none"),
        "sub_langs": config.get("sub_langs", "all"),
        "sub_auto": config.get("sub_auto", True),
        "options": options,
        "scheduled_at": scheduled_at,
        "priority": priority,
    }


def _process_queue_job(job):
    options = job.get("options", {})
    urls = job.get("urls", [])
    failed = False
    cancelled = False
    start_index = min(max(0, int(job.get("completed", 0))), len(urls))
    for index in range(start_index, len(urls)):
        source_url = urls[index]
        if download_cancel_requested:
            cancelled = True
            break

        item_options = options
        try:
            if options.get("playlist_sort", "none") != "none":
                broadcast_log("[INFO] A ler os metadados da lista para ordenar os itens.")
                sorted_urls = _extract_sorted_playlist_urls(
                    source_url, options
                )
                if sorted_urls is not None:
                    item_options = dict(options)
                    item_options.update(
                        playlist_sort="none",
                        playlist_items="",
                        playlist_reverse=False,
                    )
                    items = sorted_urls
                else:
                    items = [source_url]
            else:
                items = [source_url]
        except RuntimeError as e:
            if download_cancel_requested:
                cancelled = True
                break
            failed = True
            broadcast_log(f"[ERRO] {e}")
            with _queue_lock:
                job["completed"] = index + 1
                _persist_queue_locked()
            _broadcast_queue()
            continue

        for item_index, url in enumerate(items):
            if download_cancel_requested:
                cancelled = True
                break
            if len(items) > 1:
                broadcast_log(f"[INFO] Item ordenado {item_index + 1}/{len(items)}.")
            with _queue_lock:
                job["current_url"] = url
                job["attempt"] = 0
                _persist_queue_locked()
            broadcast(f"PLATFORM: {detect_platform(url)}")
            success = False
            file_path = None
            retries = options.get("retry_count", 2)
            for attempt in range(retries + 1):
                if download_cancel_requested:
                    cancelled = True
                    break
                with _queue_lock:
                    job["attempt"] = attempt + 1
                    _persist_queue_locked()
                success, file_path = run_download_with_fallback(
                    url,
                    job.get("mode", "video"),
                    job.get("quality", "best"),
                    job.get("vformat", "mp4"),
                    job.get("subtitles", False),
                    job.get("sub_mode", "none"),
                    job.get("sub_langs", "all"),
                    job.get("sub_auto", True),
                    item_options,
                )
                if success or download_cancel_requested:
                    break
                if attempt < retries:
                    delay = min(2 ** attempt, 10)
                    broadcast_log(f"[AVISO] Nova tentativa {attempt + 1} de {retries} em {delay} s.")
                    for _ in range(delay):
                        if download_cancel_requested:
                            cancelled = True
                            break
                        time.sleep(1)
            if cancelled:
                break

            rel_path = None
            if file_path and os.path.exists(file_path):
                try:
                    rel = os.path.relpath(file_path, get_downloads_dir()).replace("\\", "/")
                except ValueError:
                    rel = None
                if rel and not rel.startswith("..") and not os.path.isabs(rel):
                    rel_path = f"/downloads/{rel}"
                else:
                    rel_path = f"/downloads/{os.path.basename(file_path)}"

            save_history_entry(
                url,
                "lote" if len(urls) > 1 or len(items) > 1 else "singular",
                status="success" if success else "failed",
                file_path=rel_path,
                title=clean_media_title(file_path),
                platform=detect_platform(url),
                media_type=job.get("mode", "video"),
            )
            if not success:
                failed = True
                broadcast_log(f"[ERRO] Falha permanente para {url}")
            if item_index + 1 < len(items) and not download_cancel_requested:
                time.sleep(2)
        if cancelled:
            break

        with _queue_lock:
            job["completed"] = index + 1
            _persist_queue_locked()
        _broadcast_queue()
        if index + 1 < len(urls) and not download_cancel_requested:
            time.sleep(2)

    if cancelled or download_cancel_requested:
        return "cancelled", "Cancelado pelo utilizador."
    if failed:
        return "failed", "Um ou mais endereços falharam."
    return "completed", ""


def _queue_worker():
    global _queue_worker_running, _active_download_id, download_cancel_requested
    while True:
        job = None
        wait_seconds = None
        with _queue_lock:
            pending = [j for j in _queue_jobs if j.get("status") == "queued"]
            if not pending:
                _queue_worker_running = False
                return
            now = datetime.now().astimezone()

            def scheduled_time(item):
                raw = item.get("scheduled_at")
                if not raw:
                    return now
                try:
                    return datetime.fromisoformat(raw).astimezone()
                except (TypeError, ValueError):
                    return now

            ready = [j for j in pending if scheduled_time(j) <= now]
            if ready:
                ready.sort(key=lambda j: (-j.get("priority", 0), j.get("created_at", "")))
                job = ready[0]
                job["status"] = "running"
                job["started_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                job["error"] = ""
                _active_download_id = job["id"]
                download_cancel_requested = False
                for control_file in (PAUSE_FILE, CANCEL_FILE):
                    try:
                        os.remove(control_file)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        broadcast_log(f"[AVISO] Não foi possível limpar o controlo {os.path.basename(control_file)}: {e}")
                _persist_queue_locked()
            else:
                next_time = min(scheduled_time(j) for j in pending)
                wait_seconds = max(0.1, min((next_time - now).total_seconds(), 30))

        if job is None:
            _queue_wakeup.wait(wait_seconds)
            _queue_wakeup.clear()
            continue

        _broadcast_queue()
        broadcast("DOWNLOAD_STARTED: true")
        try:
            status, error = _process_queue_job(job)
        except Exception as e:
            status, error = "failed", str(e)
            broadcast_log(f"[ERRO] Erro inesperado na fila: {e}")
        with _queue_lock:
            job["status"] = status
            job["error"] = error
            job["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            _active_download_id = None
            download_cancel_requested = False
            for control_file in (PAUSE_FILE, CANCEL_FILE):
                try:
                    os.remove(control_file)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    broadcast_log(f"[AVISO] Não foi possível limpar o controlo {os.path.basename(control_file)}: {e}")
            _persist_queue_locked()
        broadcast("STATUS: " + ("Download concluído" if status == "completed" else ("Cancelado" if status == "cancelled" else "Download falhou")))
        broadcast("DOWNLOAD_FINISHED: true")
        _broadcast_queue()


def _start_queue_worker():
    global _queue_worker_running
    with _queue_lock:
        if _queue_worker_running or not any(j.get("status") == "queued" for j in _queue_jobs):
            return
        _queue_worker_running = True
        threading.Thread(target=_queue_worker, daemon=True).start()


def _enqueue_download(req):
    validated = _validate_download_request(req)
    with _queue_lock:
        job = {
            **validated,
            "id": uuid.uuid4().hex,
            "status": "queued",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "attempt": 0,
            "completed": 0,
            "error": "",
        }
        evicted = None
        evicted_index = None
        _queue_jobs.append(job)
        if len(_queue_jobs) > _QUEUE_MAX_JOBS:
            removable = next((j for j in _queue_jobs if j is not job and j.get("status") in _QUEUE_TERMINAL_STATES), None)
            if removable:
                evicted_index = _queue_jobs.index(removable)
                evicted = removable
                _queue_jobs.remove(removable)
            else:
                _queue_jobs.remove(job)
                raise ValueError("A fila está cheia; remova downloads concluídos antes de adicionar mais.")
        try:
            _persist_queue_locked()
        except OSError:
            _queue_jobs.remove(job)
            if evicted is not None:
                _queue_jobs.insert(evicted_index, evicted)
            raise
    _start_queue_worker()
    _queue_wakeup.set()
    _broadcast_queue()
    return job


def _queue_action(req):
    global download_cancel_requested
    if not isinstance(req, dict):
        raise ValueError("Ação da fila inválida.")
    job_id = req.get("id")
    action = req.get("action")
    if not isinstance(job_id, str) or action not in {"cancel", "remove", "retry"}:
        raise ValueError("Ação da fila inválida.")
    with _queue_lock:
        job = next((j for j in _queue_jobs if j.get("id") == job_id), None)
        if not job:
            raise ValueError("Download não encontrado na fila.")
        if action == "cancel":
            if job.get("status") == "queued":
                job["status"] = "cancelled"
                job["error"] = "Cancelado antes de iniciar."
            elif job.get("status") == "running":
                if _active_download_id != job_id:
                    raise ValueError("O download já não está ativo.")
                download_cancel_requested = True
                open(CANCEL_FILE, "w").close()
                try:
                    os.remove(PAUSE_FILE)
                except FileNotFoundError:
                    pass
            else:
                raise ValueError("Só é possível cancelar downloads pendentes ou ativos.")
        elif action == "remove":
            if job.get("status") == "running":
                raise ValueError("Cancele primeiro o download ativo.")
            _queue_jobs.remove(job)
        else:
            if job.get("status") not in {"failed", "cancelled"}:
                raise ValueError("Só é possível repetir downloads falhados ou cancelados.")
            if job.get("proxy_requires_reentry"):
                raise ValueError("O proxy não é guardado. Recrie o download para voltar a introduzi-lo.")
            job["status"] = "queued"
            job["scheduled_at"] = ""
            job["attempt"] = 0
            job["completed"] = 0
            job["error"] = ""
        _persist_queue_locked()
    _start_queue_worker()
    _queue_wakeup.set()
    _broadcast_queue()


_queue_jobs = _load_queue()


# ========== HANDLER HTTP ==========
class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        try:
            if message:
                clean = message.encode("ascii", errors="ignore").decode("ascii")
            else:
                clean = None
            super().send_error(code, clean, explain)
        except:
            self.send_response(code)
            self.end_headers()

    # Ficheiros estáticos permitidos (app shell + PWA). Nunca serve código/config por engano.
    STATIC_FILES = {
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
        "/sw.js": ("sw.js", "application/javascript"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    }

    def _serve_app_file(self, rel_path, mime=None, cache="no-store"):
        """Serve um ficheiro relativo a APP_DIR com proteção contra path traversal."""
        full = os.path.normpath(os.path.join(APP_DIR, rel_path))
        if not full.startswith(os.path.normpath(APP_DIR)) or not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        if not mime:
            mime, _ = mimetypes.guess_type(full)
            mime = mime or "application/octet-stream"
        try:
            with open(full, "rb") as f:
                body = f.read()
        except Exception:
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if rel_path.endswith("sw.js"):
            self.send_header("Service-Worker-Allowed", "/")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)

        if path.startswith("/downloads/"):
            rel = path[11:]
            if ".." in rel:
                self.send_response(404)
                self.end_headers()
                return
            fp = os.path.join(get_downloads_dir(), rel.replace("/", os.sep))
            if os.path.exists(fp) and os.path.isfile(fp):
                self.send_response(200)
                mime, _ = mimetypes.guess_type(fp)
                if not mime:
                    mime = "application/octet-stream"
                self.send_header("Content-type", mime)
                self.send_header("Content-Length", str(os.path.getsize(fp)))
                self.end_headers()
                with open(fp, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        if path == "/":
            idx = os.path.join(APP_DIR, "index.html")
            if os.path.exists(idx):
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with open(idx, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
            return

        if path in self.STATIC_FILES:
            rel, mime = self.STATIC_FILES[path]
            cache = "no-cache" if rel in ("sw.js", "index.html") else "public, max-age=86400"
            self._serve_app_file(rel, mime, cache)
            return

        if path.startswith("/icons/"):
            rel = path.lstrip("/")
            if ".." not in rel and rel.lower().endswith(".png"):
                self._serve_app_file(rel, "image/png", "public, max-age=604800")
                return
            self.send_response(404)
            self.end_headers()
            return

        if path == "/events":
            self.send_response(200)
            self.send_header("Content-type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            client = self.wfile
            clients.append(client)
            try:
                while True:
                    time.sleep(5)
                    client.write(b": ping\n\n")
                    client.flush()
            except:
                pass
            finally:
                if client in clients:
                    clients.remove(client)
            return

        if path == "/get_downloads":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(scan_downloads()).encode("utf-8"))
            return

        if path == "/get_config":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            cfg = config.copy()
            cfg["app_version"] = APP_VERSION
            cfg.setdefault("language", "pt")
            self.wfile.write(json.dumps(cfg).encode("utf-8"))
            return

        if path == "/get_categories":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"categories": get_categories_full()}).encode("utf-8"))
            return

        if path == "/get_history":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_json(HISTORY_FILE, [])).encode("utf-8"))
            return

        if path == "/get_queue":
            snapshot = _queue_snapshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/clear_history":
            if os.path.exists(HISTORY_FILE):
                os.remove(HISTORY_FILE)
            self.send_response(200)
            self.end_headers()
            return

        if path == "/system_status":
            info = {
                "python_version": platform.python_version(),
                "ytdlp_version": "N/A",
                "disk_total": "N/A",
                "disk_free": "N/A",
                "downloads_size": "N/A",
            }
            ytdlp = os.path.join(BIN_DIR, "yt-dlp.exe")
            if os.path.exists(ytdlp):
                try:
                    res = subprocess.run(
                        [ytdlp, "--version"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    info["ytdlp_version"] = res.stdout.strip()
                except:
                    pass
            try:
                total, used, free = shutil.disk_usage(get_downloads_dir())

                def fmt(b):
                    return f"{b / 1e9:.2f} GB"

                info["disk_total"] = fmt(total)
                info["disk_free"] = fmt(free)
                info["downloads_size"] = fmt(get_folder_size(get_downloads_dir()))
            except:
                pass
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(info).encode("utf-8"))
            return

        if path == "/init_log":
            broadcast("LOG_CLEAR: true")
            broadcast_log(f"[OK] YT-DLP Media Desk v{APP_VERSION} - Servidor ativo")
            broadcast_log("[OK] Sistema pronto. Use as estratégias de autenticação configuradas.")
            self.send_response(200)
            self.end_headers()
            return

        if path == "/update_ytdlp":
            threading.Thread(
                target=run_command,
                args=([os.path.join(BIN_DIR, "yt-dlp.exe"), "-U"], "Atualizado."),
            ).start()
            self.send_response(200)
            self.end_headers()
            return

        if path == "/get_python_pref":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"mode": get_python_pref()}).encode())
            return

        if path == "/get_licenses":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_licenses()).encode("utf-8"))
            return

        if path == "/get_integrity":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(get_integrity_status()).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global download_cancel_requested
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8") if length else "{}"

        if self.path == "/browse_folder":
            try:
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                req = json.loads(data) if data else {}
                # O titulo do dialogo e escolhido pelo cliente (ex.: escolher a
                # pasta de downloads ou uma pasta externa de destino).
                title = str(req.get("title") or "").strip() or "Escolha a pasta de downloads"
                chosen = pick_folder_native(title)
                self.wfile.write(json.dumps({"path": chosen or ""}).encode("utf-8"))
            except Exception as e:
                self.send_error(500, str(e))
            return

        if self.path == "/show_in_folder":
            # Abre o Explorador com o ficheiro descarregado selecionado.
            try:
                req = json.loads(data) if data else {}
                abs_req = str(req.get("absolute") or "").strip()
                if abs_req:
                    # So se revelam caminhos absolutos que a propria app registou
                    # no historico (ficheiros movidos para fora da app).
                    cand = os.path.normpath(abs_req)
                    full = cand if os.path.normcase(cand) in get_recorded_move_paths() else None
                else:
                    full = resolve_download_file(req.get("path", ""))
                if full is None:
                    ok, err = False, "invalid_path"
                else:
                    ok, err = show_in_folder(full)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": ok, "error": err}).encode("utf-8"))
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/save_categories":
            # Guarda a lista de gavetas e cria as respetivas pastas.
            try:
                req = json.loads(data)
                raw = req.get("categories", [])
                if not isinstance(raw, list):
                    raise ValueError("categories tem de ser uma lista")
                cats = []
                rejected = []
                seen = set()
                for item in raw:
                    if isinstance(item, dict):
                        clean = sanitize_category_name(item.get("name"))
                        media = item.get("media")
                        color = sanitize_category_color(item.get("color"))
                    else:
                        clean = sanitize_category_name(item)
                        media = _LEGACY_MEDIA
                        color = None
                    if not clean:
                        if isinstance(item, str) and item.strip():
                            rejected.append(item.strip())
                        elif isinstance(item, dict) and str(item.get("name") or "").strip():
                            rejected.append(str(item.get("name")).strip())
                        continue
                    # A pasta e unica no disco: o nome nao pode repetir-se
                    # entre areas (mudar de area num nome existente e aceite).
                    if clean.lower() in seen:
                        continue
                    seen.add(clean.lower())
                    cats.append({
                        "name": clean,
                        "media": media if media in _VALID_MEDIA else _LEGACY_MEDIA,
                        "color": color or default_category_color(clean),
                    })
                config["categories"] = cats
                save_json(CONFIG_FILE, config)
                created = []
                for c in cats:
                    try:
                        if not os.path.isdir(category_dir(c["name"])):
                            ensure_category_dir(c["name"])
                            created.append(c["name"])
                    except Exception:
                        pass
                broadcast_log(f"[INFO] Gavetas guardadas: {len(cats)}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "categories": get_categories_full(),
                    "created": created,
                    "rejected": rejected,
                }).encode("utf-8"))
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/remove_category":
            # Remove uma gaveta (dissolve=True devolve os ficheiros a raiz).
            try:
                req = json.loads(data)
                name = req.get("name", "")
                dissolve = req.get("dissolve", True)
                ok, err, moved = remove_category(name, dissolve=bool(dissolve))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if ok:
                    broadcast_log(f"[INFO] Gaveta removida: {name} ({moved} devolvido(s))")
                    self.wfile.write(json.dumps({
                        "ok": True,
                        "categories": get_categories_full(),
                        "moved": moved,
                    }).encode("utf-8"))
                else:
                    self.wfile.write(json.dumps({"ok": False, "error": err}).encode("utf-8"))
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/move_files":
            # Movimentacao interna (gaveta) ou externa (pasta escolhida na hora).
            try:
                req = json.loads(data)
                paths = req.get("paths", [])
                destination = req.get("destination", {})
                if not isinstance(paths, list) or not paths:
                    raise ValueError("Sem ficheiros para mover")
                if not isinstance(destination, dict):
                    raise ValueError("Destino invalido")
                results, moved = move_files(paths, destination)
                failed = len(results) - moved
                if destination.get("kind") == "external":
                    broadcast_log(f"[INFO] Movidos {moved} ficheiro(s) para {destination.get('dir') or '?'}")
                else:
                    target = destination.get("name") or "raiz"
                    broadcast_log(f"[INFO] Movidos {moved} ficheiro(s) para a gaveta '{target}'")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "ok": failed == 0,
                    "moved": moved,
                    "failed": failed,
                    "results": results,
                }).encode("utf-8"))
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/save_config":
            # Nota: config e mutado no lugar (nunca reatribuido), por isso nao
            # precisa da declaracao global - que alias colidiria com o uso de
            # config nos ramos anteriores deste metodo.
            try:
                new = json.loads(data)
                if not isinstance(new, dict):
                    raise ValueError("As definições têm de ser um objeto JSON.")
                if "auto_quality_recommendation" in new and not isinstance(
                    new["auto_quality_recommendation"], bool
                ):
                    raise ValueError("A recomendação automática tem de ser booleana.")
                config.update(new)
                save_json(CONFIG_FILE, config)
                self.send_response(200)
                self.end_headers()
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/save_auth":
            try:
                auth = json.loads(data)
                config.update(
                    {
                        "use_po_token": auth.get("use_po_token", False),
                        "po_token": auth.get("po_token", ""),
                        "visitor_data": auth.get("visitor_data", ""),
                    }
                )
                save_json(CONFIG_FILE, config)
                self.send_response(200)
                self.end_headers()
            except:
                self.send_response(200)
                self.end_headers()
            return

        if self.path == "/set_python_pref":
            try:
                req = json.loads(data)
                mode = req.get("mode", 1)
                set_python_pref(mode)
                self.send_response(200)
                self.end_headers()
            except:
                self.send_error(400, "Dados inválidos")
            return

        if self.path == "/download":
            try:
                req = json.loads(data)
                job = _enqueue_download(req)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "id": job["id"]}).encode("utf-8"))
            except ValueError as e:
                self.send_error(400, str(e))
            except Exception as e:
                self.send_error(500, str(e))
            return

        if self.path == "/pause_download":
            try:
                d = json.loads(data)
                if _active_download_id is None:
                    self.send_error(409, "Não há download ativo.")
                    return
                if d.get("pause", True):
                    open(PAUSE_FILE, "w").close()
                    broadcast_log("[INFO] Pausado")
                else:
                    if os.path.exists(PAUSE_FILE):
                        os.remove(PAUSE_FILE)
                    broadcast_log("[INFO] Continuado")
                self.send_response(200)
                self.end_headers()
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/cancel_download":
            try:
                with _queue_lock:
                    if _active_download_id is None:
                        raise ValueError("Não há download ativo.")
                    download_cancel_requested = True
                    open(CANCEL_FILE, "w").close()
                    try:
                        os.remove(PAUSE_FILE)
                    except FileNotFoundError:
                        pass
                broadcast_log("[INFO] Cancelamento solicitado")
                self.send_response(200)
                self.end_headers()
            except ValueError as e:
                self.send_error(409, str(e))
            except OSError as e:
                self.send_error(500, str(e))
            return

        if self.path == "/queue_action":
            try:
                _queue_action(json.loads(data))
                self.send_response(200)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            except ValueError as e:
                self.send_error(400, str(e))
            except OSError as e:
                self.send_error(500, str(e))
            return

        if self.path == "/delete_files":
            try:
                req = json.loads(data)
                paths = req.get("paths", [])
                remove_file = req.get("remove_file", True)
                remove_history = req.get("remove_history", True)
                
                history_removed = 0
                
                for path in paths:
                    if remove_file:
                        rel2 = path.lstrip("/")
                        if rel2.startswith("downloads/"):
                            rel2 = rel2[len("downloads/"):]
                        if not rel2 or ".." in rel2:
                            continue
                        full_path = os.path.join(get_downloads_dir(), rel2.replace("/", os.sep))
                        if os.path.exists(full_path):
                            os.remove(full_path)
                            parent_dir = os.path.dirname(full_path)
                            if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                                os.rmdir(parent_dir)
                    
                    if remove_history:
                        history = load_json(HISTORY_FILE, [])
                        history = [h for h in history if path not in str(h)]
                        save_json(HISTORY_FILE, history)
                        history_removed += 1
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "history_removed": history_removed
                }).encode("utf-8"))
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/remove_history_entry":
            try:
                req = json.loads(data)
                url = req.get("url")
                
                if url:
                    history = load_json(HISTORY_FILE, [])
                    history = [entry for entry in history if entry.get("url") != url]
                    save_json(HISTORY_FILE, history)
                    broadcast_log(f"[INFO] Entrada do histórico removida: {url}")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                else:
                    self.send_error(400, "URL não fornecida")
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/remove_history_by_path":
            try:
                req = json.loads(data)
                file_path = req.get("file_path")
                
                if file_path:
                    history = load_json(HISTORY_FILE, [])
                    history = [entry for entry in history if entry.get("file_path") != file_path]
                    save_json(HISTORY_FILE, history)
                    broadcast_log(f"[INFO] Entrada do histórico removida para: {file_path}")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                else:
                    self.send_error(400, "Caminho não fornecido")
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/restart_server":
            self.send_response(200)
            self.end_headers()
            threading.Timer(
                1.0, lambda: os.execl(sys.executable, sys.executable, *sys.argv)
            ).start()
            return

        self.send_response(404)
        self.end_headers()


class QuietServer(ThreadingHTTPServer):
    """ThreadingHTTPServer que silencia erros de ligacao anulada/resetada.

    Clientes (browser, launcher) fecham ligacoes a meio de pedidos — ex.: ao
    recarregar a pagina, no polling/SSE — o que gera ConnectionAbortedError /
    ConnectionResetError / BrokenPipeError. Sao inofensivos e nao devem sujar
    a consola com tracebacks.

    IMPORTANTE: allow_reuse_address = False. No Windows, SO_REUSEADDR (padrao
    do HTTPServer) permite fazer bind de uma porta ja ocupada por OUTRO
    processo, o que "engana" o fallback de portas em run_server() e faz a UI
    abrir a instancia errada. Sem SO_REUSEADDR, o bind falha com
    WSAEADDRINUSE e o servidor avanca para a porta seguinte.
    """

    allow_reuse_address = False

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def run_command(cmd, success_msg):
    try:
        subprocess.run(cmd, cwd=APP_DIR)
        broadcast_log(f"[OK] {success_msg}")
    except Exception as e:
        broadcast_log(f"[ERRO] Erro: {e}")


def run_server():
    global server_instance
    os.chdir(APP_DIR)

    # Se a porta configurada estiver ocupada (ex.: outra instancia ja ativa, ou
    # um servidor de desenvolvimento), tenta as seguintes ate encontrar uma
    # livre. A porta REAL e sempre reportada ao launcher via
    # MEDIADESK_RESPONSE_FILE — assim a UI nunca abre outra instancia que
    # esteja a servir a porta configurada.
    base_port = config.get("server_port", 8181)
    server = None
    actual_port = None
    for port in range(base_port, base_port + 20):
        try:
            server = QuietServer(("0.0.0.0", port), Handler)
            actual_port = port
            break
        except OSError as e:
            print(f"[AVISO] Porta {port} ocupada ({e}). A tentar a seguinte...")
            continue
    if server is None or actual_port is None:
        print(f"[ERRO] Sem portas livres entre {base_port} e {base_port + 19}.")
        if os.environ.get("MEDIADESK_RESPONSE_FILE"):
            try:
                with open(os.environ["MEDIADESK_RESPONSE_FILE"], "w", encoding="utf-8") as fh:
                    json.dump({"error": "Sem portas livres"}, fh)
            except Exception:
                pass
        return

    server_instance = server
    _start_queue_worker()
    print(f"\n[INFO] Servidor ativo em http://localhost:{actual_port}")
    print("[INFO] Pressione Ctrl+C para parar\n")

    # Reportar a porta real ao launcher (so ele abre a UI com ESTA instancia).
    if os.environ.get("MEDIADESK_RESPONSE_FILE"):
        try:
            with open(os.environ["MEDIADESK_RESPONSE_FILE"], "w", encoding="utf-8") as fh:
                json.dump({"port": actual_port}, fh)
        except Exception:
            pass

    if not os.environ.get("MEDIADESK_NO_BROWSER"):
        webbrowser.open(f"http://localhost:{actual_port}")

    threading.Thread(target=lambda: (time.sleep(1), broadcast("SYSTEM_READY: true"))).start()

    try:
        server.serve_forever()
    except OSError as e:
        print(f"[ERRO] {e}")
    except KeyboardInterrupt:
        print("\n[INFO] Servidor encerrado")


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print(f" YT-DLP MEDIA DESK SERVER v{APP_VERSION} - Auto Fallback + Filtros + Link-Ficheiro + PWA + Portatil")
    print("=" * 50)
    check_dependencies()
    threading.Thread(target=integrity_worker, daemon=True).start()
    run_server()