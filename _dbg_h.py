from pathlib import Path
text = Path(".ai/DIRECT_LLM_VS_AIPS_BENCHMARK.md").read_text(encoding="utf-8")
import re
for m in re.finditer(r"\bH\d\b", text):
    s = max(0, m.start() - 40)
    e = min(len(text), m.end() + 40)
    print(repr(text[s:e]))