from __future__ import annotations

import os
import re
from urllib.parse import quote

import requests
from flask import Flask, Response, jsonify, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# Render terminates TLS at its proxy. Without this, request.host_url is http://
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

VERSION = "0.3.0"
PORT = int(os.environ.get("PORT", "8080"))
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "BitChordCommunityAddon/0.3 (audio search prototype)"})

AUDIO_PRIORITY = {".flac": 0, ".wav": 1, ".aiff": 2, ".aif": 2, ".ogg": 3, ".opus": 4, ".m4a": 5, ".mp3": 6}
LOSSLESS = {".flac", ".wav", ".aiff", ".aif"}
MIME = {
    ".flac": "audio/flac", ".wav": "audio/wav", ".aiff": "audio/aiff", ".aif": "audio/aiff",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
}

PLAYER_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FLAC Player</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --line:#262a33; --text:#e8eaed; --mute:#9aa0a6; --accent:#7cc4ff; --ok:#6fd49a; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.4 system-ui,sans-serif; padding-bottom:150px; }
  header { padding:16px; position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); z-index:2; }
  h1 { font-size:17px; margin:0 0 10px; }
  form { display:flex; gap:8px; }
  input[type=search] { flex:1; padding:10px 12px; border-radius:10px; border:1px solid var(--line); background:var(--card); color:var(--text); font-size:16px; }
  button { padding:10px 14px; border-radius:10px; border:0; background:var(--accent); color:#06121c; font-weight:600; font-size:15px; }
  label.opt { display:block; margin-top:8px; color:var(--mute); font-size:13px; }
  main { padding:8px 16px; }
  .item { padding:12px 0; border-bottom:1px solid var(--line); cursor:pointer; }
  .item .t { font-weight:600; }
  .item .a { color:var(--mute); font-size:13px; }
  .tracks { margin:6px 0 0; padding:0; list-style:none; }
  .tracks li { padding:9px 10px; border-radius:8px; display:flex; justify-content:space-between; gap:8px; cursor:pointer; }
  .tracks li:active, .tracks li.now { background:var(--card); }
  .tracks li.now .n { color:var(--accent); }
  .badge { font-size:11px; padding:2px 7px; border-radius:20px; border:1px solid var(--line); color:var(--mute); white-space:nowrap; align-self:center; }
  .badge.lossless { color:var(--ok); border-color:var(--ok); }
  .msg { color:var(--mute); padding:16px 0; }
  footer { position:fixed; left:0; right:0; bottom:0; background:var(--card); border-top:1px solid var(--line); padding:10px 16px calc(10px + env(safe-area-inset-bottom)); }
  #np { font-size:13px; margin-bottom:6px; min-height:18px; }
  audio { width:100%; }
</style>
</head>
<body>
<header>
  <h1>FLAC Player <span style="color:var(--mute);font-weight:400">· Internet Archive</span></h1>
  <form id="f">
    <input type="search" id="q" placeholder="Search e.g. grateful dead" autocomplete="off" required>
    <button type="submit">Search</button>
  </form>
  <label class="opt"><input type="checkbox" id="flac" checked> FLAC only</label>
</header>
<main id="out"><div class="msg">Search for something. FLAC on Internet Archive is mostly live concert recordings and lossless uploads.</div></main>
<footer>
  <div id="np">Nothing playing</div>
  <audio id="au" controls preload="none"></audio>
</footer>
<script>
const out = document.getElementById('out');
const au = document.getElementById('au');
const np = document.getElementById('np');
let queue = [], idx = -1;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function msg(t) { out.replaceChildren(el('div', 'msg', t)); }

document.getElementById('f').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  msg('Searching…');
  const flac = document.getElementById('flac').checked ? '1' : '0';
  try {
    const r = await fetch('/search?limit=25&flac=' + flac + '&q=' + encodeURIComponent(q));
    const d = await r.json();
    if (!d.tracks || !d.tracks.length) { msg('No results. Try another search or untick FLAC only.'); return; }
    out.replaceChildren();
    d.tracks.forEach(t => {
      const box = el('div', 'item');
      box.appendChild(el('div', 't', t.title));
      box.appendChild(el('div', 'a', t.artist));
      const holder = el('ul', 'tracks');
      box.appendChild(holder);
      let loaded = false;
      box.addEventListener('click', async (e) => {
        if (e.target.closest('.tracks li')) return;
        if (loaded) { holder.hidden = !holder.hidden; return; }
        loaded = true;
        holder.appendChild(el('li', '', 'Loading…'));
        try {
          const rr = await fetch('/tracks?id=' + encodeURIComponent(t.id));
          const dd = await rr.json();
          holder.replaceChildren();
          if (!dd.tracks || !dd.tracks.length) { holder.appendChild(el('li', '', 'No playable files in this item.')); return; }
          dd.tracks.forEach((tr, i) => {
            const li = el('li');
            li.appendChild(el('span', 'n', tr.title));
            const b = el('span', 'badge' + (tr.audioQuality === 'LOSSLESS' ? ' lossless' : ''), tr.format);
            li.appendChild(b);
            li.addEventListener('click', () => play(dd.tracks, i, t));
            holder.appendChild(li);
          });
        } catch (err) { holder.replaceChildren(el('li', '', 'Could not load tracks.')); loaded = false; }
      });
      out.appendChild(box);
    });
  } catch (err) { msg('Search failed. If the server was asleep, wait a few seconds and try again.'); }
});

