"""Launch host browsers without exporting a frozen Linux runtime's libraries."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser


def external_browser_environment(environ, bundle_roots):
    """Return a child-only environment; never modify the running DLMS process.

    PyInstaller saves the pre-bootloader search path in LD_LIBRARY_PATH_ORIG.
    AppRun currently adds no paths, but also filter AppDir paths if a launcher
    or runtime hook supplies them. Retain unrelated host preload/audit entries.
    """
    environment = dict(environ)
    roots = [Path(root).resolve() for root in bundle_roots if root]

    def bundled(value):
        if not value or not os.path.isabs(value):
            return False
        path = Path(value).resolve()
        return any(path == root or root in path.parents for root in roots)

    original = environment.pop("LD_LIBRARY_PATH_ORIG", "")
    environment.pop("LD_LIBRARY_PATH", None)
    original = ":".join(part for part in original.split(":") if part and not bundled(part))
    if original:
        environment["LD_LIBRARY_PATH"] = original
    for name in ("PATH", "LD_PRELOAD", "LD_AUDIT"):
        if name not in environment:
            continue
        parts = (re.split(r"[:\s]+", environment[name])
                 if name == "LD_PRELOAD" else environment[name].split(":"))
        value = ":".join(part for part in parts if part and not bundled(part))
        if value:
            environment[name] = value
        else:
            environment.pop(name, None)
    return environment


def open_browser(url):
    """Keep platform browser handling except where Linux frozen paths leak.

    webbrowser.open has no child env argument. Use the desktop URL dispatcher
    directly for frozen Linux, with the usual BROWSER override tried first.
    No shell command interpolation or temporary process-wide env changes.
    """
    if not (sys.platform.startswith("linux") and getattr(sys, "frozen", False)):
        return webbrowser.open(url, new=2)
    environment = external_browser_environment(
        os.environ, (getattr(sys, "_MEIPASS", None), os.environ.get("APPDIR"))
    )
    commands = []
    for choice in environment.get("BROWSER", "").split(os.pathsep):
        if not choice.strip():
            continue
        try:
            arguments = shlex.split(choice)
        except ValueError:
            continue
        if arguments:
            has_placeholder = any("%s" in part for part in arguments)
            arguments = [part.replace("%s", url) for part in arguments]
            commands.append(arguments if has_placeholder else [*arguments, url])
    commands.extend((["xdg-open", url], ["gio", "open", url], ["sensible-browser", url]))
    for command in commands:
        executable = shutil.which(command[0], path=environment.get("PATH", os.defpath))
        if not executable:
            continue
        try:
            process = subprocess.Popen(
                [executable, *command[1:]], env=environment,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                if process.wait(timeout=5) == 0:
                    return True
            except subprocess.TimeoutExpired:
                # A directly selected browser may remain open for its lifetime.
                # As with stdlib webbrowser, leave the user's browser running.
                return True
        except OSError:
            continue
    return False
