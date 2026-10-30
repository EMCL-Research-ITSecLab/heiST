import { useState } from 'react';
import { ChallengeCard,Empty,Field,PageTitle,Pager,ResourceState,Select } from '../../components/ui.tsx';
import { categories,number,payload,row,rows,text } from '../../lib/data.ts';
import { useResource } from '../../lib/state.tsx';
export function Explore() {
    const [search, setSearch] = useState(''), [query, setQuery] = useState(''), [category, setCategory] = useState('all'), [difficulty, setDifficulty] = useState('all'), [sort, setSort] = useState('newest'), [page, setPage] = useState(1);
    const params = new URLSearchParams({ search: query, category, difficulty, sort, page: String(page) });
    const resource = useResource('/backend/explore.php?' + params), data = payload(resource.data), challenges = rows(data.challenges ?? data.data), pagination = row(data.pagination);
    return <>
    <PageTitle eyebrow="CHALLENGE LIBRARY" title="Find your next investigation." description="Explore real environments and follow your curiosity."/>
    <form className="filter-bar" onSubmit={e => { e.preventDefault(); setQuery(search); setPage(1); }}>
      <Field 
        label="Search challenges" 
        placeholder="Identity, cryptography, web…" 
        value={search} 
        onChange={e => setSearch(e.target.value)}/>
      <Select 
        label="Category" 
        value={category} 
        options={['all', ...categories]} 
        onChange={e => { setCategory(e.target.value); setPage(1); }}/>
      <Select 
        label="Difficulty" 
        value={difficulty} 
        options={['all', 'easy', 'medium', 'hard']} 
        onChange={e => { setDifficulty(e.target.value); setPage(1); }}/>
      <Select 
        label="Sort by" 
        value={sort} 
        options={['newest', 'oldest', 'name', 'difficulty']} 
        onChange={e => { setSort(e.target.value); setPage(1); }}/>
      <button type="submit">Search</button>
    </form>
    <ResourceState {...resource}>
      <div className="section-heading">
        <p className="muted">
          {number(pagination.total_items ?? data.total_items ?? challenges.length)} challenges to explore</p>
        <span className="view-label">LIBRARY / {category.toUpperCase()}
        </span>
      </div>
      {challenges.length ? <div className="challenge-grid">
        {challenges.map(c => <ChallengeCard key={text(c.id)} challenge={c}/>)}
      </div> : <Empty title="No matching challenges">Try a different search or category.</Empty>}
      <Pager page={page} totalPages={number(pagination.total_pages ?? data.total_pages) || 1} onPage={setPage}/>
    </ResourceState>
  </>;
}
