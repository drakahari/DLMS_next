"""Read-only filtering and bounded rendering of an already calculated scan."""

from math import ceil
from urllib.parse import urlencode


GROUPS_PER_PAGE = 20


def duplicate_report_view(report, args):
    """Preserve detection/order and paginate groups before template rendering."""
    quiz = str(args.get('quiz') or '')
    folder = str(args.get('folder') or '')
    search = str(args.get('search') or '').strip()
    result_type = str(args.get('result_type') or 'all')
    if result_type not in {'all', 'exact', 'possible'}:
        result_type = 'all'
    needle = search.casefold()
    all_groups = [('exact', group, group['questions']) for group in report['exact_groups']]
    all_groups += [
        ('near', group, group['left']['questions'] + group['right']['questions'])
        for group in report['near_groups']
    ]
    quizzes = {}
    folders = set()
    matches = []
    for kind, group, records in all_groups:
        for record in records:
            quizzes[record['quiz_id']] = record['quiz_title']
            folders.add(record['folder'])
        if result_type != 'all' and kind != ('near' if result_type == 'possible' else 'exact'):
            continue
        if quiz and not any(str(record['quiz_id']) == quiz for record in records):
            continue
        if folder and not any(record['folder'] == folder for record in records):
            continue
        if needle and not any(
            needle in record['question_text'].casefold() or
            needle in record['quiz_title'].casefold() for record in records
        ):
            continue
        matches.append((kind, group))
    pages = max(1, ceil(len(matches) / GROUPS_PER_PAGE))
    try:
        page = min(pages, max(1, int(args.get('page', 1))))
    except (TypeError, ValueError):
        page = 1
    start = (page - 1) * GROUPS_PER_PAGE
    visible = matches[start:start + GROUPS_PER_PAGE]

    def page_url(number):
        return '/library/duplicates?' + urlencode({
            'result_type': result_type,
            'quiz': quiz, 'folder': folder, 'search': search, 'page': number,
        })

    result_labels = {
        'all': ('matching group', 'matching groups'),
        'exact': ('exact duplicate group', 'exact duplicate groups'),
        'possible': ('possible match', 'possible matches'),
    }

    return {
        'report': {**report,
                   'exact_groups': [group for kind, group in visible if kind == 'exact'],
                   'near_groups': [group for kind, group in visible if kind == 'near']},
        'duplicate_view': {
            'quiz': quiz, 'folder': folder, 'search': search,
            'result_type': result_type,
            'result_label': result_labels[result_type][len(matches) != 1],
            'quizzes': sorted(quizzes.items(), key=lambda item: (item[1].casefold(), item[0])),
            'folders': sorted(folders, key=str.casefold),
            'matched_count': len(matches), 'total_count': len(all_groups),
            'page': page, 'pages': pages, 'start': start + 1 if matches else 0,
            'end': min(start + GROUPS_PER_PAGE, len(matches)),
            'expanded': len(all_groups) <= GROUPS_PER_PAGE,
            'previous_url': page_url(page - 1) if page > 1 else None,
            'next_url': page_url(page + 1) if page < pages else None,
        },
    }
