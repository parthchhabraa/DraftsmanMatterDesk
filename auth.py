import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os

CACHE_PATH = '/home/st6b/matterdesk/.cache'
if os.path.exists(CACHE_PATH):
    os.remove(CACHE_PATH)

print("\n--- Spotify Token Generator (Expanded Scope) ---")
auth_manager = SpotifyOAuth(
    client_id='515b520ddd7b4ed2a33fdd1091c9ef00',
    client_secret='e24611ecfa1c4be2b28c1d59e40af0b8',
    redirect_uri='http://127.0.0.1:8080/callback',
    scope='user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative',
    cache_path=CACHE_PATH,
    open_browser=False
)
sp = spotipy.Spotify(auth_manager=auth_manager)
sp.current_user()
print("\nToken successfully cached at /home/st6b/matterdesk/.cache\n")