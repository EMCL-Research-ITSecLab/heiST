export type TopologyMachine = {key: string; name: string};
export type TopologyNetwork = {key: string; name: string; accessible: boolean; dmz: boolean; machines: string[]};
export function topology(machines: TopologyMachine[], networks: TopologyNetwork[]) {
  const height = Math.max(160, Math.max(machines.length, networks.length) * 66 + 40);
  const position = (index: number, length: number) => 30 + (index + .5) * (height - 60) / Math.max(1, length);
  const vms = machines.map((vm, i) => ({...vm, x: 240, y: position(i, machines.length)}));
  const nets = networks.map((net, i) => ({...net, x: 80, y: position(i, networks.length)}));
  const byKey = new Map(vms.map(vm => [vm.key, vm]));
  const edges = nets.flatMap(net => [...new Set(net.machines)].flatMap(key => {
    const vm = byKey.get(key);
    return vm ? [{network: net.key, machine: key, path: `M 145 ${net.y} C 160 ${net.y}, 160 ${vm.y}, 175 ${vm.y}`}] : [];
  }));
  return {height, machines: vms, networks: nets, edges};
}
