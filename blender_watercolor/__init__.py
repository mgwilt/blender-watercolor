"""Blender Watercolor: paint and simulate on porous surfaces."""


def register():
    from . import addon

    addon.register()


def unregister():
    from . import addon

    addon.unregister()
