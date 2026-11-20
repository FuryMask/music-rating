# Выпуск Music Rating для Windows

## 1. Собери EXE и установщик

Нужны Windows x64, Python 3.11 x64 и Inno Setup 6.3 или новее. Для Inno Setup 7 можно передать путь к компилятору через `-Iscc`. [Загрузка Inno Setup](https://jrsoftware.org/inno-setup/downloads)

Выполни эти команды в PowerShell из папки проекта.

```powershell
py -3.11 -m venv .venv
$python = (Resolve-Path .venv/Scripts/python.exe).Path
& $python -m pip install -r requirements.txt 'PyInstaller==6.17.0'
& ./packaging/build.ps1 -Python $python
```

Если `py` не видит Python, создай окружение через её `python.exe`. На этом компьютере подойдёт следующая команда.

```powershell
& "$env:LOCALAPPDATA/Programs/Python/Python311/python.exe" -m venv .venv
```

Если скрипт не нашёл Inno Setup, укажи путь к `ISCC.exe`. Для сборки только переносимого EXE передай `-AppOnly`.

```powershell
& ./packaging/build.ps1 -Python $python -Iscc 'C:/Program Files (x86)/Inno Setup 6/ISCC.exe'
```

В `dist/` появятся `MusicRating.exe` для прямого запуска и `MusicRating-Setup.exe` для установки и обновления. Первый установщик запускается вручную. По умолчанию он ставит приложение в `%LOCALAPPDATA%\Programs\Music Rating` для текущего пользователя. Для проверки исходников в этой рабочей копии можно запустить `& $python checks/run.py`.

## 2. Замени исходники старой версии в Git

Сделай свежий клон. `git rm` ниже подготавливает удаление старых файлов **в этом клоне**. История коммитов сохраняется. Просмотри список изменений перед коммитом.

```powershell
# Запускай из корня текущего проекта
$source = (Get-Location).Path
$upload = Join-Path (Split-Path -Parent $source) 'music-rating-release'
git clone https://github.com/FuryMask/music-rating.git $upload
git -C $upload switch -c release-1.0.0
git -C $upload rm -r -- .
foreach ($item in @('app','packaging','checks','.gitignore','main.py','requirements.txt','README.md','RELEASE.md')) {
    Copy-Item -LiteralPath (Join-Path $source $item) -Destination $upload -Recurse
}
git -C $upload add -- app packaging checks .gitignore main.py requirements.txt README.md RELEASE.md
git -C $upload diff --cached --name-status
git -C $upload commit -m 'Release Music Rating 1.0.0'
git -C $upload push -u origin release-1.0.0
```

На GitHub открой pull request в `main` и объедини его. База, обложки, резервные копии, ключи и бинарники в этот коммит не входят. Если ключ раньше был в Git или в выложенной сборке, отзови его у сервиса и выпусти новый. Для удаления старых копий секрета из истории потребуется отдельная очистка. [Удаление конфиденциальных данных из репозитория](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

## 3. Опубликуй первый релиз

1. В репозитории открой **Releases → Draft a new release**.
2. Создай тег `v1.0.0` от коммита новой версии в `main`.
3. Прикрепи `dist/MusicRating-Setup.exe` с исходным именем. Выбери стабильный выпуск и сделай его последним, если GitHub предлагает этот параметр. Нажми **Publish release**.
4. Установи `1.0.0` этим установщиком. Чтобы проверить появление кнопки обновления, выпусти `1.0.1` и запусти установленную `1.0.0`.

Релиз должен быть публично доступен. Music Rating проверяет последний стабильный релиз `FuryMask/music-rating` при старте и затем каждые четыре часа. Кнопка включается, когда тег новее установленной версии и GitHub отдаёт SHA-256 файла `MusicRating-Setup.exe`. После нажатия программа сверяет размер и SHA-256 загрузки и запускает установщик. [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), [API вложений релиза](https://docs.github.com/en/rest/releases/assets)

50 MiB — порог предупреждения для обычного файла в Git. GitHub блокирует обычные файлы свыше 100 MiB. Во вложения Releases можно загружать файлы размером **менее 2 GiB каждый**. Прикрепляй установщик к релизу. [Ограничения файлов в Git](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github), [Ограничения Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)

## 4. Выпускай обновления

1. Увеличь `VERSION` в `app/version.py`, например до `1.0.1`. Это число отображается слева снизу и сравнивается с тегом релиза.
2. Прогони проверки, пересобери установщик и отправь изменения исходников в `main`.
3. Создай релиз с тегом `v1.0.1` от того же коммита. Снова прикрепи `MusicRating-Setup.exe`.
4. Запусти прежнюю версию, нажми «Обновить» и пройди установку. После запуска проверь версию, профиль и содержимое библиотеки.

## Данные и ключи

- База находится в `Документы\Music Rating\library.db`, обложки — в подпапке `covers`. Если Windows перенаправила «Документы» в OneDrive или в другое место, используется эта папка. Сделать архив можно через «Профиль → Настройки → Экспорт базы». Установка и обновление работают в другой папке.
- При первом запуске с пустой базой открывается регистрация. Если профиль есть и сессия завершена, открывается вход. Активная сессия сохраняется между запусками. Профили локальные.
- Spotify хранит введённый Client Secret в защищённом Windows DPAPI файле `spotify_credentials.json` в папке данных. Файл ключей исключён из экспорта и Git. При необходимости ключи можно передать через `MUSICRATING_SPOTIFY_CLIENT_ID` и `MUSICRATING_SPOTIFY_CLIENT_SECRET`.
- Genius API использует ключ из защищённого Windows DPAPI файла `genius_credentials.json` в папке данных. Переменная `MUSICRATING_GENIUS_TOKEN` имеет приоритет. Без ключа приложение разбирает открытые страницы Genius. Сборка и экспорт базы не включают файл ключа.

Чтобы сохранить свой ключ локально на другом ПК или заменить его, выполни из папки исходников с установленными зависимостями. Ввод ключа скрыт.

```powershell
& $python -c "from getpass import getpass; from app.services.genius import save_access_token; save_access_token(getpass('Genius API token: '))"
```
