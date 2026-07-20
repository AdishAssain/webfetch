from webfetch._extract import clean_text, tables


def test_clean_text_strips_scripts_and_styles():
    html = (
        "<html><head><style>.x{color:red}</style></head>"
        "<body><script>steal()</script><p>Hello world</p></body></html>"
    )
    text = clean_text(html)
    assert "Hello world" in text
    assert "steal" not in text
    assert "color:red" not in text


def test_tables_parses_html_table():
    html = "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
    dfs = tables(html)
    assert len(dfs) == 1
    assert list(dfs[0].columns) == ["a", "b"]


def test_tables_returns_empty_without_tables():
    assert tables("<html><body>no tables here</body></html>") == []
