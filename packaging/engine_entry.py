"""PyInstaller entry point for the frozen AutoEditor engine.

The desktop app spawns this binary with the same CLI as
`python -m autoeditor`. Keeping the entry file separate from the package
lets PyInstaller resolve imports cleanly.
"""
from autoeditor.pipeline import main

if __name__ == "__main__":
    main()
