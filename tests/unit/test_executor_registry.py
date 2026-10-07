from typing import get_args

from app.domain.operations import Operation
from app.executor.operation_executor import HANDLERS


def test_every_operation_type_has_an_executor_handler():
    union, _ = get_args(Operation)
    operation_types = {get_args(member.model_fields["type"].annotation)[0] for member in get_args(union)}

    assert operation_types == set(HANDLERS)
