import os
import re
import sys
import inspect
import importlib.metadata

project = "pytest-bluezenv"
copyright = "2026, Pauli Virtanen"
author = "Pauli Virtanen"
release = importlib.metadata.version("pytest-bluezenv")

extensions = ["sphinx.ext.autosummary", "sphinx.ext.napoleon", "sphinx.ext.linkcode"]
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

autosummary_generate = True

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_title = f"{project} {release}"
html_logo = "_static/logo.svg"

html_theme_options = {
    "logo": {
        "text": f"pytest-bluezenv {release}",
        "image_light": "_static/logo.svg",
        "image_dark": "_static/logo.svg",
    }
}

import pytest_bluezenv


def linkcode_resolve(domain, info):
    if domain != "py":
        return None

    modname = info["module"]
    fullname = info["fullname"]

    submod = sys.modules.get(modname)
    if submod is None:
        return None

    obj = submod
    for part in fullname.split("."):
        try:
            obj = getattr(obj, part)
        except Exception:
            return None

    # Use the original function object if it is wrapped.
    obj = getattr(obj, "__wrapped__", obj)
    try:
        fn = inspect.getsourcefile(obj)
    except Exception:
        fn = None
    if not fn:
        try:
            fn = inspect.getsourcefile(sys.modules[obj.__module__])
        except Exception:
            fn = None
    if not fn:
        return None

    try:
        source, lineno = inspect.getsourcelines(obj)
    except Exception:
        lineno = None

    if lineno:
        linespec = "#L%d-L%d" % (lineno, lineno + len(source) - 1)
    else:
        linespec = ""

    startdir = os.path.abspath(
        os.path.join(os.path.dirname(pytest_bluezenv.__file__), "..")
    )
    fn = os.path.relpath(fn, start=startdir).replace(os.path.sep, "/")

    if fn.startswith("pytest_bluezenv/"):
        fn = "src/" + fn
        m = re.match(r"^.*dev\d+\+([a-f0-9]+)$", release)
        if m:
            return "https://github.com/pv/pytest-bluezenv/blob/%s/%s%s" % (
                m.group(1),
                fn,
                linespec,
            )
        elif "dev" in release:
            return "https://github.com/pv/pytest-bluezenv/blob/main/%s%s" % (
                fn,
                linespec,
            )
        else:
            return "https://github.com/pv/pytest-bluezenv/blob/v%s/%s%s" % (
                release,
                fn,
                linespec,
            )
    else:
        return None
