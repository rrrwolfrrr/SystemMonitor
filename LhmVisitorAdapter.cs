using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading.Tasks;
using LibreHardwareMonitor.Hardware;

public static class LhmVisitorRunner
{
    private const int UpdateWaitMilliseconds = 750;
    private static readonly ConcurrentDictionary<IHardware, Stopwatch> ActiveUpdates =
        new ConcurrentDictionary<IHardware, Stopwatch>();
    private static readonly ConcurrentQueue<string> UpdateErrors =
        new ConcurrentQueue<string>();

    public static string[] Update(Computer computer)
    {
        var tasks = new List<Task>();
        foreach (IHardware hardware in computer.Hardware)
        {
            var stopwatch = Stopwatch.StartNew();
            if (!ActiveUpdates.TryAdd(hardware, stopwatch))
            {
                continue;
            }

            tasks.Add(Task.Factory.StartNew(() =>
            {
                try
                {
                    UpdateTree(hardware);
                }
                catch (Exception exception)
                {
                    UpdateErrors.Enqueue(
                        hardware.Name + ": " + exception.GetType().Name + ": " + exception.Message);
                }
                finally
                {
                    Stopwatch ignored;
                    ActiveUpdates.TryRemove(hardware, out ignored);
                }
            }));
        }

        if (tasks.Count > 0)
        {
            Task.WaitAll(tasks.ToArray(), UpdateWaitMilliseconds);
        }

        var status = new List<string>();
        foreach (var update in ActiveUpdates)
        {
            status.Add("pending:" + update.Key.Name);
        }

        string error;
        while (UpdateErrors.TryDequeue(out error))
        {
            status.Add("error:" + error);
        }

        return status.ToArray();
    }

    private static void UpdateTree(IHardware hardware)
    {
        hardware.Update();
        foreach (IHardware subHardware in hardware.SubHardware)
        {
            UpdateTree(subHardware);
        }
    }
}
