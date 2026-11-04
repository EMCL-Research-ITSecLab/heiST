"""Student challenge contracts, including transactional grading and owner checks."""
from flask import Blueprint, request

from .context import body, internal, rate_limit, repository, require_user
from .errors import ApiError
from .validation import positive_id, text

blueprint = Blueprint('challenges', __name__)
MAX_EXTENSIONS = 6


def visible_challenge(user, template_id):
    value = repository().call('get_challenge_template_details', template_id, one=True)
    if value is None:
        raise ApiError('Challenge not found', 404)
    if not value['is_active'] or value['marked_for_deletion']:
        privileged = user['is_admin'] or user['id'] == value['creator_id']
        previous = repository().scalar('get_challenge_user_status', user['id'], template_id) != 'not_tried'
        if not privileged and not previous:
            raise ApiError('Challenge not found', 404)
    return value


def timing(user_id, template_id):
    used = repository().scalar('get_remaining_extensions_for_user_challenge', user_id, template_id)
    return {'elapsed_seconds': max(0, repository().scalar('get_elapsed_seconds_for_challenge', user_id, template_id) or 0),
            'remaining_seconds': max(0, repository().scalar('get_remaining_seconds_for_user_challenge', user_id, template_id) or 0),
            'remaining_extensions': max(0, MAX_EXTENSIONS-used) if used is not None else 0}


@blueprint.get('/challenge')
def get_challenge():
    user = require_user()
    template_id = positive_id(request.args.get('id'), 'challenge identifier')
    value = visible_challenge(user, template_id)
    status = repository().scalar('get_challenge_user_status', user['id'], template_id)
    progress = repository().call('get_solve_progress_data', user['id'], template_id, one=True)
    flags = repository().call('get_challenge_flags', template_id)
    completed = {item['flag_id'] for item in repository().call('get_completed_flag_ids_for_user', user['id'], template_id)}
    points = sum(item['points'] for item in flags if item['id'] in completed)
    value.update(challenge_status={'challenge_status': status}, isSolved=progress['is_solved'],
                 flags_submitted=progress['flags_completed'], flags_total=progress['total_flags'],
                 user_points=points, challenge_points=sum(item['points'] for item in flags),
                 solution=repository().scalar('get_challenge_solution', template_id) if progress['is_solved'] else None,
                 hints=repository().call('get_unlocked_challenge_hints', template_id, points),
                 entrypoints=[str(item['subnet']) for item in repository().call('get_entrypoints_for_user_challenge', user['id'])] if status == 'running' else [],
                 leaderboard=repository().call('get_solved_leaderboard', template_id), **timing(user['id'], template_id))
    # Flag values are private grading material and never enter the browser response.
    return {'success': True, 'challenge': value}


def award_badges(user_id, template):
    repo = repository()
    eligible = []
    if repo.scalar('is_first_blood', template['id'], user_id):
        eligible.append((7, 'First Blood'))
    elapsed = repo.scalar('get_elapsed_seconds_for_challenge', user_id, template['id'])
    if elapsed is not None and 0 < elapsed <= 300:
        eligible.append((8, 'Speed Runner'))
    categories = {'web': (1, 'Web Warrior'), 'crypto': (2, 'Crypto Expert'), 'reverse': (3, 'Reverse Engineer'),
                  'forensics': (4, 'Forensic Analyst'), 'pwn': (5, 'Binary Buster'), 'misc': (6, 'Puzzle Master')}
    if repo.scalar('get_user_solved_challenges_in_category', user_id, template['category']) >= 5:
        eligible.append(categories[template['category']])
    result = []
    for badge_id, name in eligible:
        if repo.scalar('badge_with_id_exists', badge_id) and not repo.scalar('user_already_has_badge', user_id, badge_id):
            repo.call('award_badge_to_user', user_id, badge_id)
            result.append(name)
    if repo.scalar('badge_with_id_exists', 9) and not repo.scalar('user_already_has_badge', user_id, 9) and repo.scalar('count_user_badges_excluding_one', user_id, 9) == 0:
        repo.call('award_badge_to_user', user_id, 9)
        result.append('Master Hacker')
    return result


