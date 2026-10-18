"""Routing metadata has no persistence or lifecycle transition responsibilities."""

from threading import Lock


class Registry:
    def __init__(self, apps):
        self.apps = apps
        self.children = tuple({id(child): child for child in apps.values()}.values())

    def port(self, app, name):
        port = getattr(self.apps[app], name)
        if port is None:
            raise NotImplementedError(f"App {app!r} has no {name} backend")
        return port

    def ports(self, name):
        return tuple(port for child in self.children if (port := getattr(child, name)) is not None)

    def locate(self, name, identifier):
        matches = []
        for child in self.children:
            port = getattr(child, name)
            row = port.lookup(identifier) if port is not None else None
            if row is not None and self.apps.get(row["app"]) is child:
                matches.append(port)
        if len(matches) > 1:
            raise ValueError("Operation identifier is ambiguous across app databases")
        if not matches:
            raise KeyError(identifier)
        return matches[0]


class RoundRobin:
    """Rotate the starting child; each child still owns its atomic claims."""

    def __init__(self):
        self.position, self.lock = 0, Lock()

    def ordered(self, ports):
        if not ports:
            return ()
        with self.lock:
            start = self.position % len(ports)
            self.position += 1
        return ports[start:] + ports[:start]


def projection(results, keys):
    return {key: [item for result in results for item in result[key]] for key in keys}
