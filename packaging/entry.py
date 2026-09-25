"""PyInstaller entry point (onefile exe / linux binary)."""
import sys

from yalevpn.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))