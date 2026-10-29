"""Хранилище данных приложения — SQL (SQLite).

База — SQLite-файл data/library.db рядом с приложением (создаётся
при первом изменении). Схема реляционная, SQL стандартный (плейсхолдеры
«?») — при переезде на облачное SQL-хранилище заменить нужно будет
только подключение в этом файле, интерфейс MusicStore не меняется:

    artists       — исполнители (имя — ключ, порядок хранения = position)
    albums        — альбомы (id, оценка, даты, source_id ссылки Deezer)
    album_artists — исполнители альбома (список artist_names по порядку)
    album_tracks  — треки альбома (по порядку)
    track_artists — исполнители каждого трека (по порядку)
    users         — аккаунты (система профилей): вход, участники оценивания
    album_raters  — участники конкретного альбома (столбцы оценок)
    track_ratings — оценки треков участниками [трек][участник]

ПРОФИЛИ: участники оценивания (плитки на шаге 1 мастера) — это
ЗАРЕГИСТРИРОВАННЫЕ АККАНТЫ (таблица users); прежние заглушки
(«Кирилл», «Володя»…) больше не создаются. Пароли хранятся только
в виде PBKDF2-хэшей с индивидуальной солью. Текущий пользователь
(сессия) переживает перезапуск приложения — хранится в meta.

Порядок строк хранится в колонке position: «новые — раньше» в списках
и дискографиях строится по порядку вставки, как раньше. Каждое
изменение сразу пишется в базу (одна транзакция на изменение).

ОБЛОЖКИ И ФОТО: при добавлении копируются в data/covers/, в базе
хранятся пути ОТНОСИТЕЛЬНО папки приложения — библиотеку можно
переносить вместе с папкой. Прежний JSON (data/library.json) при
первом запуске с SQL-версией автоматически переносится в базу
(см. _migrate_legacy_json) — библиотека пользователя не теряется.

Интерфейс для интерфейса приложения: find_*/add_*/names (исполнители),
add_album/rate_album (альбомы), find_album_by_source (альбом, созданный
по ссылке Deezer), artist_average_rating (средняя оценка исполнителя),
artist_albums/artist_main_genre (дискография и основной жанр для его
страницы).

Исполнители НЕЗАВИСИМЫ от альбомов: delete_album убирает только
альбом — исполнители (и авторы, и фиты) остаются в базе.

При САМОМ ПЕРВОМ запуске (в базе ещё нет ни одной записи и переносить
нечего) база наполняется тестовыми данными (8 альбомов, 10
исполнителей) — чтобы сразу было видно, как выглядит заполненная
главная страница. Факт инициализации фиксируется в таблице meta:
пользователь удалил демо-альбомы (кнопка «Удалить» на странице
альбома) — они и не вернутся при следующих запусках.
"""

import hashlib
import json
import os
import random
import secrets
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from app.models import (
    Album,
    AlbumDraft,
    AlbumRatings,
    Artist,
    ArtistDraft,
    TrackDraft,
    User,
    UserStats,
)

APP_ROOT = Path(__file__).resolve().parent.parent   # папка music-rating-app
DATA_DIR = APP_ROOT / "data"
COVERS_DIR = DATA_DIR / "covers"
DB_FILE = DATA_DIR / "library.db"       # база SQL
LIBRARY_FILE = DATA_DIR / "library.json"  # прежний формат (для переноса)

# Имя базы внутри экспортного ZIP-архива (см. export_library)
EXPORT_DB_ENTRY = "library.db"
EXPORT_COVERS_PREFIX = "covers/"
# Обязательные таблицы базы Music Rating (проверка при импорте)
REQUIRED_TABLES = {"meta", "artists", "albums", "users", "album_tracks"}

# Число итераций PBKDF2 для хэшей паролей (компромисс скорость/надёжность)
PBKDF2_ITERATIONS = 120_000

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
    source_id  TEXT NOT NULL DEFAULT ''
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

CREATE TABLE IF NOT EXISTS raters (
    position INTEGER NOT NULL,
    name     TEXT NOT NULL,
    PRIMARY KEY (position)
);

CREATE TABLE IF NOT EXISTS users (
    position      INTEGER NOT NULL,
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT '',
    last_rated_at TEXT
);

