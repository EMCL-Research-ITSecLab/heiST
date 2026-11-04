"""Read-only student learning views backed by the existing graded-data procedures."""
from datetime import timedelta
import math

from flask import Blueprint, current_app, g, request
from .context import repository, require_user
from .errors import ApiError
from .validation import choice, positive_id, text

blueprint = Blueprint('learning', __name__)
CATEGORIES = ('web', 'crypto', 'forensics', 'reverse', 'pwn', 'misc')
DIFFICULTIES = ('easy', 'medium', 'hard')
RANGES = ('all', 'today', 'week', 'month', 'year')


def pagination(size=12):
    page = positive_id(request.args.get('page', '1'), 'page')
    if page > 10000:
        raise ApiError('Page is out of range')
    return page, size, (page-1)*size


def optional_filter(name, allowed):
    value = choice(request.args.get(name, 'all'), ('all', *allowed), name)
    return None if value == 'all' else value


def challenge_card(value, user_id=None):
    result = dict(value)
    result['title'] = value['name']
    result['image'] = value.get('image_path') or '/assets/images/ctf-default.png'
    if user_id:
        result['solved'] = bool(repository().scalar('get_user_solved_challenge', user_id, value['id']))
    else:
        result['solved'] = False
    return result


@blueprint.get('/explore')
def explore():
    page, size, offset = pagination()
    category = optional_filter('category', CATEGORIES)
    difficulty = optional_filter('difficulty', DIFFICULTIES)
    sort = choice(request.args.get('sort', 'popularity'), ('popularity', 'date', 'difficulty'), 'sort order')
    search = text(request.args.get('search', ''), name='Search', maximum=200)
    pattern = '%'+search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')+'%' if search else None
    total = repository().scalar('explore_challenges_count', category, difficulty, pattern, default=0)
    values = repository().call('explore_challenges', category, difficulty, pattern, sort, size, offset)
    return {'success': True, 'data': {'challenges': [challenge_card(value, g.user['id'] if g.user else None) for value in values],
            'pagination': {'current_page': page, 'per_page': size, 'total_items': total, 'total_pages': max(1, math.ceil(total/size))},
            'filters': {'search': search, 'category': category or 'all', 'difficulty': difficulty or 'all', 'sort': sort}}}


def timeline(user_id, range='week', view='daily'):
    choice(range, ('week', 'month', 'year'), 'timeline range')
    choice(view, ('daily', 'cumulative'), 'timeline view')
    end = current_app.extensions['clock']().date()
    if range == 'year':
        start = end.replace(year=end.year-1, day=1)
    else:
        start = end-timedelta(days=6 if range == 'week' else 29)
    values = repository().call('get_timeline_data_dashboard', user_id, start.isoformat(), end.isoformat(), range, 'YYYY-MM' if range == 'year' else 'YYYY-MM-DD')
    points, counts = [], []
    for value in values:
        points.append(int(value['points_sum'] or 0)+(points[-1] if points and view == 'cumulative' else 0))
        counts.append(int(value['challenge_count'] or 0)+(counts[-1] if counts and view == 'cumulative' else 0))
    return {'labels': [value['date_group'] for value in values], 'points': points, 'challenges': counts,
            'details': [value.get('challenge_details') or '' for value in values]}


@blueprint.get('/dashboard')
def dashboard():
    user = require_user()
    data_type = choice(request.args.get('data_type', 'full'), ('full', 'user', 'progress', 'activity', 'challenges', 'timeline', 'badges', 'news', 'active_challenge'), 'dashboard section')
    if data_type == 'timeline':
        return {'success': True, 'data': timeline(user['id'], request.args.get('range', 'week'), request.args.get('view', 'daily'))}
    record = repository().call('get_user_data_dashboard', user['id'], one=True)
    progress = repository().call('get_progress_data_dashboard', user['id'], one=True) or {}
    solved, attempts = int(progress.get('solved_count') or 0), int(progress.get('total_attempts') or 0)
    running = repository().scalar('get_user_running_challenge', user['id'])
    active = None
    if running is not None:
        template_id = repository().scalar('get_challenge_template_id_from_challenge_id', running)
        active = repository().call('get_running_challenge_data_dashboard', user['id'], template_id, one=True)
    values = {
        'user': {'username': record['username'], 'points': record['total_points'], 'rank': record['user_rank']},
        'progress': {'solved': solved, 'failed': int(progress.get('failed_count') or 0),
                     'success_rate': round(solved/attempts*100) if attempts else 0},
        'activity': [{**value, 'challenge': value['challenge_name']} for value in repository().call('get_user_activity_dashboard', user['id'], 5)],
        'challenges': [challenge_card(value, user['id']) for value in repository().call('get_challenges_data_dashboard', user['id'])],
        'badges': repository().call('get_user_badges_data_dashboard', user['id']),
        'timeline': timeline(user['id']), 'news': repository().call('get_announcements_data_dashboard'), 'active_challenge': active,
    }
    return {'success': True, 'data': values if data_type == 'full' else values[data_type]}


@blueprint.get('/activity')
def activity():
    user = require_user()
    page, size, offset = pagination(10)
    category = optional_filter('category', CATEGORIES)
    kind = choice(request.args.get('type', 'all'), ('all', 'solved', 'failed', 'active', 'badges'), 'activity type')
    range = choice(request.args.get('range', 'all'), RANGES, 'time range')
    values = repository().call('get_user_activities', user['id'], category, kind, range, size, offset)
    count = repository().scalar('get_user_activities_total_count', user['id'], category, kind, range, default=0)
    return {'success': True, 'data': {'activities': [{**value, 'title': value['item_name'], 'type': value['status'], 'timestamp': value['activity_date']} for value in values],
            'total': count, 'total_pages': max(1, math.ceil(count/size)), 'per_page': size, 'page': page}}


@blueprint.get('/badges')
def badges():
    user = require_user()
    values = repository().call('get_user_badges_data', user['id'])
    stats = repository().call('get_total_badge_count_and_user_earned_count', user['id'], one=True) or {}
    total, earned = int(stats.get('total_badges') or 0), int(stats.get('earned_badges') or 0)
    return {'success': True, 'data': {'badges': values, 'stats': {'total': total, 'earned': earned, 'completion_rate': round(earned/total*100) if total else 0}}}


@blueprint.get('/announcements')
def announcements():
    require_user()
    page, size, offset = pagination(10)
    importance = optional_filter('importance', ('normal', 'important', 'critical'))
    range = optional_filter('range', RANGES[1:])
    count = repository().scalar('get_filtered_announcements_count', importance, range, default=0)
    values = repository().call('get_filtered_announcements', importance, range, size, offset)
    return {'success': True, 'data': {'announcements': values, 'total': count, 'total_pages': max(1, math.ceil(count/size)), 'per_page': size, 'page': page}}
