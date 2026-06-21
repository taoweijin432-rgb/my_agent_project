from app.models.test_case import TestCaseCollection as CaseCollection
from app.models.test_case import TestCaseType as CaseType
from app.services.generator import _normalize_payload


def test_model_normalizes_case_type_and_lists() -> None:
    collection = CaseCollection.model_validate(
        {
            "cases": [
                {
                    "id": 1,
                    "title": "边界值校验",
                    "precondition": ["用户已登录"],
                    "steps": "输入超过最大长度的名称\n点击保存",
                    "expected": "保存失败\n提示长度超限",
                    "type": "边界值",
                }
            ]
        }
    )

    case = collection.cases[0]
    assert case.id == "1"
    assert case.type == CaseType.boundary
    assert case.precondition == "用户已登录"
    assert case.steps == ["输入超过最大长度的名称", "点击保存"]
    assert case.expected == ["保存失败", "提示长度超限"]


def test_model_fills_missing_case_ids() -> None:
    collection = CaseCollection.model_validate(
        {
            "cases": [
                {
                    "title": "缺失 ID 的用例",
                    "steps": ["执行操作"],
                    "expected": ["返回结果"],
                    "type": "functional",
                },
                {
                    "id": "",
                    "title": "空 ID 的用例",
                    "steps": ["执行边界操作"],
                    "expected": ["返回边界结果"],
                    "type": "boundary",
                },
                {
                    "id": "CUSTOM-1",
                    "title": "已有 ID 的用例",
                    "steps": ["执行异常操作"],
                    "expected": ["返回异常结果"],
                    "type": "exception",
                },
            ]
        }
    )

    assert [case.id for case in collection.cases] == ["TC-001", "TC-002", "CUSTOM-1"]


def test_normalize_payload_accepts_top_level_list() -> None:
    payload = [{"id": "TC-001", "title": "用例"}]

    assert _normalize_payload(payload) == {"cases": payload}


def test_normalize_payload_accepts_common_aliases() -> None:
    payload = {"test_cases": [{"id": "TC-001", "title": "用例"}]}

    assert _normalize_payload(payload) == {"cases": payload["test_cases"]}