CREATE TABLE IF NOT EXISTS album_raters (
    album_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    name     TEXT NOT NULL,
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
        self.users: list[User] = []    # аккаунты (= участники оценивания)
        self._current_user_id: str | None = None
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(DB_FILE)
        self._ensure_schema()
        # Прежний library.json переносится в SQL-базу один раз
        self._migrate_legacy_json()
        self._load()
        # ТЕСТОВАЯ СБОРКА: демо-наполнение НЕ создаётся никогда —
        # библиотека и аккаунты стартуют пустыми (наполнение появится
        # после импорта базы, подготовленной в dev-версии). Метку
        # «seeded» всё равно ставим: логика переноса прежнего JSON и
        # импорта опирается на неё.
        if self._meta_get("seeded") is None:
            self._meta_set("seeded", "1")

    def _ensure_schema(self) -> None:
        """Схема и миграции старых баз (используется и при импорте).

        CREATE TABLE IF NOT EXISTS idempotentен; колонка avatar_path
        появилась позже остальных — старые базы дополняются через
        ALTER TABLE. Таблица raters больше не используется (участники —
        аккаунты): в старых базах в ней могли остаться заглушки —
        очищаем.
        """
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
        self._conn.execute("DELETE FROM raters")
        self._conn.commit()

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

    def _meta_delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        self._conn.commit()

    # --- Участники оценивания (= аккаунты) ---------------------------------
    @property
    def raters(self) -> list[str]:
        """Имена участников для шага 1 мастера оценивания.

        Это ЗАРЕГИСТРИРОВАННЫЕ АККАНТЫ (в порядке регистрации):
        создали профиль — имя появилось в списке участников. Прежние
        заглушки (Кирилл, Володя и т.д.) больше не подставляются;
        уже сохранённые оценки старых участников в альбомах не трогаются
        (состав столбцов хранится у каждого альбома).
        """
        return [user.username for user in self.users]

    # --- Профили: пароли и сессия ------------------------------------------
    @staticmethod
    def _hash_password(password: str, salt_hex: str) -> str:
        """PBKDF2-HMAC-SHA256 пароля с солью (hex). Обратимости нет."""
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            PBKDF2_ITERATIONS,
        ).hex()

    def find_user(self, username: str) -> User | None:
        """Аккаунт по имени (без учёта регистра)."""
        low = username.strip().casefold()
        for user in self.users:
            if user.username.casefold() == low:
                return user
        return None

    @property
    def current_user(self) -> User | None:
        """Залогиненный пользователь (сессия переживает перезапуск)."""
        if self._current_user_id is None:
            return None
        return next(
            (u for u in self.users if u.id == self._current_user_id),
            None,
        )

    def set_current_user(self, user: User | None) -> None:
        """Запомнить/сбросить сессию (meta — переживает перезапуск)."""
        self._current_user_id = user.id if user is not None else None
        if user is None:
            self._meta_delete("current_user_id")
        else:
            self._meta_set("current_user_id", user.id)

    def logout(self) -> None:
        """Выйти из аккаунта (профиль останется в списке участников)."""
        self.set_current_user(None)

    def register_user(self, username: str, password: str,
                      password_again: str | None = None
                      ) -> tuple[User | None, str | None]:
        """Регистрация аккаунта (он же — новый участник оценивания).

        Возвращает (пользователь, None) при успехе и (None, текст
        ошибки) при отказе: пустые имя/пароль, несовпадение пароля
        с подтверждением, имя уже занято (регистр не важен).
        """
        name = username.strip()
        if not name or not password:
            return (None, "Введите логин и пароль")
        if password_again is not None and password != password_again:
            return (None, "Пароли не совпадают")
        if self.find_user(name) is not None:
            return (None, "Такой логин уже занят")
        salt = secrets.token_bytes(16).hex()
        user = User(
            id=uuid.uuid4().hex,
            username=name,
            password_hash=self._hash_password(password, salt),
            password_salt=salt,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.users.append(user)
        self.set_current_user(user)  # сразу залогинить нового
        self._save()
        return (user, None)

    def authenticate(self, username: str, password: str
                     ) -> tuple[User | None, str | None]:
        """Вход по имени и паролю; успех — сессия запомнена."""
        user = self.find_user(username)
        if user is None or self._hash_password(
            password, user.password_salt
        ) != user.password_hash:
            return (None, "Неверный логин или пароль")
        self.set_current_user(user)
        return (user, None)

    def change_password(self, user: User, new: str) -> str | None:
        """Сменить пароль (окно профиля → «Настройки»).

        Форма смены — два поля (новый пароль и подтверждение) БЕЗ
        ввода текущего пароля (пользователь уже вошёл в аккаунт);
        совпадение двух полей проверяет окно профиля. None — успех,
        иначе текст ошибки. Пароль нельзя «сменить» на тот же, что
        уже стоит: новый, свёртанный с текущей солью, обязан отличаться
        от текущего хэша.
        """
        if not new:
            return "Новый пароль не может быть пустым"
        if self._hash_password(new, user.password_salt) == user.password_hash:
            return "Новый пароль совпадает с текущим"
        user.password_salt = secrets.token_bytes(16).hex()
        user.password_hash = self._hash_password(new, user.password_salt)
        self._save()
        return None

    def rename_user(self, user: User, new_username: str) -> str | None:
        """Переименовать аккаунт (окно профиля → «Настройки»).

        Имя — ключ участника оценивания: обновляется и в списке
        аккаунтов, и в составах оценивавших УЖЕ ОЦЕНЁННЫХ альбомов
        (столбцы оценок остаются на своих местах, оценки не теряются).
        Сессия не сбрасывается (пользователь опознаётся по id).
        «Сменить» имя на то же самое нельзя — возвращается ошибка
        (смена только регистра допускается: строка другая).
        None — успех, иначе текст ошибки.
        """
        name = new_username.strip()
        if not name:
            return "Введите новое имя"
        if name == user.username:
            return "Это уже ваше текущее имя"
        existing = self.find_user(name)
        if existing is not None and existing.id != user.id:
            return "Такой логин уже занят"
        old = user.username
        user.username = name
        for album in self.albums:
            ratings = album.ratings
            if ratings is None:
                continue
            ratings.rater_names = [
                name if rater == old else rater
                for rater in ratings.rater_names
            ]
        self._save()
        return None

    def delete_user(self, user: User) -> None:
        """Удалить аккаунт и ЕГО ОЦЕНКИ из всех альбомов.

        Столбец участника убирается из матриц оценок, средние
        альбомов пересчитываются; альбом, который после этого
        больше некому оценивать, снова «не оценён» (оценка и дата
        сбрасываются). Имя исчезает из списка участников.
        """
        self.users = [u for u in self.users if u.id != user.id]
        for album in self.albums:
            ratings = album.ratings
            if ratings is None or user.username not in ratings.rater_names:
                continue
            column = ratings.rater_names.index(user.username)
            new_names = [
                name for i, name in enumerate(ratings.rater_names)
                if i != column
            ]
            new_values = [
                [v for i, v in enumerate(row) if i != column]
                for row in ratings.values
            ]
            if new_names and any(
                v is not None for row in new_values for v in row
            ):
                updated = AlbumRatings(
                    rater_names=new_names,
                    values=new_values,
                    rated_at=ratings.rated_at,
                )
                album.ratings = updated
                album.rating = updated.album_average()
            else:
                album.ratings = None
                album.rating = None
                album.rated_at = None
        if self.current_user is user:
            self.set_current_user(None)
        self._save()

    def user_stats(self, user: User) -> UserStats:
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
            if ratings is None or user.username not in ratings.rater_names:
                continue
            column = ratings.rater_names.index(user.username)
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
        """Путь из базы → реальный файл (относительные — от папки приложения)."""
        if not path:
            return None
        p = Path(path)
        return p if p.is_absolute() else APP_ROOT / p

    def _import_image(self, source: str | None) -> str | None:
        """Скопировать выбранную картинку в data/covers/ (путь относительно корня).

        Относительные пути (например, «data/covers/x.jpg» из
        сервисов) считаются от папки приложения, а не от текущего
        каталога запуска — обложки не теряются при запуске из
        другой папки.
        """
        if not source:
            return None
        src = Path(source)
        if not src.is_absolute():
            src = APP_ROOT / src
        if not src.is_file():
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
                   values: list[list[float | None]]) -> AlbumRatings:
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
            rated_at=datetime.now().isoformat(timespec="seconds"),
        )
        album.ratings = ratings
        album.rating = ratings.album_average()
        album.rated_at = ratings.rated_at
        # Профили: момент последней оценки — каждому участнику-
        # аккаунту, который ставил оценки в этом сеансе (вкладка
        # «Главная» окна профиля)
        now = ratings.rated_at
        for user in self.users:
            if user.username in ratings.rater_names:
                user.last_rated_at = now
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

        self.users = [
            User(
                id=row[0],
                username=row[1],
                password_hash=row[2],
                password_salt=row[3],
                created_at=row[4],
                last_rated_at=row[5],
            )
            for row in main_cur.execute(
                "SELECT id, username, password_hash, password_salt, "
                "created_at, last_rated_at FROM users ORDER BY position"
            )
        ]
        current_id = self._meta_get("current_user_id")
        self._current_user_id = current_id if any(
            u.id == current_id for u in self.users
        ) else None

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
            "rated_at, created_at, source_id FROM albums ORDER BY position"
        ):
            (album_id, title, year, genre, region, cover_path,
             rating, rated_at, created_at, source_id) = row
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
            album_raters = [
                r[0] for r in rating_cur.execute(
                    "SELECT name FROM album_raters "
                    "WHERE album_id = ? ORDER BY position",
                    (album_id,),
                )
            ]
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
                    rater_names=album_raters,
                    values=grid,
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
            ))

    def _save(self) -> None:
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
            cur.execute("DELETE FROM users")
            cur.execute("DELETE FROM album_raters")
            cur.execute("DELETE FROM track_ratings")
            for position, user in enumerate(self.users):
                cur.execute(
                    "INSERT INTO users (position, id, username, "
                    "password_hash, password_salt, created_at, "
                    "last_rated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        position, user.id, user.username,
                        user.password_hash, user.password_salt,
                        user.created_at, user.last_rated_at,
                    ),
                )
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
                    "source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        position, album.id, album.title, album.year,
                        album.genre, album.region, album.cover_path,
                        album.rating, album.rated_at, album.created_at,
                        album.source_id,
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
                            "name) VALUES (?, ?, ?)",
                            (album.id, r_pos, name),
                        )
                    for t_pos, row in enumerate(album.ratings.values):
                        for r_pos, value in enumerate(row):
                            cur.execute(
                                "INSERT INTO track_ratings (album_id, "
                                "track_position, rater_position, value) "
                                "VALUES (?, ?, ?, ?)",
                                (album.id, t_pos, r_pos, value),
                            )
            self._conn.commit()
        except sqlite3.Error:
            try:
                self._conn.rollback()
            except sqlite3.Error:
                pass
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

    # --- Тестовая библиотека ---
    def _seed_test_library(self) -> None:
        """Тестовые данные: 8 альбомов и 10 исполнителей.

        Вызывается ТОЛЬКО при самом первом запуске (в базе ещё нет ни
        одной записи, переносить нечего): с ними главная страница
        сразу выглядит заполненной, а плитка «Смотреть все» видна во
        всех трёх сегментах (8 альбомов > 7 и 10 исполнителей > 7),
        в том числе в «Недавно оценённые». Оценки покрывают все
        четыре цвета шкалы. Пользователь удаляет демо-альбомы через
        интерфейс — повторных засевов больше нет (метка в meta).
        """
        known_artists = {a.name.casefold() for a in self.artists}
        known_titles = {a.title.casefold() for a in self.albums}
        changed = False

        for name, genre in TEST_ARTISTS:
            if name.casefold() in known_artists:
                continue
            self.artists.append(Artist(name=name, genre=genre))
            changed = True

        for spec in TEST_ALBUMS:
            if spec["title"].casefold() in known_titles:
                continue
            self.albums.append(Album(
                title=spec["title"],
                year=spec["year"],
                genre=spec["genre"],
                region=spec["region"],
                cover_path=None,  # заглушка-обложка (буква + цвет)
                artist_names=list(spec["artists"]),
                tracks=[
                    TrackDraft(
                        title=track_title,
                        artists=[
                            ArtistDraft(name=name, existing=True)
                            for name in track_artists
                        ],
                    )
                    for track_title, track_artists in spec["tracks"]
                ],
                id=uuid.uuid4().hex,
                rating=spec["rating"],
                rated_at=spec["rated_at"],
                created_at=spec["created_at"],
            ))
            changed = True

        if changed:
            self._save()


