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


# --- one-line answers -------------------------------------------------------------------------------------------------
# Words that end in a full stop without ending the sentence ("State v. Rajasthan", "Sec. 302", "Dr. Sharma").
_ABBREV = {"v", "vs", "no", "nos", "sec", "secs", "s", "ss", "art", "cl", "ch", "dr", "mr", "mrs", "ms", "shri", "smt", "ltd", "pvt", "co",
           "ors", "anr", "etc", "viz", "cf", "i.e", "e.g", "hon", "hc", "sc", "ipc", "crpc", "pw", "dw", "w", "u"}
_TRAILING_HANDLES = re.compile(r"(?:\s*\[[PS]\s*\d{1,2}\])+")


def one_sentence(text: str, max_words: int = 40) -> str:
    """The first sentence of `text` (with any citation handles that follow it), capped at `max_words`.

    The model is asked for one sentence when a user asks for a one-liner; this makes it true even if the model rambles."""
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"^(?:[#>*\-\u2022]+\s*)+", "", t)
    end = len(t)
    for m in re.finditer(r"[.!?]", t):
        i = m.start()
        before = re.search(r"([A-Za-z.]+)$", t[:i])
        if before and before.group(1).lower().rstrip(".") in _ABBREV:
            continue
        rest = t[i + 1:]
        h = _TRAILING_HANDLES.match(rest)
        after = rest[h.end():] if h else rest
        if after == "" or (after[:1] == " " and re.match(r"\s*[A-Z0-9\u201c\"'(\[]", after)):
            end = i + 1 + (h.end() if h else 0)
            break
    out = t[:end].strip()
    words = out.split(" ")
    if len(words) > max_words:
        return " ".join(words[:max_words]).rstrip(",;:\u2014- ") + "\u2026"
    # tidy: a space before citation handles, handles before the full stop, and a full stop at the end ("delay[S3]" -> "delay [S3].")
    handles = "".join(re.sub(r"\s+", "", h) for h in re.findall(r"\[[PS]\s*\d{1,2}\]", out))
    body = re.sub(r"\s*\[[PS]\s*\d{1,2}\]", "", out).strip()
    stop = body[-1] if body and body[-1] in ".!?" else "."
    return body.rstrip(".!? ") + (f" {handles}" if handles else "") + stop
