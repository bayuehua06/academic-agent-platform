"""NotebookLM 抓取服务单元测试（API 已在 Phase 1 拆除；Phase 2 会挂到 sources）。"""

from app.services.notebooklm import NotebookLMService


def test_strip_ui_noise_and_conversation_heuristic():
    junk = NotebookLMService._strip_ui_noise(
        "Search results\nNo emoji found\nSomething else"
    )
    assert not NotebookLMService._looks_like_conversation(junk)

    good = (
        "User:\nWhat are the constraints?\n"
        "NotebookLM:\nConstraint: focus on higher education and APA 7th citations. "
    )
    assert NotebookLMService._looks_like_conversation(good)
