# jupyter_lab_config.py — read by JupyterLab's ExtensionApp.
#
# c.LabApp.custom_css is also set in jupyter_server_config.py. It is repeated
# here because LabApp is an ExtensionApp and whether it inherits LabApp config
# from the server's config file is a version-dependent detail. Setting both
# costs nothing and removes the guess.
c.LabApp.custom_css = True
