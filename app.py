# app.py
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import soco
from soco import SoCo
import requests
from urllib.parse import urlparse, quote_plus, unquote
import os, json, time
import re
import subprocess
import shutil


app = Flask(__name__)

# ---- Configuration ----
APP_DIR = os.path.dirname(os.path.abspath(__file__))
FAVORITES_FILE = os.path.join(APP_DIR, "favorites.json")
RADIO_BROWSER_BASE = "https://de1.api.radio-browser.info/json"
API_SERVERS = [
    "de1.api.radio-browser.info",
    "de2.api.radio-browser.info",
    "fi1.api.radio-browser.info"
]


# Sonos-accepted mime-ish types (we'll be somewhat permissive)
ACCEPTED_MIME = {
    "audio/mpeg", "audio/mp3", "audio/x-mpeg",
    "audio/aac", "audio/aacp", "audio/mp4", "audio/ogg", "audio/vorbis"
}

# common playlist file extensions
PLAYLIST_EXTS = (".m3u", ".m3u8", ".pls", ".asx", ".xspf")

# Ensure favorites file exists
if not os.path.exists(FAVORITES_FILE):
    with open(FAVORITES_FILE, "w") as f:
        json.dump([], f)


# ---- Helpers: Sonos discovery / SoCo wrapper ----
def discover_speakers():
    try:
        found = list(soco.discover() or [])
        return found
    except Exception:
        return []


def list_speaker_ips():
    return [s.ip_address for s in discover_speakers()]


def get_soco(ip):
    try:
        return SoCo(ip)
    except Exception:
        return None


