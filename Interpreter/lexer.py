from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


KEYWORDS = {
	"Frame",
	"int",
	"color",
	"pixel",
	"bool",
	"string",
	"list",
	"None",
	"true",
	"false",
	"none",
	"Do",
	"Publish",
	"return",
	"While",
	"For",
	"in",
	"if",
	"and",
	"or",
	"xor",
	"not",
}

MULTI_CHAR = ["!?", "==", "<=", ">=", "->", "=>"]
SINGLE_CHAR = set("(){}[]<>:.,?!=+-*|&~")


@dataclass(frozen=True)
class Token:
	type: str
	value: str | int
	line: int
	col: int

	def __repr__(self) -> str:
		return f"Token({self.type}, {self.value!r}, {self.line}:{self.col})"


def lex_file(path: str | Path) -> list[Token]:
	return lex_source(Path(path).read_text(encoding="utf-8"))


def lex_source(source: str) -> list[Token]:
	tokens: list[Token] = []
	i = 0
	line = 1
	col = 1

	def advance(n: int = 1) -> None:
		nonlocal i, line, col
		for _ in range(n):
			if i >= len(source):
				return
			ch = source[i]
			i += 1
			if ch == "\n":
				line += 1
				col = 1
			else:
				col += 1

	def peek(n: int = 0) -> str:
		idx = i + n
		if idx >= len(source):
			return ""
		return source[idx]

	def add_token(ttype: str, value: str | int, start_line: int, start_col: int) -> None:
		tokens.append(Token(ttype, value, start_line, start_col))

	while i < len(source):
		ch = peek()

		if ch.isspace():
			advance(1)
			continue

		if ch == "%":
			# skip comment block % ... %
			advance(1)
			while i < len(source) and peek() != "%":
				advance(1)
			if peek() == "%":
				advance(1)
			continue

		start_line, start_col = line, col

		# string literals
		if ch in {"\"", "'"}:
			quote = ch
			advance(1)
			buf: list[str] = []
			while i < len(source):
				c = peek()
				if c == "\\":
					advance(1)
					esc = peek()
					mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "\"": "\"", "'": "'"}
					buf.append(mapping.get(esc, esc))
					advance(1)
					continue
				if c == quote:
					advance(1)
					break
				buf.append(c)
				advance(1)
			add_token("STRING", "".join(buf), start_line, start_col)
			continue

		# integers
		if ch.isdigit():
			buf = [ch]
			advance(1)
			while peek().isdigit():
				buf.append(peek())
				advance(1)
			add_token("INT", int("".join(buf)), start_line, start_col)
			continue

		# identifiers / keywords
		if ch.isalpha() or ch == "_":
			buf = [ch]
			advance(1)
			while (peek().isalnum() or peek() == "_"):
				buf.append(peek())
				advance(1)
			text = "".join(buf)
			if text in KEYWORDS:
				add_token("KW", text, start_line, start_col)
			else:
				add_token("IDENT", text, start_line, start_col)
			continue

		# multi-char operators
		matched = False
		for op in MULTI_CHAR:
			if source.startswith(op, i):
				add_token("SYM", op, start_line, start_col)
				advance(len(op))
				matched = True
				break
		if matched:
			continue

		# single-char symbols
		if ch in SINGLE_CHAR:
			add_token("SYM", ch, start_line, start_col)
			advance(1)
			continue

		raise SyntaxError(f"Unexpected character {ch!r} at {line}:{col}")

	add_token("EOF", "EOF", line, col)
	return tokens


if __name__ == "__main__":
	repo_root = Path(__file__).resolve().parents[1]
	qgk_path = repo_root / "test.qgk"
	if qgk_path.exists():
		print(lex_file(qgk_path))
