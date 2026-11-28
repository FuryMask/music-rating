"""Хранилище данных приложения — SQL (SQLite).

База — SQLite-файл Music Rating/library.db в папке «Документы».
    artists       — исполнители (имя — ключ, порядок хранения = position)
    albums        — альбомы (id, оценка, даты, source_id ссылки Deezer)
    album_artists — исполнители альбома (список artist_names по порядку)
    album_tracks  — треки альбома (по порядку)
    track_artists — исполнители каждого трека (по порядку)
    album_raters  — участники конкретного альбома (столбцы оценок)
    track_ratings — оценки треков участниками [трек][участник]

Порядок строк хранится в колонке position: «новые — раньше» в списках
и дискографиях строится по порядку вставки, как раньше. Каждое
изменение сразу пишется в базу (одна транзакция на изменение).

ОБЛОЖКИ И ФОТО: при добавлении копируются в covers/ рядом с базой.
Относительные пути хранятся в формате «data/covers/<имя>» для
совместимости с архивами прежних версий. Прежний JSON (library.json) при
первом запуске с SQL-версией автоматически переносится в базу
(см. _migrate_legacy_json) — библиотека пользователя не теряется.

Интерфейс для интерфейса приложения: find_*/add_*/names (исполнители),
add_album/rate_album (альбомы), find_album_by_source (альбом, созданный
по ссылке Deezer), artist_average_rating (средняя оценка исполнителя),
artist_albums/artist_main_genre (дискография и основной жанр для его
страницы).

Исполнители НЕЗАВИСИМЫ от альбомов: delete_album убирает только
альбом — исполнители (и авторы, и фиты) остаются в базе.

Новая библиотека изначально пуста.
"""

import json
import os
import random
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from app.models import (
    Album,
    AlbumDraft,
    AlbumRatings,
    Artist,
    ArtistDraft,
    TrackDraft,
    UserStats,
)

