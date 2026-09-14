"""Download the first published lab or project missing from the workspace."""

import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://www.cs.umd.edu/~profk/216/"
KINDS = {
    "lab": ("lab", "Lab", "labs"),
    "project": ("p", "Project", "projects"),
}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for key, value in attrs if key == "href" and value)


def links(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        parser = Links()
        parser.feed(response.read().decode("utf-8"))
    return [urllib.parse.urljoin(url, href) for href in parser.hrefs]


def item_number(url, prefix, suffix):
    name = urllib.parse.unquote(urllib.parse.urlsplit(url).path).rsplit("/", 1)[-1]
    match = re.fullmatch(re.escape(prefix) + r"0*(\d+)" + suffix, name, re.IGNORECASE)
    return int(match[1]) if match else None


def download(root, kind="lab"):
    if kind not in KINDS:
        raise ValueError(f"Unsupported coursework kind: {kind}")
    prefix, label, plural = KINDS[kind]
    existing = set()
    if root.exists():
        for entry in root.iterdir():
            match = re.fullmatch(
                re.escape(prefix) + r"0*(\d+)(?:-code)?(?:\.zip)?",
                entry.name,
                re.IGNORECASE,
            )
            if match:
                existing.add(int(match[1]))
    published = {}
    for url in links(urllib.parse.urljoin(BASE, "schedule.html")):
        if not url.startswith(BASE):
            continue
        number = item_number(url, prefix, r"(?:-code\.zip|\.html)")
        if number is not None and number not in existing:
            published.setdefault(number, []).append(url)
    if not published:
        print(f"cmsc216: No new published {plural} to download.")
        return
    number = min(published)
    candidates = published[number]
    archives = [
        url for url in candidates
        if item_number(url, prefix, r"-code\.zip") == number
    ]
    if not archives:
        for page in candidates:
            archives.extend(
                url for url in links(page)
                if url.startswith(BASE)
                and item_number(url, prefix, r"-code\.zip") == number
            )
    if not archives:
        raise ValueError(f"{label} {number} has no published code ZIP yet")
    url = archives[0]
    destination = root / Path(urllib.parse.urlsplit(url).path).name
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cmsc216-download-", dir=root) as staging:
        archive = Path(staging) / f"{prefix}.zip"
        with urllib.request.urlopen(url, timeout=30) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive) as downloaded:
            if downloaded.testzip() is not None:
                raise ValueError("Downloaded ZIP failed its integrity check")
        # Publish atomically, refusing to replace an existing file even in a race.
        os.link(archive, destination)
    print(f"Downloaded {url}\nSaved to {destination}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: download-lab.py ROOT [lab|project]")
    kind = sys.argv[2] if len(sys.argv) == 3 else "lab"
    try:
        download(Path(sys.argv[1]), kind)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        sys.exit(f"cmsc216: Could not download next {kind}: {error}")
