"""Liquid Glass palette and Qt styles for Music Rating."""

import re
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# --- Палитра ---
BG_MAIN = "#101725"        # рабочий холст (контент)
BG_BAR = "#1a273e"         # верхняя полоса
BG_SIDEBAR = "#1c2a42"     # левая панель
BG_INPUT = "#1d2940"       # поля ввода и «спокойные» кнопки
BG_CARD = "#1b263c"        # карточка диалога / панель поиска
BG_HOVER = "#293957"       # подсветка строки/кнопки при наведении
BORDER = "#354768"         # тонкие границы
BORDER_SOFT = "#263650"    # ещё тише: разделители внутри панелей
FOCUS = "#7a9cd6"          # граница активного элемента
TEXT = "#f1f5ff"           # основной текст
TEXT_MUTED = "#acbad4"     # приглушённый текст / подсказки
SELECTION_BG = "#3b5e92"   # фон выделенного текста
ACCENT = "#b9d6ff"         # акцент: выбранное, фокус, главная кнопка
ACCENT_TEXT = "#132442"    # текст на акценте
ACCENT_SOFT = "#2f4a72"    # фон «выбрано» с акцентом
ACCENT_BORDER = "#759ad3"  # граница «выбрано» с акцентом

THEMES = ("Standart", "Dark", "Ruby", "Emerald", "Topaz")
VISUALIZERS = {"off": "Выключено", "wave": "Волна"}
_TINTS = {
    "Dark": (0.62, 0.10),
    "Ruby": (0.97, 1.05),
    "Emerald": (0.44, 0.90),
    "Topaz": (0.10, 1.05),
}
_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}\b|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*\d+)?\s*\)")
_RESOURCES = (Path(__file__).resolve().parent / "resources").as_posix()


def _appearance_settings() -> QSettings:
    return QSettings("Music Rating", "Music Rating")


def saved_theme() -> str:
    name = _appearance_settings().value("appearance/theme", THEMES[0], type=str)
    return name if name in THEMES else THEMES[0]


def saved_visualizer() -> str:
    mode = _appearance_settings().value("appearance/visualizer", "wave", type=str)
    return mode if mode in VISUALIZERS else "wave"


def save_visualizer(mode: str) -> None:
    if mode in VISUALIZERS:
        _appearance_settings().setValue("appearance/visualizer", mode)


def _tint(color: QColor, name: str | None) -> QColor:
    hue, saturation, value, alpha = color.getHsvF()
    if name not in _TINTS or not (0.50 <= hue <= 0.78) or saturation < 0.05:
        return color
    target, strength = _TINTS[name]
    return QColor.fromHsvF((target + (hue - 0.62) * 0.28) % 1,
                           min(1.0, saturation * strength), value, alpha)


def themed_color(color: QColor | str) -> QColor:
    app = QApplication.instance()
    name = app.property("musicRatingTheme") if app is not None else None
    return _tint(QColor(color), name)


def _stylesheet(name: str) -> str:
    if name == THEMES[0]:
        return QSS

    def replace(match: re.Match) -> str:
        literal = match.group()
        if literal == RATING_BLUE:
            return literal
        if literal.startswith("#"):
            return _tint(QColor(literal), name).name()
        channels = [int(value) for value in re.findall(r"\d+", literal)]
        color = _tint(QColor(*channels), name)
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"

    return _COLOR_PATTERN.sub(replace, QSS)

# --- Цветовая шкала оценок (0–10, шаг 0.1) ---
RATING_RED = "#e25c5c"      # 0.0–3.9
RATING_YELLOW = "#e6c34d"   # 4.0–6.9
RATING_GREEN = "#5ec26a"    # 7.0–8.9
RATING_BLUE = "#58a6e8"     # 9.0–10 (голубовато-синий)


def rating_color(value: float | None) -> str:
    """Цвет оценки по её значению; None (не оценено) — приглушённый."""
    if value is None:
        return TEXT_MUTED
    if value < 4.0:
        return RATING_RED
    if value < 7.0:
        return RATING_YELLOW
    if value < 9.0:
        return RATING_GREEN
    return RATING_BLUE


