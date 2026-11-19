import { useI18n } from '../lib/i18n.tsx';
import { useId } from 'react';
import { Card } from './ui.tsx';
import { topology, type TopologyMachine, type TopologyNetwork } from '../lib/topology.ts';
export function NetworkPreview({
  machines,
  networks,
}: {
  machines: TopologyMachine[];
  networks: TopologyNetwork[];
}) {
  const { t } = useI18n();
  const id = useId(),
    graph = topology(machines, networks);
  const label = (name: string, fallback: string) => name || fallback;
  return (
    <Card title={t('networks.networkPreview')}>
      {!machines.length && !networks.length ? (
        <p className="muted">{t('networks.addMachinesAndNetworksToPreviewTheirConnections')}</p>
      ) : (
        <>
          <div
            className="topology-scroll"
            tabIndex={0}
            role="region"
            aria-label={t('networks.scrollableNetworkDiagram')}
          >
            <svg
              className="topology-diagram"
              viewBox={`0 0 320 ${graph.height}`}
              role="img"
              aria-labelledby={id}
            >
              <title id={id}>{t('networks.challengeNetworkPreview')}</title>
              {graph.edges.map((edge) => (
                <path
                  key={edge.network + ':' + edge.machine}
                  d={edge.path}
                  className="topology-edge"
                  data-network={edge.network}
                  data-machine={edge.machine}
                />
              ))}
              {graph.networks.map((net, i) => (
                <g key={net.key} className={'topology-network' + (net.dmz ? ' dmz' : '')}>
                  <title>
                    {label(net.name, `Network ${i + 1}`)}
                    {net.accessible ? ' ' + t('common.studentAccess') : ''}
                    {net.dmz ? ' ' + t('common.dmz') : ''}
                  </title>
                  <rect x={net.x - 65} y={net.y - 24} width="130" height="48" rx="7" />
                  <text x={net.x} y={net.y - 2} textAnchor="middle">
                    {label(net.name, `Network ${i + 1}`).slice(0, 16)}
                  </text>
                  <text x={net.x} y={net.y + 15} textAnchor="middle" className="topology-detail">
                    {net.dmz
                      ? net.accessible
                        ? 'DMZ · Student access'
                        : 'DMZ'
                      : net.accessible
                        ? 'Student access'
                        : 'Network'}
                  </text>
                </g>
              ))}
              {graph.machines.map((vm, i) => (
                <g key={vm.key} className="topology-machine">
                  <title>{label(vm.name, `Machine ${i + 1}`)}</title>
                  <rect x={vm.x - 65} y={vm.y - 20} width="130" height="40" rx="5" />
                  <text x={vm.x} y={vm.y + 5} textAnchor="middle">
                    {label(vm.name, `Machine ${i + 1}`).slice(0, 16)}
                  </text>
                </g>
              ))}
            </svg>
          </div>
          <details>
            <summary>{t('networks.networkConnections')}</summary>
            <ul className="topology-connections">
              {machines.map((vm, i) => (
                <li key={vm.key}>
                  <strong>{label(vm.name, `Machine ${i + 1}`)}</strong>:{' '}
                  {networks
                    .filter((net) => net.machines.includes(vm.key))
                    .map((net, j) => label(net.name, `Network ${j + 1}`))
                    .join(', ') || 'Not connected'}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </Card>
  );
}
