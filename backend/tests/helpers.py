"""测试辅助：准备写作所需的 A + 锁定 C。"""


async def prepare_writing_inputs(auth_client, project_id: str) -> None:
    """创建 Assessment + Specific + Outline 并锁定，满足 run-agent 前置。"""
    await auth_client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "role": "ASSESSMENT",
            "raw_text": "Machine learning in education. Requirement: APA.",
        },
    )
    await auth_client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "role": "SPECIFIC",
            "raw_text": "Constraint: focus on higher education.",
        },
    )
    outline = await auth_client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "role": "OUTLINE",
            "raw_text": "# Introduction\n\n# Literature Review\n\n# Conclusion\n",
        },
    )
    assert outline.status_code == 201
    lock = await auth_client.post(
        f"/api/projects/{project_id}/outline/lock",
        json={"source_id": outline.json()["id"]},
    )
    assert lock.status_code == 200