QSS = f"""
* {{
    color: {TEXT};
    selection-background-color: {SELECTION_BG};
    selection-color: #ffffff;
}}

/* Текстовые метки прозрачны всегда: их фон — то, что под ними
   (карточка диалога, панель, холст), а не собственный прямоугольник */
QLabel {{
    background: transparent;
}}

#logo {{ background: transparent; font-weight: 700; font-size: 16px; }}
#topBar, #topBarSide, #sidebar {{ background: transparent; border: none; }}

#homePage,
#listenPage,
#collectionPage,
#artistPage,
#albumPage,
#artistEditorPage,
#cloudPage {{
    background-color: {BG_MAIN};
}}

#listenTitle {{
    color: {TEXT};
    font-weight: 700;
    font-size: 24px;
}}
#listenArtist {{ color: {TEXT_MUTED}; font-size: 15px; }}
#listenControl, #listenAlbumLink {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
#listenAlbumLink {{ padding: 8px 12px; }}
#listenControl:hover, #listenControl:focus, #listenAlbumLink:focus {{
    border-color: {ACCENT_BORDER};
}}
#listenControl:disabled {{ background-color: {BG_CARD}; border-color: {BORDER_SOFT}; }}
#listenRatings, #listenRatings QWidget {{ background: transparent; }}
#listenProgress {{
    min-height: 18px;
    max-height: 18px;
}}
#listenProgress::groove:horizontal {{
    background-color: {BG_INPUT};
    border-radius: 2px;
    height: 4px;
}}
#listenProgress::sub-page:horizontal {{ background-color: {ACCENT}; border-radius: 2px; }}
#listenProgress::handle:horizontal {{
    background-color: {ACCENT};
    border: none;
    border-radius: 6px;
    width: 12px;
    margin: -4px 0;
}}
#listenProgress::handle:horizontal:disabled {{ background-color: transparent; }}

/* ---------- Поле поиска ---------- */
QLineEdit#searchInput {{
    background: rgba(6, 13, 29, 114);
    border: 1px solid rgba(201, 223, 255, 67);
    border-radius: 17px;
    padding: 8px 12px;
}}

QLineEdit#searchInput:hover {{
    border-color: {FOCUS};
}}

QLineEdit#searchInput:focus {{
    border: 1px solid {ACCENT_BORDER};
    background-color: {BG_INPUT};
}}

/* Поле поиска в режиме «Облачно» (поиск по облаку недоступен) */
QLineEdit#searchInput:disabled {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SOFT};
    color: #8090ae;
}}

/* ---------- Тексты и секции ---------- */
#sectionTitle {{
    font-size: 21px;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: 0.2px;
}}

#emptyHint {{
    color: {TEXT_MUTED};
    font-size: 13px;
}}

/* «В разработке» на странице «Облачно»: крупно и полупрозрачно */
#devPlaceholder {{
    color: rgba(220, 234, 255, 155);
    font-size: 44px;
    font-weight: 700;
    letter-spacing: 1px;
    background: qradialgradient(cx:0.5, cy:0.50, radius:0.43,
        stop:0 rgba(86, 116, 179, 62), stop:1 transparent);
}}

/* ---------- Карточка альбома ---------- */
/* Цвет названия задаётся inline (плавно белеет при наведении) */
#albumTitle {{
    font-size: 13px;
    color: #e8e8ee;
}}

/* Оценка — «пилюля», которую рисует AlbumCard.paintEvent;
   здесь только шрифт. Цвет — inline по шкале rating_color() */
#albumRating {{
    font-size: 11px;
    font-weight: 700;
}}

/* Карточка исполнителя (круглое фото, имя, средняя оценка) */
#artistName {{
    font-size: 13px;
}}

/* Цвет — inline (rating_color от средней оценки альбомов) */
#artistRating {{
    font-size: 12px;
    font-weight: 700;
}}

/* Плитка «Смотреть все» — восьмая плитка полной секции */
#viewAllTile {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {BG_HOVER}, stop:1 {BG_CARD});
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

#viewAllLabel {{
    background: transparent;
    color: #c8d7ee;
    font-size: 13px;
    letter-spacing: 0.2px;
}}

/* ---------- Страница альбома ---------- */
#backButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 13px;
}}

#backButton:hover {{
    background-color: {BG_HOVER};
    border-color: {FOCUS};
}}

#detailTitle {{
    background: transparent;
    font-size: 33px;
    font-weight: 700;
    letter-spacing: -0.4px;
    color: #f6f6f8;
}}

#detailArtists {{
    background: transparent;
    font-size: 15px;
    color: #bdcce5;
}}

#detailMeta {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 13px;
}}

#albumPage QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 8px 12px;
}}

#albumPage QLineEdit:focus {{
    border: 1px solid {FOCUS};
}}

/* ---------- Кнопки сайдбара ---------- */
#plusButton,
#profileButton,
#modeButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 13px;
}}

#plusButton:hover,
#profileButton:hover,
#modeButton:hover {{
    background-color: {BG_HOVER};
    border-color: {FOCUS};
}}

/* Кнопка-БД переключения режима: отмеченное состояние (= «Облачно»)
   подсвечивается голубым акцентом, как выбранные вкладки */
#modeButton:checked {{
    background-color: {ACCENT_SOFT};
    border: 1px solid {ACCENT_BORDER};
}}

/* Неактивная кнопка «Выгрузить» — серая, без ховер-реакций */
#uploadAlbumButton:disabled {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 11px;
    padding: 9px 18px;
    color: #8090ae;
}}

/* ---------- Окно профиля: вход / регистрация / вкладки ---------- */
#profileTitle {{
    background: transparent;
    font-size: 18px;
    font-weight: 700;
}}

#authLink {{
    background: transparent;
    font-size: 12px;
}}

QLabel#authError {{
    background: transparent;
    color: {RATING_RED};
    font-size: 12px;
}}

/* Держатели строк статусов в профиле — строго прозрачные (см. HANDOFF
   §5.4: иначе глобальное «*» красит QWidget и на карточке проступает
   тёмный прямоугольник) */
#profileStatusHolder,
#profileDbStatusHolder {{
    background: transparent;
}}

/* Вкладки карточки профиля */
#profileTab {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 7px 14px;
    color: {TEXT};
    font-size: 12px;
}}

#profileTab:hover {{
    border: 1px solid {FOCUS};
}}

#profileTab:checked {{
    background-color: {ACCENT_SOFT};
    border: 1px solid {ACCENT_BORDER};
    font-weight: 600;
}}

#profileName {{
    background: transparent;
    font-size: 20px;
    font-weight: 700;
}}

#profileMeta {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 13px;
}}

#statRow {{
    background: transparent;
    font-size: 13px;
}}

/* Маленькие кнопки-иконки окна профиля: «✕» и «✓» */
#profileCloseButton,
#checkButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 0px;
}}

#profileCloseButton:hover,
#checkButton:hover {{
    border: 1px solid {FOCUS};
    background-color: {BG_HOVER};
}}

/* Компактная красная кнопка «Удалить аккаунт» */
#dangerSmallButton {{
    background-color: {RATING_RED};
    color: #1d0f0f;
    font-weight: 700;
    font-size: 12px;
    border: none;
    border-radius: 11px;
    padding: 6px 14px;
}}

#dangerSmallButton:hover {{
    background-color: #ef6f6f;
}}

/* ---------- Мастер создания альбома ---------- */
#createOverlay {{
    background-color: {BG_MAIN};
}}

#overlayTitle {{
    font-size: 18px;
    font-weight: 700;
}}

#stepHint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#fieldLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#createOverlay QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 8px 12px;
}}

#createOverlay QLineEdit:focus {{
    border: 1px solid {ACCENT_BORDER};
}}

#createOverlay QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 8px 12px;
}}

#createOverlay QComboBox:focus {{
    border: 1px solid {ACCENT_BORDER};
}}

#createOverlay QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

/* Стрелку рисует сам DarkComboBox (paintEvent): QSS-трюк с
   «треугольником через border» Qt рисует прямоугольником */
#createOverlay QComboBox::down-arrow {{
    width: 0px;
    height: 0px;
}}

/* Неактивные поля (когда выбран другой режим добавления исполнителя) */
#createOverlay QLineEdit:disabled,
#createOverlay QComboBox:disabled {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_SOFT};
    color: #8090ae;
}}

/* ---------- Редактор исполнителя (страница рабочей зоны) ---------- */
#artistEditorPage QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 8px 12px;
}}

#artistEditorPage QLineEdit:focus {{
    border: 1px solid {ACCENT_BORDER};
}}

#artistEditorPage QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 8px 12px;
}}

#artistEditorPage QComboBox:focus {{
    border: 1px solid {ACCENT_BORDER};
}}

#artistEditorPage QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

#artistEditorPage QComboBox::down-arrow {{
    width: 0px;
    height: 0px;
}}

/* ---------- Радио-варианты ---------- */
#createOverlay QRadioButton {{
    background: transparent;
    font-size: 13px;
    spacing: 8px;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    image: url("{_RESOURCES}/radio-off.svg");
}}

QRadioButton::indicator:checked {{
    image: url("{_RESOURCES}/radio-on.svg");
}}

/* Подписи полей в строку, пометки, ошибки */
QLabel#inlineLabel {{
    background: transparent;
    font-size: 13px;
}}

QLabel#optionalHint {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 11px;
}}

QLabel#errorHint {{
    background: transparent;
    color: #d47a7a;
    font-size: 12px;
}}

QLabel#listTitle {{
    background: transparent;
    font-size: 13px;
    font-weight: 600;
}}

/* ---------- Плитка исполнителя (чип) ---------- */
#artistChip {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
}}

#chipName {{
    background: transparent;
    font-size: 12px;
}}

#chipRemove {{
    background: transparent;
    border: none;
}}

/* ---------- Внутриприложные диалоги ---------- */
/* Фон оверлея рисуется в paintEvent (размытый снимок содержимого),
   карточки — скруглённые панели поверх него. */
#dialogCard {{
    background: qlineargradient(x1:0, y1:0, x2:0.8, y2:1,
        stop:0 rgba(48, 64, 95, 247), stop:1 rgba(26, 35, 56, 246));
    border: 1px solid rgba(190, 218, 255, 114);
    border-radius: 23px;
}}

#dialogTitle {{
    background: transparent;
    font-size: 15px;
    font-weight: 700;
}}

#dialogCard QLabel {{
    background: transparent;
}}

/* Вложенные страницы мастера оставляют видимым материал карточки. */
#dialogCard QStackedWidget,
#dialogCard QStackedWidget > QWidget {{
    background: transparent;
    border: none;
}}

#dialogCard QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 8px 12px;
}}

#dialogCard QLineEdit:focus {{
    border: 1px solid {ACCENT_BORDER};
}}

#dialogCard QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 8px 12px;
}}

#dialogCard QComboBox:focus {{
    border: 1px solid {ACCENT_BORDER};
}}

#dialogCard QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

#dialogCard QComboBox::down-arrow {{
    width: 0px;
    height: 0px;
}}

/* Скролл-области внутри карточек не перекрашивают фон */
#dialogCard QScrollArea {{
    background: transparent;
    border: none;
}}

#dialogCard QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* Плюс «создать исполнителя» справа от поиска в диалоге трека */
#dialogPlusButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
}}

#dialogPlusButton:hover {{
    border: 1px solid {FOCUS};
    background-color: {BG_HOVER};
}}

/* Окно выбора способа создания альбома («+» в сайдбаре) */
#choiceButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 13px;
    padding: 14px 18px;
    font-size: 14px;
    color: {TEXT};
}}

#choiceButton:hover {{
    background-color: {BG_HOVER};
    border-color: {FOCUS};
}}

/* Предупреждение после автоматической загрузки альбома */
#warningTitle {{
    background: transparent;
    font-size: 16px;
    font-weight: 700;
    color: {RATING_YELLOW};
}}

#warningBody {{
    background: transparent;
    font-size: 13px;
    color: {TEXT};
}}

/* ---------- Сегмент «Треклист» ---------- */
#trackListFrame {{
    background-color: #151e30;
    border: 1px solid {BORDER_SOFT};
    border-radius: 18px;
}}

#trackListFrame QLabel {{
    background: transparent;
}}

#trackListFrame QScrollArea {{
    background: transparent;
    border: none;
}}

#trackListFrame QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* Строка трека; последняя — без разделителя снизу */
#trackRow {{
    background: transparent;
    border-bottom: 1px solid rgba(179, 204, 242, 26);
}}

#trackRowLast {{
    background: transparent;
}}

#trackRow:hover,
#trackRowLast:hover {{
    background-color: rgba(255, 255, 255, 7);
}}

#trackIndex {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#trackRowTitle {{
    font-size: 13px;
}}

#trackArtists {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

/* ---------- Выпадающие списки ---------- */
QListView#completionList {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 11px;
    color: {TEXT};
    selection-background-color: {SELECTION_BG};
    selection-color: #ffffff;
    outline: none;
    padding: 4px;
}}

QComboBox {{ combobox-popup: 0; }}

QComboBox QAbstractItemView {{
    background: transparent;
    border: none;
    padding: 0;
    selection-background-color: {SELECTION_BG};
    selection-color: #ffffff;
    outline: none;
}}

QComboBox QAbstractItemView::item {{ padding: 4px 8px; }}
QListView#completionList::item {{ padding: 6px 12px; }}

#artistChipList, #artistChipList QWidget#qt_scrollarea_viewport {{
    background: transparent;
}}

/* ---------- Основные кнопки ---------- */
#regionButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    color: {TEXT};
}}

#regionButton:hover {{
    border-color: {FOCUS};
}}

#regionButton:checked {{
    background-color: {ACCENT_SOFT};
    border: 1px solid {ACCENT_BORDER};
    font-weight: 600;
}}

#primaryButton {{
    background-color: {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 700;
    border: none;
    border-radius: 12px;
    padding: 10px 22px;
}}

#primaryButton:hover {{
    background-color: #d5e7ff;
}}

#primaryButton:pressed {{
    background-color: #9bbcf1;
}}

#primaryButton:disabled {{
    background-color: {BG_CARD};
    color: #8090ae;
}}

#ghostButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 18px;
    color: {TEXT};
}}

#ghostButton:hover {{
    background-color: {BG_HOVER};
    border-color: {FOCUS};
}}

#ghostButton:pressed {{
    background-color: {BG_INPUT};
}}

#ghostButton:disabled {{
    background-color: {BG_CARD};
    border-color: {BORDER_SOFT};
    color: #8090ae;
}}

/* ---------- Подтверждение удаления альбома ---------- */
#dangerTitle {{
    background: transparent;
    font-size: 15px;
    font-weight: 700;
    color: {RATING_RED};
}}

#dangerButton {{
    background-color: {RATING_RED};
    color: #1d0f0f;
    font-weight: 700;
    border: none;
    border-radius: 12px;
    padding: 10px 22px;
}}

#dangerButton:hover {{
    background-color: #ea6f6f;
}}

#dangerButton:pressed {{
    background-color: #cf5050;
}}

/* Кнопка «Удалить» в шапке страницы альбома */
#deleteAlbumButton {{
    background-color: transparent;
    border: 1px solid #4a2e2e;
    border-radius: 11px;
    padding: 9px 18px;
    color: {RATING_RED};
}}

#deleteAlbumButton:hover {{
    border-color: {RATING_RED};
    background-color: #2a1c1c;
}}

/* ---------- Панель результатов поиска ---------- */
#searchPanel {{
    background: qlineargradient(x1:0, y1:0, x2:0.8, y2:1,
        stop:0 #293954, stop:1 #1c2842);
    border: 1px solid #627395;
    border-radius: 18px;
}}

#searchPanel QLabel {{
    background: transparent;
}}

#searchRow {{
    background: transparent;
    border-radius: 11px;
}}

#searchRow:hover {{
    background-color: {BG_HOVER};
}}

#searchRowName {{
    font-size: 13px;
}}

#searchRowType {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#searchEmpty {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

/* ---------- Маркеры автозаполнения ---------- */
QLabel#autoMarkBadge {{
    background: transparent;
    font-size: 15px;
    font-weight: 700;
}}

QLabel#autoMarkBadge[mark="ok"] {{
    color: {RATING_YELLOW};
}}

QLabel#autoMarkBadge[mark="bad"] {{
    color: {RATING_RED};
}}

/* Рамки полей, помеченных при автозаполнении */
#createOverlay QLineEdit[autoMark="ok"] {{
    border: 1px solid {RATING_YELLOW};
}}

#createOverlay QLineEdit[autoMark="bad"] {{
    border: 1px solid {RATING_RED};
}}

#createOverlay QComboBox[autoMark="ok"] {{
    border: 1px solid {RATING_YELLOW};
}}

#createOverlay QComboBox[autoMark="bad"] {{
    border: 1px solid {RATING_RED};
}}

#regionButton[autoMark="ok"] {{
    border: 1px solid {RATING_YELLOW};
}}

#regionButton[autoMark="bad"] {{
    border: 1px solid {RATING_RED};
}}

#artistChip[autoMark="ok"] {{
    border: 1px solid {RATING_YELLOW};
}}

#dupWarning {{
    background: transparent;
    color: {RATING_YELLOW};
    font-size: 12px;
}}

#dupHint {{
    background: transparent;
    color: {RATING_YELLOW};
    font-size: 12px;
}}

#tipTitle {{
    background: transparent;
    font-size: 16px;
    font-weight: 700;
    color: {RATING_BLUE};
}}

/* ---------- Страница альбома: «Редактировать», оценка, «Оценить?» ---------- */
#editAlbumButton {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 9px 18px;
    color: {TEXT};
}}

#editAlbumButton:hover {{
    border-color: {FOCUS};
    background-color: {BG_HOVER};
}}

#detailSource {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#oldCoverMark {{
    background: transparent;
    color: #98a9c7;
    font-size: 11px;
    letter-spacing: 0.6px;
}}

#detailRating {{
    background: transparent;
    font-size: 15px;
    font-weight: 700;
}}

#notRatedHint {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 13px;
}}

/* Кнопка «Оценить?» */
#rateNowButton {{
    background-color: {ACCENT};
    color: {ACCENT_TEXT};
    font-weight: 700;
    border: none;
    border-radius: 12px;
    padding: 10px 26px;
}}

#rateNowButton:hover {{
    background-color: #d5e7ff;
}}

#rateNowButton:pressed {{
    background-color: #9bbcf1;
}}

/* ---------- Мастер оценивания ---------- */
#raterChip {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 13px;
    padding: 8px 20px;
    color: {TEXT};
    font-size: 13px;
}}

#raterChip:hover {{
    border-color: {FOCUS};
}}

#raterChip:checked {{
    background-color: {ACCENT_SOFT};
    border: 1px solid {ACCENT};
    font-weight: 600;
}}

#rateHeadRow {{
    background: transparent;
    border-bottom: 1px solid {BORDER};
}}

#rateHeadTitle {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#rateColName {{
    color: {TEXT_MUTED};
    font-size: 12px;
    font-weight: 600;
}}

/* Клетка оценки 0–10 (шаг 0.1); секретная 11 — жёлтая рамка,
   невалидная (вторая «11» в столбце) — красная */
#ratingCell {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 2px 4px;
    font-size: 13px;
}}

#ratingCell:focus {{
    border: 1px solid {ACCENT_BORDER};
}}

#ratingCell[state="secret"] {{
    border: 1px solid {ACCENT};
    color: {ACCENT};
    font-weight: 700;
    background-color: #2a2418;
}}

#ratingCell[state="bad"] {{
    border: 1px solid {RATING_RED};
    color: {RATING_RED};
}}

#rateHint {{
    background: transparent;
    color: {RATING_YELLOW};
    font-size: 12px;
}}

#rateAvgLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#rateAvgValue {{
    background: transparent;
    font-size: 14px;
    font-weight: 700;
}}

/* ---------- Итоги: статистика ---------- */
#statsRow {{
    background: transparent;
    font-size: 13px;
}}

#statsHighlight {{
    background: transparent;
    font-size: 13px;
    font-weight: 700;
    color: {ACCENT};
}}

#successTitle {{
    background: transparent;
    font-size: 16px;
    font-weight: 700;
    color: {RATING_GREEN};
}}

/* ---------- Скроллбары: тонкие, «растворяются» в фоне ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 4px 0;
}}
QScrollBar::handle:vertical {{
    background: transparent;
    min-height: 16px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    margin: 0 4px;
}}
QScrollBar::handle:horizontal {{
    background: transparent;
    min-width: 16px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QAbstractScrollArea::corner {{ background: transparent; }}

/* Прозрачные вьюпорты лент и списков */
#sectionRow, #sectionRow > QWidget > QWidget {{
    background: transparent;
    border: none;
}}

/* Полоса прокрутки ГОРИЗОНТАЛЬНОЙ ленты карточек — почти невидимая:
   лента листается колесом/тачпадом, а полоса лишь намекает, что
   правее есть ещё карточки */
#sectionRow QScrollBar:horizontal {{
    height: 5px;
}}

/* ---------- Подсказки и меню ---------- */
QToolTip {{
    background-color: {BG_CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 9px;
    font-size: 12px;
}}

QMenu {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 13px;
    padding: 6px;
}}

QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 6px;
    background: transparent;
}}

QMenu::item:selected {{
    background-color: {BG_HOVER};
}}

QMenu::separator {{
    height: 1px;
    background: {BORDER_SOFT};
    margin: 5px 8px;
}}

#centralWidget {{
    background: qradialgradient(cx:0.12, cy:0.04, radius:0.98, fx:0.12, fy:0.04,
        stop:0 #233355, stop:0.48 #141f36, stop:1 #101420);
}}
#brandMark {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #496da1, stop:1 #39335e);
    border: 1px solid rgba(214, 232, 255, 110);
    border-radius: 11px;
}}
#sidebarCaption {{
    color: #bac8e2;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.7px;
    padding: 0 0 2px 8px;
}}
#appVersion {{ background: transparent; color: {TEXT_MUTED}; font-size: 10px; margin-top: 5px; }}
#updateButton {{
    background: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {FOCUS};
    border-radius: 14px;
    min-height: 36px;
    padding: 0 12px;
    text-align: left;
}}
#updateButton:disabled {{ background: transparent; color: {TEXT_MUTED}; border-color: {BORDER_SOFT}; }}
#updateButton:hover {{ background: {BG_HOVER}; }}

#navButton {{
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 14px;
    padding: 8px 9px;
    min-height: 20px;
    font-size: 13px;
    font-weight: 600;
}}
#navButton:hover {{ background: rgba(193, 218, 255, 23); }}
#navButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(184, 214, 255, 72), stop:1 rgba(148, 172, 242, 38));
    border-color: rgba(208, 229, 255, 100);
}}
#navButton:pressed {{ background: rgba(193, 218, 255, 82); }}
#navButton:focus {{ border-color: {ACCENT}; }}
#modeLabel {{
    color: #e3edff;
    background: rgba(185, 214, 255, 27);
    border: 1px solid rgba(213, 230, 255, 59);
    border-radius: 12px;
    padding: 4px 10px;
    font-weight: 600;
}}
#contentArea {{
    background: {BG_MAIN};
    border: 1px solid {BORDER_SOFT};
    border-radius: 23px;
    padding: 9px;
}}
#plusButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #507fbe, stop:1 #49478b);
    border-color: #83a3d7;
}}
#plusButton:hover {{ background: #586caa; }}
#primaryButton:focus, #ghostButton:focus, #rateNowButton:focus,
#backButton:focus, #plusButton:focus,
#profileButton:focus, #modeButton:focus {{
    border: 1px solid #e1edff;
}}
"""


def apply_theme(app: QApplication, name: str | None = None, *, persist: bool = False) -> None:
    """Применяет палитру сразу; при запуске читает локальный выбор."""
    name = saved_theme() if name is None else name
    name = name if name in THEMES else THEMES[0]
    if persist:
        _appearance_settings().setValue("appearance/theme", name)
    app.setProperty("musicRatingTheme", name)
    palette = app.palette()
    for role, value in (
        (QPalette.ColorRole.PlaceholderText, TEXT_MUTED),
        (QPalette.ColorRole.Window, BG_MAIN),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, BG_INPUT),
        (QPalette.ColorRole.AlternateBase, BG_CARD),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.Button, BG_INPUT),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, ACCENT_TEXT),
        (QPalette.ColorRole.ToolTipBase, BG_CARD),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ):
        palette.setColor(role, _tint(QColor(value), name))
    app.setPalette(palette)
    app.setStyleSheet(_stylesheet(name))
