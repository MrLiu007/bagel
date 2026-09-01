"""One-off syntax fix helper — paths resolved from this script, never hardcoded."""

from pathlib import Path

p = Path(__file__).resolve().parents[1] / "src" / "bagel" / "web" / "routes" / "health.py"
lines = p.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    stripped = line.rstrip()
    if 'RedirectResponse(url="/settings?tab=papers"' in stripped and not stripped.endswith(")"):
        line = stripped + ")"
    out.append(line)
text = "\n".join(out) + "\n"
p.write_text(text, encoding="utf-8")
print("done", p.name)
