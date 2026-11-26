"""Validate serial wiring while allowing parked nodes and incomplete paths."""
def ordered_ids(ids,connections,require_output=True):
    ids=set(ids)
    if ids & {'input','output'}:raise ValueError('Reserved module identifier')
    known=ids|{'input','output'};links={};incoming=set()
    if not isinstance(connections,(list,tuple)):raise ValueError('Invalid connections')
    for edge in connections:
        if not isinstance(edge,(list,tuple)) or len(edge)!=2 or not all(isinstance(v,str) for v in edge):raise ValueError('Invalid connection')
        source,target=edge
        if source not in known or target not in known:raise ValueError('Connection to a missing module')
        if source=='output' or target=='input' or source==target:raise ValueError('Invalid connection direction')
        if source in links or target in incoming:raise ValueError('Port has multiple connections')
        links[source]=target;incoming.add(target)
    # Reject cycles even in disconnected islands.
    done=set()
    for start in known:
        current=start;seen=set()
        while current in links and current not in done:
            if current in seen:raise ValueError('Cyclic connections are not allowed')
            seen.add(current);current=links[current]
        done.update(seen)
    ordered=[];current='input'
    while current!='output':
        current=links.get(current)
        if current is None:
            if require_output:raise ValueError('Incomplete wiring: connect the active path to OUTPUT. Live preview remains available up to the last connected node.')
            break
        if current!='output':ordered.append(current)
    return ordered,current=='output'
