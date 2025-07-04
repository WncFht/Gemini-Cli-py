from __future__ import annotations

import logging
import re
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from gemini_cli_core.core.app import GeminiClient
    from gemini_cli_core.tools.file.edit_file import EditToolParams


logger = logging.getLogger(__name__)

# --- Caches ---
MAX_CACHE_SIZE = 50
edit_correction_cache: OrderedDict[str, CorrectedEditResult] = OrderedDict()
file_content_correction_cache: OrderedDict[str, str] = OrderedDict()


def _get_from_cache(cache: OrderedDict, key: str) -> Any:
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    return None


def _set_in_cache(cache: OrderedDict, key: str, value: Any):
    if len(cache) >= MAX_CACHE_SIZE:
        cache.popitem(last=False)
    cache[key] = value


# --- Data Models ---
class CorrectedEditParams(BaseModel):
    file_path: str
    old_string: str
    new_string: str


class CorrectedEditResult(BaseModel):
    params: CorrectedEditParams
    occurrences: int


# --- Schemas for LLM ---
OLD_STRING_CORRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "corrected_target_snippet": {
            "type": "string",
            "description": "The corrected version of the target snippet that exactly and uniquely matches within the provided file content.",
        },
    },
    "required": ["corrected_target_snippet"],
}

NEW_STRING_CORRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "corrected_new_string": {
            "type": "string",
            "description": "The adjusted new_string that is a suitable replacement for the corrected_old_string, maintaining the intent of the original change.",
        },
    },
    "required": ["corrected_new_string"],
}

CORRECT_NEW_STRING_ESCAPING_SCHEMA = {
    "type": "object",
    "properties": {
        "corrected_new_string_escaping": {
            "type": "string",
            "description": "The unescaped version of the new_string, ensuring it's a suitable replacement for the old_string, especially fixing over-escaping from previous LLM generations.",
        },
    },
    "required": ["corrected_new_string_escaping"],
}

CORRECT_STRING_ESCAPING_SCHEMA = {
    "type": "object",
    "properties": {
        "corrected_string_escaping": {
            "type": "string",
            "description": "The unescaped version of the string, ensuring it is valid, especially fixing over-escaping from previous LLM generations.",
        },
    },
    "required": ["corrected_string_escaping"],
}


async def ensure_correct_edit(
    current_content: str,
    original_params: EditToolParams,
    client: GeminiClient,
    abort_signal: Any | None = None,
) -> CorrectedEditResult:
    """
    Ensures edit parameters are correct, attempting to fix them if necessary.
    This is a detailed port of the original TypeScript logic.
    """
    cache_key = f"{current_content}---{original_params.old_string}---{original_params.new_string}"
    cached_result = _get_from_cache(edit_correction_cache, cache_key)
    if cached_result:
        return cached_result

    final_new_string = original_params.new_string
    new_string_potentially_escaped = (
        unescape_string_for_gemini_bug(original_params.new_string)
        != original_params.new_string
    )

    expected_replacements = original_params.expected_replacements or 1

    final_old_string = original_params.old_string
    occurrences = count_occurrences(current_content, final_old_string)

    if occurrences == expected_replacements:
        if new_string_potentially_escaped:
            final_new_string = await correct_new_string_escaping(
                client,
                final_old_string,
                original_params.new_string,
                abort_signal,
            )
    elif occurrences > expected_replacements:
        pass  # Too many matches, fall through. Validation will fail.
    else:  # occurrences is 0 or less than expected
        unescaped_old_string = unescape_string_for_gemini_bug(
            original_params.old_string
        )
        unescaped_occurrences = count_occurrences(
            current_content, unescaped_old_string
        )

        if unescaped_occurrences == expected_replacements:
            final_old_string = unescaped_old_string
            if new_string_potentially_escaped:
                final_new_string = await correct_new_string(
                    client,
                    original_params.old_string,
                    final_old_string,
                    original_params.new_string,
                    abort_signal,
                )
        elif unescaped_occurrences == 0:
            llm_corrected_old_string = await correct_old_string_mismatch(
                client, current_content, unescaped_old_string, abort_signal
            )
            llm_occurrences = count_occurrences(
                current_content, llm_corrected_old_string
            )

            if llm_occurrences == expected_replacements:
                final_old_string = llm_corrected_old_string
                if new_string_potentially_escaped:
                    base_new_string_for_llm = unescape_string_for_gemini_bug(
                        original_params.new_string
                    )
                    final_new_string = await correct_new_string(
                        client,
                        original_params.old_string,
                        final_old_string,
                        base_new_string_for_llm,
                        abort_signal,
                    )
            else:  # LLM failed
                final_old_string = original_params.old_string
    final_old_string, final_new_string = trim_pair_if_possible(
        final_old_string,
        final_new_string,
        current_content,
        expected_replacements,
    )

    result = CorrectedEditResult(
        params=CorrectedEditParams(
            file_path=original_params.file_path,
            old_string=final_old_string,
            new_string=final_new_string,
        ),
        occurrences=count_occurrences(current_content, final_old_string),
    )
    _set_in_cache(edit_correction_cache, cache_key, result)
    return result


