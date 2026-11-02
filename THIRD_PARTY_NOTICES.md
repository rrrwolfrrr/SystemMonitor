# Third-party components and build inputs

The pinned LibreHardwareMonitor 0.9.6 DLL dependencies and PresentMon
executable are allowed in Git by `.gitignore`. Their versions and package
references match the upstream v0.9.6 project files; the local PresentMon
executable matches the official release SHA-256. The PawnIO v2.1.0 driver
source snapshot, its pinned PawnPP submodule, and their license texts are
included under `third_party/PawnIO/2.1.0`. `PawnIO_setup.exe` remains excluded:
the official setup repository publishes the binary release but provides neither
buildable installer source nor a license grant for redistributing the installer
itself. Other unreviewed root DLL/EXE remain excluded.

`LhmVisitorAdapter.dll` is generated locally by `build.bat` from
`LhmVisitorAdapter.cs`; the DLL is not a repository input.

## Components referenced by `build.spec`

| Component / files | License information found | Publication note |
|---|---|---|
| `LibreHardwareMonitorLib.dll` (file version 0.9.6.0) | MPL-2.0; [upstream v0.9.6 project](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/tree/v0.9.6) | The local file version matches v0.9.6. Preserve MPL notices and provide corresponding source as required when distributing covered binaries or modifications. |
| `BlackSharp.Core.dll` (1.0.7), `DiskInfoToolkit.dll` (1.1.2), `RAMSPDToolkit-NDD.dll` (1.4.2) | These exact package versions are referenced by the [LibreHardwareMonitor v0.9.6 library project](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/v0.9.6/LibreHardwareMonitorLib/LibreHardwareMonitorLib.csproj); NuGet declares MPL-2.0 for each. | These are LHM dependencies, not all code authored under the LHM license. Keep their MPL notices and source references; verify the exact local binaries against upstream package/source versions. |
| `PresentMon-2.6.0-x64.exe` | MIT; [v2.6.0 license](https://github.com/GameTechDev/PresentMon/blob/v2.6.0/LICENSE.txt) | This is a separate dependency, not an LHM binary. The local SHA-256 matches the official v2.6.0 GitHub release asset, and its Authenticode signature is valid. `PRESENTMON_LICENSE.txt` is retained; preserve it with any distributed copy. |
| `HidSharp.dll` (2.6.4.0) | Apache-2.0; version 2.6.4 is referenced by [LibreHardwareMonitor v0.9.6](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/v0.9.6/LibreHardwareMonitorLib/LibreHardwareMonitorLib.csproj); [NuGet license](https://www.nuget.org/packages/HidSharp/2.6.4/License). | Include Apache license and required notices when distributing it. |
| `OxyPlot.dll`, `OxyPlot.WindowsForms.dll` (2.2.0.0) | MIT; version 2.2.0 is referenced by the [LibreHardwareMonitor v0.9.6 app project](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/v0.9.6/LibreHardwareMonitor/LibreHardwareMonitor.csproj); [upstream license](https://github.com/oxyplot/oxyplot/blob/develop/LICENSE). | Preserve the OxyPlot copyright and license notice. |
| `Microsoft.Win32.TaskScheduler.dll` (2.12.2.0) | The v0.9.6 app project references TaskScheduler 2.12.2; [upstream license](https://github.com/dahall/TaskScheduler/blob/master/license.md). | Preserve its MIT notice. |
| `Aga.Controls.dll` (1.7.0.0) | LHM v0.9.6 references the Aga.Controls project; related [TreeViewAdv source](https://github.com/AdamsLair/treeviewadv) contains a BSD license. | Keep the BSD notice with redistributed copies; local version metadata matches 1.7.0.0. |
| `PawnIO_setup.exe` (file version 2.1.0.0) | The PawnIO driver source at [v2.1.0](https://github.com/namazso/PawnIO/tree/2.1.0) is GPL-2.0-or-later with a special exception for independent modules communicating solely through its device IOCTL interface. Its pinned [PawnPP dependency](https://github.com/namazso/PawnPP/tree/e64e4c37b2d8ba0d8ee57205faf8183aee12c438) is MPL-2.0. The separate [setup release](https://github.com/namazso/PawnIO.Setup/releases/tag/2.1.0) has no published installer source or redistribution license. | The complete driver source, pinned PawnPP source, and their licenses are included under `third_party/PawnIO/2.1.0`. The local setup executable is byte-for-byte identical to the official v2.1.0 release asset and has a valid Authenticode signature from namazso, but the setup project's lack of a source/license grant leaves redistribution of the installer itself unverified. It remains ignored by Git; do not include it until that permission is confirmed. |
| `System.*.dll` and `Microsoft.Bcl.*.dll` files listed in `build.spec` | Microsoft runtime/support dependencies; some corresponding packages are referenced by the v0.9.6 LHM projects. | Allowed by the build-input rules where listed, but verify exact NuGet package versions and applicable redistribution notices before making a release. |

Other root-level DLL/EXE files not explicitly allow-listed in `.gitignore`
remain ignored. Their presence in a developer's working folder does not mean
they are required or approved for distribution.

## Project assets

The project owner confirms that the dashboard themes, application icon, and
user-facing HTML documents were created for this project with Copilot. This
confirmation addresses their authorship for this preparation; it does not
replace a project license or change the third-party terms above.

## Project license

SystemMonitor itself does not yet have a selected project license. Third-party
licenses listed above apply only to their respective components; they do not
grant rights to use or redistribute SystemMonitor. Add a project license only
after the copyright holder has chosen one.
