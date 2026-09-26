from app.services.preview_alignment import PAGE_MARKER_PATTERN, build_page_markers


def test_page_markers_follow_content_list_blocks():
    markdown = "# First page\n\nFirst page body.\n\n# Second page\n\nSecond page body.\n"
    content_list = {
        "pages": [
            {
                "page_idx": 0,
                "blocks": [
                    {"type": "doc_title", "content": "First page"},
                    {"type": "text", "content": "First page body."},
                ],
            },
            {
                "page_idx": 1,
                "blocks": [
                    {"type": "doc_title", "content": "Second page"},
                    {"type": "text", "content": "Second page body."},
                ],
            },
        ]
    }

    markers = build_page_markers(markdown, content_list)

    assert markers == [
        {"page": 1, "offset": 0},
        {"page": 2, "offset": len("# First page\n\nFirst page body.\n\n".encode("utf-8")),
        },
    ]


def test_marker_pattern_is_invisible_to_markdown_rendering():
    content = "\n\n<!-- docvortex-page: 3 -->\n\n## Heading"
    assert PAGE_MARKER_PATTERN.search(content).group(1) == "3"


def test_image_only_page_uses_mineru_page_image_name():
    markdown = "# First page\n\n![](images/page_1_chart.jpg)\n\n![](images/page_2_chart.jpg)\n\n# Third page\n"
    content_list = {
        "pages": [
            {"page_idx": 0, "blocks": [{"type": "text", "content": "First page"}]},
            {"page_idx": 1, "blocks": [{"type": "chart", "content": ""}]},
            {"page_idx": 2, "blocks": [{"type": "doc_title", "content": "Third page"}]},
        ]
    }

    markers = build_page_markers(markdown, content_list)

    assert [marker["page"] for marker in markers] == [1, 2, 3]
    assert markers[1]["offset"] > markers[0]["offset"]


def test_table_page_anchor_matches_markdown_table_start():
    markdown = (
        "# Page one\n\n"
        "## 一页速查\n\n"
        "| 你想做什么 | 推荐入口 | 最小提示词要点 |\n"
        "| --- | --- | --- |\n"
        "| 快速问一个独立问题 | 新建聊天 | 目标和输出 |\n\n"
        "## 给 Codex 的四要素\n\n目标:最终要得到什么结果。\n"
    )
    content_list = {
        "pages": [
            {"page_idx": 0, "blocks": [{"type": "text", "content": "Page one"}]},
            {
                "page_idx": 1,
                "blocks": [
                    {
                        "type": "table",
                        "content": "| 你想做什么 | 推荐入口 | 最小提示词要点 |\n| --- | --- | --- |\n| 快速问一个独立问题 | 新建聊天 | 目标和输出 |",
                    }
                ],
            },
        ]
    }

    markers = build_page_markers(markdown, content_list)

    assert markers[1]["offset"] == len("# Page one\n\n## 一页速查\n\n".encode("utf-8"))
