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
            "icon_path": "/opt/conda/lib/python3.11/site-packages/jupyter_server_proxy/icons/server-proxy.svg",
        },
    }
}
