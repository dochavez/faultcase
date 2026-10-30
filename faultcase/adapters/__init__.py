"""OS adapters: raw evidence collectors, one subpackage per operating system.

Each adapter returns OS-independent structures that later stages normalize
against schemas/evidence.schema.json. Windows is implemented first; macOS
and Linux adapters can be added alongside it later.
"""
