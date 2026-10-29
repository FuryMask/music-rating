"""Тёмная тема приложения (минимализм).

Здесь живут:
  1. Палитра — константы цветов, чтобы все следующие шаги
     использовали одни и те же цвета из одного места.
  2. QSS — стили в духе CSS, которыми красим виджеты.
  3. Цветовая шкала оценок (rating_color) — единая для карточек,
     страницы альбома и карточек исполнителей.
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# --- Палитра ---
BG_MAIN = "#141414"        # основной фон
BG_BAR = "#1b1b1b"         # верхняя полоса
BG_SIDEBAR = "#181818"     # левая панель
BG_INPUT = "#232323"       # поля ввода
BORDER = "#2a2a2a"         # тонкие границы
FOCUS = "#5a5a5a"          # граница активного элемента
TEXT = "#e8e8e8"           # основной текст
TEXT_MUTED = "#8a8a8a"     # приглушённый текст / подсказки
SELECTION_BG = "#3d3d3d"   # фон выделенного текста
ACCENT = "#e2a84b"         # акцент — пригодится позже (звёзды рейтинга и т.п.)

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
    background-color: {BG_MAIN};
    color: {TEXT};
    selection-background-color: {SELECTION_BG};
    selection-color: #ffffff;
}}

/* Верхняя полоса */
#topBar {{
    background-color: {BG_BAR};
    border-bottom: 1px solid {BORDER};
}}

/* Логотип */
#logo {{
    background: transparent;
    font-weight: 700;
    font-size: 16px;
    letter-spacing: 0.4px;
}}

/* Боковые колонки верхней полосы (невидимые) */
#topBarSide {{
    background: transparent;
}}

/* Левая панель */
#sidebar {{
    background-color: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
}}

/* Рабочая зона */
#contentArea {{
    background-color: {BG_MAIN};
}}

/* Поле поиска */
QLineEdit#searchInput {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
}}

QLineEdit#searchInput:focus {{
    border: 1px solid {FOCUS};
}}

/* Поле поиска в режиме «Облачно» (поиск по облаку пока недоступен) */
QLineEdit#searchInput:disabled {{
    background-color: #1d1d1d;
    border: 1px solid #222222;
    color: #6a6a6a;
}}

/* Метка режима просмотра в правом углу верхней полосы */
#modeLabel {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 13px;
}}

/* Заголовки секций и пустые состояния */
#sectionTitle {{
    font-size: 15px;
    font-weight: 600;
}}

#emptyHint {{
    color: {TEXT_MUTED};
    font-size: 13px;
}}

/* «В разработке» на странице «Комнаты»: крупно и полупрозрачно */
#devPlaceholder {{
    color: rgba(232, 232, 232, 64);
    font-size: 44px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}}

/* Карточка альбома */
#albumTitle {{
    font-size: 13px;
}}

/* Цвет оценки (#albumRating) задаётся inline — rating_color();
   здесь только шрифт */
#albumRating {{
    font-size: 13px;
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
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

#viewAllLabel {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 13px;
}}

/* Страница альбома */
#backButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

#detailTitle {{
    background: transparent;
    font-size: 24px;
    font-weight: 700;
}}

#detailArtists {{
    background: transparent;
    font-size: 14px;
}}

#detailMeta {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 13px;
}}

#albumPage QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

#albumPage QLineEdit:focus {{
    border: 1px solid {FOCUS};
}}

/* Кнопка «+» в сайдбаре */
#plusButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-size: 20px;
    color: {TEXT};
}}

/* Кнопка профиля — самый левый ряд, та же геометрия и стиль */
#profileButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

/* Кнопка сетевых комнат («планета») — та же геометрия и стиль */
#networkButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

/* Кнопка-БД переключения режима просмотра: как соседние; отмеченное
   состояние (= «Облачно») подсвечивается, как выбранные вкладки */
#modeButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

#modeButton:checked {{
    background-color: #353535;
    border: 1px solid {FOCUS};
}}

/* Неактивная кнопка «Выгрузить» на странице альбома — как отключённые
   поля мастера: серая, без ховер-реакций (hover не работает на
   disabled — реакции и не должно быть) */
#uploadAlbumButton:disabled {{
    background-color: #1d1d1d;
    border: 1px solid #222222;
    border-radius: 8px;
    padding: 9px 18px;
    color: #6a6a6a;
}}

/* --- Страница «Комнаты»: поиск лобби оценивания по сети --- */
#roomRow {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

#roomRow:hover {{
    border: 1px solid {FOCUS};
    background-color: #2a2a2a;
}}

#roomRowName {{
    background: transparent;
    font-size: 13px;
    font-weight: 600;
}}

#roomRowHost {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 12px;
}}

/* --- Окно профиля: вход / регистрация / вкладки --- */
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

/* Держатели строк статусов в профиле: вкладка «Данные»
   (#profileStatusHolder) и вкладка «Настройки»
   (#profileDbStatusHolder, экспорт/импорт БД) — строго прозрачные.
   Без этого правила глобальное «*» красит простой QWidget в фон
   главного окна (#141414), и за оповещениями проступает тёмный
   прямоугольник на фоне карточки (#1e1e1e) */
#profileStatusHolder,
#profileDbStatusHolder {{
    background: transparent;
}}

/* Вкладки карточки профиля (Главная / Об аккаунте / Статистика) */
#profileTab {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT};
    font-size: 12px;
}}

#profileTab:hover {{
    border: 1px solid {FOCUS};
}}

#profileTab:checked {{
    background-color: #353535;
    border: 1px solid {FOCUS};
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

/* Маленькие кнопки-иконки окна профиля: «✕» (возврат в меню, в конце
   ряда вкладок) и «✓» (подтвердить смену пароля/имени) */
#profileCloseButton,
#checkButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 0px;
}}

#profileCloseButton:hover,
#checkButton:hover {{
    border: 1px solid {FOCUS};
}}

/* Компактная красная кнопка «Удалить аккаунт» (вкладка «Настройки»);
   отдельный стиль — большая #dangerButton осталась подтверждению
   удаления альбома */
#dangerSmallButton {{
    background-color: {RATING_RED};
    color: #1d0f0f;
    font-weight: 700;
    font-size: 12px;
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
}}

/* --- Мастер создания альбома --- */
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
    border-radius: 8px;
    padding: 8px 12px;
}}

#createOverlay QLineEdit:focus {{
    border: 1px solid {FOCUS};
}}

#createOverlay QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

#createOverlay QComboBox:focus {{
    border: 1px solid {FOCUS};
}}

#createOverlay QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

/* Стрелку рисует сам DarkComboBox (paintEvent): QSS-трюк с
   «треугольником через border» Qt рисует прямоугольником.
   Здесь субконтрол обнулён, чтобы стиль не рисовал свой вариант */
#createOverlay QComboBox::down-arrow {{
    width: 0px;
    height: 0px;
}}

/* Неактивные поля (когда выбран другой режим добавления исполнителя) */
#createOverlay QLineEdit:disabled,
#createOverlay QComboBox:disabled {{
    background-color: #1d1d1d;
    border: 1px solid #222222;
    color: #6a6a6a;
}}

/* --- Редактор исполнителя (страница в рабочей зоне) --- */
#artistEditorPage QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

#artistEditorPage QLineEdit:focus {{
    border: 1px solid {FOCUS};
}}

/* Стрелку рисует сам DarkComboBox — субконтролы QSS обнулены */
#artistEditorPage QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

#artistEditorPage QComboBox:focus {{
    border: 1px solid {FOCUS};
}}

#artistEditorPage QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

#artistEditorPage QComboBox::down-arrow {{
    width: 0px;
    height: 0px;
}}

/* --- Шаг «Исполнители»: радио-варианты добавления --- */
#createOverlay QRadioButton {{
    background: transparent;
    font-size: 13px;
    spacing: 8px;
}}

QRadioButton::indicator {{
    width: 12px;
    height: 12px;
    border: 2px solid {FOCUS};
    border-radius: 8px;
    background: {BG_INPUT};
}}

QRadioButton::indicator:hover {{
    border: 2px solid #7a7a7a;
}}

QRadioButton::indicator:checked {{
    border: 2px solid {ACCENT};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {ACCENT}, stop:0.4 {ACCENT},
        stop:0.5 rgba(0,0,0,0), stop:1 rgba(0,0,0,0));
}}

/* Подписи полей в строку («Имя исполнителя:», «Возраст:»…) */
QLabel#inlineLabel {{
    background: transparent;
    font-size: 13px;
}}

/* Пометка «(необязательно)» */
QLabel#optionalHint {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 11px;
}}

/* Подсказка об ошибке («исполнителя нет в базе») */
QLabel#errorHint {{
    background: transparent;
    color: #d47a7a;
    font-size: 12px;
}}

/* «Список исполнителей:» */
QLabel#listTitle {{
    background: transparent;
    font-size: 13px;
    font-weight: 600;
}}

/* --- Плитка исполнителя (чип) --- */
#artistChip {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

#chipName {{
    background: transparent;
    font-size: 12px;
}}

#chipRemove {{
    background: transparent;
    border: none;
}}

/* --- Внутриприложные диалоги (трек, новый исполнитель) ---
   Фон оверлея рисуется в paintEvent (размытый снимок содержимого),
   карточки — скруглённые панели поверх него. */
#dialogCard {{
    background-color: #1e1e1e;
    border: 1px solid #2e2e2e;
    border-radius: 16px;
}}

#dialogTitle {{
    background: transparent;
    font-size: 15px;
    font-weight: 700;
}}

#dialogCard QLabel {{
    background: transparent;
}}

/* Голые контейнеры внутри карточки (например, QStackedWidget и его
   страницы в окне выбора способа создания) не должны перекрашиваться
   глобальным правилом «*» — иначе внутри карточки проступает тёмный
   квадрат фона главного окна. Прямые наследники — только страницы,
   кнопкам/полям внутри них собственные правила не мешают. */
#dialogCard QStackedWidget,
#dialogCard QStackedWidget > QWidget {{
    background: transparent;
    border: none;
}}

#dialogCard QLineEdit {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

#dialogCard QLineEdit:focus {{
    border: 1px solid {FOCUS};
}}

#dialogCard QComboBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

#dialogCard QComboBox:focus {{
    border: 1px solid {FOCUS};
}}

/* Стрелку комбобокса рисует DarkComboBox (см. комментарий выше) */
#dialogCard QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

#dialogCard QComboBox::down-arrow {{
    width: 0px;
    height: 0px;
}}

/* Скролл-области внутри карточек не должны перекрашивать фон */
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
    border-radius: 8px;
}}

#dialogPlusButton:hover {{
    border: 1px solid {FOCUS};
}}

/* Окно выбора способа создания альбома («+» в сайдбаре) */
#choiceButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 14px;
    color: {TEXT};
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

/* --- Сегмент «Треклист» в мастере --- */
#trackListFrame {{
    background-color: #191919;
    border: 1px solid {BORDER};
    border-radius: 12px;
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
    border-bottom: 1px solid #242424;
}}

#trackRowLast {{
    background: transparent;
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

QComboBox QAbstractItemView {{
    background-color: {BG_BAR};
    border: 1px solid {BORDER};
    color: {TEXT};
    selection-background-color: #2e2e2e;
    selection-color: {TEXT};
    outline: none;
}}

#regionButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT};
}}

#regionButton:checked {{
    background-color: #353535;
    border: 1px solid {FOCUS};
    font-weight: 600;
}}

#primaryButton {{
    background-color: {ACCENT};
    color: #171717;
    font-weight: 700;
    border: none;
    border-radius: 8px;
    padding: 10px 22px;
}}

#primaryButton:disabled {{
    background-color: #2e2e2e;
    color: #6a6a6a;
}}

#ghostButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px 18px;
    color: {TEXT};
}}

/* ТЕСТОВАЯ СБОРКА: неактивная «По сети» в выборе режима оценивания —
   как отключённые поля мастера (клики невозможны, подсказка «В
   разработке» доставляется и отключённой кнопке) */
#ghostButton:disabled {{
    background-color: #1d1d1d;
    border: 1px solid #222222;
    color: #6a6a6a;
}}

/* ТЕСТОВАЯ СБОРКА: кнопки-заглушки в стартовой двери
   («выберите, кем вы являетесь») */
#stubButton {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {TEXT};
}}

#stubButton:hover {{
    border: 1px solid {FOCUS};
}}

#stubButton:checked {{
    background-color: #353535;
    border: 1px solid {FOCUS};
    font-weight: 600;
}}

/* --- Подтверждение удаления альбома --- */
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
    border-radius: 8px;
    padding: 10px 22px;
}}

/* Кнопка «Удалить» в шапке страницы альбома — без заливки,
   красная рамка и текст; при наведении фон слегка краснеет */
#deleteAlbumButton {{
    background-color: transparent;
    border: 1px solid #4a2e2e;
    border-radius: 8px;
    padding: 9px 18px;
    color: {RATING_RED};
}}

#deleteAlbumButton:hover {{
    border-color: {RATING_RED};
    background-color: #2a1c1c;
}}

/* --- Панель результатов поиска под строкой поиска --- */
#searchPanel {{
    background-color: {BG_BAR};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

#searchPanel QLabel {{
    background: transparent;
}}

/* Строки альбома и исполнителя — кликабельны, подсветка при наведении */
#searchRow {{
    background: transparent;
    border-radius: 8px;
}}

#searchRow:hover {{
    background-color: #2a2a2a;
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

/* --- Маркеры автозаполнения: цветной «!» справа от поля ---------- */
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

/* Рамки полей, помеченных при автозаполнении (жёлтый — «верно»,
   красный — «неверно / не заполняется автоматически») */
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

/* Жёлтая рамка плиток исполнителей (автозаполнение или возможный
   дубль альбома при ручном создании) */
#artistChip[autoMark="ok"] {{
    border: 1px solid {RATING_YELLOW};
}}

/* «Возможно такой альбом уже существует» — шаг 1 мастера (без фона) */
#dupWarning {{
    background: transparent;
    color: {RATING_YELLOW};
    font-size: 12px;
}}

/* «Кажется, этот альбом уже создан» — окно ссылки Deezer */
#dupHint {{
    background: transparent;
    color: {RATING_YELLOW};
    font-size: 12px;
}}

/* Окно «Совет.» после предупреждения автозагрузки */
#tipTitle {{
    background: transparent;
    font-size: 16px;
    font-weight: 700;
    color: {RATING_BLUE};
}}

/* --- Страница альбома: «Редактировать», оценка, блок «Оценить?» --- */
/* Без margin: зазор между кнопками задаёт компоновка — обводка ховера
   рисуется по всей ширине виджета, и margin делал её длиннее кнопки */
#editAlbumButton {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 18px;
    color: {TEXT};
}}

#editAlbumButton:hover {{
    border-color: {FOCUS};
    background-color: #232323;
}}

/* Откуда альбом: строка над названием («Создано с помощью …») */
#detailSource {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 12px;
}}

/* Надпись «old» над обложкой на странице альбома (на всех альбомах) */
#oldCoverMark {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 12px;
}}

/* Оценка под «год · жанр» (цвет задаётся inline — rating_color) */
#detailRating {{
    background: transparent;
    font-size: 15px;
    font-weight: 700;
}}

#notRatedHint {{
    background: transparent;
    color: {TEXT_MUTED};
    font-size: 14px;
}}

/* Синяя кнопка «Оценить?» (пользовательское ТЗ — синяя) */
#rateNowButton {{
    background-color: {RATING_BLUE};
    color: #10222e;
    font-weight: 700;
    border: none;
    border-radius: 8px;
    padding: 10px 26px;
}}

/* --- Мастер оценивания ------------------------------------------ */
/* Плитка участника (этап 1) — переключатель */
#raterChip {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 20px;
    color: {TEXT};
    font-size: 13px;
}}

#raterChip:hover {{
    border-color: {FOCUS};
}}

#raterChip:checked {{
    background-color: #33301f;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}

/* Шапка сетки оценок */
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
    border-radius: 6px;
    padding: 2px 4px;
    font-size: 13px;
}}

#ratingCell:focus {{
    border: 1px solid {FOCUS};
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

/* Подсказка под сеткой (секретная 11 и т.п.) */
#rateHint {{
    background: transparent;
    color: {RATING_YELLOW};
    font-size: 12px;
}}

/* Нижняя строка: средняя оценка каждого участника */
#rateAvgLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

#rateAvgValue {{
    background: transparent;
    font-size: 14px;
    font-weight: 700;
}}

/* --- Итоги: статистика --- */
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

/* Заголовок «Альбом создан!» в окне после создания */
#successTitle {{
    background: transparent;
    font-size: 16px;
    font-weight: 700;
    color: {RATING_GREEN};
}}

/* Тонкие скроллбары в духе минимализма */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #2e2e2e;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3a3a3a; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #2e2e2e;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: #3a3a3a; }}

QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QAbstractScrollArea::corner {{ background: transparent; }}
"""


def apply_theme(app: QApplication) -> None:
    """Применяет тёмную палитру и QSS ко всему приложению."""
    app.setStyleSheet(QSS)

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_MAIN))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    app.setPalette(palette)
