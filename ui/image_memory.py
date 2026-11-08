"""Decode fixed-size artwork near its display size without changing its aspect."""
import math

import flet as ft


def preview_image(src, *, width, height, **options):
    options.setdefault("cache_width", max(1, math.ceil(width * 2)))
    return ft.Image(src=src, width=width, height=height, **options)
