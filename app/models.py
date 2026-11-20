"""Модели данных приложения.

Album/Artist — сохраняемые сущности (база — SQL, data/library.db,
см. app/store.py). *Draft — черновики мастера создания, в базу они
не пишутся напрямую: их превращает в Album/Artist store.add_album().
"""

import zlib
from dataclasses import dataclass, field

# Приглушённые тёмные тона для обложек-заглушек (без синего/индиго)
COVER_COLORS = [
    "#4a4034",  # тёплый коричневый
    "#3d4438",  # оливково-серый
    "#473a44",  # пыльный сливовый
    "#3a4347",  # серо-графитовый
    "#4a4432",  # горчично-серый
    "#40343c",  # тёмный баклажанный
]


# Стартовый список жанров: выпадающие списки мастера и диалогов.
# Можно вписать и свой вариант — поля редактируемые.
STARTER_GENRES = [
    "Рок", "Поп", "Хип-хоп", "Электроника", "Джаз", "Классика",
    "Метал", "Панк", "Инди", "Альтернатива", "Фолк", "Соул", "R&B",
]


def _stable_color(text: str) -> str:
    """Стабильный приглушённый цвет для заглушки по тексту."""
    index = zlib.crc32(text.encode("utf-8")) % len(COVER_COLORS)
    return COVER_COLORS[index]


def _display_letter(text: str) -> str:
    """Первая буквенная символ строки — для обложки-заглушки."""
    for ch in text:
        if ch.isalpha():
            return ch.upper()
    return "?"


@dataclass
class Artist:
    """Исполнитель из базы приложения."""

    name: str
    genre: str = ""
    photo_path: str | None = None   # путь внутрь data/ (см. store)
    # Аватар-обложка (когда своего фото нет): обложка одного из
    # альбомов, выбирается один раз и запоминается (store).
    avatar_path: str | None = None

    @property
    def display_letter(self) -> str:
        """Первая буква имени — для заглушки фото."""
        return _display_letter(self.name)

    @property
    def display_color(self) -> str:
        """Стабильный цвет заглушки: одинаковый при каждом запуске."""
        return _stable_color(self.name)


@dataclass
class ArtistDraft:
    """Исполнитель альбома или трека.

    Может быть добавлен как уже существующий в базе (existing=True,
    поиск по имени) или как новый — тогда заполняются необязательные
    основной жанр и фото.
    """

    name: str                       # имя (обязательно)
    genre: str = ""                 # основной жанр (необязательно)
    photo_path: str | None = None   # фото (необязательно)
    existing: bool = False          # True — из базы, False — новый


@dataclass
class TrackDraft:
    """Трек альбома (шаг «Треклист» мастера создания).

    Название обязательно; исполнители необязательны — список
    черновиков ArtistDraft, общий с шагом «Исполнители».
    """

    title: str
    artists: list[ArtistDraft] = field(default_factory=list)


@dataclass
class AlbumDraft:
    """Черновик создаваемого альбома (мастер создания, шаги 1–3)."""

    title: str = ""          # шаг 1: название (обязательно)
    year: str = ""           # шаг 1: год, 4 цифры (обязательно)
    genre: str = ""          # шаг 1: жанр, можно свой (необязательно)
    region: str = "RU"       # шаг 1: регион RU/WW (обязательно)
    cover_path: str | None = None  # шаг 1: путь к обложке (необязательно)
    artists: list[ArtistDraft] = field(default_factory=list)  # шаг 2
    tracks: list[TrackDraft] = field(default_factory=list)    # шаг 3
    source_id: str = ""      # id источника («spotify:<id>» или id Deezer)


@dataclass
class User:
    """Аккаунт пользователя (система профилей).

    Пароль хранится ТОЛЬКО в виде хэша PBKDF2-HMAC-SHA256 со своей
    солью (см. store.register_user) — восстановить исходный текст
    нельзя. last_rated_at — момент последней оценки, в которой этот
    пользователь участвовал (обновляется при «Готово» в мастере
    оценивания); показывается на вкладке «Главная» окна профиля.
    """

    id: str                       # заполняет store при регистрации
    username: str
    password_hash: str = ""
    password_salt: str = ""
    created_at: str = ""          # момент регистрации (ISO-строка)
    last_rated_at: str | None = None


@dataclass
class UserStats:
    """Статистика пользователя (вкладка «Статистика» окна профиля).

    favorite_album — (название, средняя оценка пользователя этому
    альбому); favorite_artist — (имя, средняя оценка пользователя
    его трекам). least_favorite_* — зеркальные «нелюбимые»: самые
    низкие средние по тем же правилам (при равенстве — оценённый
    позже / больше треков / алфавитно). favorite_rating — оценка,
    которую пользователь ставит ЧАЩЕ ВСЕГО (при равенстве частоты —
    бо́льшее значение). Средние — как всюду в приложении: по
    заполненным клеткам и максимум 10. None — пока нет ни одной
    оценки.
    """

    rated_count: int = 0          # альбомов, где пользователь ставил оценки
    favorite_album: tuple[str, float] | None = None
    favorite_artist: tuple[str, float] | None = None
    favorite_rating: float | None = None    # самая частая оценка
    least_favorite_album: tuple[str, float] | None = None
    least_favorite_artist: tuple[str, float] | None = None


