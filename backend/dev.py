"""Local web app API backed by the Track 1 course dataset in data/.

Set COPILOT_DATA_DIR (e.g. to demo_data) to run against another data directory.
"""

import base64
import os
import secrets

from backend.app.main import create_app
from backend.copilot import BACKEND_DIR, DEFAULT_CONFIG_PATH, DEFAULT_DATA_DIR, PROJECT_ROOT


def _ensure_local_encryption_key() -> None:
    if os.getenv("AI_CREDENTIALS_ENCRYPTION_KEY"):
        return
    key_path = BACKEND_DIR / ".ai-credentials.key"
    if key_path.exists():
        encoded_key = key_path.read_text(encoding="ascii").strip()
    else:
        encoded_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        try:
            descriptor = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            encoded_key = key_path.read_text(encoding="ascii").strip()
        else:
            with os.fdopen(descriptor, "w", encoding="ascii") as key_file:
                key_file.write(encoded_key)
                key_file.write("\n")
    os.environ["AI_CREDENTIALS_ENCRYPTION_KEY"] = encoded_key


_ensure_local_encryption_key()

# A relative COPILOT_DATA_DIR is resolved against the project root, as in create_app.
DATA_DIR = PROJECT_ROOT / os.environ["COPILOT_DATA_DIR"] if os.getenv("COPILOT_DATA_DIR") else DEFAULT_DATA_DIR

app = create_app(
    data_dir=DATA_DIR,
    db_path=BACKEND_DIR / ".frontend-demo.sqlite3",
    config_path=DEFAULT_CONFIG_PATH,
)