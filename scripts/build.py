#!/usr/bin/env python3
"""Build a portable static site and skill bundle using only Python's standard library."""
import argparse
import html
import json
import re
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / 'skills/worth-using'
SKILL_FILES = ('SKILL.md', 'references/rubric.md', 'references/delegated-runs.md', 'references/usefulness-card.schema.json', 'references/coaching-session.v1.md', 'LICENSE.md')
RATINGS = ('Missing', 'Partial', 'Solid')
GRADES = ('Claimed', 'Seen', 'Repeated')
LEVELS = {1: 'E', 2: 'D', 3: 'S'}


def escape(value):
    return html.escape(str(value), quote=True)


def section(markdown, heading):
    """Return the body of one '## heading' section."""
    match = re.search(rf'^## {re.escape(heading)}\n(.*?)(?=^## |\Z)', markdown, re.M | re.S)
    if not match:
        raise ValueError(f'Missing section: {heading}')
    return match.group(1)


def table_rows(block):
    rows = [line for line in block.splitlines() if line.startswith('|')]
    return [[cell.strip() for cell in row.strip('|').split('|')] for row in rows[2:]]


def bullets(block):
    return [line[2:].split(' | ') for line in block.splitlines() if line.startswith('- ')]


def read_reference(reference, benchmark):
    # The site presents the canonical rubric and method, never a second copy of them.
    questions = re.findall(r'^\d\. (.+)$', section(reference, 'Opening questions'), re.M)
    criteria = bullets(section(reference, 'Six criteria'))
    evidence = bullets(section(reference, 'Evidence'))
    dimensions = bullets(section(reference, 'Five dimensions'))
    moves = bullets(section(reference, 'Teaching moves'))
    diagnosis = table_rows(section(reference, 'Diagnosis'))
    tests = table_rows(section(benchmark, 'Tests'))
    if len(criteria) != 6 or any(len(c) != 5 for c in criteria):
        raise ValueError('Expected six criteria, each with a question and three ratings')
    if [g[0] for g in evidence] != list(GRADES) or any(len(g) != 2 for g in evidence):
        raise ValueError('Expected the three evidence grades in order')
    if len(questions) != 5 or len(dimensions) != 5 or any(len(d) != 4 for d in dimensions):
        raise ValueError('Expected five opening questions and five dimensions with three levels each')
    if len(moves) != 8 or any(len(m) != 3 for m in moves):
        raise ValueError('Expected eight teaching moves with what and where')
    if len(diagnosis) < 5 or any(len(r) != 3 for r in diagnosis) or len(tests) != 12 or any(len(t) != 3 for t in tests):
        raise ValueError('Diagnosis needs three columns; the benchmark needs twelve tests')
    return questions, criteria, evidence, dimensions, moves, diagnosis, tests


def trace_svg(example, names):
    points = example['checkpoints']
    count = len(points)
    left, right, top, row = 132, 620, 34, 56
    xs = [left + i * (right - left) / (count - 1) for i in range(count)]
    level_y = {3: 12, 2: 26, 1: 40}
    parts = []
    breaks = example['round_breaks']
    rounds = [1] + breaks
    for n, start in enumerate(rounds):
        end = (breaks[n] - 1) if n < len(breaks) else count - 2
        start = max(start, 1)
        middle = (xs[start] + xs[end]) / 2
        parts.append(f'<text class="trace-round" x="{middle:.1f}" y="14" text-anchor="middle">Round {n + 1}</text>')
    for b in breaks:
        x = (xs[b - 1] + xs[b]) / 2
        parts.append(f'<path class="trace-break" d="M{x:.1f} 22V{top + 5 * row - 4}"/>')
    dip_number = {}
    for i, dip in enumerate(example['dips'], 1):
        dip_number[(dip['dimension'], dip['at'])] = i
    for r, name in enumerate(names):
        y0 = top + r * row
        values = example['trace'][name]
        if len(values) != count or any(v not in LEVELS for v in values):
            raise ValueError(f'{example["id"]}: {name} needs one level (1-3) per checkpoint')
        parts.append(f'<text class="trace-name" x="0" y="{y0 + 30}">{escape(name)}</text>')
        for level, offset in level_y.items():
            parts.append(f'<path class="trace-level" d="M{left - 8} {y0 + offset}H{right + 8}"/><text class="trace-letter" x="{left - 14}" y="{y0 + offset + 4}" text-anchor="end">{LEVELS[level]}</text>')
        line = ' '.join(f'{xs[i]:.1f},{y0 + level_y[v]}' for i, v in enumerate(values))
        parts.append(f'<polyline class="trace-line" points="{line}"/>')
        for i, v in enumerate(values):
            parts.append(f'<circle class="trace-dot" cx="{xs[i]:.1f}" cy="{y0 + level_y[v]}" r="3.5"/>')
            if (name, i) in dip_number:
                n = dip_number[(name, i)]
                parts.append(f'<circle class="trace-dip" cx="{xs[i]:.1f}" cy="{y0 + level_y[v]}" r="9"/><text class="trace-dip-label" x="{xs[i] + 13:.1f}" y="{y0 + level_y[v] + 4}">{n}</text>')
    for i, label in enumerate(points):
        parts.append(f'<text class="trace-check" x="{xs[i]:.1f}" y="{top + 5 * row + 12}" text-anchor="middle">{escape(label)}</text>')
    for (name, at) in dip_number:
        if not 0 < at < count:
            raise ValueError(f'{example["id"]}: dip outside the run')
        if example['trace'][name][at] >= example['trace'][name][at - 1]:
            raise ValueError(f'{example["id"]}: a labeled dip must be a drop ({name} at {at})')
    height = top + 5 * row + 22
    summary = '; '.join(f'{n} from {LEVELS[example["trace"][n][0]]} to {LEVELS[example["trace"][n][-1]]}' for n in names)
    dips = ' '.join(f'Dip {i}: {d["note"]}' for i, d in enumerate(example['dips'], 1))
    return (f'<div class="trace-scroll"><svg class="trace" viewBox="-4 0 652 {height}" role="img" aria-labelledby="t-{example["id"]} d-{example["id"]}">'
            f'<title id="t-{example["id"]}">{escape(example["label"])}: the builder across {count} checkpoints</title>'
            f'<desc id="d-{example["id"]}">{escape(summary)}. {escape(dips)} Illustrative, not measured.</desc>'
            + ''.join(parts) + '</svg></div>')


