from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from .lexer import Token


# AST Nodes


@dataclass
class Program:
	items: List[object]


@dataclass
class Param:
	type_name: str
	name: str
	line: int


@dataclass
class FunctionDecl:
	name: str
	params: List[Param]
	return_type: str
	body: List[object]
	line: int


@dataclass
class VarDecl:
	type_name: str
	name: str
	value: Optional[object]
	line: int


@dataclass
class Assign:
	target: object
	value: object
	line: int


@dataclass
class PixelAssign:
	pointer: object
	value: object
	line: int


@dataclass
class PublishStmt:
	expr: object
	line: int


@dataclass
class ReturnStmt:
	expr: Optional[object]
	line: int


@dataclass
class ExprStmt:
	expr: object
	line: int


@dataclass
class IfStmt:
	condition: object
	then_body: List[object]
	else_body: Optional[List[object]]
	line: int


@dataclass
class WhileStmt:
	condition: object
	body: List[object]
	line: int


@dataclass
class ForStmt:
	type_name: Optional[str]
	var_name: str
	iterable: object
	body: List[object]
	line: int


# Expressions


@dataclass
class Literal:
	value: object
	line: int


@dataclass
class Var:
	name: str
	line: int


@dataclass
class UnaryOp:
	op: str
	expr: object
	line: int


@dataclass
class BinaryOp:
	op: str
	left: object
	right: object
	line: int


@dataclass
class IndexExpr:
	base: object
	index: object
	line: int


@dataclass
class CallExpr:
	name: str
	args: List[object]
	line: int


@dataclass
class ColorLit:
	r: object
	g: object
	b: object
	line: int


@dataclass
class PixelLit:
	x: object
	y: object
	line: int


@dataclass
class ListLit:
	items: List[object]
	line: int


@dataclass
class ParenExpr:
	expr: object
	line: int


@dataclass
class WalrusAssign:
	name: str
	expr: object
	line: int


@dataclass
class WalrusDecl:
	type_name: str
	name: str
	expr: object
	line: int


TYPE_KEYWORDS = {"Frame", "int", "color", "pixel", "bool", "string", "list", "None"}


class ParseError(Exception):
	pass