async def ensure_correct_file_content(
    content: str, client: GeminiClient, abort_signal: Any | None = None
) -> str:
    """Ensures a new file's content is correctly unescaped, using an LLM if needed."""
    cached_result = _get_from_cache(file_content_correction_cache, content)
    if cached_result is not None:
        return cached_result

    if unescape_string_for_gemini_bug(content) == content:
        _set_in_cache(file_content_correction_cache, content, content)
        return content

    corrected_content = await correct_string_escaping(
        content, client, abort_signal
    )
    _set_in_cache(file_content_correction_cache, content, corrected_content)
    return corrected_content


async def correct_old_string_mismatch(
    client: GeminiClient,
    file_content: str,
    problematic_snippet: str,
    abort_signal: Any,
) -> str:
    """Uses an LLM to correct a mismatched old_string."""
    prompt = f"""
Background: A process needs to find an exact, literal, unique match for a snippet of text inside a file's content. The provided snippet failed to match perfectly. This is most likely because it was improperly escaped.

Task: Analyze the provided file content and the problematic target snippet. Identify the part of the file content that the snippet was *most likely* intended to match. Output the *exact, literal* text of that portion from the file content. *Only* focus on removing extraneous escape characters, fixing formatting, whitespace, or minor variations to achieve a perfect literal match. The output must be the exact literal text as it appears in the file.

Problematic Target Snippet:
```
{problematic_snippet}
```

File Content:
```
{file_content}
```

For example, if the problematic snippet is "\\nconst greeting = `Hello \\`\\${{name}}\\\\``;" and the file content has "\nconst greeting = `Hello `\\${{name}}``;", then corrected_target_snippet should be exactly that to fix the incorrect escaping.
If the difference is only whitespace or formatting, apply similar changes to corrected_target_snippet.

Return a JSON with only one key 'corrected_target_snippet' with the corrected target snippet. If no clear, unique match can be found, return an empty 'corrected_target_snippet'.
    """.strip()
    try:
        response = await client.generate_json(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            schema=OLD_STRING_CORRECTION_SCHEMA,
            abort_signal=abort_signal,
        )
        return response.get("corrected_target_snippet", problematic_snippet)
    except Exception as e:
        if not (hasattr(e, "code") and e.code == "ABORTED"):
            logger.warning(
                "LLM call for old_string correction failed.", exc_info=True
            )
        return problematic_snippet


async def correct_new_string(
    client: GeminiClient,
    original_old: str,
    corrected_old: str,
    original_new: str,
    abort_signal: Any,
) -> str:
    """Adjusts the new_string to align with the corrected old_string."""
    if original_old == corrected_old:
        return original_new
    prompt = f"""
Background: A text replacement operation is planned. The original text to be replaced (original_old_string) differs slightly from the actual text in the file (corrected_old_string). The original_old_string has now been corrected to match the file content.
We now need to adjust the replacement text (original_new_string) so that it makes sense as a replacement for the corrected_old_string, while preserving the intent of the original change.

original_old_string (what was originally going to be looked for):
```
{original_old}
```

corrected_old_string (what was actually found in the file and will be replaced):
```
{corrected_old}
```

original_new_string (what was intended to replace original_old_string):
```
{original_new}
```

Task: Based on the differences between original_old_string and corrected_old_string, and the content of original_new_string, generate a corrected_new_string. This corrected_new_string should be what original_new_string would have been if it were designed to directly replace corrected_old_string, maintaining the spirit of the original transformation.

For example, if original_old_string was "\\nconst x = 1;" and corrected_old_string is "  const x = 1;", and original_new_string was "\\nconst x = 2;", then corrected_new_string should likely be "  const x = 2;" to match the indentation.

Return a JSON with only one key 'corrected_new_string'. If no adjustment is deemed necessary or possible, return the original original_new_string.
    """.strip()
    try:
        response = await client.generate_json(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            schema=NEW_STRING_CORRECTION_SCHEMA,
            abort_signal=abort_signal,
        )
        return response.get("corrected_new_string", original_new)
    except Exception as e:
        if not (hasattr(e, "code") and e.code == "ABORTED"):
            logger.warning(
                "LLM call for new_string correction failed.", exc_info=True
            )
        return original_new