def chip(rating, grade):
    if rating not in RATINGS or grade not in GRADES:
        raise ValueError(f'Unknown rating or evidence: {rating}, {grade}')
    return f'<span class="chip r-{rating.lower()}"><b>{escape(rating)}</b><i>{escape(grade)}</i></span>'


def zone(rubric):
    """Apply the skill's zone rule to a run's final ratings."""
    final = {r['criterion']: (r['to'], r['to_ev']) for r in rubric}
    core = ['Job', 'First value', 'Fit', 'Outcome', 'Trust']
    ready = all(final[c][0] == 'Solid' and final[c][1] in ('Seen', 'Repeated') for c in core)
    worth = ready and final['Return'] == ('Solid', 'Repeated')
    return ready, worth


def panel(example, first, criteria):
    hidden = '' if first else ' hidden'
    rubric = example['rubric']
    if [r['criterion'] for r in rubric] != criteria:
        raise ValueError(f'{example["id"]}: rubric rows must follow the six criteria in order')
    rows = ''.join(f'<tr><th scope="row">{escape(r["criterion"])}</th><td>{chip(r["from"], r["from_ev"])}</td><td>{chip(r["to"], r["to_ev"])}</td><td>{escape(r["note"])}</td></tr>' for r in rubric)
    ready, worth = zone(rubric)
    zone_text = ('Worth using' if worth else 'Stranger-ready' if ready else 'No zone yet')
    dips = ''.join(f'<li>{escape(d["note"])}</li>' for d in example['dips'])
    decisions = ''.join(f'<li>{escape(d)}</li>' for d in example['decisions'])
    return (f'<div class="example-content" data-example="{escape(example["id"])}" data-outcome="{escape(example["outcome"])}"{hidden}>'
            f'<p class="example-brief">{escape(example["brief"])}</p>'
            f'<div class="quotes"><p><span>Builder, at the start</span>“{escape(example["started"])}”</p><p><span>Builder, at the end</span>“{escape(example["got_to"])}”</p></div>'
            f'<div class="table-scroll"><table class="run-card"><caption>Usefulness card · zone: <b>{escape(zone_text)}</b></caption><thead><tr><th scope="col">Criterion</th><th scope="col">Start</th><th scope="col">End</th><th scope="col">Why</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'<dl class="run-meta"><dt>Return check</dt><dd>{escape(example["return_check"])}</dd><dt>Cut</dt><dd>{escape(example["cut"])}</dd></dl>'
            f'<details class="experiment-details"><summary>The builder\'s dips, explained</summary><ol class="dip-list">{dips}</ol></details>'
            f'<details class="experiment-details"><summary>Decision log</summary><ul class="decision-list">{decisions}</ul></details>'
            f'<p class="example-direction">Next time: {escape(example["next"])}</p></div>')


