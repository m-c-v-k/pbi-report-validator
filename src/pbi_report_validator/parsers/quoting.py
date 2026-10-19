"""Single-quoted names and literals, as used by PBIR and TMDL.

Both formats wrap text in single quotes and escape a quote inside it by
doubling it: ``'Sales ''24'`` stands for ``Sales '24``.
"""


def is_quoted(value: str) -> bool:
    """Whether ``value`` is wrapped in single quotes."""
    return len(value) >= 2 and value.startswith("'") and value.endswith("'")


def unquote(value: str) -> str:
    """Strip the quotes and undouble inner quotes; unquoted text is unchanged."""
    if is_quoted(value):
        return value[1:-1].replace("''", "'")
    return value
