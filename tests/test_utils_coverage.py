import pytest
from datetime import date
from polyfuseql.utils.utils import (
    _camelize,
    camelize_dict,
    env,
    _snake_case,
    _camelize_keys,
    get_pydantic_model,
)

# --- String Manipulation Tests ---


def test_camelize_logic():
    """Covers _camelize logic including underscore handling."""
    assert _camelize("snake_case") == "snakeCase"
    assert _camelize("long_snake_case_string") == "longSnakeCaseString"
    assert _camelize("alreadyCamel") == "alreadyCamel"
    assert _camelize("") == ""
    # Edge case: Leading underscore (based on logic `upper_next = True`)
    assert _camelize("_hidden_field") == "HiddenField"


def test_camelize_dict():
    """Covers camelize_dict wrapper."""
    data = {"first_name": "John", "last_name": "Doe"}
    result = camelize_dict(data)
    assert result == {"firstName": "John", "lastName": "Doe"}


def test_snake_case_logic():
    """Covers _snake_case regex logic."""
    assert _snake_case("camelCase") == "camel_case"
    assert _snake_case("PascalCase") == "pascal_case"
    assert _snake_case("SVGParser") == "svg_parser"  # Handles consecutive caps
    assert _snake_case("snake_case") == "snake_case"


def test_env_helper(monkeypatch):
    """Covers simple env wrapper."""
    monkeypatch.setenv("TEST_VAR", "value")
    assert env("TEST_VAR") == "value"
    assert env("MISSING_VAR", "default") == "default"


# --- JSON & Key Conversion Tests ---


def test_camelize_keys_dict():
    """Covers _camelize_keys with dictionary input."""
    data = {"user_id": 1, "user_name": "admin"}
    result = _camelize_keys(data)
    assert result == {"userId": 1, "userName": "admin"}


def test_camelize_keys_json_string():
    """Covers _camelize_keys with valid JSON string input."""
    json_str = '{"order_id": 100, "total_price": 50.5}'
    result = _camelize_keys(json_str)
    assert result == {"orderId": 100, "totalPrice": 50.5}


def test_camelize_keys_invalid_json():
    """Covers _camelize_keys exception block for invalid JSON."""
    # Should return empty dict on error
    assert _camelize_keys("{invalid_json") == {}
    assert _camelize_keys(None) == {}  # Not a dict or string


# --- Pydantic Dynamic Model Tests ---


def test_get_pydantic_model_missing_columns():
    """Targets ValueError when schema lacks 'columns'."""
    schema = {"pk": "id"}  # Missing 'columns'
    with pytest.raises(ValueError, match="does not contain 'columns' definition"):
        get_pydantic_model("test_table", schema)


def test_dynamic_caster_logic():
    """
    Targets the @field_validator 'dynamic_caster' logic in the generated model.
    This covers the type coercion blocks.
    """
    schema = {
        "columns": {
            "id_col": "int",
            "score_col": "float",
            "date_col": "date",
            "str_col": "str",
        }
    }
    DynamicModel = get_pydantic_model("test_table", schema)

    # Case 1: Standard Types (No casting needed)
    obj = DynamicModel(id_col=1, score_col=2.5, date_col=date(2023, 1, 1), str_col="s")
    assert obj.id_col == 1

    # Case 2: String Coercion (The core logic being tested)
    raw_data = {
        "id_col": "123",  # -> int
        "score_col": "45.67",  # -> float
        "date_col": "2023-10-25",  # -> date
        "str_col": "  ",  # -> None (strip check)
    }
    obj_casted = DynamicModel(**raw_data)

    assert obj_casted.id_col == 123
    assert isinstance(obj_casted.id_col, int)

    assert obj_casted.score_col == 45.67
    assert isinstance(obj_casted.score_col, float)

    assert obj_casted.date_col == date(2023, 10, 25)

    assert obj_casted.str_col is None


def test_dynamic_caster_fallbacks():
    """
    Targets the except blocks in dynamic_caster where casting fails
    but returns original value.
    """
    schema = {"columns": {"val": "str"}}
    DynamicModel = get_pydantic_model("fallback_table", schema)

    # Pass a string that looks like a float but we want to ensure it survives
    # the int() check and falls through logic correctly
    obj = DynamicModel(val="not_a_number")
    assert obj.val == "not_a_number"

    # Pass something that isn't a string (first check in validator)
    obj_int = DynamicModel(val=999)
    assert obj_int.val == 999
