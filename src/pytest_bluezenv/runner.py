#!/usr/bin/python3 -P
# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
import sys
import pickle
from pathlib import Path
from importlib.machinery import PathFinder
from subprocess import run


class SelfImport(PathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pytest_bluezenv":
            path = [str(Path(__file__).parent / "..")]
        return super().find_spec(fullname, path, target)


sys.meta_path.insert(0, SelfImport())

# Mount /run/shared
path = Path("/run/shared")
path.mkdir()
run(["mount", "-t", "9p", "/dev/shared", str(path)], check=True)

# Early setup sys.path
with open("/run/shared/defaults", "rb") as f:
    sys.path = pickle.load(f)[0]


import pytest_bluezenv.env

sys.exit(pytest_bluezenv.env._main_runner())