async def correct_new_string_escaping(
    client: GeminiClient,
    old_string: str,
    problematic_new_string: str,
    abort_signal: Any,
) -> str:
    """Corrects improper escaping in a new_string."""
    prompt = f"""
Background: A text replacement is planned. The text to be replaced (old_string) has been correctly identified in a file. However, the replacement text (new_string) may have been incorrectly escaped by a previous LLM generation (e.g., using \\n for a newline instead of \n, or unnecessary quotes like \\"Hello\\" instead of "Hello").

old_string (this is the exact text that will be replaced):
```
{old_string}
```

potentially_problematic_new_string (this is what should replace old_string, but might have bad escaping, or it could be perfectly fine):
```
{problematic_new_string}
```

Task: Analyze the potentially_problematic_new_string. If it is syntactically invalid due to incorrect escaping (e.g., "\\n", "\\t", "\\\\", "\\'", "\\""), fix the invalid syntax. The goal is to make sure the new_string is valid and will be interpreted correctly when inserted into code.

For example, if old_string is "foo" and potentially_problematic_new_string is "bar\\nbaz", then corrected_new_string_escaping should be "bar\nbaz".
If potentially_problematic_new_string is console.log(\\"Hello World\\"), it should be console.log("Hello World").

Return a JSON with only one key 'corrected_new_string_escaping' with the corrected string. If no escaping correction is needed, return the original potentially_problematic_new_string.
    """.strip()
    try:
        response = await client.generate_json(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            schema=CORRECT_NEW_STRING_ESCAPING_SCHEMA,
            abort_signal=abort_signal,
        )
        return response.get(
            "corrected_new_string_escaping", problematic_new_string
        )
    except Exception as e:
        if not (hasattr(e, "code") and e.code == "ABORTED"):
            logger.warning(
                "LLM call for new_string escaping correction failed.",
                exc_info=True,
            )
        return problematic_new_string


async def correct_string_escaping(
    problematic_string: str, client: GeminiClient, abort_signal: Any
) -> str:
    """Corrects a generic string that might be improperly escaped."""
    prompt = f"""
Background: An LLM just generated the potentially_problematic_string, which may have been improperly escaped (e.g., using \\n for a newline instead of \n, or unnecessary quotes like \\"Hello\\" instead of "Hello").

potentially_problematic_string (This text might have bad escaping, or it could be perfectly fine):
```
{problematic_string}
```

Task: Analyze the potentially_problematic_string. If it is syntactically invalid due to incorrect escaping (e.g., "\\n", "\\t", "\\\\", "\\'", "\\""), fix the invalid syntax. The goal is to make sure the text is valid and will be interpreted correctly.

For example, if potentially_problematic_string is "bar\\nbaz", then corrected_string_escaping should be "bar\nbaz".
If potentially_problematic_string is console.log(\\"Hello World\\"), it should be console.log("Hello World").

Return a JSON with only one key 'corrected_string_escaping' with the corrected string. If no escaping correction is needed, return the original potentially_problematic_string.
    """.strip()
    try:
        response = await client.generate_json(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            schema=CORRECT_STRING_ESCAPING_SCHEMA,
            abort_signal=abort_signal,
        )
        return response.get("corrected_string_escaping", problematic_string)
    except Exception as e:
        if not (hasattr(e, "code") and e.code == "ABORTED"):
            logger.warning(
                "LLM call for string escaping correction failed.", exc_info=True
            )
        return problematic_string


def trim_pair_if_possible(
    target: str,
    trim_if_target_trims: str,
    content: str,
    expected_replacements: int,
) -> tuple[str, str]:
    """
    Trims whitespace from both ends of a pair of strings if the trimmed target still
    has the expected number of occurrences in the content.
    """
    trimmed_target = target.strip()
    if len(target) != len(trimmed_target):
        trimmed_occurrences = count_occurrences(content, trimmed_target)
        if trimmed_occurrences == expected_replacements:
            return trimmed_target, trim_if_target_trims.strip()
    return target, trim_if_target_trims


def unescape_string_for_gemini_bug(input_string: str) -> str:
    """Fixes specific escaping errors in LLM-generated strings."""

    def replacer(match: re.Match) -> str:
        char = match.group(1)
        if char == "n":
            return "\n"
        if char == "t":
            return "\t"
        if char == "r":
            return "\r"
        if char in ("'", '"', "`", "\\", "\n"):
            return char
        return match.group(0)

    return re.sub(r"\\+(n|t|r|'|\"|`|\\|\n)", replacer, input_string)


def count_occurrences(text: str, sub: str) -> int:
    """Counts non-overlapping occurrences of a substring."""
    return text.count(sub) if sub else 0


def reset_edit_corrector_caches_test_only():
    """Resets all caches in this module, for testing purposes only."""
    edit_correction_cache.clear()
    file_content_correction_cache.clear()
