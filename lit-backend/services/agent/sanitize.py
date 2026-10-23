"""
Streaming sanitiser for LLM text.

1. Drops citation handles ([P#] / [S#]) that no tool issued, as the text streams — so a user can never click a
   citation that points at nothing. (The check used to be after the fact; by then the text is on screen.)
2. Normalises the typographic spaces and hyphens some models emit inside names ("Ramesh<NNBSP>Kumar"), which break
   copy-and-paste and later search.

It holds back at most a few characters (an unclosed '[') so streaming stays smooth.
"""

import re
from typing import List, Set

_HANDLE = re.compile(r"^[PS]\s*\d{1,2}$")
_MAX_BRACKET = 10
_MAP = {
    "\N{NARROW NO-BREAK SPACE}": " ", "\N{NO-BREAK SPACE}": " ", "\N{THIN SPACE}": " ", "\N{FIGURE SPACE}": " ",
    "\N{NON-BREAKING HYPHEN}": "-",
    # full-width brackets some models use for citations (e.g. 【S1】) are mapped to ASCII so they are checked like any other
    "\N{LEFT BLACK LENTICULAR BRACKET}": "[", "\N{RIGHT BLACK LENTICULAR BRACKET}": "]",
    "\N{FULLWIDTH LEFT SQUARE BRACKET}": "[", "\N{FULLWIDTH RIGHT SQUARE BRACKET}": "]",
}


class StreamSanitizer:
    def __init__(self, issued: Set[str]) -> None:
        self.issued = issued
        self._buf = ""        # an open '[...' being examined
        self.dropped: List[str] = []

    def _close(self) -> str:
        inner = self._buf[1:-1].strip()
        buf, self._buf = self._buf, ""
        if _HANDLE.match(inner):
            handle = inner.replace(" ", "")
            if handle in self.issued:
                return f"[{handle}]"
            self.dropped.append(handle)
            return ""
        return buf

    def feed(self, delta: str) -> str:
        out: List[str] = []
        for ch in delta:
            ch = _MAP.get(ch, ch)
            if self._buf:
                self._buf += ch
                if ch == "]":
                    out.append(self._close())
                elif len(self._buf) > _MAX_BRACKET or ch == "\n":
                    out.append(self._buf)
                    self._buf = ""
            elif ch == "[":
                self._buf = "["
            else:
                out.append(ch)
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        return rest
