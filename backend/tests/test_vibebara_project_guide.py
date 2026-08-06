from app.services import project_service


def test_ensure_vibebara_guide_preserves_existing_content(tmp_path):
    guide_path = tmp_path / "vibebara.md"
    guide_path.write_text("# 团队自定义说明\n", encoding="utf-8")

    project_service._ensure_vibebara_guide(str(tmp_path))
    project_service._ensure_vibebara_guide(str(tmp_path))

    guide = guide_path.read_text(encoding="utf-8")
    assert guide.startswith("# 团队自定义说明\n")
    assert "vibebara status" in guide
    assert "vibebara pull <skill-name>" in guide
    assert "vibebara push <skill-name>" in guide
    assert "vibebara merge <skill-name> --preview" in guide
    assert guide.count(project_service.VIBEBARA_GUIDE_START) == 1
