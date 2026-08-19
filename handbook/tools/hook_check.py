#!/usr/bin/env python3
"""Stop-hook entry point: refuse to end a session with a stale handbook.

Claude Code invokes this with the hook payload on stdin. It blocks only on
`check` **errors** -- the machine-fixable ones, every one of which is
resolved by running `build`. Drift warnings never block: deciding whether a
prose chapter is still true is a person's job, and a hook that demands
judgement gets disabled.

Two safeguards against wedging a session:

* `stop_hook_active` in the payload means this hook already blocked once.
  Blocking again would loop, so it stands down and lets the session end.
* Any unexpected failure inside the hook exits 0. A broken documentation
  check must never be the reason somebody cannot finish their work.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    if payload.get("stop_hook_active"):
        return 0

    try:
        import gen
        import lint

        errors = [f for f in gen.collect_findings(ROOT) if f.level == lint.ERROR]
    except Exception as error:  # never wedge a session over the handbook
        print(f"handbook hook skipped: {error}", file=sys.stderr)
        return 0

    if not errors:
        return 0

    detail = "\n".join(f"  {f.code}  {f.page}: {f.message}" for f in errors[:10])
    if len(errors) > 10:
        detail += f"\n  ... and {len(errors) - 10} more"
    print(
        f"The handbook is out of date: {len(errors)} error(s).\n{detail}\n\n"
        "Run `python3 handbook/tools/gen.py build`, then read any chapter whose "
        "subject changed and re-baseline it with "
        "`python3 handbook/tools/gen.py accept --chapter <id>`. "
        "See handbook/chapters/30-how-this-handbook-stays-true.md.",
        file=sys.stderr,
    )
    return 2  # exit 2 on a Stop hook feeds stderr back and blocks stopping


if __name__ == "__main__":
    sys.exit(main())
