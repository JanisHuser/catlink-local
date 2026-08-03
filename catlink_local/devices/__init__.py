"""Device handlers.

Importing this package registers every built-in handler.  To add a new device
type, drop a module in here that defines a ``@register``-decorated
:class:`~catlink_local.devices.base.DeviceHandler` subclass and import it below.
"""

# Order matters: specific handlers first, the generic fallback LAST so it only
# claims devices no dedicated handler recognised.
from . import feeder  # noqa: F401  (import for its @register side effect)
from . import generic  # noqa: F401  must stay last

__all__ = ["feeder", "generic"]
