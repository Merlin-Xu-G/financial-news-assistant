"""包入口，使 ``python -m scripts.kb`` 可用。"""

from .cli import main

raise SystemExit(main())
