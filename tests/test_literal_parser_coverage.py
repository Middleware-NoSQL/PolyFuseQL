import pytest
from decimal import Decimal
from sqlglot import exp
from polyfuseql.strategy.LiteralParser import LiteralParser


class MockStrategy(LiteralParser):
    """A dummy class to expose the mixin method for testing."""

    pass


@pytest.fixture
def parser():
    return MockStrategy()


def test_parse_boolean_literals_logic(parser):
    """
    Test 'true' and 'false' parsing logic.
    NOTE: We must manually set is_string=False to bypass the early return
    and hit the conversion logic lines we want to cover.
    """
    # Simulates a bare literal like TRUE (if not parsed as exp.Boolean)
    true_expr = exp.Literal(this="true", is_string=False)
    assert parser._parse_literal_expression(true_expr) is True

    false_expr = exp.Literal(this="false", is_string=False)
    assert parser._parse_literal_expression(false_expr) is False

    # Test case-insensitivity
    upper_expr = exp.Literal(this="TRUE", is_string=False)
    assert parser._parse_literal_expression(upper_expr) is True


def test_parse_null_literal_logic(parser):
    """
    Test 'null' literal parsing logic.
    """
    null_expr = exp.Literal(this="null", is_string=False)
    assert parser._parse_literal_expression(null_expr) is None


def test_parse_valid_decimal(parser):
    """
    Test valid numeric strings are converted to Decimal.
    exp.Literal.number() automatically sets is_string=False.
    """
    assert parser._parse_literal_expression(exp.Literal.number(123)) == Decimal("123")
    assert parser._parse_literal_expression(exp.Literal.number(12.50)) == Decimal(
        "12.50"
    )


def test_parse_invalid_decimal_fallback(parser):
    """
    Test the InvalidOperation catch block.
    We pass a Literal that is NOT a string (is_string=False),
    but contains non-numeric text. This forces it into the try/except Decimal block.
    """
    val = "abc_string"
    # Manually construct to ensure is_string=False, triggering the parsing attempt
    literal_expr = exp.Literal(this=val, is_string=False)

    result = parser._parse_literal_expression(literal_expr)
    assert result == val


def test_parse_non_literal_expression(parser):
    """
    Test passing something that isn't a Literal expression (Fallback path).
    """
    # When passing a Column, .this is an Identifier object
    col_name = "some_column"
    col_expr = exp.Column(this=exp.Identifier(this=col_name, quoted=False))

    result = parser._parse_literal_expression(col_expr)

    # The method returns lit_expr.this. For a Column, that is the Identifier object.
    assert isinstance(result, exp.Identifier)
    assert result.this == col_name


def test_parse_string_literal_early_return(parser):
    """
    Test that standard quoted strings return early as strings.
    """
    # exp.Literal.string() sets is_string=True
    str_expr = exp.Literal.string("true")
    assert (
        parser._parse_literal_expression(str_expr) == "true"
    )  # Returns string, not bool
