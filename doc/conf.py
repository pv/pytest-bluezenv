import importlib.metadata

project = 'pytest-bluezenv'
copyright = '2026, Pauli Virtanen'
author = 'Pauli Virtanen'
release = importlib.metadata.version('pytest-bluezenv')

extensions = ["sphinx.ext.autosummary", "sphinx.ext.napoleon"]
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

autosummary_generate = True

html_theme = 'pyramid'
html_static_path = ['_static']
