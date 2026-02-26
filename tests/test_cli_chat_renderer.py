"""Tests for unified chat CLI renderer."""

from app.cli.lib.chat_renderer import ChatRenderer


def test_render_message_multiline_with_separators(capsys):
    renderer = ChatRenderer()
    message = {
        "content": "第一行\n第二行\n第三行",
        "actions": [{"label": "查看结果", "href": "/result"}],
        "references": [{"title": "Ref1", "href": "https://example.com", "description": "desc"}],
    }

    renderer.render_message(message)
    out = capsys.readouterr().out

    assert "第一行" in out
    assert "第二行" in out
    assert "第三行" in out
    assert "[相关操作]" in out
    assert "[参考链接]" in out
    assert "------------------------------------------------------------" in out


def test_render_stage_done(capsys):
    renderer = ChatRenderer()
    renderer.render_stage("claims", "done")
    out = capsys.readouterr().out
    assert "主张抽取完成" in out


def test_render_error(capsys):
    renderer = ChatRenderer()
    renderer.render_error("测试错误")
    out = capsys.readouterr().out
    assert "测试错误" in out
