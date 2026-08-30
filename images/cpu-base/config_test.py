"""
Build-time gate for the Sahab workspace configuration.

Runs inside the built image, with no GPU and no network, so it executes on
every build rather than only on a GPU host the way smoke_test.py does.

The check that earns its keep is the schema validation. A wrong plugin id or a
renamed property in overrides.json is NOT an error to JupyterLab: it logs a
warning and ignores the entry. The styling would simply fail to appear, with
nothing on screen to say why. Validating against the schemas JupyterLab
actually shipped turns that silent no-op into a failed build.
"""

import json
import os
import sys

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}{': ' + detail if detail else ''}")
        FAILURES.append(label)


print("Sahab workspace config test")

# --- Paths, resolved rather than hardcoded: the GPU image is Miniconda under
# --- /opt/conda and the CPU image is system Python under /usr/local.
lab_dir = os.path.join(sys.prefix, "share", "jupyter", "lab")
overrides_path = os.path.join(lab_dir, "settings", "overrides.json")
schemas_root = os.path.join(lab_dir, "schemas")

print(f"\nsys.prefix = {sys.prefix}")

# --- overrides.json ---------------------------------------------------------
check("overrides.json exists", os.path.isfile(overrides_path), overrides_path)

overrides = {}
if os.path.isfile(overrides_path):
    try:
        with open(overrides_path) as fh:
            overrides = json.load(fh)
        check("overrides.json parses", True)
    except Exception as exc:  # noqa: BLE001
        check("overrides.json parses", False, str(exc))

# --- Validate every id and key against the schemas that actually shipped -----
check("schemas directory exists", os.path.isdir(schemas_root), schemas_root)

for plugin_id, settings in overrides.items():
    if ":" not in plugin_id:
        check(f"plugin id looks valid: {plugin_id}", False, "no ':' separator")
        continue

    package, _, schema_name = plugin_id.rpartition(":")
    schema_path = os.path.join(schemas_root, package, f"{schema_name}.json")

    if not os.path.isfile(schema_path):
        check(f"schema exists for {plugin_id}", False, schema_path)
        continue
    check(f"schema exists for {plugin_id}", True)

    with open(schema_path) as fh:
        properties = json.load(fh).get("properties", {})

    for key in settings:
        check(
            f"  {plugin_id} -> {key}",
            key in properties,
            f"not in schema; known keys: {sorted(properties)}",
        )

# --- The cell toolbar must gain a run button and take nothing away -----------
# JupyterLab 4.2 ships a per-cell toolbar with six items and no run button. The
# run button is the closest thing to Colab's per-cell play control reachable
# without writing an extension.
#
# The setting is a whole array, and it was not obvious whether overriding it
# replaces the schema's defaults or merges with them. Measured in a running
# workspace: it MERGES -- the six stock items still render, ours is added, and
# rank decides the order. That is why only the run button is listed below
# rather than all seven; re-listing the stock items would pin their command ids
# to whatever this version of JupyterLab happens to call them.
#
# This check exists because that merge behaviour is the load-bearing assumption.
# If a future JupyterLab starts replacing instead, the workspace silently loses
# delete-cell, move-cell-up and the rest, with nothing on screen to say why.
CELL_TOOLBAR = "@jupyterlab/cell-toolbar-extension:plugin"
cell_toolbar_schema = os.path.join(
    schemas_root, "@jupyterlab", "cell-toolbar-extension", "plugin.json"
)
if os.path.isfile(cell_toolbar_schema) and CELL_TOOLBAR in overrides:
    with open(cell_toolbar_schema) as fh:
        schema = json.load(fh)
    stock = schema.get("jupyter.lab.toolbars", {}).get("Cell", [])
    ours = overrides[CELL_TOOLBAR].get("toolbar", [])
    item_props = schema["definitions"]["toolbarItem"]["properties"]

    check("cell toolbar: schema still supplies the stock items", bool(stock))
    check(
        "cell toolbar: no stock item is overridden or disabled",
        not ({i["name"] for i in stock} & {i.get("name") for i in ours}),
        "an override shadowing a stock item can disable or rename it",
    )
    check(
        "cell toolbar: a run button is configured",
        any("run" in (i.get("command") or "") for i in ours),
        "no notebook:run-* command in the toolbar",
    )
    for item in ours:
        for key in item:
            check(f"  toolbar item key: {key}", key in item_props)

    # An item naming a command JupyterLab does not have renders as a dead
    # button, and like a bad settings key it fails silently.
    static_dir = os.path.join(lab_dir, "static")
    blob = ""
    if os.path.isdir(static_dir):
        for entry in os.listdir(static_dir):
            if entry.endswith(".js"):
                with open(
                    os.path.join(static_dir, entry), encoding="utf8", errors="ignore"
                ) as fh:
                    blob += fh.read()
    for item in ours:
        command = item.get("command", "")
        check(f"  command exists: {command}", command in blob)
        icon = item.get("icon")
        if icon:
            check(f"  icon exists: {icon}", icon in blob)

# --- custom.css -------------------------------------------------------------
# jupyter_server searches [config_dir/custom, DEFAULT_STATIC_FILES_PATH/custom],
# and config_dir is /home/jovyan/.jupyter here.
css_path = "/home/jovyan/.jupyter/custom/custom.css"
check("custom.css exists", os.path.isfile(css_path), css_path)
if os.path.isfile(css_path):
    css = open(css_path).read()
    check("custom.css is not empty", len(css.strip()) > 0)
    check(
        "custom.css braces balanced",
        css.count("{") == css.count("}"),
        f"{css.count('{')} open vs {css.count('}')} close",
    )

# --- The trait that serves it must be real for this JupyterLab version ------
try:
    from jupyterlab.labapp import LabApp

    check("LabApp has a custom_css trait", "custom_css" in LabApp.class_traits())
except Exception as exc:  # noqa: BLE001
    check("LabApp imports", False, str(exc))

# --- Server config: syntax only. Executing it would fail on the undefined `c`.
config_dirs = [
    os.path.join(sys.prefix, "etc", "jupyter"),
    "/etc/jupyter",
]
found_server_config = False
for directory in config_dirs:
    path = os.path.join(directory, "jupyter_server_config.py")
    if os.path.isfile(path):
        found_server_config = True
        try:
            compile(open(path).read(), path, "exec")
            check(f"{path} compiles", True)
        except SyntaxError as exc:
            check(f"{path} compiles", False, str(exc))

        source = open(path).read()
        check(
            "single-user CSP allows same-origin framing",
            "frame-ancestors 'self'" in source,
            "the workspace shell embeds this server in an iframe",
        )
        check("custom_css is enabled", "c.LabApp.custom_css = True" in source)

check("a jupyter_server_config.py was found", found_server_config, str(config_dirs))

# --- The launcher icon path, if one is configured, must exist ---------------
# The GPU image hardcodes an /opt/conda/... path that does not exist in the
# CPU image; this catches that class of drift.
for directory in config_dirs:
    path = os.path.join(directory, "jupyter_server_config.py")
    if not os.path.isfile(path):
        continue
    for line in open(path):
        if '"icon_path"' in line:
            icon = line.split('"')[3]
            check(f"launcher icon exists: {icon}", os.path.isfile(icon))

# --- The proxied app must import --------------------------------------------
try:
    import jupyter_server_proxy  # noqa: F401

    check("jupyter_server_proxy imports", True)
except Exception as exc:  # noqa: BLE001
    check("jupyter_server_proxy imports", False, str(exc))

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)

print("All workspace config checks passed.")