function play(list, i, album) {
  queue = list; idx = i;
  const tr = queue[idx];
  au.src = tr.streamUrl;
  au.play().catch(() => {});
  np.textContent = tr.format + ' · ' + tr.title + ' — ' + (tr.artist || album.artist);
  document.querySelectorAll('.tracks li').forEach(l => l.classList.remove('now'));
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({ title: tr.title, artist: tr.artist || album.artist, album: tr.album });
    navigator.mediaSession.setActionHandler('nexttrack', next);
  }
}
function next() { if (idx + 1 < queue.length) play(queue, idx + 1, {artist: ''}); }
au.addEventListener('ended', next);
au.addEventListener('error', () => { np.textContent = 'Playback error for this file. Try another track.'; });
</script>
</body>
</html>
"""


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


def audio_ext(name: str) -> str:
    match = re.search(r"\.[A-Za-z0-9]{2,5}$", name or "")
    return match.group(0).lower() if match else ""


def audio_files(files: list[dict]) -> list[dict]:
    out = []
    for item in files:
        name = item.get("name", "")
        if audio_ext(name) in AUDIO_PRIORITY and not name.startswith("__MACOSX/"):
            out.append(item)
    out.sort(key=lambda f: (AUDIO_PRIORITY[audio_ext(f["name"])], f["name"].lower()))
    return out


def public_file_url(identifier: str, filename: str) -> str:
    safe_path = "/".join(quote(part, safe="") for part in filename.split("/"))
    return f"https://archive.org/download/{quote(identifier, safe='')}/{safe_path}"


def track_dict(identifier: str, f: dict, album: str, artist: str) -> dict:
    ext = audio_ext(f["name"])
    return {
        "id": f"{identifier}|{f['name']}",
        "title": f.get("title") or os.path.splitext(os.path.basename(f["name"]))[0],
        "artist": f.get("creator") or artist,
        "album": album,
        "format": ext.lstrip(".").upper(),
        "audioQuality": "LOSSLESS" if ext in LOSSLESS else "LOSSY",
        "size": f.get("size"),
        "streamUrl": public_file_url(identifier, f["name"]),
        "source": "Internet Archive",
    }


def get_metadata(identifier: str) -> dict:
    r = SESSION.get(IA_METADATA + quote(identifier, safe=""), timeout=20)
    r.raise_for_status()
    return r.json()


@app.get("/")
def index():
    return Response(PLAYER_HTML, mimetype="text/html")


@app.get("/api")
def api_info():
    return jsonify({"name": "BitChord Community Audio", "version": VERSION,
                    "manifest": "/manifest.json", "health": "/health"})


@app.get("/health")
def health():
    return jsonify({"status": "ok", "version": VERSION})


@app.get("/manifest.json")
def manifest():
    # Generic manifest. Adapt to the exact schema an addon-capable client expects.
    base = request.host_url.rstrip("/")
    return jsonify({
        "id": "community.archive.audio",
        "name": "Community Audio Archive",
        "version": VERSION,
        "description": "Search public-domain or appropriately licensed audio hosted by Internet Archive.",
        "baseUrl": base,
        "endpoints": {
            "search": "/search?q={query}&limit={limit}",
            "tracks": "/tracks?id={id}",
            "stream": "/stream?id={id}",
        },
    })


@app.get("/search")
def search():
    query = (request.args.get("q") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), 50))
    except ValueError:
        limit = 20
    if not query:
        return jsonify({"tracks": [], "total": 0})

    # Only items that contain a FLAC file by default. Use flac=0 to disable.
    flac_only = request.args.get("flac", "1") != "0"
    q = f"({query}) AND mediatype:audio"
    if flac_only:
        q += " AND format:Flac"

    params = [
        ("q", q),
        ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "creator"),
        ("fl[]", "date"), ("rows", str(limit)), ("page", "1"),
        ("output", "json"), ("sort[]", "downloads desc"),
    ]
    try:
        response = SESSION.get(IA_SEARCH, params=params, timeout=15)
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
    except (requests.RequestException, ValueError):
        return jsonify({"error": "Internet Archive search is temporarily unavailable", "tracks": [], "total": 0}), 502

    tracks = []
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        creator = doc.get("creator") or "Unknown artist"
        if isinstance(creator, list):
            creator = ", ".join(str(x) for x in creator[:3])
        title = doc.get("title") or identifier
        tracks.append({
            "id": identifier, "title": str(title), "artist": str(creator),
            "album": str(title), "audioQuality": "LOSSLESS" if flac_only else "UNKNOWN",
            "format": "FLAC" if flac_only else "Resolve using the stream endpoint",
            "source": "Internet Archive",
        })
    return jsonify({"tracks": tracks, "total": len(tracks)})


@app.get("/tracks")
def tracks():
    """Track-level listing for one item (an item is usually a whole album)."""
    identifier = (request.args.get("id") or "").split("|")[0].strip()
    if not identifier or not re.fullmatch(r"[A-Za-z0-9._-]+", identifier):
        return jsonify({"error": "A valid Internet Archive identifier is required"}), 400
    try:
        meta = get_metadata(identifier)
    except (requests.RequestException, ValueError):
        return jsonify({"error": "Could not retrieve item metadata"}), 502

    info = meta.get("metadata", {})
    album = str(info.get("title") or identifier)
    artist = info.get("creator") or "Unknown artist"
    if isinstance(artist, list):
        artist = ", ".join(str(x) for x in artist[:3])

    files = audio_files(meta.get("files", []))
    # Keep only the best format present, so a FLAC album doesn't list MP3 duplicates.
    if files:
        best = audio_ext(files[0]["name"])
        files = [f for f in files if audio_ext(f["name"]) == best]
        files.sort(key=lambda f: f["name"].lower())
    out = [track_dict(identifier, f, album, str(artist)) for f in files]
    return jsonify({"tracks": out, "total": len(out)})


@app.get("/stream")
def stream():
    """
    /stream?id=<item>                 best audio file in the item
    /stream?id=<item>|<file>          that specific file (ids from /tracks)
    Add &redirect=1 to get a 302 straight to the audio file instead of JSON.
    """
    raw_id = (request.args.get("id") or "").strip()
    identifier, _, filename = raw_id.partition("|")
    filename = request.args.get("file") or filename
    if not identifier or not re.fullmatch(r"[A-Za-z0-9._-]+", identifier):
        return jsonify({"error": "A valid Internet Archive identifier is required"}), 400
    try:
        meta = get_metadata(identifier)
    except (requests.RequestException, ValueError):
        return jsonify({"error": "Could not retrieve item metadata"}), 502

    files = audio_files(meta.get("files", []))
    selected = None
    if filename:
        selected = next((f for f in files if f["name"] == filename), None)
    elif files:
        selected = files[0]
    if not selected:
        return jsonify({"error": "No supported audio file found for this item"}), 404

    name = selected["name"]
    ext = audio_ext(name)
    url = public_file_url(identifier, name)
    if request.args.get("redirect") == "1":
        return redirect(url, code=302)
    return jsonify({
        "id": raw_id, "url": url, "mimeType": MIME.get(ext, "audio/" + ext.lstrip(".")),
        "format": ext.lstrip(".").upper(), "size": selected.get("size"),
        "audioQuality": "LOSSLESS" if ext in LOSSLESS else "LOSSY",
        "license": "Check the Internet Archive item page before use",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
