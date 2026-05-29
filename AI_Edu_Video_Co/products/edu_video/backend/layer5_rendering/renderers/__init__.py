# products/edu_video/backend/layer5_rendering/renderers/__init__.py
"""
Renderers package.
All renderers are lazy-imported by animation_router.py — this __init__.py
only exports the base class and error type for type-checking convenience.
Direct imports of individual renderers are done inside _get_renderer().
"""

from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["BaseRenderer", "RendererError"]
