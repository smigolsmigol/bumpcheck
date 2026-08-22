import os
import subprocess
import sys


def run():
    print("python stdout", flush=True)
    os.write(1, b"native stdout\n")
    subprocess.run(
        [sys.executable, "-c", "print('child stdout')"],
        check=True,
    )
    print("python stderr", file=sys.stderr, flush=True)
    os.write(2, b"native stderr\n")
    return {"ok": True}
