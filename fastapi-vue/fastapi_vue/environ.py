"""Access to the project's fastapi-vue environment variables.

The project entry point (generated __main__.py) sets FASTAPI_VUE to the
project-specific prefix (e.g. "MY_APP"). Project settings are then passed
as "<PREFIX>_*" environment variables; this module is the single place
that resolves those names.
"""

import os

PREFIX_VARIABLE = "FASTAPI_VUE"


class _Env:
    """Lazy accessors for the project's "<PREFIX>_*" environment variables.

    Evaluated on each access. Value accessors return None when FASTAPI_VUE
    or the variable itself is not set.
    """

    @property
    def prefix(self) -> str | None:
        """Return the project prefix from the FASTAPI_VUE environment variable."""
        return os.environ.get(PREFIX_VARIABLE) or None

    def _get(self, name: str) -> str | None:
        prefix = self.prefix
        return os.environ.get(f"{prefix}_{name}") if prefix else None

    @property
    def dev(self) -> bool:
        """Check whether running under the devserver (<PREFIX>_DEV=1)."""
        return self._get("DEV") == "1"

    @property
    def vite_url(self) -> str | None:
        """Return the vite devserver URL (<PREFIX>_VITE_URL), if set."""
        return self._get("VITE_URL")

    @property
    def backend_url(self) -> str | None:
        """Return the backend URL (<PREFIX>_BACKEND_URL), if set."""
        return self._get("BACKEND_URL")


env = _Env()
