#!/usr/bin/env python3
"""Small, offline CMSC216 assembly reference and full-text search."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path


DATA = Path(os.environ.get("ASMHELP_DATA", Path(__file__).with_name("topics.toml")))
STOPWORDS = {"a", "an", "and", "do", "for", "how", "i", "in", "of", "the", "to", "with"}
CATEGORY_ORDER = ["Start here", "Instructions", "Control flow", "Functions and data", "Debugging"]


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9%]+", value.lower()))


def load_data():
    with DATA.open("rb") as stream:
        data = tomllib.load(stream)
    topics = data["topic"]
    by_id = {topic["id"]: topic for topic in topics}
    if len(by_id) != len(topics):
        raise ValueError("duplicate topic id in asmhelp database")
    aliases = {}
    for topic in topics:
        for alias in [topic["id"], topic["title"], *topic.get("aliases", [])]:
            key = normalize(alias)
            if key in aliases and aliases[key]["id"] != topic["id"]:
                raise ValueError(f"duplicate alias in asmhelp database: {alias}")
            aliases[key] = topic
        unknown = set(topic.get("see", [])) - by_id.keys()
        if unknown:
            raise ValueError(f"unknown related topic for {topic['id']}: {sorted(unknown)}")
    return data["manual"], topics, aliases


def variants(term):
    words = {term}
    for suffix in ("ing", "ed", "es", "s"):
        if term.endswith(suffix) and len(term) > len(suffix) + 3:
            words.add(term[: -len(suffix)])
    return words


def topic_text(topic):
    return normalize(" ".join([
        topic["id"], topic["title"], topic["summary"], topic["body"],
        " ".join(topic.get("aliases", [])), " ".join(topic.get("keywords", [])),
    ]))


def search(query, topics):
    terms = [term for term in normalize(query).split() if term not in STOPWORDS]
    if not terms:
        return []
    results = []
    for topic in topics:
        haystack = topic_text(topic)
        if not all(any(word in haystack for word in variants(term)) for term in terms):
            continue
        aliases = [normalize(topic["id"]), *[normalize(a) for a in topic.get("aliases", [])]]
        score = 0
        for term in terms:
            if term in aliases:
                score += 20
            elif any(alias.startswith(term) for alias in aliases):
                score += 10
            score += min(haystack.count(term), 5)
        results.append((score, topic["id"], topic))
    return [topic for _, _, topic in sorted(results, key=lambda item: (-item[0], item[1]))]


def render_topic(topic, by_id, manual):
    related = [by_id[item]["title"] for item in topic.get("see", []) if item in by_id]
    output = [
        topic["title"],
        "=" * len(topic["title"]),
        "",
        textwrap.fill(topic["summary"], width=88),
        "",
        topic["body"].strip(),
    ]
    if related:
        output.extend(["", "RELATED", "  " + " · ".join(related)])
    output.extend(["", "SCOPE", textwrap.fill(manual["scope"], width=88)])
    return "\n".join(output) + "\n"


def render_index(manual, topics):
    lines = [manual["title"], "=" * len(manual["title"]), "", manual["intro"].strip(), ""]
    grouped = {category: [] for category in CATEGORY_ORDER}
    for topic in topics:
        grouped.setdefault(topic["category"], []).append(topic)
    for category in CATEGORY_ORDER:
        entries = grouped.get(category, [])
        if not entries:
            continue
        lines.extend([category.upper(), "-" * len(category)])
        for topic in entries:
            lines.append(f"  {topic['id']:<14} {topic['summary']}")
        lines.append("")
    lines.extend([
        "LOOKUP",
        "------",
        "  `asmhelp div`, `asmhelp idivl`, and `asmhelp remainder` open Division.",
        "  `asmhelp signed comparison` performs a local full-text search.",
        "  There is no network access and no model/backend call.",
    ])
    return "\n".join(lines) + "\n"


def render_results(query, results):
    lines = [f"Course-reference matches for: {query}", ""]
    for topic in results[:12]:
        lines.append(f"  {topic['id']:<14} {topic['summary']}")
    if len(results) > 12:
        lines.append(f"  … {len(results) - 12} more")
    lines.extend(["", "Open a page with `asmhelp TOPIC`."])
    return "\n".join(lines) + "\n"


def emit(text):
    if not sys.stdout.isatty() or os.environ.get("ASMHELP_PAGER") == "cat":
        sys.stdout.write(text)
        return
    pager = os.environ.get("ASMHELP_PAGER") or os.environ.get("MANPAGER") or os.environ.get("PAGER")
    command = pager.split() if pager else ([shutil.which("less"), "-R", "-F", "-X"] if shutil.which("less") else [])
    if not command or not command[0]:
        sys.stdout.write(text)
        return
    try:
        subprocess.run(command, input=text, text=True, check=False)
    except (BrokenPipeError, OSError):
        sys.stdout.write(text)


def main():
    parser = argparse.ArgumentParser(
        prog="asmhelp",
        description="offline CMSC216 x86-64 AT&T reference; give a topic or search words",
    )
    parser.add_argument("query", nargs="*", help="for example: mov, div, regs, stack, or signed comparison")
    args = parser.parse_args()
    manual, topics, aliases = load_data()
    by_id = {topic["id"]: topic for topic in topics}
    if not args.query or normalize(" ".join(args.query)) in {"help", "topics", "list"}:
        emit(render_index(manual, topics))
        return 0
    query = " ".join(args.query)
    exact = aliases.get(normalize(query))
    if exact:
        emit(render_topic(exact, by_id, manual))
        return 0
    significant_terms = [term for term in normalize(query).split() if term not in STOPWORDS]
    token_matches = {aliases[term]["id"] for term in significant_terms if term in aliases}
    if len(token_matches) == 1:
        emit(render_topic(by_id[token_matches.pop()], by_id, manual))
        return 0
    results = search(query, topics)
    if len(results) == 1:
        emit(render_topic(results[0], by_id, manual))
        return 0
    if results:
        emit(render_results(query, results))
        return 0
    sys.stderr.write(
        f"asmhelp: no CMSC216 topic matches: {query}\n"
        "Run `asmhelp` to see the intentionally small course reference.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
