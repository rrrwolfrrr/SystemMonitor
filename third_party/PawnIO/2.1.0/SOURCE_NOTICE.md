# PawnIO 2.1.0 source and redistribution notice

This directory contains the upstream PawnIO 2.1.0 source and the complete
PawnPP source dependency pinned by that release:

- PawnIO tag `2.1.0`, commit
  `e1043d7750f501b6b0d3ac0a71bd5b9406cd17b6`
- PawnPP commit `e64e4c37b2d8ba0d8ee57205faf8183aee12c438`, populated under
  `source/PawnPP` in place of the source archive's empty submodule directory

The local project may contain a candidate `PawnIO_setup.exe` at its root. It
reports version `2.1.0.0`, has a valid Authenticode signature from namazso, and
its SHA-256 matches the official v2.1.0 release asset:

`A3A46226C5E2824F4CDD42BE0EECBABFC672C86F7889710F5AB1E6AD385B47A0`

The PawnIO driver is licensed under GPL-2.0-or-later with the special exception
printed in the upstream README and source headers. The complete GPL text is in
`source/COPYING`; retain the README and source headers because they contain the
exception. PawnPP is licensed under MPL-2.0; its unmodified license is in
`source/PawnPP/LICENSE`.

The official [PawnIO.Setup release repository](https://github.com/namazso/PawnIO.Setup)
contains only a README and publishes no buildable installer source or license
grant for redistribution of the setup executable. Therefore this bundle
provides the driver source and notices, but does not establish permission to
redistribute the installer wrapper; `PawnIO_setup.exe` remains excluded from
Git until that permission is confirmed.

Upstream references:

- [PawnIO v2.1.0 source](https://github.com/namazso/PawnIO/tree/2.1.0)
- [PawnPP pinned source](https://github.com/namazso/PawnPP/tree/e64e4c37b2d8ba0d8ee57205faf8183aee12c438)
- [PawnIO.Setup v2.1.0 release](https://github.com/namazso/PawnIO.Setup/releases/tag/2.1.0)
- [PawnIO official edition description and download](https://pawnio.eu/)
