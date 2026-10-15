#!/usr/bin/env python3
# YT-DLP Interface Server - v3.1.0 com auto‑fallback, gestão de Python, filtros UI e associação link-ficheiro

import hashlib
import json
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
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
APP_VERSION = "3.7.1"  # gerado por tools/sync_version.ps1

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
            subprocess.Popen(["explorer", path if is_dir else ("/select," + path)])
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
    broadcast("DOWNLOAD_STARTED: true")

    for f in [PAUSE_FILE, CANCEL_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

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

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
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
        error_detected = False
        downloaded_file_path = None

        def remember(path):
            nonlocal downloaded_file_path
            path = (path or "").strip().strip('"')
            if path:
                downloaded_file_path = path
                broadcast(f"FILENAME: {os.path.basename(path)}")

        for line in iter(process.stdout.readline, ""):
            if not line:
                continue
            if os.path.exists(CANCEL_FILE):
                broadcast_log("Cancelado pelo utilizador")
                process.terminate()
                break
            while os.path.exists(PAUSE_FILE):
                download_paused = True
                time.sleep(1)
            download_paused = False

            if "Sign in to confirm" in line or "HTTP Error 403" in line:
                error_detected = True
                broadcast_log("[AVISO] Erro de autenticação detectado")
                process.terminate()
                break

            fm = regex_final.search(line) or regex_audio.search(line)
            if fm:
                remember(fm.group(1))

            fd = regex_dest.search(line) or regex_exists.search(line)
            if fd:
                remember(fd.group(1))

            p = regex_progress.search(line)
            if p:
                broadcast(f"PROGRESS: {p.group(1)}")
            else:
                clean = line.strip()
                if clean:
                    broadcast(f"LOG: {clean}")

        process.wait()
        if error_detected or process.returncode != 0:
            return False, None
        final_path = pick_final_file(downloaded_file_path)
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
        current_process = None
        broadcast("PROGRESS: 0")


def run_download_with_fallback(
    url, mode, quality, vformat, subtitles, sub_mode, sub_langs, sub_auto
):
    broadcast_log(f"[INFO] Iniciando download: {url}")
    broadcast(f"PLATFORM: {detect_platform(url)}")
    ytdlp = os.path.join(BIN_DIR, "yt-dlp.exe")
    # Agrupamento opcional por uploader/canal: downloads/<canal>/<titulo>.<ext>
    # Caso contrario: downloads/<titulo>/<titulo>.<ext>
    out_dir = get_downloads_dir()
    if config.get("group_by_uploader"):
        output_template = os.path.join(out_dir, "%(uploader,channel)s", "%(title)s.%(ext)s")
    else:
        output_template = os.path.join(out_dir, "%(title)s", "%(title)s.%(ext)s")

    base_cmd = [ytdlp, "-o", output_template]
    base_cmd.extend(
        [
            "--no-mtime",
            "--extractor-retries",
            "3",
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
            ["-x", "--audio-format", "mp3", "--audio-quality", str(quality)]
        )
    else:
        if quality == "best" or quality == "0":
            fmt = "bestvideo+bestaudio/best"
        else:
            fmt = f"bestvideo[height<={quality}][ext={vformat}]+bestaudio[ext=m4a]/best[height<={quality}][ext={vformat}]/best"
        base_cmd.extend(["-f", fmt, "--merge-output-format", vformat])

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
        broadcast_log(f"[INFO] A tentar: {name}")
        success, file_path = execute_cmd_and_check(cmd)
        if success:
            broadcast_log(f"[OK] Sucesso com {name}")
            return True, file_path
        else:
            broadcast_log(f"[ERRO] Falha na estratégia: {name}")

    broadcast_log("[ERRO] Todas as estratégias falharam.")
    return False, None


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
                        [ytdlp, "--version"], capture_output=True, text=True
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
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8") if length else "{}"

        if self.path == "/browse_folder":
            try:
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                chosen = pick_folder_native()
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
                urls = req.get("urls", [])
                mode = req.get("mode", "video")
                quality = req.get("quality", "best")
                subtitles = req.get("subtitles", False)
                vformat = req.get("vformat", "mp4")
                sub_mode = config.get("sub_mode", "none")
                sub_langs = config.get("sub_langs", "all")
                sub_auto = config.get("sub_auto", True)

                if not urls:
                    self.send_error(400, "Sem URL")
                    return

                def worker():
                    download_type = "lote" if len(urls) > 1 else "singular"
                    for url in urls:
                        if url.strip():
                            success, file_path = run_download_with_fallback(
                                url.strip(),
                                mode,
                                quality,
                                vformat,
                                subtitles,
                                sub_mode,
                                sub_langs,
                                sub_auto,
                            )
                            
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
                                url.strip(),
                                download_type,
                                status="success" if success else "failed",
                                file_path=rel_path,
                                title=clean_media_title(file_path),
                                platform=detect_platform(url.strip()),
                                media_type=mode
                            )
                            if not success:
                                broadcast_log(f"[ERRO] Falha permanente para {url}")
                            time.sleep(2)

                threading.Thread(target=worker).start()
                self.send_response(200)
                self.end_headers()
            except Exception as e:
                self.send_error(400, str(e))
            return

        if self.path == "/pause_download":
            try:
                d = json.loads(data)
                if d.get("pause", True):
                    open(PAUSE_FILE, "w").close()
                    broadcast_log("[INFO] Pausado")
                else:
                    if os.path.exists(PAUSE_FILE):
                        os.remove(PAUSE_FILE)
                    broadcast_log("[INFO] Continuado")
                self.send_response(200)
                self.end_headers()
            except:
                self.send_response(200)
                self.end_headers()
            return

        if self.path == "/cancel_download":
            open(CANCEL_FILE, "w").close()
            if os.path.exists(PAUSE_FILE):
                os.remove(PAUSE_FILE)
            broadcast_log("[INFO] Cancelamento solicitado")
            self.send_response(200)
            self.end_headers()
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