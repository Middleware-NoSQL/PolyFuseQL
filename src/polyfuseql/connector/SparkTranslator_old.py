from decimal import Decimal, InvalidOperation
from sqlglot import exp

try:
    from pyspark.sql import functions as F
    from pyspark.sql.types import DecimalType

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False


class SparkTranslator:
    """
    A class that provides SQL-to-PySpark translation capabilities.
    This allows Connectors (like Redis and Neo4j) to share the same
    logic for converting sqlglot expressions into Spark Columns.
    """

    def _translate_alias(self, expression: exp.Alias):
        """Translates an ALIAS expression (e.g., col AS c)."""
        inner_expr = self._translate_expression_to_spark(expression.this)
        return inner_expr.alias(expression.alias)

    def _translate_column(self, expression: exp.Column):
        """Translates a COLUMN expression (e.g., t1.col or col)."""
        if expression.table:
            return F.col(f"{expression.table}.{expression.name}")
        return F.col(expression.name)

    def _translate_literal(self, expression: exp.Literal):
        """Translates a LITERAL expression (e.g., 'foo', 123, 12.5)."""
        val = expression.this
        try:
            # Try to cast to Decimal for numeric literals for precision
            return F.lit(Decimal(val)) if not expression.is_string else F.lit(val)
        except InvalidOperation:
            # Fallback to string literal
            return F.lit(val)

    def _translate_paren(self, expression: exp.Paren):
        """Translates a PAREN expression (e.g., (1 + 1))."""
        return self._translate_expression_to_spark(expression.this)

    def _translate_binary(self, expression: exp.Binary):
        """Translates all BINARY expressions (e.g., +, -, =, AND, OR)."""
        left = self._translate_expression_to_spark(expression.left)
        right = self._translate_expression_to_spark(expression.right)

        op_map = {
            exp.Mul: lambda a, b: a * b,
            exp.Sub: lambda a, b: a - b,
            exp.Add: lambda a, b: a + b,
            exp.Div: lambda a, b: a / b,
            exp.EQ: lambda a, b: a == b,
            exp.NEQ: lambda a, b: a != b,
            exp.GT: lambda a, b: a > b,
            exp.GTE: lambda a, b: a >= b,
            exp.LT: lambda a, b: a < b,
            exp.LTE: lambda a, b: a <= b,
            exp.And: lambda a, b: a & b,
            exp.Or: lambda a, b: a | b,
        }

        op_func = op_map.get(type(expression))
        if op_func:
            return op_func(left, right)

        raise NotImplementedError(f"Unsupported binary operator: {type(expression)}")

    def _translate_agg_func(self, expression: exp.AggFunc):
        """Translates all AGGREGATE expressions (e.g., SUM, COUNT)."""
        inner_expr = self._translate_expression_to_spark(expression.this)

        agg_map = {
            exp.Sum: F.sum,
            exp.Avg: F.avg,
            exp.Count: F.count,
            exp.Min: F.min,
            exp.Max: F.max,
        }

        agg_func = agg_map.get(type(expression))
        if not agg_func:
            raise NotImplementedError(
                f"Unsupported aggregate function: {type(expression)}"
            )

        agg_expr = agg_func(inner_expr)
        if type(expression) in [exp.Sum, exp.Avg]:
            # Cast aggregates to a high-precision decimal
            agg_expr = agg_expr.cast(DecimalType(38, 6))

        return agg_expr

    def _translate_cast(self, expression: exp.Cast):
        """Translates a CAST expression (e.g., CAST(col AS DATE))."""
        if expression.to.this == exp.DataType.Type.DATE:
            return F.to_date(self._translate_expression_to_spark(expression.this))

        raise NotImplementedError(f"Unsupported CAST type: {expression.to.this}")

    def _translate_star(self, expression: exp.Star):
        """Translates a STAR expression (e.g., COUNT(*))."""
        return F.lit(1)

    def _translate_expression_to_spark(self, expression: exp.Expression):
        """
        [Sonar Refactor]
        Translates a sqlglot Expression into a PySpark Column expression.
        Delegates to helper methods to reduce cognitive complexity.
        """
        if not SPARK_AVAILABLE:
            raise ImportError("PySpark is not installed or available.")

        # --- Dispatcher ---
        if isinstance(expression, exp.Binary):
            return self._translate_binary(expression)

        if isinstance(expression, exp.AggFunc):
            return self._translate_agg_func(expression)

        translator_map = {
            exp.Alias: self._translate_alias,
            exp.Column: self._translate_column,
            exp.Literal: self._translate_literal,
            exp.Paren: self._translate_paren,
            exp.Cast: self._translate_cast,
            exp.Star: self._translate_star,
        }

        translator = translator_map.get(type(expression))

        if translator:
            return translator(expression)

        raise NotImplementedError(
            f"Unsupported SQL expression for Spark translation: {type(expression)}"
        )
