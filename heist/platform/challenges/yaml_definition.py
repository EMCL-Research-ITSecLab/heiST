"""Bounded legacy YAML import using the platform's existing PyYAML dependency."""
from .definition import DefinitionError

MAX_BYTES = 256*1024


def parse_yaml(source):
    import yaml
    if not isinstance(source,str) or len(source.encode('utf-8',errors='replace')) > MAX_BYTES:
        raise DefinitionError('YAML file must be at most 256 KiB')
    try:
        depth = 0
        for count,event in enumerate(yaml.parse(source)):
            if count > 10000 or isinstance(event,yaml.AliasEvent):
                raise DefinitionError('YAML aliases or oversized documents are not supported')
            if isinstance(event,(yaml.MappingStartEvent,yaml.SequenceStartEvent)):
                depth += 1
                if depth > 24:raise DefinitionError('YAML nesting is too deep')
            elif isinstance(event,(yaml.MappingEndEvent,yaml.SequenceEndEvent)):
                depth -= 1
        class Loader(yaml.SafeLoader):
            pass
        def mapping(loader,node,deep=False):
            result = {}
            for key_node,value_node in node.value:
                key = loader.construct_object(key_node,deep=deep)
                if not isinstance(key,str) or key in result:
                    raise DefinitionError('YAML mapping keys must be unique text')
                result[key] = loader.construct_object(value_node,deep=deep)
            return result
        Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
        value = yaml.load(source,Loader=Loader)
    except (yaml.YAMLError,RecursionError):
        raise DefinitionError('Invalid YAML document') from None
    if not isinstance(value,dict) or not isinstance(value.get('ctf'),dict):
        raise DefinitionError('YAML must contain a ctf object')
    data = value['ctf']
    def entries(name,maximum):
        items = data.get(name,{})
        if not isinstance(items,dict) or len(items)>maximum or any(not isinstance(v,dict) for v in items.values()):
            raise DefinitionError('Invalid YAML '+name)
        return list(items.items())
    result = {name:data.get(name,'') for name in ('name','description','category','difficulty','hint','solution')}
    result['isActive'] = data.get('is_active',True)
    result['vms'] = [{'name':name,'ova_name':vm.get('ova_name',''),'cores':vm.get('cores',1),
                      'ram_gb':vm.get('ram_gb',1),'domain_name':vm.get('domain_name',''),
                      'ad_role':vm.get('ad_role','none')} for name,vm in entries('vms',20)]
    result['subnets'] = [{'name':name,'dmz':net.get('dmz',False),'accessible':net.get('accessible',False),
                          'attached_vms':net.get('attached_vms',[])} for name,net in entries('subnets',10)]
    result['flags'] = [{'flag':flag.get('flag',''),'description':flag.get('description',''),
                        'points':flag.get('points',0),'order_index':flag.get('order_index',index),
                        'user_specific':flag.get('user_specific',False),'vm_name':flag.get('vm_name','')}
                       for index,(_,flag) in enumerate(entries('flags',20))]
    result['hints'] = [{'hint_text':hint.get('hint_text',''),'unlock_points':hint.get('unlock_points',0),
                        'order_index':hint.get('order_index',index)} for index,(_,hint) in enumerate(entries('hints',10))]
    return result
