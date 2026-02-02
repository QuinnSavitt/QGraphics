from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Engine.engine import Frame

from .lexer import Token, lex_file, lex_source
from .parser import (
	Assign,
	BinaryOp,
	CallExpr,
	ColorLit,
	ExprStmt,
	ForStmt,
	FunctionDecl,
	IfStmt,
	IndexExpr,
	ListLit,
	Literal,
	ParseError,
	ParenExpr,
	PixelAssign,
	PixelLit,
	Program,
	PublishStmt,
	ReturnStmt,
	UnaryOp,
	Var,
	VarDecl,
	WalrusAssign,
	WalrusDecl,
	WhileStmt,
	parse,
)


TYPE_DEFAULTS = {
	"Frame": lambda: Frame(),
	"int": lambda: 0,
	"color": lambda: (0, 0, 0),
	"pixel": lambda: (0, 0),
	"bool": lambda: False,
	"string": lambda: "",
	"list": lambda: [],
	"None": lambda: None,
}


class RuntimeErrorWithLine(RuntimeError):
	def __init__(self, message: str, line: int) -> None:
		super().__init__(f"Line {line}: {message}")
		self.line = line


class ReturnSignal(Exception):
	def __init__(self, value: Any) -> None:
		self.value = value


@dataclass
class PixelRef:
	frame: Frame
	x: int
	y: int


@dataclass
class FunctionValue:
	decl: FunctionDecl
	closure: "Environment"


class Environment:
	def __init__(self, parent: Optional["Environment"] = None) -> None:
		self.parent = parent
		self.values: Dict[str, Any] = {}

	def define(self, name: str, value: Any) -> None:
		self.values[name] = value

	def set(self, name: str, value: Any) -> None:
		if name in self.values:
			self.values[name] = value
			return
		if self.parent:
			self.parent.set(name, value)
			return
		raise NameError(f"Undefined variable {name}")

	def get(self, name: str) -> Any:
		if name in self.values:
			return self.values[name]
		if self.parent:
			return self.parent.get(name)
		raise NameError(f"Undefined variable {name}")


