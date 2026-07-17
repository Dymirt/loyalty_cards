"""Small configuration helpers that are safe to unit test without Django setup."""


def config_with_legacy_alias(config, primary, legacy, *, default=""):
    """Read a renamed setting while retaining one bounded legacy fallback."""

    value = config(primary, default="")
    if value:
        return value
    return config(legacy, default=default)
