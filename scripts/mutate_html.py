"""Reproduce the assignment's mutations without adding a parser dependency."""
from html import escape
from pathlib import Path
import argparse
import re

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
html = args.source.read_text()
html = html.replace('class="original-field"', 'class="renamed-by-portal"')
blocks = re.findall(r'  <div class="renamed-by-portal">.*?</div>', html)
if blocks:
    for block in blocks:
        html = html.replace(block, "", 1)
    html = html.replace("</form>", "\n".join(reversed(blocks)) + "\n</form>")
args.destination.parent.mkdir(parents=True, exist_ok=True)
args.destination.write_text('<!doctype html><html><body><div class="new-wrapper"><iframe title="Moved form" srcdoc="' + escape(html, quote=True) + '"></iframe></div></body></html>')
print(args.destination)
