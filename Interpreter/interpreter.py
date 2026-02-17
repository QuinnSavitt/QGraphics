from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

from Engine.engine import Frame, loadQGC, saveQGC

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
	SendStmt,
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


@dataclass
class StepInfo:
	line: int
	stmt: Any


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
	def __init__(
		self,
		publish_handler: Optional[Callable[[Frame], None]] = None,
		send_handler: Optional[Callable[[str], None]] = None,
	) -> None:
		self.globals = Environment()
		self._install_builtins()
		self.publish_handler = publish_handler
		self.send_handler = send_handler
		self._statement_end_handler: Optional[Callable[[Frame], None]] = None
		self._last_modified_frame: Optional[Frame] = None

	def _install_builtins(self) -> None:
		self.globals.define("Frame", self._builtin_frame)
		self.globals.define("setRed", self._builtin_set_red)
		self.globals.define("setGreen", self._builtin_set_green)
		self.globals.define("setBlue", self._builtin_set_blue)
		self.globals.define("setColor", self._builtin_set_color)
		self.globals.define("getPixel", self._builtin_get_pixel)
		self.globals.define("getRed", self._builtin_get_red)
		self.globals.define("getGreen", self._builtin_get_green)
		self.globals.define("getBlue", self._builtin_get_blue)
		self.globals.define("makeRect", self._builtin_make_rect)
		self.globals.define("makeLine", self._builtin_make_line)
		self.globals.define("Fill", self._builtin_fill)
		self.globals.define("makeOval", self._builtin_make_oval)
		self.globals.define("makeCurve", self._builtin_make_curve)
		self.globals.define("LoadQGC", self._builtin_load_qgc)
		self.globals.define("SaveQGC", self._builtin_save_qgc)

	def run_file(self, path: str | Path) -> None:
		tokens = lex_file(path)
		program = parse(tokens)
		self.execute_program(program)

	def run_source(self, source: str) -> None:
		program = parse(lex_source(source))
		self.execute_program(program)

	def run_source_steps(
		self,
		source: str,
		statement_end_handler: Optional[Callable[[Frame], None]] = None,
	) -> "Generator[StepInfo, None, None]":
		self._statement_end_handler = statement_end_handler
		program = parse(lex_source(source))
		return self.execute_program_steps(program)

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
			value = self.eval_expr(stmt.value, env) if stmt.value else self._default_value(stmt.type_name)
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
		if isinstance(stmt, SendStmt):
			value = self.eval_expr(stmt.expr, env)
			self.send(value)
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

	def execute_program_steps(self, program: Program) -> "Generator[StepInfo, None, None]":
		for item in program.items:
			if isinstance(item, FunctionDecl):
				self.globals.define(item.name, FunctionValue(item, self.globals))

		for item in program.items:
			if isinstance(item, FunctionDecl):
				continue
			try:
				yield from self.execute_stmt_steps(item, self.globals)
			except RuntimeErrorWithLine:
				raise
			except Exception as exc:
				line = getattr(item, "line", -1)
				raise RuntimeErrorWithLine(str(exc), line) from exc

	def execute_block_steps(self, stmts: List[Any], env: Environment) -> "Generator[StepInfo, None, None]":
		for stmt in stmts:
			yield from self.execute_stmt_steps(stmt, env)

	def execute_stmt_steps(self, stmt: Any, env: Environment) -> "Generator[StepInfo, None, None]":
		if isinstance(stmt, IfStmt):
			yield StepInfo(stmt.line, stmt)
			cond = yield from self.eval_expr_steps(stmt.condition, env)
			if cond:
				yield from self.execute_block_steps(stmt.then_body, env)
			elif stmt.else_body is not None:
				yield from self.execute_block_steps(stmt.else_body, env)
			return
		if isinstance(stmt, WhileStmt):
			while True:
				yield StepInfo(stmt.line, stmt)
				cond = yield from self.eval_expr_steps(stmt.condition, env)
				if not cond:
					break
				yield from self.execute_block_steps(stmt.body, env)
			return
		if isinstance(stmt, ForStmt):
			iterable = yield from self.eval_expr_steps(stmt.iterable, env)
			if not isinstance(iterable, list):
				raise RuntimeErrorWithLine("For loop requires a list iterable", stmt.line)
			for item in iterable:
				yield StepInfo(stmt.line, stmt)
				loop_env = Environment(env)
				loop_env.define(stmt.var_name, item)
				yield from self.execute_block_steps(stmt.body, loop_env)
			return

		yield StepInfo(getattr(stmt, "line", -1), stmt)
		self._reset_statement_frame()
		if isinstance(stmt, VarDecl):
			value = (yield from self.eval_expr_steps(stmt.value, env)) if stmt.value else self._default_value(stmt.type_name)
			env.define(stmt.name, value)
			self._emit_statement_frame()
			return
		if isinstance(stmt, Assign):
			value = yield from self.eval_expr_steps(stmt.value, env)
			self.assign_target(stmt.target, value, env, stmt.line)
			self._emit_statement_frame()
			return
		if isinstance(stmt, PixelAssign):
			value = yield from self.eval_expr_steps(stmt.value, env)
			ptr = yield from self.eval_expr_steps(stmt.pointer, env)
			self.assign_pixel(ptr, value, stmt.line)
			self._emit_statement_frame()
			return
		if isinstance(stmt, PublishStmt):
			value = yield from self.eval_expr_steps(stmt.expr, env)
			self.publish(value)
			self._emit_statement_frame()
			return
		if isinstance(stmt, SendStmt):
			value = yield from self.eval_expr_steps(stmt.expr, env)
			self.send(value)
			self._emit_statement_frame()
			return
		if isinstance(stmt, ReturnStmt):
			value = (yield from self.eval_expr_steps(stmt.expr, env)) if stmt.expr else None
			self._emit_statement_frame()
			raise ReturnSignal(value)
		if isinstance(stmt, ExprStmt):
			yield from self.eval_expr_steps(stmt.expr, env)
			self._emit_statement_frame()
			return
		raise RuntimeErrorWithLine(f"Unknown statement {stmt}", getattr(stmt, "line", -1))

	def eval_expr_steps(self, expr: Any, env: Environment) -> "Generator[StepInfo, None, Any]":
		if expr is None:
			return None
		if isinstance(expr, Literal):
			return expr.value
		if isinstance(expr, Var):
			return env.get(expr.name)
		if isinstance(expr, UnaryOp):
			value = yield from self.eval_expr_steps(expr.expr, env)
			return self.eval_unary(expr.op, value, expr.line)
		if isinstance(expr, BinaryOp):
			left = yield from self.eval_expr_steps(expr.left, env)
			right = yield from self.eval_expr_steps(expr.right, env)
			return self.eval_binary(expr.op, left, right, expr.line)
		if isinstance(expr, IndexExpr):
			base = yield from self.eval_expr_steps(expr.base, env)
			idx = yield from self.eval_expr_steps(expr.index, env)
			if not isinstance(idx, int):
				raise RuntimeErrorWithLine("Index must be int", expr.line)
			return base[idx]
		if isinstance(expr, CallExpr):
			args: List[Any] = []
			for arg in expr.args:
				args.append((yield from self.eval_expr_steps(arg, env)))
			return (yield from self.call_function_steps(expr.name, args, expr.line, env))
		if isinstance(expr, ColorLit):
			r = yield from self.eval_expr_steps(expr.r, env)
			g = yield from self.eval_expr_steps(expr.g, env)
			b = yield from self.eval_expr_steps(expr.b, env)
			return (r, g, b)
		if isinstance(expr, PixelLit):
			x = yield from self.eval_expr_steps(expr.x, env)
			y = yield from self.eval_expr_steps(expr.y, env)
			return (x, y)
		if isinstance(expr, ListLit):
			items: List[Any] = []
			for item in expr.items:
				items.append((yield from self.eval_expr_steps(item, env)))
			return items
		if isinstance(expr, ParenExpr):
			return (yield from self.eval_expr_steps(expr.expr, env))
		if isinstance(expr, WalrusAssign):
			value = yield from self.eval_expr_steps(expr.expr, env)
			env.set(expr.name, value)
			return value
		if isinstance(expr, WalrusDecl):
			value = yield from self.eval_expr_steps(expr.expr, env)
			env.define(expr.name, value)
			return value
		raise RuntimeErrorWithLine(f"Unknown expression {expr}", getattr(expr, "line", -1))

	def call_function_steps(
		self,
		name: str,
		args: List[Any],
		line: int,
		env: Environment,
	) -> "Generator[StepInfo, None, Any]":
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
				yield from self.execute_block_steps(decl.body, call_env)
			except ReturnSignal as rs:
				return rs.value
			return None
		raise RuntimeErrorWithLine(f"Unknown function {name}", line)

	def _default_value(self, type_name: str) -> Any:
		if type_name == "Frame":
			return self._track_frame(Frame())
		return TYPE_DEFAULTS[type_name]()

	def _track_frame(self, frame: Frame) -> Frame:
		try:
			frame.set_on_change(self._on_frame_changed)
		except AttributeError:
			pass
		return frame

	def _on_frame_changed(self, frame: Frame) -> None:
		self._last_modified_frame = frame

	def _reset_statement_frame(self) -> None:
		self._last_modified_frame = None

	def _emit_statement_frame(self) -> None:
		if self._statement_end_handler is None:
			return
		if self._last_modified_frame is None:
			return
		self._statement_end_handler(self._last_modified_frame)
		self._last_modified_frame = None

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
		if self.publish_handler is not None:
			self.publish_handler(value)
			return
		try:
			from PyQt5.QtWidgets import QApplication
			from GUI.framedisplayer import LedMatrixWidget
			app = QApplication.instance() or QApplication([])
			widget = LedMatrixWidget(value)
			widget.show()
			app.exec_()
		except Exception as exc:
			raise RuntimeError(f"Failed to publish frame: {exc}") from exc

	def send(self, value: Any) -> None:
		if not isinstance(value, str):
			raise RuntimeErrorWithLine("Send expects a path string", -1)
		if self.send_handler is not None:
			self.send_handler(value)
			return
		try:
			from Engine.engine import sendQGC
			sendQGC(value)
		except Exception as exc:
			raise RuntimeError(f"Failed to send frame: {exc}") from exc

	def _builtin_set_red(self, args: List[Any], line: int) -> None:
		self._builtin_set_channel(args, line, "red")

	def _builtin_set_green(self, args: List[Any], line: int) -> None:
		self._builtin_set_channel(args, line, "green")

	def _builtin_set_blue(self, args: List[Any], line: int) -> None:
		self._builtin_set_channel(args, line, "blue")

	def _builtin_frame(self, args: List[Any], line: int) -> Frame:
		if args:
			raise RuntimeErrorWithLine("Frame() takes no arguments", line)
		return self._track_frame(Frame())

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

	def _builtin_get_pixel(self, args: List[Any], line: int) -> tuple[int, int, int]:
		if len(args) != 1:
			raise RuntimeErrorWithLine("getPixel requires frame->pixel", line)
		ptr = args[0]
		if not isinstance(ptr, PixelRef):
			raise RuntimeErrorWithLine("Argument must be frame->pixel", line)
		return ptr.frame.getPixel(ptr.x, ptr.y)

	def _builtin_get_red(self, args: List[Any], line: int) -> int:
		return self._builtin_get_channel(args, line, "red")

	def _builtin_get_green(self, args: List[Any], line: int) -> int:
		return self._builtin_get_channel(args, line, "green")

	def _builtin_get_blue(self, args: List[Any], line: int) -> int:
		return self._builtin_get_channel(args, line, "blue")

	def _builtin_get_channel(self, args: List[Any], line: int, channel: str) -> int:
		if len(args) != 1:
			raise RuntimeErrorWithLine("getColor requires frame->pixel", line)
		ptr = args[0]
		if not isinstance(ptr, PixelRef):
			raise RuntimeErrorWithLine("Argument must be frame->pixel", line)
		if channel == "red":
			return ptr.frame.getRed(ptr.x, ptr.y)
		if channel == "green":
			return ptr.frame.getGreen(ptr.x, ptr.y)
		if channel == "blue":
			return ptr.frame.getBlue(ptr.x, ptr.y)
		raise RuntimeErrorWithLine("Unknown color channel", line)

	def _builtin_make_rect(self, args: List[Any], line: int) -> None:
		if len(args) != 4:
			raise RuntimeErrorWithLine("makeRect requires frame, p1, p2, color", line)
		frame, p1, p2, color = args
		if not isinstance(frame, Frame):
			raise RuntimeErrorWithLine("First arg must be Frame", line)
		x1, y1 = self._unwrap_point(p1, line)
		x2, y2 = self._unwrap_point(p2, line)
		if not (isinstance(color, tuple) and len(color) == 3):
			raise RuntimeErrorWithLine("Fourth arg must be color tuple", line)
		r, g, b = color
		frame.makeRect(int(x1), int(y1), int(x2), int(y2), int(r), int(g), int(b))

	def _builtin_make_line(self, args: List[Any], line: int) -> None:
		if len(args) != 4:
			raise RuntimeErrorWithLine("makeLine requires frame, p1, p2, color", line)
		frame, p1, p2, color = args
		if not isinstance(frame, Frame):
			raise RuntimeErrorWithLine("First arg must be Frame", line)
		x1, y1 = self._unwrap_point(p1, line)
		x2, y2 = self._unwrap_point(p2, line)
		if not (isinstance(color, tuple) and len(color) == 3):
			raise RuntimeErrorWithLine("Fourth arg must be color tuple", line)
		r, g, b = color
		frame.makeLine(int(x1), int(y1), int(x2), int(y2), int(r), int(g), int(b))

	def _builtin_make_oval(self, args: List[Any], line: int) -> None:
		if len(args) != 4:
			raise RuntimeErrorWithLine("makeOval requires frame, p1, p2, color", line)
		frame, p1, p2, color = args
		if not isinstance(frame, Frame):
			raise RuntimeErrorWithLine("First arg must be Frame", line)
		x1, y1 = self._unwrap_point(p1, line)
		x2, y2 = self._unwrap_point(p2, line)
		if not (isinstance(color, tuple) and len(color) == 3):
			raise RuntimeErrorWithLine("Fourth arg must be color tuple", line)
		r, g, b = color
		frame.makeOval(int(x1), int(y1), int(x2), int(y2), int(r), int(g), int(b))

	def _builtin_make_curve(self, args: List[Any], line: int) -> None:
		if len(args) != 5:
			raise RuntimeErrorWithLine("makeCurve requires frame, p1, p2, control, color", line)
		frame, p1, p2, ctrl, color = args
		if not isinstance(frame, Frame):
			raise RuntimeErrorWithLine("First arg must be Frame", line)
		x1, y1 = self._unwrap_point(p1, line)
		x2, y2 = self._unwrap_point(p2, line)
		cx, cy = self._unwrap_point(ctrl, line)
		if not (isinstance(color, tuple) and len(color) == 3):
			raise RuntimeErrorWithLine("Fifth arg must be color tuple", line)
		r, g, b = color
		frame.makeCurve(int(x1), int(y1), int(x2), int(y2), int(cx), int(cy), int(r), int(g), int(b))

	def _builtin_load_qgc(self, args: List[Any], line: int) -> Frame:
		if len(args) != 1:
			raise RuntimeErrorWithLine("LoadQGC requires path string", line)
		path = args[0]
		if not isinstance(path, str):
			raise RuntimeErrorWithLine("Path must be string", line)
		return self._track_frame(loadQGC(path))

	def _builtin_save_qgc(self, args: List[Any], line: int) -> None:
		if len(args) != 2:
			raise RuntimeErrorWithLine("SaveQGC requires frame and path string", line)
		frame, path = args
		if not isinstance(frame, Frame):
			raise RuntimeErrorWithLine("First arg must be Frame", line)
		if not isinstance(path, str):
			raise RuntimeErrorWithLine("Path must be string", line)
		saveQGC(frame, path)

	def _builtin_fill(self, args: List[Any], line: int) -> None:
		if len(args) != 4:
			raise RuntimeErrorWithLine("Fill requires frame, startx, starty, color", line)
		frame, startx, starty, color = args
		if not isinstance(frame, Frame):
			raise RuntimeErrorWithLine("First arg must be Frame", line)
		if not isinstance(startx, int) or not isinstance(starty, int):
			raise RuntimeErrorWithLine("startx/starty must be int", line)
		if not (isinstance(color, tuple) and len(color) == 3):
			raise RuntimeErrorWithLine("color must be tuple", line)
		r, g, b = color
		frame.fill(int(startx), int(starty), int(r), int(g), int(b))

	def _unwrap_point(self, value: Any, line: int) -> tuple[int, int]:
		if isinstance(value, PixelRef):
			return int(value.x), int(value.y)
		if isinstance(value, tuple) and len(value) == 2:
			return int(value[0]), int(value[1])
		raise RuntimeErrorWithLine("Point must be pixel or (x y)", line)

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

