# pyright: reportMissingImports=false
"""OpenAI ``input`` parsing: text vs inline images, never confused."""

import pytest

from app.services.embedding_inputs import EmbeddingInputError, parse_openai_input

PNG = "data:image/png;base64,iVBORw0KGgo="
JPEG = "data:image/jpeg;base64,/9j/4AAQ"


def _shape(items):
    return [
        (i.type, i.text)
        if i.type == "text"
        else (i.type, i.image_format, i.image_base64)
        for i in items
    ]


def test_plain_string_is_one_text():
    assert _shape(parse_openai_input("hello")) == [("text", "hello")]


def test_mixed_list_keeps_order_and_accepts_every_image_form():
    items = parse_openai_input(
        [
            "a runner on a track",
            PNG,
            {"type": "image_url", "image_url": {"url": JPEG}},
            {"type": "image_url", "image_url": PNG},
            {"image": "data:image/jpg;base64,/9j/4AAQ"},
            {"type": "text", "text": "caption"},
            {"text": "jina style"},
        ]
    )

    assert _shape(items) == [
        ("text", "a runner on a track"),
        ("image", "png", "iVBORw0KGgo="),
        ("image", "jpeg", "/9j/4AAQ"),
        ("image", "png", "iVBORw0KGgo="),
        ("image", "jpeg", "/9j/4AAQ"),
        ("text", "caption"),
        ("text", "jina style"),
    ]


def test_data_uri_is_never_embedded_as_text():
    # Regression: a base64 image string used to be embedded as literal text.
    [item] = parse_openai_input([JPEG])
    assert item.type == "image" and item.text is None


def test_whitespace_in_base64_is_tolerated():
    [item] = parse_openai_input(["data:image/png;base64,iVBO\nRw0K\nGgo="])
    assert item.image_base64 == "iVBORw0KGgo="


@pytest.mark.parametrize(
    ("item", "message"),
    [
        ("https://example.com/a.png", None),  # plain URL string is text, not fetched
        (
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            "not fetched",
        ),
        ("data:image/png;base64,***", "not valid base64"),
        ("data:image/tiff;base64,AAAA", "unsupported image type"),
        ("data:text/plain;base64,aGk=", "data:image"),
        ({"type": "image_url", "image_url": {"url": 5}}, "data URI string"),
        ({"type": "audio", "audio": "x"}, "expected text"),
        ("", "non-empty"),
        (123, "expected text"),
    ],
)
def test_invalid_items_name_their_position(item, message):
    if message is None:
        assert parse_openai_input([item])[0].type == "text"
        return
    with pytest.raises(EmbeddingInputError, match=message) as exc_info:
        parse_openai_input(["ok", item])
    assert "input[1]" in str(exc_info.value)
