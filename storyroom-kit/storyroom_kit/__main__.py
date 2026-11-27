from .cli import main

if __name__ == "__main__":  # (worker processes import this module too: they must not run the command again)
    raise SystemExit(main())
