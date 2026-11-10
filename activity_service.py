#!/usr/bin/env python3
"""Servico de atividade e RSS do YT-DLP Media Desk.

Responsabilidades:
  * Agrega os metadados de cada download num ficheiro cifrado `data/activity.enc`
    (plataforma, canal, uploader, data, tamanho, tema e metadados extra).
  * Aprende preferencias (plataformas/canais/temas/palavras-chave) a partir do
    historico e das acoes do utilizador (aprovar/rejeitar propostas).
  * Monitoriza feeds RSS/Atom em segundo plano, mesmo com a aplicacao fechada.
  * Gera uma lista curada de propostas de download em `rss_proposals.json`.

O processo e lancado pelo servidor (ou pelo arranque automatico do Windows) e
nao depende do WebView2 nem da interface. Usa apenas a biblioteca padrao do
Python 3.10 embebido.

Cifra: chave aleatoria de 32 bytes protegida com DPAPI (ambito do utilizador),
PBKDF2-HMAC-SHA256 por ficheiro, fluxo SHA-256 em modo contador e HMAC-SHA256
(encrypt-then-MAC). Nada e escrito em claro no disco.
"""
from __future__ import annotations

import base64
import ctypes
import gzip
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, urlencode, urlparse

LOG = logging.getLogger("mediadesk.activity")
SCHEMA = 1
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YT-DLP-Media-Desk/3.11"
MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_FEED_ITEMS = 200
MAX_DOWNLOADS = 5000
MAX_SEEN = 5000
PBKDF2_ROUNDS = 90_000
CONFIG_MAGIC = b"MEDIADESK-CONFIG-DPAPI-v1\n"

SUPPORTED_PLATFORMS = (
    "youtube", "vimeo", "rumble", "odysee", "tiktok", "instagram",
    "facebook", "x", "twitch", "soundcloud", "bitchute", "dailymotion",
    "peertube", "kick", "bilibili", "web",
)

_PLATFORM_HOSTS = (
    ("youtube", ("youtube.com", "youtu.be", "youtube-nocookie.com")),
    ("vimeo", ("vimeo.com",)),
    ("rumble", ("rumble.com",)),
    ("odysee", ("odysee.com", "lbry.tv")),
    ("tiktok", ("tiktok.com",)),
    ("instagram", ("instagram.com",)),
    ("facebook", ("facebook.com", "fb.watch")),
    ("x", ("x.com", "twitter.com")),
    ("twitch", ("twitch.tv",)),
    ("soundcloud", ("soundcloud.com",)),
    ("bitchute", ("bitchute.com",)),
    ("dailymotion", ("dailymotion.com", "dai.ly")),
    ("kick", ("kick.com",)),
    ("bilibili", ("bilibili.com", "b23.tv")),
)

_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "uma", "dos", "das",
    "para", "com", "sem", "por", "que", "como", "mais", "novo", "nova", "video",
    "audio", "official", "music", "video", "full", "part", "episode", "ep",
}


# =====================================================================
# Caminhos e configuracao
# =====================================================================
def _app_dir(app_dir=None):
    if app_dir:
        return os.path.abspath(str(app_dir))
    return os.path.dirname(os.path.abspath(__file__))


def paths(app_dir=None):
    root = _app_dir(app_dir)
    data = os.path.join(root, "data")
    return {
        "root": root,
        "data": data,
        "activity": os.path.join(data, "activity.enc"),
        "config": os.path.join(data, "config.enc"),
        "legacy_config": os.path.join(root, "config.json"),
        "key": os.path.join(data, "activity.key"),
        "lock": os.path.join(data, "activity.lock"),
        "service_lock": os.path.join(data, "service.lock"),
        "heartbeat": os.path.join(data, "service.heartbeat"),
        "stop": os.path.join(data, "service.stop"),
        "trigger": os.path.join(data, "rss_now"),
        "log": os.path.join(data, "service.log"),
        "rss_cache": os.path.join(data, "rss_cache"),
        "history": os.path.join(root, "history.json"),
        "channels": os.path.join(root, "rss_channels.json"),
        "proposals": os.path.join(root, "rss_proposals.json"),
        "script": os.path.join(root, "activity_service.py"),
        "python": os.path.join(root, "bin", "python", "pythonw.exe"),
        "python_console": os.path.join(root, "bin", "python", "python.exe"),
    }


def _ensure_dirs(root):
    p = paths(root)
    os.makedirs(p["data"], exist_ok=True)
    os.makedirs(p["rss_cache"], exist_ok=True)
    return p


def load_config(app_dir=None):
    p = paths(app_dir)
    if not os.path.exists(p["config"]) and not os.path.exists(p["legacy_config"]):
        return {}
    if os.path.exists(p["config"]):
        try:
            with open(p["config"], "rb") as fh:
                data = _decode_config(fh.read())
        except Exception as exc:
            raise RuntimeError(
                "Nao foi possivel validar data/config.enc. O ficheiro foi preservado; "
                "verifique se foi criado por outra conta ou computador."
            ) from exc
        if os.path.exists(p["legacy_config"]):
            legacy = _read_legacy_config(p["legacy_config"])
            if legacy:
                data.update(legacy)
                _write_config(data, p["config"])
                _verify_config(data, p["config"])
            os.remove(p["legacy_config"])
        return data

    data = _read_legacy_config(p["legacy_config"])
    _write_config(data, p["config"])
    _verify_config(data, p["config"])
    os.remove(p["legacy_config"])
    return data


