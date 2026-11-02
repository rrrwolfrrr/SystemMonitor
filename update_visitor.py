"""Optional UpdateVisitor adapter for LibreHardwareMonitor.

No C# SDK is required: PythonNet uses the managed ``IVisitor`` when present.
Older/newer LHM builds with an incompatible interface use the deterministic
recursive ``hardware.Update()`` fallback.
"""

from __future__ import annotations


class UpdateVisitorAdapter:
    """Duck-typed visitor that works across LHM/PythonNet versions."""

    def VisitComputer(self, computer):
        traverse = getattr(computer, "Traverse", None)
        if callable(traverse):
            traverse(self)
            return
        for hardware in getattr(computer, "Hardware", ()) or ():
            self.VisitHardware(hardware)

    def VisitHardware(self, hardware):
        update = getattr(hardware, "Update", None)
        if callable(update):
            update()
        for child in getattr(hardware, "SubHardware", ()) or ():
            self.VisitHardware(child)

    def VisitSensor(self, sensor):
        return None

    def VisitParameter(self, parameter):
        return None


def create_visitor(visitor_interface=None):
    """Create a managed visitor when possible, otherwise a duck-typed one."""
    if visitor_interface is None:
        return UpdateVisitorAdapter()
    try:
        return type("UpdateVisitor", (UpdateVisitorAdapter, visitor_interface), {})()
    except TypeError:
        return UpdateVisitorAdapter()
