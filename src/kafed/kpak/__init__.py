"""KAFED 知识包模块 — 可分享的知识单元。

用法:
    import kafed.kpak
    kafed.kpak.pack_domain("SAP_PM")
    kafed.kpak.unpack_kpak("SAP_PM.kpak")
    kafed.kpak.list_kpak()
"""

from kafed.kpak.pack import pack_domain, list_kpak
from kafed.kpak.unpack import unpack_kpak

__all__ = ["pack_domain", "unpack_kpak", "list_kpak"]
