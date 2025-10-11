# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

try:
    from vayuayan import __version__ as package_version
except Exception:
    package_version = "0.1.0"

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "vayuayan"
copyright = "2025"
author = ""
release = package_version
version = os.environ.get("SMV_CURRENT_VERSION") or os.environ.get(
    "READTHEDOCS_VERSION_NAME",
    release,
)

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "myst_nb",
    # "sphinx_multiversion",  # Temporarily disabled due to template error
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

language = "en"

# -- Autodoc configuration --------------------------------------------------
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}

# -- Napoleon settings -------------------------------------------------------
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

# -- Intersphinx mapping ----------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["css/custom.css"]

# Logo configuration
html_logo = "assets/vayuayan.png"

html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/scroll-end.html",
    ]
}

# -- Theme options -----------------------------------------------------------
html_theme_options = {
    "navigation_with_keys": True,
    "sidebar_hide_name": False,  # Show name alongside logo
    "default_mode": "dark",  # Set dark theme as default for Furo
    "light_css_variables": {
        "color-brand-primary": "#1b1b1f",
        "color-brand-content": "#1b1b1f",
        "font-stack": '"SF Pro Display", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        "font-stack--monospace": '"SF Mono", "JetBrains Mono", Menlo, monospace',
    },
    "dark_css_variables": {
        "color-brand-primary": "#f5f5f7",
        "color-brand-content": "#f5f5f7",
        "background-color": "#050505",
        "background-color-secondary": "#121214",
    },
}

# Set default color scheme to dark
html_css_files = ["css/custom.css"]

# MyST-NB configuration
nb_execution_mode = "off"

# Sphinx multiversion settings (disabled)
# smv_branch_whitelist = os.environ.get(
#     "SMV_BRANCH_WHITELIST",
#     r"^(master|main|release/.+)$",
# )
# smv_tag_whitelist = os.environ.get("SMV_TAG_WHITELIST", r"^v\d+\.\d+\.\d+$")
# smv_remote_whitelist = os.environ.get("SMV_REMOTE_WHITELIST", r"^origin$")
# smv_outputdir_format = "{ref.refname}"
# smv_latest_version = os.environ.get("SMV_LATEST_VERSION", "master")
# smv_rename_latest_version = "latest"