def submit_flag(user, template, submitted):
    flag = text(submitted, name='Flag', minimum=1, maximum=4096).strip()
    if not flag:
        raise ApiError('Enter a flag')
    repo = repository()
    with repo.transaction():
        # Serialize completion and First Blood across students, including when
        # their final flags differ. The lock ends with this grading transaction.
        repo.call('web_challenge_grade_lock', template['id'])
        record = repo.call('validate_and_lock_flag', template['id'], flag, user['id'], one=True)
        if record is None:
            raise ApiError('Incorrect flag')
        if repo.scalar('is_duplicate_flag_submission', user['id'], template['id'], record['id']):
            raise ApiError('You already submitted this flag', 409)
        count = repo.scalar('get_user_submitted_flags_count_for_challenge', user['id'], template['id'])
        total = repo.scalar('get_total_flags_count_for_challenge', template['id'])
        complete = count+1 >= total
        active = repo.scalar('get_active_attempt_id', user['id'], template['id'])
        if active is not None:
            if complete:
                repo.call('update_running_attempt', record['id'], active)
            else:
                repo.call('create_new_completed_attempt', user['id'], template['id'], record['id'])
        else:
            recent = repo.scalar('get_recent_unflagged_attempt', user['id'], template['id'])
            if recent is not None:
                repo.call('update_recent_attempt', record['id'], recent)
            else:
                repo.call('create_new_completed_attempt', user['id'], template['id'], record['id'])
        badges = award_badges(user['id'], template) if complete else []
    return {'success': True, 'message': 'Flag accepted! You earned '+str(record['points'])+' points!', 'badges': badges, 'is_complete': complete}


def deploy(user, template):
    if template['marked_for_deletion'] or (not template['is_active'] and not user['is_admin'] and template['creator_id'] != user['id']):
        raise ApiError('This challenge is currently unavailable', 409)
    repo = repository()
    if repo.scalar('get_user_running_challenge', user['id']) is not None:
        raise ApiError('Stop your running challenge before starting another one', 409)
    response = internal().request('start', {'user_id': user['id'], 'challenge_template_id': template['id']})
    with repo.transaction():
        repo.call('create_new_challenge_attempt', user['id'], template['id'])
        repo.call('start_user_network_trace', user['id'], template['id'])
    return {'success': True, 'message': 'Challenge started', 'entrypoints': response.get('entrypoints', []), **timing(user['id'], template['id'])}


def cancel(user, template_id):
    repo = repository()
    if repo.scalar('get_challenge_user_status', user['id'], template_id) != 'running':
        raise ApiError('You do not have this challenge running', 409)
    internal().request('stop', {'user_id': user['id']})
    # The platform service closes attempts/traces atomically with unassignment.
    # Template/VM teardown belongs to the platform cleanup service. Never delete
    # a retired template from a student request while instances still exist.
    return {'success': True, 'message': 'Challenge stopped'}


def extend(user, template_id):
    repo = repository()
    with repo.transaction():
        record = repo.call('get_id_and_used_extensions_of_running_challenge', user['id'], template_id, one=True)
        if not record or (repo.scalar('get_remaining_seconds_for_user_challenge', user['id'], template_id) or 0) <= 0:
            raise ApiError('You do not have this challenge running', 409)
        if record['used_extensions'] >= MAX_EXTENSIONS:
            raise ApiError('No time extensions remain', 409)
        repo.call('extend_user_challenge_time', record['id'], 1)
        result = timing(user['id'], template_id)
    return {'success': True, 'message': 'Challenge time extended by one hour', **result}


@blueprint.post('/challenge')
def update_challenge():
    user = require_user()
    value = body()
    template_id = positive_id(value.get('challenge_id'), 'challenge identifier')
    action = value.get('action')
    if action not in ('deploy', 'cancel', 'submit_flag', 'extend_time'):
        raise ApiError('Invalid challenge action')
    rate_limit('challenge-'+action, str(user['id']), 60 if action == 'submit_flag' else 20)
    template = visible_challenge(user, template_id)
    if action == 'submit_flag':
        return submit_flag(user, template, value.get('flag'))
    if action == 'deploy':
        return deploy(user, template)
    if action == 'cancel':
        return cancel(user, template_id)
    return extend(user, template_id)
