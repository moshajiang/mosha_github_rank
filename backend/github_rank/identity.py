import hashlib
from pathlib import Path


def workspace_id(root):
    return hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:20]
