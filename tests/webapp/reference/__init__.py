"""The reference values the browser app is checked against, section by section.

``tests/webapp/make_reference.py`` is the file to run and the file other code
loads; this package is what it runs. ``build.py`` holds ``build()``, which
fills ``tests/webapp/reference.json`` entry by entry in the order the file
keeps; each other module holds the cases, the helpers and the
``*_reference()`` or ``fill_*()`` function of the entries its docstring
names; and ``common.py`` holds the paths, the JSON shapes and the tolerances
``--check`` compares within.

Nothing is imported here, so ``from reference.common import drifted`` costs
no more than that one module. The modules import each other relatively, and
only ``make_reference.py`` needs ``tests/webapp`` on ``sys.path``.
"""
