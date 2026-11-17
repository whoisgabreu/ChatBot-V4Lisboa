import time

import pytest

from app.prompts import PromptManager


@pytest.fixture
def prompts_dir(tmp_path):
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "system.md").write_text("padrao {{name}}", encoding="utf-8")
    (directory / "vendas.md").write_text("vendas", encoding="utf-8")
    return directory


def test_list_and_get(prompts_dir):
    manager = PromptManager(prompts_dir, "system.md")
    assert manager.list() == ["system", "vendas"]
    assert manager.get() == "padrao {{name}}"
    assert manager.get("vendas") == "vendas"
    assert manager.get("vendas.md") == "vendas"


def test_hot_reload(prompts_dir):
    manager = PromptManager(prompts_dir, "system.md")
    assert manager.get() == "padrao {{name}}"
    path = prompts_dir / "system.md"
    path.write_text("novo conteudo", encoding="utf-8")
    time.sleep(0.01)
    assert manager.get() == "novo conteudo"


def test_missing_custom_falls_back_to_default(prompts_dir):
    manager = PromptManager(prompts_dir, "system.md")
    assert manager.get("inexistente") == "padrao {{name}}"


def test_invalid_name_is_rejected(prompts_dir):
    manager = PromptManager(prompts_dir, "system.md")
    assert not manager.exists("../../etc/passwd")


def test_render_placeholders():
    rendered = PromptManager.render(
        "Oi {{name}}, numero {{number}}, em {{date}}", name="Ana", number="123"
    )
    assert "Ana" in rendered
    assert "123" in rendered
    assert "{{date}}" not in rendered
