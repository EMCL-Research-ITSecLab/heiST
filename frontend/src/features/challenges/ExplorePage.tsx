import { useI18n } from '../../lib/i18n.tsx';
import { useState } from 'react';
import {
  ChallengeCard,
  Empty,
  Field,
  PageTitle,
  Pager,
  ResourceState,
  Select,
} from '../../components/ui.tsx';
import { categories, number, payload, row, rows, text } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';
export function Explore() {
  const { t } = useI18n();
  const [search, setSearch] = useState(''),
    [query, setQuery] = useState(''),
    [category, setCategory] = useState('all'),
    [difficulty, setDifficulty] = useState('all'),
    [sort, setSort] = useState('popularity'),
    [page, setPage] = useState(1);
  const params = new URLSearchParams({
    search: query,
    category,
    difficulty,
    sort,
    page: String(page),
  });
  const resource = useResource('/api/explore?' + params),
    data = payload(resource.data),
    challenges = rows(data.challenges ?? data.data),
    pagination = row(data.pagination);
  return (
    <>
      <PageTitle
        eyebrow={t('library.challengeLibrary')}
        title={t('navigation.challenges')}
        description={t('library.browseExercisesByCategoryAndDifficulty')}
      />
      <form
        className="filter-bar"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(search);
          setPage(1);
        }}
      >
        <Field
          label={t('library.searchChallenges')}
          placeholder={t('library.identityCryptographyWeb')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Select
          label={t('common.labels.category')}
          value={category}
          options={['all', ...categories]}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(1);
          }}
        />
        <Select
          label={t('authoring.difficulty')}
          value={difficulty}
          options={['all', 'easy', 'medium', 'hard']}
          onChange={(e) => {
            setDifficulty(e.target.value);
            setPage(1);
          }}
        />
        <Select
          label={t('library.sortBy')}
          value={sort}
          options={['popularity', 'date', 'difficulty']}
          onChange={(e) => {
            setSort(e.target.value);
            setPage(1);
          }}
        />
        <button type="submit">{t('common.actions.search')}</button>
      </form>
      <ResourceState {...resource}>
        <div className="section-heading">
          <p className="muted">
            {number(pagination.total_items ?? data.total_items ?? challenges.length)}
            {' ' + t('library.challengesToExplore')}
          </p>
          <span className="view-label">
            {t('library.library') + ' '}
            {category.toUpperCase()}
          </span>
        </div>
        {challenges.length ? (
          <div className="challenge-grid">
            {challenges.map((c) => (
              <ChallengeCard key={text(c.id)} challenge={c} />
            ))}
          </div>
        ) : (
          <Empty title={t('authoring.noMatchingChallenges')}>
            {t('library.tryADifferentSearchOrCategory')}
          </Empty>
        )}
        <Pager
          page={page}
          totalPages={number(pagination.total_pages ?? data.total_pages) || 1}
          onPage={setPage}
        />
      </ResourceState>
    </>
  );
}