def _data_directory() -> Path:
    override = os.environ.get("MUSICRATING_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return (Path(documents) if documents else Path.home() / "Documents") / "Music Rating"


DATA_DIR = _data_directory()
COVERS_DIR = DATA_DIR / "covers"
DB_FILE = DATA_DIR / "library.db"       # база SQL
LIBRARY_FILE = DATA_DIR / "library.json"  # прежний формат (для переноса)

# Имя базы внутри экспортного ZIP-архива (см. export_library)
EXPORT_DB_ENTRY = "library.db"
EXPORT_COVERS_PREFIX = "covers/"
# Обязательные таблицы базы Music Rating (проверка при импорте)
REQUIRED_TABLES = {"meta", "artists", "albums", "album_tracks"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artists (
    position    INTEGER NOT NULL,
    name        TEXT PRIMARY KEY,
    genre       TEXT NOT NULL DEFAULT '',
    photo_path  TEXT,
    avatar_path TEXT
);

CREATE TABLE IF NOT EXISTS albums (
    position   INTEGER NOT NULL,
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    year       TEXT NOT NULL DEFAULT '',
    genre      TEXT NOT NULL DEFAULT '',
    region     TEXT NOT NULL DEFAULT 'RU',
    cover_path TEXT,
    rating     REAL,
    rated_at   TEXT,
    created_at TEXT NOT NULL DEFAULT '',
    source_id  TEXT NOT NULL DEFAULT '',
    cloud_id   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS album_artists (
    album_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    name     TEXT NOT NULL,
    PRIMARY KEY (album_id, position)
);

CREATE TABLE IF NOT EXISTS album_tracks (
    album_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    title    TEXT NOT NULL,
    PRIMARY KEY (album_id, position)
);

CREATE TABLE IF NOT EXISTS track_artists (
    album_id       TEXT NOT NULL,
    track_position INTEGER NOT NULL,
    position       INTEGER NOT NULL,
    name           TEXT NOT NULL,
    PRIMARY KEY (album_id, track_position, position)
);

CREATE TABLE IF NOT EXISTS album_raters (
    album_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    name     TEXT NOT NULL,
    cloud_user_id TEXT,
    PRIMARY KEY (album_id, position)
);

CREATE TABLE IF NOT EXISTS track_ratings (
    album_id       TEXT NOT NULL,
    track_position INTEGER NOT NULL,
    rater_position INTEGER NOT NULL,
    value          REAL,
    PRIMARY KEY (album_id, track_position, rater_position)
);
"""


class MusicStore:
    """База исполнителей и альбомов (SQL) с сохранением на диск."""

    def __init__(self) -> None:
        self.artists: list[Artist] = []
        self.albums: list[Album] = []
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(DB_FILE)
        self._ensure_schema()
        # Прежний library.json переносится в SQL-базу один раз
        self._migrate_legacy_json()
        self._load()
        if self._meta_get("seeded") is None:
            self._meta_set("seeded", "1")

    def _ensure_schema(self) -> None:
        """Дополнить старую базу и удалить локальные учётные записи."""
        self._conn.executescript(SCHEMA)
        cols = {
            row[1] for row in self._conn.execute(
                "PRAGMA table_info(artists)"
            )
        }
        if "avatar_path" not in cols:
            self._conn.execute(
                "ALTER TABLE artists ADD COLUMN avatar_path TEXT"
            )
            self._conn.commit()
        for table, column, definition in (
            ("albums", "cloud_id", "TEXT NOT NULL DEFAULT ''"),
            ("album_raters", "cloud_user_id", "TEXT"),
        ):
            if column not in {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self._conn.commit()
        # Keep only the old settings key for migrating an encrypted cloud session.
        if self._conn.execute("SELECT 1 FROM sqlite_master WHERE name IN ('users', 'raters')").fetchone():
            secure_delete = self._conn.execute("PRAGMA secure_delete").fetchone()[0]
            self._conn.execute("PRAGMA secure_delete = ON")
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO meta (key, value) "
                        "SELECT 'legacy_cloud_profile', value FROM meta WHERE key = 'current_user_id'"
                    )
                    self._conn.execute("DELETE FROM meta WHERE key = 'current_user_id'")
                    self._conn.execute("DROP TABLE IF EXISTS users")
                    self._conn.execute("DROP TABLE IF EXISTS raters")
            finally:
                self._conn.execute(f"PRAGMA secure_delete = {secure_delete}")

    # --- Мета (служебные флаги инициализации) -----------------------------
    def _meta_get(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row is not None else None

    def _meta_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def legacy_cloud_profile(self) -> str:
        return self._meta_get("legacy_cloud_profile") or "guest"

    def cloud_state(self, key: str) -> str | None:
        return self._meta_get(f"cloud_sync:{key}")

    def record_cloud_upload(self, key: str, value: str, album_ids: dict[str, str]) -> None:
        with self._conn:
            self._conn.executemany("UPDATE albums SET cloud_id = ? WHERE id = ?",
                                   [(cloud_id, album_id) for album_id, cloud_id in album_ids.items()])
            self._conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (f"cloud_sync:{key}", value))
        for album in self.albums:
            if album.id in album_ids:
                album.cloud_id = album_ids[album.id]

    def apply_cloud_library(self, albums: list[Album], artists: list[Artist], state: dict[str, str]) -> None:
        previous = self.albums, self.artists
        self.albums, self.artists = albums, artists
        try:
            self._save(state)
        except sqlite3.Error:
            self.albums, self.artists = previous
            raise

    def update_rater_names(self, members: dict[str, str]) -> set[str]:
        if not members:
            return set()
        changes = []
        for album in self.albums:
            if album.ratings is None:
                continue
            for index, old_name in enumerate(album.ratings.rater_names):
                new_name = members.get(album.ratings.rater_id(index))
                if new_name and new_name != old_name:
                    changes.append((album, index, new_name))
        if not changes:
            return set()
        try:
            with self._conn:
                self._conn.executemany("UPDATE album_raters SET name = ? WHERE album_id = ? AND position = ?",
                                       [(name, album.id, index) for album, index, name in changes])
        except sqlite3.Error:
            return set()
        for album, index, name in changes:
            album.ratings.rater_names[index] = name
        return {album.id for album, _, _ in changes}

    def user_stats(self, user_id: str, display_name: str) -> UserStats:
        """Статистика для вкладки «Статистика» окна профиля.

        rated_count — альбомы, где пользователь заполнил хоть одну
        клетку. Любимый альбом — наивысшая СРЕДНЯЯ ПОЛЬЗОВАТЕЛЯ
        этому альбому (при равенстве — оценённый позже); самый
        нелюбимый — зеркально, наинизшая средняя (при равенстве —
        тоже оценённый позже). Любимый исполнитель — наивысшая
        средняя оценка пользователя его трекам, самый нелюбимый —
        наинизшая (учитываются все треки оценённых альбомов, включая
        фиты; при равенстве средней — у кого больше оценённых
        треков, далее — алфавитно). Любимая оценка — значение,
        которое пользователь выставляет ЧАЩЕ ВСЕГО (при равенстве
        частоты — бо́льшее значение). Средние капятся на 10, как и
        всюду в приложении.
        """
        stats = UserStats()
        best_album: tuple[float, str, Album] | None = None   # (ср, дата, ал)
        worst_album: tuple[float, str, Album] | None = None
        artist_values: dict[str, list[float]] = {}
        rating_counts: dict[float, int] = {}
        for album in self.albums:
            ratings = album.ratings
            if ratings is None:
                continue
            column = next((i for i in range(len(ratings.rater_names)) if ratings.rater_id(i) == user_id), None)
            if column is None:
                column = next((i for i, name in enumerate(ratings.rater_names)
                               if ratings.rater_id(i) is None and name.casefold() == display_name.casefold()), None)
            if column is None:
                continue
            filled = [
                row[column] for row in ratings.values
                if column < len(row) and row[column] is not None
            ]
            if not filled:
                continue
            stats.rated_count += 1
            average = min(AlbumRatings.AVERAGE_CAP,
                          round(sum(filled) / len(filled), 1))
            rated_at = album.rated_at or ""
            stats.last_rated_at = max(stats.last_rated_at or "", rated_at) or None
            if (
                best_album is None
                or average > best_album[0]
                # «при равенстве — оценённый позже»; оценка в ту же
                # секунду — позже созданный (порядок итерации)
                or (average == best_album[0]
                    and rated_at >= best_album[1])
            ):
                best_album = (average, rated_at, album)
            if (
                worst_album is None
                or average < worst_album[0]
                or (average == worst_album[0]
                    and rated_at >= worst_album[1])
            ):
                worst_album = (average, rated_at, album)
            for value in filled:
                key = round(value, 1)
                rating_counts[key] = rating_counts.get(key, 0) + 1
            for t_index, track in enumerate(album.tracks):
                if t_index >= len(ratings.values):
                    continue
                value = ratings.values[t_index][column]
                if value is None:
                    continue
                for artist in track.artists:
                    artist_values.setdefault(artist.name, []).append(value)
        if best_album is not None:
            stats.favorite_album = (best_album[2].title, best_album[0])
        if worst_album is not None:
            stats.least_favorite_album = (
                worst_album[2].title, worst_album[0]
            )
        if rating_counts:
            # чаще всего; при равной частоте — бо́льшая оценка
            stats.favorite_rating = max(
                rating_counts.items(), key=lambda item: (item[1], item[0])
            )[0]
        if artist_values:
            def capped_mean(values: list[float]) -> float:
                return min(AlbumRatings.AVERAGE_CAP,
                           round(sum(values) / len(values), 1))

            # «алфавитно первый» при max — инвертированное имя, при
            # min — прямое; «больше треков» и там и там выигрывает
            name, values = max(
                artist_values.items(),
                key=lambda item: (
                    capped_mean(item[1]),
                    len(item[1]),
                    [-ord(ch) for ch in item[0].casefold()],
                ),
            )
            stats.favorite_artist = (name, capped_mean(values))
            name, values = min(
                artist_values.items(),
                key=lambda item: (
                    capped_mean(item[1]),
                    -len(item[1]),
                    [ord(ch) for ch in item[0].casefold()],
                ),
            )
            stats.least_favorite_artist = (name, capped_mean(values))
        return stats

    # --- Пути ---
    def resolve(self, path: str | None) -> Path | None:
        """Путь из базы → локальный файл. Поддерживает пути старых архивов."""
        if not path:
            return None
        p = Path(path)
        if p.is_absolute():
            return p
        if p.parts and p.parts[0] == "data":
            p = Path(*p.parts[1:])
        return DATA_DIR / p

    def _import_image(self, source: str | None) -> str | None:
        """Скопировать выбранную картинку в data/covers/ (путь относительно корня).

        Относительные пути от сервисов раскрываются через папку библиотеки.
        """
        if not source:
            return None
        src = self.resolve(source)
        if src is None or not src.is_file():
            return None
        try:
            COVERS_DIR.mkdir(parents=True, exist_ok=True)
            suffix = src.suffix.lower() or ".jpg"
            name = f"{uuid.uuid4().hex}{suffix}"
            shutil.copy2(src, COVERS_DIR / name)
        except OSError:
            return None  # не смогли скопировать — обойдёмся заглушкой
        return f"data/covers/{name}"

    # --- Чистка осиротевших картинок ---------------------------------------
    def _referenced_image_names(self) -> set[str]:
        """Имена файлов из data/covers, на которые ссылается база.

        Ссылки — обложки альбомов, фото и аватары-обложки исполнителей
        (в базе хранятся ОТНОСИТЕЛЬНЫЕ пути «data/covers/<имя>»).
        Аватар учитывается, даже если он ещё не попадал в базу: выбор
        происходит в памяти (см. artist_avatar_path) — файл нельзя
        считать мусором, пока на него смотрит хотя бы исполнитель.
        """
        names: set[str] = set()
        for album in self.albums:
            if album.cover_path:
                names.add(Path(album.cover_path).name)
        for artist in self.artists:
            if artist.photo_path:
                names.add(Path(artist.photo_path).name)
            if artist.avatar_path:
                names.add(Path(artist.avatar_path).name)
        return names

    def prune_covers(self) -> int:
        """Удалить из data/covers файлы, на которые не ссылается база.

        Осиротевшие картинки появляются, когда альбом удалён (файл
        обложки раньше оставался), при замене обложки/фото при
        редактировании и после импорта чужой базы (старые картинки
        новой базе не нужны). Возвращает число удалённых файлов;
        любые ошибки диска молча пропускаются — чистка не должна
        ронять операции с базой.
        """
        removed = 0
        try:
            if not COVERS_DIR.is_dir():
                return 0
            referenced = self._referenced_image_names()
            for image in sorted(COVERS_DIR.iterdir()):
                if not image.is_file():
                    continue
                if image.name in referenced:
                    continue
                try:
                    image.unlink()
                    removed += 1
                except OSError:
                    continue
        except OSError:
            return removed
        return removed

    # --- Исполнители ---
    def find_artist(self, name: str) -> Artist | None:
        """Найти исполнителя по имени (без учёта регистра)."""
        low = name.strip().casefold()
        for artist in self.artists:
            if artist.name.casefold() == low:
                return artist
        return None

    def add_artist(self, name: str, genre: str = "",
                   photo_path: str | None = None) -> Artist | None:
        """Добавить исполнителя; дубликаты игнорируются (вернётся None)."""
        if self.find_artist(name) is not None:
            return None
        artist = Artist(
            name=name.strip(),
            genre=genre,
            photo_path=self._import_image(photo_path),
        )
        self.artists.append(artist)
        self._save()
        return artist

    def artist_names(self) -> list[str]:
        """Имена всех исполнителей — для автодополнения поиска."""
        return [a.name for a in self.artists]

    def artist_avatar_path(self, artist: Artist) -> str | None:
        """Картинка для показа вместо заглушки: фото ИЛИ аватар.

        Если у исполнителя нет своего фото, аватаром назначается
        обложка ОДНОГО из его альбомов: выбирается один раз (random)
        и запоминается в базе — новые альбомы и перезапуски её не
        меняют. Файл обложки мог исчезнуть (удалён с диска) — тогда
        выбирается заново. Нет ни фото, ни альбомов с обложками —
        None (интерфейс покажет заглушку с буквой).
        """
        if artist.photo_path:
            return artist.photo_path
        if artist.avatar_path is not None:
            resolved = self.resolve(artist.avatar_path)
            if resolved is not None and resolved.is_file():
                return artist.avatar_path
            artist.avatar_path = None  # файл пропал — выберем другой
        covers: list[str] = []
        for album in self.artist_albums(artist.name):
            if not album.cover_path:
                continue
            resolved = self.resolve(album.cover_path)
            if resolved is not None and resolved.is_file():
                covers.append(album.cover_path)
        if not covers:
            return None
        artist.avatar_path = random.choice(covers)
        self._save()
        return artist.avatar_path

    def update_artist(
        self,
        artist: Artist,
        name: str,
        genre: str = "",
        photo_src: str | None = None,
        clear_photo: bool = False,
    ) -> Artist:
        """Редактирование исполнителя (страница «Редактировать»).

        Имя — ключ ссылок: переименование синхронизирует artist_names
        альбомов и исполнителей треков (фиты), оценки и порядок не
        трогаются. Жанр — указанный вручную: artist_main_genre теперь
        вернёт его (а не подсчёт по альбомам); пустая строка снова
        включает автоподсчёт. Фото: photo_src — новый файл
        (копируется в data/covers), clear_photo — убрать текущее
        (аватар-обложка при этом выбирается заново).
        """
        old_name = artist.name
        new_name = name.strip()
        if new_name.casefold() != old_name.casefold():
            existing = self.find_artist(new_name)
            if existing is not None and existing is not artist:
                return artist  # занято — вызывающий проверяет заранее
        renamed = new_name != old_name
        artist.name = new_name
        artist.genre = genre.strip()
        if clear_photo:
            artist.photo_path = None
            artist.avatar_path = None
        elif photo_src:
            imported = self._import_image(photo_src)
            if imported is not None:
                artist.photo_path = imported
        if renamed:
            low_old = old_name.casefold()
            for album in self.albums:
                album.artist_names = [
                    new_name if n.casefold() == low_old else n
                    for n in album.artist_names
                ]
                for track in album.tracks:
                    track.artists = [
                        ArtistDraft(
                            name=new_name
                            if a.name.casefold() == low_old
                            else a.name,
                            genre=a.genre,
                            photo_path=a.photo_path,
                            existing=True,
                        )
                        for a in track.artists
                    ]
        self._save()
        # Фото могло быть заменено/убрано — прежний файл мог осиротеть
        self.prune_covers()
        return artist

    def artist_albums(self, name: str) -> list[Album]:
        """Дискография исполнителя: альбомы, где он автор или соавтор.

        Учитываются только имена в artist_names альбома; участие в
        треках чужих альбомов (фиты) дискографию НЕ наполняет.
        Новые альбомы — раньше.
        """
        return [
            album for album in reversed(self.albums)
            if name in album.artist_names
        ]

    def artist_main_genre(self, name: str) -> str:
        """Основной жанр исполнителя для его страницы.

        Если жанр указан при создании — возвращается он. Если НЕ
        указан, жанр определяется автоматически: жанр, которого
        среди альбомов исполнителя (автор/соавтор, без фитов)
        больше всего; при равенстве — жанр первого альбома.
        Нет ни заданного жанра, ни альбомов — пустая строка
        (на странице покажется «—»).
        """
        artist = self.find_artist(name)
        if artist is not None and artist.genre:
            return artist.genre
        counts: dict[str, int] = {}
        for album in self.albums:
            if name in album.artist_names and album.genre:
                counts[album.genre] = counts.get(album.genre, 0) + 1
        if not counts:
            return ""
        best = max(counts.values())
        for genre, count in counts.items():
            if count == best:
                return genre
        return ""

    def artist_average_rating(self, name: str) -> float | None:
        """Средняя оценка альбомов исполнителя.

        Учитываются только альбомы, где имя стоит в artist_names
        (исполнитель — автор альбома). Участие в треках чужих
        альбомов (фиты) на оценку НЕ влияет. Если оценённых
        альбомов нет — None (карточка покажет «—»).
        """
        values = [
            album.rating
            for album in self.albums
            if name in album.artist_names and album.rating is not None
        ]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    # --- Альбомы ---
    def add_album(self, draft: AlbumDraft) -> Album:
        """Собрать Album из черновика мастера, сохранить в базу и на диск.

        Исполнители альбома уже в базе (новые попадают туда при
        добавлении в мастер) — в альбоме храним имена-ссылки.
        source_id (id альбома Deezer) запоминается для защиты от
        повторного создания по той же ссылке.
        """
        album = Album(
            title=draft.title,
            year=draft.year,
            genre=draft.genre,
            region=draft.region,
            cover_path=self._import_image(draft.cover_path),
            artist_names=[a.name for a in draft.artists],
            tracks=[
                TrackDraft(
                    title=t.title,
                    artists=[
                        ArtistDraft(
                            name=a.name,
                            genre=a.genre,
                            photo_path=a.photo_path,
                            existing=True,
                        )
                        for a in t.artists
                    ],
                )
                for t in draft.tracks
            ],
            id=uuid.uuid4().hex,
            created_at=datetime.now().isoformat(timespec="seconds"),
            source_id=draft.source_id,
        )
        self.albums.append(album)
        self._save()
        return album

    def find_album_by_source(self, source_id: str) -> Album | None:
        """Альбом, созданный по этой ссылке Deezer (по id альбома).

        Ссылки вида «…/album/123», «…/ru/album/123» и короткие
        ведут к ОДНОМУ id — сравнение по нему надёжнее сравнения
        текста ссылки. None — альбом по такой ссылке ещё не создавали.
        """
        if not source_id:
            return None
        for album in self.albums:
            if album.source_id == source_id:
                return album
        return None

    def rate_album(self, album: Album, rater_names: list[str],
                   values: list[list[float | None]], *, rater_ids: list[str | None] | None = None,
                   preserve_other_raters: bool = False) -> AlbumRatings:
        """Сохранить оценки альбома из мастера оценивания.

        rater_names — участники по столбцам; values — матрица
        [трек][участник] (None — пустая клетка, 11 — секретная).
        Средняя альбома пишется в album.rating (показывается в
        карточках и на странице альбома), момент — в rated_at
        («Недавно оценённые» поднимают альбом наверх). Возвращает
        сохранённый AlbumRatings (он же album.ratings).
        """
        ratings = AlbumRatings(
            rater_names=list(rater_names),
            values=[list(row) for row in values],
            rated_at=datetime.now().isoformat(timespec="microseconds"),
            rater_ids=list(rater_ids or ()),
        )
        if preserve_other_raters and (previous := album.ratings) is not None:
            selected = {ratings.rater_id(i) or name.casefold() for i, name in enumerate(rater_names)}
            selected_names = {name.casefold() for name in rater_names}
            ratings.rater_ids = [ratings.rater_id(i) for i in range(len(rater_names))]
            for i, name in enumerate(previous.rater_names):
                rater_id = previous.rater_id(i)
                if (rater_id or name.casefold()) in selected or (rater_id is None and name.casefold() in selected_names):
                    continue
                ratings.rater_names.append(name)
                ratings.rater_ids.append(rater_id)
                for row, old_row in zip(ratings.values, previous.values):
                    row.append(old_row[i])
        album.ratings = ratings
        album.rating = ratings.album_average()
        album.rated_at = ratings.rated_at
        self._save()
        return ratings

    def update_album(self, album: Album, draft: AlbumDraft) -> Album:
        """Редактирование альбома (кнопка «Редактировать»).

        Обновляет поля и списки СУЩЕСТВУЮЩЕГО альбома: id, даты
        (created_at), source_id ссылки Deezer и исполнительные записи
        в базе не меняются. Новые исполнители (existing=False) перед
        сохранением создаются. Если менялся ТРЕКЛИСТ (состав или
        порядок треков), сохранённые оценки треков теряют смысл —
        они сбрасываются (album.ratings/rating/rated_at), альбом снова
        «не оценён»; при правке только шапки/обложки/исполнителей
        оценки остаются.
        """
        old_tracks = [(t.title, [a.name for a in t.artists])
                      for t in album.tracks]
        new_tracks = [(t.title, [a.name for a in t.artists])
                      for t in draft.tracks]
        tracks_changed = old_tracks != new_tracks

        album.title = draft.title
        album.year = draft.year
        album.genre = draft.genre
        album.region = draft.region
        album.artist_names = [a.name for a in draft.artists]
        album.tracks = [
            TrackDraft(
                title=t.title,
                artists=[
                    ArtistDraft(
                        name=a.name,
                        genre=a.genre,
                        photo_path=a.photo_path,
                        existing=True,
                    )
                    for a in t.artists
                ],
            )
            for t in draft.tracks
        ]
        # Обложка: импортируем только НОВЫЙ файл (путь в черновике —
        # прежний относительный путь альбома или свежевыбранный файл)
        if draft.cover_path and draft.cover_path != album.cover_path:
            imported = self._import_image(draft.cover_path)
            if imported is not None:
                album.cover_path = imported
        if tracks_changed:
            album.ratings = None
            album.rating = None
            album.rated_at = None
        self._save()
        # Обложка могла быть заменена — прежний файл мог осиротеть
        self.prune_covers()
        return album

    def set_album_cover(self, album: Album, cover_path: str) -> None:
        """Записать альбому обложку (путь от корня) и сохранить базу."""
        album.cover_path = cover_path
        self._save()
        self.prune_covers()  # прежняя обложка могла осиротеть

    def update_artist_photo(self, artist: Artist, photo_path: str) -> None:
        """Записать исполнителю фото (путь от корня) и сохранить базу."""
        artist.photo_path = photo_path
        self._save()

    def delete_album(self, album: Album) -> None:
        """Удалить альбом из базы (кнопка «Удалить» на его странице).

        Исполнители НЕ удаляются вместе с альбомом: они независимы
        от своих альбомов. Альбом исчез из библиотеки — а исполнители
        (и авторы, и фиты в треках) остались: их можно найти через
        поиск, а их дискография просто станет короче.
        """
        if any(a is album for a in self.albums):
            self.albums = [a for a in self.albums if a is not album]
        self._save()
        # Файл обложки больше не нужен: он ссылался только на этот
        # альбом (аватары других исполнителей могли ссылаться на него —
        # они проверяются при чистке, чужие файлы не трогаются)
        self.prune_covers()

    # --- Чтение / запись SQL ---------------------------------------------
    def _load(self) -> None:
        """Прочитать базу в память (порядок — по колонке position).

        У каждого уровня вложенности СВОЙ курсор: повторный
        cur.execute(...) на том же курсоре сбросил бы идущую внешнюю
        итерацию (треки бы терялись).
        """
        main_cur = self._conn.cursor()
        album_cur = self._conn.cursor()
        track_cur = self._conn.cursor()
        rating_cur = self._conn.cursor()

        self.artists = [
            Artist(name=row[0], genre=row[1], photo_path=row[2],
                   avatar_path=row[3])
            for row in main_cur.execute(
                "SELECT name, genre, photo_path, avatar_path FROM artists "
                "ORDER BY position"
            )
        ]
        self.albums = []
        for row in main_cur.execute(
            "SELECT id, title, year, genre, region, cover_path, rating, "
            "rated_at, created_at, source_id, cloud_id FROM albums ORDER BY position"
        ):
            (album_id, title, year, genre, region, cover_path,
             rating, rated_at, created_at, source_id, cloud_id) = row
            artist_names = [
                r[0] for r in album_cur.execute(
                    "SELECT name FROM album_artists "
                    "WHERE album_id = ? ORDER BY position",
                    (album_id,),
                )
            ]
            tracks: list[TrackDraft] = []
            for t_pos, t_title in album_cur.execute(
                "SELECT position, title FROM album_tracks "
                "WHERE album_id = ? ORDER BY position",
                (album_id,),
            ):
                track_artists = [
                    ArtistDraft(name=r[0], existing=True)
                    for r in track_cur.execute(
                        "SELECT name FROM track_artists "
                        "WHERE album_id = ? AND track_position = ? "
                        "ORDER BY position",
                        (album_id, t_pos),
                    )
                ]
                tracks.append(TrackDraft(title=t_title, artists=track_artists))
            # Участники ЭТОГО альбома (столбцы оценок) — хранятся у
            # альбома, а не берутся из глобального списка raters:
            # состав оценивавших может отличаться от текущей шестёрки
            album_raters = list(rating_cur.execute(
                    "SELECT name, cloud_user_id FROM album_raters "
                    "WHERE album_id = ? ORDER BY position",
                    (album_id,),
            ))
            grid: list[list[float | None]] = [
                [None] * len(album_raters) for _ in tracks
            ]
            for t_pos, r_pos, value in rating_cur.execute(
                "SELECT track_position, rater_position, value "
                "FROM track_ratings WHERE album_id = ?",
                (album_id,),
            ):
                if t_pos < len(grid) and r_pos < len(album_raters):
                    grid[t_pos][r_pos] = value
            ratings = None
            if tracks and album_raters and any(
                v is not None for row in grid for v in row
            ):
                ratings = AlbumRatings(
                    rater_names=[name for name, _ in album_raters],
                    values=grid,
                    rated_at=rated_at or "",
                    rater_ids=[rater_id for _, rater_id in album_raters],
                )
            self.albums.append(Album(
                title=title,
                year=year,
                genre=genre,
                region=region,
                cover_path=cover_path,
                artist_names=artist_names,
                tracks=tracks,
                id=album_id,
                rating=rating,
                rated_at=rated_at,
                created_at=created_at,
                source_id=source_id,
                ratings=ratings,
                cloud_id=cloud_id,
            ))

    def _save(self, cloud_state: dict[str, str] | None = None) -> None:
        """Переписать базу целиком одним изменением (одна транзакция).

        Библиотека небольшая (десятки альбомов), полная перезапись
        проще и надёжнее точечных UPDATE: порядок строк и состав
        списков гарантированно совпадают с памятью.
        """
        try:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM track_artists")
            cur.execute("DELETE FROM album_tracks")
            cur.execute("DELETE FROM album_artists")
            cur.execute("DELETE FROM albums")
            cur.execute("DELETE FROM artists")
            cur.execute("DELETE FROM album_raters")
            cur.execute("DELETE FROM track_ratings")
            for position, artist in enumerate(self.artists):
                cur.execute(
                    "INSERT INTO artists (position, name, genre, "
                    "photo_path, avatar_path) VALUES (?, ?, ?, ?, ?)",
                    (position, artist.name, artist.genre,
                     artist.photo_path, artist.avatar_path),
                )
            for position, album in enumerate(self.albums):
                cur.execute(
                    "INSERT INTO albums (position, id, title, year, genre, "
                    "region, cover_path, rating, rated_at, created_at, "
                    "source_id, cloud_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        position, album.id, album.title, album.year,
                        album.genre, album.region, album.cover_path,
                        album.rating, album.rated_at, album.created_at,
                        album.source_id, album.cloud_id,
                    ),
                )
                for a_pos, name in enumerate(album.artist_names):
                    cur.execute(
                        "INSERT INTO album_artists (album_id, position, name) "
                        "VALUES (?, ?, ?)",
                        (album.id, a_pos, name),
                    )
                for t_pos, track in enumerate(album.tracks):
                    cur.execute(
                        "INSERT INTO album_tracks (album_id, position, title) "
                        "VALUES (?, ?, ?)",
                        (album.id, t_pos, track.title),
                    )
                    for a_pos, artist in enumerate(track.artists):
                        cur.execute(
                            "INSERT INTO track_artists (album_id, "
                            "track_position, position, name) "
                            "VALUES (?, ?, ?, ?)",
                            (album.id, t_pos, a_pos, artist.name),
                        )
                if album.ratings is not None:
                    for r_pos, name in enumerate(album.ratings.rater_names):
                        cur.execute(
                            "INSERT INTO album_raters (album_id, position, "
                            "name, cloud_user_id) VALUES (?, ?, ?, ?)",
                            (album.id, r_pos, name, album.ratings.rater_id(r_pos)),
                        )
                    for t_pos, row in enumerate(album.ratings.values):
                        for r_pos, value in enumerate(row):
                            cur.execute(
                                "INSERT INTO track_ratings (album_id, "
                                "track_position, rater_position, value) "
                                "VALUES (?, ?, ?, ?)",
                                (album.id, t_pos, r_pos, value),
                            )
            if cloud_state:
                cur.executemany("INSERT INTO meta (key, value) VALUES (?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                [(f"cloud_sync:{key}", value) for key, value in cloud_state.items()])
            self._conn.commit()
        except sqlite3.Error:
            try:
                self._conn.rollback()
            except sqlite3.Error:
                pass
            if cloud_state is not None:
                raise
            # нет доступа к диску/базе — работаем в памяти

    # --- Экспорт / импорт базы (вкладка «Настройки» профиля) ---------------
    def export_library(self, target: Path) -> Path:
        """Сохранить копию библиотеки в ZIP-файл (база + обложки).

        Снимок базы делается через VACUUM INTO — согласованное состояние
        без остановки приложения (даже если что-то пишется параллельно).
        В архив кладутся library.db и папка covers/ (обложки альбомов и
        фото/аватары исполнителей — в базе хранятся ОТНОСИТЕЛЬНЫЕ пути,
        поэтому без них библиотека на другом компьютере осталась бы без
        картинок). Возвращает итоговый путь; без расширения добавляется
        .zip.
        """
        target = Path(target)
        if not target.suffix:
            target = target.with_name(target.name + ".zip")
        target.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(prefix="mra-export-", suffix=".db")
        os.close(fd)
        tmp_db = Path(tmp_name)
        tmp_db.unlink()  # VACUUM INTO требует НЕсуществующий файл
        try:
            self._conn.execute("VACUUM INTO ?", (str(tmp_db),))
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(tmp_db, EXPORT_DB_ENTRY)
                if COVERS_DIR.is_dir():
                    for image in sorted(COVERS_DIR.iterdir()):
                        if image.is_file():
                            zf.write(image, EXPORT_COVERS_PREFIX + image.name)
        finally:
            tmp_db.unlink(missing_ok=True)
        return target

    def import_library(self, source: Path) -> str | None:
        """Заменить локальное наполнение базой из файла (ZIP или .db).

        Принимается: ZIP-архив из export_library (база + обложки) или
        «голый» SQLite-файл (обложки, которых нет локально, дадут
        заглушки). Файл проверяется (это база Music Rating?) ДО
        подмены живой базы: при ошибке ничего не меняется. Обложки из
        архива распаковываются в data/covers (имена — uuid, коллизий
        нет). None — успех, иначе текст ошибки для интерфейса.
        """
        source = Path(source)
        if not source.is_file():
            return "Файл не найден"

        fd, tmp_name = tempfile.mkstemp(prefix="mra-import-", suffix=".db")
        os.close(fd)
        tmp_db = Path(tmp_name)
        try:
            # 1) Достать базу из архива/файла во временный файл
            cover_names: list[str] = []
            try:
                if zipfile.is_zipfile(source):
                    try:
                        with zipfile.ZipFile(source) as zf:
                            if EXPORT_DB_ENTRY not in zf.namelist():
                                return (
                                    "В архиве нет базы "
                                    f"({EXPORT_DB_ENTRY})"
                                )
                            with zf.open(EXPORT_DB_ENTRY) as fr, open(
                                tmp_db, "wb"
                            ) as fw:
                                shutil.copyfileobj(fr, fw)
                            cover_names = [
                                name for name in zf.namelist()
                                if name.startswith(EXPORT_COVERS_PREFIX)
                                and not name.endswith("/")
                            ]
                    except (zipfile.BadZipFile, OSError):
                        return "Не удалось прочитать архив"
                else:
                    shutil.copyfile(source, tmp_db)
            except OSError:
                return "Не удалось прочитать файл"

            # 2) Проверить структуру ДО подмены живой базы
            try:
                check = sqlite3.connect(tmp_db)
                try:
                    tables = {
                        row[0] for row in check.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type = 'table'"
                        )
                    }
                    if not REQUIRED_TABLES <= tables:
                        return "Это не база Music Rating"
                finally:
                    check.close()
            except sqlite3.Error:
                return "Файл повреждён или это не база SQLite"

            # 3) Обложки из архива → data/covers (имена — только basename)
            for name in cover_names:
                try:
                    with zipfile.ZipFile(source) as zf:
                        data = zf.read(name)
                    COVERS_DIR.mkdir(parents=True, exist_ok=True)
                    (COVERS_DIR / Path(name).name).write_bytes(data)
                except (OSError, zipfile.BadZipFile, KeyError):
                    continue  # недостающая обложка — заглушка, не ошибка

            # 4) Подменить живую базу. Соединение сначала закрывается —
            #    на Windows открытый файл не заменить. Копия сначала в
            #    соседний staging-файл, затем os.replace (атомарно);
            #    если копирование оборвалось — старая база не тронута.
            self._conn.close()
            staging = DB_FILE.parent / (DB_FILE.name + ".new")
            try:
                shutil.copyfile(tmp_db, staging)
                os.replace(staging, DB_FILE)
            except OSError:
                staging.unlink(missing_ok=True)
                return "Не удалось записать базу на диск"
            finally:
                self._conn = sqlite3.connect(DB_FILE)

            # 5) Схема (на случай базы от старой версии) и перечитывание.
            #    Засев демо-данными отменяется: у импортированной базы
            #    своя история — пользователь мог сознательно выбрать
            #    пустую базу.
            self._ensure_schema()
            if self._meta_get("seeded") is None:
                self._meta_set("seeded", "1")
            self._load()
            # Картинки прежней библиотеки новой базе не нужны:
            # всё, на что не ссылается импортированная база — мусор
            self.prune_covers()
            return None
        finally:
            tmp_db.unlink(missing_ok=True)

    # --- Перенос прежнего JSON ---------------------------------------------
    def _migrate_legacy_json(self) -> None:
        """Однократный перенос data/library.json в SQL-базу.

        Выполняется, только если база ещё ни разу не инициализировалась
        (нет метки «seeded»), а JSON-файл прежней версии существует:
        библиотека пользователя полностью переезжает в SQL. Сам JSON
        остаётся на диске как резервная копия.
        """
        if self._meta_get("seeded") is not None:
            return  # база уже инициализирована — перенос не нужен
        if not LIBRARY_FILE.is_file():
            return
        try:
            payload = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # повреждённый файл не валит приложение
        self.artists = [
            Artist(
                name=a.get("name", ""),
                genre=a.get("genre", ""),
                photo_path=a.get("photo_path"),
            )
            for a in payload.get("artists", [])
        ]
        self.albums = [
            Album(
                title=raw.get("title", ""),
                year=raw.get("year", ""),
                genre=raw.get("genre", ""),
                region=raw.get("region", "RU"),
                cover_path=raw.get("cover_path"),
                artist_names=list(raw.get("artist_names", [])),
                tracks=[
                    TrackDraft(
                        title=t.get("title", ""),
                        artists=[
                            ArtistDraft(name=name, existing=True)
                            for name in t.get("artists", [])
                        ],
                    )
                    for t in raw.get("tracks", [])
                ],
                id=raw.get("id", ""),
                rating=raw.get("rating"),
                rated_at=raw.get("rated_at"),
                created_at=raw.get("created_at", ""),
                source_id=raw.get("source_id", ""),
            )
            for raw in payload.get("albums", [])
        ]
        self._save()
        self._meta_set("seeded", "1")


STORE = MusicStore()  # единый экземпляр на приложение