@dataclass
class AlbumRatings:
    """Оценки альбома из мастера оценивания (3 этапа).

    values — матрица [трек][участник]: None — клетка не заполнена;
    11 — «секретная» оценка (у каждого участника максимум одна на
    альбом, см. мастер оценивания). Средние считаются только по
    заполненным клеткам; секретная 11 участвует в среднем как 11, но
    ИТОГОВАЯ средняя (альбома, участника, трека) не бывает выше 10 —
    даже если из-за секретных оценок арифметика даёт больше.
    """

    AVERAGE_CAP = 10.0   # предельная итоговая средняя (см. ТЗ)

    rater_names: list[str] = field(default_factory=list)   # столбцы
    values: list[list[float | None]] = field(default_factory=list)
    rated_at: str = ""          # момент сохранения оценок (ISO)
    rater_ids: list[str | None] = field(default_factory=list)

    def rater_id(self, column: int) -> str | None:
        return self.rater_ids[column] if column < len(self.rater_ids) else None

    # --- Заполненность -------------------------------------------------
    def filled_count(self) -> int:
        """Сколько клеток заполнено всего."""
        return sum(
            1
            for row in self.values
            for value in row
            if value is not None
        )

    # --- Средние -------------------------------------------------------
    def album_average(self) -> float | None:
        """Средняя оценка альбома: по всем заполненным клеткам.

        Максимум 10, даже если секретные 11 сдвинули среднюю выше.
        """
        filled = [
            value
            for row in self.values
            for value in row
            if value is not None
        ]
        if not filled:
            return None
        return min(self.AVERAGE_CAP, round(sum(filled) / len(filled), 1))

    def participant_average(self, column: int) -> float | None:
        """Средняя оценка альбома одним участником (по его столбцу).

        Максимум 10, даже если секретная 11 подняла среднюю выше.
        """
        filled = [
            row[column]
            for row in self.values
            if row[column] is not None
        ]
        if not filled:
            return None
        return min(self.AVERAGE_CAP, round(sum(filled) / len(filled), 1))

    # --- Любимые треки -------------------------------------------------
    def participant_favorite(self, column: int) -> int | None:
        """Номер трека (индекс), который участник оценил выше всех.

        При равенстве — САМЫЙ ПОСЛЕДНИЙ в треклисте (ниже по списку).
        Ни одной заполненной клетки в столбце — None.
        """
        best_index: int | None = None
        best_value: float | None = None
        for index, row in enumerate(self.values):
            value = row[column]
            if value is None:
                continue
            if best_value is None or value >= best_value:
                best_value = value
                best_index = index
        return best_index

    def track_average(self, index: int) -> float | None:
        """Средняя оценка трека по всем участникам (не выше 10)."""
        filled = [v for v in self.values[index] if v is not None]
        if not filled:
            return None
        return min(self.AVERAGE_CAP, round(sum(filled) / len(filled), 1))

    def overall_favorite(self) -> tuple[int, float] | None:
        """Любимый трек всех: трек с наивысшей средней оценкой.

        Возвращает (индекс трека, средняя); при равенстве средних —
        самый последний в треклисте. Ни одной заполненной клетки — None.
        """
        best_index: int | None = None
        best_average: float | None = None
        for index in range(len(self.values)):
            average = self.track_average(index)
            if average is None:
                continue
            if best_average is None or average >= best_average:
                best_average = average
                best_index = index
        if best_index is None or best_average is None:
            return None
        return (best_index, best_average)


@dataclass
class Album:
    """Альбом в базе.

    Оценка 0–10 с шагом 0.1 (None — ещё не оценён); rated_at — момент
    последней оценки (ISO-строка): по нему строится очередь «Недавно
    оценённые» (свежая оценка — на первую позицию). Сама оценка больше
    НЕ ставится вручную на странице альбома (появится в ином виде) —
    поля остаются в базе: у ранее оценённых альбомов оценки и средние
    оценки исполнителей продолжают показываться.
    """

    title: str
    year: str = ""
    genre: str = ""
    region: str = "RU"
    cover_path: str | None = None   # путь внутрь data/ (см. store)
    artist_names: list[str] = field(default_factory=list)
    tracks: list[TrackDraft] = field(default_factory=list)
    id: str = ""                    # заполняет store при создании
    rating: float | None = None
    rated_at: str | None = None
    created_at: str = ""            # момент создания (ISO-строка)
    source_id: str = ""            # id источника («spotify:<id>» или Deezer)
                                 # (защита от повторного создания по той же ссылке)
    ratings: AlbumRatings | None = None   # оценки по трекам/участникам
                                 # (мастер оценивания; rating — средняя)
    cloud_id: str = ""

    @property
    def artists_text(self) -> str:
        """Исполнители одной строкой: «Земфира · Muse» / «—»."""
        return " · ".join(self.artist_names) if self.artist_names else "—"

    @property
    def meta_text(self) -> str:
        """Строка «год · жанр» под исполнителем на странице альбома."""
        return " · ".join(part for part in (self.year, self.genre) if part)

    @property
    def cover_letter(self) -> str:
        """Первая буква названия — для обложки-заглушки."""
        return _display_letter(self.title)

    @property
    def cover_color(self) -> str:
        """Стабильный цвет обложки: одинаковый при каждом запуске."""
        return _stable_color(self.title)

    @property
    def rating_text(self) -> str:
        """Оценка одной строкой: 8.3 / — (если ещё не оценён)."""
        return f"{self.rating:.1f}" if self.rating is not None else "—"
