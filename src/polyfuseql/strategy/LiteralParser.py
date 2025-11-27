import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from sqlglot import exp


class LiteralParser:
    """
    A class that provides logic to parse sqlglot Literal expressions
    into native Python types. This is shared across Insert, Update, and
    Select strategies.
    """

    def _parse_literal_expression(self, lit_expr: exp.Literal) -> Any:
        """
        [Sonar Refactor] Shared helper to parse sqlglot Literal expressions.
        Reduces Cognitive Complexity and duplication across strategies.
        """
        if not isinstance(lit_expr, exp.Literal):
            # Fallback for unexpected types
            return lit_expr.this

        if lit_expr.is_string:
            return lit_expr.this

        val_str = lit_expr.this
        if not val_str:
            return None

        val_lower = val_str.lower()

        # Handle NULL
        if val_lower == "null":
            return None

        # Handle Booleans
        if val_lower == "true":
            return True
        if val_lower == "false":
            return False

        # Handle Numerics
        try:
            # Use Decimal for precision, consistent with other connector logic
            return Decimal(val_str)
        except InvalidOperation:
            # Fallback for any other unhandled literal (e.g., 'abc')
            msg = f"Could not parse literal '{val_str}' "
            msg += "as numeric, returning as string."
            logging.warning(msg)
            return val_str
