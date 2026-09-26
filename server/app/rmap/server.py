"""RMAP server Flask extension"""

import rmap


class RMAPServerExtension:
    """RMAP server Flask extension"""

    def __init__(self, app=None):
        """Initialize extension"""

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize RMAP server and store as app extension"""

        # Read private key pass from secret file
        with open(
            app.config["RMAP_SERVER_PRIVATE_KEY_PASS_FILE"], encoding="utf8"
        ) as pass_file:
            private_key_pass = pass_file.read().strip()

        rmap_server = rmap.RMAPServer(
            server_public_key_path=app.config["RMAP_SERVER_PUBLIC_KEY_PATH"],
            server_private_key_path=app.config["RMAP_SERVER_PRIVATE_KEY_PATH"],
            passphrase=private_key_pass,
            linkPrefix=app.config["RMAP_LINK_PREFIX"],
        )
        rmap_server.loadIdentities(app.config["RMAP_CLIENT_KEYS_DIR"])

        # Register server as extension
        app.extensions["rmap-server"] = rmap_server