class Interpreter:
	def __init__(self) -> None:
		self.globals = Environment()
		self._install_builtins()

	def _install_builtins(self) -> None:
		self.globals.define("Frame", self._builtin_frame)
		self.globals.define("setRed", self._builtin_set_red)
		self.globals.define("setGreen", self._builtin_set_green)
		self.globals.define("setBlue", self._builtin_set_blue)
		self.globals.define("setColor", self._builtin_set_color)

	def run_file(self, path: str | Path) -> None:
		tokens = lex_file(path)
		program = parse(tokens)
		self.execute_program(program)

	def run_source(self, source: str) -> None:
		program = parse(lex_source(source))
		self.execute_program(program)

	def execute_program(self, program: Program) -> None:
		# Pre-register functions (forward references allowed)
		for item in program.items:
			if isinstance(item, FunctionDecl):
				self.globals.define(item.name, FunctionValue(item, self.globals))

		for item in program.items:
			if isinstance(item, FunctionDecl):
				continue
			try:
				self.execute_stmt(item, self.globals)
			except RuntimeErrorWithLine:
				raise
			except Exception as exc:
				line = getattr(item, "line", -1)
				raise RuntimeErrorWithLine(str(exc), line) from exc

	def execute_stmt(self, stmt: Any, env: Environment) -> None:
		if isinstance(stmt, VarDecl):
			value = self.eval_expr(stmt.value, env) if stmt.value else TYPE_DEFAULTS[stmt.type_name]()
			env.define(stmt.name, value)
			return
		if isinstance(stmt, Assign):
			value = self.eval_expr(stmt.value, env)
			self.assign_target(stmt.target, value, env, stmt.line)
			return
		if isinstance(stmt, PixelAssign):
			value = self.eval_expr(stmt.value, env)
			ptr = self.eval_expr(stmt.pointer, env)
			self.assign_pixel(ptr, value, stmt.line)
			return
		if isinstance(stmt, PublishStmt):
			value = self.eval_expr(stmt.expr, env)
			self.publish(value)
			return
		if isinstance(stmt, ReturnStmt):
			value = self.eval_expr(stmt.expr, env) if stmt.expr else None
			raise ReturnSignal(value)
		if isinstance(stmt, ExprStmt):
			self.eval_expr(stmt.expr, env)
			return
		if isinstance(stmt, IfStmt):
			cond = self.eval_expr(stmt.condition, env)
			if cond:
				self.execute_block(stmt.then_body, env)
			elif stmt.else_body is not None:
				self.execute_block(stmt.else_body, env)
			return
		if isinstance(stmt, WhileStmt):
			while self.eval_expr(stmt.condition, env):
				self.execute_block(stmt.body, env)
			return
		if isinstance(stmt, ForStmt):
			iterable = self.eval_expr(stmt.iterable, env)
			if not isinstance(iterable, list):
				raise RuntimeErrorWithLine("For loop requires a list iterable", stmt.line)
			for item in iterable:
				loop_env = Environment(env)
				loop_env.define(stmt.var_name, item)
				self.execute_block(stmt.body, loop_env)
			return
		raise RuntimeErrorWithLine(f"Unknown statement {stmt}", getattr(stmt, "line", -1))

	def execute_block(self, stmts: List[Any], env: Environment) -> None:
		for stmt in stmts:
			self.execute_stmt(stmt, env)

	def eval_expr(self, expr: Any, env: Environment) -> Any:
		if expr is None:
			return None
		if isinstance(expr, Literal):
			return expr.value
		if isinstance(expr, Var):
			return env.get(expr.name)
		if isinstance(expr, UnaryOp):
			value = self.eval_expr(expr.expr, env)
			return self.eval_unary(expr.op, value, expr.line)
		if isinstance(expr, BinaryOp):
			left = self.eval_expr(expr.left, env)
			right = self.eval_expr(expr.right, env)
			return self.eval_binary(expr.op, left, right, expr.line)
		if isinstance(expr, IndexExpr):
			base = self.eval_expr(expr.base, env)
			idx = self.eval_expr(expr.index, env)
			if not isinstance(idx, int):
				raise RuntimeErrorWithLine("Index must be int", expr.line)
			return base[idx]
		if isinstance(expr, CallExpr):
			args = [self.eval_expr(a, env) for a in expr.args]
			return self.call_function(expr.name, args, expr.line, env)
		if isinstance(expr, ColorLit):
			r = self.eval_expr(expr.r, env)
			g = self.eval_expr(expr.g, env)
			b = self.eval_expr(expr.b, env)
			return (r, g, b)
		if isinstance(expr, PixelLit):
			x = self.eval_expr(expr.x, env)
			y = self.eval_expr(expr.y, env)
			return (x, y)
		if isinstance(expr, ListLit):
			return [self.eval_expr(i, env) for i in expr.items]
		if isinstance(expr, ParenExpr):
			return self.eval_expr(expr.expr, env)
		if isinstance(expr, WalrusAssign):
			value = self.eval_expr(expr.expr, env)
			env.set(expr.name, value)
			return value
		if isinstance(expr, WalrusDecl):
			value = self.eval_expr(expr.expr, env)
			env.define(expr.name, value)
			return value
		raise RuntimeErrorWithLine(f"Unknown expression {expr}", getattr(expr, "line", -1))

	def eval_unary(self, op: str, value: Any, line: int) -> Any:
		if op == "not":
			return not value
		if op == "~":
			if not isinstance(value, int):
				raise RuntimeErrorWithLine("Bitwise ~ requires int", line)
			return self._mask_int(~value)
		if op == "-":
			return -value
		raise RuntimeErrorWithLine(f"Unknown unary operator {op}", line)

	def eval_binary(self, op: str, left: Any, right: Any, line: int) -> Any:
		if op == "->":
			if isinstance(left, Frame) and isinstance(right, tuple) and len(right) == 2:
				x, y = right
				return PixelRef(left, x, y)
			raise RuntimeErrorWithLine("Invalid pointer expression", line)
		if op == "+":
			return left + right
		if op == "-":
			return left - right
		if op == "*":
			return left * right
		if op == "==":
			return left == right
		if op == "<":
			return left < right
		if op == ">":
			return left > right
		if op == "<=":
			return left <= right
		if op == ">=":
			return left >= right
		if op == "and":
			return left and right
		if op == "or":
			return left or right
		if op == "xor":
			return bool(left) ^ bool(right)
		if op == "|":
			if not isinstance(left, int) or not isinstance(right, int):
				raise RuntimeErrorWithLine("Bitwise | requires ints", line)
			return self._mask_int(left | right)
		if op == "&":
			if not isinstance(left, int) or not isinstance(right, int):
				raise RuntimeErrorWithLine("Bitwise & requires ints", line)
			return self._mask_int(left & right)
		raise RuntimeErrorWithLine(f"Unknown binary operator {op}", line)

	def _mask_int(self, value: int) -> int:
		return value & 0xFFFFFFFF

	def assign_target(self, target: Any, value: Any, env: Environment, line: int) -> None:
		if isinstance(target, Var):
			env.set(target.name, value)
			return
		if isinstance(target, IndexExpr):
			base = self.eval_expr(target.base, env)
			idx = self.eval_expr(target.index, env)
			if not isinstance(idx, int):
				raise RuntimeErrorWithLine("Index must be int", line)
			base[idx] = value
			return
		raise RuntimeErrorWithLine("Invalid assignment target", line)

	def assign_pixel(self, ptr: Any, value: Any, line: int) -> None:
		if not isinstance(ptr, PixelRef):
			raise RuntimeErrorWithLine("Pixel assignment requires frame->pixel", line)
		if not (isinstance(value, tuple) and len(value) == 3):
			raise RuntimeErrorWithLine("Pixel assignment requires color tuple", line)
		r, g, b = value
		ptr.frame.setColor(ptr.x, ptr.y, r, g, b)

	def call_function(self, name: str, args: List[Any], line: int, env: Environment) -> Any:
		fn = env.get(name)
		if callable(fn) and not isinstance(fn, FunctionValue):
			return fn(args, line)
		if isinstance(fn, FunctionValue):
			decl = fn.decl
			call_env = Environment(fn.closure)
			if len(args) != len(decl.params):
				raise RuntimeErrorWithLine("Argument count mismatch", line)
			for param, arg in zip(decl.params, args):
				call_env.define(param.name, arg)
			try:
				self.execute_block(decl.body, call_env)
			except ReturnSignal as rs:
				return rs.value
			return None
		raise RuntimeErrorWithLine(f"Unknown function {name}", line)

	def publish(self, value: Any) -> None:
		if not isinstance(value, Frame):
			raise RuntimeErrorWithLine("Publish expects a Frame", -1)
		try:
			from PyQt5.QtWidgets import QApplication
			from GUI.framedisplayer import LedMatrixWidget
			app = QApplication.instance() or QApplication([])
			widget = LedMatrixWidget(value)
			widget.show()
			app.exec_()
		except Exception as exc:
			raise RuntimeError(f"Failed to publish frame: {exc}") from exc

	def _builtin_set_red(self, args: List[Any], line: int) -> None:
		self._builtin_set_channel(args, line, "red")

	def _builtin_set_green(self, args: List[Any], line: int) -> None:
		self._builtin_set_channel(args, line, "green")

	def _builtin_set_blue(self, args: List[Any], line: int) -> None:
		self._builtin_set_channel(args, line, "blue")

	def _builtin_frame(self, args: List[Any], line: int) -> Frame:
		if args:
			raise RuntimeErrorWithLine("Frame() takes no arguments", line)
		return Frame()

	def _builtin_set_color(self, args: List[Any], line: int) -> None:
		if len(args) != 2:
			raise RuntimeErrorWithLine("setColor requires frame->pixel and color", line)
		ptr, color = args
		if not isinstance(ptr, PixelRef):
			raise RuntimeErrorWithLine("First arg must be frame->pixel", line)
		if not (isinstance(color, tuple) and len(color) == 3):
			raise RuntimeErrorWithLine("Second arg must be color tuple", line)
		r, g, b = color
		ptr.frame.setColor(ptr.x, ptr.y, int(r), int(g), int(b))

	def _builtin_set_channel(self, args: List[Any], line: int, channel: str) -> None:
		if len(args) != 2:
			raise RuntimeErrorWithLine("setColor requires frame->pixel and int", line)
		ptr, value = args
		if not isinstance(ptr, PixelRef):
			raise RuntimeErrorWithLine("First arg must be frame->pixel", line)
		if channel == "red":
			ptr.frame.setRed(ptr.x, ptr.y, int(value))
		elif channel == "green":
			ptr.frame.setGreen(ptr.x, ptr.y, int(value))
		elif channel == "blue":
			ptr.frame.setBlue(ptr.x, ptr.y, int(value))
		else:
			raise RuntimeErrorWithLine("Unknown color channel", line)


def run_file(path: str | Path) -> None:
	Interpreter().run_file(path)


def run_source(source: str) -> None:
	Interpreter().run_source(source)

