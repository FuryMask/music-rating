"""Пакет переиспользуемых виджетов."""

from app.ui.widgets.album_card import AlbumCard
from app.ui.widgets.artist_card import ArtistCard
from app.ui.widgets.cover_view import CoverView
from app.ui.widgets.hoverable import HoverButton, Hoverable
from app.ui.widgets.section import Section
from app.ui.widgets.view_all_tile import ViewAllTile

__all__ = [
    "AlbumCard",
    "ArtistCard",
    "CoverView",
    "HoverButton",
    "Hoverable",
    "Section",
    "ViewAllTile",
]
