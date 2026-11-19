"""Administrator grading uses the student verifier and records attribution atomically."""
import csv
import io

from flask import Response, request
from .administration import blueprint
from .context import body, rate_limit, repository, require_admin
from .validation import positive_id, text
from .errors import ApiError
from .challenges import submit_flag, visible_challenge


def csv_cell(value):
    value = '' if value is None else str(value)
    return "'"+value if value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@')) else value


@blueprint.post('/admin/grading/submissions')
def submit():
    actor=require_admin();rate_limit('admin-grading',str(actor['id']),30)
    data=body();user_id=positive_id(data.get('user_id'),'user identifier')
    reason=text(data.get('reason'),name='Reason',minimum=10,maximum=500).strip()
    if len(reason)<10:raise ApiError('Describe why assistance is needed')
    target=repository().call('web_admin_grading_user',actor['id'],user_id,one=True)
    if target is None:raise ApiError('User not found',404)
    if data.get('confirmation')!=target['username']:raise ApiError('Type the student username to confirm')
    template=visible_challenge(actor,positive_id(data.get('challenge_id'),'challenge identifier'))
    return submit_flag(target,template,data.get('flag'),administrator=actor['id'],reason=reason)


@blueprint.get('/admin/grading/submissions.csv')
def export():
    actor=require_admin();rate_limit('admin-export',str(actor['id']),10)
    template=positive_id(request.args['challenge_id'],'challenge identifier') if request.args.get('challenge_id') else 0
    moodle=request.args.get('format')=='moodle'
    if moodle and not template:raise ApiError('Choose one challenge for a Moodle grade import')
    output=io.StringIO(newline='');writer=csv.writer(output)
    records=[];after=0
    while True:
        batch=repository().call('web_admin_submission_export',actor['id'],template,after)
        records.extend(batch)
        if len(records)>100000:raise ApiError('Export is too large; select one challenge',413)
        if len(batch)<1000:break
        after=batch[-1]['submission_id']
    if moodle:
        writer.writerow(['Username','Email address','Grade'])
        users={};seen=set()
        for item in records:
            grade=users.setdefault(item['user_id'],[item['username'],item['email'],0])
            key=(item['user_id'],item['flag_id'])
            if key not in seen:grade[2]+=item['points'];seen.add(key)
        for grade in users.values():writer.writerow(map(csv_cell,grade))
    else:
        columns=['submission_id','user_id','username','email','challenge_id','challenge','flag_id','points','completed_at','administrator','reason']
        writer.writerow(columns)
        for item in records:writer.writerow(csv_cell(item[column]) for column in columns)
    return Response(output.getvalue(),content_type='text/csv; charset=utf-8',headers={
        'Content-Disposition':'attachment; filename="heist-'+('moodle-grades' if moodle else 'submissions')+'.csv"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
