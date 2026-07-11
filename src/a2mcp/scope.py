"""Per-group primitive scoping (design D3).

Each group server carries ONE ``GroupScopeMiddleware`` that enforces that group's
per-backend allow/deny globs on BOTH discovery and invocation:

- filters ``tools/list``, ``resources/list``, ``resources/templates/list``,
  ``prompts/list`` to matching entries;
- REJECTS ``tools/call``, ``resources/read``, ``resources/subscribe``, ``prompts/get``
  for items that do not match, so a hidden item cannot be invoked by guessing its name
  (listing is not a security boundary).

Globs match the UNPREFIXED primitive name within its backend (tools/prompts by name;
resources by ``uri`` / template ``uriTemplate``). Composition namespaces primitives
``<backend>_<name>`` (tools/prompts) and ``<scheme>://<backend>/<rest>`` (resources), so
a name is first mapped to its owning backend, then unprefixed, then matched against that
backend's globs. Because a backend is reachable only if the group includes it,
cross-backend name collisions cannot leak: a glob for one backend never matches another.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

from fastmcp.exceptions import PromptError, ResourceError, ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from .config import BackendRef, Group


def _matches(patterns: list[str], value: str) -> bool:
    return any(fnmatchcase(value, p) for p in patterns)


class GroupScopeMiddleware(Middleware):
    """Enforce one group's per-backend primitive globs on lists and on calls."""

    def __init__(self, group: Group) -> None:
        # Longest backend name first so a name that is a prefix of another resolves right.
        self._refs: dict[str, BackendRef] = {ref.name: ref for ref in group.backends}
        self._names: list[str] = sorted(self._refs, key=len, reverse=True)

    # --- backend resolution + unprefixing -------------------------------------------

    def _backend_of_name(self, namespaced: str) -> tuple[str, str] | None:
        """``ha_light_on`` -> ``("ha", "light_on")`` using the group's backend names."""
        for name in self._names:
            prefix = f"{name}_"
            if namespaced.startswith(prefix):
                return name, namespaced[len(prefix) :]
        return None

    def _backend_of_uri(self, uri: str) -> tuple[str, str] | None:
        """``resource://ha/config/main`` -> ``("ha", "resource://config/main")``."""
        scheme, sep, rest = uri.partition("://")
        if not sep:
            return None
        for name in self._names:
            prefix = f"{name}/"
            if rest.startswith(prefix):
                return name, f"{scheme}://{rest[len(prefix) :]}"
        return None

    # --- the allow/deny decision ----------------------------------------------------

    def _allowed(self, backend: str, kind: str, identifier: str) -> bool:
        ref = self._refs.get(backend)
        if ref is None:  # not in this group -> never exposed
            return False
        allow = getattr(ref, kind)  # ref.tools / ref.resources / ref.prompts
        if not _matches(allow, identifier):
            return False
        return not _matches(ref.exclude, identifier)  # exclude wins over allow

    def _tool_allowed(self, namespaced: str) -> bool:
        resolved = self._backend_of_name(namespaced)
        if resolved is None:
            return False
        backend, unprefixed = resolved
        return self._allowed(backend, "tools", unprefixed)

    def _prompt_allowed(self, namespaced: str) -> bool:
        resolved = self._backend_of_name(namespaced)
        if resolved is None:
            return False
        backend, unprefixed = resolved
        return self._allowed(backend, "prompts", unprefixed)

    def _resource_allowed(self, uri: str) -> bool:
        resolved = self._backend_of_uri(uri)
        if resolved is None:
            return False
        backend, unprefixed = resolved
        return self._allowed(backend, "resources", unprefixed)

    # --- list filtering (discovery) -------------------------------------------------

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext):
        result = await call_next(context)
        return [t for t in result if self._tool_allowed(t.name)]

    async def on_list_prompts(self, context: MiddlewareContext, call_next: CallNext):
        result = await call_next(context)
        return [p for p in result if self._prompt_allowed(p.name)]

    async def on_list_resources(self, context: MiddlewareContext, call_next: CallNext):
        result = await call_next(context)
        return [r for r in result if self._resource_allowed(str(r.uri))]

    async def on_list_resource_templates(
        self, context: MiddlewareContext, call_next: CallNext
    ):
        result = await call_next(context)
        return [t for t in result if self._resource_allowed(str(t.uri_template))]

    # --- call-time enforcement ------------------------------------------------------

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        name = getattr(context.message, "name", "")
        if not self._tool_allowed(name):
            raise ToolError(f"tool {name!r} is not available in this group")
        return await call_next(context)

    async def on_get_prompt(self, context: MiddlewareContext, call_next: CallNext):
        name = getattr(context.message, "name", "")
        if not self._prompt_allowed(name):
            raise PromptError(f"prompt {name!r} is not available in this group")
        return await call_next(context)

    async def on_read_resource(self, context: MiddlewareContext, call_next: CallNext):
        uri = str(getattr(context.message, "uri", ""))
        if not self._resource_allowed(uri):
            raise ResourceError(f"resource {uri!r} is not available in this group")
        return await call_next(context)

    async def on_request(self, context: MiddlewareContext, call_next: CallNext):
        # No dedicated subscribe hook exists; gate resources/subscribe here by method.
        if context.method == "resources/subscribe":
            uri = str(getattr(context.message, "uri", ""))
            if not self._resource_allowed(uri):
                raise ResourceError(f"resource {uri!r} is not available in this group")
        return await call_next(context)
