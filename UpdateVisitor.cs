// Optional reference implementation for SDK users. The Python application
// does not compile this file; update_visitor.py provides the no-SDK adapter.
using LibreHardwareMonitor.Hardware;

public sealed class UpdateVisitor : IVisitor
{
    public void VisitComputer(IComputer computer) { computer.Traverse(this); }
    public void VisitHardware(IHardware hardware) { hardware.Update(); }
    public void VisitSensor(ISensor sensor) { }
    public void VisitParameter(IParameter parameter) { }
}
