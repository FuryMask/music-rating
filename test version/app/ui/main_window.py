"""Главное окно приложения.

Компоновка:
  ┌──────────────────────────────────┐
  │  TopBar (логотип + поиск)        │
  ├─────────┬────────────────────────┤
  │ Sidebar │  Pages (QStackedWidget)│
  │  («+»)  │  • HomePage            │
  │         │  • AlbumDetailPage     │
  │         │  • ArtistDetailPage    │
  │         │  • ArtistEditorPage    │
  │         │  • CollectionPage      │
  └─────────┴────────────────────────┘
  ↑ CreateChoiceOverlay — выбор «вручную / автоматически» (по «+»)
  ↑ CreateAlbumOverlay открывается поверх ВСЕГО окна
  ↑ SearchResultsPanel — результаты поиска под строкой поиска

Кнопка «+» в сайдбаре открывает окно выбора способа создания
(см. dialogs/create_choice_dialog.py): вручную — обычный мастер,
автоматически — ссылка на альбом Deezer, после загрузки мастер
открывается с заполненными данными и предупреждением (см.
dialogs/autofill_warning_dialog.py).

Навигация по кликам (со СТЕКОМ истории):
  • карточка альбома (главная/списки/дискография) → страница альбома;
  • карточка исполнителя / его имя на странице альбома / строка в
    результатах поиска → страница исполнителя: фото, имя, основной
    жанр (не указанный при создании определяется автоматически по
    альбомам) и дискография — только альбомы, где он автор/соавтор
    (см. pages/artist_detail.py);
  • плитка «Смотреть все» → полный список: «Недавно оценённые»
    (от последней оценки к первой), «Оценённые альбомы» (все альбомы
    по дате создания в приложении) или «Исполнители» (новее — раньше)
    (см. pages/collection_page.py);
  • «назад» (кнопка или Esc на странице списка/альбома/исполнителя,
    когда не открыт ни один оверлей) возвращает НА ШАГ НАЗАД:
    каждый открытый экран запоминает, откуда он открыт, и выход
    возвращает туда — например «Смотреть все» → альбом → выход
    снова открывает «Смотреть все», а не главную.

Оценка альбома появляется в МАСТЕРЕ ОЦЕНИВАНИЯ (см.
pages/rate_album.py): на странице неоценённого альбома справа, на
уровне обложки — текст «Этот альбом ещё не оценили» и синяя кнопка
«Оценить?»; под шапкой показывается треклист, а у оценённого альбома —
сетка оценок участников (см. pages/album_detail.py); после создания
альбома главное окно предлагает «Вы успешно создали альбом, хотите
оценить его сейчас?» (см. dialogs/rate_after_create_dialog.py).
«Оценить?» СНАЧАЛА открывает выбор режима (см.
dialogs/rate_mode_dialog.py): «Локально» — обычный мастер (выбор
участников → треклист со столбцом на каждого, 0–10 с шагом 0.1,
секретная 11 один раз на участника → итоги со статистикой),
«По сети» — сетевой мастер с лобби (см. pages/rate_network.py).
Средняя пишется в album.rating (карточки и страница альбома).

СЕТЕВОЕ ОЦЕНИВАНИЕ (заготовка под будущее P2P, см.
pages/rate_network.py): «По сети» создаёт сессию-лобби (хост ждёт
участников, затем «Оценить» → этап оценок со столбцом на каждого).
Выход в любой момент сохраняет сессию — повторное подключение
возвращает на тот же этап. Кнопка-планета в сайдбаре открывает
страницу «Комнаты» (см. pages/rooms_page.py) — сейчас это
заглушка «В разработке»: сетевые функции отложены, интерфейса
комнат больше нет (реестр ROOMS продолжает жить для сессий).

Кнопка «Редактировать» на странице альбома открывает мастер создания
с заполненными данными (см. create_album.open_for_edit): сохранение
обновляет существующий альбом (store.update_album), а не создаёт
новый. Слева от неё — НЕАКТИВНАЯ «Выгрузить» (публикация в облако,
сетевые функции отложены; подсказка «В разработке»).

РЕЖИМ ПРОСМОТРА (Task 30): кнопка-БД в сайдбаре (рядом с профилем,
комнатами и «+») переключает «Локально»/«Облачно». «Локально» —
обычная библиотека пользователя; «Облачно» — всё, загруженное
пользователями (сетевые функции отложены: рабочая зона показывает
«В разработке», см. pages/cloud_page.py). Текущий режим дублируется
надписью справа сверху, в верхней полосе (TopBar.mode_label).
При переключении в «Облачно» рабочая страница запоминается и
возвращается при переключении назад; поиск в облачном режиме
выключен (ищется только локальная библиотека). Любое действие с
локальными данными (создание/открытие альбома, списки) возвращает
режим «Локально» (_ensure_local_mode).

Кнопка «Удалить» на странице альбома открывает подтверждение
(см. dialogs/delete_confirm_dialog.py): по подтверждению удаляется
ТОЛЬКО альбом — исполнители независимы от альбомов и остаются
в базе. Затем происходит возврат на главную.

Поиск: по мере ввода под строкой появляется панель результатов
(альбомы, ТРЕКИ и исполнители, см. app/ui/widgets/search_results.py).
Название альбома поднимает и его исполнителей (без фитов). Строка
трека — обложка альбома, название, справа «трек с «Альбом»»;
клик открывает альбом. Клик по
любой строке открывает страницу альбома/исполнителя. Панель
закрывается: очисткой поля, Esc, кликом мимо панели и поля,
открытием мастера.

Экспорт/импорт БД (Task 30): вкладка «Настройки» окна профиля
(см. dialogs/profile_dialog.py). Экспорт — ZIP (база + обложки,
STORE.export_library), импорт — замена локального наполнения
(STORE.import_library); сигнал db_imported обновляет главную и
возвращает режим «Локально».

УВЕДОМЛЕНИЯ (Task 31): все одноразовые оповещения («Введите новый
пароль», «База успешно импортирована», ошибки загрузки ссылок
и т.п.) показываются ВСПЛЫВАЮЩИМИ ТОСТАМИ сверху по центру главного
окна (см. widgets/toast.py): зелёная галочка / красный крестик,
уходящая полоска прогресса, стопка максимум из 3. Менеджер —
self.toasts; любой виджет приложения показывает тост через
app.ui.widgets.toast.notify(widget, text, kind).

АНИМАЦИЯ ОТКРЫТИЯ (Task 31): при первом показе окна содержимое
(верхняя полоса, сайдбар, секции главной) ПАДАЕТ СВЕРХУ с нулевой
прозрачности за 0.250 с (см. widgets/drop_animation.py). Те же
анимации — на страницах «Смотреть все» (collection_page.show_mode)
и «Дискография» (artist_detail.set_artist).

ЧИСТКА КАРТИНОК (Task 31): при старте STORE.prune_covers() удаляет
из data/covers файлы, на которые больше не ссылается база (обложки
удалённых альбомов и т.п.) — внутри системы не остаются осиротевшие
картинки; чистка также выполняется при удалении/редактировании
альбома, редактировании исполнителя и импорте базы.

После старта фоновый ArtBackfiller (см. services/backfill.py)
дозагружает с Deezer ФОТО исполнителей без картинок — вместо
заглушек-букв. Обложки альбомов НЕ дозагружаются: у альбома есть
только та обложка, которую выбрал пользователь (или пришедшая
с Deezer при создании по ссылке).
"""

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import Album, Artist
from app.services.backfill import ArtBackfiller
from app.services.deezer import DeezerAlbum
from app.services.spotify import SpotifyAlbum
from app.services.ytmusic import YTMusicAlbum
from app.store import STORE
from app.ui.dialogs.create_choice_dialog import CreateChoiceOverlay
from app.ui.dialogs.delete_confirm_dialog import DeleteConfirmOverlay
from app.ui.dialogs.profile_dialog import ProfileOverlay
from app.ui.dialogs.rate_after_create_dialog import RateAfterCreateOverlay
from app.ui.dialogs.rate_mode_dialog import RateModeOverlay
from app.ui.dialogs.test_gate_dialog import GateProfileOverlay, TestGateOverlay
from app.ui.pages import HomePage
from app.ui.pages.album_detail import AlbumDetailPage
from app.ui.pages.artist_detail import ArtistDetailPage
from app.ui.pages.artist_editor import ArtistEditorPage
from app.ui.pages.cloud_page import CloudStubPage
from app.ui.pages.collection_page import CollectionPage
from app.ui.pages.create_album import CreateAlbumOverlay
from app.ui.pages.rate_album import RateAlbumOverlay
from app.ui.pages.rate_network import (
    NetworkRateOverlay,
    NetworkSession,
    find_album,
    register_room,
    unregister_room,
)
from app.ui.pages.rooms_page import RoomsPage
from app.ui.sidebar import Sidebar
from app.ui.top_bar import MODE_CLOUD, MODE_LOCAL, TopBar
from app.ui.widgets.drop_animation import pre_hide, run_drop_in
from app.ui.widgets.search_results import SearchResultsPanel
from app.ui.widgets.toast import ToastManager

