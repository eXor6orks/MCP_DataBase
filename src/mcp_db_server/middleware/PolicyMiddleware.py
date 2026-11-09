from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp_db_server.policy import Policy, _POLICY_REGISTRY, _EXEMPT_TOOLS, PolicyDeniedException

class PolicyMiddleware(Middleware):
    """
    Middleware to enforce policy checks on database operations.
    """

    def __init__(self, policy : Policy):
        self._policy = policy

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """
        Middleware method that checks the policy for
        the requested tool before allowing its executions.

        Args:
            context (MiddlewareContext): The context of the current request.
            call_next: The next middleware or tool to call.
        """
        tool_name = context.message.name
        if tool_name in _EXEMPT_TOOLS:
            return await call_next(context)

        requirement = _POLICY_REGISTRY.get(tool_name)
        if requirement is None:
            raise PolicyDeniedException(f"Tool '{tool_name}' sans politique déclarée — refusé par défaut")

        level, extractor = requirement
        connection_name, table_name = extractor(context.message.arguments)
        self._policy.check(connection_name, table_name, level)
        return await call_next(context)