# --- Тестовая библиотека: 8 альбомов и 10 исполнителей ---
# Оценки альбомов специально покрывают все четыре цвета шкалы:
# красный (0–3.9), жёлтый (4–6.9), зелёный (7–8.9), голубовато-
# синий (9–10). Восьмой альбом нужен, чтобы оценённых стало больше
# семи — тогда плитка «Смотреть все» видна и в «Недавно оценённые»,
# и в «Оценённых альбомах». Найк Борзов, Хадн дадн и Пошлая Молли
# встречаются только фитами в чужих треках — средней оценки у них
# нет.
TEST_ARTISTS = [
    ("Земфира", "Рок"),
    ("Мумий Тролль", "Рок"),
    ("Сплин", "Рок"),
    ("Би-2", "Рок"),
    ("Дельфин", "Хип-хоп"),
    ("Скриптонит", "Хип-хоп"),
    ("Zivert", "Поп"),
    ("Найк Борзов", "Поп"),
    ("Хадн дадн", "Инди"),
    ("Пошлая Молли", "Альтернатива"),
]

TEST_ALBUMS = [
    {
        "title": "Морская",
        "year": "1997", "genre": "Рок", "region": "RU",
        "rating": 8.4,  # зелёный
        "rated_at": "2025-06-01T10:00:00",
        "created_at": "2025-06-01T09:50:00",
        "artists": ["Мумий Тролль"],
        "tracks": [
            ("Утекай", ["Мумий Тролль"]),
            ("Кот кота", ["Мумий Тролль"]),
            ("Владивосток 2000", ["Мумий Тролль"]),
        ],
    },
    {
        "title": "Гранатовый альбом",
        "year": "1998", "genre": "Рок", "region": "RU",
        "rating": 7.8,  # зелёный
        "rated_at": "2025-06-01T11:00:00",
        "created_at": "2025-06-01T10:50:00",
        "artists": ["Сплин"],
        "tracks": [
            ("Выхода нет", ["Сплин"]),
            ("Романс", ["Сплин"]),
            # фит: Найк Борзов — он не автор альбома
            ("Мороз по коже", ["Сплин", "Найк Борзов"]),
        ],
    },
    {
        "title": "Нечего терять",
        "year": "2017", "genre": "Рок", "region": "RU",
        "rating": 6.5,  # жёлтый
        "rated_at": "2025-06-01T12:00:00",
        "created_at": "2025-06-01T11:50:00",
        "artists": ["Би-2"],
        "tracks": [
            ("Филасовый", ["Би-2"]),
            ("Пора возвращаться домой", ["Би-2"]),
            ("Медленная звезда", ["Би-2"]),
        ],
    },
    {
        "title": "Глубина резкости",
        "year": "2021", "genre": "Хип-хоп", "region": "RU",
        "rating": 4.7,  # жёлтый
        "rated_at": "2025-06-01T13:00:00",
        "created_at": "2025-06-01T12:50:00",
        "artists": ["Дельфин"],
        "tracks": [
            ("Наперёд", ["Дельфин"]),
            # фит: Хадн дадн — она не автор альбома
            ("Стекло", ["Дельфин", "Хадн дадн"]),
            ("Дверь", ["Дельфин"]),
        ],
    },
    {
        "title": "Дом с нормальными явлениями",
        "year": "2015", "genre": "Хип-хоп", "region": "WW",
        "rating": 3.4,  # красный
        "rated_at": "2025-06-01T14:00:00",
        "created_at": "2025-06-01T13:50:00",
        "artists": ["Скриптонит"],
        "tracks": [
            ("Это любовь", ["Скриптонит"]),
            ("Положение", ["Скриптонит"]),
            ("Витамин", ["Скриптонит"]),
        ],
    },
    {
        "title": "RGB",
        "year": "2019", "genre": "Поп", "region": "WW",
        "rating": 2.1,  # красный
        "rated_at": "2025-06-01T15:00:00",
        "created_at": "2025-06-01T14:50:00",
        "artists": ["Zivert"],
        "tracks": [
            ("Life", ["Zivert"]),
            ("Твой Д", ["Zivert"]),
            # фит: Пошлая Молли — она не автор альбома
            ("Credo", ["Zivert", "Пошлая Молли"]),
        ],
    },
    {
        "title": "Прости меня моя любовь",
        "year": "2000", "genre": "Рок", "region": "RU",
        "rating": 9.2,  # голубовато-синий
        "rated_at": "2025-06-01T16:00:00",
        "created_at": "2025-06-01T15:50:00",
        "artists": ["Земфира"],
        "tracks": [
            ("Искала", ["Земфира"]),
            ("Хочешь?", ["Земфира"]),
            ("Бесконечность", ["Земфира"]),
        ],
    },
    {
        "title": "Земфира",
        "year": "1999", "genre": "Рок", "region": "RU",
        "rating": 9.6,  # голубовато-синий; свежая оценка —
        # первая карточка в «Недавно оценённые»
        "rated_at": "2025-06-01T17:00:00",
        "created_at": "2025-06-01T16:50:00",
        "artists": ["Земфира"],
        "tracks": [
            ("Ариведерчи", ["Земфира"]),
            ("Скандал", ["Земфира"]),
            ("Синоптик", ["Земфира"]),
        ],
    },
]

STORE = MusicStore()  # единый экземпляр на приложение
