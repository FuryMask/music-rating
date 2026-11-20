import uuid

from app.models import Album, Artist, ArtistDraft, TrackDraft


def populate_library(store) -> None:
    """Наполнить временную библиотеку демонстрационными данными для проверок."""
    known_artists = {a.name.casefold() for a in store.artists}
    known_titles = {a.title.casefold() for a in store.albums}
    changed = False

    for name, genre in TEST_ARTISTS:
        if name.casefold() in known_artists:
            continue
        store.artists.append(Artist(name=name, genre=genre))
        changed = True

    for spec in TEST_ALBUMS:
        if spec["title"].casefold() in known_titles:
            continue
        store.albums.append(Album(
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
        store._save()


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

