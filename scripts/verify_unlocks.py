"""Owned private source verification; production settings remain read only."""
from unlock_verification import main

if __name__ == "__main__":
    raise SystemExit(main('unlocks'))