def _read_legacy_config(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except Exception as exc:
        raise RuntimeError(f"Nao foi possivel ler a configuracao antiga: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError("A configuracao antiga nao e um objeto JSON.")
    return data


def _encode_config(data):
    if os.name != "nt":
        raise OSError("A cifragem das definicoes requer DPAPI no Windows.")
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return CONFIG_MAGIC + _dpapi_protect(raw)


def _decode_config(blob):
    if not blob.startswith(CONFIG_MAGIC):
        raise ValueError("config.enc nao e um ficheiro MediaDesk.")
    raw = _dpapi_unprotect(blob[len(CONFIG_MAGIC):])
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("As definicoes desencriptadas nao sao um objeto JSON.")
    return data


def _write_config(data, path):
    temporary = f"{path}.{os.getpid()}.{threading.get_ident()}.verified"
    try:
        _atomic_write(temporary, _encode_config(data))
        _verify_config(data, temporary)
        os.replace(temporary, path)
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass


def _verify_config(expected, path):
    with open(path, "rb") as fh:
        actual = _decode_config(fh.read())
    if actual != expected:
        raise RuntimeError("A validacao de data/config.enc falhou.")


def save_config(data, app_dir=None):
    if not isinstance(data, dict):
        raise ValueError("A configuracao tem de ser um objeto.")
    config_path = paths(app_dir)["config"]
    _write_config(data, config_path)
    _verify_config(data, config_path)


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except Exception:
            pass
    os.replace(tmp, path)


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _info_tags(info):
    tags = info.get("tags")
    if not isinstance(tags, list):
        return []
    return [str(tag)[:60] for tag in tags[:20]]


def _min_iso(current, candidate):
    if not current:
        return candidate
    if not candidate:
        return current
    first, second = _parse_iso(current), _parse_iso(candidate)
    if first and second:
        return candidate if second < first else current
    return candidate if str(candidate) < str(current) else current


def _max_iso(current, candidate):
    if not current:
        return candidate
    if not candidate:
        return current
    first, second = _parse_iso(current), _parse_iso(candidate)
    if first and second:
        return candidate if second > first else current
    return candidate if str(candidate) > str(current) else current


# =====================================================================
# Bloqueio entre processos (servidor + servico)
# =====================================================================
@contextmanager
def _file_lock(app_dir=None, name="lock", timeout=25.0):
    p = _ensure_dirs(app_dir)
    path = p[name]
    fh = open(path, "a+b")
    try:
        if os.path.getsize(path) == 0:
            fh.write(b"\0")
            fh.flush()
        fh.seek(0)
        deadline = time.time() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Bloqueio ocupado: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                fh.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
    finally:
        fh.close()


# =====================================================================
# Cifra (stdlib): DPAPI + PBKDF2 + SHA-256 CTR + HMAC-SHA256
# =====================================================================
_MAGIC = b"MDA1"
_DPAPI_MAGIC = b"DPAPI1"
_SERVICE_LOCK_HANDLE = None


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_call(fn, data):
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI indisponivel")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_protect(data):
    if os.name != "nt":
        raise OSError("DPAPI requer Windows")
    return _dpapi_call(ctypes.windll.crypt32.CryptProtectData, data)


def _dpapi_unprotect(data):
    if os.name != "nt":
        raise OSError("DPAPI requer Windows")
    return _dpapi_call(ctypes.windll.crypt32.CryptUnprotectData, data)


def _secret(app_dir=None):
    """Chave-mestra local. Preferencia: DPAPI; fallback: ficheiro 0600."""
    env = os.environ.get("MEDIADESK_ACTIVITY_KEY", "").strip()
    if env:
        try:
            raw = base64.b64decode(env)
            if len(raw) >= 16:
                return raw
        except Exception:
            pass
    p = _ensure_dirs(app_dir)["key"]
    if os.path.exists(p):
        try:
            with open(p, "rb") as fh:
                blob = fh.read()
        except Exception:
            blob = b""
        if blob.startswith(_DPAPI_MAGIC):
            try:
                return _dpapi_unprotect(blob[len(_DPAPI_MAGIC):])
            except Exception:
                raise RuntimeError(
                    "Nao foi possivel desproteger data/activity.key com DPAPI. "
                    "O ficheiro foi criado por outro utilizador/maquina?"
                )
        if len(blob) >= 16:
            return blob

    new_key = secrets.token_bytes(32)
    try:
        payload = _DPAPI_MAGIC + _dpapi_protect(new_key)
    except Exception:
        if os.name == "nt":
            raise RuntimeError("Nao foi possivel proteger a chave de atividade com DPAPI.")
        payload = new_key
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # Outro processo ganhou a corrida: espera que a chave fique completa.
        for _ in range(40):
            time.sleep(0.05)
            try:
                with open(p, "rb") as fh:
                    blob = fh.read()
            except Exception:
                continue
            if blob.startswith(_DPAPI_MAGIC):
                return _dpapi_unprotect(blob[len(_DPAPI_MAGIC):])
            if len(blob) >= 16:
                return blob
        raise RuntimeError("data/activity.key existe mas esta vazio/invalido")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except Exception:
            pass
    return new_key


def _derive(secret, salt):
    material = hashlib.pbkdf2_hmac("sha256", secret, salt, PBKDF2_ROUNDS, dklen=64)
    return material[:32], material[32:]


def _keystream(key, nonce, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:length])


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def encrypt_blob(plain, secret):
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _derive(secret, salt)
    cipher = _xor(plain, _keystream(enc_key, nonce, len(plain)))
    header = _MAGIC + salt + nonce
    tag = hmac.new(mac_key, header + cipher, hashlib.sha256).digest()
    return header + tag + cipher


def decrypt_blob(blob, secret):
    if not blob or not blob.startswith(_MAGIC):
        raise ValueError("activity.enc nao e um ficheiro MediaDesk")
    pos = len(_MAGIC)
    salt = blob[pos:pos + 16]
    nonce = blob[pos + 16:pos + 32]
    tag = blob[pos + 32:pos + 64]
    cipher = blob[pos + 64:]
    if len(salt) != 16 or len(nonce) != 16 or len(tag) != 32:
        raise ValueError("activity.enc truncado")
    enc_key, mac_key = _derive(secret, salt)
    expected = hmac.new(mac_key, _MAGIC + salt + nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("activity.enc corrompido ou chave errada")
    return _xor(cipher, _keystream(enc_key, nonce, len(cipher)))


# =====================================================================
# Modelo de atividade
# =====================================================================
def _empty_activity():
    return {
        "schema": SCHEMA,
        "created_at": _now_iso(),
        "updated_at": None,
        "downloads": [],
        "platforms": {},
        "preferences": {
            "platforms": {}, "channels": {}, "uploaders": {},
            "themes": {}, "keywords": {}, "updated_at": None,
        },
        "rss": {"seen": [], "actions": [], "last_check": None, "last_error": None},
    }


def _normalize_activity(data):
    base = _empty_activity()
    if not isinstance(data, dict):
        return base
    base.update({k: v for k, v in data.items() if k in base})
    for key in ("downloads", "platforms", "preferences", "rss"):
        if not isinstance(base.get(key), type(base[key])):
            base[key] = _empty_activity()[key]
    prefs = base["preferences"]
    for key in ("platforms", "channels", "uploaders", "themes", "keywords"):
        if not isinstance(prefs.get(key), dict):
            prefs[key] = {}
    rss = base["rss"]
    for key in ("seen", "actions"):
        if not isinstance(rss.get(key), list):
            rss[key] = []
    return base


def load_activity(app_dir=None):
    p = _ensure_dirs(app_dir)
    if not os.path.exists(p["activity"]):
        return _empty_activity()
    try:
        with open(p["activity"], "rb") as fh:
            blob = fh.read()
        data = json.loads(decrypt_blob(blob, _secret(app_dir)).decode("utf-8"))
        return _normalize_activity(data)
    except Exception as exc:
        LOG.error("Nao foi possivel ler activity.enc: %s", exc)
        try:
            backup = f"{p['activity']}.corrupt-{int(time.time())}"
            os.replace(p["activity"], backup)
            LOG.error("Ficheiro ilegivel preservado em %s", backup)
        except Exception:
            pass
        return _empty_activity()


def _save_activity(data, app_dir=None):
    p = _ensure_dirs(app_dir)
    data["schema"] = SCHEMA
    data["updated_at"] = _now_iso()
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _atomic_write(p["activity"], encrypt_blob(raw, _secret(app_dir)))


# =====================================================================
# Preferencias
# =====================================================================
def _bump(mapping, key, amount=1):
    if not key:
        return
    key = str(key).strip()
    if not key:
        return
    mapping[key] = max(0, int(mapping.get(key, 0)) + amount)
    if len(mapping) > 400:
        for old in sorted(mapping, key=lambda k: mapping[k])[: max(0, len(mapping) - 300)]:
            mapping.pop(old, None)


def _keywords(title):
    words = re.findall(r"[0-9A-Za-zÀ-ÿ]{4,}", (title or "").lower())
    return [w for w in words if w not in _STOPWORDS][:12]


def _learn(activity, entry, weight=1):
    prefs = activity["preferences"]
    _bump(prefs["platforms"], entry.get("platform"), weight)
    _bump(prefs["channels"], entry.get("channel"), weight)
    _bump(prefs["uploaders"], entry.get("uploader"), weight)
    _bump(prefs["themes"], entry.get("theme"), weight)
    for word in _keywords(entry.get("title")):
        _bump(prefs["keywords"], word, weight)
    prefs["updated_at"] = _now_iso()


def _affinity(mapping, key):
    try:
        value = float(mapping.get(key, 0) or 0)
        top = max([float(v or 0) for v in mapping.values()] or [0])
    except Exception:
        return 0.0
    return (value / top) if top > 0 else 0.0


# =====================================================================
# Registo de downloads
# =====================================================================
def _download_id(entry):
    base = "|".join(
        str(entry.get(k) or "")
        for k in ("platform", "url", "title", "date", "file_path")
    )
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:20]


def _safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _platform_from_info(info, url):
    aliases = {
        "youtube": "youtube",
        "youtube:tab": "youtube",
        "youtube:playlist": "youtube",
        "twitter": "x",
        "twitter:broadcast": "x",
        "twitch:vod": "twitch",
    }
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    platform = aliases.get(extractor, extractor.split(":", 1)[0])
    return platform if platform in SUPPORTED_PLATFORMS else detect_platform(url)


def _merge_platform(activity, entry):
    platform = str(entry.get("platform") or "web").lower()
    slot = activity["platforms"].setdefault(platform, {
        "count": 0, "bytes": 0, "first_seen": None, "last_seen": None,
        "channels": {}, "uploaders": {}, "themes": {}, "media_types": {},
    })
    slot["count"] = int(slot.get("count", 0)) + 1
    slot["bytes"] = int(slot.get("bytes", 0)) + int(entry.get("file_size") or 0)
    slot["first_seen"] = _min_iso(slot.get("first_seen"), entry.get("date"))
    slot["last_seen"] = _max_iso(slot.get("last_seen"), entry.get("date") or _now_iso())
    for field, bucket in (
        ("channel", "channels"), ("uploader", "uploaders"),
        ("theme", "themes"), ("media_type", "media_types"),
    ):
        value = entry.get(field)
        if value:
            _bump(slot.setdefault(bucket, {}), value, 1)


def _downloads_dir(root, config):
    mode = str(config.get("downloads_mode") or "internal")
    if mode == "system":
        base = os.path.join(os.path.expanduser("~"), "Downloads")
    elif mode == "custom":
        base = str(config.get("downloads_custom_dir") or "").strip()
        if not base:
            base = os.path.join(root, "downloads")
    else:
        base = os.path.join(root, "downloads")
    if not os.path.isabs(base):
        base = os.path.join(root, base)
    return base


def _resolve_media_path(root, file_path):
    rel = str(file_path or "").strip()
    if not rel:
        return None
    if rel.startswith("/downloads/"):
        rel = rel[len("/downloads/"):]
    elif rel.startswith("downloads/"):
        rel = rel[len("downloads/"):]
    rel = rel.replace("/", os.sep)
    downloads = os.path.realpath(_downloads_dir(root, load_config(root)))
    candidate = os.path.realpath(rel if os.path.isabs(rel) else os.path.join(downloads, rel))
    try:
        if os.path.commonpath((downloads, candidate)) != downloads:
            return None
    except ValueError:
        return None
    return candidate if os.path.isfile(candidate) else None


def _read_info_json(media_path):
    if not media_path:
        return {}
    sidecar = os.path.splitext(media_path)[0] + ".info.json"
    try:
        if os.path.getsize(sidecar) > MAX_FEED_BYTES:
            return {}
        with open(sidecar, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _history_entries(root, exclude_urls=None):
    """Converte o historico existente em entradas de atividade.

    Serve para integrar os downloads anteriores no primeiro activity.enc, sem
    perder o contexto de quem ja usava a aplicacao.
    """
    exclude_urls = {str(u) for u in (exclude_urls or set()) if u}
    try:
        with open(paths(root)["history"], "r", encoding="utf-8-sig") as fh:
            history = json.load(fh)
    except Exception:
        return []
    if not isinstance(history, list):
        return []
    entries = []
    for item in history[:1000]:
        if not isinstance(item, dict) or item.get("status") != "success":
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in exclude_urls:
            continue
        rel = str(item.get("file_path") or "").strip()
        disk_path = _resolve_media_path(root, rel)
        info = _read_info_json(disk_path)
        entries.append({
            "url": url,
            "date": item.get("date") or _now_iso(),
            "title": info.get("title") or item.get("title") or (os.path.basename(disk_path) if disk_path else None),
            "platform": str(item.get("platform") or _platform_from_info(info, url)).lower(),
            "channel": info.get("channel") or info.get("uploader") or info.get("creator"),
            "channel_id": info.get("channel_id"),
            "channel_url": info.get("channel_url"),
            "uploader": info.get("uploader") or info.get("channel") or info.get("artist"),
            "uploader_id": info.get("uploader_id"),
            "uploader_url": info.get("uploader_url"),
            "file_path": rel or None,
            "file_name": os.path.basename(disk_path) if disk_path else None,
            "file_size": os.path.getsize(disk_path) if disk_path else None,
            "media_type": item.get("media_type") or info.get("ext"),
            "theme": None,
            "theme_mode": None,
            "duration": _safe_int(info.get("duration")),
            "view_count": _safe_int(info.get("view_count")),
            "upload_date": info.get("upload_date") or info.get("release_date"),
            "ext": info.get("ext"),
            "width": _safe_int(info.get("width")),
            "height": _safe_int(info.get("height")),
            "tags": _info_tags(info),
            "thumbnail": info.get("thumbnail"),
            "description": str(info.get("description") or "")[:500],
            "extractor": info.get("extractor"),
            "source": "history",
        })
    return entries


def _apply_download(activity, entry):
    """Aplica uma entrada (nova ou repetida) ao modelo em memoria."""
    existing = next((d for d in activity["downloads"] if d.get("id") == entry["id"]), None)
    if existing:
        for key, value in entry.items():
            if value in (None, "", 0, [], {}):
                continue
            if not existing.get(key):
                existing[key] = value
        existing["last_downloaded_at"] = entry.get("date")
        if entry.get("file_path"):
            existing["file_path"] = entry["file_path"]
        if entry.get("file_size"):
            existing["file_size"] = entry["file_size"]
        return True
    activity["downloads"].insert(0, entry)
    activity["downloads"] = activity["downloads"][:MAX_DOWNLOADS]
    _merge_platform(activity, entry)
    _learn(activity, entry, 1)
    return False


def record_download(entry, app_dir=None):
    """Cria/atualiza activity.enc com um download concluido.

    Devolve um resumo ou None em caso de falha. Nunca propaga excecoes para o
    fluxo de download: a atividade e um efeito secundario.
    """
    if not isinstance(entry, dict):
        return None
    try:
        setup_logging(app_dir)
    except Exception:
        pass
    entry = dict(entry)
    entry.setdefault("date", _now_iso())
    entry.setdefault("platform", detect_platform(entry.get("url")))
    entry["platform"] = str(entry["platform"] or "web").lower()
    if not entry.get("file_size"):
        media = _resolve_media_path(_app_dir(app_dir), entry.get("file_path"))
        if media:
            try:
                entry["file_size"] = os.path.getsize(media)
            except OSError:
                pass
    entry["id"] = entry.get("id") or _download_id(entry)
    try:
        with _file_lock(app_dir):
            activity_path = paths(app_dir)["activity"]
            existed = os.path.exists(activity_path)
            activity = load_activity(app_dir)
            backfilled = 0
            if not existed or not os.path.exists(activity_path):
                # Primeiro download: integra os registos anteriores do
                # historico, para o ficheiro nascer ja com contexto.
                for old in _history_entries(_app_dir(app_dir), {entry.get("url")}):
                    if not _apply_download(activity, {**old, "id": _download_id(old)}):
                        backfilled += 1
            merged = _apply_download(activity, entry)
            _save_activity(activity, app_dir)
            return {
                "id": entry["id"],
                "created": not merged,
                "platform": entry["platform"],
                "downloads": len(activity["downloads"]),
                "platforms": len(activity["platforms"]),
                "backfilled": backfilled,
            }
    except Exception as exc:
        LOG.exception("Falha ao registar atividade: %s", exc)
        return None


def record_action(proposal, action, app_dir=None):
    """Aprende com uma decisao do utilizador sobre uma proposta."""
    if not isinstance(proposal, dict):
        return None
    try:
        with _file_lock(app_dir):
            activity = load_activity(app_dir)
            action = str(action or "").lower()
            weight = 2 if action in ("approved", "accepted", "download") else -1
            entry = {
                "platform": proposal.get("platform"),
                "channel": proposal.get("channel_name"),
                "uploader": proposal.get("uploader") or proposal.get("channel_name"),
                "title": proposal.get("title"),
                "theme": load_config(app_dir).get("theme_palette") or "indigo",
            }
            _learn(activity, entry, weight)
            activity["rss"]["actions"].insert(0, {
                "id": proposal.get("id"),
                "url": proposal.get("url"),
                "title": proposal.get("title"),
                "channel": proposal.get("channel_name"),
                "platform": proposal.get("platform"),
                "action": action,
                "at": _now_iso(),
            })
            activity["rss"]["actions"] = activity["rss"]["actions"][:500]
            _save_activity(activity, app_dir)
            return True
    except Exception as exc:
        LOG.warning("Falha ao registar acao: %s", exc)
        return None


def get_summary(app_dir=None):
    activity = load_activity(app_dir)
    prefs = activity["preferences"]
    platforms = sorted(
        activity["platforms"].items(),
        key=lambda kv: int(kv[1].get("count", 0)),
        reverse=True,
    )
    return {
        "created_at": activity.get("created_at"),
        "updated_at": activity.get("updated_at"),
        "downloads": len(activity["downloads"]),
        "platforms": [
            {
                "platform": name,
                "count": int(info.get("count", 0)),
                "bytes": int(info.get("bytes", 0)),
                "last_seen": info.get("last_seen"),
                "channels": info.get("channels", {}),
            }
            for name, info in platforms
        ],
        "preferences": {
            "platforms": dict(sorted(prefs.get("platforms", {}).items(), key=lambda kv: kv[1], reverse=True)[:8]),
            "channels": dict(sorted(prefs.get("channels", {}).items(), key=lambda kv: kv[1], reverse=True)[:12]),
            "themes": prefs.get("themes", {}),
            "keywords": dict(sorted(prefs.get("keywords", {}).items(), key=lambda kv: kv[1], reverse=True)[:15]),
        },
        "last_check": activity["rss"].get("last_check"),
    }


def suggestion_channels(app_dir=None, limit=8):
    """Canais observados na atividade e no histórico local."""
    activity = load_activity(app_dir)
    downloads = list(activity.get("downloads", []))
    known_urls = {
        str(item.get("url") or "").strip()
        for item in downloads
        if item.get("url")
    }
    downloads.extend(
        entry
        for entry in _history_entries(_app_dir(app_dir))
        if entry.get("url") and entry["url"] not in known_urls
    )
    items = {}
    for download in downloads:
        name = str(download.get("channel") or download.get("uploader") or "").strip()
        if not name:
            continue
        platform = str(download.get("platform") or "web").lower()
        url = str(download.get("channel_url") or download.get("uploader_url") or "").strip()
        channel_id = str(download.get("channel_id") or "").strip()
        if not url and platform == "youtube" and channel_id.startswith("UC"):
            url = f"https://www.youtube.com/channel/{channel_id}"
        key = (platform, channel_id.casefold() or name.casefold())
        slot = items.get(key)
        if slot is None:
            slot = items[key] = {
                "name": name,
                "platform": platform,
                "url": url,
                "channel_id": channel_id,
                "count": 0,
                "last_seen": None,
            }
        slot["count"] += 1
        if url and not slot["url"]:
            slot["url"] = url
        slot["last_seen"] = _max_iso(slot["last_seen"], download.get("date"))

    for item in items.values():
        item.update(rss_capability(item))

    now = datetime.now(timezone.utc)
    for item in items.values():
        last_seen = _parse_iso(item.get("last_seen"))
        age_days = max(0.0, (now - last_seen).total_seconds() / 86400) if last_seen else 365
        recency = 0.5 ** (age_days / 90)
        item["score"] = round(
            0.75 * item["count"] / (item["count"] + 3) + 0.25 * recency,
            4,
        )
    ranked = sorted(
        items.values(),
        key=lambda item: (-item["score"], -item["count"], item["name"].casefold()),
    )
    return ranked[: max(1, int(limit))]


def rss_capability(channel):
    """Classifica apenas rotas RSS/Atom utilizáveis sem scraping ou serviços terceiros."""
    platform = str(channel.get("platform") or "").strip().lower()
    url = str(channel.get("url") or "").strip()
    channel_id = str(channel.get("channel_id") or "").strip()
    parsed = urlparse(url if re.match(r"^https?://", url, re.I) else "")
    path = parsed.path.lower()
    query = parse_qs(parsed.query)

    def result(status, reason, feed_url=None, supported=None):
        return {
            "rss_status": status,
            "rss_supported": status == "supported" if supported is None else supported,
            "rss_reason": reason,
            "rss_feed_url": feed_url,
        }

    if platform == "youtube":
        match = re.search(r"(?:channel/|channel_id=)(UC[\w-]{22})", url)
        if not match:
            match = re.search(r"[?&]channel_id=(UC[\w-]{22})", url)
        channel_id = channel_id or (match.group(1) if match else "")
        if "youtube.com/feeds/videos.xml" in url and query.get("channel_id"):
            return result("supported", "Feed Atom oficial do canal.", url)
        if re.fullmatch(r"UC[\w-]{22}", channel_id):
            return result(
                "supported",
                "Feed Atom oficial disponível com o ID do canal.",
                f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
            )
        return result(
            "conditional",
            "O feed oficial requer o ID UC do canal; links de vídeo ou @handle não bastam.",
        )
    if platform == "dailymotion":
        if re.search(r"/rss/user/[^/]+", path):
            return result("supported", "Feed RSS de utilizador disponível.", url)
        match = re.search(r"/user/([^/]+)", path)
        if match:
            feed = f"https://www.dailymotion.com/rss/user/{match.group(1)}"
            return result("supported", "Feed RSS de utilizador disponível.", feed)
        return result("unsupported", "Não foi identificado um perfil de utilizador com feed RSS.")
    if platform == "peertube":
        if path.endswith("/feeds/videos.xml") and (query.get("videoChannelId") or query.get("videochannelid")):
            return result("supported", "Feed RSS do canal PeerTube desta instância.", url)
        if channel_id and parsed.netloc:
            feed = f"{parsed.scheme}://{parsed.netloc}/feeds/videos.xml?{urlencode({'videoChannelId': channel_id})}"
            return result("supported", "Feed RSS disponível; depende da instância PeerTube.", feed)
        return result("conditional", "Feed depende da instância; é necessário o ID do canal ou um URL de feed direto.")
    if platform == "soundcloud":
        if parsed.netloc == "feeds.soundcloud.com" and path.endswith(".rss"):
            return result("supported", "Feed RSS configurado pelo criador.", url)
        return result("conditional", "Só funciona se o criador tiver configurado um feed RSS público; indique o URL do feed.")
    if path.endswith((".rss", ".xml", ".atom")):
        return result(
            "conditional",
            "URL de feed RSS/Atom direto; a compatibilidade será confirmada ao verificar.",
            url,
            supported=True,
        )
    if platform == "vimeo":
        return result("unsupported", "Os feeds RSS antigos do Vimeo foram descontinuados.")
    if platform in {"tiktok", "instagram", "facebook", "x", "twitch", "kick"}:
        return result("unsupported", "A plataforma documenta APIs, não um feed RSS público fiável para canais.")
    if platform in {"rumble", "odysee", "bitchute", "bilibili"}:
        return result("unknown", "Não foi possível confirmar um feed RSS oficial e estável; não será sugerido automaticamente.")
    return result("unsupported", "Não foi identificado um feed RSS/Atom direto para este canal.")


# =====================================================================
# Feeds RSS / Atom
# =====================================================================
def detect_platform(url):
    try:
        host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except Exception:
        host = ""
    for name, hosts in _PLATFORM_HOSTS:
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name
    return host.split(".")[0] if host else "web"


def _local(tag):
    return str(tag).rsplit("}", 1)[-1].lower()


def _child_text(node, names):
    for child in list(node):
        if _local(child.tag) in names:
            text = (child.text or "").strip()
            if text:
                return text
    return ""


def _entry_link(node):
    fallback = ""
    for child in list(node):
        if _local(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        rel = (child.attrib.get("rel") or "alternate").lower()
        text = (child.text or "").strip()
        if rel in ("alternate", "") and (href or text):
            return href or text
        fallback = fallback or href or text
    return fallback


def _parse_date(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    return _parse_iso(value)


def parse_feed(raw, base_url=""):
    """Interpreta RSS 2.0, RSS 1.0/RDF e Atom. Devolve uma lista de itens."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "ignore")
    root = ET.fromstring(raw)
    items = []
    nodes = [n for n in root.iter() if _local(n.tag) in ("item", "entry")]
    for node in nodes[:MAX_FEED_ITEMS]:
        title = _child_text(node, {"title"})
        url = _entry_link(node) or _child_text(node, {"guid", "id"})
        if not url:
            continue
        published = _parse_date(
            _child_text(node, {"pubdate", "published", "updated", "date"})
        )
        author = _child_text(node, {"creator", "author", "name"})
        if not author:
            for child in list(node):
                if _local(child.tag) in ("author", "creator"):
                    author = _child_text(child, {"name"}) or (child.text or "").strip()
                    if author:
                        break
        summary = _child_text(node, {"description", "summary", "content"})
        items.append({
            "id": hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:20],
            "title": re.sub(r"<[^>]+>", "", title).strip() or "(sem titulo)",
            "url": url,
            "published": published.isoformat(timespec="seconds") if published else None,
            "author": author or "",
            "summary": re.sub(r"<[^>]+>", "", summary)[:500],
        })
    return items


def fetch_feed(url, timeout=12):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        length = int(resp.headers.get("Content-Length") or 0)
        if length > MAX_FEED_BYTES:
            raise ValueError(f"feed demasiado grande ({length} bytes)")
        raw = resp.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("feed demasiado grande")
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw)
    return raw


def resolve_feed_url(channel, timeout=12):
    """Aceita um feed direto ou uma pagina de canal (YouTube) e devolve o feed."""
    url = str(channel.get("url") or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    platform = str(channel.get("platform") or detect_platform(url)).lower()
    if not url:
        return None
    if "youtube.com/feeds/videos.xml" in url:
        return url
    if platform == "youtube" or "youtube.com" in url or "youtu.be" in url:
        match = re.search(r"(?:channel/|channel_id=)(UC[\w-]{22})", url)
        if not match:
            match = re.search(r"/channel/(UC[\w-]{22})", url)
        if match:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={match.group(1)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                page = resp.read(MAX_FEED_BYTES).decode("utf-8", "ignore")
            match = re.search(r'"externalId"\s*:\s*"(UC[\w-]{22})"', page) or \
                re.search(r"channel_id=(UC[\w-]{22})", page)
            if match:
                return f"https://www.youtube.com/feeds/videos.xml?channel_id={match.group(1)}"
        except Exception as exc:
            LOG.info("Nao foi possivel resolver o canal YouTube %s: %s", url, exc)
    return url


def load_channels(app_dir=None):
    try:
        with open(paths(app_dir)["channels"], "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_channels(channels, app_dir=None):
    raw = json.dumps(channels, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(paths(app_dir)["channels"], raw)


def load_proposals(app_dir=None):
    try:
        with open(paths(app_dir)["proposals"], "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("proposed", [])
            data.setdefault("seen", [])
            return data
    except Exception:
        pass
    return {"proposed": [], "seen": [], "generated_at": None}


def save_proposals(data, app_dir=None):
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(paths(app_dir)["proposals"], raw)


def _fetch_channel(channel):
    feed_url = resolve_feed_url(channel)
    if not feed_url:
        return {"items": [], "error": "sem URL de feed", "feed_url": None}
    try:
        items = parse_feed(fetch_feed(feed_url), feed_url)
        return {"items": items, "error": None, "feed_url": feed_url}
    except Exception as exc:
        return {"items": [], "error": str(exc)[:220], "feed_url": feed_url}


def _history_urls(app_dir):
    urls = set()
    try:
        with open(paths(app_dir)["history"], "r", encoding="utf-8-sig") as fh:
            history = json.load(fh)
        if isinstance(history, list):
            for entry in history:
                    if not isinstance(entry, dict) or entry.get("status") != "success":
                        continue
                    url = str(entry.get("url") or "").strip()
                    if url:
                        urls.add(url)
    except Exception:
        pass
    return urls


def _merge_historical_preferences(activity, app_dir):
    """Learn from successful history entries not yet represented in activity.enc."""
    known_urls = {
        str(entry.get("url") or "").strip()
        for entry in activity.get("downloads", [])
        if entry.get("url")
    }
    historical = _empty_activity()
    for entry in _history_entries(_app_dir(app_dir)):
        url = str(entry.get("url") or "").strip()
        if not url or url in known_urls:
            continue
        known_urls.add(url)
        _learn(historical, entry)

    preferences = activity.setdefault("preferences", _empty_activity()["preferences"])
    for group, values in historical["preferences"].items():
        if not isinstance(values, dict):
            continue
        target = preferences.setdefault(group, {})
        for name, count in values.items():
            target[name] = float(target.get(name, 0) or 0) + float(count or 0)
    if any(
        isinstance(values, dict) and values
        for values in historical["preferences"].values()
    ):
        preferences["updated_at"] = _now_iso()


def _preference_affinity(mapping, *keys):
    normalized = {}
    for name, value in mapping.items():
        try:
            score = float(value or 0)
        except (TypeError, ValueError):
            continue
        key = str(name).strip().casefold()
        normalized[key] = normalized.get(key, 0.0) + score
    scores = [normalized.get(str(key).strip().casefold(), 0.0) for key in keys if key]
    value = max(scores, default=0.0)
    top = max(normalized.values(), default=0.0)
    return value / top if top > 0 else 0.0


def _score_item(item, activity, prefs):
    published = _parse_iso(item.get("published"))
    if published:
        age_h = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 3600.0)
    else:
        age_h = 24 * 14
    recency = 0.5 ** (age_h / 72.0)
    channel = max(
        _preference_affinity(
            prefs.get("channels", {}),
            item.get("channel_name"),
            item.get("author"),
        ),
        _preference_affinity(
            prefs.get("uploaders", {}),
            item.get("author"),
            item.get("channel_name"),
        ),
    )
    platform = _affinity(prefs.get("platforms", {}), item.get("platform"))
    keywords = prefs.get("keywords", {})
    scores = [_affinity(keywords, w) for w in _keywords(item.get("title"))][:5]
    keyword = sum(scores) / len(scores) if scores else 0.0
    return round(0.45 * recency + 0.25 * channel + 0.20 * platform + 0.10 * keyword, 4)


def build_proposals(items, activity, config, existing, history_urls=None):
    prefs = activity.get("preferences", {})
    seen = existing.get("seen", []) if isinstance(existing, dict) else []
    seen_urls = {str(s.get("url") or "") for s in seen if isinstance(s, dict)}
    seen_ids = {str(s.get("id") or "") for s in seen if isinstance(s, dict)}
    known = set(history_urls or ())
    for entry in activity.get("downloads", []):
        if entry.get("url"):
            known.add(str(entry["url"]))

    max_total = max(1, min(50, int(config.get("rss_proposals_max") or 12)))
    max_age_days = max(1, min(365, int(config.get("automation_max_age_days") or 30)))
    platform_filter = {str(p).lower() for p in (config.get("automation_platforms") or []) if p}
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    per_channel = {}
    candidates = []
    for item in items:
        url = str(item.get("url") or "")
        if not url or url in known or url in seen_urls or item.get("id") in seen_ids:
            continue
        platform = str(item.get("platform") or "web").lower()
        if platform_filter and platform not in platform_filter:
            continue
        published = _parse_iso(item.get("published"))
        if published and published < cutoff:
            continue
        channel_id = item.get("channel_id")
        count = per_channel.get(channel_id, 0)
        if count >= 3:
            continue
        per_channel[channel_id] = count + 1
        score = _score_item(item, activity, prefs)
        reasons = []
        if max(
            _preference_affinity(
                prefs.get("channels", {}),
                item.get("channel_name"),
                item.get("author"),
            ),
            _preference_affinity(
                prefs.get("uploaders", {}),
                item.get("author"),
                item.get("channel_name"),
            ),
        ) >= 0.5:
            reasons.append("canal frequente")
        if _affinity(prefs.get("platforms", {}), platform) >= 0.5:
            reasons.append("plataforma preferida")
        if published:
            reasons.append("recente")
        candidates.append({
            "id": item.get("id") or hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:20],
            "channel_id": channel_id,
            "channel_name": item.get("channel_name") or item.get("author") or "",
            "platform": platform,
            "url": url,
            "title": item.get("title") or "",
            "filename": re.sub(r"[^\w\-. ]+", "", item.get("title") or "")[:120],
            "published": item.get("published"),
            "uploader": item.get("author") or "",
            "proposed_at": int(time.time()),
            "score": score,
            "reason": ", ".join(reasons) or "sugestao do feed",
        })
    candidates.sort(key=lambda p: p.get("score", 0), reverse=True)
    return candidates[:max_total]


def check_feeds(app_dir=None, force=False, heartbeat=False):
    """Le os feeds ativos, aprende com o historico e grava propostas curadas.

    So o processo do servico deve escrever o heartbeat (heartbeat=True): uma
    verificacao manual corre dentro do servidor HTTP e, se escrevesse o
    heartbeat, faria crer que existe um servico de fundo em execucao.
    """
    global _LAST_STATS
    root = _app_dir(app_dir)
    p = _ensure_dirs(root)
    config = load_config(root)
    channels = load_channels(root)
    platform_filter = {
        str(p).lower() for p in (config.get("automation_platforms") or []) if p
    }
    enabled = []
    for channel in channels:
        if not channel.get("enabled", True) or not str(channel.get("url") or "").strip():
            continue
        if platform_filter:
            platform = str(channel.get("platform") or detect_platform(channel.get("url"))).lower()
            if platform not in platform_filter:
                continue
        enabled.append(channel)
    existing = load_proposals(root)
    stats = {"feeds": 0, "items": 0, "proposed": 0, "errors": []}
    collected = []

    if enabled:
        with ThreadPoolExecutor(max_workers=min(4, len(enabled))) as pool:
            futures = {pool.submit(_fetch_channel, ch): ch for ch in enabled}
            for future in as_completed(futures):
                ch = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"items": [], "error": str(exc), "feed_url": None}
                ch["last_checked"] = _now_iso()
                ch["last_error"] = result.get("error")
                ch["feed_url"] = result.get("feed_url") or ch.get("feed_url")
                ch["item_count"] = len(result.get("items") or [])
                stats["feeds"] += 1
                if result.get("error"):
                    stats["errors"].append(f"{ch.get('name') or ch.get('url')}: {result['error']}")
                for item in result.get("items") or []:
                    item = dict(item)
                    item["channel_id"] = ch.get("id")
                    item["channel_name"] = ch.get("name") or item.get("author") or ""
                    item["platform"] = ch.get("platform") or detect_platform(ch.get("url"))
                    collected.append(item)
        if channels:
            try:
                save_channels(channels, root)
            except Exception as exc:
                LOG.warning("Nao foi possivel guardar rss_channels.json: %s", exc)

    stats["items"] = len(collected)
    activity = load_activity(root)
    _merge_historical_preferences(activity, root)
    proposals = build_proposals(
        collected, activity, config, existing, _history_urls(root)
    )
    # Mantem propostas anteriores ainda por decidir: o servico pode correr
    # varias vezes ate o utilizador abrir a aplicacao.
    max_total = max(1, min(50, int(config.get("rss_proposals_max") or 12)))
    merged_proposals = []
    seen_keys = set()
    previous = [p for p in (existing.get("proposed") or []) if isinstance(p, dict)]
    for proposal in list(proposals) + previous:
        key = str(proposal.get("url") or proposal.get("id") or "")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        merged_proposals.append(proposal)
    merged_proposals.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            int(item.get("proposed_at") or 0),
        ),
        reverse=True,
    )
    proposals = merged_proposals[:max_total]
    stats["proposed"] = len(proposals)
    stats["finished_at"] = _now_iso()

    merged = {
        "proposed": proposals,
        "seen": existing.get("seen", [])[-MAX_SEEN:],
        "generated_at": _now_iso(),
        "stats": stats,
        "source": "activity_service",
    }
    try:
        save_proposals(merged, root)
    except Exception as exc:
        LOG.error("Nao foi possivel guardar propostas: %s", exc)

    try:
        with _file_lock(root):
            activity = load_activity(root)
            activity["rss"]["last_check"] = _now_iso()
            activity["rss"]["last_error"] = "; ".join(stats["errors"])[:500] or None
            _save_activity(activity, root)
    except Exception as exc:
        LOG.warning("Nao foi possivel atualizar o estado RSS: %s", exc)

    _LAST_STATS = dict(stats)
    if heartbeat:
        _write_heartbeat(root, extra={"last_stats": stats})
    LOG.info(
        "RSS: %s feeds, %s itens, %s propostas%s",
        stats["feeds"], stats["items"], stats["proposed"],
        f" ({len(stats['errors'])} erros)" if stats["errors"] else "",
    )
    return merged


# =====================================================================
# Estado / ciclo de vida do servico
# =====================================================================
_LAST_STATS = {}


def _write_heartbeat(app_dir=None, extra=None, role="service"):
    p = _ensure_dirs(app_dir)
    config = load_config(app_dir)
    payload = {
        "pid": os.getpid(),
        "role": role,
        "updated_at": _now_iso(),
        "interval_min": int(config.get("automation_interval") or 30),
        "enabled": bool(config.get("automation_enabled")),
    }
    if _LAST_STATS:
        payload["last_stats"] = _LAST_STATS
    if extra:
        payload.update(extra)
    try:
        _atomic_write(p["heartbeat"], json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass


def _pid_alive(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _lock_now(fh):
    fh.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh):
    try:
        fh.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def is_running(app_dir=None):
    if _SERVICE_LOCK_HANDLE is not None:
        return True
    p = paths(app_dir)
    try:
        fh = open(p["service_lock"], "a+b")
        try:
            if os.path.getsize(p["service_lock"]) == 0:
                fh.write(b"\0")
                fh.flush()
            if not _lock_now(fh):
                return True
            _unlock(fh)
        finally:
            fh.close()
        return _legacy_is_running(app_dir)
    except OSError:
        try:
            with open(p["heartbeat"], "r", encoding="utf-8-sig") as fh:
                hb = json.load(fh)
            if hb.get("role") == "service" and _pid_alive(hb.get("pid")):
                return True
        except Exception:
            pass
        try:
            with open(p["service_lock"], "r", encoding="utf-8-sig") as fh:
                lock = json.load(fh)
            return _pid_alive(lock.get("pid"))
        except Exception:
            return False


def _acquire_instance(app_dir=None):
    global _SERVICE_LOCK_HANDLE
    if _SERVICE_LOCK_HANDLE is not None:
        return True
    p = _ensure_dirs(app_dir)
    try:
        fh = open(p["service_lock"], "a+b")
        if os.path.getsize(p["service_lock"]) == 0:
            fh.write(b"\0")
            fh.flush()
        if not _lock_now(fh):
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(
            {"pid": os.getpid(), "started_at": _now_iso()}
        ).encode("utf-8"))
        fh.flush()
        _SERVICE_LOCK_HANDLE = fh
        return True
    except Exception:
        try:
            _unlock(fh)
            fh.close()
        except Exception:
            pass
        return False


def _release_instance(app_dir=None):
    global _SERVICE_LOCK_HANDLE
    fh = _SERVICE_LOCK_HANDLE
    _SERVICE_LOCK_HANDLE = None
    if fh is None:
        return
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(b"{}")
        fh.flush()
        _unlock(fh)
    finally:
        fh.close()


def _legacy_is_running(app_dir=None):
    """Compatibility fallback for older service processes without file locks."""
    p = paths(app_dir)
    try:
        with open(p["heartbeat"], "r", encoding="utf-8-sig") as fh:
            hb = json.load(fh)
        if hb.get("role") == "service" and _pid_alive(hb.get("pid")):
            return True
    except Exception:
        pass
    try:
        with open(p["service_lock"], "r", encoding="utf-8-sig") as fh:
            lock = json.load(fh)
        return _pid_alive(lock.get("pid"))
    except Exception:
        return False


def request_check(app_dir=None):
    """Pede ao servico (ou ao proximo ciclo) uma verificacao imediata."""
    p = _ensure_dirs(app_dir)
    try:
        _atomic_write(p["trigger"], _now_iso().encode("utf-8"))
        return True
    except Exception:
        return False


def stop_service(app_dir=None, timeout=5.0):
    p = paths(app_dir)
    try:
        _atomic_write(p["stop"], str(os.getpid()).encode("ascii"))
    except Exception:
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_running(app_dir):
            break
        time.sleep(0.2)
    if is_running(app_dir):
        try:
            with open(p["heartbeat"], "r", encoding="utf-8-sig") as fh:
                pid = int(json.load(fh).get("pid") or 0)
            if pid:
                os.kill(pid, 9)
        except Exception:
            pass
    for key in ("stop",):
        try:
            os.remove(p[key])
        except Exception:
            pass
    return not is_running(app_dir)


def _detached_flags():
    flags = 0
    if os.name == "nt":
        flags |= 0x00000008  # DETACHED_PROCESS
        flags |= 0x00000200  # CREATE_NEW_PROCESS_GROUP
        flags |= 0x08000000  # CREATE_NO_WINDOW
    return flags


def start_service(app_dir=None, force=False):
    """Lanca o servico fora da arvore de processos da aplicacao, se possivel."""
    root = _app_dir(app_dir)
    if not force and is_running(root):
        return True
    p = paths(root)
    if not os.path.isfile(p["script"]):
        LOG.warning("activity_service.py nao encontrado")
        return False
    python = p["python"] if os.path.isfile(p["python"]) else sys.executable
    cmd = [python, p["script"], "--service", root]
    try:
        if os.path.exists(p["stop"]):
            os.remove(p["stop"])
    except Exception:
        pass
    # 1) Tentativa normal, com breakaway do Job Object do launcher.
    try:
        subprocess.Popen(
            cmd,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_detached_flags() | 0x01000000,  # CREATE_BREAKAWAY_FROM_JOB
            close_fds=True,
        )
        return True
    except Exception:
        pass
    # 2) O Job Object do launcher pode proibir breakaway. O WMI cria o processo
    #    fora do job (o pai e o WmiPrvSE), mantendo o utilizador atual.
    if os.name == "nt":
        try:
            command = subprocess.list2cmdline(cmd)
            ps = (
                "$ErrorActionPreference='Stop';"
                "$r=Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
                f"-Arguments @{{CommandLine={_ps_quote(command)}}};"
                "if($r.ReturnValue -ne 0){exit 1}"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                creationflags=_detached_flags(),
            )
            return True
        except Exception as exc:
            LOG.warning("WMI falhou ao lancar o servico: %s", exc)
    # 3) Ultimo recurso: processo filho normal.
    try:
        subprocess.Popen(
            cmd, cwd=root,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_detached_flags(), close_fds=True,
        )
        return True
    except Exception as exc:
        LOG.error("Nao foi possivel lancar o servico: %s", exc)
        return False


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def install_autostart(app_dir=None):
    if os.name != "nt":
        return False
    root = _app_dir(app_dir)
    p = paths(root)
    python = p["python"] if os.path.isfile(p["python"]) else sys.executable
    command = f'"{python}" "{p["script"]}" --service "{root}"'
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "MediaDeskActivityService", 0, winreg.REG_SZ, command)
        return True
    except Exception as exc:
        LOG.warning("Nao foi possivel instalar o arranque automatico: %s", exc)
        return False


def remove_autostart():
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "MediaDeskActivityService")
        return True
    except FileNotFoundError:
        return True
    except Exception:
        return False


def autostart_installed():
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, "MediaDeskActivityService")
        return True
    except Exception:
        return False


def service_status(app_dir=None):
    root = _app_dir(app_dir)
    config = load_config(root)
    hb = {}
    try:
        with open(paths(root)["heartbeat"], "r", encoding="utf-8-sig") as fh:
            hb = json.load(fh)
    except Exception:
        pass
    running = is_running(root)
    if not running or hb.get("role") != "service":
        hb = {}
    proposals = load_proposals(root)
    return {
        "enabled": bool(config.get("automation_enabled")),
        "running": running,
        "pid": hb.get("pid"),
        "updated_at": hb.get("updated_at"),
        "last_check": (hb.get("last_stats") or {}).get("finished_at") or load_activity(root)["rss"].get("last_check"),
        "next_check": hb.get("next_check"),
        "autostart": autostart_installed(),
        "proposals": len(proposals.get("proposed") or []),
        "errors": (hb.get("last_stats") or {}).get("errors") or [],
        "channels": len(load_channels(root)),
    }


# =====================================================================
# Log
# =====================================================================
def setup_logging(app_dir=None):
    p = _ensure_dirs(app_dir)
    if LOG.handlers:
        return
    LOG.setLevel(logging.INFO)
    handler = RotatingFileHandler(p["log"], maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    if sys.stderr is not None:
        LOG.addHandler(logging.StreamHandler())


# =====================================================================
# Ciclo principal
# =====================================================================
def run_service(app_dir=None):
    root = _app_dir(app_dir)
    setup_logging(root)
    if not _acquire_instance(root):
        LOG.info("Ja existe uma instancia do servico; a sair.")
        return 0
    stop_event = threading.Event()

    def _handle(signum, frame):
        stop_event.set()

    try:
        import signal
        signal.signal(signal.SIGINT, _handle)
        signal.signal(signal.SIGTERM, _handle)
    except Exception:
        pass

    LOG.info("Servico de atividade iniciado (pid %s, %s)", os.getpid(), root)
    next_check = 0.0
    try:
        while not stop_event.is_set():
            p = _ensure_dirs(root)
            if os.path.exists(p["stop"]):
                LOG.info("Pedido de paragem recebido.")
                break
            config = load_config(root)
            if not config.get("automation_enabled", False):
                LOG.info("Automatismo desativado; a encerrar o servico.")
                break
            now = time.time()
            trigger = os.path.exists(p["trigger"])
            if trigger or now >= next_check:
                try:
                    check_feeds(root, force=True, heartbeat=True)
                except Exception:
                    LOG.exception("Falha na verificacao de feeds")
                try:
                    if os.path.exists(p["trigger"]):
                        os.remove(p["trigger"])
                except Exception:
                    pass
                interval = max(5, int(config.get("automation_interval") or 30)) * 60
                next_check = time.time() + interval
            hb_extra = {"next_check": datetime.fromtimestamp(next_check, timezone.utc).isoformat(timespec="seconds")}
            _write_heartbeat(root, hb_extra)
            for _ in range(10):
                if stop_event.is_set() or os.path.exists(p["stop"]):
                    break
                time.sleep(0.5)
    finally:
        _release_instance(root)
        for key in ("stop", "trigger"):
            try:
                os.remove(paths(root)[key])
            except Exception:
                pass
        LOG.info("Servico de atividade terminado.")
    return 0


_FLAGS_WITH_VALUE = {"--root"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    rest = []
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg in _FLAGS_WITH_VALUE and idx + 1 < len(argv):
            root = argv[idx + 1]
            idx += 2
            continue
        if arg == "--service" and idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            # Forma usada pelo launcher: activity_service.py --service <raiz>
            root = argv[idx + 1]
            rest.append(arg)
            idx += 2
            continue
        if not arg.startswith("-") and root is None:
            root = arg
        else:
            rest.append(arg)
        idx += 1
    argv = rest
    setup_logging(root)
    if "--service" in argv:
        return run_service(root)
    if "--once" in argv:
        check_feeds(root, force=True)
        return 0
    if "--status" in argv:
        print(json.dumps(service_status(root), ensure_ascii=False, indent=2))
        return 0
    if "--install-autostart" in argv:
        print("autostart:", install_autostart(root))
        return 0
    if "--remove-autostart" in argv:
        print("autostart removido:", remove_autostart())
        return 0
    if "--record" in argv:
        payload = json.load(sys.stdin)
        print(json.dumps(record_download(payload, root), ensure_ascii=False))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
