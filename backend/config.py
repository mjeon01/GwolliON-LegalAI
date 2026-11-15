"""Read server-only local configuration without modifying process environment."""
from pathlib import Path
import os
import re


def load_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key.strip()] = value
    return values


def ai_provider() -> str:
    """Translation uses an explicit provider; the presence of a key never opts in."""
    settings = load_env(Path(__file__).resolve().parents[1] / '.env')
    value = os.environ.get('GWOLLION_AI_PROVIDER', settings.get('GWOLLION_AI_PROVIDER', 'ollama')).strip().lower()
    if value not in {'ollama', 'openai'}:
        raise ValueError('GWOLLION_AI_PROVIDER는 ollama 또는 openai여야 합니다.')
    return value
