"""Compile authoritative help fragments before release; gate checks never rewrite them."""
import argparse
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from empire.plugins.ui.help_content import Article, parse_articles

if __package__:
    from .release_identity import files, owned, write_json
else:
    from release_identity import files, owned, write_json

SOURCE_INDEX = 'src/empire/documentation/help-index.json'
REFERENCE = 'src/empire/plugins/ui/storage_reference.md'
GENERATED_HEADER = (
    '<!-- GENERATED: do not edit. Authoritative fragments: '
    'src/empire/documentation/help-index.json; '
    'run python scripts/documentation_build.py generate before release freeze. -->\n\n'
)
FEATURE_PATH = re.compile(r'src/empire/features/([a-z][a-z0-9_]*)/docs/help/[a-z0-9_-]+\.md')
SHARED_PATH = re.compile(r'src/empire/documentation/topics/[a-z0-9_-]+\.md')


@dataclass(frozen=True)
class HelpBundle:
    content: bytes
    articles: tuple[Article, ...]
    inputs: dict[str, str]
    origins: dict[str, dict[str, str]]

    def evidence(self):
        return {'schema': 1, 'sources': self.inputs, 'origins': self.origins,
                'aggregate': REFERENCE,
                'aggregate_sha256': hashlib.sha256(self.content).hexdigest(),
                'topics': [article.title for article in self.articles]}


def _path(root, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
            or PurePosixPath(name).as_posix() != name):
        raise ValueError('Invalid help source path: ' + repr(name))
    return owned(root, root / name)


def _document_links(text, name):
    """Offline reader only follows help: links; repository guides own file links."""
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        line = re.sub(r'(`+).*?\1', 'CODE', line)
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]*)\)', line):
            if not target.startswith('help:'):
                raise ValueError(f'Offline help requires a help: topic link: {name}: {target}')


def _fragment_files(root):
    """Discover recursively so an invalid nested source cannot evade the index."""
    folders = [root / 'src/empire/documentation/topics',
               *(root / 'src/empire/features').glob('*/docs/help')]
    discovered = set()
    for folder in folders:
        # The shared release walker rejects links/junctions before descending.
        for path in files(_path(root, folder.relative_to(root).as_posix()), source=False):
            if path.suffix.casefold() != '.md':
                continue
            name = path.relative_to(root).as_posix()
            if not (FEATURE_PATH.fullmatch(name) or SHARED_PATH.fullmatch(name)):
                raise ValueError('Invalid help source path: ' + name)
            discovered.add(name)
    return discovered


def compile_help(root):
    root = Path(root).resolve()
    index_bytes = _path(root, SOURCE_INDEX).read_bytes()
    index = json.loads(index_bytes)
    if (not isinstance(index, dict) or set(index) != {'schema', 'sources'}
            or type(index['schema']) is not int or index['schema'] != 1
            or not isinstance(index['sources'], list) or not index['sources']):
        raise ValueError('Invalid help source index')
    inputs = {SOURCE_INDEX: hashlib.sha256(index_bytes).hexdigest()}
    chunks, origins, seen = [], {}, set()
    for entry in index['sources']:
        if (not isinstance(entry, dict) or set(entry) != {'owner', 'path'}
                or not isinstance(entry['owner'], str) or not isinstance(entry['path'], str)):
            raise ValueError('Invalid help source declaration')
        owner, name = entry['owner'], entry['path']
        feature = FEATURE_PATH.fullmatch(name)
        if not ((feature and owner == feature[1]) or (owner == 'shared' and SHARED_PATH.fullmatch(name))):
            raise ValueError('Help source has no matching business owner: ' + name)
        if name.casefold() in seen:
            raise ValueError('Duplicate or case-colliding help source: ' + name)
        seen.add(name.casefold())
        raw = _path(root, name).read_bytes()
        inputs[name] = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8').replace('\r\n', '\n')
        if '\r' in text:
            raise ValueError('Help source contains bare carriage returns: ' + name)
        matches = list(re.finditer(r'^<!-- topic:([^|\n]+)\|([^\n]+) -->$', text, re.M))
        if (len(matches) != 1 or matches[0].start() != 0 or text.count('<!-- topic:') != 1
                or text.count('<!-- summary:') != 1 or text.count('<!-- group:') > 1):
            raise ValueError('Each help source must own exactly one complete topic: ' + name)
        title = matches[0][2]
        if title in origins:
            raise ValueError('Duplicate help topic: ' + title)
        origins[title] = dict(owner=owner, path=name)
        _document_links(text, name)
        chunks.append(text.rstrip() + '\n')
    # No topic is silently omitted just because someone forgot the index entry.
    discovered = _fragment_files(root)
    expected = set(inputs) - {SOURCE_INDEX}
    if discovered != expected:
        raise ValueError('Help source index differs from fragment files: '
                         + ', '.join(sorted(discovered ^ expected)))
    content = (GENERATED_HEADER + '\n'.join(chunks)).encode('utf-8')
    values = tuple(parse_articles(content.decode('utf-8')))
    if [article.title for article in values] != list(origins):
        raise ValueError('Help fragment order differs from parsed topic order')
    return HelpBundle(content, values, inputs, origins)


def check_generated(root):
    root = Path(root).resolve()
    bundle = compile_help(root)
    target = _path(root, REFERENCE)
    if not target.is_file() or target.read_bytes() != bundle.content:
        raise RuntimeError('Offline help aggregate is stale; edit the authoritative fragments, then run '
                           'python scripts/documentation_build.py generate before release freeze')
    return bundle


def generate(root):
    root = Path(root).resolve()
    bundle = compile_help(root)
    target = _path(root, REFERENCE)
    # Do not change file timestamps for a no-op generation.
    if target.is_file() and target.read_bytes() == bundle.content:
        return bundle
    temporary = _path(root, REFERENCE + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as output:
            output.write(bundle.content)
            output.flush()
            os.fsync(output.fileno())
        if compile_help(root) != bundle:
            raise RuntimeError('Help source changed during generation; retry after edits finish')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('generate', 'check'))
    parser.add_argument('--report', type=Path, help='Check evidence path; relative paths are below workspace build/')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.report is not None and args.action != 'check':
        parser.error('--report belongs to check; generation must finish before release freeze')
    bundle = generate(root) if args.action == 'generate' else check_generated(root)
    if args.report is not None:
        destination = args.report if args.report.is_absolute() else root / 'build' / args.report
        report = owned(root / 'build', destination)
        report.parent.mkdir(parents=True, exist_ok=True)
        owned(root / 'build', report)
        write_json(report, bundle.evidence())
    print(f'PASS offline help {args.action}: {len(bundle.articles)} topics')


if __name__ == '__main__':
    main()
