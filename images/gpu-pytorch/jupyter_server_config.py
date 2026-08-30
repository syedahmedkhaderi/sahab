# jupyter_server_config.py — registers code-server as a proxied app in JupyterLab.
# Installed at /opt/conda/etc/jupyter/ so it is picked up by jupyter_server.
# The "vscode" key becomes the path segment: /user/<name>/proxy/vscode/

c.ServerProxy.servers = {
    "vscode": {
        "command": [
            "code-server",
            "--auth", "none",
            "--disable-telemetry",
            "--disable-update-check",
            "--user-data-dir", "/home/jovyan/work/.vscode-data",
            "--extensions-dir", "/home/jovyan/work/.vscode-extensions",
            "--bind-addr", "127.0.0.1:{port}",
        ],
        "timeout": 30,
        "new_browser_tab": True,
        "launcher_entry": {
            "title": "VS Code",
            "icon_path": "/opt/sahab/icons/vscode.svg",
        },
    }
}

# ---------------------------------------------------------------------------
# Embedding: allow the Sahab workspace shell to frame this server.
#
# JupyterHub 4.1 changed the single-user server's default CSP from
# `frame-ancestors 'self'` to `'none'`, which blocks every iframe including a
# same-origin one. Sahab serves the app, the API, the hub and /user/* from a
# single origin, and /sessions/<id>/workspace embeds this server there to give
# the user a way back out, a stop button and their credit usage.
#
# 'self' is the narrowest policy that permits that: only pages on this same
# origin may frame it, so an attacker would already have to control a page on
# our own domain. It is not 'none', and it is deliberately not '*'.
#
# jupyterhub.singleuser.mixins applies its default with headers.setdefault(),
# so this value is kept rather than overwritten.
# ---------------------------------------------------------------------------
c.ServerApp.tornado_settings = {
    "headers": {"Content-Security-Policy": "frame-ancestors 'self'"}
}

# ---------------------------------------------------------------------------
# Load /home/jovyan/.jupyter/custom/custom.css into the Lab page.
#
# jupyter_server resolves the search path as
# [os.path.join(d, "custom") for d in (config_dir, DEFAULT_STATIC_FILES_PATH)],
# and config_dir here is /home/jovyan/.jupyter, which is not on the user's
# named volume, so the file baked into the image is the one that is served.
# ---------------------------------------------------------------------------
c.LabApp.custom_css = True
