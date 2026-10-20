"""Private complete-market st_events source verification; never a production writer."""
from event_verification import main

if __name__ == "__main__":
    raise SystemExit(main("st_events"))
