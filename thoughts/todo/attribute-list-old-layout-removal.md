# Remove the old-layout attribute list reader

**Filed** 2026-11-13 by `thoughts/plans/2026-11-13-attribute-list-v2-port.md`
(Phase 4).

4.0 moved attribute lists onto the property list format
(`list:<name>-meta`, `list:<name>-#<rank>`). A list written before 4.0
(`list:<name>:meta`, `list:<name>:<i>`) is read in place and converted on its
first change (`actingweb/attribute_list.py`: `_settle_layout`, `_convert`,
the old-layout readers, the `layout_cleanup` marker, and the conflict
detection between the two layouts). Every list operation pays one extra point
read per instance for the old-layout probe.

**What to do:** once a release has been live long enough that no deployment
can hold old-layout lists (and rolling back to 3.15 is off the table), remove
the reader, the converter and the probe; keep a conflict check only if the
tool still needs it. Before that, `actingweb-verify-property-lists
--attributes` (with `--repair` to convert) must report no old-layout list in
the deployments that matter, Emm's included.

**Why not now:** rolling back from 4.0 to 3.15 relies on old-layout lists
staying readable until they are written, and a rolling deploy has 3.15 and
4.0 processes side by side.
