"""Music control — Apple Music (AppleScript) and Spotify (spogo CLI)."""

import json as _json
import shutil
import subprocess

HAS_SPOGO = shutil.which("spogo") is not None

_INSTALL_SPOGO_MSG = (
    "For full Spotify search & play-by-name support, install the spogo CLI: "
    "brew install steipete/tap/spogo && spogo auth import --browser chrome"
)
_AUTH_SPOGO_MSG = (
    "Spotify search requires spogo authentication. "
    "Run: spogo auth import --browser chrome  (Requires Spotify Premium "
    "and being logged in at open.spotify.com in Chrome.)"
)


def _spogo_auth_ok() -> bool:
    """Check if spogo has a valid sp_dc session cookie."""
    if not HAS_SPOGO:
        return False
    try:
        r = subprocess.run(
            ["spogo", "auth", "status"],
            capture_output=True, text=True, timeout=5,
        )
        return "missing sp_dc" not in r.stdout
    except Exception:
        return False


SPOGO_AUTHED = HAS_SPOGO and _spogo_auth_ok()

DEFINITION = {
    "type": "function",
    "function": {
        "name": "music_control",
        "description": (
            "Control music playback on Apple Music or Spotify. "
            "ONLY use when the user explicitly asks to play, pause, skip, "
            "search, or browse music. Do NOT call for greetings or general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "play", "pause", "next", "previous",
                        "current_track", "play_song", "play_artist", "play_album",
                        "artist_info", "album_info", "search",
                        "list_artists", "list_albums",
                    ],
                    "description": (
                        "play: resume playback. pause: pause playback. "
                        "next/previous: skip tracks. current_track: what's playing now. "
                        "play_song: play a specific song (set query to song name, optionally set artist). "
                        "play_artist: shuffle all songs by an artist (set query to artist name). "
                        "play_album: play an album (set query to album name). "
                        "artist_info: list albums and songs by an artist. "
                        "album_info: list tracks on an album. "
                        "search: search the library for anything. "
                        "list_artists: list all artists in the library. "
                        "list_albums: list all albums in the library."
                    ),
                },
                "app": {
                    "type": "string",
                    "enum": ["spotify", "apple_music"],
                    "description": "Which music app to use. Default: apple_music",
                },
                "query": {
                    "type": "string",
                    "description": "Song name, artist name, album name, or search query",
                },
                "artist": {
                    "type": "string",
                    "description": "Artist name — use with play_song to find a specific song by a specific artist (e.g. query='Volcano', artist='U2')",
                },
            },
            "required": ["action"],
        },
    },
}


# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------
def _applescript(script: str, timeout: int = 15) -> str:
    """Run an AppleScript via osascript and return output."""
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        return f"Error: {r.stderr.strip()}"
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# spogo helpers (Spotify — requires authenticated sp_dc cookie)
# ---------------------------------------------------------------------------
def _spogo(args: list, timeout: int = 15) -> str:
    """Run a spogo CLI command and return output."""
    try:
        r = subprocess.run(
            ["spogo"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return f"Error: {r.stderr.strip()}"
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: spogo command timed out"
    except Exception as e:
        return f"Error: spogo failed — {e}"


def _spogo_json(args: list, timeout: int = 15):
    """Run a spogo command with --json and parse the output.
    Returns (parsed_data, None) on success, or (None, error_string) on failure."""
    out = _spogo(args + ["--json"], timeout=timeout)
    if out.startswith("Error"):
        return None, out
    try:
        return _json.loads(out), None
    except (_json.JSONDecodeError, ValueError):
        return None, f"Error: unexpected output from spogo"


# ---------------------------------------------------------------------------
# Spotify via AppleScript (no spogo needed — basic playback + URI scheme)
# ---------------------------------------------------------------------------
def _spotify_applescript(script: str, timeout: int = 15) -> str:
    """Run an AppleScript targeting the Spotify app."""
    return _applescript(script, timeout)


def _spotify_open_uri(uri: str) -> str:
    """Open a Spotify URI via the app (triggers playback)."""
    return _applescript(f'tell application "Spotify" to open location "{uri}"')


def _spotify_execute(action: str, query: str, artist: str) -> str:
    """Handle Spotify actions. Uses AppleScript for basic playback,
    spogo (if authenticated) for search/play-by-name, and falls back
    to Spotify URI scheme when spogo is unavailable."""

    # --- Basic playback: always via AppleScript (no auth needed) ---
    if action == "play":
        result = _spotify_applescript('tell application "Spotify" to play')
        if result.startswith("Error"):
            return f"Could not resume Spotify playback. Is Spotify open? ({result})"
        return "Resumed playback on Spotify."

    elif action == "pause":
        result = _spotify_applescript('tell application "Spotify" to pause')
        if result.startswith("Error"):
            return f"Could not pause Spotify. Is Spotify open? ({result})"
        return "Paused Spotify."

    elif action == "next":
        result = _spotify_applescript('tell application "Spotify" to next track')
        if result.startswith("Error"):
            return f"Could not skip track. Is Spotify open? ({result})"
        return "Skipped to next track on Spotify."

    elif action == "previous":
        result = _spotify_applescript('tell application "Spotify" to previous track')
        if result.startswith("Error"):
            return f"Could not go to previous track. Is Spotify open? ({result})"
        return "Went to previous track on Spotify."

    elif action == "current_track":
        info = _spotify_applescript(
            'tell application "Spotify"\n'
            '  if player state is playing then\n'
            '    return (name of current track) & " by " & (artist of current track) & " (" & (album of current track) & ")"\n'
            '  else\n'
            '    return "NOT_PLAYING"\n'
            '  end if\n'
            'end tell'
        )
        if info.startswith("Error"):
            return "Could not check Spotify playback. Is Spotify open?"
        if "NOT_PLAYING" in info:
            return "No track is currently playing on Spotify."
        return f"Now playing on Spotify: {info}"

    # --- Search / play-by-name: use spogo for search, AppleScript for playback ---
    elif action == "play_song" and query:
        if SPOGO_AUTHED:
            search_query = f"{query} {artist}".strip() if artist else query
            data, err = _spogo_json(["search", "track", search_query, "--limit", "5"])
            if data:
                tracks = data.get("items", [])
                if tracks:
                    picked = tracks[0]
                    uri = picked.get("uri", "")
                    name = picked.get("name", query)
                    result = _spotify_applescript(f'tell application "Spotify" to play track "{uri}"')
                    if result.startswith("Error"):
                        return f"Found '{name}' but could not start playback. Is Spotify open? ({result})"
                    return f"Now playing on Spotify: {name}"
            # spogo search failed, fall through to URI scheme
        # Fallback: open Spotify search URI
        import urllib.parse
        search_query = f"{query} {artist}".strip() if artist else query
        encoded = urllib.parse.quote(search_query)
        _spotify_open_uri(f"spotify:search:{encoded}")
        if not SPOGO_AUTHED:
            hint = _INSTALL_SPOGO_MSG if not HAS_SPOGO else _AUTH_SPOGO_MSG
            return f"Opened Spotify search for '{search_query}'. (Tip: {hint})"
        return f"Opened Spotify search for '{search_query}'. Please select a track to play."

    elif action == "play_artist" and query:
        if SPOGO_AUTHED:
            data, err = _spogo_json(["search", "artist", query, "--limit", "1"])
            if data:
                artists = data.get("items", [])
                if artists:
                    uri = artists[0].get("uri", "")
                    name = artists[0].get("name", query)
                    result = _spotify_applescript(
                        f'tell application "Spotify"\n'
                        f'  set shuffling to true\n'
                        f'  play track "{uri}"\n'
                        f'end tell'
                    )
                    if result.startswith("Error"):
                        return f"Found '{name}' but could not start playback. Is Spotify open? ({result})"
                    return f"Playing {name} on Spotify (shuffled)."
        # Fallback: open artist search URI
        import urllib.parse
        encoded = urllib.parse.quote(query)
        _spotify_open_uri(f"spotify:search:{encoded}")
        if not SPOGO_AUTHED:
            hint = _INSTALL_SPOGO_MSG if not HAS_SPOGO else _AUTH_SPOGO_MSG
            return f"Opened Spotify search for artist '{query}'. (Tip: {hint})"
        return f"Opened Spotify search for artist '{query}'. Please select an artist to play."

    elif action == "play_album" and query:
        if SPOGO_AUTHED:
            data, err = _spogo_json(["search", "album", query, "--limit", "1"])
            if data:
                albums = data.get("items", [])
                if albums:
                    uri = albums[0].get("uri", "")
                    name = albums[0].get("name", query)
                    result = _spotify_applescript(f'tell application "Spotify" to play track "{uri}"')
                    if result.startswith("Error"):
                        return f"Found album '{name}' but could not start playback. Is Spotify open? ({result})"
                    return f"Playing album '{name}' on Spotify."
        # Fallback: open album search URI
        import urllib.parse
        encoded = urllib.parse.quote(query)
        _spotify_open_uri(f"spotify:search:{encoded}")
        if not SPOGO_AUTHED:
            hint = _INSTALL_SPOGO_MSG if not HAS_SPOGO else _AUTH_SPOGO_MSG
            return f"Opened Spotify search for album '{query}'. (Tip: {hint})"
        return f"Opened Spotify search for album '{query}'. Please select an album to play."

    elif action == "search" and query:
        if SPOGO_AUTHED:
            result = _spogo(["search", "track", query, "--limit", "15", "--plain"])
            if not result.startswith("Error") and result:
                return f"Spotify search results for '{query}':\n{result}"
        # Fallback: open search in Spotify app
        import urllib.parse
        encoded = urllib.parse.quote(query)
        _spotify_open_uri(f"spotify:search:{encoded}")
        return f"Opened Spotify search for '{query}' in the app."

    elif action == "artist_info" and query:
        if not SPOGO_AUTHED:
            hint = _INSTALL_SPOGO_MSG if not HAS_SPOGO else _AUTH_SPOGO_MSG
            return f"Artist info requires spogo. {hint}"
        data, err = _spogo_json(["search", "artist", query, "--limit", "1"])
        if not data:
            return err or f"Could not find artist '{query}' on Spotify."
        artists = data.get("items", [])
        if not artists:
            return f"Could not find artist '{query}' on Spotify."
        artist_id = artists[0].get("id", "")
        name = artists[0].get("name", query)
        info = _spogo(["artist", "info", artist_id, "--plain"])
        if info.startswith("Error"):
            return f"Found {name} but could not fetch details."
        return info

    elif action == "album_info" and query:
        if not SPOGO_AUTHED:
            hint = _INSTALL_SPOGO_MSG if not HAS_SPOGO else _AUTH_SPOGO_MSG
            return f"Album info requires spogo. {hint}"
        data, err = _spogo_json(["search", "album", query, "--limit", "1"])
        if not data:
            return err or f"Could not find album '{query}' on Spotify."
        albums = data.get("items", [])
        if not albums:
            return f"Could not find album '{query}' on Spotify."
        album_id = albums[0].get("id", "")
        info = _spogo(["album", "info", album_id, "--plain"])
        if info.startswith("Error"):
            name = albums[0].get("name", query)
            return f"Found '{name}' but could not fetch details."
        return info

    elif action == "list_artists":
        if not SPOGO_AUTHED:
            hint = _INSTALL_SPOGO_MSG if not HAS_SPOGO else _AUTH_SPOGO_MSG
            return f"Listing library artists requires spogo. {hint}"
        result = _spogo(["library", "artists", "list", "--limit", "50", "--plain"], timeout=30)
        if result.startswith("Error") or not result:
            return "Could not read your Spotify library."
        return f"Artists in your Spotify library:\n{result}"

    elif action == "list_albums":
        if not SPOGO_AUTHED:
            hint = _INSTALL_SPOGO_MSG if not HAS_SPOGO else _AUTH_SPOGO_MSG
            return f"Listing library albums requires spogo. {hint}"
        result = _spogo(["library", "albums", "list", "--limit", "50", "--plain"], timeout=30)
        if result.startswith("Error") or not result:
            return "Could not read your Spotify library."
        return f"Albums in your Spotify library:\n{result}"

    return f"Unknown action: {action}"


# ---------------------------------------------------------------------------
# Apple Music actions via AppleScript
# ---------------------------------------------------------------------------
def _apple_music_execute(action: str, query: str, artist: str) -> str:
    """Handle all Apple Music actions via AppleScript."""
    safe_query = query.replace("'", "'\\''") if query else ""
    safe_artist = artist.replace("'", "'\\''") if artist else ""

    if action == "play":
        _applescript('tell application "Music" to play')
        return "Resumed playback on Apple Music."

    elif action == "pause":
        _applescript('tell application "Music" to pause')
        return "Paused Apple Music."

    elif action == "next":
        _applescript('tell application "Music" to next track')
        return "Skipped to next track on Apple Music."

    elif action == "previous":
        _applescript('tell application "Music" to previous track')
        return "Went to previous track on Apple Music."

    elif action == "current_track":
        info = _applescript(
            'tell application "Music" to get '
            '{name of current track, artist of current track, album of current track}'
        )
        if info.startswith("Error"):
            return "No track is currently playing."
        return f"Now playing on Apple Music: {info}"

    elif action == "play_song" and safe_query:
        if safe_artist:
            result = _applescript(
                f'tell application "Music"\n'
                f'  set results to (search playlist "Library" for "{safe_query}" only songs)\n'
                f'  if (count of results) = 0 then return "NOT_FOUND"\n'
                f'  repeat with t in results\n'
                f'    if artist of t contains "{safe_artist}" then\n'
                f'      play t\n'
                f'      return name of current track & " by " & artist of current track\n'
                f'    end if\n'
                f'  end repeat\n'
                f'  play item 1 of results\n'
                f'  return name of current track & " by " & artist of current track\n'
                f'end tell'
            )
        else:
            result = _applescript(
                f'tell application "Music"\n'
                f'  set results to (search playlist "Library" for "{safe_query}" only songs)\n'
                f'  if (count of results) > 0 then\n'
                f'    play item 1 of results\n'
                f'    return name of current track & " by " & artist of current track\n'
                f'  else\n'
                f'    return "NOT_FOUND"\n'
                f'  end if\n'
                f'end tell'
            )
        if "NOT_FOUND" in result or result.startswith("Error"):
            msg = f"Could not find '{query}'"
            if artist:
                msg += f" by {artist}"
            return msg + " in your Apple Music library."
        return f"Now playing: {result}"

    elif action == "play_artist" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose artist contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set shuffle enabled to true\n'
            f'  play item 1 of results\n'
            f'  return "Playing " & artist of current track & " — " & name of current track & " (" & (count of results) & " tracks, shuffled)"\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find artist '{query}' in your Apple Music library."
        return result

    elif action == "play_album" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (search playlist "Library" for "{safe_query}" only albums)\n'
            f'  if (count of results) > 0 then\n'
            f'    play item 1 of results\n'
            f'    return "Playing album: " & album of current track\n'
            f'  else\n'
            f'    return "NOT_FOUND"\n'
            f'  end if\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find album '{query}' in your Apple Music library."
        return result

    elif action == "artist_info" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose artist contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set albumList to {{}}\n'
            f'  set songList to {{}}\n'
            f'  repeat with t in results\n'
            f'    set aName to album of t\n'
            f'    if aName is not in albumList then set end of albumList to aName\n'
            f'    if (count of songList) < 20 then\n'
            f'      set end of songList to (name of t & " (" & album of t & ")")\n'
            f'    end if\n'
            f'  end repeat\n'
            f'  set albumCount to count of albumList\n'
            f'  set songCount to count of results\n'
            f'  set output to "Artist: {safe_query}" & return & "Songs: " & songCount & ", Albums: " & albumCount & return & return & "Albums:" & return\n'
            f'  repeat with a in albumList\n'
            f'    set output to output & "- " & a & return\n'
            f'  end repeat\n'
            f'  set output to output & return & "Songs (first 20):" & return\n'
            f'  repeat with s in songList\n'
            f'    set output to output & "- " & s & return\n'
            f'  end repeat\n'
            f'  return output\n'
            f'end tell',
            timeout=30,
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find artist '{query}' in your Apple Music library."
        return result

    elif action == "album_info" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose album contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set output to "Album: " & album of (item 1 of results) & return & "Artist: " & artist of (item 1 of results) & return & "Tracks:" & return\n'
            f'  repeat with t in results\n'
            f'    set output to output & (track number of t) & ". " & (name of t) & " (" & (round ((duration of t) / 60) rounding down) & ":" & text -2 thru -1 of ("0" & (round ((duration of t) mod 60))) & ")" & return\n'
            f'  end repeat\n'
            f'  return output\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find album '{query}' in your Apple Music library."
        return result

    elif action == "search" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (search playlist "Library" for "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set output to "Search results for \\"{safe_query}\\":" & return\n'
            f'  set maxItems to 15\n'
            f'  if (count of results) < maxItems then set maxItems to (count of results)\n'
            f'  repeat with i from 1 to maxItems\n'
            f'    set t to item i of results\n'
            f'    set output to output & "- " & (name of t) & " by " & (artist of t) & " (" & (album of t) & ")" & return\n'
            f'  end repeat\n'
            f'  if (count of results) > 15 then set output to output & "... and " & ((count of results) - 15) & " more results"\n'
            f'  return output\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"No results found for '{query}' in your Apple Music library."
        return result

    elif action == "list_artists":
        result = _applescript(
            'tell application "Music"\n'
            '  set allTracks to every track of playlist "Library"\n'
            '  set artistList to {}\n'
            '  repeat with t in allTracks\n'
            '    set aName to artist of t\n'
            '    if aName is not in artistList then set end of artistList to aName\n'
            '  end repeat\n'
            '  set totalCount to count of artistList\n'
            '  set maxShow to 50\n'
            '  if totalCount < maxShow then set maxShow to totalCount\n'
            '  set output to "Artists in your library (" & totalCount & " total):" & return\n'
            '  repeat with i from 1 to maxShow\n'
            '    set output to output & "- " & item i of artistList & return\n'
            '  end repeat\n'
            '  if totalCount > 50 then set output to output & "... and " & (totalCount - 50) & " more"\n'
            '  return output\n'
            'end tell',
            timeout=30,
        )
        if result.startswith("Error"):
            return "Could not read your Apple Music library."
        return result

    elif action == "list_albums":
        result = _applescript(
            'tell application "Music"\n'
            '  set allTracks to every track of playlist "Library"\n'
            '  set albumList to {}\n'
            '  set albumArtists to {}\n'
            '  repeat with t in allTracks\n'
            '    set aName to album of t\n'
            '    if aName is not in albumList then\n'
            '      set end of albumList to aName\n'
            '      set end of albumArtists to artist of t\n'
            '    end if\n'
            '  end repeat\n'
            '  set totalCount to count of albumList\n'
            '  set maxShow to 50\n'
            '  if totalCount < maxShow then set maxShow to totalCount\n'
            '  set output to "Albums in your library (" & totalCount & " total):" & return\n'
            '  repeat with i from 1 to maxShow\n'
            '    set output to output & "- " & item i of albumList & " (" & item i of albumArtists & ")" & return\n'
            '  end repeat\n'
            '  if totalCount > 50 then set output to output & "... and " & (totalCount - 50) & " more"\n'
            '  return output\n'
            'end tell',
            timeout=30,
        )
        if result.startswith("Error"):
            return "Could not read your Apple Music library."
        return result

    return f"Unknown action: {action}"


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------
def execute(args: dict) -> str:
    """Route to the correct backend based on the app parameter."""
    action = args.get("action", "")
    app = args.get("app", "apple_music")
    query = args.get("query", "")
    artist = args.get("artist", "")

    if app == "spotify":
        return _spotify_execute(action, query, artist)
    return _apple_music_execute(action, query, artist)
