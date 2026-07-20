import io

import pandas as pd
from selectolax.parser import HTMLParser


def clean_text(html: str) -> str:
    tree = HTMLParser(html)
    for tag in tree.css("script, style, noscript, template, svg"):
        tag.decompose()
    node = tree.body or tree.root
    return node.text(separator="\n", strip=True) if node else ""


def tables(html: str) -> list[pd.DataFrame]:
    try:
        return pd.read_html(io.StringIO(html), flavor="lxml")
    except ValueError:
        return []
