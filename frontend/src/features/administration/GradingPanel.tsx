import {useState, type FormEvent} from 'react';
import {Card, Field, Notice, ResourceState, Select} from '../../components/ui.tsx';
import {request} from '../../lib/api.ts';
import {number, payload, rows, text} from '../../lib/data.ts';
import {useAction, useResource} from '../../lib/state.tsx';

export function GradingPanel() {
  const resource=useResource('/api/admin/challenges'), action=useAction();
  const [challenge,setChallenge]=useState(''),[flag,setFlag]=useState('');
  const options: [string,string][]=[['','Choose a challenge'],...rows(payload(resource.data).challenges).map(c=>[text(c.id),text(c.name)] as [string,string])];
  function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();const values=new FormData(event.currentTarget);
    void action.run(()=>request('/api/admin/grading/submissions',{method:'POST',body:{user_id:number(values.get('user_id')),challenge_id:number(challenge),flag,
      confirmation:text(values.get('confirmation')),reason:text(values.get('reason'))}}),()=>setFlag(''));
  }
  return <><Notice error={action.error} message={action.message}/><ResourceState {...resource}>
    <Card title="Export grades">
      <Select label="Grading challenge" value={challenge} options={options} onChange={event=>setChallenge(event.target.value)}/>
      <div className="button-row">
        <button className="secondary" disabled={action.busy} onClick={()=>void action.run(()=>request('/api/admin/grading/submissions.csv'+(challenge?'?challenge_id='+challenge:''),{download:true}))}>Export submissions CSV</button>
        <button className="secondary" disabled={!challenge||action.busy} onClick={()=>void action.run(()=>request('/api/admin/grading/submissions.csv?format=moodle&challenge_id='+challenge,{download:true}))}>Export Moodle grades</button>
      </div>
      <p className="muted">Submissions include accepted flag IDs and points, without flag secrets. Moodle exports total points per student for the selected challenge. Match Username or Email address during Moodle import and map Grade to the intended grade item. Students with no submissions are omitted.</p>
    </Card>
    <Card title="Submit a flag for a student"><form onSubmit={submit}>
      <p>The flag is checked normally. The administrator and reason are recorded with the submission.</p>
      <Field label="Student user ID" name="user_id" type="number" min={1} required/>
      <Field label="Student username confirmation" name="confirmation" required autoComplete="off"/>
      <Field label="Student flag" type="password" value={flag} onChange={event=>setFlag(event.target.value)} required autoComplete="off" maxLength={4096}/>
      <Field label="Reason for assisted submission" name="reason" required minLength={10} maxLength={500}/>
      <button disabled={!challenge||action.busy}>Submit for student</button>
    </form></Card>
  </ResourceState></>;
}
