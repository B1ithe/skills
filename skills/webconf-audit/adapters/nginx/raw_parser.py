from __future__ import annotations

from functools import cached_property

from pyparsing import (
    Combine,
    FollowedBy,
    Forward,
    Group,
    Keyword,
    Literal,
    OneOrMore,
    Optional,
    ParseResults,
    ParserElement,
    QuotedString,
    Regex,
    Suppress,
    Word,
    ZeroOrMore,
    alphanums,
)

# Rely on pyparsing's default whitespace skipping between tokens.
# Do NOT also require explicit White() before values (that double-eats spaces).
ParserElement.set_default_whitespace_chars(" \t\r\n")


class NginxRawParser:
    """pyparsing grammar for an nginx conf subset used in security audits."""

    def parse(self, text: str) -> ParseResults:
        content = text.strip()
        if not content:
            return ParseResults([])
        return self.grammar.parse_string(content, parse_all=True)

    @cached_property
    def grammar(self):
        left = Suppress("{")
        right = Suppress("}")
        semi = Suppress(";")

        keyword = Word(alphanums + "._-+/")
        value_wq = Regex(r"(?:\([^\s;]*\)|\$\{\w+\}|[^\s;{}])+")
        # multiline=True: real configs sometimes put CSP etc. across lines inside quotes
        value = QuotedString('"', multiline=True) | QuotedString("'", multiline=True) | value_wq

        location_mod = Keyword("=") | Keyword("~*") | Keyword("~") | Keyword("^~")
        # Only these use key/value bodies (not nested nginx directives).
        hash_kw = (
            Keyword("map")
            | Keyword("types")
            | Keyword("charset_map")
            | Keyword("geo")
            | Keyword("split_clients")
        )

        if_mod = Combine(
            Optional("!")
            + (
                Keyword("=")
                | Keyword("~*")
                | Keyword("~")
                | (Literal("-") + (Literal("f") | Literal("d") | Literal("e") | Literal("x")))
            )
        )
        condition_body = (if_mod + Optional(value)) | (Word("$_" + alphanums) + Optional(if_mod + Optional(value)))
        condition = Regex(r"\((?:[^()\n\r\\]|(?:\(.*\))|(?:\\.))+?\)").set_parse_action(
            lambda t: condition_body.parse_string(t[0][1:-1])
        )

        include = (Keyword("include") + value + semi)("include")
        directive = (keyword + ZeroOrMore(value) + semi)("directive")
        comment = Regex(r"\#[^\n]*")("comment").set_parse_action(lambda t: [t[0][1:].strip()])

        generic_block = Forward()
        if_block = Forward()
        location_block = Forward()
        hash_block = Forward()

        sub = OneOrMore(
            Group(comment | include | directive | if_block | location_block | hash_block | generic_block)
        )

        if_block <<= (Keyword("if") + Group(condition) + Group(left + Optional(sub) + right))("block")

        location_block <<= (
            Keyword("location")
            + Group(Optional(location_mod) + value)
            + FollowedBy("{")
            + Group(left + Optional(sub) + right)
        )("block")

        # types/map bodies: entries or comments (comments are common inside types {}).
        hash_value = Group(value + ZeroOrMore(value) + semi)("hash_value")
        hash_body = ZeroOrMore(Group(comment) | hash_value)
        hash_block <<= (
            hash_kw
            + Group(ZeroOrMore(value))
            + FollowedBy("{")
            + Group(left + hash_body + right)
        )("block")

        generic_block <<= (
            keyword + Group(ZeroOrMore(value)) + FollowedBy("{") + Group(left + Optional(sub) + right)
        )("block")

        return sub
