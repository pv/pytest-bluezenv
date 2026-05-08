# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
%(prog)s
"""
import re
import os
import sys
import argparse
import subprocess
import tempfile
from pathlib import Path


def main():
    p = argparse.ArgumentParser(usage=__doc__.strip())
    sp = p.add_subparsers(required=True, help="subcommand")

    attach_p = sp.add_parser("attach")
    attach_p.set_defaults(main=main_attach)

    args = p.parse_args()
    args.main(args)


def main_attach(args):
    sockets = []

    tmpdir = Path(tempfile.gettempdir())
    for d in tmpdir.iterdir():
        if not d.name.startswith("pytest-bluezenv-"):
            continue

        for s in d.iterdir():
            if s.name.startswith("pytest-bluezenv-tty-"):
                sockets.append(s)

    if not sockets:
        print(f"No sockets in {tmpdir} to attach to")
        return

    session = "pytest-bluezenv"

    for j, sock in enumerate(sockets):
        name = re.sub(r".*tty-", "host", sock.name)

        cmd = ["tmux"]
        if j == 0:
            cmd += ["new-session", "-d", "-n", name, "-s", session]
        else:
            cmd += ["new-window", "-d", "-n", name, "-t", f"{session}:"]
        cmd += ["--", "socat", sock, "STDIO,rawer"]

        subprocess.run(cmd, check=True)

    os.execvp("tmux", ["tmux", "attach-session", "-t", session])


if __name__ == "__main__":
    main()
    sys.exit(0)
