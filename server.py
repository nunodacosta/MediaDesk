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
from concurrent.futures import ThreadPoolExecutor
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
CONFIG_FILE = os.path.join(APP_DIR, "data", "config.enc")
HISTORY_FILE = os.path.join(APP_DIR, "history.json")
DEFAULT_DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")
PAUSE_FILE = os.path.join(APP_DIR, ".pause")
CANCEL_FILE = os.path.join(APP_DIR, ".cancel")
QUEUE_FILE = os.path.join(APP_DIR, "download_queue.json")
RSS_FILE = os.path.join(APP_DIR, "rss_channels.json")
RSS_PROPOSALS_FILE = os.path.join(APP_DIR, "rss_proposals.json")
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
_dependencies_ready = threading.Event()
_dependencies_ready.set()
_queue_jobs = []
_queue_worker_running = False
_active_download_id = None
APP_VERSION = "3.11.4"  # gerado por tools/sync_version.ps1
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
    return True


def load_rss_channels():
    try:
        if os.path.exists(RSS_FILE):
            with open(RSS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def save_rss_channels(channels):
    try:
        return save_json(RSS_FILE, channels)
    except Exception:
        return False


def load_rss_proposals():
    try:
        if os.path.exists(RSS_PROPOSALS_FILE):
            with open(RSS_PROPOSALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {"proposed": [], "seen": []}


def save_rss_proposals(data):
    try:
        return save_json(RSS_PROPOSALS_FILE, data)
    except Exception:
        return False


def analyze_user_focus():
    history = load_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        return {"channels": [], "platforms": []}
    counts = {}
    for h in history:
        if h.get("status") != "success":
            continue
        plat = h.get("platform") or (detect_platform(h.get("url")) if h.get("url") else None)
        if not plat:
            continue
        key = plat
        counts[key] = counts.get(key, 0) + 1
    platforms = [p for p,_ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]]
    return {"channels": [], "platforms": platforms}


def suggest_rss_from_history():
    focus = analyze_user_focus()
    channels = []
    seen = set()
    for p in focus.get("platforms", []):
        ch = {"name": p, "platform": p, "source": "history", "enabled": True}
        k = (ch["name"].lower(), ch["platform"])
        if k not in seen:
            channels.append(ch)
            seen.add(k)
    return channels


# ========== SERVICO DE ATIVIDADE / AUTOMATISMO ==========
# O servico vive num processo Python separado (activity_service.py), para
# continuar a monitorizar os feeds mesmo com a interface fechada. Estas
# funcoes sao a ponte entre o servidor HTTP e esse processo.
_activity_module = None
_activity_import_error = None
_activity_lock = threading.Lock()

_PLATFORM_BY_EXTRACTOR = {
    "youtube": "youtube",
    "youtube:tab": "youtube",
    "youtube:playlist": "youtube",
    "tiktok": "tiktok",
    "instagram": "instagram",
    "facebook": "facebook",
    "twitter": "x",
    "twitter:broadcast": "x",
    "vimeo": "vimeo",
    "twitch": "twitch",
    "twitch:vod": "twitch",
    "soundcloud": "soundcloud",
    "rumble": "rumble",
    "odysee": "odysee",
    "dailymotion": "dailymotion",
    "bitchute": "bitchute",
    "kick": "kick",
    "bilibili": "bilibili",
}


def activity_module():
    """Importa activity_service.py de forma preguicosa e segura."""
    global _activity_module, _activity_import_error
    if _activity_module is not None:
        return _activity_module
    with _activity_lock:
        if _activity_module is not None:
            return _activity_module
        if _activity_import_error is not None:
            return None
        try:
            if APP_DIR not in sys.path:
                sys.path.insert(0, APP_DIR)
            import activity_service as module  # noqa: WPS433 (import tardio propositado)
            _activity_module = module
        except Exception as exc:
            _activity_import_error = str(exc)
            print(f"[AVISO] Servico de atividade indisponivel: {exc}")
        return _activity_module


def load_config():
    module = activity_module()
    if module is None:
        raise RuntimeError(f"Servico de configuracao indisponivel: {_activity_import_error}")
    return module.load_config(APP_DIR)


def save_config(data):
    module = activity_module()
    if module is None:
        raise RuntimeError(f"Servico de configuracao indisponivel: {_activity_import_error}")
    module.save_config(data, APP_DIR)


def _resolve_download_path(file_path):
    """Converte '/downloads/x/y.mp4' (ou caminho absoluto) em caminho real.

    Nunca devolve ficheiros fora da pasta de downloads, mesmo que o pedido
    traga um caminho absoluto (ex.: C:/Windows/...).
    """
    raw = str(file_path or "").strip()
    if not raw:
        return None
    base = os.path.normpath(get_downloads_dir())
    candidate = resolve_download_file(raw)
    if candidate and os.path.isfile(candidate):
        return candidate
    if os.path.isabs(raw):
        full = os.path.normpath(raw)
        if os.path.normcase(full).startswith(os.path.normcase(base + os.sep)) and os.path.isfile(full):
            return full
    return None


def _read_info_json(file_path):
    """Le o sidecar <media>.info.json, se o yt-dlp o tiver escrito."""
    path = _resolve_download_path(file_path)
    if not path:
        return {}
    sidecar = os.path.splitext(path)[0] + ".info.json"
    try:
        with open(sidecar, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _meta_platform(info, url):
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").strip().lower()
    if extractor in _PLATFORM_BY_EXTRACTOR:
        return _PLATFORM_BY_EXTRACTOR[extractor]
    for candidate in (info.get("webpage_url"), info.get("original_url"), url):
        if candidate:
            detected = detect_platform(candidate)
            if detected and detected != "web":
                return detected
    return detect_platform(url) if url else "web"


def _safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _activity_entry(url, file_path, media_type=None, title=None, platform=None, meta=None):
    """Normaliza metadados de um download para o formato de activity.enc."""
    info = dict(meta or {})
    for key, value in _read_info_json(file_path).items():
        if info.get(key) in (None, "", 0, [], {}):
            info[key] = value
    path = _resolve_download_path(file_path)
    info_url = info.get("webpage_url") or info.get("original_url") or url
    info_platform = (platform or "").lower() or _meta_platform(info, info_url)
    entry = {
        "url": info_url,
        "original_url": url,
        "title": title or info.get("title") or (os.path.basename(path) if path else None),
        "platform": info_platform,
        "channel": info.get("channel") or info.get("uploader") or info.get("creator") or "",
        "channel_id": info.get("channel_id") or "",
        "channel_url": info.get("channel_url") or "",
        "uploader": info.get("uploader") or info.get("channel") or info.get("artist") or "",
        "uploader_id": info.get("uploader_id") or "",
        "uploader_url": info.get("uploader_url") or "",
        "date": datetime.now().astimezone().isoformat(timespec="microseconds"),
        "file_path": file_path,
        "file_name": os.path.basename(path) if path else None,
        "file_size": os.path.getsize(path) if path else _safe_int(info.get("filesize")),
        "media_type": media_type or info.get("ext") or None,
        "theme": config.get("theme_palette") or "indigo",
        "theme_mode": config.get("theme") or "system",
        "duration": _safe_int(info.get("duration")),
        "view_count": _safe_int(info.get("view_count")),
        "upload_date": info.get("upload_date") or info.get("release_date"),
        "ext": info.get("ext"),
        "width": _safe_int(info.get("width")),
        "height": _safe_int(info.get("height")),
        "tags": [str(t)[:60] for t in (info.get("tags") or [])][:20],
        "thumbnail": info.get("thumbnail"),
        "description": (info.get("description") or "")[:500],
        "extractor": info.get("extractor"),
        "source": "yt-dlp",
    }
    return {key: value for key, value in entry.items() if value not in (None, "", [], {})}


def record_activity_entry(entry):
    """Regista um download em activity.enc. Nunca interrompe o download."""
    svc = activity_module()
    if not svc:
        return None
    try:
        return svc.record_download(entry, APP_DIR)
    except Exception as exc:
        print(f"[AVISO] Falha ao registar atividade: {exc}")
        return None


def _automation_status():
    svc = activity_module()
    status = {
        "available": bool(svc),
        "enabled": bool(config.get("automation_enabled")),
        "mode": config.get("automation_mode", "manual"),
        "interval": int(config.get("automation_interval") or 30),
        "autostart": bool(config.get("automation_autostart")),
        "platforms": list(config.get("automation_platforms") or []),
        "running": False,
        "pid": None,
        "last_check": None,
        "next_check": None,
        "proposals": len(load_rss_proposals().get("proposed") or []),
        "channels": len(load_rss_channels()),
        "errors": [],
    }
    if svc:
        try:
            status.update(svc.service_status(APP_DIR))
            status["available"] = True
        except Exception as exc:
            status["error"] = str(exc)
    return status


def _start_automation_service(delay=2.5):
    """Lanca o servico em segundo plano, sem atrasar o arranque do servidor."""
    if not config.get("automation_enabled"):
        return

    def _launch():
        if delay:
            time.sleep(delay)
        svc = activity_module()
        if not svc:
            return
        try:
            ok = svc.start_service(APP_DIR)
            print(f"[INFO] Servico de atividade: {'iniciado' if ok else 'indisponivel'}")
        except Exception as exc:
            print(f"[AVISO] Nao foi possivel iniciar o servico de atividade: {exc}")

    threading.Thread(target=_launch, name="activity-launcher", daemon=True).start()


def _rss_check_background():
    """Corre uma verificacao unica de feeds sem bloquear o pedido HTTP."""
    def _run():
        svc = activity_module()
        if not svc:
            return
        try:
            svc.check_feeds(APP_DIR, force=True)
        except Exception as exc:
            print(f"[AVISO] Verificacao de feeds falhou: {exc}")

    threading.Thread(target=_run, name="rss-check", daemon=True).start()


def _normalize_channel(req):
    name = str(req.get("name") or "").strip()[:120]
    url = str(req.get("url") or "").strip()[:2048]
    if url and "://" not in url:
        url = "https://" + url
    if url:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().lower()
        valid_host = (
            bool(host)
            and re.fullmatch(r"[a-z0-9.\-]+", host) is not None
            and ("." in host or host == "localhost" or re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host))
        )
        if parsed.scheme not in ("http", "https") or not valid_host:
            raise ValueError("URL do canal inválida (use http:// ou https:// com um domínio válido).")
        if any(ch.isspace() for ch in url):
            raise ValueError("URL do canal inválida.")
    if not name and not url:
        raise ValueError("Indique um nome ou uma URL de canal.")
    platform = str(req.get("platform") or "").strip().lower()
    if not platform and url:
        platform = detect_platform(url)
    # Identificador simples: nunca aceitar texto livre vindo do cliente.
    platform = re.sub(r"[^a-z0-9_.\-]+", "", platform or "")[:40] or "web"
    return {
        "name": name or platform or "Canal",
        "url": url,
        "platform": platform,
        "enabled": bool(req.get("enabled", True)),
    }


def _json_reply(handler, code, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except Exception:
        pass


def _activity_suggestions():
    """Canais reais observados nos downloads (para adicionar ao RSS)."""
    svc = activity_module()
    if not svc or not hasattr(svc, "suggestion_channels"):
        return []
    try:
        return svc.suggestion_channels(APP_DIR) or []
    except Exception:
        return []


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


# ========== MOTOR DE VERSAO (COMPARACAO DE FICHEIROS EM CADA ARRANQUE) ==========
# Ficheiros cujo conteudo define a versao da aplicacao. O binario do yt-dlp
# fica de fora: e atualizado em runtime (-U) e nao faz parte desta versao.
VERSION_TRACKED = (
    "index.html",
    "server.py",
    "activity_service.py",
    "sw.js",
    "licenses.json",
    "manifest.webmanifest",
    "favicon.svg",
)
_version_lock = threading.Lock()
_updates_cache = {"quando": 0.0, "dados": None}
_libraries_cache = {"quando": 0.0, "dados": None, "running": False, "loaded": False, "done": threading.Event()}
_libraries_cache["done"].set()
_libraries_lock = threading.Lock()
# O splash nunca deve esperar pela rede nem por executaveis externos. O ultimo
# resultado fica em memoria e em disco; quando expira, e refrescado em segundo
# plano e a interface usa imediatamente o valor conhecido.
LIBRARIES_CACHE_FILE = os.path.join(APP_DIR, "data", "libraries_cache.json")
LIBRARIES_TTL = 600
LIBRARIES_SPLASH_TTL = 6 * 3600
_ytdlp_version_cache = {"key": None, "version": None}
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _js(value):
    """Literal JavaScript seguro (aspas e escapes) para o bloco VERSION."""
    return json.dumps(str(value), ensure_ascii=False)


def _read_text(path):
    # utf-8-sig remove o BOM se existir (e comporta-se como utf-8 se nao).
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return fh.read()


def _write_text(path, text, bom=False):
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        fh.write(text)


def _has_bom(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(3) == b"\xef\xbb\xbf"
    except Exception:
        return False


def _bump_semver(version, level):
    parts = str(version or "0.0.0").split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        major, minor, patch = (int(p) for p in parts[:3])
    except ValueError:
        major, minor, patch = 0, 0, 0
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _next_build(date, previous):
    code = int(str(date).replace("-", ""))
    try:
        prev = int(previous)
    except (TypeError, ValueError):
        prev = 0
    return prev + 1 if prev // 100 == code else code * 100 + 1


def _version_block(vj):
    """Gera o bloco // VERSION:BEGIN ... END a partir de version.json."""
    pad = " " * 12
    lines = ["// VERSION:BEGIN - gerado por tools/sync_version.ps1; nao editar a mao."]
    lines.append(f"{pad}const APP_VERSION = {_js(vj.get('version'))};")
    lines.append(f"{pad}const APP_VERSION_DATE = {_js(vj.get('date'))};")
    lines.append(f"{pad}const APP_BUILD = {int(vj.get('build') or 0)};")
    lines.append(f"{pad}const VERSION_HISTORY = [")
    entries = []
    for entry in vj.get("history") or []:
        if not isinstance(entry, dict):
            continue
        e = ["                {"]
        e.append(f"                    version: {_js(entry.get('version'))},")
        e.append(f"                    date: {_js(entry.get('date'))},")
        groups = entry.get("groups")
        if isinstance(groups, dict) and groups:
            e.append("                    groups: {")
            for name, items in groups.items():
                items = [str(i) for i in (items or [])]
                e.append(
                    f"                        {_js(name)}: [{', '.join(_js(i) for i in items)}],"
                )
            e.append("                    }")
        else:
            changes = [str(c) for c in (entry.get("changes") or [])]
            e.append(f"                    changes: [{', '.join(_js(c) for c in changes)}]")
        e.append("                }")
        entries.append("\n".join(e))
    if entries:
        lines.append(",\n".join(entries))
    lines.append("            ];")
    lines.append(f"{pad}const CURRENT_VERSION_CHANGES = VERSION_HISTORY[0].groups")
    lines.append(f"{pad}    ? Object.values(VERSION_HISTORY[0].groups).flat()")
    lines.append(f"{pad}    : (VERSION_HISTORY[0].changes || []);")
    lines.append(f"{pad}// VERSION:END")
    return "\n".join(lines)


def sync_version_files(vj):
    """Propaga a versao de version.json para index.html, server.py, csproj, .iss e README."""
    version = str(vj.get("version") or APP_VERSION)
    updated = []

    idx = os.path.join(APP_DIR, "index.html")
    if os.path.isfile(idx):
        html = _read_text(idx)
        begin, end = "// VERSION:BEGIN", "// VERSION:END"
        bi, ei = html.find(begin), html.find(end)
        if bi >= 0 and ei >= 0:
            html = html[:bi] + _version_block(vj) + html[ei + len(end):]
            pattern = r'(<span class="brand-version" id="app-version"[^>]*>)v[^<]*(</span>)'
            html = re.sub(pattern, lambda m: f"{m.group(1)}v{version}{m.group(2)}", html)
            _write_text(idx, html)
            updated.append("index.html")

    srv = os.path.join(APP_DIR, "server.py")
    if os.path.isfile(srv):
        text = _read_text(srv)
        new_text = re.sub(
            r'(?m)^APP_VERSION\s*=\s*"[^"]*".*$',
            f'APP_VERSION = "{version}"  # gerado por tools/sync_version.ps1',
            text,
        )
        if new_text != text:
            _write_text(srv, new_text)
            updated.append("server.py")

    csproj = os.path.join(APP_DIR, "MediaDeskLauncher.csproj")
    if os.path.isfile(csproj):
        text = _read_text(csproj)
        text = re.sub(r"<Version>[^<]*</Version>", f"<Version>{version}</Version>", text)
        text = re.sub(r"<FileVersion>[^<]*</FileVersion>", f"<FileVersion>{version}.0</FileVersion>", text)
        text = re.sub(
            r"<InformationalVersion>[^<]*</InformationalVersion>",
            f"<InformationalVersion>{version}</InformationalVersion>",
            text,
        )
        _write_text(csproj, text, bom=_has_bom(csproj))
        updated.append("MediaDeskLauncher.csproj")

    iss = os.path.join(APP_DIR, "installer", "mediadesk.iss")
    if os.path.isfile(iss):
        text = _read_text(iss)
        new_text = re.sub(
            r'(?m)^(#define AppVersion\s*)"[^"]*"', rf'\g<1>"{version}"', text
        )
        if new_text != text:
            _write_text(iss, new_text, bom=_has_bom(iss))
            updated.append("installer/mediadesk.iss")

    readme = os.path.join(APP_DIR, "README.md")
    if os.path.isfile(readme):
        text = _read_text(readme)
        new_text = re.sub(r"(?m)^(- \*\*Versão:\*\* ).*$", rf"\g<1>{version}", text)
        if new_text != text:
            _write_text(readme, new_text, bom=_has_bom(readme))
            updated.append("README.md")

    return updated


def _refresh_checksums():
    """Recalcula os hashes dos ficheiros de versao em checksums.json."""
    manifest = load_json(CHECKSUMS_FILE, {})
    if not isinstance(manifest, dict):
        manifest = {}
    files = manifest.get("ficheiros")
    if not isinstance(files, dict):
        files = {}
    for rel in VERSION_TRACKED + ("version.json",):
        full = os.path.join(APP_DIR, rel.replace("/", os.sep))
        if os.path.isfile(full):
            files[rel] = _sha256_file(full)
    manifest["ficheiros"] = files
    manifest["algoritmo"] = manifest.get("algoritmo") or "SHA-256"
    manifest["gerado"] = datetime.now().isoformat(timespec="seconds")
    save_json(CHECKSUMS_FILE, manifest)


def ensure_version_current():
    """Compara os ficheiros com checksums.json e aplica o nivel de atualizacao.

    O nivel e as notas vem do bloco "unreleased" de version.json, escrito
    quando existem alteracoes por publicar. Depois de aplicar, propaga a nova
    versao para todos os ficheiros e atualiza os hashes. Sem "unreleased" nao
    ha bump (evita versoes falsas quando so se corre o sincronizador).
    """
    global APP_VERSION
    with _version_lock:
        vj = load_json(VERSION_FILE, None)
        if not isinstance(vj, dict):
            return {"available": False, "changed": [], "bumped": False}
        manifest = load_json(CHECKSUMS_FILE, {})
        stored = (manifest.get("ficheiros") if isinstance(manifest, dict) else None) or {}
        changed = []
        for rel in VERSION_TRACKED:
            full = os.path.join(APP_DIR, rel.replace("/", os.sep))
            if not os.path.isfile(full):
                continue
            previous = str(stored.get(rel) or "").lower()
            if not previous or _sha256_file(full) != previous:
                changed.append(rel)
        pending = vj.get("unreleased")
        pending = pending if isinstance(pending, dict) else None
        result = {
            "available": True,
            "changed": changed,
            "bumped": False,
            "version": str(vj.get("version") or APP_VERSION),
            "date": vj.get("date"),
            "build": vj.get("build"),
            "level": str((pending or {}).get("level") or "none"),
        }
        if not pending or not changed:
            return result

        level = str(pending.get("level") or "patch").lower()
        if level not in ("major", "minor", "patch"):
            level = "patch"
        previous_version = str(vj.get("version") or APP_VERSION)
        new_version = _bump_semver(previous_version, level)
        today = datetime.now().strftime("%Y-%m-%d")
        groups = pending.get("groups")
        if not isinstance(groups, dict) or not groups:
            groups = {"Melhorado": [f"Atualização automática: {', '.join(changed)}"]}
        entry = {"version": new_version, "date": today, "groups": groups}
        history = [h for h in (vj.get("history") or []) if isinstance(h, dict)]
        vj["history"] = [entry] + [h for h in history if h.get("version") != new_version]
        vj["version"] = new_version
        vj["date"] = today
        vj["build"] = _next_build(today, vj.get("build"))
        vj.pop("unreleased", None)
        save_json(VERSION_FILE, vj)
        updated = sync_version_files(vj)
        _refresh_checksums()
        APP_VERSION = new_version
        result.update({
            "bumped": True,
            "previous": previous_version,
            "version": new_version,
            "date": today,
            "build": vj["build"],
            "level": level,
            "updated_files": updated,
        })
        try:
            broadcast_log(
                f"[OK] Versao atualizada para v{new_version} ({level}): "
                f"{len(changed)} ficheiro(s) comparado(s)."
            )
        except Exception:
            pass
        return result


# ========== VERIFICACAO ONLINE E HASHES DO HISTORICO ==========
def _local_ytdlp_version():
    exe = os.path.join(BIN_DIR, "yt-dlp.exe")
    if not os.path.isfile(exe):
        return None
    # Arrancar o yt-dlp custa ~1.3 s; repetir a cada verificacao atrasava o
    # splash e o painel de atualizacoes. A chave (tamanho + mtime) invalida o
    # cache quando o executavel e substituido.
    try:
        st = os.stat(exe)
        key = (st.st_size, st.st_mtime_ns)
    except Exception:
        key = None
    with _libraries_lock:
        if key is not None and _ytdlp_version_cache["key"] == key:
            return _ytdlp_version_cache["version"]
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        version = (proc.stdout or "").strip() or None
    except Exception:
        return None
    with _libraries_lock:
        _ytdlp_version_cache.update({"key": key, "version": version})
    return version


def _latest_ytdlp_version():
    req = Request(
        "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
        headers={
            "User-Agent": "YT-DLP-Media-Desk",
            "Accept": "application/vnd.github+json",
        },
    )
    with urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("tag_name") or "").lstrip("v") or None


def check_updates(force=False):
    """Le a versao local do yt-dlp e compara com a ultima release (com cache)."""
    now = time.time()
    if not force and _updates_cache["dados"] and now - _updates_cache["quando"] < 600:
        return _updates_cache["dados"]

    current = _local_ytdlp_version()
    latest = None
    error = None
    try:
        latest = _latest_ytdlp_version()
    except Exception as exc:
        error = str(exc)
    update_available = None
    if current and latest:
        update_available = current != latest
    result = {
        "app": {"current": APP_VERSION},
        "ytdlp": {
            "current": current,
            "latest": latest,
            "update_available": update_available,
        },
        "ffmpeg": {"present": os.path.isfile(os.path.join(BIN_DIR, "ffmpeg.exe"))},
        "python": {"version": platform.python_version()},
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "offline": bool(error),
        "error": error,
    }
    _updates_cache.update({"quando": now, "dados": result})
    return result


def _run_version_command(cmd, pattern, timeout=8):
    """Executa um comando de versao e extrai a versao com uma expressao regular."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        match = re.search(pattern, output, re.I)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return None


def _version_tuple(value):
    nums = re.findall(r"\d+", str(value or ""))
    return tuple(int(n) for n in nums[:4]) if nums else ()


def _is_newer(latest, installed):
    a, b = _version_tuple(latest), _version_tuple(installed)
    if not a or not b:
        return False
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)) > b + (0,) * (size - len(b))


def _github_latest_release(repo):
    req = Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={
            "User-Agent": "YT-DLP-Media-Desk",
            "Accept": "application/vnd.github+json",
        },
    )
    with urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("tag_name") or "").lstrip("v") or None


def _latest_cycle(product, cycle=None):
    """Ultima versao publicada no endoflife.date (Python, FFmpeg, .NET).

    Quando ``cycle`` e indicado (por exemplo ``8.0``), a comparacao fica
    limitada a essa linha de suporte. Isto evita anunciar .NET 10 como
    atualizacao de uma aplicacao publicada para .NET 8.
    """
    req = Request(
        f"https://endoflife.date/api/{product}.json",
        headers={"User-Agent": "YT-DLP-Media-Desk", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=6) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        candidates = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or not row.get("latest"):
                    continue
                if cycle and str(row.get("cycle")) != str(cycle):
                    continue
                candidates.append(str(row["latest"]))
        if candidates:
            return max(candidates, key=_version_tuple)
    except Exception:
        pass
    # Em algumas maquinas a cadeia de certificados do sistema esta
    # desatualizada. O GitHub usa a mesma CA do yt-dlp e serve de fallback.
    if product == "python":
        return _latest_github_tag("python/cpython", r"v?(3\.\d+\.\d+)")
    if product == "ffmpeg":
        return _latest_github_tag("FFmpeg/FFmpeg", r"n?(\d+\.\d+(?:\.\d+)?)")
    if product == "dotnet":
        pattern = rf"v?({re.escape(str(cycle))}\.\d+)" if cycle else r"v?(\d+\.\d+\.\d+)"
        return _latest_github_tag("dotnet/runtime", pattern)
    return None


def _latest_github_tag(repo, pattern):
    req = Request(
        f"https://api.github.com/repos/{repo}/tags?per_page=100",
        headers={
            "User-Agent": "YT-DLP-Media-Desk",
            "Accept": "application/vnd.github+json",
        },
    )
    with urlopen(req, timeout=6) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    versions = []
    for row in rows if isinstance(rows, list) else []:
        name = str((row or {}).get("name") or "")
        match = re.fullmatch(pattern, name)
        if match:
            versions.append(match.group(1))
    if not versions:
        return None
    versions.sort(key=_version_tuple)
    return versions[-1]


def _ffmpeg_local():
    candidates = []
    custom = str(config.get("custom_ffmpeg_path", "") or "").strip()
    if custom:
        candidates.append(custom)
    candidates.append(os.path.join(BIN_DIR, "ffmpeg.exe"))
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    for exe in candidates:
        if exe and os.path.isfile(exe):
            raw = _run_version_command(
                [exe, "-version"], r"ffmpeg version\s+(\S+)"
            )
            if raw:
                if raw.lower().startswith("n-"):
                    # Builds nightly do BtbN usam N-<build>-g<hash>-<AAAAMMDD>.
                    date = re.search(r"(\d{8})$", raw)
                    if date:
                        day = date.group(1)
                        return exe, f"nightly {day[:4]}-{day[4:6]}-{day[6:]}"
                return exe, raw.split("-")[0]
            return exe, None
    return None, None


def _deno_local():
    candidates = [os.path.join(BIN_DIR, "deno.exe")]
    found = shutil.which("deno")
    if found:
        candidates.append(found)
    for exe in candidates:
        if exe and os.path.isfile(exe):
            return exe, _run_version_command([exe, "--version"], r"deno\s+(\d+\.\d+\.\d+)")
    return None, None


def _webview2_local():
    try:
        import winreg
    except Exception:
        return None
    guid = WEBVIEW2_CLIENT_GUID
    paths = (
        ("SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + guid, winreg.HKEY_LOCAL_MACHINE),
        ("SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\" + guid, winreg.HKEY_LOCAL_MACHINE),
        ("SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + guid, winreg.HKEY_CURRENT_USER),
    )
    for path, root in paths:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
                if value:
                    return str(value)
        except Exception:
            continue
    return None


def _dotnet_target_cycle():
    """Linha de .NET alvo do launcher (net8.0-windows no projeto atual)."""
    csproj = os.path.join(APP_DIR, "MediaDeskLauncher.csproj")
    try:
        if os.path.isfile(csproj):
            with open(csproj, "r", encoding="utf-8-sig") as fh:
                match = re.search(r"<TargetFramework>net(\d+\.\d+)", fh.read())
                if match:
                    return match.group(1)
    except Exception:
        pass
    return "8.0"


def _dotnet_system_runtime(target=None):
    """Maior runtime .NET do sistema, opcionalmente limitado a uma linha."""
    try:
        proc = subprocess.run(
            ["dotnet", "--list-runtimes"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        versions = []
        for match in re.finditer(
            r"Microsoft\.(?:WindowsDesktop|NETCore)\.App\s+(\d+\.\d+\.\d+)",
            output,
        ):
            version = match.group(1)
            if target and not version.startswith(str(target) + "."):
                continue
            versions.append(version)
        return max(versions, key=_version_tuple) if versions else None
    except Exception:
        return None


def _dotnet_bundled_version():
    """Versao incluida no build auto-contido, quando o runtimeconfig existe."""
    candidates = (
        os.path.join(APP_DIR, "Media Desk.runtimeconfig.json"),
        os.path.join(APP_DIR, "build", "portable", "launcher", "Media Desk.runtimeconfig.json"),
        os.path.join(
            APP_DIR, "bin", "Release", "net8.0-windows", "win-x64",
            "Media Desk.runtimeconfig.json",
        ),
        # Nomes antigos (pacotes anteriores a renomeacao).
        os.path.join(APP_DIR, "YT-DLP-Media-Desk.runtimeconfig.json"),
        os.path.join(APP_DIR, "build", "portable", "launcher", "YT-DLP-Media-Desk.runtimeconfig.json"),
    )
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            frameworks = (data.get("runtimeOptions") or {}).get("includedFrameworks") or []
            for framework in frameworks:
                if not isinstance(framework, dict):
                    continue
                name = str(framework.get("name") or "")
                version = str(framework.get("version") or "")
                if name in ("Microsoft.WindowsDesktop.App", "Microsoft.NETCore.App") and version:
                    return version
        except Exception:
            continue
    return None


def _dotnet_local():
    """Devolve (versao, incluido, linha) para o runtime que o launcher executa."""
    bundled = _dotnet_bundled_version()
    if bundled:
        return bundled, True, ".".join(bundled.split(".")[:2])

    csproj = os.path.join(APP_DIR, "MediaDeskLauncher.csproj")
    target = None
    self_contained = False
    try:
        if os.path.isfile(csproj):
            with open(csproj, "r", encoding="utf-8-sig") as fh:
                text = fh.read()
            match = re.search(r"<TargetFramework>net(\d+\.\d+)", text)
            if match:
                target = match.group(1)
            self_contained = bool(re.search(
                r"<SelfContained>\s*true\s*</SelfContained>", text, re.I
            ))
    except Exception:
        pass

    if target and self_contained:
        # O launcher viaja com o runtime incluido; a versao exata do patch
        # nao fica exposta no pacote portatil, por isso nao inventamos uma.
        return target + " (incluído)", True, target
    if target:
        version = _dotnet_system_runtime(target)
        if version:
            return version, False, target
        return target + " (incluído)", True, target

    version = _dotnet_system_runtime()
    if version:
        return version, False, ".".join(version.split(".")[:2])
    exe = os.path.join(APP_DIR, "Media Desk.exe")
    if os.path.isfile(exe):
        return "8.0 (incluído)", True, "8.0"
    return None, False, None


def _library_entry(lib_id, name, installed, latest, present, url,
                   auto=False, status_override=None):
    if status_override:
        status = status_override
    elif auto:
        status = "auto"
    elif not present or not installed:
        status = "missing"
    elif latest and _is_newer(latest, installed):
        status = "update"
    elif latest:
        status = "ok"
    else:
        status = "unknown"
    action = ""
    if status in ("update", "missing"):
        if lib_id == "ytdlp":
            action = "update_ytdlp"
        elif lib_id == "ffmpeg":
            action = "update_ffmpeg"
        else:
            action = "open"
    elif url and status == "unknown":
        action = "open"
    return {
        "id": lib_id,
        "name": name,
        "installed": installed,
        "latest": latest,
        "present": bool(present),
        "status": status,
        "action": action,
        "url": url,
    }


def _compute_libraries():
    """Verificacao completa (locais + rede). Pode demorar varios segundos."""
    now = time.time()

    def safe(fn, *args):
        try:
            return fn(*args)
        except Exception:
            return None

    dotnet_cycle = _dotnet_target_cycle()
    # As deteções locais e as consultas online correm em paralelo. Assim o
    # splash nao espera primeiro pela rede e depois por cada executavel.
    with ThreadPoolExecutor(max_workers=10) as pool:
        latest_futures = {
            "ytdlp": pool.submit(safe, _github_latest_release, "yt-dlp/yt-dlp"),
            "deno": pool.submit(safe, _github_latest_release, "denoland/deno"),
            "python": pool.submit(safe, _latest_cycle, "python"),
            "ffmpeg": pool.submit(safe, _latest_cycle, "ffmpeg"),
            "dotnet": pool.submit(safe, _latest_cycle, "dotnet", dotnet_cycle),
        }
        local_futures = {
            "ytdlp": pool.submit(safe, _local_ytdlp_version),
            "ffmpeg": pool.submit(safe, _ffmpeg_local),
            "deno": pool.submit(safe, _deno_local),
            "webview2": pool.submit(safe, _webview2_local),
            "dotnet": pool.submit(safe, _dotnet_local),
        }
        latest = {name: future.result() for name, future in latest_futures.items()}
        ytdlp_current = local_futures["ytdlp"].result()
        ffmpeg_exe, ffmpeg_current = local_futures["ffmpeg"].result() or (None, None)
        deno_exe, deno_current = local_futures["deno"].result() or (None, None)
        webview2_current = local_futures["webview2"].result()
        dotnet_current, dotnet_bundled, _dotnet_cycle = (
            local_futures["dotnet"].result() or (None, False, None)
        )

    ffmpeg_nightly = str(ffmpeg_current or "").startswith("nightly")
    libraries = [
        _library_entry(
            "ytdlp", "yt-dlp", ytdlp_current, latest["ytdlp"],
            bool(ytdlp_current), "https://github.com/yt-dlp/yt-dlp/releases/latest",
        ),
        _library_entry(
            "ffmpeg", "FFmpeg", ffmpeg_current, latest["ffmpeg"],
            bool(ffmpeg_exe), "https://github.com/BtbN/FFmpeg-Builds/releases/latest",
            status_override="nightly" if ffmpeg_nightly else None,
        ),
        _library_entry(
            "python", "Python", platform.python_version(), latest["python"],
            True, "https://www.python.org/downloads/",
        ),
        _library_entry(
            "deno", "Deno", deno_current, latest["deno"],
            bool(deno_exe), "https://github.com/denoland/deno/releases/latest",
        ),
        _library_entry(
            "webview2", "Microsoft Edge WebView2", webview2_current, None,
            bool(webview2_current), "https://developer.microsoft.com/microsoft-edge/webview2/",
            auto=True,
        ),
        _library_entry(
            "dotnet", ".NET", dotnet_current, latest["dotnet"],
            bool(dotnet_current), "https://dotnet.microsoft.com/download",
            status_override="bundled" if (dotnet_bundled and dotnet_current) else None,
        ),
    ]
    offline = not any((latest["ytdlp"], latest["python"], latest["ffmpeg"], latest["dotnet"], latest["deno"]))
    result = {
        "libraries": libraries,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "offline": bool(offline),
        "updates_available": sum(1 for lib in libraries if lib["status"] in ("update", "missing")),
    }
    _libraries_cache.update({"quando": now, "dados": result})
    return result


def _libraries_placeholder():
    """Resposta minima e instantanea enquanto a verificacao corre em segundo plano."""
    return {
        "libraries": [],
        "checked_at": None,
        "offline": False,
        "updates_available": 0,
        "pending": True,
    }


def _libraries_disk_cache():
    """Carrega (uma vez) o ultimo resultado guardado em data/libraries_cache.json."""
    with _libraries_lock:
        if _libraries_cache["loaded"]:
            return
        _libraries_cache["loaded"] = True
    data = load_json(LIBRARIES_CACHE_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("libraries"), list):
        return
    try:
        when = float(data.get("_cached_at") or 0)
    except Exception:
        when = 0.0
    data = {key: value for key, value in data.items() if key != "_cached_at"}
    with _libraries_lock:
        if not _libraries_cache["dados"]:
            _libraries_cache["quando"] = when
            _libraries_cache["dados"] = data


def _libraries_refresh_async():
    """Arranca (se ainda nao correr) uma verificacao completa em segundo plano."""
    with _libraries_lock:
        if _libraries_cache["running"]:
            return False
        _libraries_cache["running"] = True
        _libraries_cache["done"].clear()

    def worker():
        try:
            result = _compute_libraries()
            with _libraries_lock:
                _libraries_cache["dados"] = result
                _libraries_cache["quando"] = time.time()
            try:
                os.makedirs(os.path.dirname(LIBRARIES_CACHE_FILE), exist_ok=True)
                save_json(LIBRARIES_CACHE_FILE, dict(result, _cached_at=time.time()))
            except Exception:
                pass
        except Exception as exc:
            try:
                print(f"[AVISO] Verificacao de bibliotecas falhou: {exc}")
            except Exception:
                pass
        finally:
            with _libraries_lock:
                _libraries_cache["running"] = False
            _libraries_cache["done"].set()

    thread = threading.Thread(target=worker, daemon=True, name="libraries-refresh")
    _libraries_cache["thread"] = thread
    thread.start()
    return True


def check_libraries(force=False, background=False):
    """Verifica as bibliotecas instaladas e compara-as com as versoes mais recentes.

    background=True devolve imediatamente o ultimo resultado conhecido (mesmo
    que antigo) e atualiza-o em segundo plano. E o modo usado pelo splash: o
    arranque nunca fica preso a rede, ao GitHub ou ao `yt-dlp --version`.
    """
    _libraries_disk_cache()
    now = time.time()
    with _libraries_lock:
        dados = _libraries_cache["dados"]
        quando = _libraries_cache["quando"] or 0.0
        running = _libraries_cache["running"]
        done = _libraries_cache["done"]
    age = (now - quando) if quando else None

    if background:
        if dados is None or age is None or age > LIBRARIES_SPLASH_TTL:
            _libraries_refresh_async()
        return dados or _libraries_placeholder()

    if not force and dados is not None and age is not None and age < LIBRARIES_TTL:
        return dados

    # Pedido explicito de dados atuais: espera pela verificacao em curso (se
    # existir) em vez de lancar outra em paralelo.
    if running:
        done.wait(timeout=60)
        with _libraries_lock:
            if _libraries_cache["dados"] is not None:
                return _libraries_cache["dados"]

    _libraries_refresh_async()
    done.wait(timeout=60)
    with _libraries_lock:
        if _libraries_cache["dados"] is not None:
            return _libraries_cache["dados"]
    return dados or _libraries_placeholder()


def _quick_hash(path, chunk=256 * 1024):
    """Hash rapido (tamanho + inicio + fim) para verificar media sem ler GB."""
    size = os.path.getsize(path)
    h = hashlib.sha256()
    h.update(str(size).encode("ascii"))
    with open(path, "rb") as fh:
        h.update(fh.read(chunk))
        if size > chunk * 2:
            fh.seek(-chunk, os.SEEK_END)
            h.update(fh.read(chunk))
    return h.hexdigest()


def verify_media_history():
    """Verifica os media com os hashes guardados nas definicoes cifradas."""
    stored = config.get("media_hashes")
    if not isinstance(stored, dict):
        stored = {}
    library = scan_downloads()
    seen = set()
    verified = new = 0
    changed = []
    for kind in ("video", "audio"):
        for item in library.get(kind, []):
            url_path = item.get("path") or ""
            rel = url_path[len("/downloads/"):] if url_path.startswith("/downloads/") else url_path
            full = os.path.join(get_downloads_dir(), rel.replace("/", os.sep))
            if not os.path.isfile(full):
                continue
            seen.add(url_path)
            try:
                digest = _quick_hash(full)
            except Exception:
                continue
            previous = stored.get(url_path)
            if not previous:
                new += 1
            elif previous != digest:
                changed.append(rel)
            else:
                verified += 1
            stored[url_path] = digest
    missing = [key for key in list(stored) if key not in seen]
    for key in missing:
        stored.pop(key, None)

    history = load_json(HISTORY_FILE, [])
    history_missing = 0
    if isinstance(history, list):
        for entry in history:
            fp = str((entry or {}).get("file_path") or "")
            if not fp:
                continue
            if fp.startswith("/downloads/"):
                rel = fp[len("/downloads/"):]
                full = os.path.join(get_downloads_dir(), rel.replace("/", os.sep))
            else:
                full = fp
            if not os.path.isfile(full):
                history_missing += 1

    if config.get("media_hashes") != stored:
        config["media_hashes"] = stored
        try:
            save_config(config)
        except Exception:
            pass
    return {
        "total": len(seen),
        "ok": verified,
        "new": new,
        "changed": changed,
        "missing": missing,
        "history_missing": history_missing,
        "version": APP_VERSION,
    }


# Posicoes validas da pre-visualizacao (grelha 3x3 das definicoes).
PREVIEW_POSITIONS = (
    "top-left", "top-center", "top-right",
    "middle-left", "center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
)


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
    "embed_metadata": False,
    "embed_thumbnail": False,
    "embed_chapters": False,
    "write_info_json": False,
    "download_delay": 8,
    "download_retries": 2,
    "auto_quality_recommendation": True,
    "sub_mode": "none",
    "sub_langs": "pt,en",
    "sub_auto": True,
    "library_filter": "all",
    "categories_per_row": 3,
    "preview_position": "bottom-center",
    "categories": [],
    "tooltip_copy_enabled": True,
    "settings_autosave_enabled": True,
    "settings_autosave_interval": 30,
    "online_checks_enabled": True,
    "automation_enabled": False,
    "automation_mode": "manual",
    "automation_interval": 30,
    "automation_autostart": False,
    "automation_platforms": [],
    "clipboard_monitor_enabled": False,
    "automation_max_age_days": 30,
    "rss_proposals_max": 12,
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
config = dict(default_config)
config.update(load_config())
if not os.path.exists(CONFIG_FILE):
    save_config(config)
APP_RELEASE_REPO = config.get("app_release_repo", "")
APP_UPDATE_URL = config.get("app_update_url", "")
if not isinstance(config.get("categories"), list):
    config["categories"] = []
for _new_key in (
    "tooltip_copy_enabled",
    "settings_autosave_enabled",
    "settings_autosave_interval",
    "online_checks_enabled",
    "automation_enabled",
    "automation_mode",
    "automation_interval",
    "automation_autostart",
    "automation_platforms",
    "automation_max_age_days",
    "rss_proposals_max",
    "embed_metadata",
    "embed_thumbnail",
    "embed_chapters",
    "write_info_json",
):
    config.setdefault(_new_key, default_config[_new_key])


# Chaves que a interface pode escrever nas definicoes. Tudo o resto e
# rejeitado: /save_config e alcancavel pelo browser e nao pode servir para
# injetar chaves internas (versao, changelog, hashes, etc.).
CONFIG_WRITABLE_KEYS = frozenset({
    "auto_quality_recommendation",
    "automation_autostart",
    "automation_enabled",
    "automation_interval",
    "automation_max_age_days",
    "automation_mode",
    "automation_platforms",
    "app_release_repo",
    "categories",
    "categories_per_row",
    "clipboard_monitor_enabled",
    "cookies_browser",
    "cookies_method",
    "custom_ffmpeg_path",
    "download_delay",
    "download_retries",
    "downloads_custom_dir",
    "downloads_mode",
    "embed_chapters",
    "embed_metadata",
    "embed_thumbnail",
    "group_by_uploader",
    "language",
    "library_filter",
    "online_checks_enabled",
    "po_token",
    "preview_position",
    "rss_proposals_max",
    "server_port",
    "settings_autosave_enabled",
    "settings_autosave_interval",
    "sub_auto",
    "sub_langs",
    "sub_mode",
    "theme",
    "theme_palette",
    "tooltip_copy_enabled",
    "use_cookies",
    "use_po_token",
    "visitor_data",
    "write_info_json",
})


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

def save_history_entry(url, download_type, status="success", file_path=None, title=None, platform=None, media_type=None, metadata=None):
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
    if status == "success":
        # Efeito secundario: alimenta o ficheiro cifrado de atividade. Falhas
        # aqui nunca podem marcar o download como falhado.
        try:
            record_activity_entry(
                _activity_entry(
                    url,
                    file_path,
                    media_type=media_type,
                    title=title,
                    platform=entry["platform"],
                    meta=metadata,
                )
            )
        except Exception as exc:
            print(f"[AVISO] Atividade nao registada: {exc}")


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

    thumb_exts = (".jpg", ".jpeg", ".png", ".webp")
    for root, _, files in os.walk(ddir):
        # Capas guardadas ao lado do media (sidecar) para usar como miniatura
        # na mediateca e na Atividade.
        thumbnails = {}
        for name in files:
            stem, sext = os.path.splitext(name)
            if sext.lower() in thumb_exts:
                thumbnails.setdefault(stem.lower(), name)
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in video_exts and ext not in audio_exts:
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, ddir).replace("\\", "/")
            url_path = f"/downloads/{rel}"
            thumb_name = thumbnails.get(os.path.splitext(f)[0].lower())
            thumb_url = None
            if thumb_name:
                thumb_rel = os.path.relpath(os.path.join(root, thumb_name), ddir).replace("\\", "/")
                thumb_url = f"/downloads/{thumb_rel}"
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
                "thumbnail": thumb_url,
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
    save_config(config)
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


def _start_dependency_check():
    _dependencies_ready.clear()

    def worker():
        try:
            check_dependencies()
        except Exception as exc:
            message = f"[ERRO] Verificação de dependências: {exc}"
            print(message)
            broadcast_log(message)
        finally:
            _dependencies_ready.set()

    try:
        threading.Thread(target=worker, daemon=True, name="dependency-check").start()
    except Exception as exc:
        _dependencies_ready.set()
        message = f"[ERRO] Não foi possível iniciar a verificação de dependências: {exc}"
        print(message)
        broadcast_log(message)


def update_ffmpeg_worker():
    """Descarrega a build mais recente do FFmpeg e substitui o executavel."""
    custom = str(config.get("custom_ffmpeg_path", "") or "").strip()
    target = custom if custom and os.path.isabs(custom) and os.path.isfile(custom) else os.path.join(BIN_DIR, "ffmpeg.exe")
    os.makedirs(os.path.dirname(target) or BIN_DIR, exist_ok=True)
    temp_zip = os.path.join(BIN_DIR, "ffmpeg-update.zip")
    temp_exe = target + ".new"
    broadcast_log("[UPDATE] A descarregar a versao mais recente do FFmpeg...")
    try:
        if not download_file(FFMPEG_URL, temp_zip):
            broadcast_log("[ERRO] Nao foi possivel descarregar o FFmpeg.")
            return
        with zipfile.ZipFile(temp_zip, "r") as archive:
            member = next((n for n in archive.namelist() if n.lower().endswith("ffmpeg.exe")), None)
            if not member:
                broadcast_log("[ERRO] O pacote do FFmpeg nao contem ffmpeg.exe.")
                return
            with archive.open(member) as src, open(temp_exe, "wb") as dst:
                shutil.copyfileobj(src, dst)
        os.replace(temp_exe, target)
        broadcast_log(f"[OK] FFmpeg atualizado em {target}.")
        _libraries_cache.update({"quando": 0.0, "dados": None})
    except Exception as exc:
        broadcast_log(f"[ERRO] FFmpeg: {exc}")
        try:
            if os.path.isfile(temp_exe):
                os.remove(temp_exe)
        except Exception:
            pass
    finally:
        try:
            if os.path.isfile(temp_zip):
                os.remove(temp_zip)
        except Exception:
            pass


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


def _aggregate_transfer_progress(
    percent, format_index=1, format_count=1, playlist_index=1, playlist_count=1
):
    """Agrega el progresso real das transferências de formatos e itens."""
    local = max(0.0, min(100.0, float(percent)))
    format_count = max(1, int(format_count))
    format_index = min(max(1, int(format_index)), format_count)
    if format_count > 1:
        local = ((format_index - 1) + local / 100.0) / format_count * 100.0
    playlist_count = max(1, int(playlist_count))
    playlist_index = min(max(1, int(playlist_index)), playlist_count)
    if playlist_count > 1:
        local = ((playlist_index - 1) + local / 100.0) / playlist_count * 100.0
    return max(0.0, min(100.0, local))


def execute_cmd_and_check(cmd, progress_context=None):
    global current_process, download_paused
    progress_base, progress_span = progress_context or (0.0, 1.0)
    progress_base = max(0.0, min(1.0, float(progress_base)))
    progress_span = max(0.0, min(1.0 - progress_base, float(progress_span)))
    broadcast("STATUS: A processar...")
    broadcast("LOG_CLEAR: true")
    # Cada tentativa/estratégia recomeça no início do seu segmento (que pode
    # ser posterior a zero num trabalho com vários URLs). Não repor no finally
    # evita apagar o progresso logo após cada transferência.
    broadcast(f"PROGRESS: {progress_base * 100:.1f}")
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
        regex_playlist_item = re.compile(
            r"Downloading item\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE
        )
        # O yt-dlp junta video e audio na mesma linha de formatos ("...: 137+140").
        # Dividimos a barra pelo numero de transferencias para nao a encher logo
        # na primeira (video) e recomecar na segunda (audio).
        regex_formats = re.compile(r"Downloading \d+ format\(s\): (.+)")
        n_formats = 1
        format_index = 0
        playlist_index = 1
        playlist_total = 1
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

            item_match = regex_playlist_item.search(line)
            if item_match:
                playlist_index = max(1, int(item_match.group(1)))
                playlist_total = max(1, int(item_match.group(2)))
                progress_floor = (
                    (min(playlist_index, playlist_total) - 1) / playlist_total
                ) * 100
                broadcast(
                    f"PROGRESS: {progress_base * 100 + progress_span * progress_floor:.1f}"
                )

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
                value = _aggregate_transfer_progress(
                    float(p.group(1)),
                    format_index,
                    n_formats,
                    playlist_index,
                    playlist_total,
                )
                progress_floor = max(progress_floor, value)
                broadcast(
                    f"PROGRESS: "
                    f"{min(99.5, progress_base * 100 + progress_span * min(progress_floor, 95)):.1f}"
                )
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
        # Ficheiros já existentes e conversões podem não emitir progresso; o
        # segmento chega perto do fim, mas só a fila confirma 100% após registar
        # o histórico e concluir o trabalho inteiro.
        broadcast(f"PROGRESS: {min(99.5, (progress_base + progress_span) * 100):.1f}")
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


def _read_meta_file(meta_file, file_path=None):
    """Le a ultima linha JSON valida escrita por --print-to-file."""
    if not meta_file or not os.path.exists(meta_file):
        return {}
    try:
        with open(meta_file, "r", encoding="utf-8-sig") as fh:
            lines = [line.strip() for line in fh if line.strip()]
    except Exception:
        return {}
    entries = []
    for line in lines:
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            entries.append(data)
    if not entries:
        return {}
    if file_path:
        wanted = os.path.basename(_resolve_download_path(file_path) or file_path)
        for entry in reversed(entries):
            if os.path.basename(str(entry.get("filepath") or "")) == wanted:
                return entry
    return entries[-1]


def _discard_meta_file(meta_file):
    if not meta_file:
        return
    try:
        os.remove(meta_file)
    except Exception:
        pass


def _cleanup_activity_temp(max_age=24 * 3600):
    """Remove ficheiros .meta_* de execucoes interrompidas."""
    directory = os.path.join(APP_DIR, "data")
    try:
        now = time.time()
        for name in os.listdir(directory):
            if not name.endswith(".jsonl") or not name.startswith(".meta_"):
                continue
            path = os.path.join(directory, name)
            if now - os.path.getmtime(path) > max_age:
                os.remove(path)
    except Exception:
        pass


def run_download_with_fallback(
    url, mode, quality, vformat, subtitles, sub_mode, sub_langs, sub_auto,
    options=None, progress_context=None
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
        # Guarda tambem a capa ao lado do ficheiro (sidecar). E esta imagem que
        # a mediateca e a Atividade usam como miniatura do item.
        base_cmd.append("--write-thumbnail")
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

    # Metadados estruturados de cada item (uma linha JSON por video). E escrito
    # num ficheiro temporario e lido no fim; nao depende de o utilizador ter
    # ativado --write-info-json nem de o yt-dlp ter mudado o formato de saida.
    meta_file = None
    try:
        meta_dir = os.path.join(APP_DIR, "data")
        os.makedirs(meta_dir, exist_ok=True)
        meta_file = os.path.join(meta_dir, f".meta_{uuid.uuid4().hex}.jsonl")
        base_cmd.extend(
            [
                "--print-to-file",
                "after_move:%(.{id,title,channel,channel_id,channel_url,uploader,uploader_id,"
                "uploader_url,creator,artist,webpage_url,original_url,duration,view_count,"
                "upload_date,release_date,extractor,extractor_key,filepath,ext,description,"
                "tags,thumbnail,width,height})j",
                meta_file,
            ]
        )
    except Exception as exc:
        broadcast_log(f"[AVISO] Metadados indisponiveis: {exc}")
        meta_file = None

    strategies = build_command_with_fallback(
        url, base_cmd, mode, quality, vformat, subtitles, sub_mode, sub_langs, sub_auto
    )
    
    for name, cmd in strategies:
        if download_cancel_requested:
            _discard_meta_file(meta_file)
            return False, None, {}
        broadcast_log(f"[INFO] A tentar: {name}")
        if progress_context is None:
            success, file_path = execute_cmd_and_check(cmd)
        else:
            success, file_path = execute_cmd_and_check(cmd, progress_context)
        if success:
            broadcast_log(f"[OK] Sucesso com {name}")
            meta = _read_meta_file(meta_file, file_path)
            _discard_meta_file(meta_file)
            return True, file_path, meta
        else:
            broadcast_log(f"[ERRO] Falha na estratégia: {name}")

    _discard_meta_file(meta_file)
    broadcast_log("[ERRO] Todas as estratégias falharam.")
    return False, None, {}


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
                success, file_path, file_meta = run_download_with_fallback(
                    url,
                    job.get("mode", "video"),
                    job.get("quality", "best"),
                    job.get("vformat", "mp4"),
                    job.get("subtitles", False),
                    job.get("sub_mode", "none"),
                    job.get("sub_langs", "all"),
                    job.get("sub_auto", True),
                    item_options,
                    (
                        (index / max(1, len(urls)))
                        + item_index / (max(1, len(urls)) * max(1, len(items))),
                        1 / (max(1, len(urls)) * max(1, len(items))),
                    ),
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
                metadata=file_meta if success else None,
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
    _dependencies_ready.wait()
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
        with _queue_lock:
            if status == "completed":
                try:
                    if job in _queue_jobs:
                        _queue_jobs.remove(job)
                    _persist_queue_locked()
                except ValueError:
                    pass
                _active_download_id = None
                download_cancel_requested = False
                for control_file in (PAUSE_FILE, CANCEL_FILE):
                    try:
                        os.remove(control_file)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        broadcast_log(f"[AVISO] Não foi possível limpar o controlo {os.path.basename(control_file)}: {e}")
                broadcast("STATUS: Download concluído")
                broadcast("PROGRESS: 100")
                broadcast(
                    "DOWNLOAD_FINISHED: "
                    + json.dumps(
                        {
                            "id": job["id"],
                            "status": status,
                            "origin": job.get("source", "input"),
                            "urls": job.get("urls", []) if job.get("source", "input") == "input" else [],
                        },
                        ensure_ascii=False,
                    )
                )
                broadcast("QUEUE_UPDATED: true")
                _queue_wakeup.set()
                continue
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
        broadcast("STATUS: " + ("Cancelado" if status == "cancelled" else "Download falhou"))
        broadcast(
            "DOWNLOAD_FINISHED: "
            + json.dumps(
                {
                    "id": job["id"],
                    "status": status,
                    "origin": job.get("source", "input"),
                    "urls": job.get("urls", []) if job.get("source", "input") == "input" else [],
                },
                ensure_ascii=False,
            )
        )
        broadcast("QUEUE_UPDATED: true")
        _queue_wakeup.set()


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
            "source": req.get("source") if req.get("source") == "rss" else "input",
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

    def _origin_allowed(self):
        """Bloqueia pedidos de escrita vindos de paginas externas.

        O servidor so deve responder a interface local. Sem esta verificacao,
        qualquer site aberto no browser podia enviar POSTs para
        http://127.0.0.1:<porta> (CSRF) e alterar definicoes ou apagar ficheiros.
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin.lower() == "null":
            return False
        try:
            host = (urlparse(origin).hostname or "").lower()
        except Exception:
            return False
        return host in ("127.0.0.1", "localhost", "::1")

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
            # resolve_download_file valida o caminho e garante que o ficheiro
            # fica dentro da pasta de downloads (um caminho absoluto como
            # /downloads/C:/Windows/... nao pode escapar).
            fp = resolve_download_file(path)
            if fp and os.path.isfile(fp):
                self.send_response(200)
                mime, _ = mimetypes.guess_type(fp)
                if not mime:
                    mime = "application/octet-stream"
                self.send_header("Content-type", mime)
                self.send_header("Content-Length", str(os.path.getsize(fp)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with open(fp, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, 1024 * 1024)
                return
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
            cfg.setdefault("preview_position", "bottom-center")
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

        if path == "/automation/status":
            payload = _automation_status()
            payload["suggested"] = suggest_rss_from_history()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/rss/channels":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "channels": load_rss_channels(),
                        "status": _automation_status(),
                        "suggested": suggest_rss_from_history(),
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return

        if path == "/rss/proposals":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"proposals": load_rss_proposals(), "status": _automation_status()},
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return

        if path == "/rss/suggest":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"suggested": suggest_rss_from_history(), "focus": analyze_user_focus()},
                    ensure_ascii=False,
                ).encode("utf-8")
            )
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

        if path == "/check_updates":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            force = "force=1" in (urlparse(self.path).query or "")
            try:
                payload = check_updates(force=force)
            except Exception as exc:
                payload = {"offline": True, "error": str(exc), "app": {"current": APP_VERSION}}
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        if path == "/check_libraries":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            force = "force=1" in (urlparse(self.path).query or "")
            background = "background=1" in (urlparse(self.path).query or "")
            try:
                payload = check_libraries(force=force, background=background)
            except Exception as exc:
                payload = {"libraries": [], "offline": True, "error": str(exc)}
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        if path == "/update_ffmpeg":
            threading.Thread(target=update_ffmpeg_worker, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"started": True}).encode("utf-8"))
            return

        if path == "/splash_verify":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                media = verify_media_history()
            except Exception as exc:
                media = {"error": str(exc)}
            payload = {
                "version": {
                    "current": APP_VERSION,
                    "date": load_json(VERSION_FILE, {}).get("date"),
                    "build": load_json(VERSION_FILE, {}).get("build"),
                },
                "media": media,
                "integrity": get_integrity_status(),
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        if path == "/version_status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            engine = load_json(VERSION_FILE, {}) or {}
            payload = {
                "current": APP_VERSION,
                "date": engine.get("date"),
                "build": engine.get("build"),
                "pending": isinstance(engine.get("unreleased"), dict),
                "integrity": get_integrity_status(),
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global download_cancel_requested
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8") if length else "{}"
        path = unquote(urlparse(self.path).path)
        if not self._origin_allowed():
            self.send_error(403, "Origem não autorizada")
            return

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
                save_config(config)
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

        if path == "/rss/channels":
            try:
                req = json.loads(data or "{}")
                if not isinstance(req, dict):
                    raise ValueError("Dados inválidos.")
                action = str(req.get("action") or "add").lower()
                channels = load_rss_channels()
                if action in ("add", "upsert"):
                    norm = _normalize_channel(req)
                    if len(channels) >= 100:
                        raise ValueError("Limite de 100 canais atingido.")
                    wanted = norm["url"].lower()
                    if wanted and any(
                        str(c.get("url") or "").strip().lower() == wanted for c in channels
                    ):
                        raise ValueError("Este canal já está na lista.")
                    channel = {
                        "id": str(uuid.uuid4()),
                        **norm,
                        "added_at": int(time.time()),
                        "last_checked": None,
                        "last_error": None,
                    }
                    channels.append(channel)
                elif action in ("remove", "delete"):
                    cid = str(req.get("id") or "").strip()
                    if not cid:
                        raise ValueError("Canal não indicado.")
                    channels = [c for c in channels if c.get("id") != cid]
                elif action in ("toggle", "enable", "disable"):
                    cid = str(req.get("id") or "").strip()
                    if not cid:
                        raise ValueError("Canal não indicado.")
                    enabled = bool(req.get("enabled", action != "disable"))
                    target = next((c for c in channels if c.get("id") == cid), None)
                    if target is None:
                        raise ValueError("Canal não encontrado.")
                    target["enabled"] = enabled
                else:
                    raise ValueError("Ação inválida.")
                if not save_rss_channels(channels):
                    raise ValueError("Não foi possível guardar a lista de canais.")
                svc = activity_module()
                if svc and config.get("automation_enabled"):
                    try:
                        svc.request_check(APP_DIR)
                    except Exception:
                        pass
                _json_reply(
                    self,
                    200,
                    {"ok": True, "channels": channels, "status": _automation_status()},
                )
            except ValueError as exc:
                _json_reply(self, 400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                _json_reply(self, 500, {"ok": False, "error": str(exc)})
            return

        if path == "/check_app_update":
            try:
                threading.Thread(target=_check_app_update, daemon=True).start()
                _json_reply(self, 200, {"ok": True})
            except Exception as exc:
                _json_reply(self, 500, {"ok": False, "error": str(exc)})
            return

        if path == "/rss/check":
            try:
                req = json.loads(data or "{}")
            except Exception:
                req = {}
            wait = bool(isinstance(req, dict) and req.get("wait"))
            svc = activity_module()
            started = False
            via_service = bool(
                svc and config.get("automation_enabled") and svc.is_running(APP_DIR)
            )
            try:
                if via_service:
                    started = bool(svc.request_check(APP_DIR))
                elif wait and svc:
                    svc.check_feeds(APP_DIR, force=True)
                    started = True
                elif svc:
                    _rss_check_background()
                    started = True
                _json_reply(
                    self,
                    200,
                    {
                        "ok": started,
                        "started": started,
                        "service": via_service,
                        "status": _automation_status(),
                        "proposals": load_rss_proposals(),
                    },
                )
            except Exception as exc:
                _json_reply(self, 500, {"ok": False, "error": str(exc)})
            return

        if path == "/rss/suggest":
            _json_reply(
                self,
                200,
                {
                    "suggested": suggest_rss_from_history(),
                    "channels": _activity_suggestions(),
                    "focus": analyze_user_focus(),
                },
            )
            return

        if path == "/rss/proposals":
            try:
                req = json.loads(data or "{}")
                if not isinstance(req, dict):
                    raise ValueError("Dados inválidos.")
                action = str(req.get("action") or "").lower()
                pid = str(req.get("id") or "")
                proposals = load_rss_proposals()
                proposed = proposals.get("proposed") or []
                seen = proposals.get("seen") or []
                target = next((p for p in proposed if p.get("id") == pid), None)
                queued = False
                if action in ("accept", "approve", "download"):
                    if target is None:
                        raise ValueError("Proposta não encontrada.")
                    url = str(target.get("url") or "").strip()
                    if not url:
                        raise ValueError("Esta proposta não tem um URL de download.")
                    if action == "approve" and config.get("automation_mode", "manual") != "auto":
                        # Em modo manual, aprovar apenas retira da lista; quem
                        # descarrega é a ação explícita "accept".
                        status = "approved"
                    else:
                        _enqueue_download({
                            "urls": [url],
                            "mode": "video",
                            "quality": "best",
                            "vformat": "mp4",
                            "source": "rss",
                        })
                        status = "accepted"
                        queued = True
                    seen.insert(0, {**target, "status": status, "acted_at": int(time.time())})
                    proposals["proposed"] = [p for p in proposed if p.get("id") != pid]
                    svc = activity_module()
                    if svc:
                        try:
                            svc.record_action(target, status, APP_DIR)
                        except Exception:
                            pass
                elif action == "reject":
                    if target is None:
                        raise ValueError("Proposta não encontrada.")
                    seen.insert(0, {**target, "status": "rejected", "acted_at": int(time.time())})
                    proposals["proposed"] = [p for p in proposed if p.get("id") != pid]
                    svc = activity_module()
                    if svc:
                        try:
                            svc.record_action(target, "rejected", APP_DIR)
                        except Exception:
                            pass
                elif action in ("clear_done", "clear_seen"):
                    proposals["seen"] = []
                elif action in ("clear", "clear_all"):
                    proposals["proposed"] = []
                else:
                    raise ValueError("Ação inválida.")
                proposals["seen"] = (proposals.get("seen") or seen)[:500]
                save_rss_proposals(proposals)
                _json_reply(
                    self,
                    200,
                    {"ok": True, "queued": queued, "proposals": proposals, "status": _automation_status()},
                )
            except ValueError as exc:
                _json_reply(self, 400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                _json_reply(self, 500, {"ok": False, "error": str(exc)})
            return

        if path == "/automation/config":
            try:
                req = json.loads(data or "{}")
                if not isinstance(req, dict):
                    raise ValueError("Dados inválidos.")
                updates = {}
                if "enabled" in req:
                    updates["automation_enabled"] = bool(req["enabled"])
                if "mode" in req:
                    mode = str(req["mode"]).lower()
                    if mode not in ("manual", "auto"):
                        raise ValueError("Modo inválido.")
                    updates["automation_mode"] = mode
                if "interval" in req:
                    interval = int(req["interval"])
                    if interval < 5 or interval > 1440:
                        raise ValueError("O intervalo tem de estar entre 5 e 1440 minutos.")
                    updates["automation_interval"] = interval
                if "autostart" in req:
                    updates["automation_autostart"] = bool(req["autostart"])
                if "platforms" in req:
                    platforms = req["platforms"]
                    if not isinstance(platforms, list):
                        raise ValueError("As plataformas têm de ser uma lista.")
                    clean = []
                    for item in platforms[:20]:
                        value = re.sub(r"[^a-z0-9_.\-]+", "", str(item or "").strip().lower())[:40]
                        if value:
                            clean.append(value)
                    updates["automation_platforms"] = clean
                if "max_age_days" in req:
                    days = int(req["max_age_days"])
                    if days < 1 or days > 365:
                        raise ValueError("A validade das propostas tem de estar entre 1 e 365 dias.")
                    updates["automation_max_age_days"] = days
                if "proposals_max" in req:
                    total = int(req["proposals_max"])
                    if total < 1 or total > 50:
                        raise ValueError("O número de propostas tem de estar entre 1 e 50.")
                    updates["rss_proposals_max"] = total
                if not updates:
                    raise ValueError("Nada para atualizar.")
                config.update(updates)
                save_config(config)
                svc = activity_module()
                if svc:
                    try:
                        if config.get("automation_autostart"):
                            svc.install_autostart(APP_DIR)
                        else:
                            svc.remove_autostart()
                    except Exception as exc:
                        print(f"[AVISO] Arranque automatico: {exc}")
                    if config.get("automation_enabled"):
                        threading.Thread(
                            target=lambda: svc.start_service(APP_DIR),
                            name="activity-start",
                            daemon=True,
                        ).start()
                    else:
                        threading.Thread(
                            target=lambda: svc.stop_service(APP_DIR),
                            name="activity-stop",
                            daemon=True,
                        ).start()
                _json_reply(self, 200, {"ok": True, "status": _automation_status()})
            except ValueError as exc:
                _json_reply(self, 400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                _json_reply(self, 500, {"ok": False, "error": str(exc)})
            return

        if self.path == "/save_config":
            # Nota: config e mutado no lugar (nunca reatribuido), por isso nao
            # precisa da declaracao global - que alias colidiria com o uso de
            # config nos ramos anteriores deste metodo.
            try:
                new = json.loads(data)
                if not isinstance(new, dict):
                    raise ValueError("As definições têm de ser um objeto JSON.")
                unknown = sorted(set(new) - CONFIG_WRITABLE_KEYS)
                if unknown:
                    raise ValueError(
                        "Definições não reconhecidas: " + ", ".join(unknown[:5])
                    )
                if "server_port" in new:
                    try:
                        _port = int(new["server_port"])
                    except (TypeError, ValueError):
                        raise ValueError("A porta do servidor é inválida.")
                    if not 1024 <= _port <= 65535:
                        raise ValueError("A porta do servidor tem de estar entre 1024 e 65535.")
                    new["server_port"] = _port
                if "downloads_mode" in new and new["downloads_mode"] not in ("internal", "system", "custom"):
                    raise ValueError("O destino dos downloads é inválido.")
                for _str_key, _max_len in (
                    ("po_token", 4096),
                    ("visitor_data", 4096),
                    ("custom_ffmpeg_path", 1024),
                    ("downloads_custom_dir", 1024),
                    ("language", 16),
                    ("theme", 32),
                    ("theme_palette", 32),
                    ("cookies_browser", 32),
                    ("cookies_method", 32),
                    ("sub_mode", 16),
                    ("sub_langs", 200),
                    ("library_filter", 32),
                    ("app_release_repo", 200),
                ):
                    if _str_key not in new:
                        continue
                    if new[_str_key] is None:
                        new.pop(_str_key)
                        continue
                    if not isinstance(new[_str_key], str):
                        raise ValueError(f"O valor de {_str_key} é inválido.")
                    new[_str_key] = new[_str_key].strip()[:_max_len]
                for _int_key, _low, _high in (
                    ("download_delay", 0, 60),
                    ("download_retries", 0, 20),
                    ("categories_per_row", 1, 8),
                ):
                    if _int_key not in new:
                        continue
                    try:
                        _value = int(new[_int_key])
                    except (TypeError, ValueError):
                        raise ValueError(f"O valor de {_int_key} é inválido.")
                    if not _low <= _value <= _high:
                        raise ValueError(f"O valor de {_int_key} tem de estar entre {_low} e {_high}.")
                    new[_int_key] = _value
                if "categories" in new and not isinstance(new["categories"], list):
                    raise ValueError("As gavetas têm de ser uma lista.")
                if "auto_quality_recommendation" in new and not isinstance(
                    new["auto_quality_recommendation"], bool
                ):
                    raise ValueError("A recomendação automática tem de ser booleana.")
                if "preview_position" in new and new["preview_position"] not in PREVIEW_POSITIONS:
                    raise ValueError("A posição da pré-visualização é inválida.")
                for _bool_key in ("automation_enabled", "automation_autostart"):
                    if _bool_key in new and not isinstance(new[_bool_key], bool):
                        raise ValueError("As opções de automatismo têm de ser booleanas.")
                if "automation_mode" in new and new["automation_mode"] not in ("manual", "auto"):
                    raise ValueError("O modo de automatismo é inválido.")
                if "automation_interval" in new:
                    try:
                        _automation_interval = int(new["automation_interval"])
                    except (TypeError, ValueError):
                        raise ValueError("O intervalo do automatismo é inválido.")
                    if not 5 <= _automation_interval <= 1440:
                        raise ValueError("O intervalo do automatismo tem de estar entre 5 e 1440 minutos.")
                    new["automation_interval"] = _automation_interval
                if "automation_max_age_days" in new:
                    try:
                        _automation_age = int(new["automation_max_age_days"])
                    except (TypeError, ValueError):
                        raise ValueError("A validade das propostas é inválida.")
                    if not 1 <= _automation_age <= 365:
                        raise ValueError("A validade das propostas tem de estar entre 1 e 365 dias.")
                    new["automation_max_age_days"] = _automation_age
                if "rss_proposals_max" in new:
                    try:
                        _proposals_max = int(new["rss_proposals_max"])
                    except (TypeError, ValueError):
                        raise ValueError("O limite de propostas é inválido.")
                    if not 1 <= _proposals_max <= 50:
                        raise ValueError("O limite de propostas tem de estar entre 1 e 50.")
                    new["rss_proposals_max"] = _proposals_max
                if "automation_platforms" in new:
                    if not isinstance(new["automation_platforms"], list):
                        raise ValueError("As plataformas do automatismo têm de ser uma lista.")
                    new["automation_platforms"] = [
                        re.sub(r"[^a-z0-9_.\-]+", "", str(item or "").strip().lower())[:40]
                        for item in new["automation_platforms"][:20]
                        if str(item or "").strip()
                    ]
                    new["automation_platforms"] = [p for p in new["automation_platforms"] if p]
                was_enabled = bool(config.get("automation_enabled"))
                was_autostart = bool(config.get("automation_autostart"))
                config.update(new)
                save_config(config)
                if was_enabled != bool(config.get("automation_enabled")) or was_autostart != bool(config.get("automation_autostart")):
                    svc = activity_module()
                    if svc:
                        try:
                            if config.get("automation_autostart"):
                                svc.install_autostart(APP_DIR)
                            else:
                                svc.remove_autostart()
                        except Exception:
                            pass
                        if config.get("automation_enabled"):
                            threading.Thread(target=lambda: svc.start_service(APP_DIR), daemon=True).start()
                        else:
                            threading.Thread(target=lambda: svc.stop_service(APP_DIR), daemon=True).start()
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
                save_config(config)
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

        if path == "/delete_files":
            try:
                req = json.loads(data or "{}")
                if not isinstance(req, dict):
                    raise ValueError("Dados inválidos.")
                paths = req.get("paths", [])
                if not isinstance(paths, list):
                    raise ValueError("paths tem de ser uma lista.")
                remove_file = bool(req.get("remove_file", True))
                remove_history = bool(req.get("remove_history", True))

                history_removed = 0
                removed_files = []
                targets = set()
                for item in paths[:500]:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    targets.add(item)
                    full_path = resolve_download_file(item)
                    if not full_path:
                        # Caminho fora da pasta de downloads: nunca apagar.
                        continue
                    targets.add(full_path)
                    if remove_file and os.path.isfile(full_path):
                        os.remove(full_path)
                        removed_files.append(full_path)
                        parent_dir = os.path.dirname(full_path)
                        base_dir = os.path.normpath(get_downloads_dir())
                        if (
                            os.path.normcase(parent_dir) != os.path.normcase(base_dir)
                            and os.path.isdir(parent_dir)
                            and not os.listdir(parent_dir)
                        ):
                            try:
                                os.rmdir(parent_dir)
                            except OSError:
                                pass

                if remove_history and targets:
                    norm_targets = {os.path.normcase(t) for t in targets}
                    history = load_json(HISTORY_FILE, [])
                    kept = []
                    for entry in history:
                        raw = ""
                        if isinstance(entry, dict):
                            raw = str(entry.get("file_path") or "")
                        full = resolve_download_file(raw) if raw else None
                        matched = (
                            raw in targets
                            or (full is not None and os.path.normcase(full) in norm_targets)
                        )
                        if matched:
                            history_removed += 1
                        else:
                            kept.append(entry)
                    if history_removed:
                        save_json(HISTORY_FILE, kept)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "removed": len(removed_files),
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


def _pid_alive(pid):
    """True se o processo indicado ainda existe."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            # Sem permissao para abrir: assume vivo, para nunca encerrar o
            # servidor por engano.
            return kernel32.GetLastError() == ERROR_ACCESS_DENIED
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_active_download():
    """Termina o yt-dlp/ffmpeg em curso (best effort)."""
    proc = current_process
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
    except Exception:
        pass


def _start_parent_watchdog():
    """Encerra o servidor quando o launcher (processo pai) desaparece.

    Complementa o Job Object do launcher (KILL_ON_JOB_CLOSE): mesmo que a
    associacao ao job falhe, ou que o launcher morra de forma abrupta, o
    servidor nao fica orfao a segurar a porta, o yt-dlp e o ffmpeg.
    So e ativado quando o servidor foi arrancado pela aplicacao.
    """
    parent = os.getppid()
    if parent <= 0:
        return

    def _watch():
        while True:
            time.sleep(2.0)
            if not _pid_alive(parent):
                print("[INFO] O launcher terminou. A encerrar o servidor...")
                _terminate_active_download()
                os._exit(0)

    threading.Thread(target=_watch, name="launcher-watchdog", daemon=True).start()


def _check_app_update():
    try:
        repo = APP_RELEASE_REPO or config.get("app_release_repo") or ""
        if not repo:
            return
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "MediaDesk", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").strip().lstrip("v")
        current = (APP_VERSION or "").strip().lstrip("v")
        if tag and current and tag != current:
            msg = f"Atualização disponível: {tag} (atual: {APP_VERSION})"
            broadcast(f"TOAST:info:{msg}")
            broadcast_log(f"[UPDATE] {msg}")
    except Exception as e:
        broadcast_log(f"[UPDATE] verificação falhou: {e}")


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
            # Escuta apenas em loopback: a aplicacao e local e nao deve ficar
            # exposta na rede (nem permitir pedidos de outros dispositivos).
            server = QuietServer(("127.0.0.1", port), Handler)
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
                    json.dump({"error": "Sem portas livres", "pid": os.getpid()}, fh)
            except Exception:
                pass
        return

    server_instance = server
    _start_dependency_check()
    _start_queue_worker()
    _cleanup_activity_temp()
    _start_automation_service()
    # So quando arrancado pela aplicacao (o launcher define este ficheiro).
    if os.environ.get("MEDIADESK_RESPONSE_FILE"):
        _start_parent_watchdog()
    threading.Thread(target=lambda: (time.sleep(2), _check_app_update()), daemon=True).start()
    print(f"\n[INFO] Servidor ativo em http://localhost:{actual_port}")
    print("[INFO] Pressione Ctrl+C para parar\n")

    # Reportar a porta real ao launcher (so ele abre a UI com ESTA instancia).
    if os.environ.get("MEDIADESK_RESPONSE_FILE"):
        try:
            with open(os.environ["MEDIADESK_RESPONSE_FILE"], "w", encoding="utf-8") as fh:
                json.dump({"port": actual_port, "pid": os.getpid()}, fh)
        except Exception:
            pass

    if os.environ.get("MEDIADESK_OPEN_BROWSER") and not os.environ.get("MEDIADESK_NO_BROWSER"):
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
    # Compara os ficheiros com os hashes guardados e aplica o nivel de
    # atualizacao definido em version.json ("unreleased") antes de servir.
    try:
        _version_result = ensure_version_current()
        if _version_result.get("bumped"):
            print(
                f"[INFO] Versao sincronizada: v{_version_result.get('previous')} -> "
                f"v{_version_result.get('version')} ({_version_result.get('level')})"
            )
        elif _version_result.get("changed"):
            print("[INFO] Alteracoes locais detetadas (sem bump pendente).")
    except Exception as _exc:
        print(f"[AVISO] Motor de versao: {_exc}")
    threading.Thread(target=integrity_worker, daemon=True).start()
    run_server()