# jupyter_server_config.py — registers code-server as a proxied app in JupyterLab.
# Identical to the GPU image configuration; the proxy is CPU-agnostic.

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
        },
    }
}
