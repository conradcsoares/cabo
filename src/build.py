"""Builds the standalone website version (dist/index.html) from the shared game page."""
import os
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "game.html")).read()
shim = open(os.path.join(here, "peer-shim.js")).read()
head = ('<script src="https://cdn.jsdelivr.net/npm/peerjs@1.5.4/dist/peerjs.min.js" '
        'onerror="var s=document.createElement(\'script\');s.src=\'https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js\';document.head.appendChild(s)"></script>\n'
        '<script>\n' + shim + '\n</script>\n')
marker = '<script>\n"use strict";'
assert src.count(marker) == 1
out = src.replace(marker, head + marker)
old = "Online play needs this page opened from its shared Claude link while signed in. Practice mode works anywhere."
assert old in out
out = out.replace(old, "Couldn’t load online play — check your internet connection and refresh. Practice mode still works.")
open(os.path.join(here, "..", "index.html"), "w").write(out)
print("built index.html", len(out), "bytes")
