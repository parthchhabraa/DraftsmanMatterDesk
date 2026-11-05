"""MatterDesk v6.

    python -m desk                 run the desk (http://127.0.0.1:8420)
    python -m desk demo            run with fake data, no Pi hardware needed
    python -m desk spotify-auth    one-time Spotify login, run over SSH
    python -m desk key             print a fresh random key for desk.toml
"""
from __future__ import annotations

import logging
import os
import secrets
import sys


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if cmd == "key":
        print(secrets.token_urlsafe(24))
        return
    if cmd == "demo":
        os.environ["MATTERDESK_DEMO"] = "1"
        cmd = "serve"
    from .config import load_config
    cfg = load_config()
    if cmd == "spotify-auth":
        from .engines.spotify import make_auth
        if not (cfg.spotify.client_id and cfg.spotify.client_secret):
            sys.exit("Set [spotify] client_id and client_secret in config/desk.toml first.")
        auth = make_auth(cfg)
        print("\n1. Open this on your Mac:\n\n" + auth.get_authorize_url())
        url = input("\n2. After you approve, the browser lands on a page that will not load.\n"
                    "   Copy that whole address and paste it here: ").strip()
        auth.get_access_token(auth.parse_response_code(url), as_dict=False)
        print(f"\nSaved token to {cfg.spotify.cache_path}. Restart the desk.")
        return
    if cmd == "serve":
        import uvicorn
        from .server import create_app
        uvicorn.run(create_app(cfg), host=cfg.server.host, port=cfg.server.port, log_level="warning",
                    ws_ping_interval=20)
        return
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
