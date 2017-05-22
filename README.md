Basic tool for checking typeshed stubs for completeness. Needs more work.

Currently it's somewhat usable as follows:
- # make a venv
- `pip install typeshed-client inspect2`
- `git clone https://github.com/JelleZijlstra/stubcheck`
- `cd stubcheck`
- `python3 checker.py os  # or any other module`

Major limitation: it checks typeshed as bundled by your version of mypy, not a
checked out version.