class Parser:
	def __init__(self, tokens: Sequence[Token]) -> None:
		self.tokens = list(tokens)
		self.pos = 0

	def current(self) -> Token:
		return self.tokens[self.pos]

	def advance(self) -> Token:
		cur = self.current()
		self.pos += 1
		return cur

	def match_value(self, value: str) -> bool:
		if self.current().value == value:
			self.advance()
			return True
		return False

	def expect_value(self, value: str) -> Token:
		if self.current().value != value:
			raise ParseError(f"Expected {value!r} at line {self.current().line}")
		return self.advance()

	def match_type(self, ttype: str) -> Optional[Token]:
		if self.current().type == ttype:
			return self.advance()
		return None

	def parse_program(self) -> Program:
		items: List[object] = []
		while self.current().type != "EOF":
			if self._is_function_decl():
				items.append(self.parse_function_decl())
			else:
				items.append(self.parse_statement())
		return Program(items)

	def _is_function_decl(self) -> bool:
		if self.current().type != "IDENT":
			return False
		if self._peek_value(1) != "{":
			return False
		# look ahead for "}" then "=>"
		depth = 0
		for i in range(self.pos, len(self.tokens)):
			val = self.tokens[i].value
			if val == "{":
				depth += 1
			elif val == "}":
				depth -= 1
				if depth == 0:
					return self._peek_value(i - self.pos + 1) == "=>"
		return False

	def _peek_value(self, offset: int) -> str:
		idx = self.pos + offset
		if idx >= len(self.tokens):
			return ""
		return str(self.tokens[idx].value)

	def parse_function_decl(self) -> FunctionDecl:
		name_tok = self.expect_type("IDENT")
		self.expect_value("{")
		params: List[Param] = []
		if self.current().value != "}":
			params = self.parse_param_list()
		self.expect_value("}")
		self.expect_value("=>")
		ret_type = self.parse_type_name()
		self.expect_value(":")
		body = self.parse_block_end()
		return FunctionDecl(name_tok.value, params, ret_type, body, name_tok.line)

	def parse_param_list(self) -> List[Param]:
		params: List[Param] = []
		while True:
			ptype = self.parse_type_name()
			name_tok = self.expect_type("IDENT")
			params.append(Param(ptype, name_tok.value, name_tok.line))
			if self.current().value in {"}", "=>"}:
				break
		return params

	def parse_block_end(self) -> List[object]:
		stmts: List[object] = []
		while self.current().value != "!":
			stmts.append(self.parse_statement())
		self.expect_value("!")
		return stmts

	def parse_statement(self) -> object:
		cur = self.current()
		if cur.value == "if" or self._looks_like_if():
			return self.parse_if_stmt()
		if cur.value == "While":
			return self.parse_while_stmt()
		if cur.value == "For":
			return self.parse_for_stmt()
		stmt = self.parse_simple_stmt()
		self.expect_value(".")
		return stmt

	def parse_simple_stmt(self) -> object:
		cur = self.current()
		if cur.value in TYPE_KEYWORDS:
			return self.parse_var_decl()
		if cur.value == "Publish":
			return self.parse_publish_stmt()
		if cur.value == "return":
			return self.parse_return_stmt()
		return self.parse_assignment_or_expr()

	def parse_var_decl(self) -> VarDecl:
		type_name = self.parse_type_name()
		name_tok = self.expect_type("IDENT")
		value = None
		if self.match_value("="):
			value = self.parse_expr()
		return VarDecl(type_name, name_tok.value, value, name_tok.line)

	def parse_publish_stmt(self) -> PublishStmt:
		tok = self.expect_value("Publish")
		expr = self.parse_expr()
		return PublishStmt(expr, tok.line)

	def parse_return_stmt(self) -> ReturnStmt:
		tok = self.expect_value("return")
		expr = None
		if self.match_value("("):
			expr = self.parse_expr()
			self.expect_value(")")
		return ReturnStmt(expr, tok.line)

	def parse_assignment_or_expr(self) -> object:
		start_pos = self.pos
		expr = self.parse_pointer_expr()
		if self.match_value("="):
			value = self.parse_expr()
			if isinstance(expr, (Var, IndexExpr)):
				return Assign(expr, value, self.tokens[start_pos].line)
			if isinstance(expr, BinaryOp) and expr.op == "->":
				return PixelAssign(expr, value, self.tokens[start_pos].line)
			raise ParseError(f"Invalid assignment target at line {self.tokens[start_pos].line}")
		return ExprStmt(expr, self.tokens[start_pos].line)

	def parse_if_stmt(self) -> IfStmt:
		line = self.current().line
		if self.current().value == "if":
			self.advance()
		self.expect_value("(")
		cond = self.parse_expr()
		self.expect_value(")")
		self.expect_value("?")
		then_body = self.parse_block_body(stop_values={"!?", "!"})
		else_body = None
		if self.match_value("!?"):
			else_body = self.parse_block_body(stop_values={"!"})
		self.expect_value("!")
		return IfStmt(cond, then_body, else_body, line)

	def parse_block_body(self, stop_values: set[str]) -> List[object]:
		stmts: List[object] = []
		while self.current().value not in stop_values:
			stmts.append(self.parse_statement())
		return stmts

	def parse_while_stmt(self) -> WhileStmt:
		line = self.current().line
		self.expect_value("While")
		self.expect_value("(")
		cond = self.parse_expr()
		self.expect_value(")")
		body = self.parse_block_end()
		return WhileStmt(cond, body, line)

	def parse_for_stmt(self) -> ForStmt:
		line = self.current().line
		self.expect_value("For")
		type_name = None
		if self.current().value in TYPE_KEYWORDS:
			type_name = self.parse_type_name()
		var_tok = self.expect_type("IDENT")
		self.expect_value("in")
		iterable = self.parse_expr()
		self.expect_value(":")
		body = self.parse_block_end()
		return ForStmt(type_name, var_tok.value, iterable, body, line)

	def parse_type_name(self) -> str:
		cur = self.current()
		if cur.value not in TYPE_KEYWORDS:
			raise ParseError(f"Expected type name at line {cur.line}")
		self.advance()
		return str(cur.value)

	def parse_expr(self) -> object:
		return self.parse_pointer_expr()

	def parse_pointer_expr(self) -> object:
		left = self.parse_bool_expr()
		while self.match_value("->"):
			right = self.parse_bool_expr()
			left = BinaryOp("->", left, right, self.current().line)
		return left

	def parse_bool_expr(self) -> object:
		left = self.parse_compare_expr()
		while self.current().value in {"and", "or", "xor"}:
			op = str(self.advance().value)
			right = self.parse_compare_expr()
			left = BinaryOp(op, left, right, self.current().line)
		return left

	def parse_compare_expr(self) -> object:
		left = self.parse_bitor_expr()
		if self.current().value in {"==", "<", ">", "<=", ">="}:
			op = str(self.advance().value)
			right = self.parse_bitor_expr()
			return BinaryOp(op, left, right, self.current().line)
		return left

	def parse_bitor_expr(self) -> object:
		left = self.parse_bitand_expr()
		while self.match_value("|"):
			right = self.parse_bitand_expr()
			left = BinaryOp("|", left, right, self.current().line)
		return left

	def parse_bitand_expr(self) -> object:
		left = self.parse_add_expr()
		while self.match_value("&"):
			right = self.parse_add_expr()
			left = BinaryOp("&", left, right, self.current().line)
		return left

	def parse_add_expr(self) -> object:
		left = self.parse_mul_expr()
		while self.current().value in {"+", "-"}:
			op = str(self.advance().value)
			right = self.parse_mul_expr()
			left = BinaryOp(op, left, right, self.current().line)
		return left

	def parse_mul_expr(self) -> object:
		left = self.parse_unary_expr()
		while self.match_value("*"):
			right = self.parse_unary_expr()
			left = BinaryOp("*", left, right, self.current().line)
		return left

	def parse_unary_expr(self) -> object:
		if self.current().value in {"not", "~", "-"}:
			op = str(self.advance().value)
			expr = self.parse_unary_expr()
			return UnaryOp(op, expr, self.current().line)
		return self.parse_postfix_expr()

	def parse_postfix_expr(self) -> object:
		expr = self.parse_primary_expr()
		while self.current().value == "<":
			saved = self.pos
			try:
				self.expect_value("<")
				index = self.parse_index_expr()
				self.expect_value(">")
				expr = IndexExpr(expr, index, self.current().line)
			except ParseError:
				self.pos = saved
				break
		return expr

	def parse_index_expr(self) -> object:
		# Index expressions should not consume the closing '>' as a comparison op.
		return self.parse_bitor_expr()

	def parse_primary_expr(self) -> object:
		cur = self.current()
		if cur.value in TYPE_KEYWORDS and self._peek_value(1) == "(" and self._peek_value(2) == ")":
			name = str(cur.value)
			line = cur.line
			self.advance()
			self.expect_value("(")
			self.expect_value(")")
			return CallExpr(name, [], line)
		if cur.type == "INT":
			self.advance()
			return Literal(cur.value, cur.line)
		if cur.type == "STRING":
			self.advance()
			return Literal(cur.value, cur.line)
		if cur.value in {"true", "false", "none"}:
			self.advance()
			val = True if cur.value == "true" else False if cur.value == "false" else None
			return Literal(val, cur.line)
		if cur.value == "Do":
			return self.parse_call_expr()
		if cur.type == "IDENT":
			name_tok = self.advance()
			if self.current().value == "{":
				return self.parse_brace_call(name_tok)
			return Var(str(name_tok.value), name_tok.line)
		if cur.value == "[":
			return self.parse_list_lit()
		if cur.value == "(":
			return self.parse_paren_expr()
		raise ParseError(f"Unexpected token {cur.value!r} at line {cur.line}")

	def parse_call_expr(self) -> CallExpr:
		tok = self.expect_value("Do")
		name_tok = self.expect_type("IDENT")
		return self.parse_brace_call(name_tok, tok.line)

	def parse_brace_call(self, name_tok: Token, line_override: int | None = None) -> CallExpr:
		line = line_override if line_override is not None else name_tok.line
		self.expect_value("{")
		args: List[object] = []
		if self.current().value != "}":
			args = self.parse_arg_list()
		self.expect_value("}")
		return CallExpr(str(name_tok.value), args, line)

	def parse_arg_list(self) -> List[object]:
		args: List[object] = []
		while self.current().value != "}":
			args.append(self.parse_expr())
			if self.current().value == "}":
				break
		return args

	def parse_list_lit(self) -> ListLit:
		line = self.current().line
		self.expect_value("[")
		items: List[object] = []
		while self.current().value != "]":
			items.append(self.parse_expr())
		self.expect_value("]")
		return ListLit(items, line)

	def parse_paren_expr(self) -> object:
		line = self.current().line
		self.expect_value("(")
		# walrus-style typed declaration
		if (
			self.current().value in TYPE_KEYWORDS
			and self._peek_type(1) == "IDENT"
			and self._peek_value(2) == "="
		):
			type_name = self.parse_type_name()
			name_tok = self.expect_type("IDENT")
			self.expect_value("=")
			expr = self.parse_expr()
			self.expect_value(")")
			return WalrusDecl(type_name, str(name_tok.value), expr, line)
		# walrus assignment
		if self.current().type == "IDENT" and self._peek_value(1) == "=":
			name_tok = self.expect_type("IDENT")
			self.expect_value("=")
			expr = self.parse_expr()
			self.expect_value(")")
			return WalrusAssign(str(name_tok.value), expr, line)

		expr1 = self.parse_expr()
		if self.match_value(")"):
			return ParenExpr(expr1, line)
		expr2 = self.parse_expr()
		if self.match_value(")"):
			return PixelLit(expr1, expr2, line)
		expr3 = self.parse_expr()
		self.expect_value(")")
		return ColorLit(expr1, expr2, expr3, line)

	def _looks_like_if(self) -> bool:
		# Detect pattern: "(" Expr ")" "?" without consuming
		if self.current().value != "(":
			return False
		depth = 0
		for i in range(self.pos, len(self.tokens)):
			val = self.tokens[i].value
			if val == "(":
				depth += 1
			elif val == ")":
				depth -= 1
				if depth == 0:
					return self._peek_value(i - self.pos + 1) == "?"
		return False

	def _peek_type(self, offset: int) -> str:
		idx = self.pos + offset
		if idx >= len(self.tokens):
			return ""
		return str(self.tokens[idx].type)

	def expect_type(self, ttype: str) -> Token:
		tok = self.match_type(ttype)
		if not tok:
			raise ParseError(f"Expected {ttype} at line {self.current().line}")
		return tok


def parse(tokens: Sequence[Token]) -> Program:
	return Parser(tokens).parse_program()
