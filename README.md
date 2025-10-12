# PdfToImagesFunction (Yandex Cloud Function)

Асинхронная конвертация страниц PDF в изображения WebP и загрузка результатов в Object Storage (совместимый с S3). Реализовано согласно technical_specification.md.

## Возможности
- Вход: JSON с `pdf_key` и `output_prefix` (обязательные).
- Скачивание PDF из Object Storage в `/tmp`.
- Растеризация каждой страницы PDF с DPI=150 в WebP (качество ~85).
- Загрузка изображений по ключам `{output_prefix}page-{N}.webp`, где N начинается с 1.
- Создание и загрузка `manifest.json` с `{"page_count": N, "format": "webp"}`.
- Возврат JSON-ответа с `status: "success"`, `page_count`, `format`.
- Обработчики ошибок: 400 (валидация), 404 (нет исходного объекта), 500 (прочие ошибки).

## Среда выполнения
- Python 3.9+
- Память: ≥ 512 MB
- Тайм-аут: ≥ 60 секунд
- Привязка к сервисному аккаунту с ролью `storage.editor` для целевого бакета.

## Зависимости
Файл `requirements.txt`:
- boto3
- pypdfium2
- Pillow

## Переменные окружения
- `S3_BUCKET_NAME`: имя бакета Object Storage (например, `my-documents-bucket`)
- `S3_ENDPOINT_URL`: эндпоинт S3 (например, `https://storage.yandexcloud.net`)
- `AWS_ACCESS_KEY_ID`: ID статического ключа сервисного аккаунта
- `AWS_SECRET_ACCESS_KEY`: секретный ключ сервисного аккаунта
- `AWS_REGION`: регион (например, `ru-central1`)

## Входные данные (Event)
Пример (прямой вызов, non-HTTP):
```json
{
  "pdf_key": "path/to/document.pdf",
  "output_prefix": "converted/path/to/document.xlsx/"
}
```

Пример (HTTP-событие с телом):
```json
{
  "body": "{\"pdf_key\":\"path/to/document.pdf\",\"output_prefix\":\"converted/path/to/document.xlsx/\"}",
  "isBase64Encoded": false
}
```

Требования:
- `output_prefix` обязательно должен заканчиваться символом `/`.

## Выходные данные
Успех (HTTP 200):
```json
{
  "status": "success",
  "page_count": 5,
  "format": "webp"
}
```

Ошибка (HTTP 400/404/500):
```json
{
  "status": "error",
  "message": "Описание ошибки"
}
```

## Структура проекта
- `src/handler.py` — точка входа функции: `handler(event, context)`
- `requirements.txt` — список зависимостей
- `tests/local_invoke.py` — локальный запуск (см. ниже)

## Деплой в Yandex Cloud Functions (пример через CLI)
1) Создать функцию (однократно):
```
yc serverless function create --name pdf-to-images
```

2) Загрузить новую версию:
```
yc serverless function version create \
  --function-name pdf-to-images \
  --runtime python39 \
  --entrypoint src.handler.handler \
  --memory 512m \
  --execution-timeout 60s \
  --service-account-id <SERVICE_ACCOUNT_ID> \
  --environment S3_BUCKET_NAME=<BUCKET>,S3_ENDPOINT_URL=https://storage.yandexcloud.net,AWS_ACCESS_KEY_ID=<KEY_ID>,AWS_SECRET_ACCESS_KEY=<SECRET>,AWS_REGION=ru-central1 \
  --source-path . \
  --install-deps
```
Примечания:
- Укажите корректный `--service-account-id` с ролью `storage.editor` на бакет.
- Параметры памяти и тайм-аута можно увеличить при необходимости.
- `--install-deps` установит зависимости из `requirements.txt`.

3) Вызов функции:
```
yc serverless function invoke pdf-to-images \
  --data '{"pdf_key":"path/to/document.pdf","output_prefix":"converted/path/to/document.xlsx/"}'
```

## Локальный запуск (для отладки)
Скрипт `tests/local_invoke.py` позволяет локально вызвать `handler`:
- Требуются переменные окружения, как для боевого запуска (`S3_BUCKET_NAME`, `S3_ENDPOINT_URL`, `AWS_*`, `AWS_REGION`).
- Должен существовать доступ к Object Storage по указанным ключам.

Примеры:
```
# Прямой event
python -m tests.local_invoke \
  --pdf-key path/to/document.pdf \
  --output-prefix converted/path/to/document.xlsx/

# HTTP-подобный event
python -m tests.local_invoke \
  --pdf-key path/to/document.pdf \
  --output-prefix converted/path/to/document.xlsx/ \
  --http-event
```

Скрипт выведет HTTP-ответ (statusCode, headers, body).

## Логирование и ошибки
Функция логирует ключевые этапы: старт, скачивание PDF, обработка страниц, загрузку объектов, завершение.  
Обработчик исключений возвращает JSON-ошибки с соответствующим HTTP-кодом:
- 400 — валидационные ошибки входа/окружения;
- 404 — отсутствует исходный PDF-объект;
- 500 — ошибки S3 или неожиданные исключения.

## Примечания по производительности
- Растеризация ведётся постранично (ограничение потребления RAM).
- DPI=150 сбалансирован между качеством и размером изображений.
- Качество WebP по умолчанию 85 (можно изменить в коде при необходимости).
