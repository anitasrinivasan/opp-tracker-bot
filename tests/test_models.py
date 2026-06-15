import pytest
from pydantic import ValidationError

from models import COL_INDEX, COLUMNS, Opportunity


def test_defaults():
    o = Opportunity(title="Grant X")
    assert o.deadline is None
    assert o.category == "other"
    assert o.status == "interested"
    assert o.description == ""


@pytest.mark.parametrize("blank", [None, "", "null", "None", "   "])
def test_deadline_blank_normalizes_to_none(blank):
    assert Opportunity(title="t", deadline=blank).deadline is None


def test_valid_iso_deadline_kept():
    assert Opportunity(title="t", deadline="2026-09-01").deadline == "2026-09-01"


@pytest.mark.parametrize("bad", ["09/01/2026", "Sept 1", "2026-13-01", "next Friday"])
def test_bad_deadline_raises(bad):
    with pytest.raises((ValidationError, ValueError)):
        Opportunity(title="t", deadline=bad)


def test_title_required():
    with pytest.raises((ValidationError, ValueError)):
        Opportunity(title="   ")


def test_bad_enum_raises():
    with pytest.raises(ValidationError):
        Opportunity(title="t", category="banana")


def test_extra_fields_ignored():
    o = Opportunity.model_validate({"title": "t", "junk": 1})
    assert o.title == "t"


def test_columns_and_index():
    assert COLUMNS[0] == "title" and COLUMNS[-1] == "source_type"
    assert COL_INDEX["title"] == 1
    assert COL_INDEX["status"] == 6
