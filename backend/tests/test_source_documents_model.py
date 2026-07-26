"""源文档模型写入冒烟测试（Phase 1）。"""

from app.db.models import Project, ProjectSourceDocument, User
from app.core.security import get_password_hash


async def test_source_document_can_be_persisted(session_factory):
    async with session_factory() as session:
        user = User(
            username="src_user",
            email="src@example.com",
            password_hash=get_password_hash("secret123"),
        )
        session.add(user)
        await session.flush()

        project = Project(user_id=user.id, title="Sources Smoke", status="INITIALIZING")
        session.add(project)
        await session.flush()

        doc = ProjectSourceDocument(
            project_id=project.id,
            role="ASSESSMENT",
            source_type="PASTE",
            title="Rubric",
            raw_text="Write an APA literature review.",
            status="PARSED",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

        assert doc.id is not None
        assert doc.role == "ASSESSMENT"
        assert doc.raw_text.startswith("Write")