def build(output):
    site = ROOT / 'site'
    config = json.loads((site / 'site.json').read_text(encoding='utf-8'))
    skill = (SKILL_DIR / 'SKILL.md').read_text(encoding='utf-8')
    reference = (SKILL_DIR / 'references/rubric.md').read_text(encoding='utf-8')
    benchmark = (ROOT / 'docs/BENCHMARK.md').read_text(encoding='utf-8')
    questions, criteria, evidence, dimensions, moves, diagnosis, tests = read_reference(reference, benchmark)
    names = config['dimensions']
    if names != [d[0] for d in dimensions]:
        raise ValueError('site.json dimensions must match the rubric reference')
    criteria_names = [c[0] for c in criteria]
    if config['criteria'] != criteria_names:
        raise ValueError('site.json criteria must match the rubric reference')
    examples = config['examples']
    if len(examples) < 2 or len({e['id'] for e in examples}) != len(examples):
        raise ValueError('At least two distinct fictional examples are required')
    if not any(e['dips'] for e in examples):
        raise ValueError('At least one example must show a dip')
    replacements = {
        'NAME': escape(config['name']),
        'DESCRIPTION': escape(config['description']),
        'FIRST_OUTCOME': escape(examples[0]['outcome']),
        'EXAMPLE_OPTIONS': ''.join(f'<option value="{escape(e["id"])}">{escape(e["label"])}</option>' for e in examples),
        'TRACES': ''.join(f'<div class="trace-panel" data-example="{escape(e["id"])}"{"" if i == 0 else " hidden"}>{trace_svg(e, names)}</div>' for i, e in enumerate(examples)),
        'EXAMPLE_PANELS': ''.join(panel(e, i == 0, criteria_names) for i, e in enumerate(examples)),
        'CRITERIA': ''.join(f'<li><h3>{escape(n)}</h3><p class="criterion-q">{escape(q)}</p><p><span class="mobile-axis-label">Missing</span>{escape(m)}</p><p><span class="mobile-axis-label">Partial</span>{escape(p)}</p><p><span class="mobile-axis-label">Solid</span>{escape(so)}</p></li>' for n, q, m, p, so in criteria),
        'EVIDENCE': ''.join(f'<li class="grade g-{escape(g.lower())}"><b>{escape(g)}</b><span>{escape(d)}</span></li>' for g, d in evidence),
        'SCORER_ROWS': ''.join(f'<tr><th scope="row" id="c{i}">{escape(n)}<span>{escape(q)}</span></th><td><select data-criterion="{escape(n)}" data-kind="rating" aria-labelledby="c{i} rating-head">' + ''.join(f'<option>{r}</option>' for r in RATINGS) + f'</select></td><td><select data-criterion="{escape(n)}" data-kind="grade" aria-labelledby="c{i} grade-head">' + ''.join(f'<option>{g}</option>' for g in GRADES) + '</select></td></tr>' for i, (n, q, *_rest) in enumerate(criteria)),
        'DIMENSIONS': ''.join(f'<li><h3>{escape(n)}</h3><p><span class="mobile-axis-label">Early</span>{escape(e)}</p><p><span class="mobile-axis-label">Developing</span>{escape(d)}</p><p><span class="mobile-axis-label">Strong</span>{escape(s)}</p></li>' for n, e, d, s in dimensions),
        'MOVES': ''.join(f'<li><div><b>{escape(m)}</b> {escape(what)}<span class="move-where">{escape(where)}</span></div></li>' for m, what, where in moves),
        'QUESTIONS': ''.join(f'<li>{escape(q)}</li>' for q in questions),
        'DIAGNOSIS': ''.join(f'<tr><td>{escape(a)}</td><td>{escape(b)}</td><td class="return-to">{escape(c)}</td></tr>' for a, b, c in diagnosis),
        'BENCHMARK': ''.join(f'<tr><th scope="row">{escape(a)}</th><td>{escape(b)}</td><td>{escape(c)}</td></tr>' for a, b, c in tests),
        'SKILL_SOURCE': escape(skill),
    }
    page = (site / 'template.html').read_text(encoding='utf-8')
    for key, value in replacements.items():
        page = page.replace('@@' + key + '@@', value)
    if re.search(r'@@[A-Z_]+@@', page):
        raise ValueError('Unresolved template placeholder')
    if output.exists():
        shutil.rmtree(output)
    assets = output / 'assets'
    assets.mkdir(parents=True)
    (output / 'index.html').write_text(page, encoding='utf-8')
    shutil.copy2(site / 'theme/style.css', assets / 'family.css')
    shutil.copy2(site / 'style.css', assets / 'style.css')
    shutil.copy2(site / 'site.js', assets / 'site.js')
    shutil.copy2(site / 'theme/LICENSE', assets / 'family-LICENSE.txt')
    for asset in sorted((site / 'assets').iterdir()):
        if asset.is_file():
            shutil.copy2(asset, assets / asset.name)
    # Publish the skill at the site root (stable download links) and at its source
    # path (so README links work both on GitHub and on the site).
    for name in SKILL_FILES:
        for target in (output / name, output / SKILL_DIR.relative_to(ROOT) / name):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SKILL_DIR / name, target)
    documentation = ['README.md', 'LICENSE', 'CHANGELOG.md', 'site/README.md', 'site/theme/LICENSE']
    documentation.extend(str(path.relative_to(ROOT)) for path in sorted((ROOT / 'docs').glob('*.md')))
    for name in documentation:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (output / '.nojekyll').touch()
    # Fixed archive metadata makes download contents reproducible across builds.
    with ZipFile(output / 'worth-using.zip', 'w', ZIP_DEFLATED) as bundle:
        for name in SKILL_FILES:
            info = ZipInfo('worth-using/' + name, (2026, 10, 23, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, (SKILL_DIR / name).read_bytes())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '_site', help='Static output directory (default: _site)')
    args = parser.parse_args()
    print(f'Built {build(args.output.resolve())}')
