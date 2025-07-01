"""
This file is refactored from packages/core_ts/src/tools/diffOptions.ts.
It contains default options for generating diffs.
"""

# In Python's difflib, the equivalent of 'context' is `n` in unified_diff.
# The equivalent of 'ignoreWhitespace' is not a direct parameter but can be
# achieved by pre-processing lines if needed. For now, we'll just define
# the context lines.

DEFAULT_DIFF_CONTEXT_LINES = 3
