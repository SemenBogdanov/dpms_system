#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

python3 tools/validate_catalog.py data/competency_catalog.json
python3 tools/validate_catalog.py app/data/competency_catalog.json
cmp -s data/competency_catalog.json app/data/competency_catalog.json || {
  printf '%s\n' "Каталоги вопросов в source и runtime различаются" >&2
  exit 1
}

python3 - <<'PY'
import hashlib
import json
from pathlib import Path

manifest = json.loads(Path("MANIFEST.json").read_text(encoding="utf-8"))
catalog = Path("data/competency_catalog.json").read_bytes()
payload = json.loads(catalog)
competencies = payload["competencies"]
questions = [q for item in competencies for q in item["questions"]]
choices = [choice for question in questions for choice in question["choices"]]
interpretations = [value for item in competencies for value in item["interpretations"]]
actual = {
    "sha256": hashlib.sha256(catalog).hexdigest(),
    "competencies": len(competencies),
    "questions": len(questions),
    "choices": len(choices),
    "interpretations": len(interpretations),
}
if actual != manifest["catalog"]:
    raise SystemExit(f"MANIFEST.json не совпадает с каталогом: {actual!r}")
PY

if [ -f CHECKSUMS.sha256 ]; then
  python3 - <<'PY'
import hashlib
from pathlib import Path

for raw_line in Path("CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
    if not raw_line.strip():
        continue
    expected, relative = raw_line.split("  ", 1)
    path = Path(relative)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"Контрольная сумма не совпала: {relative}")
PY
fi

printf '%s\n' "Пакет проверен: каталог вопросов не содержит пользователей и ответов."
