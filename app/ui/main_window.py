"""Главное окно, навигация по медиатеке и переключение страниц."""

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from app.models import Album, Artist
from app.services.backfill import ArtBackfiller
from app.services.deezer import DeezerAlbum
from app.services.genius import GeniusAlbum
from app.services.spotify import SpotifyAlbum
from app.services.updates import Updates
from app.services.yandex_music import YandexMusicAlbum
from app.services.ytmusic import YTMusicAlbum
from app.store import STORE
from app.ui.dialogs.create_choice_dialog import CreateChoiceOverlay
from app.ui.dialogs.delete_confirm_dialog import DeleteConfirmOverlay
from app.ui.dialogs.profile_dialog import ProfileOverlay
from app.ui.dialogs.rate_after_create_dialog import RateAfterCreateOverlay
from app.ui.pages import HomePage
from app.ui.pages.album_detail import AlbumDetailPage
from app.ui.pages.artist_detail import ArtistDetailPage
from app.ui.pages.artist_editor import ArtistEditorPage
from app.ui.pages.cloud_page import CloudStubPage
from app.ui.pages.collection_page import CollectionPage
from app.ui.pages.create_album import CreateAlbumOverlay
from app.ui.pages.rate_album import RateAlbumOverlay
from app.ui.sidebar import Sidebar
from app.ui.top_bar import MODE_CLOUD, MODE_LOCAL, TopBar
from app.ui.widgets.drop_animation import pre_hide, run_drop_in
from app.ui.widgets.page_stack import AnimatedStackedWidget
from app.ui.widgets.search_results import SearchResultsPanel
from app.ui.widgets.toast import KIND_ERROR, ToastManager, notify

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
        self._after_create_overlay: RateAfterCreateOverlay | None = None
        self._profile_overlay: ProfileOverlay | None = None
        self._after_create_album: Album | None = None
        self._pending_delete: Album | None = None
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
        # первом показе окна (Task 31)
        self._drop_played = False

        # Тосты-уведомления (Task 31): менеджер главного окна; любые
        # диалоги/страницы показывают их через toast.notify(self, …)
        self.toasts = ToastManager(self)

        # Чистка осиротевших картинок (обложки удалённых альбомов и
        # прочий мусор в data/covers) — раз при старте (Task 31)
        STORE.prune_covers()

        central = QWidget(self)
        central.setObjectName("centralWidget")
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # 1. Верхняя полоса с поиском
        self.top_bar = TopBar(central)
        root.addWidget(self.top_bar)
        search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        search_shortcut.activated.connect(self._focus_search)

        # 2. Тело: левая панель + рабочая зона
        body = QWidget(central)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        self.sidebar = Sidebar(body)
        self.sidebar.add_album_clicked.connect(self.open_create_choice)
        self.sidebar.profile_clicked.connect(self.open_profile)
        self.sidebar.mode_clicked.connect(self._toggle_view_mode)
        self.sidebar.destination_clicked.connect(self._open_destination)
        self.updates = Updates(self)
        self.sidebar.update_clicked.connect(self.updates.install)
        self.updates.available.connect(self.sidebar.set_update_state)
        self.updates.progress.connect(self._show_update_progress)
        self.updates.failed.connect(lambda message: notify(self, message, KIND_ERROR))
        self.updates.installer_started.connect(self.close)

        # Рабочая зона — стек страниц: главная, альбом, исполнитель,
        # полные списки «Смотреть все», заглушка «Облачно»
        self.pages = AnimatedStackedWidget(body)
        self.pages.setObjectName("contentArea")
        self.home_page = HomePage(self.pages)
        self.album_page = AlbumDetailPage(self.pages)
        self.artist_page = ArtistDetailPage(self.pages)
        self.artist_editor = ArtistEditorPage(self.pages)
        self.list_page = CollectionPage(self.pages)
        self.cloud_page = CloudStubPage(self.pages)
        self.pages.addWidget(self.home_page)
        self.pages.addWidget(self.album_page)
        self.pages.addWidget(self.artist_page)
        self.pages.addWidget(self.artist_editor)
        self.pages.addWidget(self.list_page)
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
        self.pages.currentChanged.connect(self._sync_destination)

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
    def _focus_search(self) -> None:
        if self.top_bar.search_input.isEnabled() and not self._any_overlay_visible():
            self.top_bar.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _on_search_text(self, text: str) -> None:
        if not text.strip():
            self.search_panel.hide()
            return
        self.search_panel.update_for(text)
        self._reposition_search_panel()
        self.search_panel.show_faded()
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
        # Фильтр стоит на QApplication и видит КАЖДОЕ событие, поэтому
        # сначала дешёвая проверка типа: иначе перестройка главной
        # (сотни событий) тратит время на питон-вызовы (Task 45)
        etype = event.type()
        if etype == QEvent.Type.KeyPress:
            if event.key() != Qt.Key.Key_Escape:
                return False
            # Esc в поле поиска: очистить ввод (панель закроется сама)
            if obj is self.top_bar.search_input:
                self.top_bar.search_input.clear()
                return True
            # Esc на страницах: НАЗАД (на шаг). Только когда не открыт
            # ни один оверлей — иначе Esc управляет им
            if not self._any_overlay_visible():
                current = self.pages.currentWidget()
                if current in (self.list_page, self.album_page,
                               self.artist_page, self.artist_editor):
                    self.search_panel.hide()
                    self._go_back()
                    return True
            return False
        if etype == QEvent.Type.MouseButtonPress \
                and self.search_panel.isVisible() \
                and isinstance(obj, QWidget):
            # Клик мимо панели и поля поиска — закрыть панель
            if not self._is_over_search_widgets(obj):
                self.search_panel.hide()
        return False

    def _any_overlay_visible(self) -> bool:
        """Открыт ли хоть один полнооконный оверлей?"""
        return any(
            overlay is not None and overlay.isVisible()
            for overlay in (
                self._overlay,             # мастер создания/редактирования
                self._choice_overlay,      # выбор способа создания
                self._delete_overlay,      # подтверждение удаления
                self._rate_overlay,        # мастер оценивания (локально)
                self._after_create_overlay,  # «оценить сейчас?»
                self._profile_overlay,     # профиль (вход/регистрация)
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
            self._nav_stack.append(("cloud", None))
        else:
            self._nav_stack.append(("home", None))

    def _go_back(self) -> None:
        """Вернуться на шаг назад (или на главную, если истории нет).

        Экраны при возврате перечитывают данные: база могла измениться
        (например, альбом удалён). Удалённый альбом в истории
        пропускается — возврат происходит дальше по стеку.

        Направление перехода — «назад» (Task 39): прежняя страница
        растворяется со сдвигом вправо, новая приходит слева.
        """
        while self._nav_stack:
            kind, obj = self._nav_stack.pop()
            if kind == "album" and any(a is obj for a in STORE.albums):
                self.album_page.set_album(obj)
                self._show_page(self.album_page, back=True)
                return
            if kind == "artist" and any(a is obj for a in STORE.artists):
                self.artist_page.set_artist(obj)
                self._show_page(self.artist_page, back=True)
                return
            if kind == "list":
                self.list_page.show_mode(obj)
                self._show_page(self.list_page, back=True)
                return
            if kind == "cloud":
                # Возврат в заглушку облачного режима (если его снова
                # не включили — на главную, как из «home»)
                if self._view_mode == "cloud":
                    self._show_page(self.cloud_page, back=True)
                    return
                break
            if kind == "home":
                break
        self._show_home()

    def _show_page(self, page: QWidget, back: bool = False) -> None:
        """Переключить страницу рабочей зоны с учётом направления.

        Вперёд (открытие) — снимок прежней страницы уезжает влево;
        назад — вправо. Анимацию выполняет AnimatedStackedWidget.
        """
        self.pages.set_direction(-1 if back else 1)
        self.pages.setCurrentWidget(page)
        self._sync_destination()

    def _show_update_progress(self, progress: int) -> None:
        release = self.updates.release
        if release is not None:
            self.sidebar.set_update_state(release.version, progress)

    def _sync_destination(self) -> None:
        current = self.pages.currentWidget()
        if current is self.home_page:
            destination = "home"
        elif current is self.list_page:
            destination = self.list_page.mode
        else:
            destination = None
            if current is not self.cloud_page:
                for kind, value in reversed(self._nav_stack):
                    if kind in ("home", "list"):
                        destination = value if kind == "list" else "home"
                        break
        self.sidebar.set_destination(destination)

    def _open_destination(self, destination: str) -> None:
        current = self.pages.currentWidget()
        if destination == "home" and current is not self.home_page:
            self._ensure_local_mode()
            self._nav_stack.clear()
            self.search_panel.hide()
            self._show_home()
        elif destination != "home" and (
            current is not self.list_page or self.list_page.mode != destination
        ):
            self.open_list(destination)
        self._sync_destination()

    def _show_home(self) -> None:
        """Главная: база могла измениться — обновляем.

        Возврат на главную — это всегда «назад»: снимок уходящей
        страницы уезжает вправо, карточки главной появляются каскадом.
        """
        self.home_page.refresh()
        self._show_page(self.home_page, back=True)
        QTimer.singleShot(0, self.home_page.play_entrance)

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
        self._show_page(self.list_page)

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
        self,
        data: DeezerAlbum | SpotifyAlbum | YTMusicAlbum | GeniusAlbum
        | YandexMusicAlbum,
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

    def open_rate_album(self, album: Album | None) -> None:
        if album is None:
            return
        self.search_panel.hide()
        if self._rate_overlay is None:
            self._rate_overlay = RateAlbumOverlay(self)
            self._rate_overlay.album_rated.connect(self._on_album_rated)
        self._rate_overlay.open_for(album)

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
        """Кнопка профиля в сайдбаре — окно входа или карточки аккаунта."""
        self.search_panel.hide()
        if self._profile_overlay is None:
            self._profile_overlay = ProfileOverlay(self)
            self._profile_overlay.account_deleted.connect(
                self._on_account_deleted
            )
            self._profile_overlay.db_imported.connect(self._on_db_imported)
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
        if self._after_create_overlay is not None \
                and self._after_create_overlay.isVisible():
            self._after_create_overlay.setGeometry(self.rect())
        if self._profile_overlay is not None \
                and self._profile_overlay.isVisible():
            self._profile_overlay.setGeometry(self.rect())
        if self.search_panel.isVisible():
            self._reposition_search_panel()

    # --- Анимация открытия (Task 31) ---------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._drop_played:
            self._drop_played = True
            # Дать компоновке пересчитаться после показа — затем
            # содержимое «падает» сверху с проявлением (0.250 с)
            QTimer.singleShot(0, self._play_open_drop)

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
