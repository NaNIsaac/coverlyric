"""Print the bundled ffmpeg's version line and whether it has the H.264 encoder."""

import subprocess

from coverlyric import media

exe = media.ffmpeg()
version = subprocess.run(
    [exe, "-version"], capture_output=True, text=True, check=True
).stdout.splitlines()[0]
encoders = subprocess.run(
    [exe, "-hide_banner", "-encoders"], capture_output=True, text=True, check=True
).stdout
print(version)
print("libx264:", "libx264" in encoders)
