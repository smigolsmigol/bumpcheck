import warnings


def run():
    warnings.warn("old API", DeprecationWarning, stacklevel=2)
    return None
