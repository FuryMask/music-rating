"""Окно «Создание альбома»: выбор способа или ссылка на Deezer/Spotify/YouTube Music/Genius/Яндекс Музыку.

Открывается по «+» в сайдбаре вместо мастера. Устроено как диалог
трека (см. dialogs/track_dialog.py):
  • фон оверлея — РАЗМЫТЫЙ снимок главного окна (grab + blur);
  • карточка (#dialogCard) поднимается из низа с проявлением;
  • внутри карточки QStackedWidget из трёх страниц:
      0 — «Создать вручную» / «Создать автоматически» (кнопки
          фиксированной ширины, по центру) / «Отмена»;
      1 — ввод ссылки на альбом Deezer, Spotify, YouTube Music,
          Genius или Яндекс Музыки + «Загрузить». Провайдер
          определяется по адресу (deezer.com / spotify / youtube /
          genius.com / music.yandex.*);
      2 — ключи Spotify (Client ID / Client Secret) + прокси:
          открывается, когда вставлена ссылка Spotify, а ключей
          ещё нет, Spotify их отверг или НЕ ОТВЕЧАЕТ (блокировка
          провайдера — тогда в поле прокси вводится адрес
          proxy/VPN, через который Spotify доступен). Ключи и
          прокси хранятся ТОЛЬКО на этом компьютере
          (data/spotify_credentials.json, в архив проекта файл
          не попадает); после сохранения загрузка повторяется
          сама. Прокси касается ТОЛЬКО Spotify — Deezer,
          YouTube Music, Genius и Яндекс Музыка всегда ходят
          напрямую;
  • если ссылка не на альбом (или сети нет) — красная подсказка
    под полем;
  • если альбом по этой ссылке УЖЕ создавали (ссылка запоминается
    за альбомом по id источника: у Deezer — число, у Spotify —
    «spotify:<id>») — жёлтое сообщение «Кажется, этот альбом уже
    создан»: окно не закрывается, загрузить альбом второй раз
    нельзя;
  • при удачной загрузке — сигнал album_loaded(данные альбома): главное
    окно прячет это окно, открывает мастер с заполненными данными
    и предупреждением (см. dialogs/autofill_warning_dialog.py).

Esc: со страницы ключей и ссылки — назад (ключи → ссылка → выбор),
с выбора — закрыть окно.
Во время загрузки поле и кнопки заблокированы, Esc игнорируется.

Ошибки («ссылка не распознана», «альбом уже создан», проблемы
ключей/прокси) — всплывающие тосты сверху по центру главного окна
(Task 31, см. widgets/toast.py); надпись хода загрузки («Загрузка
альбома с Deezer…») остаётся под полем — это индикатор процесса,
а не уведомление.

Кнопки нижнего ряда («Отмена», «← Назад», «Загрузить») смещены
влево и вверх от краёв карточки: при ховер-росте (+10 %) они
не должны «пропадать» на её невидимых границах.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QPoint,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services import deezer, genius, spotify, ytmusic, yandex_music
from app.services.deezer import DeezerAlbum, DeezerError
from app.services.genius import GeniusAlbum, GeniusError
from app.services.music_catalog import CatalogError, MusicCatalog
from app.services.spotify import SpotifyAlbum, SpotifyError
from app.services.yandex_music import YandexMusicAlbum, YandexMusicError
from app.services.ytmusic import YTMusicAlbum, YTMusicError
from app.store import STORE
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.toast import KIND_ERROR, notify
from app.ui.dialogs.exit_confirm_dialog import _make_blurred

CARD_SIZE = (460, 380)   # карточка выбора/ссылки/ключей (третья строка — прокси)
CHOICE_BUTTON_WIDTH = 280  # кнопки выбора — фиксированной ширины по центру
RISE_MS = 320            # подъём с низа + проявление
BLUR_RADIUS = 26         # сила блюра фона (как в диалоге трека)

NOT_LINK_MSG = (
    "Это не ссылка на альбом Deezer, Spotify, YouTube Music, "
    "Genius или Яндекс Музыки. Примеры: "
    "https://www.deezer.com/album/123456, "
    "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv, "
    "https://music.youtube.com/playlist?list=OLAK5uy_…, "
    "https://genius.com/albums/Artist/Album, "
    "https://music.yandex.ru/album/123456"
)


def detect_provider(link: str) -> str:
    """Провайдер ссылки: 'deezer' | 'spotify' | 'ytmusic' | 'genius' |
    'yandex' | '' (не распознана)."""
    text = link.strip()
    if not text:
        return ""
    if text.casefold().startswith("spotify:album:"):
        return "spotify"
    if "://" not in text:
        text = "https://" + text
    host = QUrl(text).host().casefold()
    if "spotify" in host:
        return "spotify"
    if "deezer" in host:
        return "deezer"
    if "youtube" in host or host == "youtu.be":
        return "ytmusic"
    if host == "genius.com" or host.endswith(".genius.com"):
        return "genius"
    if yandex_music.is_yandex_music_host(host):
        return "yandex"
    return ""



class CreateChoiceOverlay(QWidget):
    """Оверлей «как создать альбом»: вручную или по ссылке."""

    manual_requested = Signal()       # «Создать вручную»
    album_loaded = Signal(object)     # данные альбома — загрузка удалась
    cloud_sign_in_requested = Signal()

    def __init__(self, parent: QWidget, *, catalog: MusicCatalog | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self.setObjectName("choiceOverlay")
        self._bg: QPixmap | None = None
        self._loading = False
        self._dup_link: str | None = None  # ссылка уже созданного альбома

        self.card = QWidget(self)
        self.card.setObjectName("dialogCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.card.setFixedSize(*CARD_SIZE)

        self._fx = QGraphicsOpacityEffect(self.card)
        self._fx.setOpacity(1.0)
        self.card.setGraphicsEffect(self._fx)

        card_v = QVBoxLayout(self.card)
        card_v.setContentsMargins(24, 22, 24, 22)
        card_v.setSpacing(12)

        self.pages = QStackedWidget(self.card)
        card_v.addWidget(self.pages)
        self.pages.addWidget(self._make_choice_page())
        self.pages.addWidget(self._make_link_page())
        self.pages.addWidget(self._make_keys_page())

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.handle_escape
        )

    # ==================================================================
    # Страница 0: выбор способа
    # ==================================================================
    def _make_choice_page(self) -> QWidget:
        page = QWidget(self.card)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        title = QLabel("Создание альбома", page)
        title.setObjectName("dialogTitle")
        v.addWidget(title)

        subtitle = QLabel("Как создадим новый альбом?", page)
        subtitle.setObjectName("emptyHint")
        v.addWidget(subtitle)

        v.addSpacing(6)

        # Кнопки НЕ на всю ширину карточки, а фиксированной ширины
        # по центру: растянутые на всю карточку, при ховере (+10 %)
        # они вырастали за её скруглённые края
        self.btn_manual = HoverButton("Создать вручную", page)
        self.btn_manual.setObjectName("choiceButton")
        self.btn_manual.setFixedWidth(CHOICE_BUTTON_WIDTH)
        self.btn_manual.clicked.connect(self._choose_manual)
        v.addWidget(self.btn_manual, 0, Qt.AlignmentFlag.AlignHCenter)

        self.btn_auto = HoverButton("Создать автоматически", page)
        self.btn_auto.setObjectName("choiceButton")
        self.btn_auto.setFixedWidth(CHOICE_BUTTON_WIDTH)
        self.btn_auto.clicked.connect(self._choose_auto)
        v.addWidget(self.btn_auto, 0, Qt.AlignmentFlag.AlignHCenter)

        v.addStretch(1)

        cancel_row = QHBoxLayout()
        # Сдвиг «Отмена» чуть левее и выше: при ховер-росте (+10 %)
        # кнопка не должна добираться до невидимых границ карточки
        # (справа/снизу она слегка «пропадает»)
        cancel_row.setContentsMargins(0, 0, 12, 10)
        cancel_row.addStretch(1)
        self.btn_cancel = HoverButton("Отмена", page)
        self.btn_cancel.setObjectName("ghostButton")
        self.btn_cancel.clicked.connect(self.close_overlay)
        cancel_row.addWidget(self.btn_cancel)
        v.addLayout(cancel_row)
        return page

    # ==================================================================
    # Страница 1: ссылка на альбом Deezer
    # ==================================================================
    def _make_link_page(self) -> QWidget:
        page = QWidget(self.card)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        title = QLabel("Автоматическое создание", page)
        title.setObjectName("dialogTitle")
        v.addWidget(title)

        caption = QLabel(
            "Вставьте ссылку на альбом Deezer, Spotify, YouTube Music, "
            "Genius или Яндекс Музыки:",
            page,
        )
        caption.setObjectName("fieldLabel")
        caption.setWordWrap(True)
        v.addWidget(caption)

        self.input_link = QLineEdit(page)
        self.input_link.setPlaceholderText(
            "https://www.deezer.com/album/123456"
        )
        self.input_link.textChanged.connect(self._on_link_changed)
        self.input_link.returnPressed.connect(self._try_load)
        v.addWidget(self.input_link)

        # Ход загрузки (приглушённая надпись — индикатор процесса,
        # а не уведомление: ошибки уходят в тосты, Task 31)
        self.lbl_status = QLabel("", page)
        self.lbl_status.setObjectName("emptyHint")
        self.lbl_status.hide()
        v.addWidget(self.lbl_status)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        # Кнопки не должны упираться в невидимые границы страницы:
        # страница (QStackedWidget) обрезает детей по своим границам,
        # и при ховер-росте (+10 %) у «Назад» срезался ЛЕВЫЙ край
        # (она стоит вплотную к границе, х = 0), а «Загрузить» без
        # правого поля резался бы справа. Отступы 10/12 дают запас;
        # нижнее поле 10 приподнимает ряд от нижней границы
        buttons.setContentsMargins(10, 0, 12, 10)
        self.btn_back = HoverButton("← Назад", page)
        self.btn_back.setObjectName("ghostButton")
        self.btn_back.clicked.connect(self._back_to_choice)
        buttons.addWidget(self.btn_back)
        buttons.addStretch(1)
        self.btn_load = HoverButton("Загрузить", page)
        self.btn_load.setObjectName("primaryButton")
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self._try_load)
        buttons.addWidget(self.btn_load)
        v.addLayout(buttons)
        return page

    # ==================================================================
    # Страница 2: ключи Spotify (Client ID / Client Secret)
    # ==================================================================
    def _make_keys_page(self) -> QWidget:
        page = QWidget(self.card)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        title = QLabel("Ключи Spotify", page)
        title.setObjectName("dialogTitle")
        v.addWidget(title)

        caption = QLabel(
            "Войдите в облако для использования общего ключа Spotify или укажите свои ключи."
            if self._catalog is not None else "Вставьте ключи приложения с developer.spotify.com.", page,
        )
        caption.setObjectName("fieldLabel")
        caption.setWordWrap(True)
        v.addWidget(caption)

        self.input_client_id = QLineEdit(page)
        self.input_client_id.setPlaceholderText("Client ID")
        self.input_client_id.textChanged.connect(self._sync_keys_state)
        v.addWidget(self.input_client_id)

        self.input_client_secret = QLineEdit(page)
        self.input_client_secret.setPlaceholderText("Client Secret")
        self.input_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_client_secret.textChanged.connect(self._sync_keys_state)
        v.addWidget(self.input_client_secret)

        # Прокси — единственный способ достучаться до Spotify там, где
        # он заблокирован (РФ и т.п.): с выхода НЕ из РФ всё работает
        self.input_proxy = QLineEdit(page)
        self.input_proxy.setPlaceholderText(
            "Прокси (необязательно): http://host:port или socks5://host:port"
        )
        v.addWidget(self.input_proxy)

        hint = QLabel(
            "Ключи и прокси сохраняются только на этом компьютере. "
            "Если Spotify недоступен напрямую — укажите прокси: через "
            "него пойдёт только Spotify, остальные сервисы работают "
            "как обычно.",
            page,
        )
        hint.setObjectName("emptyHint")
        hint.setWordWrap(True)
        v.addWidget(hint)

        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.setContentsMargins(10, 0, 12, 10)
        self.btn_keys_back = HoverButton("← Назад", page)
        self.btn_keys_back.setObjectName("ghostButton")
        self.btn_keys_back.clicked.connect(self._back_to_link)
        buttons.addWidget(self.btn_keys_back)
        if self._catalog is not None:
            button = HoverButton("Войти в облако", page)
            button.setObjectName("ghostButton")
            button.clicked.connect(self._request_cloud_sign_in)
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.btn_keys_save = HoverButton("Сохранить и загрузить", page)
        self.btn_keys_save.setObjectName("primaryButton")
        self.btn_keys_save.setEnabled(False)
        self.btn_keys_save.clicked.connect(self._save_keys_and_load)
        buttons.addWidget(self.btn_keys_save)
        v.addLayout(buttons)
        return page

    # ==================================================================
    # Поведение
    # ==================================================================
    def _choose_manual(self) -> None:
        self.close_overlay()
        self.manual_requested.emit()

    def _choose_auto(self) -> None:
        self._show_error("")
        self._show_dup("")
        self.pages.setCurrentIndex(1)
        self.input_link.setFocus()

    def _back_to_choice(self) -> None:
        if self._loading:
            return
        self._show_error("")
        self._show_dup("")
        self.input_link.clear()
        self.pages.setCurrentIndex(0)

    def _on_link_changed(self, *_args) -> None:
        """Текст ссылки меняется: блокировка «уже создан» снимается."""
        if self._dup_link is not None and \
                self.input_link.text().strip() != self._dup_link:
            self._dup_link = None
            self._show_dup("")
        self._sync_load_state()

    def _sync_load_state(self, *_args) -> None:
        text = self.input_link.text().strip()
        blocked = self._dup_link is not None and text == self._dup_link
        self.btn_load.setEnabled(
            bool(text) and not self._loading and not blocked
        )

    def _show_error(self, text: str) -> None:
        """Ошибка загрузки по ссылке — красный тост (Task 31).

        Пустая строка — сброс перед новой попыткой: показывать нечего.
        """
        if text:
            notify(self, text, KIND_ERROR)

    def _show_dup(self, text: str) -> None:
        """Сообщение «этот альбом уже создан» — красный тост (Task 31)."""
        if text:
            notify(self, text, KIND_ERROR)

    # --- Страница ключей Spotify --------------------------------------
    def _back_to_link(self) -> None:
        if self._loading:
            return
        self._show_keys_error("")
        self.pages.setCurrentIndex(1)
        self.input_link.setFocus()

    def _sync_keys_state(self, *_args) -> None:
        self.btn_keys_save.setEnabled(
            bool(self.input_client_id.text().strip())
            and bool(self.input_client_secret.text().strip())
        )

    def _show_keys_error(self, text: str) -> None:
        """Ошибка страницы ключей — красный тост (Task 31)."""
        if text:
            notify(self, text, KIND_ERROR)

    def _open_keys_page(self, error_text: str = "") -> None:
        """Ссылка Spotify есть, ключей нет (или отвергнуты): окно ключей.

        Сохранённые ключи и прокси подставляются — чтобы можно было
        исправить одну ошибку вместо ввода заново. Ссылка остаётся
        в поле: после сохранения ключей загрузка повторяется сама.
        """
        self.lbl_status.hide()
        creds = spotify.load_credentials()
        if creds is not None:
            self.input_client_id.setText(creds[0])
            self.input_client_secret.setText(creds[1])
        self.input_proxy.setText(spotify.load_proxy())
        self._show_keys_error(error_text)
        self.pages.setCurrentIndex(2)
        self.input_client_id.setFocus()

    def _request_cloud_sign_in(self) -> None:
        self._back_to_link()
        self.cloud_sign_in_requested.emit()

    def _save_keys_and_load(self) -> None:
        """Сохранить ключи и прокси на диск (только локально) и повторить загрузку."""
        client_id = self.input_client_id.text().strip()
        client_secret = self.input_client_secret.text().strip()
        proxy = self.input_proxy.text()
        if not client_id or not client_secret:
            self._show_keys_error("Введите Client ID и Client Secret.")
            return
        # Сначала прокси: невалидная строка не даст сохранить мусор
        proxy_error = spotify.apply_proxy(proxy)
        if proxy_error:
            self._show_keys_error(proxy_error)
            return
        try:
            spotify.save_credentials(client_id, client_secret, proxy)
        except OSError:
            self._show_keys_error("Не удалось сохранить ключи на диск.")
            return
        spotify.invalidate_token()
        self._show_keys_error("")
        self.pages.setCurrentIndex(1)
        self._try_load()

    def _try_load(self) -> None:
        if self._loading:
            return
        link = self.input_link.text().strip()
        if not link:
            return
        # Ссылка уже созданного альбома: запрещаем и повторную загрузку
        # (Enter в поле обходит заблокированную кнопку)
        if link == self._dup_link:
            self._show_dup("Кажется, этот альбом уже создан.")
            return
        provider = detect_provider(link)
        catalog = self._catalog if self._catalog is not None and self._catalog.available() else None
        local_spotify = provider == "spotify" and spotify.load_credentials() is not None
        spotify_catalog = catalog if not local_spotify else None
        if provider == "spotify" and not local_spotify and spotify_catalog is None:
            # Ключей ещё нет: окно ключей, ссылка остаётся в поле —
            # после сохранения загрузка повторится сама
            self._open_keys_page()
            return
        self._loading = True
        self._show_error("")
        status_texts = {
            "spotify": "Загрузка альбома со Spotify…",
            "ytmusic": "Загрузка альбома с YouTube Music…",
            "genius": "Загрузка альбома с Genius…",
            "yandex": "Загрузка альбома с Яндекс Музыки…",
        }
        self.lbl_status.setText(
            status_texts.get(provider, "Загрузка альбома с Deezer…")
        )
        self.lbl_status.show()
        self.btn_load.setEnabled(False)
        self.btn_back.setEnabled(False)
        self.input_link.setEnabled(False)

        data: DeezerAlbum | SpotifyAlbum | YTMusicAlbum | GeniusAlbum | YandexMusicAlbum | None = None
        error_text = ""
        try:
            if provider == "spotify":
                data = (spotify.load_album_from_link(link, catalog=spotify_catalog) if spotify_catalog
                        else spotify.load_album_from_link(link))
            elif provider == "deezer":
                data = deezer.load_album_from_link(link)
            elif provider == "ytmusic":
                data = ytmusic.load_album_from_link(link)
            elif provider == "genius":
                data = genius.load_album_from_link(link, catalog=catalog) if catalog else genius.load_album_from_link(link)
            elif provider == "yandex":
                data = yandex_music.load_album_from_link(link)
            else:
                error_text = NOT_LINK_MSG
        except (
            DeezerError, SpotifyError, YTMusicError, GeniusError,
            YandexMusicError, CatalogError,
        ) as exc:
            error_text = str(exc)

        # Загрузка могла случиться, пока окно уже закрыли (Esc/кнопки
        # заблокированы, но перестраховка не помешает)
        self._loading = False
        self.btn_back.setEnabled(True)
        self.input_link.setEnabled(True)
        self.lbl_status.hide()
        self._sync_load_state()

        if not self.isVisible():
            return
        if data is None:
            if provider == "spotify" and (
                error_text == spotify.BAD_CREDENTIALS_MSG
                or error_text in spotify.CONNECTION_MESSAGES
            ):
                # Ключи отвергнуты ИЛИ Spotify недоступен (блокировка):
                # окно ключей — там же прокси, спасающий от блокировки
                self._open_keys_page(error_text)
            else:
                self._show_error(error_text or "Не удалось загрузить альбом.")
            return
        # Защита от дублей: альбом, созданный по этой ссылке, уже есть
        # (ссылка запоминается за альбомом по id источника)
        if STORE.find_album_by_source(data.album_id) is not None:
            self._dup_link = link
            self._show_dup("Кажется, этот альбом уже создан.")
            self._sync_load_state()
            return
        self.input_link.clear()
        self.close_overlay()
        self.album_loaded.emit(data)

    # ==================================================================
    # Открытие / закрытие (блюр-фон + подъём карточки, как в треке)
    # ==================================================================
    def open(self) -> None:
        parent = self.parentWidget()
        # Снимок ДО показа оверлея — иначе в кадр попал бы он сам
        self._bg = _make_blurred(parent.grab())
        self.setGeometry(parent.rect())

        self._loading = False
        self._dup_link = None
        self._show_error("")
        self._show_dup("")
        self._show_keys_error("")
        self.lbl_status.hide()
        self.input_link.setEnabled(True)
        self.btn_back.setEnabled(True)
        self.input_link.clear()
        self.pages.setCurrentIndex(0)
        self._sync_load_state()

        self.show()
        self.raise_()

        target = QPoint(
            (self.width() - CARD_SIZE[0]) // 2,
            (self.height() - CARD_SIZE[1]) // 2,
        )
        self._fx.setOpacity(0.0)
        self.card.move(target.x(), self.height() + 8)

        pos_anim = QPropertyAnimation(self.card, b"pos", self.card)
        pos_anim.setDuration(RISE_MS)
        pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        pos_anim.setStartValue(self.card.pos())
        pos_anim.setEndValue(target)
        fade_anim = QPropertyAnimation(self._fx, b"opacity", self.card)
        fade_anim.setDuration(RISE_MS)
        fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        group = QParallelAnimationGroup(self.card)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)

        self.card.show()
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
        self.btn_manual.setFocus()

    def close_overlay(self) -> None:
        self.card.hide()
        self.hide()

    def handle_escape(self) -> None:
        if not self.isVisible():
            return  # Esc не должен управлять спрятанным окном
        if self._loading:
            return  # идёт загрузка — Esc игнорируем
        if self.pages.currentIndex() == 2:
            self._back_to_link()
            return
        if self.pages.currentIndex() == 1:
            self._back_to_choice()
            return
        self.close_overlay()

    # ==================================================================
    # Отрисовка и геометрия
    # ==================================================================
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self._bg is not None:
            painter.drawPixmap(self.rect(), self._bg)
        else:
            painter.fillRect(self.rect(), QColor("#141414"))
        # лёгкое затемнение — карточка читается контрастнее
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self.card.move(
                (self.width() - CARD_SIZE[0]) // 2,
                (self.height() - CARD_SIZE[1]) // 2,
            )
            self._fx.setOpacity(1.0)

    def mousePressEvent(self, event) -> None:
        # Клик по фону ничего не делает (закрытие — по кнопкам/Esc)
        event.accept()
