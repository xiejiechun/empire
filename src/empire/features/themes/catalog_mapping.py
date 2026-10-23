"""Map verified protobuf content to history rows; does not certify transport."""
from empire.features.themes.history_model import directory


def history_rows(catalog, *, max_rows=12000):
    rows = []
    for theme in catalog.themes:
        rows.append({'theme_id': theme.theme_id, 'source_theme_id': theme.theme_id,
                     'concept_id': None, 'name': theme.name, 'parent_id': None,
                     'rank_no': theme.rank_no, 'display_order': len(rows),
                     'new_flag': theme.new_flag, 'hot_score': theme.hot_score,
                     'change_rate': theme.ratio, 'limit_up_count': theme.limit_up_count})
        for child in theme.concepts:
            rows.append({'theme_id': f'{theme.theme_id}_{child.cid}',
                         'source_theme_id': theme.theme_id, 'concept_id': child.cid,
                         'name': child.name, 'parent_id': theme.theme_id,
                         'rank_no': None, 'display_order': len(rows), 'new_flag': 0,
                         'hot_score': None, 'change_rate': child.ratio,
                         'limit_up_count': child.limit_up_count})
    return list(directory(rows, max_rows=max_rows).values())
