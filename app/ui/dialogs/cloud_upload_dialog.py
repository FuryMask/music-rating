"""Connect an account and exchange records with the shared library."""

import json
import sqlite3
from uuid import UUID

from PySide6.QtCore import QEvent, QPoint, QRect, QRegularExpression, QSettings, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.services.cloud_library import CloudError, CloudLibrary, CloudSession, snapshot_library
from app.services.shared_library import BASELINE, baseline, download_plan, member_names, upload_plan
from app.services.windows_credentials import protect_secret, unprotect_secret
from app.store import STORE
from app.theme import BG_MAIN, themed_color
from app.ui.dialogs.exit_confirm_dialog import _make_blurred
from app.ui.widgets.hoverable import HoverButton
from app.ui.widgets.motion import fade_in

_SESSION_KEY = "CloudSession/current"
_SESSION_MIGRATED_KEY = "CloudSession/migrated"


class CloudUploadDialog(QDialog):
    _finished = Signal(object, object)
    _poll_finished = Signal(object, object)
    _session_refreshed = Signal(object)
    availability_changed = Signal(bool, str)
    library_downloaded = Signal(int)
    members_changed = Signal(object)
    session_changed = Signal(object)
    display_name_finished = Signal(str)
    sign_in_required = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Загрузка в облако")
        self._background: QPixmap | None = None
        self._cloud = CloudLibrary()
        self._session: CloudSession | None = None
        self._settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope,
                                   "Music Rating", "Music Rating")
        self._members: dict[str, str] = {}
        self._polling = False
        self._deferred_operation = None
        self._continuation = None
        self._failure_callback = None
        self._carry_out_upload = False
        self._action = "upload"
        self._auth_only = False
        self._finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
        self._poll_finished.connect(self._on_polled, Qt.ConnectionType.QueuedConnection)
        self._session_refreshed.connect(self._save_session, Qt.ConnectionType.QueuedConnection)
        self._poll_timer = QTimer(self, interval=20000)
        self._poll_timer.timeout.connect(self.poll)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        self.card = QWidget(self)
        self.card.setObjectName("dialogCard")
        self.card.setFixedWidth(510)
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        self.confirm_title = QLabel("Переместить все локальные данные в облако?", self.card)
        self.confirm_title.setObjectName("warningTitle")
        self.confirm_title.setWordWrap(True)
        layout.addWidget(self.confirm_title)
        self.pages = QStackedWidget(self.card)
        layout.addWidget(self.pages)
        self.confirm = self._make_confirm()
        self.sign_in = self._make_sign_in()
        self.verify_email = self._make_verify_email()
        self.preview = self._make_preview()
        self.fetch_page = QWidget()
        fetch_layout = QHBoxLayout(self.fetch_page)
        fetch_layout.setContentsMargins(0, 0, 0, 0)
        self._button("Закрыть", self.reject, fetch_layout)
        fetch_layout.addStretch(1)
        self.pages.addWidget(self.fetch_page)
        self.status = QLabel(self.card)
        self.status.setObjectName("warningBody")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.hide()
        layout.addWidget(self.status)
        parent.installEventFilter(self)
        self._restore_session()

    def _make_confirm(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QLabel("Локальная копия сохранится. Загруженные записи будут видны участникам общей библиотеки.", page)
        text.setObjectName("warningBody")
        text.setWordWrap(True)
        layout.addWidget(text)
        row = QHBoxLayout()
        self.no_button = self._button("Нет", self.reject, row)
        row.addStretch(1)
        self.preview_button = self._button("Предосмотр", lambda: self._start(upload=False), row)
        self.yes_button = self._button("Да", lambda: self._start(upload=True), row, primary=True)
        layout.addLayout(row)
        account_row = QHBoxLayout()
        self.account_button = self._button("Войти в аккаунт", self._cloud_account, account_row)
        account_row.addStretch(1)
        layout.addLayout(account_row)
        self.pages.addWidget(page)
        return page

    def _make_sign_in(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Войдите в облачный аккаунт Music Rating.", page)
        label.setObjectName("warningBody")
        layout.addWidget(label)
        form = QFormLayout()
        self.email = QLineEdit(page)
        self.password = QLineEdit(page)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Электронная почта", self.email)
        form.addRow("Пароль", self.password)
        layout.addLayout(form)
        self.password.returnPressed.connect(lambda: self._authenticate(register=False))
        row = QHBoxLayout()
        self._button("Назад", self._back_from_sign_in, row)
        row.addStretch(1)
        self._button("Создать аккаунт", lambda: self._authenticate(register=True), row)
        self._button("Войти", lambda: self._authenticate(register=False), row, primary=True)
        layout.addLayout(row)
        self.pages.addWidget(page)
        return page

    def _make_verify_email(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.code_recipient = QLabel(page)
        self.code_recipient.setObjectName("warningBody")
        self.code_recipient.setTextFormat(Qt.TextFormat.PlainText)
        self.code_recipient.setWordWrap(True)
        layout.addWidget(self.code_recipient)
        form = QFormLayout()
        self.email_code = QLineEdit(page)
        self.email_code.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)
        self.email_code.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]{0,10}"), self.email_code))
        self.email_code.returnPressed.connect(self._confirm_email)
        form.addRow("Код из письма", self.email_code)
        layout.addLayout(form)
        row = QHBoxLayout()
        self._button("Назад", self._show_sign_in, row)
        row.addStretch(1)
        self._button("Выслать новый код", self._resend_code, row)
        self._button("Подтвердить", self._confirm_email, row, primary=True)
        layout.addLayout(row)
        self.pages.addWidget(page)
        return page

    def _make_preview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget(page)
        self.tree.setAccessibleName("Данные, ожидающие загрузки")
        self.tree.setObjectName("cloudPreview")
        self.tree.setHeaderHidden(True)
        self.tree.setMaximumHeight(278)
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        self._button("Назад", self._show_confirm, row)
        row.addStretch(1)
        self.preview_upload_button = self._button("Да", lambda: self._start(upload=True), row, primary=True)
        layout.addLayout(row)
        self.pages.addWidget(page)
        return page

    def _button(self, text: str, action, row: QHBoxLayout, *, primary: bool = False) -> HoverButton:
        button = HoverButton(text, self.card)
        button.setObjectName("primaryButton" if primary else "ghostButton")
        button.clicked.connect(action)
        row.addWidget(button)
        return button

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _show_confirm(self) -> None:
        self.password.clear()
        self.email_code.clear()
        self._set_status("")
        self.confirm_title.setText("Переместить все локальные данные в облако?")
        self.account_button.setVisible(self._session is None)
        self._show_page(self.confirm)
        self.no_button.setFocus()

    def _show_page(self, page: QWidget) -> None:
        for child in (self.confirm, self.preview, self.sign_in, self.verify_email, self.fetch_page):
            policy = QSizePolicy.Policy.Preferred if child is page else QSizePolicy.Policy.Ignored
            child.setSizePolicy(QSizePolicy.Policy.Preferred, policy)
        self.pages.setCurrentWidget(page)
        self.card.updateGeometry()

    def _show_sign_in(self) -> None:
        self.email_code.clear()
        self._set_status("")
        self._show_page(self.sign_in)
        self.email.setFocus()

    def _show_email_confirmation(self) -> None:
        email = self.email.text().strip()
        self.password.clear()
        self.email_code.clear()
        self._set_status("")
        self.code_recipient.setText(f"Введите код подтверждения из письма на {email}.")
        self._show_page(self.verify_email)
        self.email_code.setFocus()

    def _fit_parent(self) -> None:
        parent = self.parentWidget()
        self.setGeometry(QRect(parent.mapToGlobal(QPoint()), parent.size()))

    def _refit_if_visible(self) -> None:
        if self.isVisible():
            self._fit_parent()

    def open(self) -> None:
        if self.isVisible():
            return
        self._auth_only = False
        self._background = _make_blurred(self.parentWidget().grab())
        self._fit_parent()
        super().open()

    def open_sign_in(self) -> None:
        if self.isVisible():
            return
        self.open()
        self._auth_only = True
        self._action = "connect"
        self.confirm_title.setText("Вход в Music Rating")
        self._show_sign_in()

    def _back_from_sign_in(self) -> None:
        if self._auth_only:
            self.reject()
        else:
            self._show_confirm()

    def eventFilter(self, watched, event) -> bool:
        if (watched is self.parentWidget() and self.isVisible()
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.WindowStateChange)):
            self._fit_parent()
            QTimer.singleShot(0, self._refit_if_visible)
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._show_confirm()
        self._fit_parent()
        QTimer.singleShot(0, self._refit_if_visible)
        fade_in(self.card, 180)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._background = None

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self._background is not None:
            painter.drawPixmap(self.rect(), self._background)
        else:
            painter.fillRect(self.rect(), themed_color(BG_MAIN))
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

    def reject(self) -> None:
        if self._continuation is None:
            self.password.clear()
            self.email_code.clear()
            super().reject()

    def _run(self, status: str, operation, continuation, *, on_error=None) -> None:
        self._continuation = continuation
        self._failure_callback = on_error
        self.pages.setEnabled(False)
        self._set_status(status)
        finished = self._finished.emit

        def execute() -> None:
            try:
                result = operation()
            except CloudError as error:
                finished(None, error)
            except (OSError, ValueError, TypeError, KeyError, IndexError):
                finished(None, CloudError("Не удалось подготовить данные библиотеки."))
            else:
                finished(result, None)

        if self._polling:
            self._deferred_operation = execute
        else:
            QThreadPool.globalInstance().start(execute)

    def _on_finished(self, result, error) -> None:
        continuation, self._continuation = self._continuation, None
        failure_callback, self._failure_callback = self._failure_callback, None
        self.pages.setEnabled(True)
        if error is not None:
            if error.expired:
                self._save_session(None)
                self._set_members({})
                self.availability_changed.emit(False, str(error))
            if error.code == "email_not_confirmed":
                self._show_email_confirmation()
            if failure_callback is None:
                self._set_status(str(error))
            else:
                failure_callback(str(error))
            return
        self._set_status("")
        continuation(result)

    def _start(self, *, upload: bool) -> None:
        if self._continuation is not None:
            return
        self._carry_out_upload = upload
        self._action = "upload"
        if upload and self._session is None:
            self._show_sign_in()
            return
        previous = baseline(STORE)

        def prepare():
            if self._session is None:
                return snapshot_library(STORE), None, None, {}
            session = self._active_session()
            status = self._cloud.shared_status(session, download=True)
            pending, acknowledged, album_ids, sent_hashes = upload_plan(STORE, status, previous)
            if upload:
                self._cloud.shared_upload(session, pending)
                acknowledged.update(sent_hashes)
            mapped = {album_id: cloud_id for album_id, cloud_id in album_ids.items()
                      if f"album:{cloud_id}" in acknowledged}
            return pending, {**previous, **acknowledged}, status, mapped

        status = "Загружаем данные в Supabase…" if upload else "Готовим список данных…"
        self._run(status, prepare, self._prepared)

    def _prepared(self, result) -> None:
        items, acknowledged, status, album_ids = result
        if status is not None:
            self._set_members(member_names(status))
        if acknowledged is not None:
            try:
                STORE.record_cloud_upload(BASELINE, json.dumps(acknowledged), album_ids)
            except sqlite3.Error:
                self._set_status("Не удалось сохранить состояние облачной загрузки в локальной базе.")
                return
        if not self._carry_out_upload:
            self._show_preview(items, status is not None)
        else:
            self._show_preview([], status is not None)
            if items:
                self._set_status(f"Данные загружены. Записей в облаке обновлено: {len(items)}.")
            self.poll()

    def _show_preview(self, items, checked_online: bool) -> None:
        self.tree.clear()
        groups = (({"album"}, "Альбомы"), ({"artist"}, "Исполнители"), ({"rating", "summary"}, "Оценки альбомов"))
        for kinds, title in groups:
            labels = [item.label for item in items if item.kind in kinds]
            section = QTreeWidgetItem(self.tree, [f"{title} ({len(labels)})"])
            section.addChildren([QTreeWidgetItem([label]) for label in labels])
            section.setExpanded(bool(labels))
        self.preview_upload_button.setEnabled(bool(items))
        if not items:
            self._set_status("Нет данных, ожидающих загрузки.")
        elif not checked_online:
            self._set_status("Показаны локальные записи. Перед загрузкой проверим облако.")
        self._show_page(self.preview)

    def _authenticate(self, *, register: bool) -> None:
        if self._continuation is not None:
            return
        email, password = self.email.text().strip(), self.password.text()
        if "@" not in email or not password:
            self._set_status("Введите электронную почту и пароль.")
            return
        self.password.clear()
        self._run("Подключаемся к Supabase…",
                  lambda: self._cloud.authenticate(email, password, register=register),
                  self._registered if register else self._authenticated)

    def _registered(self, session: CloudSession | None) -> None:
        if session is None:
            self._show_email_confirmation()
            return
        self._account_ready(session, "Аккаунт создан. Нажмите «Да», чтобы начать загрузку.")

    def _authenticated(self, session: CloudSession) -> None:
        self._account_ready(session, "Вы вошли в облачный аккаунт.")
        if self._action == "upload":
            self._start(upload=True)

    def _account_ready(self, session: CloudSession, message: str) -> None:
        self._save_session(session)
        if self._auth_only:
            self.accept()
        else:
            self._show_confirm()
            self._set_status(message)
        QTimer.singleShot(0, self.poll)

    def _cloud_account(self) -> None:
        self._action = "connect"
        self._show_sign_in()

    def logout(self) -> None:
        if self._polling:
            self._deferred_operation = self._disconnect
        else:
            self._disconnect()

    def _disconnect(self) -> None:
        session = self._session
        self._save_session(None)
        self._set_members({})
        self.availability_changed.emit(False, "Войдите через кнопку профиля слева внизу.")
        self.sign_in_required.emit()
        if session is not None and session.access_token:
            def revoke() -> None:
                try:
                    self._cloud.sign_out(session)
                except CloudError:
                    pass

            QThreadPool.globalInstance().start(revoke)

    def _restore_session(self) -> None:
        key = _SESSION_KEY
        encrypted = self._settings.value(key, "", type=str)
        if not encrypted and not self._settings.value(_SESSION_MIGRATED_KEY, False, type=bool):
            key = f"CloudSession/{STORE.legacy_cloud_profile()}"
            if key != _SESSION_KEY:
                encrypted = self._settings.value(key, "", type=str)
        if encrypted:
            try:
                data = json.loads(unprotect_secret(encrypted))
                refresh = data["refresh_token"]
                if not isinstance(refresh, str) or not refresh:
                    raise ValueError
                self._session = CloudSession(str(UUID(data["user_id"])), "", refresh,
                                             email=data.get("email", ""), display_name=data.get("display_name", ""),
                                             created_at=data.get("created_at", ""))
                if key != _SESSION_KEY:
                    self._settings.setValue(_SESSION_KEY, encrypted)
                    self._settings.remove(key)
            except (OSError, TypeError, ValueError, KeyError):
                self._settings.remove(key)
        if not self._settings.value(_SESSION_MIGRATED_KEY, False, type=bool):
            self._settings.setValue(_SESSION_MIGRATED_KEY, True)
            self._settings.sync()

    def _save_session(self, session: CloudSession | None) -> None:
        previous_id = self._session.user_id if self._session is not None else None
        self._session = session
        if session is None or session.user_id != previous_id:
            self._set_members({})
        if session is None:
            self._settings.remove(_SESSION_KEY)
        elif session.refresh_token:
            try:
                data = json.dumps({"user_id": session.user_id, "refresh_token": session.refresh_token,
                                   "email": session.email, "display_name": session.display_name,
                                   "created_at": session.created_at})
                self._settings.setValue(_SESSION_KEY, protect_secret(data))
            except (OSError, ValueError):
                self._settings.remove(_SESSION_KEY)
        self._settings.sync()
        self.account_button.setVisible(session is None)
        self.session_changed.emit(session)

    def _active_session(self) -> CloudSession:
        session = self._session
        if session is None:
            raise CloudError("Войдите в облачный аккаунт.", expired=True)
        renewed = self._cloud.renew(session)
        if renewed is not session:
            self._session_refreshed.emit(renewed)
        return renewed

    def _set_members(self, members: dict[str, str]) -> None:
        if members != self._members:
            self._members = members
            self.members_changed.emit(members)

    def members(self) -> dict[str, str]:
        return dict(self._members)

    def rating_members(self) -> dict[str, str]:
        members = self.members()
        if self._session is not None and self._session.display_name:
            members[self._session.user_id] = self._session.display_name
        return members

    def update_display_name(self, display_name: str) -> None:
        if self._continuation is not None or self._deferred_operation is not None:
            self.display_name_finished.emit("Дождитесь окончания текущей операции и повторите попытку.")
            return

        def saved(session: CloudSession) -> None:
            self._save_session(session)
            self.display_name_finished.emit("")
            self.poll()

        self._run("Сохраняем имя…", lambda: self._cloud.update_display_name(self._active_session(), display_name),
                  saved, on_error=self.display_name_finished.emit)

    def catalog_session(self) -> CloudSession | None:
        return self._session

    def start_monitoring(self) -> None:
        self._poll_timer.start()
        self.poll()

    def poll(self) -> None:
        if self._polling or self._continuation is not None:
            return
        if self._session is None:
            return
        self._polling = True

        def check() -> None:
            try:
                status = self._cloud.shared_status(self._active_session())
                members = member_names(status)
            except CloudError as error:
                self._poll_finished.emit(None, error)
            else:
                self._poll_finished.emit((status, members), None)

        QThreadPool.globalInstance().start(check)

    def _on_polled(self, result, error) -> None:
        self._polling = False
        if error is not None:
            if error.expired:
                self._save_session(None)
                self._set_members({})
                self.sign_in_required.emit()
            elif error.code == "PT403":
                self._set_members({})
            self.availability_changed.emit(False, str(error))
            if self.isVisible() and self._action == "connect" and self._continuation is None:
                self._set_status(str(error))
        else:
            status, members = result
            self._set_members(members)
            changed = bool(status.get("has_data")) and status["revision"] != STORE.cloud_state(self._revision_key())
            self.availability_changed.emit(changed, "Скачать изменения из облака" if changed else "Библиотека актуальна.")
        operation, self._deferred_operation = self._deferred_operation, None
        if operation is not None:
            if self._continuation is None:
                operation()
            else:
                QThreadPool.globalInstance().start(operation)

    def _revision_key(self) -> str:
        return f"seen:{self._session.user_id}"

    def download(self) -> None:
        if self.isVisible() or self._session is None:
            return
        account_id = self._session.user_id
        self.open()
        if self._session is None or self._session.user_id != account_id:
            self.reject()
            self.poll()
            return
        self._action = "download"
        self.confirm_title.setText("Загрузка библиотеки из облака")
        self._show_page(self.fetch_page)
        previous = baseline(STORE)

        def prepare():
            session = self._active_session()
            status = self._cloud.shared_status(session, download=True)
            plan = download_plan(self._cloud, session, STORE, status, previous)
            return status, plan

        self._run("Скачиваем библиотеку и изображения…", prepare, self._downloaded)

    def _downloaded(self, result) -> None:
        status, (albums, artists, receipts, skipped) = result
        try:
            STORE.apply_cloud_library(albums, artists, {
                BASELINE: json.dumps(receipts), self._revision_key(): status["revision"],
            })
        except sqlite3.Error:
            self._set_status("Не удалось записать библиотеку в локальную базу. Повторите загрузку.")
            return
        self.accept()
        self._set_members(member_names(status))
        self.availability_changed.emit(False, "Библиотека актуальна.")
        self.library_downloaded.emit(skipped)
        self.poll()

    def _confirm_email(self) -> None:
        code = self.email_code.text().strip()
        if self._continuation is not None:
            return
        if len(code) < 6:
            self._set_status("Введите полный код из письма.")
            return
        email = self.email.text().strip()
        self._run("Подтверждаем почту…",
                  lambda: self._cloud.confirm_email(email, code),
                  lambda session: self._account_ready(session, "Почта подтверждена. Нажмите «Да», чтобы начать загрузку."))

    def _resend_code(self) -> None:
        if self._continuation is not None:
            return
        email = self.email.text().strip()

        def sent(_result) -> None:
            self.email_code.clear()
            self.email_code.setFocus()
            self._set_status("Запрошено новое письмо. Введите код из самого свежего письма.")

        self._run("Запрашиваем новый код…", lambda: self._cloud.resend_confirmation(email), sent)
