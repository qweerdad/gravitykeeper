"""Files supplied by Windows or Microsoft's own redistributable installer."""

from pathlib import PurePosixPath
import re


MICROSOFT_NAMES = re.compile(
    r"^(?:(?:api-ms-|ext-ms-|vcruntime|msvcp|msvcr|concrt|vcomp|mfc|mfcm|atl).*\.dll"
    r"|ucrtbase(?:d)?\.dll|vc[_-]?redist.*\.(?:exe|msm))$",
    re.IGNORECASE,
)


def is_microsoft_runtime(name):
    return MICROSOFT_NAMES.fullmatch(PurePosixPath(name.replace("\\", "/")).name) is not None
