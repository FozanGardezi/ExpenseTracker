from .base import Provider
from .careem import Careem
from .foodpanda import Foodpanda
from .indrive import InDrive
from .kravemart import KraveMart

# Order here is the display order and fixes each service's chart color.
PROVIDERS: dict[str, Provider] = {
    p.key: p for p in (Foodpanda(), Careem(), InDrive(), KraveMart())
}

__all__ = ["PROVIDERS", "Provider"]
