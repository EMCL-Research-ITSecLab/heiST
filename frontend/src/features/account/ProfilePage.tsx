import {useI18n} from '../../lib/i18n.tsx';
import { AchievementIcon } from '../../components/AchievementIcon.tsx';
import { TrainingPreferencePanel } from './TrainingPreferencePanel.tsx';
import { avatarImage } from '../../lib/artwork.ts';
import { useState, type FormEvent } from 'react';
import { ActivityList, Area, Badge, Card, Confirm, Field, Notice, PageTitle, ResourceState, Stat } from '../../components/ui.tsx';
import { post, request } from '../../lib/api.ts';
import { external, payload, row, rows, text } from '../../lib/data.ts';
import { useRouter } from '../../lib/router.tsx';
import { useAction, useResource, useSession } from '../../lib/state.tsx';
export function Profile({ username }: {
  username?: string;
}) {
  const {t}=useI18n();
  const publicView = Boolean(username), resource = useResource(publicView ? '/api/profiles/' + encodeURIComponent(username!) : '/api/profile');
  const data = payload(resource.data), basic = row(data.basic ?? data.profile), stats = row(data.stats), action = useAction(), session = useSession(), router = useRouter();
  const [deleting, setDeleting] = useState(false), [password, setPassword] = useState('');
  async function save(event: FormEvent<HTMLFormElement>, name: string) {
    event.preventDefault();
    const fields = Object.fromEntries(new FormData(event.currentTarget).entries());
    await action.run(() => post('profile', { action: name, ...fields }), async () => { resource.reload(); await session.refresh(); });
  }
  return <>
    <PageTitle eyebrow={t(publicView ? 'PROFILE' : 'YOUR ACCOUNT')} title={text(basic.full_name ?? basic.username, publicView ? username : 'Profile')} description={t(publicView ? 'Challenge progress and achievements.' : 'Manage your identity, connection and account preferences.')} />
    <Notice error={action.error} message={action.message} />
    <ResourceState {...resource}>
      <div className="profile-summary card">
        <img className="avatar large" src={avatarImage(basic.avatar_url)} alt="" />
        <div>
          <h2>
            {text(basic.username)}
          </h2>
          <p className="prose">
            {text(basic.bio, 'Always learning. Always investigating.')}
          </p>
          <div className="button-row">
            {[['GitHub', basic.github_url], ['Social', basic.twitter_url], ['Website', basic.website_url]].map(([label, url]) => external(url) && <a key={text(label)} href={external(url)} rel="noopener noreferrer" target="_blank">
              {text(label)} ↗</a>)}
          </div>
        </div>
      </div>
      <div className="stats-grid">
        <Stat label={t("Total points")} value={basic.total_points ?? stats.total_points} />
        <Stat label={t("Challenges solved")} value={basic.solved_count ?? stats.solved_count} />
        <Stat label={t("Your rank")} value={stats.rank ?? stats.user_rank} />
        <Stat label={t("Achievements")} value={rows(data.badges).length} />
      </div>
      {!publicView && <div className="two-columns">
        <div>
          <Card title={t("Profile details")}>
            <form onSubmit={e => void save(e, 'update_username')}>
              <Field
                label={t("Username")}
                name="username"
                key={text(basic.username)}
                defaultValue={text(basic.username)}
                required
                minLength={3}
                maxLength={20} />
              <button disabled={action.busy}>{t("Save username")}</button>
            </form>
            <form onSubmit={e => void save(e, 'update_email')}>
              <Field
                label={t("Email address")}
                name="email"
                key={text(basic.email)}
                defaultValue={text(basic.email)}
                type="email"
                required />
              <button className="secondary" disabled={action.busy}>{t("Save email")}</button>
            </form>
            <form onSubmit={e => void save(e, 'update_full_name')}>
              <Field
                label={t("Full name")}
                name="full_name"
                key={text(basic.full_name)}
                defaultValue={text(basic.full_name)}
                maxLength={30} />
              <button className="secondary" disabled={action.busy}>{t("Save name")}</button>
            </form>
            <form onSubmit={e => void save(e, 'update_bio')}>
              <Area
                label={t("About you")}
                name="bio"
                key={text(basic.bio)}
                defaultValue={text(basic.bio)}
                maxLength={500} />
              <button className="secondary" disabled={action.busy}>{t("Save biography")}</button>
            </form>
          </Card>
          <Card title={t("Around the web")}>
            <form onSubmit={e => void save(e, 'update_social')}>
              <Field label={t("GitHub URL")} name="github" type="url" defaultValue={text(basic.github_url)} />
              <Field label={t("Social profile URL")} name="twitter" type="url" defaultValue={text(basic.twitter_url)} />
              <Field label={t("Website URL")} name="website" type="url" defaultValue={text(basic.website_url)} />
              <button disabled={action.busy}>{t("Save links")}</button>
            </form>
          </Card>
        </div>
        <div>
          <Card title={t("Your lab connection")}>
            <Badge tone="active">{t("OpenVPN")}</Badge>
            <h3>{t("Take your workspace with you.")}</h3>
            <p className="muted">{t("Download your personal configuration and connect with an OpenVPN client before starting a lab.")}</p>
            <button disabled={action.busy} onClick={() => void action.run(() => post('profile', { action: 'get_vpn_config' }))}>{t("Download VPN configuration ↓")}</button>
          </Card>
          <Card title={t("Choose your avatar")}>
            <div className="avatar-options">
              {['avatar1', 'avatar2', 'avatar3'].map(avatar => <button
                key={avatar}
                className="secondary"
                aria-label={t('Use {avatar}',{avatar})}
                disabled={action.busy}
                onClick={() => void action.run(() => post('profile', { action: 'update_avatar', avatar }), resource.reload)}>
                <img className="avatar" src={`/assets/avatars/${avatar}.png`} alt={avatar} />
              </button>)}
            </div>
            <form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); form.set('action', 'upload_avatar'); void action.run(() => post('profile', form), resource.reload); }}>
              <Field
                label={t("Upload a custom avatar (up to 2 MiB)")}
                name="avatar"
                type="file"
                accept="image/png,image/jpeg,image/gif"
                required
                onChange={e => { const file = e.target.files?.[0]; e.target.setCustomValidity(file && file.size > 2 * 1024 * 1024 ? 'Choose an image smaller than 2 MiB.' : ''); }} />
              <button className="secondary" disabled={action.busy}>{t("Upload avatar")}</button>
            </form>
          </Card>
          <TrainingPreferencePanel />
          <Card title={t("Account security")}>
            <form onSubmit={e => void save(e, 'change_password')}>
              <Field
                label={t("Current password")}
                name="current_password"
                type="password"
                autoComplete="current-password"
                required />
              <Field
                label={t("New password")}
                name="new_password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                maxLength={72}
                required />
              <button disabled={action.busy}>{t("Change password")}</button>
            </form>
          </Card>
          <Card title={t("Delete account")}>
            <p className="muted">{t("Permanently remove your account. Your active environment will be stopped.")}</p>
            <button className="danger subtle" onClick={() => setDeleting(true)}>{t("Delete my account")}</button>
          </Card>
        </div>
      </div>}
      <Card title={t("Recent activity")}>
        <ActivityList items={rows(data.activity)} />
      </Card>
      {rows(data.badges).length > 0 && <Card title={t("Achievements")}>
        <div className="button-row">
          {rows(data.badges).map((badge, i) => <Badge key={i}>
            <AchievementIcon badge={badge} compact />{text(badge.name)}
          </Badge>)}
        </div>
      </Card>}
    </ResourceState>
    {deleting && <Confirm
      title={t("Permanently delete your account?")}
      confirm={t("Delete account")}
      busy={action.busy}
      onClose={() => { setDeleting(false); setPassword(''); }}
      onConfirm={() => void action.run(() => request('/api/profile', { method: 'DELETE', body: { password } }), async () => { await session.refresh(); router.navigate('/landing', true); })}>
      <p>{t("This cannot be undone. Enter your current password to confirm.")}</p>
      <Field
        label={t("Current password")}
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={e => setPassword(e.target.value)}
        required />
      <Notice error={action.error} />
    </Confirm>}
  </>;
}