SEARCH_PANEL_GAP = 6  # просвет между полем поиска и панелью результатов
BACKFILL_DELAY_MS = 800  # запуск дозагрузки картинок после показа окна


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Music Rating")
        self.setMinimumSize(900, 600)  # чтобы узкое окно не ломало компоновку

        self._overlay: CreateAlbumOverlay | None = None
        self._choice_overlay: CreateChoiceOverlay | None = None
        self._delete_overlay: DeleteConfirmOverlay | None = None
        self._rate_overlay: RateAlbumOverlay | None = None
        self._rate_mode_overlay: RateModeOverlay | None = None
        self._network_overlay: NetworkRateOverlay | None = None
        self._after_create_overlay: RateAfterCreateOverlay | None = None
        self._profile_overlay: ProfileOverlay | None = None
        # ТЕСТОВАЯ СБОРКА: стартовая дверь «выберите, кем вы являетесь»
        # (показывается при запуске без залогиненного пользователя)
        self._test_gate: TestGateOverlay | None = None
        self._after_create_album: Album | None = None
        self._pending_delete: Album | None = None
        self._pending_rate_album: Album | None = None
        # Сетевые сессии по ключу (album_id, хост ли): выход из
        # сетевого мастера сессию НЕ снимает — переподключение
        self._network_sessions: dict[tuple[str, bool], NetworkSession] = {}
        self._backfiller: ArtBackfiller | None = None
        # Стек навигации: каждый открытый экран запоминает, откуда он
        # открыт («шаг назад» вместо безусловного возврата на главную)
        self._nav_stack: list[tuple[str, object]] = []
        # Режим просмотра: «local» (своё) / «cloud» (облако — заглушка).
        # Страница, с которой ушли в «Облачно», запоминается —
        # возвращаемся ровно на неё
        self._view_mode = "local"
        self._page_before_cloud: QWidget | None = None
        # Анимация «падения сверху» проигрывается один раз — при
        # первом показе окна (Task 31); _drop_scheduled — планирование
        # уже запущено (в тестовой сборке между показом окна и
        # анимацией может стоять стартовая дверь)
        self._drop_played = False
        self._drop_scheduled = False

        # Тосты-уведомления (Task 31): менеджер главного окна; любые
        # диалоги/страницы показывают их через toast.notify(self, …)
        self.toasts = ToastManager(self)

        # Чистка осиротевших картинок (обложки удалённых альбомов и
        # прочий мусор в data/covers) — раз при старте (Task 31)
        STORE.prune_covers()

        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Верхняя полоса с поиском
        self.top_bar = TopBar(central)
        root.addWidget(self.top_bar)

        # 2. Тело: левая панель + рабочая зона
        body = QWidget(central)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = Sidebar(body)
        self.sidebar.add_album_clicked.connect(self.open_create_choice)
        self.sidebar.profile_clicked.connect(self.open_profile)
        self.sidebar.network_clicked.connect(self.open_rooms)
        self.sidebar.mode_clicked.connect(self._toggle_view_mode)

        # Рабочая зона — стек страниц: главная, альбом, исполнитель,
        # полные списки «Смотреть все», комната, заглушка «Облачно»
        self.pages = QStackedWidget(body)
        self.pages.setObjectName("contentArea")
        self.home_page = HomePage(self.pages)
        self.album_page = AlbumDetailPage(self.pages)
        self.artist_page = ArtistDetailPage(self.pages)
        self.artist_editor = ArtistEditorPage(self.pages)
        self.list_page = CollectionPage(self.pages)
        self.rooms_page = RoomsPage(self.pages)
        self.cloud_page = CloudStubPage(self.pages)
        self.pages.addWidget(self.home_page)
        self.pages.addWidget(self.album_page)
        self.pages.addWidget(self.artist_page)
        self.pages.addWidget(self.artist_editor)
        self.pages.addWidget(self.list_page)
        self.pages.addWidget(self.rooms_page)
        self.pages.addWidget(self.cloud_page)

        self.home_page.album_opened.connect(self.open_album)
        self.home_page.artist_opened.connect(self.open_artist)
        self.home_page.view_all.connect(self.open_list)
        self.album_page.back_clicked.connect(self.close_album)
        self.album_page.delete_requested.connect(self._confirm_delete_album)
        self.album_page.edit_requested.connect(self._open_edit_album)
        self.album_page.rate_requested.connect(self.open_rate_album)
        self.album_page.artist_opened.connect(self.open_artist_by_name)
        self.artist_page.back_clicked.connect(self.close_artist)
        self.artist_page.album_opened.connect(self.open_album)
        self.artist_page.edit_requested.connect(self.open_artist_editor)
        self.artist_editor.back_clicked.connect(self._go_back)
        self.artist_editor.artist_saved.connect(self._on_artist_saved)
        self.list_page.back_clicked.connect(self.close_list)
        self.list_page.album_opened.connect(self.open_album)
        self.list_page.artist_opened.connect(self.open_artist)
        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.pages, 1)

        root.addWidget(body, 1)

        # 3. Панель результатов поиска (ребёнок окна — видна поверх
        #    рабочей зоны, но под полнооконным мастером)
        self.search_panel = SearchResultsPanel(self)
        self.search_panel.hide()
        self.search_panel.album_activated.connect(self._open_from_search)
        self.search_panel.artist_activated.connect(self._open_artist_from_search)

        input = self.top_bar.search_input
        input.textChanged.connect(self._on_search_text)
        input.returnPressed.connect(self.search_panel.hide)

        # Клики мимо панели/поля закрывают подсказку (фильтр на всё
        # приложение — виджеты страниц фокус у поля не забирают)
        QApplication.instance().installEventFilter(self)

        # Через мгновение после показа окна — дозагрузка картинок
        QTimer.singleShot(BACKFILL_DELAY_MS, self._start_art_backfill)

        # АНИМАЦИЯ ОТКРЫТИЯ: содержимое прячется ЕЩЁ ДО показа окна —
        # первый кадр окна рисуется уже прозрачным (если применять
        # эффект только после showEvent, первый кадр на Windows успевает
        # нарисоваться целиком, и анимация выглядит неприменённой).
        # «Падение» играется по первому показу (см. showEvent).
        self._drop_targets = [
            self.top_bar,
            self.sidebar,
            self.home_page.section_recent,
            self.home_page.section_rated,
            self.home_page.section_artists,
        ]
        pre_hide(self._drop_targets)

    # --- Поиск: панель результатов ---
    def _on_search_text(self, text: str) -> None:
        if not text.strip():
            self.search_panel.hide()
            return
        self.search_panel.update_for(text)
        self._reposition_search_panel()
        self.search_panel.show()
        self.search_panel.raise_()

    def _reposition_search_panel(self) -> None:
        """Панель строго под полем поиска, той же ширины."""
        field = self.top_bar.search_input
        top_left = field.mapTo(self, QPoint(0, 0))
        self.search_panel.setGeometry(
            top_left.x(),
            top_left.y() + field.height() + SEARCH_PANEL_GAP,
            field.width(),
            self.search_panel.height(),
        )

    def _open_from_search(self, album: Album) -> None:
        """Клик по строке альбома в результатах поиска."""
        self.search_panel.hide()
        self.top_bar.search_input.clear()
        self.open_album(album)

    def _open_artist_from_search(self, artist: Artist) -> None:
        """Клик по строке исполнителя в результатах поиска."""
        self.search_panel.hide()
        self.top_bar.search_input.clear()
        self.open_artist(artist)

    def eventFilter(self, obj, event) -> bool:
        # Esc в поле поиска: очистить ввод (панель закроется сама)
        if (
            event.type() == QEvent.Type.KeyPress
            and obj is self.top_bar.search_input
            and event.key() == Qt.Key.Key_Escape
        ):
            self.top_bar.search_input.clear()
            return True
        # Esc на страницах списка/альбома/исполнителя: НАЗАД (на шаг).
        # Работает только когда не открыт ни один оверлей — иначе
        # Esc управляет им (мастер/выбор/подтверждение удаления)
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and not self._any_overlay_visible()
        ):
            current = self.pages.currentWidget()
            if current in (self.list_page, self.album_page,
                           self.artist_page, self.artist_editor,
                           self.rooms_page):
                self.search_panel.hide()
                self._go_back()
                return True
        # Клик мимо панели и поля поиска — закрыть панель
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and self.search_panel.isVisible()
            and isinstance(obj, QWidget)
        ):
            if not self._is_over_search_widgets(obj):
                self.search_panel.hide()
        return super().eventFilter(obj, event)

    def _any_overlay_visible(self) -> bool:
        """Открыт ли хоть один полнооконный оверлей?"""
        return any(
            overlay is not None and overlay.isVisible()
            for overlay in (
                self._overlay,             # мастер создания/редактирования
                self._choice_overlay,      # выбор способа создания
                self._delete_overlay,      # подтверждение удаления
                self._rate_overlay,        # мастер оценивания (локально)
                self._rate_mode_overlay,   # «локально или по сети?»
                self._network_overlay,     # мастер оценивания по сети
                self._after_create_overlay,  # «оценить сейчас?»
                self._profile_overlay,     # профиль (вход/регистрация)
                self._test_gate,           # стартовая дверь тестовой сборки
            )
        )

    def _is_over_search_widgets(self, widget: QWidget) -> bool:
        """Клик пришёлся на панель результатов или поле поиска?"""
        center = widget.mapToGlobal(widget.rect().center())
        for target in (self.search_panel, self.top_bar.search_input):
            if target.rect().contains(target.mapFromGlobal(center)):
                return True
        return False

    # --- Режим просмотра: Локально / Облачно (Task 30) -------------------
    def _toggle_view_mode(self) -> None:
        """Клик по кнопке-БД: переключить Локально ↔ Облачно."""
        self.set_view_mode(
            "local" if self._view_mode == "cloud" else "cloud"
        )

    def set_view_mode(self, mode: str) -> None:
        """Переключить режим просмотра рабочей зоны.

        «Облачно»: содержимое рабочей зоны заменяется заглушкой
        «В разработке» (cloud_page); страница, с которой ушли,
        запоминается и возвращается при обратном переключении;
        поиск отключается (ищется только локальная библиотека).
        Надпись в верхней полосе и состояние кнопки-БД обновляются.
        """
        if mode == self._view_mode:
            return
        cloud = mode == "cloud"
        self._view_mode = mode
        self.search_panel.hide()
        if cloud:
            current = self.pages.currentWidget()
            self._page_before_cloud = (
                current if current is not self.cloud_page else None
            )
            self.pages.setCurrentWidget(self.cloud_page)
            self.top_bar.search_input.setEnabled(False)
            self.top_bar.search_input.setToolTip(
                "Поиск работает в режиме «Локально»"
            )
        else:
            self.top_bar.search_input.setEnabled(True)
            self.top_bar.search_input.setToolTip("")
            target = self._page_before_cloud or self.home_page
            self._page_before_cloud = None
            if target is self.home_page:
                self.home_page.refresh()  # база могла измениться
            self.pages.setCurrentWidget(target)
        self.top_bar.set_mode_text(MODE_CLOUD if cloud else MODE_LOCAL)
        self.sidebar.set_view_mode(cloud)

    def _ensure_local_mode(self) -> None:
        """Вернуть режим «Локально», если сейчас «Облачно».

        Все входы в локальные данные (открытие альбома/исполнителя,
        списки, создание) вызывают это: создав альбом в облачном
        режиме, пользователь должен увидеть его — а не заглушку.
        """
        if self._view_mode == "cloud":
            self.set_view_mode("local")

    # --- Навигация со стеком: каждый экран помнит, откуда открыт ---
    def _push_current(self) -> None:
        """Запомнить текущий экран как точку возврата (шаг назад)."""
        current = self.pages.currentWidget()
        if current is self.album_page and self.album_page.album is not None:
            self._nav_stack.append(("album", self.album_page.album))
        elif current is self.artist_page and \
                self.artist_page.artist is not None:
            self._nav_stack.append(("artist", self.artist_page.artist))
        elif current is self.list_page:
            self._nav_stack.append(("list", self.list_page.mode))
        elif current is self.cloud_page:
            # Из облака открыли «Комнаты» — вернуться тоже в облако
            self._nav_stack.append(("cloud", None))
        else:
            self._nav_stack.append(("home", None))

    def _go_back(self) -> None:
        """Вернуться на шаг назад (или на главную, если истории нет).

        Экраны при возврате перечитывают данные: база могла измениться
        (например, альбом удалён). Удалённый альбом в истории
        пропускается — возврат происходит дальше по стеку.
        """
        while self._nav_stack:
            kind, obj = self._nav_stack.pop()
            if kind == "album" and any(a is obj for a in STORE.albums):
                self.album_page.set_album(obj)
                self.pages.setCurrentWidget(self.album_page)
                return
            if kind == "artist" and any(a is obj for a in STORE.artists):
                self.artist_page.set_artist(obj)
                self.pages.setCurrentWidget(self.artist_page)
                return
            if kind == "list":
                self.list_page.show_mode(obj)
                self.pages.setCurrentWidget(self.list_page)
                return
            if kind == "cloud":
                # Возврат в заглушку облачного режима (если его снова
                # не включили — на главную, как из «home»)
                if self._view_mode == "cloud":
                    self.pages.setCurrentWidget(self.cloud_page)
                    return
                break
            if kind == "home":
                break
        self._show_home()

    def _show_home(self) -> None:
        """Главная: база могла измениться — обновляем."""
        self.home_page.refresh()
        self.pages.setCurrentWidget(self.home_page)

    def open_album(self, album: Album) -> None:
        self._ensure_local_mode()
        self._push_current()
        self.search_panel.hide()
        self.album_page.set_album(album)
        self.pages.setCurrentWidget(self.album_page)

    def close_album(self) -> None:
        """Выход со страницы альбома — на шаг назад."""
        self._go_back()

    def open_artist(self, artist: Artist) -> None:
        """Страница исполнителя: фото, имя, жанр, дискография."""
        self._ensure_local_mode()
        self._push_current()
        self.search_panel.hide()
        self.artist_page.set_artist(artist)
        self.pages.setCurrentWidget(self.artist_page)

    def open_artist_by_name(self, name: str) -> None:
        """Клик по имени исполнителя на странице альбома."""
        artist = STORE.find_artist(name)
        if artist is not None:
            self.open_artist(artist)

    def close_artist(self) -> None:
        """Выход со страницы исполнителя — на шаг назад."""
        self._go_back()

    # --- Редактирование исполнителя (страница в рабочей зоне) ---------
    def open_artist_editor(self, artist: Artist | None) -> None:
        """«Редактировать» на странице исполнителя → его редактор.

        В отличие от альбома (полнооконный мастер) редактор занимает
        только основное поле: точка возврата — та же страница
        исполнителя (push в стек навигации).
        """
        if artist is None:
            return
        self.search_panel.hide()
        self._push_current()
        self.artist_editor.set_artist(artist)
        self.pages.setCurrentWidget(self.artist_editor)

    def _on_artist_saved(self, artist: Artist) -> None:
        """Исполнитель сохранён: обновить экраны и вернуться к нему.

        Объект Artist мутирует на месте (в том числе при
        переименовании), поэтому возврат по стеку — «(artist, obj)»
        — перечитает уже обновлённые данные.
        """
        self.home_page.refresh()
        self._go_back()

    def open_list(self, mode: str) -> None:
        """Полный список «Смотреть все»: recent / albums / artists."""
        self._ensure_local_mode()
        self._push_current()
        self.search_panel.hide()
        self.list_page.show_mode(mode)
        self.pages.setCurrentWidget(self.list_page)

    def close_list(self) -> None:
        """Выход из «Смотреть все» — на шаг назад."""
        self._go_back()

    # --- Мастер создания альбома (полнооконный оверлей) ---
    def open_create_choice(self) -> None:
        """«+» → окно выбора: создать вручную или по ссылке Deezer.

        Создание альбома — локальное действие: облачный режим заранее
        переключается на «Локально», чтобы после мастера пользователь
        не оказался перед заглушкой.
        """
        self._ensure_local_mode()
        self.search_panel.hide()
        if self._choice_overlay is None:
            self._choice_overlay = CreateChoiceOverlay(self)
            self._choice_overlay.manual_requested.connect(
                self.open_create_album
            )
            self._choice_overlay.album_loaded.connect(self._open_auto_filled)
        self._choice_overlay.open()

    def open_create_album(self) -> None:
        self.search_panel.hide()
        if self._overlay is None:
            self._overlay = CreateAlbumOverlay(self)
            self._overlay.album_created.connect(self._on_album_created)
        self._overlay.reset()
        self._overlay.setGeometry(self.rect())
        self._overlay.show()
        self._overlay.raise_()

    def _open_auto_filled(
        self, data: DeezerAlbum | SpotifyAlbum | YTMusicAlbum
    ) -> None:
        """Ссылка загрузилась: мастер с заполненными данными + предупреждение."""
        self.open_create_album()
        self._overlay.apply_auto_fill(data)
        self._overlay.open_autofill_warning()

    # --- Удаление альбома (кнопка «Удалить» на его странице) ---
    def _confirm_delete_album(self, album: Album | None) -> None:
        """«Удалить» → окно подтверждения с названием альбома."""
        if album is None:
            return
        self.search_panel.hide()
        if self._delete_overlay is None:
            self._delete_overlay = DeleteConfirmOverlay(self)
            self._delete_overlay.confirmed.connect(self._delete_current_album)
        self._pending_delete = album
        self._delete_overlay.open(album.title)

    def _delete_current_album(self) -> None:
        """Подтверждение получено: удалить альбом и вернуться на главную.

        Исполнители НЕ трогаются: они независимы от альбомов
        (см. store.delete_album). История навигации сбрасывается:
        удалённого альбома больше нет, возврат «по шагам» к нему
        не имеет смысла.
        """
        album = self._pending_delete
        self._pending_delete = None
        if album is None:
            return
        STORE.delete_album(album)
        # Сетевые сессии и комната удалённого альбома больше не нужны
        for as_host in (True, False):
            self._network_sessions.pop((album.id, as_host), None)
        unregister_room(album.id)
        self._nav_stack.clear()
        self._show_home()  # обновить главную и показать её

    # --- Редактирование альбома (кнопка «Редактировать») ---
    def _open_edit_album(self, album: Album | None) -> None:
        """Мастер создания в режиме редактирования существующего альбома."""
        if album is None:
            return
        self.search_panel.hide()
        if self._overlay is None:
            self._overlay = CreateAlbumOverlay(self)
            self._overlay.album_created.connect(self._on_album_created)
            self._overlay.album_updated.connect(self._on_album_updated)
        self._overlay.open_for_edit(album)
        self._overlay.setGeometry(self.rect())
        self._overlay.show()
        self._overlay.raise_()

    def _on_album_updated(self, album: Album) -> None:
        """Альбом отредактирован: обновить главную и его страницу."""
        self.home_page.refresh()
        if (
            self.pages.currentWidget() is self.album_page
            and self.album_page.album is album
        ):
            self.album_page.set_album(album)

    # --- Оценивание: выбор режима («Локально или по сети?») ---
    def open_rate_album(self, album: Album | None) -> None:
        """«Оценить?» → окно выбора режима (локально / по сети).

        Обе точки входа (кнопка на странице альбома и предложение
        после создания) проходят через это окно — режим выбирается в
        dialogs/rate_mode_dialog.py.
        """
        if album is None:
            return
        self.search_panel.hide()
        self._pending_rate_album = album
        if self._rate_mode_overlay is None:
            self._rate_mode_overlay = RateModeOverlay(self)
            self._rate_mode_overlay.local_requested.connect(
                self._rate_mode_local
            )
            self._rate_mode_overlay.network_requested.connect(
                self._rate_mode_network
            )
        self._rate_mode_overlay.open()

    def _rate_mode_local(self) -> None:
        """«Локально» — обычный мастер оценивания."""
        album = self._pending_rate_album
        self._pending_rate_album = None
        if album is None:
            return
        if self._rate_overlay is None:
            self._rate_overlay = RateAlbumOverlay(self)
            self._rate_overlay.album_rated.connect(self._on_album_rated)
        self._rate_overlay.open_for(album)

    def _rate_mode_network(self) -> None:
        """«По сети» — сессия-лобби этого пользователя (роль хоста)."""
        album = self._pending_rate_album
        self._pending_rate_album = None
        if album is None:
            return
        key = (album.id, True)
        session = self._network_sessions.get(key)
        if session is None:
            host_name = self._account_name("Хост")
            session = NetworkSession(
                album_id=album.id,
                host_name=host_name,
                is_host=True,
                joined=[host_name],
            )
            self._network_sessions[key] = session
            register_room(album.id, host_name)
        self._show_network_session(session, album)

    # --- Сетевое оценивание (заготовка P2P) -------------------------------
    def _account_name(self, fallback: str) -> str:
        """Имя залогиненного аккаунта (или запасное)."""
        user = STORE.current_user
        return user.username if user is not None else fallback

    def _show_network_session(self, session: NetworkSession,
                              album: Album) -> None:
        """Открыть/показать сетевой мастер на состоянии сессии."""
        self.search_panel.hide()
        if self._network_overlay is None:
            self._network_overlay = NetworkRateOverlay(self)
            self._network_overlay.session_finished.connect(
                self._on_network_finished
            )
        self._network_overlay.open_for_session(session, album)

    def _on_network_finished(self, album_id: str, was_host: bool) -> None:
        """«Готово» сетевого мастера: сессия снята, экраны обновлены."""
        self._network_sessions.pop((album_id, was_host), None)
        if was_host:
            unregister_room(album_id)
        album = find_album(album_id)
        if album is not None:
            self._on_album_rated(album)

    # --- Страница «Комнаты» (кнопка-планета в сайдбаре) -------------------
    def open_rooms(self) -> None:
        """Главная зона → заглушка «В разработке» (Task 31).

        Сетевые функции отложены: интерфейса комнат больше нет,
        страница — только надпись (см. pages/rooms_page.py). Стек
        навигации работает как раньше — Esc возвращает на шаг назад.
        """
        self._push_current()
        self.search_panel.hide()
        self.pages.setCurrentWidget(self.rooms_page)

    def close_rooms(self) -> None:
        """Выход со страницы комнат — на шаг назад."""
        self._go_back()

    def _on_album_rated(self, album: Album) -> None:
        """Оценки сохранены: обновить главную и страницу альбома."""
        self.home_page.refresh()
        if (
            self.pages.currentWidget() is self.album_page
            and self.album_page.album is album
        ):
            self.album_page.set_album(album)

    def _offer_rate_after_create(self, album: Album) -> None:
        """После создания: «Вы успешно создали альбом, хотите оценить
        его сейчас?» — «Да» открывает мастер оценивания."""
        if self._after_create_overlay is None:
            self._after_create_overlay = RateAfterCreateOverlay(self)
            self._after_create_overlay.accepted.connect(self._rate_after_create)
        self._after_create_album = album
        self._after_create_overlay.open()

    def _rate_after_create(self) -> None:
        album = self._after_create_album
        self._after_create_album = None
        self.open_rate_album(album)

    # --- Профиль (вход / регистрация / аккаунт) ---
    def open_profile(self) -> None:
        """Кнопка профиля в сайдбаре — окно входа или карточки аккаунта.

        ТЕСТОВАЯ СБОРКА: используется подкласс GateProfileOverlay,
        сообщающий о закрытии — если пользователь закрыл профиль,
        НЕ залогинившись, стартовая дверь возвращается (уйти без
        опознавания нельзя).
        """
        self.search_panel.hide()
        if self._profile_overlay is None:
            self._profile_overlay = GateProfileOverlay(self)
            self._profile_overlay.account_deleted.connect(
                self._on_account_deleted
            )
            self._profile_overlay.db_imported.connect(self._on_db_imported)
            self._profile_overlay.closed.connect(self._on_profile_closed)
        self._profile_overlay.open()

    def _on_db_imported(self) -> None:
        """База импортирована (Task 30): обновить экраны.

        Локальное наполнение сменилось целиком: старые объекты Album
        недействительны (стек навигации очищается — возврат «по шагам»
        к ним не имеет смысла), показывается главная в режиме
        «Локально». Страницы альбома/исполнителя перечитываются при
        каждом открытии, поэтому отдельно их обновлять не нужно.
        """
        self._ensure_local_mode()
        self._nav_stack.clear()
        self._show_home()

    def _on_account_deleted(self) -> None:
        """Аккаунт удалён: его оценки убраны — обновить экраны."""
        self.home_page.refresh()
        if self.album_page.album is not None:
            self.album_page.set_album(self.album_page.album)

    # --- Стартовая дверь тестовой сборки ------------------------------------
    def _open_test_gate(self) -> None:
        """Показать дверь «выберите, кем вы являетесь» (без сессии)."""
        self.search_panel.hide()
        if self._test_gate is None:
            self._test_gate = TestGateOverlay(self)
            self._test_gate.identity_confirmed.connect(
                self._on_gate_confirmed
            )
            self._test_gate.login_requested.connect(
                self._on_gate_login_requested
            )
        self._test_gate.open_gate()

    def _on_gate_confirmed(self) -> None:
        """Пользователь опознан (заглушка создана и залогинена):
        показать приложение — самое время для анимации открытия."""
        self._maybe_play_open_drop()

    def _on_gate_login_requested(self) -> None:
        """«Меня здесь нет» → окно входа/регистрации (профиль).

        Профиль — GateProfileOverlay: при закрытии решаем, что дальше
        (см. _on_profile_closed) — дверь или приложение.
        """
        if self._profile_overlay is None:
            self._profile_overlay = GateProfileOverlay(self)
            self._profile_overlay.account_deleted.connect(
                self._on_account_deleted
            )
            self._profile_overlay.db_imported.connect(self._on_db_imported)
            self._profile_overlay.closed.connect(self._on_profile_closed)
        self._profile_overlay.open()

    def _on_profile_closed(self) -> None:
        """Профиль закрыт: без залогиненного пользователя дверь вернётся,
        с ним — приложение показывается (первый раз — с анимацией)."""
        if STORE.current_user is None:
            self._open_test_gate()
        else:
            self._maybe_play_open_drop()

    # --- Фоновая дозагрузка фото исполнителей с Deezer ---
    def _start_art_backfill(self) -> None:
        if self._backfiller is None:
            self._backfiller = ArtBackfiller(self)
            # Каждая скачанная картинка сразу появляется на главной
            self._backfiller.changed.connect(self.home_page.refresh)
        self._backfiller.start()

    def _on_album_created(self, _album: Album) -> None:
        """Новый альбом и его исполнители появляются на главной.

        Сразу (не дожидаясь следующего запуска) запускается фоновая
        дозагрузка ФОТО новых исполнителей, затем появляется окно
        «Вы успешно создали альбом, хотите оценить его сейчас?».
        Создание могло начаться и из облачного режима — показывать
        главную надо в «Локально».
        """
        self._ensure_local_mode()
        self.home_page.refresh()
        self._start_art_backfill()
        self._offer_rate_after_create(_album)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())
        if self._choice_overlay is not None and self._choice_overlay.isVisible():
            self._choice_overlay.setGeometry(self.rect())
        if self._delete_overlay is not None and self._delete_overlay.isVisible():
            self._delete_overlay.setGeometry(self.rect())
        if self._rate_overlay is not None and self._rate_overlay.isVisible():
            self._rate_overlay.setGeometry(self.rect())
        if self._network_overlay is not None \
                and self._network_overlay.isVisible():
            self._network_overlay.setGeometry(self.rect())
        if self._rate_mode_overlay is not None \
                and self._rate_mode_overlay.isVisible():
            self._rate_mode_overlay.setGeometry(self.rect())
        if self._after_create_overlay is not None \
                and self._after_create_overlay.isVisible():
            self._after_create_overlay.setGeometry(self.rect())
        if self._profile_overlay is not None \
                and self._profile_overlay.isVisible():
            self._profile_overlay.setGeometry(self.rect())
        if self._test_gate is not None and self._test_gate.isVisible():
            self._test_gate.setGeometry(self.rect())
        if self.search_panel.isVisible():
            self._reposition_search_panel()

    # --- Анимация открытия (Task 31) ---------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._drop_scheduled:
            self._drop_scheduled = True
            # Дать компоновке пересчитаться после показа — затем решаем:
            # без залогиненного пользователя (тестовая сборка) сначала
            # показывается стартовая дверь, и только после опознания
            # содержимое «падает» сверху с проявлением (0.250 с)
            QTimer.singleShot(0, self._after_window_shown)

    def _after_window_shown(self) -> None:
        """Первый показ окна: дверь тестовой сборки или анимация."""
        if STORE.current_user is None:
            self._open_test_gate()
        else:
            self._maybe_play_open_drop()

    def _maybe_play_open_drop(self) -> None:
        """Анимация падения — один раз за жизнь окна."""
        if self._drop_played:
            return
        self._drop_played = True
        self._play_open_drop()

    def _play_open_drop(self) -> None:
        """Падение содержимого главного окна при его первом показе."""
        # Дожать отложенную компоновку (в т.ч. после асинхронного
        # maximize Windows): финальные позиции должны быть захвачены
        # настоящими, иначе падение уйдёт «не туда»
        QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        root_lay = self.layout()
        if root_lay is not None:
            root_lay.activate()
        run_drop_in(
            list(self._drop_targets),
            block_container=self.centralWidget(),
        )