def load_favorites():
    try:
        with open(FAVORITES_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_favorites(data):
    with open(FAVORITES_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---- Playlist resolution helpers ----
def fetch_text(uri, timeout=6, headers=None):
    headers = headers or {"User-Agent": "Linux UPnP/1.0 Sonos/99.9 (Probe)"}
    r = requests.get(uri, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.url, r.headers


def parse_m3u(text):
    # m3u/m3u8: lines starting with # are comments, others are URIs
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return lines


def parse_pls(text):
    # .pls is INI-like with File1=..., File2=...
    lines = text.splitlines()
    uris = []
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            if k.strip().lower().startswith("file"):
                uris.append(v.strip())
    return uris


def parse_xspf(text):
    # crude XML parsing for <location>...</location>
    matches = re.findall(r"<location>(.*?)</location>", text, flags=re.IGNORECASE | re.DOTALL)
    return [m.strip() for m in matches]


def resolve_playlist(uri, timeout=6):
    """
    If URI points to a playlist file or a resource that contains playlist text,
    attempt to resolve to a direct stream URL. Returns list of candidate URLs (may be empty).
    """
    try:
        headers = {"User-Agent": "Linux UPnP/1.0 Sonos/99.9 (PlaylistResolver)"}
        text, final_url, resp_headers = fetch_text(uri, timeout=timeout, headers=headers)
        final_lower = final_url.lower()
        candidates = []

        # If URL ends with a known playlist ext, parse accordingly
        if any(final_lower.endswith(ext) for ext in (".m3u", ".m3u8")):
            candidates = parse_m3u(text)
        elif final_lower.endswith(".pls"):
            candidates = parse_pls(text)
        elif final_lower.endswith(".xspf"):
            candidates = parse_xspf(text)
        elif final_lower.endswith(".asx") or "<asx" in text.lower():
            # asx is XML-like; look for <ref href="..."/>
            matches = re.findall(r'href=["\'](.*?)["\']', text, flags=re.IGNORECASE)
            candidates = matches
        else:
            # Not explicit playlist extension — try to parse heuristically:
            # if content contains http:// or https:// entries or location tags
            candidates = parse_m3u(text) or parse_pls(text) or parse_xspf(text)
            if not candidates:
                # look for obvious urls
                candidates = re.findall(r'(https?://[^\s\'">]+)', text)
        # normalize relative URLs if any (rare)
        resolved = []
        for c in candidates:
            c = c.strip()
            if not c:
                continue
            if c.startswith("http://") or c.startswith("https://"):
                resolved.append(c)
            else:
                # make absolute relative to final_url
                base = final_url.rsplit("/", 1)[0]
                resolved.append(base + "/" + c.lstrip("/"))
        return resolved
    except Exception:
        return []


# ---- Stream probing (Sonos-like) ----
def probe_url(uri, timeout=6, chunk_test=True):
    """
    Returns a dict:
      {
        http_status, content_type, final_url,
        playable (bool): whether Sonos should be able to play directly,
        needs_relay (bool): whether we should relay to sonos,
        reason: human string,
      }
    """
    result = {
        "http_status": None,
        "content_type": None,
        "final_url": uri,
        "playable": False,
        "needs_relay": False,
        "reason": None,
    }
    if not uri:
        result["reason"] = "empty uri"
        return result

    # Use Sonos-like UA to mimic Sonos server behavior
    headers = {"User-Agent": "Linux UPnP/1.0 Sonos/99.9 (Probe)"}
    try:
        # follow redirects to final
        r = requests.get(uri, headers=headers, stream=True, timeout=timeout, allow_redirects=True)
        result["http_status"] = r.status_code
        final_url = r.url
        result["final_url"] = final_url
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        result["content_type"] = ctype

        # If final url looks like a playlist or HTML page -> needs relay (resolve playlist first)
        if any(final_url.lower().endswith(ext) for ext in PLAYLIST_EXTS) or ("text/html" in ctype) or ("application/xhtml+xml" in ctype):
            result["reason"] = "redirects to playlist or HTML"
            result["needs_relay"] = True
            # attempt to resolve playlist to direct stream URL(s)
            candidates = resolve_playlist(final_url)
            if candidates:
                # test first candidate for audio content-type
                for cand in candidates:
                    try:
                        cr = requests.head(cand, headers=headers, timeout=4, allow_redirects=True)
                        cctype = (cr.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                        if cctype in ACCEPTED_MIME or "audio" in cctype:
                            result["playable"] = True
                            result["needs_relay"] = False
                            result["final_url"] = cr.url
                            return result
                    except Exception:
                        continue
            return result

        # If content-type is clearly audio, accept
        if ctype and ("audio" in ctype or ctype in ACCEPTED_MIME):
            # optionally read a small chunk to ensure binary audio, not text disguised
            if chunk_test:
                try:
                    chunk = next(r.iter_content(2048), b"")
                    if not chunk:
                        result["reason"] = "no data"
                        result["needs_relay"] = True
                        return result
                    # detect if chunk looks like text (too many printable ASCII)
                    text_ratio = sum(32 <= b <= 126 for b in chunk) / max(len(chunk), 1)
                    if text_ratio > 0.9 and not ctype.startswith("audio/"):
                        result["reason"] = "first chunk looks like text"
                        result["needs_relay"] = True
                        return result
                except Exception:
                    result["needs_relay"] = True
                    result["reason"] = "chunk read failed"
                    return result

            result["playable"] = True
            return result

        # If content-type is missing or weird, try HEAD of final URL
        if not ctype:
            try:
                hr = requests.head(final_url, headers=headers, timeout=4, allow_redirects=True)
                hctype = (hr.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                result["content_type"] = hctype
                if hctype and ("audio" in hctype or hctype in ACCEPTED_MIME):
                    result["playable"] = True
                    return result
            except Exception:
                pass

        # default: treat as needing relay (playlist/HTML/unrecognized)
        result["needs_relay"] = True
        result["reason"] = f"unsupported MIME: {ctype}"
        return result

    except Exception as e:
        result["needs_relay"] = True
        result["reason"] = f"probe error: {e}"
        return result

# ---- Relay endpoint for Sonos ----
# ---- FFmpeg Stream Helper ----
def ffmpeg_stream(url, bitrate="128k", samplerate=44100):
    """
    Launch FFmpeg to decode any external stream and output MP3 44.1kHz for Sonos.
    Returns a file-like stdout stream.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg not found in PATH. Install FFmpeg before using the relay.")

    cmd = [
        ffmpeg_path,
        "-i", url,
        "-f", "mp3",
        "-ar", str(samplerate),
        "-b:a", bitrate,
        "pipe:1"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return proc.stdout

# ---- Relay endpoint for Sonos ----
@app.route("/relay")
def relay_stream():
    target = request.args.get("url")
    if not target:
        return "No URL provided", 400

    target = unquote(target)

    # Resolve playlists
    if any(target.lower().endswith(ext) for ext in PLAYLIST_EXTS):
        candidates = resolve_playlist(target)
        if candidates:
            target = candidates[0]

    try:
        def generate():
            stream = ffmpeg_stream(target)
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                yield chunk
            stream.close()

        return Response(stream_with_context(generate()), mimetype="audio/mpeg")

    except Exception as e:
        app.logger.exception("relay failed")
        return f"Relay failed: {e}", 500



# ---- Current track info ----
def get_current_track_info(ip):
    try:
        s = get_soco(ip)
        if not s:
            return {"status": "error", "message": "speaker not found"}
        # update transport info
        try:
            s.get_current_transport_info()
        except Exception:
            pass
        track = s.get_current_track_info()
        return {
            "status": "ok",
            "title": track.get("title") or "",
            "artist": track.get("artist") or "",
            "album": track.get("album") or "",
            "album_art": track.get("album_art") or "",
            "mute": s.mute,
            "volume": s.volume
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---- Flask Routes ----
@app.route("/")
def index():
    return render_template("index.html", speakers=list_speaker_ips(), favorites=load_favorites())


@app.route("/speakers")
def speakers_list():
    return jsonify({"speakers": list_speaker_ips()})


@app.route("/track_info")
def track_info():
    ip = request.args.get("ip")
    if not ip:
        return jsonify({"status": "error", "message": "no ip"}), 400
    return jsonify(get_current_track_info(ip))


# ---- Playback & Control ----
@app.route("/play", methods=["POST"])
def play():
    return _simple_control("play")


@app.route("/pause", methods=["POST"])
def pause():
    return _simple_control("pause")


@app.route("/stop", methods=["POST"])
def stop():
    return _simple_control("stop")


@app.route("/next", methods=["POST"])
def next_track():
    return _simple_control("next")


@app.route("/previous", methods=["POST"])
def previous_track():
    return _simple_control("previous")


def _simple_control(action):
    ip = request.json.get("ip")
    s = get_soco(ip)
    if not s:
        return jsonify({"status": "error", "message": "speaker not found"}), 404
    try:
        getattr(s, action)()
        app.logger.info(f"{action} sent to {ip}")
        return jsonify({"status": "ok"})
    except Exception as e:
        app.logger.exception(f"{action} failed")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---- Volume / Mute ----
@app.route("/volume", methods=["POST"])
def set_volume():
    ip, level = request.json.get("ip"), request.json.get("level", 20)
    s = get_soco(ip)
    if not s:
        return jsonify({"status": "error", "message": "speaker not found"}), 404
    try:
        s.volume = int(level)
        return jsonify({"status": "ok"})
    except Exception as e:
        app.logger.exception("volume failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/mute", methods=["POST"])
def mute():
    return _mute_control(True)


@app.route("/unmute", methods=["POST"])
def unmute():
    return _mute_control(False)


def _mute_control(state):
    ip = request.json.get("ip")
    s = get_soco(ip)
    if not s:
        return jsonify({"status": "error", "message": "speaker not found"}), 404
    try:
        s.mute = state
        return jsonify({"status": "ok"})
    except Exception as e:
        app.logger.exception("mute failed")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---- Play URI (decide relay OR direct) ----
@app.route("/play_uri", methods=["POST"])
def play_uri():
    ip, uri = request.json.get("ip"), request.json.get("uri")
    s = get_soco(ip)
    if not s:
        return jsonify({"status": "error", "message": "speaker not found"}), 404
    if not uri:
        return jsonify({"status": "error", "message": "no uri"}), 400

    # Build fully qualified URL for the relay endpoint
    # Use LAN IP, not localhost
    host_ip = request.host.split(":")[0]  # e.g., 192.168.1.180
    host_port = request.host.split(":")[1] if ":" in request.host else "5000"
    host_url = f"http://{host_ip}:{host_port}"
    play_target = f"{host_url}/relay?url={quote_plus(uri)}"

    try:
        s.stop()

        # Provide minimal metadata to prevent UPnP 714
        metadata = f"""<?xml version="1.0"?>
        <DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"
                   xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">
          <item id="0" parentID="-1" restricted="true">
            <dc:title>Radio Stream</dc:title>
            <upnp:class>object.item.audioItem.audioBroadcast</upnp:class>
            <res protocolInfo="http-get:*:audio/mpeg:*">{play_target}</res>
          </item>
        </DIDL-Lite>"""

        s.avTransport.SetAVTransportURI([
            ("InstanceID", 0),
            ("CurrentURI", play_target),
            ("CurrentURIMetaData", metadata)
        ])
        s.play()

        app.logger.info(f"play_uri {play_target} on {ip}")
        return jsonify({"status": "ok", "uri": play_target})

    except Exception as e:
        app.logger.exception("play_uri failed")
        return jsonify({"status": "error", "message": str(e)}), 500





# ---- Stream probe endpoint ----
@app.route("/streams/probe", methods=["POST"])
def streams_probe():
    uri = (request.json or {}).get("uri")
    if not uri:
        return jsonify({"status": "error", "message": "no uri"}), 400
    return jsonify(probe_url(uri))


# ---- Radio Browser search wrapper ----
@app.route("/search_stations")
def search_stations():
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", 20))
    params = {"limit": limit}
    try:
        if q:
            url = f"{RADIO_BROWSER_BASE}/stations/search"
            params["name"] = q
        else:
            url = f"{RADIO_BROWSER_BASE}/stations/topclick/10"

        stations = fetch_stations(q, limit)
        cleaned = [
            {
                "name": s.get("name"),
                "uri": s.get("url_resolved") or s.get("url"),
                "favicon": s.get("favicon"),
                "tags": s.get("tags"),
                "country": s.get("country"),
                "bitrate": s.get("bitrate"),
            }
            for s in stations
        ]
        return jsonify({"status": "ok", "results": cleaned})
    except Exception as e:
        app.logger.exception("radio browser failed")
        return jsonify({"status": "error", "message": str(e)}), 500


def fetch_stations(q, limit):
    # Try each server until one works
    for server in API_SERVERS:
        try:
            if q:
                url = f"https://{server}/json/stations/search"
                params = {"limit": limit, "name": q}
            else:
                url = f"https://{server}/json/stations/topclick/10"
                params = {"limit": limit}

            r = requests.get(url, params=params, timeout=8)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            app.logger.warning(f"Station search failed on {server}: {e}")
    # All servers failed
    raise RuntimeError("All radio-browser servers failed")


# ---- Favorites ----
@app.route("/favorites", methods=["GET"])
def get_favorites():
    return jsonify({"favorites": load_favorites()})


@app.route("/favorites", methods=["POST"])
def add_favorite():
    data = request.json or {}
    name, uri = data.get("name", "Untitled"), data.get("uri", "")
    favs = load_favorites()
    favs.insert(0, {"name": name, "uri": uri, "added": int(time.time())})
    save_favorites(favs)
    return jsonify({"status": "ok", "favorites": favs})


@app.route("/favorites", methods=["DELETE"])
def delete_favorite():
    data = request.json or {}
    uri = data.get("uri")
    favs = [f for f in load_favorites() if f.get("uri") != uri]
    save_favorites(favs)
    return jsonify({"status": "ok", "favorites": favs})


# ---- Run server ----
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
